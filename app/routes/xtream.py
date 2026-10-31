import asyncio
import logging
import math
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
import requests

from app.auth import authenticate_user
from app.config import config
from app.drm.oneplay_wv import drm_manager
from app.drm.streamer import ffmpeg_stream_generator, find_ffmpeg_binary, prepare_dash_manifest
from app.epg import get_cached_channels
from app.providers.manager import provider_manager
from app.routes.iptv import clean_id, get_effective_base_url
from app.stream import build_proxy_master_m3u8, resolve_epg_id_from_utc, safe_parse_timestamp

logger = logging.getLogger("SweetTV.Routes.Xtream")
router = APIRouter(tags=["Xtream Codes API"])

_vod_cache_by_id: Dict[int, Dict[str, Any]] = {}
_series_cache_by_id: Dict[int, Dict[str, Any]] = {}
_series_info_cache: Dict[int, Tuple[float, Dict[str, Any]]] = {}
_vod_session_cache: Dict[int, Dict[str, Any]] = {}


def validate_xtream_user(username: Optional[str], password: Optional[str]) -> bool:
    """Validates Xtream Codes user credentials against SQLite and legacy fallback."""
    if not username or not password:
        return False
    user = authenticate_user(username.strip(), password.strip())
    if user and user.can_access():
        return True
    if username.strip() == config.xtream_user and password.strip() == config.xtream_password:
        return True
    return False


def _parse_timeshift_timestamp(start_str: str) -> Optional[int]:
    """Parses timeshift start parameter into a unix timestamp."""
    return safe_parse_timestamp(start_str)


