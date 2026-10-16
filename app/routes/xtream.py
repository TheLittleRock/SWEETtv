import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from app.config import config
from app.epg import get_cached_channels
from app.routes.iptv import clean_id, get_effective_base_url
from app.stream import build_proxy_master_m3u8, resolve_epg_id_from_utc

logger = logging.getLogger("SweetTV.Routes.Xtream")
router = APIRouter(tags=["Xtream Codes API"])


def _parse_timeshift_timestamp(start_str: str) -> Optional[int]:
    """Parses timeshift start parameter into a unix timestamp."""
    if not start_str:
        return None
    start_clean = str(start_str).strip()
    if start_clean.isdigit():
        return int(start_clean)
    for fmt in ("%Y-%m-%d:%H-%M", "%Y-%m-%d-%H-%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(start_clean, fmt)
            return int(dt.timestamp())
        except ValueError:
            continue
    return None


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

    # If explicit credentials were submitted, validate against configured credentials
    if username is not None and password is not None:
        if username.strip() != valid_user or password.strip() != valid_pwd:
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
        data = get_cached_channels(need_epg=False)
        categories = data.get("categories", []) if data else []
        output = [
            {
                "category_id": str(c.get("id")),
                "category_name": c.get("caption", f"Category {c.get('id')}"),
                "parent_id": 0
            }
            for c in categories if c.get("id") != 1000
        ]
        return JSONResponse(content=output)

    # 3. Live streams
    if action == "get_live_streams":
        data = get_cached_channels(need_epg=False)
        channels = data.get("list", []) if data else []
        output = []
        idx = 0
        for ch in channels:
            if not ch.get("available"):
                continue
            idx += 1
            cid = ch.get("id")
            cats = ch.get("category", [])
            primary_cat = str(cats[0]) if cats else "1"
            if category_id and str(category_id) != primary_cat:
                continue

            output.append({
                "num": idx,
                "name": ch.get("name") or f"Channel {cid}",
                "stream_type": "live",
                "stream_id": cid,
                "stream_icon": ch.get("icon_v2_url") or ch.get("icon_url") or "",
                "epg_channel_id": str(cid),
                "added": "1600000000",
                "category_id": primary_cat,
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
    """Handles Xtream live stream playback."""
    if not config.is_logged:
        raise HTTPException(status_code=401, detail="Sweet.tv login required.")

    cid = clean_id(stream_id)
    base_url = get_effective_base_url(request)
    content, media_type = build_proxy_master_m3u8(
        channel_id=cid,
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
    stream_id: Optional[str] = None,
    start: Optional[str] = None,
    duration: Optional[int] = None,
    quality: Optional[str] = Query(None),
    stream: Optional[str] = Query(None)
):
    """Handles Xtream timeshift (catchup archive) playback."""
    if not config.is_logged:
        raise HTTPException(status_code=401, detail="Sweet.tv login required.")

    raw_id = stream_id or stream or request.query_params.get("stream_id")
    if not raw_id:
        raise HTTPException(status_code=400, detail="Missing stream ID.")

    cid = clean_id(str(raw_id))
    start_val = start or request.query_params.get("start")
    target_ts = _parse_timeshift_timestamp(start_val) if start_val else None

    target_epg_id = None
    if target_ts:
        target_epg_id = resolve_epg_id_from_utc(cid, target_ts)

    base_url = get_effective_base_url(request)
    content, media_type = build_proxy_master_m3u8(
        channel_id=cid,
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
