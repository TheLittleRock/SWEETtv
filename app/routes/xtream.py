import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from app.auth import authenticate_user
from app.config import config
from app.epg import get_cached_channels
from app.providers.manager import provider_manager
from app.routes.iptv import clean_id, get_effective_base_url
from app.stream import build_proxy_master_m3u8, resolve_epg_id_from_utc, safe_parse_timestamp

logger = logging.getLogger("SweetTV.Routes.Xtream")
router = APIRouter(tags=["Xtream Codes API"])


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
                "allowed_output_formats": ["m3u8", "ts"]
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

        data = get_cached_channels(need_epg=True)
        listings = []
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

    # 5. VOD & Series stubs
    if action in ("get_vod_categories", "get_vod_streams", "get_series_categories", "get_series"):
        return JSONResponse(content=[])

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
        target_cid = target_ch["id"] if target_ch else str(sid_int)

        stream_info = provider_manager.oneplay.get_stream_details(target_cid)
        if not stream_info or not stream_info.get("master_url"):
            raise HTTPException(status_code=502, detail="Failed to retrieve stream from Oneplay.")

        rewritten = provider_manager.oneplay.rewrite_manifest(stream_info["master_url"], base_url)
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
        target_cid = target_ch["id"] if target_ch else str(sid_int)

        stream_info = provider_manager.oneplay.get_stream_details(target_cid, utc_time=target_ts)
        if not stream_info or not stream_info.get("master_url"):
            raise HTTPException(status_code=502, detail="Failed to retrieve catchup stream from Oneplay.")

        rewritten = provider_manager.oneplay.rewrite_manifest(stream_info["master_url"], base_url)
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