@router.api_route("/player_api.php", methods=["GET", "POST"])
async def player_api(
    request: Request,
    username: Optional[str] = Query(None),
    password: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    stream_id: Optional[str] = Query(None),
    category_id: Optional[str] = Query(None),
    vod_id: Optional[str] = Query(None),
    series_id: Optional[str] = Query(None),
    limit: Optional[int] = Query(None)
):
    """
    Xtream Codes API v2 emulation endpoint.
    Compatible with IPTV clients, IPTV Smarters, TiviMate, OTT Navigator, XCIPTV.
    """
    # Accept params from form body if POST
    if request.method == "POST":
        try:
            form = await request.form()
            username = username or form.get("username")
            password = password or form.get("password")
            action = action or form.get("action")
            stream_id = stream_id or form.get("stream_id")
            category_id = category_id or form.get("category_id")
            vod_id = vod_id or form.get("vod_id")
            series_id = series_id or form.get("series_id")
            if form.get("limit") and not limit:
                limit = int(form.get("limit"))
        except Exception:
            pass

    valid_user = config.xtream_user
    valid_pwd = config.xtream_password

    # Validate against SQLite database or configured credentials
    if username is not None and password is not None:
        if not validate_xtream_user(username, password):
            logger.warning(f"Xtream authentication rejected for user '{username}'")
            return JSONResponse(content={"user_info": {"auth": 0}})

    user = username or valid_user
    pwd = password or valid_pwd

    base_url = get_effective_base_url(request)
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = str(parsed.port or (443 if parsed.scheme == "https" else 80))
    now = int(time.time())

    # 1. Handshake / Authentication check
    if not action:
        return JSONResponse(content={
            "user_info": {
                "username": user,
                "password": pwd,
                "message": "Sweet.tv IPTV Proxy Server",
                "auth": 1,
                "status": "Active",
                "exp_date": "1999999999",
                "is_trial": "0",
                "active_cons": "0",
                "created_at": "1600000000",
                "max_connections": "5",
                "allowed_output_formats": ["m3u8", "ts", "mp4"]
            },
            "server_info": {
                "url": host,
                "port": port,
                "https_port": "443" if parsed.scheme == "https" else port,
                "server_protocol": parsed.scheme,
                "rtmp_port": "8880",
                "timezone": "Europe/Prague",
                "timestamp_now": now,
                "time_now": time.strftime("%Y-%m-%d %H:%M:%S")
            }
        })

    # 2. Live categories
    if action == "get_live_categories":
        output = []
        # Sweet.tv categories
        data = get_cached_channels(need_epg=False)
        categories = data.get("categories", []) if data else []
        for c in categories:
            if c.get("id") != 1000:
                cid_val = c.get("id")
                caption_val = c.get("caption") or f"Category {cid_val}"
                output.append({
                    "category_id": str(cid_val),
                    "category_name": f"[Sweet] {caption_val}",
                    "parent_id": 0
                })
        # Oneplay categories
        if config.oneplay_enabled and config.is_oneplay_logged:
            output.append({"category_id": "2000", "category_name": "[Oneplay] TV Kanály", "parent_id": 0})
            output.append({"category_id": "2001", "category_name": "[Oneplay] Sport MD", "parent_id": 0})

        return JSONResponse(content=output)

    # 3. Live streams
    if action == "get_live_streams":
        all_channels = provider_manager.get_channels()
        output = []
        idx = 0
        for ch in all_channels:
            idx += 1
            cid = ch.get("id")
            provider = ch.get("provider")
            cname = ch.get("name") or f"Channel {cid}"
            chno = ch.get("channel_number", idx)

            if provider == "oneplay":
                stream_id_int = 10000 + int(chno)
                cat_id = "2001" if "MD" in cname else "2000"
            else:
                try:
                    stream_id_int = int(cid)
                except ValueError:
                    stream_id_int = idx
                cats = ch.get("raw", {}).get("category", [])
                cat_id = str(cats[0]) if cats else "1"

            if category_id and str(category_id) != cat_id:
                continue

            output.append({
                "num": idx,
                "name": cname,
                "stream_type": "live",
                "stream_id": stream_id_int,
                "stream_icon": ch.get("icon") or "",
                "epg_channel_id": f"{provider}:{cid}",
                "added": "1600000000",
                "category_id": cat_id,
                "custom_sid": "",
                "tv_archive": 1 if ch.get("catchup") else 0,
                "direct_source": "",
                "tv_archive_duration": int(ch.get("catchup_duration", 7) or 7)
            })
        return JSONResponse(content=output)

    # 4. EPG Schedule
    if action in ("get_simple_data_table", "get_short_epg"):
        if not stream_id:
            return JSONResponse(content={"epg_listings": []})

        try:
            target_cid = int(stream_id)
        except ValueError:
            return JSONResponse(content={"epg_listings": []})

        listings = []
        if target_cid >= 10000:
            if config.oneplay_enabled and config.is_oneplay_logged:
                op_channels = provider_manager.oneplay.get_channels()
                target_ch = next((c for c in op_channels if (10000 + int(c.get("channel_number", 0))) == target_cid), None)
                if target_ch:
                    raw_progs = provider_manager.oneplay.get_channel_epg(target_ch["id"])
                    for p in raw_progs:
                        t_start = p.get("start") or p.get("time_start") or p.get("startts") or 0
                        t_stop = p.get("stop") or p.get("time_stop") or p.get("endts") or 0
                        if not t_start or not t_stop:
                            continue
                        listings.append({
                            "id": str(p.get("id", "")),
                            "epg_id": str(p.get("id", "")),
                            "title": p.get("title", ""),
                            "lang": "cs",
                            "start": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t_start)),
                            "end": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t_stop)),
                            "description": p.get("description") or "",
                            "channel_id": str(target_cid),
                            "start_timestamp": t_start,
                            "stop_timestamp": t_stop,
                            "now_playing": 1 if t_start <= now < t_stop else 0,
                            "has_archive": 1 if p.get("can_replay") else 0
                        })
        else:
            data = get_cached_channels(need_epg=True)
            for ch in (data.get("list", []) if data else []):
                if ch.get("id") == target_cid:
                    has_catchup = bool(ch.get("catchup"))
                    for p in ch.get("epg", []):
                        t_start = p.get("time_start", 0)
                        t_stop = p.get("time_stop", 0)
                        if not t_start or not t_stop:
                            continue
                        listings.append({
                            "id": str(p.get("id", "")),
                            "epg_id": str(p.get("id", "")),
                            "title": p.get("text", ""),
                            "lang": "cs",
                            "start": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t_start)),
                            "end": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t_stop)),
                            "description": p.get("description") or p.get("genre") or "",
                            "channel_id": str(target_cid),
                            "start_timestamp": t_start,
                            "stop_timestamp": t_stop,
                            "now_playing": 1 if t_start <= now < t_stop else 0,
                            "has_archive": 1 if (has_catchup and p.get("available")) else 0
                        })
                    break

        if limit and limit > 0:
            listings = listings[:limit]

        return JSONResponse(content={"epg_listings": listings})

    # 5. VOD Categories
    if action == "get_vod_categories":
        return JSONResponse(content=[
            {"category_id": "3000", "category_name": "[Oneplay] Filmy", "parent_id": 0},
            {"category_id": "3001", "category_name": "[Oneplay] Nahrávky (Cloud DVR)", "parent_id": 0},
        ])

    # 6. VOD Streams
    if action == "get_vod_streams":
        vod_out = []
        if config.oneplay_enabled and config.is_oneplay_logged:
            cat_filter = str(category_id) if category_id else None
            items = []
            if cat_filter == "3001":
                items = provider_manager.oneplay.get_recordings()
            else:
                res = provider_manager.oneplay.get_vod_items(category="movies", page=1, all_pages=True)
                items = res.get("items") or []

            idx = 0
            for it in items:
                idx += 1
                sid = (31000 if cat_filter == "3001" else 30000) + idx
                _vod_cache_by_id[sid] = it
                title = it.get("title", "")
                if it.get("is_drm"):
                    title = f"{title} [DRM]"
                vod_out.append({
                    "num": idx,
                    "name": title,
                    "stream_type": "movie",
                    "stream_id": sid,
                    "stream_icon": it.get("image", ""),
                    "rating": "7.5",
                    "rating_5based": 3.75,
                    "added": "1600000000",
                    "category_id": cat_filter or "3000",
                    "container_extension": "m3u8",
                    "custom_sid": "",
                    "direct_source": ""
                })
        return JSONResponse(content=vod_out)

    # 7. VOD Info
    if action == "get_vod_info":
        try:
            eff_id = vod_id or stream_id
            vid = int(clean_id(str(eff_id))) if eff_id else 0
        except Exception:
            vid = 0

        item = _vod_cache_by_id.get(vid)
        if not item and config.oneplay_enabled and config.is_oneplay_logged:
            try:
                res_m = provider_manager.oneplay.get_vod_items(category="movies", page=1, all_pages=True)
                idx = 0
                for it in (res_m.get("items") or []):
                    idx += 1
                    _vod_cache_by_id[30000 + idx] = it
                res_r = provider_manager.oneplay.get_vod_items(category="recordings", page=1)
                idx = 0
                for it in (res_r.get("items") or []):
                    idx += 1
                    _vod_cache_by_id[31000 + idx] = it
                item = _vod_cache_by_id.get(vid)
            except Exception as e:
                logger.error(f"Error refreshing VOD cache for {vid}: {e}")

        name = item.get("title", f"Film {vid}") if item else f"Film {vid}"
        poster = item.get("image", "") if item else ""
        desc = item.get("description", "") if item else ""
        dur = item.get("duration") if item else None
        dur_int = int(dur) if dur is not None and str(dur).isdigit() else 7200
        h_dur = dur_int // 3600
        m_dur = (dur_int % 3600) // 60
        s_dur = dur_int % 60
        dur_str = f"{h_dur:02d}:{m_dur:02d}:{s_dur:02d}"
        year_val = str(item.get("year", "2024") if item else "2024")
        return JSONResponse(content={
            "info": {
                "name": name,
                "cover_big": poster,
                "movie_image": poster,
                "plot": desc,
                "cast": "",
                "director": "",
                "genre": "Oneplay",
                "release_date": year_val,
                "duration_secs": dur_int,
                "duration": dur_str,
                "video": {},
                "audio": {},
                "bitrate": 6000000,
                "filesize": int((dur_int * 6000000) / 8)
            },
            "movie_data": {
                "stream_id": vid,
                "name": name,
                "container_extension": "m3u8"
            }
        })

    # 8. Series Categories
    if action == "get_series_categories":
        return JSONResponse(content=[
            {"category_id": "4000", "category_name": "[Oneplay] Seriály", "parent_id": 0}
        ])

    # 9. Series List
    if action == "get_series":
        series_out = []
        if config.oneplay_enabled and config.is_oneplay_logged:
            try:
                res = provider_manager.oneplay.get_vod_items(category="series", page=1, all_pages=True)
                items = res.get("items") or []
                idx = 0
                for it in items:
                    idx += 1
                    sid = 40000 + idx
                    _series_cache_by_id[sid] = it
                    series_out.append({
                        "num": idx,
                        "name": it.get("title", ""),
                        "series_id": sid,
                        "cover": it.get("image", ""),
                        "plot": it.get("description", ""),
                        "cast": "",
                        "director": "",
                        "genre": "Seriál",
                        "releaseDate": str(it.get("year", "2024") or "2024"),
                        "last_modified": "1600000000",
                        "rating": "8.0",
                        "rating_5based": 4.0,
                        "category_id": "4000"
                    })
            except Exception as e:
                logger.error(f"Error fetching series in get_series: {e}")
        return JSONResponse(content=series_out)

    # 10. Series Info (Seasons & Episodes)
    if action == "get_series_info":
        try:
            eff_sid = series_id or stream_id
            sid = int(clean_id(str(eff_sid))) if eff_sid else 0
        except Exception:
            sid = 0

        # Check in-memory series info cache (1h TTL) to avoid long re-fetches and client timeouts
        now_ts = time.time()
        cached_info = _series_info_cache.get(sid)
        if cached_info and (now_ts - cached_info[0]) < 3600:
            return JSONResponse(content=cached_info[1])

        s_item = _series_cache_by_id.get(sid)
        if (not s_item or not s_item.get("payload")) and config.oneplay_enabled and config.is_oneplay_logged:
            try:
                res = provider_manager.oneplay.get_vod_items(category="series", page=1, all_pages=True)
                idx = 0
                for it in (res.get("items") or []):
                    idx += 1
                    _series_cache_by_id[40000 + idx] = it
                s_item = _series_cache_by_id.get(sid)
            except Exception as e:
                logger.error(f"Error refreshing series cache in get_series_info for {sid}: {e}")

        if not s_item or not s_item.get("payload"):
            return JSONResponse(content={"seasons": [], "info": {}, "episodes": {}})

        try:
            detail = provider_manager.oneplay.get_series_detail(s_item["payload"])
        except Exception as e:
            logger.error(f"Error getting series detail for {sid}: {e}")
            detail = {}

        seasons_meta = []
        episodes_map: Dict[str, List[Dict[str, Any]]] = {}

        seasons = detail.get("seasons") or []
        if seasons:
            def _fetch_season_task(item_tuple):
                s_num, season = item_tuple
                s_key = str(s_num)
                meta = {
                    "season_number": s_num,
                    "name": season.get("label", f"{s_num}. série"),
                    "episode_count": 0,
                    "id": s_num,
                    "air_date": "2024"
                }
                try:
                    eps = provider_manager.oneplay.get_season_episodes(season["carouselId"], season["criteria"])
                except Exception as e:
                    logger.error(f"Error fetching season episodes in get_series_info for {season}: {e}")
                    eps = []
                meta["episode_count"] = len(eps)
                ep_list = []
                ep_num = 0
                for ep in eps:
                    ep_num += 1
                    # Globally unique episode ID: sid * 1000000 + season * 1000 + ep_num
                    ep_sid = (sid * 1000000) + (s_num * 1000) + ep_num
                    _vod_cache_by_id[ep_sid] = ep
                    dur_ep = ep.get("duration")
                    dur_ep_int = int(dur_ep) if dur_ep is not None and str(dur_ep).isdigit() else 3000
                    h_ep = dur_ep_int // 3600
                    m_ep = (dur_ep_int % 3600) // 60
                    s_ep = dur_ep_int % 60
                    dur_ep_str = f"{h_ep:02d}:{m_ep:02d}:{s_ep:02d}"
                    ep_list.append({
                        "id": ep_sid,
                        "episode_num": ep_num,
                        "title": ep.get("title", f"Díl {ep_num}"),
                        "container_extension": "m3u8",
                        "info": {
                            "name": ep.get("title", ""),
                            "plot": ep.get("description", ""),
                            "duration_secs": dur_ep_int,
                            "duration": dur_ep_str,
                            "movie_image": ep.get("image", ""),
                            "bitrate": 6000000,
                            "filesize": int((dur_ep_int * 6000000) / 8)
                        }
                    })
                return s_num, meta, s_key, ep_list

            # Fetch seasons concurrently with ThreadPoolExecutor
            indexed_seasons = list(enumerate(seasons, start=1))
            with ThreadPoolExecutor(max_workers=min(8, len(indexed_seasons))) as executor:
                results = list(executor.map(_fetch_season_task, indexed_seasons))

            # Sort by season number
            results.sort(key=lambda r: r[0])
            for _, meta, s_key, ep_list in results:
                seasons_meta.append(meta)
                episodes_map[s_key] = ep_list

        elif detail.get("episodes"):
            # Direct episodes
            seasons_meta.append({"season_number": 1, "name": "1. série", "episode_count": len(detail["episodes"]), "id": 1, "air_date": "2024"})
            ep_list = []
            ep_num = 0
            for ep in detail["episodes"]:
                ep_num += 1
                ep_sid = (sid * 1000000) + 1000 + ep_num
                _vod_cache_by_id[ep_sid] = ep
                dur_ep = ep.get("duration")
                dur_ep_int = int(dur_ep) if dur_ep is not None and str(dur_ep).isdigit() else 3000
                h_ep = dur_ep_int // 3600
                m_ep = (dur_ep_int % 3600) // 60
                s_ep = dur_ep_int % 60
                dur_ep_str = f"{h_ep:02d}:{m_ep:02d}:{s_ep:02d}"
                ep_list.append({
                    "id": ep_sid,
                    "episode_num": ep_num,
                    "title": ep.get("title", f"Díl {ep_num}"),
                    "container_extension": "m3u8",
                    "info": {
                        "name": ep.get("title", ""),
                        "plot": ep.get("description", ""),
                        "duration_secs": dur_ep_int,
                        "duration": dur_ep_str,
                        "movie_image": ep.get("image", ""),
                        "bitrate": 6000000,
                        "filesize": int((dur_ep_int * 6000000) / 8)
                    }
                })
            episodes_map["1"] = ep_list

        result_payload = {
            "seasons": seasons_meta,
            "info": {
                "name": detail.get("title", s_item.get("title")),
                "cover": detail.get("image", s_item.get("image")),
                "plot": detail.get("description", s_item.get("description")),
                "genre": "Seriál",
                "releaseDate": str(detail.get("year", "2024") or "2024"),
                "rating": "8.0",
                "rating_5based": 4.0
            },
            "episodes": episodes_map
        }
        _series_info_cache[sid] = (now_ts, result_payload)
        return JSONResponse(content=result_payload)

    return JSONResponse(content={"message": f"Action {action} not handled", "status": "OK"})


@router.get("/live/{username}/{password}/{stream_id}.m3u8", response_class=Response)
@router.get("/live/{username}/{password}/{stream_id}.ts", response_class=Response)
@router.get("/live/{username}/{password}/{stream_id}", response_class=Response)
def xtream_live_stream(
    request: Request,
    username: str,
    password: str,
    stream_id: str,
    quality: Optional[str] = Query(None)
):
    """Handles Xtream live stream playback for Sweet.tv and Oneplay."""
    if not validate_xtream_user(username, password):
        raise HTTPException(status_code=401, detail="Invalid Xtream credentials.")

    try:
        sid_int = int(clean_id(stream_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid stream ID.")

    base_url = get_effective_base_url(request)

    # Oneplay streams are mapped to stream_id >= 10000
    if sid_int >= 10000:
        if not (config.oneplay_enabled and config.is_oneplay_logged):
            raise HTTPException(status_code=401, detail="Oneplay is not logged in.")
        # Find Oneplay channel matching stream_id
        op_channels = provider_manager.oneplay.get_channels()
        target_ch = next((c for c in op_channels if (10000 + int(c.get("channel_number", 0))) == sid_int), None)
        if not target_ch:
            target_ch = next((c for c in op_channels if str(c.get("id")) == str(sid_int) or str(c.get("channel_number")) == str(sid_int)), None)
        target_cid = target_ch["id"] if target_ch else str(sid_int - 10000 if sid_int > 10000 else sid_int)

        stream_info = provider_manager.oneplay.get_stream_details(target_cid)
        if not stream_info or not stream_info.get("master_url"):
            raise HTTPException(status_code=502, detail="Failed to retrieve stream from Oneplay.")

        rewritten = provider_manager.oneplay.rewrite_manifest(stream_info["master_url"], base_url, start_at_begin=False)
        return Response(
            content=rewritten,
            media_type="application/vnd.apple.mpegurl",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "no-cache, no-store, must-revalidate",
            }
        )

    # Sweet.tv stream
    if not config.is_logged:
        raise HTTPException(status_code=401, detail="Sweet.tv login required.")

    content, media_type = build_proxy_master_m3u8(
        channel_id=sid_int,
        base_url=base_url,
        quality=quality or config.default_quality
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        }
    )


@router.get("/timeshift/{username}/{password}/{duration}/{start}/{stream_id}.m3u8", response_class=Response)
@router.get("/timeshift/{username}/{password}/{duration}/{start}/{stream_id}.ts", response_class=Response)
@router.get("/timeshift/{username}/{password}/{duration}/{start}/{stream_id}", response_class=Response)
@router.get("/streaming/timeshift.php", response_class=Response)
def xtream_timeshift_stream(
    request: Request,
    username: Optional[str] = None,
    password: Optional[str] = None,
    stream_id: Optional[str] = None,
    start: Optional[str] = None,
    duration: Optional[int] = None,
    quality: Optional[str] = Query(None),
    stream: Optional[str] = Query(None)
):
    """Handles Xtream timeshift (catchup archive) playback for Sweet.tv and Oneplay."""
    u = username or request.query_params.get("username")
    p = password or request.query_params.get("password")
    if u and p and not validate_xtream_user(u, p):
        raise HTTPException(status_code=401, detail="Invalid Xtream credentials.")

    raw_id = stream_id or stream or request.query_params.get("stream_id")
    if not raw_id:
        raise HTTPException(status_code=400, detail="Missing stream ID.")

    try:
        sid_int = int(clean_id(str(raw_id)))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid stream ID.")

    start_val = start or request.query_params.get("start")
    target_ts = _parse_timeshift_timestamp(start_val) if start_val else None
    base_url = get_effective_base_url(request)

    # Oneplay streams are mapped to stream_id >= 10000
    if sid_int >= 10000:
        if not (config.oneplay_enabled and config.is_oneplay_logged):
            raise HTTPException(status_code=401, detail="Oneplay is not logged in.")
        op_channels = provider_manager.oneplay.get_channels()
        target_ch = next((c for c in op_channels if (10000 + int(c.get("channel_number", 0))) == sid_int), None)
        if not target_ch:
            target_ch = next((c for c in op_channels if str(c.get("id")) == str(sid_int) or str(c.get("channel_number")) == str(sid_int)), None)
        target_cid = target_ch["id"] if target_ch else str(sid_int - 10000 if sid_int > 10000 else sid_int)

        stream_info = provider_manager.oneplay.get_stream_details(target_cid, utc_time=target_ts)
        if not stream_info or not stream_info.get("master_url"):
            raise HTTPException(status_code=502, detail="Failed to retrieve catchup stream from Oneplay.")

        rewritten = provider_manager.oneplay.rewrite_manifest(stream_info["master_url"], base_url, start_at_begin=True)
        return Response(
            content=rewritten,
            media_type="application/vnd.apple.mpegurl",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "no-cache, no-store, must-revalidate",
            }
        )

    # Sweet.tv stream
    if not config.is_logged:
        raise HTTPException(status_code=401, detail="Sweet.tv login required.")

    target_epg_id = None
    if target_ts:
        target_epg_id = resolve_epg_id_from_utc(sid_int, target_ts)

    content, media_type = build_proxy_master_m3u8(
        channel_id=sid_int,
        base_url=base_url,
        epg_id=target_epg_id,
        quality=quality or config.default_quality
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        }
    )


@router.api_route("/xmltv.php", methods=["GET"])
def xtream_xmltv(
    request: Request,
    username: Optional[str] = Query(None),
    password: Optional[str] = Query(None)
):
    """Universal XMLTV EPG endpoint for Xtream Codes IPTV players."""
    if username and password and not validate_xtream_user(username, password):
        raise HTTPException(status_code=401, detail="Invalid Xtream credentials.")
    xml_content = provider_manager.generate_xmltv_epg()
    return Response(
        content=xml_content,
        media_type="text/xml; charset=utf-8",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Content-Disposition": 'inline; filename="epg.xml"',
            "Cache-Control": "public, max-age=1800"
        }
    )


# =========================================================================
# XTREAM CODES VOD & SERIES PLAYBACK ENDPOINTS
# =========================================================================

@router.api_route("/movie/{username}/{password}/{stream_id}.m3u8", methods=["GET", "HEAD"])
@router.api_route("/movie/{username}/{password}/{stream_id}.ts", methods=["GET", "HEAD"])
@router.api_route("/movie/{username}/{password}/{stream_id}.mp4", methods=["GET", "HEAD"])
@router.api_route("/movie/{username}/{password}/{stream_id}", methods=["GET", "HEAD"])
async def xtream_movie_stream(
    request: Request,
    username: str,
    password: str,
    stream_id: str
):
    """Playback endpoint for Xtream Codes VOD movies, series episodes, and recordings."""
    if not validate_xtream_user(username, password):
        raise HTTPException(status_code=401, detail="Invalid Xtream credentials.")

    try:
        sid_int = int(clean_id(stream_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid stream ID.")

    url_path = request.url.path.lower()
    is_m3u8 = url_path.endswith(".m3u8")
    is_mp4 = url_path.endswith(".mp4")
    out_format = "mp4" if is_mp4 else "ts"
    media_type = "video/mp4" if is_mp4 else ("application/vnd.apple.mpegurl" if is_m3u8 else "video/mp2t")
    file_ext = "mp4" if is_mp4 else ("m3u8" if is_m3u8 else "ts")

    item = _vod_cache_by_id.get(sid_int)
    if not item or not item.get("payload"):
        # Auto-reload VOD cache if expired or missing
        if config.oneplay_enabled and config.is_oneplay_logged:
            try:
                # Check if this is a series episode (sid_int >= 40000000 or legacy sid_int >= 400000)
                if sid_int >= 40000000:
                    series_base_id = sid_int // 1000000
                elif sid_int >= 400000:
                    series_base_id = sid_int // 100
                else:
                    series_base_id = None

                if series_base_id:
                    s_item = _series_cache_by_id.get(series_base_id)
                    if not s_item or not s_item.get("payload"):
                        res_s = provider_manager.oneplay.get_vod_items(category="series", page=1, all_pages=True)
                        idx = 0
                        for it in (res_s.get("items") or []):
                            idx += 1
                            _series_cache_by_id[40000 + idx] = it
                        s_item = _series_cache_by_id.get(series_base_id)
                    if s_item and s_item.get("payload"):
                        detail = provider_manager.oneplay.get_series_detail(s_item["payload"])
                        s_num = 0
                        for season in (detail.get("seasons") or []):
                            s_num += 1
                            eps = provider_manager.oneplay.get_season_episodes(season["carouselId"], season["criteria"])
                            ep_idx = 0
                            for ep in eps:
                                ep_idx += 1
                                _vod_cache_by_id[(series_base_id * 1000000) + (s_num * 1000) + ep_idx] = ep
                                _vod_cache_by_id[(series_base_id * 100) + ep_idx] = ep  # Legacy compatibility
                        for ep_idx, ep in enumerate(detail.get("episodes") or []):
                            _vod_cache_by_id[(series_base_id * 1000000) + 1000 + (ep_idx + 1)] = ep
                            _vod_cache_by_id[(series_base_id * 100) + (ep_idx + 1)] = ep
                else:
                    res_m = provider_manager.oneplay.get_vod_items(category="movies", page=1, all_pages=True)
                    idx = 0
                    for it in (res_m.get("items") or []):
                        idx += 1
                        _vod_cache_by_id[30000 + idx] = it
                    res_r = provider_manager.oneplay.get_vod_items(category="recordings", page=1, all_pages=True)
                    idx = 0
                    for it in (res_r.get("items") or []):
                        idx += 1
                        _vod_cache_by_id[31000 + idx] = it
            except Exception as e:
                logger.error(f"Error auto-reloading VOD cache for {sid_int}: {e}")
        item = _vod_cache_by_id.get(sid_int)

    dur_val = item.get("duration") if item else 0
    try:
        duration_sec = float(dur_val) if dur_val is not None else 0.0
    except Exception:
        duration_sec = 0.0

    bytes_per_sec = 820_000 if out_format == "ts" else 775_000
    total_bytes = int(duration_sec * bytes_per_sec) if duration_sec > 0 else 2_500_000_000

    # Fast probe response for HEAD requests from IPTV players (e.g. VLC, TiviMate, IPTVnator)
    if request.method == "HEAD":
        head_headers = {
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Content-Disposition": f'inline; filename="vod_{sid_int}.{file_ext}"',
            "Accept-Ranges": "none",
        }
        if duration_sec > 0:
            head_headers["X-Content-Duration"] = str(int(duration_sec))
            head_headers["Content-Duration"] = str(int(duration_sec))
        return Response(
            status_code=200,
            media_type=media_type,
            headers=head_headers
        )

    if not item or not item.get("payload"):
        raise HTTPException(status_code=404, detail="VOD item not found or expired.")

    stream_info = provider_manager.oneplay.get_vod_stream(item["payload"])
    if not stream_info or not stream_info.get("url"):
        raise HTTPException(status_code=502, detail="Failed to resolve VOD stream from Oneplay.")

    manifest_type = stream_info.get("manifest_type")
    stream_url = stream_info.get("url")
    is_drm = bool(stream_info.get("is_drm"))

    # 1. Clear HLS stream -> manifest rewrite with Oneplay CDN tokens
    if manifest_type == "hls" and not is_drm:
        base_url = get_effective_base_url(request)
        rewritten = provider_manager.oneplay.rewrite_manifest(stream_url, base_url, start_at_begin=False)
        return Response(
            content=rewritten,
            media_type="application/vnd.apple.mpegurl",
            headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-cache"}
        )

    # 2. HLS playlist request for DASH/DRM VOD -> generate standard HLS VOD playlist
    if is_m3u8:
        base_url = get_effective_base_url(request)
        seg_duration = 10.0
        total_dur = duration_sec if duration_sec > 0 else 7200.0
        num_segs = max(1, int(math.ceil(total_dur / seg_duration)))
        lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:3",
            f"#EXT-X-TARGETDURATION:{int(seg_duration) + 1}",
            "#EXT-X-MEDIA-SEQUENCE:0",
            "#EXT-X-PLAYLIST-TYPE:VOD",
        ]
        for seg_idx in range(num_segs):
            cur_start = seg_idx * seg_duration
            cur_dur = min(seg_duration, total_dur - cur_start)
            lines.append(f"#EXTINF:{cur_dur:.3f},")
            lines.append(f"{base_url}/vod_segment/{username}/{password}/{sid_int}/{int(cur_start)}.ts")
        lines.append("#EXT-X-ENDLIST\n")
        return Response(
            content="\n".join(lines),
            media_type="application/vnd.apple.mpegurl",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "public, max-age=3600"
            }
        )

    # 3. Direct MPEG-TS or fragmented MP4 streaming via FFmpeg
    start_param = request.query_params.get("start") or request.query_params.get("t")
    start_sec = 0.0
    if start_param:
        try:
            start_sec = max(0.0, float(start_param))
        except ValueError:
            pass

    decryption_keys = []
    if is_drm:
        drm_meta = stream_info.get("drm") or {}
        token_val = drm_meta.get("token") or ""
        lic_url = drm_meta.get("license_url")
        try:
            h = {
                "User-Agent": provider_manager.oneplay.api.ua,
                "Referer": "https://www.oneplay.cz/",
                "Origin": "https://www.oneplay.cz"
            }
            r_mpd = requests.get(stream_url, headers=h, timeout=10)
            if r_mpd.status_code == 200:
                pssh = drm_manager.extract_pssh_from_mpd(r_mpd.text, base_url=stream_url)
                if pssh:
                    keys = drm_manager.get_decryption_keys(pssh, token_val, license_url=lic_url)
                    decryption_keys = [k[1] for k in keys if k and len(k) > 1 and k[1]]
                    logger.info(f"Derived {len(decryption_keys)} decryption key(s) for VOD stream {sid_int}")
                else:
                    logger.warning(f"Could not extract PSSH from MPD manifest for VOD {sid_int}")
            else:
                logger.error(f"Failed to fetch MPD manifest (HTTP {r_mpd.status_code}) for VOD {sid_int}")
        except Exception as e:
            logger.error(f"Error acquiring DRM keys for VOD stream {sid_int}: {e}")

    headers_dict = {
        "User-Agent": provider_manager.oneplay.api.ua,
        "Referer": "https://www.oneplay.cz/"
    }
    generator = ffmpeg_stream_generator(
        stream_url=stream_url,
        decryption_keys=decryption_keys,
        headers=headers_dict,
        output_format=out_format,
        duration_secs=duration_sec,
        start_time=start_sec,
        chunk_size=524288
    )
    resp_headers = {
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Content-Disposition": f'inline; filename="vod_{sid_int}.{file_ext}"',
        "Accept-Ranges": "none",
    }
    if duration_sec > 0:
        resp_headers["X-Content-Duration"] = str(int(duration_sec))
        resp_headers["Content-Duration"] = str(int(duration_sec))

    return StreamingResponse(
        content=generator,
        status_code=200,
        media_type=media_type,
        headers=resp_headers
    )


@router.api_route("/vod_segment/{username}/{password}/{stream_id}/{start_sec}.ts", methods=["GET", "HEAD"])
async def xtream_vod_segment(
    request: Request,
    username: str,
    password: str,
    stream_id: str,
    start_sec: int
):
    """Generates an individual 10-second MPEG-TS segment for HLS VOD playback."""
    if not validate_xtream_user(username, password):
        raise HTTPException(status_code=401, detail="Invalid Xtream credentials.")

    if request.method == "HEAD":
        return Response(
            status_code=200,
            media_type="video/mp2t",
            headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=86400"}
        )

    try:
        sid_int = int(clean_id(stream_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid stream ID.")

    now = time.time()
    session = _vod_session_cache.get(sid_int)
    if not session or session.get("expiry", 0) < now or not os.path.exists(session.get("mpd_path", "")):
        item = _vod_cache_by_id.get(sid_int)
        if not item or not item.get("payload"):
            raise HTTPException(status_code=404, detail="VOD item not found.")

        stream_info = provider_manager.oneplay.get_vod_stream(item["payload"])
        if not stream_info or not stream_info.get("url"):
            raise HTTPException(status_code=502, detail="Failed to resolve VOD stream.")

        stream_url = stream_info.get("url")
        is_drm = bool(stream_info.get("is_drm"))
        decryption_keys = []
        if is_drm:
            drm_meta = stream_info.get("drm") or {}
            token_val = drm_meta.get("token") or ""
            lic_url = drm_meta.get("license_url")
            h = {"User-Agent": provider_manager.oneplay.api.ua, "Referer": "https://www.oneplay.cz/", "Origin": "https://www.oneplay.cz"}
            r_mpd = requests.get(stream_url, headers=h, timeout=10)
            if r_mpd.status_code == 200:
                pssh = drm_manager.extract_pssh_from_mpd(r_mpd.text, base_url=stream_url)
                if pssh:
                    keys = drm_manager.get_decryption_keys(pssh, token_val, license_url=lic_url)
                    decryption_keys = [k[1] for k in keys if k and len(k) > 1 and k[1]]

        h = {"User-Agent": provider_manager.oneplay.api.ua, "Referer": "https://www.oneplay.cz/"}
        r_mpd = requests.get(stream_url, headers=h, timeout=10)
        rewritten, _, _, _ = prepare_dash_manifest(r_mpd.text, stream_url)
        fd, temp_mpd_path = tempfile.mkstemp(suffix=".mpd", prefix="vod_dash_seg_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(rewritten)

        # Evict old sessions if cache grows large
        if len(_vod_session_cache) > 10:
            oldest_sid = min(_vod_session_cache, key=lambda k: _vod_session_cache[k].get("expiry", 0))
            old_s = _vod_session_cache.pop(oldest_sid, None)
            if old_s and old_s.get("mpd_path") and os.path.exists(old_s["mpd_path"]):
                try:
                    os.remove(old_s["mpd_path"])
                except Exception:
                    pass

        session = {
            "mpd_path": temp_mpd_path,
            "keys": decryption_keys,
            "expiry": now + 7200
        }
        _vod_session_cache[sid_int] = session

    ffmpeg_bin = find_ffmpeg_binary()
    if not ffmpeg_bin:
        raise HTTPException(status_code=500, detail="FFmpeg binary not found.")

    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel", "warning",
        "-ss", str(start_sec),
        "-allowed_extensions", "ALL",
        "-protocol_whitelist", "file,crypto,data,https,tls,tcp",
    ]
    if session.get("keys"):
        cmd.extend(["-cenc_decryption_key", session["keys"][0]])
    cmd.extend([
        "-i", session["mpd_path"],
        "-map", "0:v:0",
        "-map", "0:a?",
        "-c:v", "copy",
        "-c:a", "copy",
        "-t", "10",
        "-output_ts_offset", str(start_sec),
        "-f", "mpegts",
        "pipe:1"
    ])
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    return Response(
        content=stdout,
        media_type="video/mp2t",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=86400"
        }
    )


@router.api_route("/series/{username}/{password}/{stream_id}.m3u8", methods=["GET", "HEAD"])
@router.api_route("/series/{username}/{password}/{stream_id}.ts", methods=["GET", "HEAD"])
@router.api_route("/series/{username}/{password}/{stream_id}.mp4", methods=["GET", "HEAD"])
@router.api_route("/series/{username}/{password}/{stream_id}", methods=["GET", "HEAD"])
async def xtream_series_stream(
    request: Request,
    username: str,
    password: str,
    stream_id: str
):
    """Playback endpoint for Xtream Codes TV series episodes."""
    return await xtream_movie_stream(request, username, password, stream_id)

