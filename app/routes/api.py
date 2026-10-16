import logging
import time
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.client import client
from app.config import config
from app.epg import get_cached_channels, invalidate_cache
from app.stream import get_stream_details
from app.version import APP_NAME, APP_VERSION

logger = logging.getLogger("SweetTV.Routes.API")
router = APIRouter(prefix="/api", tags=["API"])

SERVER_START_TIME = time.time()


class SettingsUpdate(BaseModel):
    countryCode: Optional[str] = None
    external_url: Optional[str] = None
    default_quality: Optional[str] = None
    direct_redirect: Optional[bool] = None
    m3u_catchup: Optional[bool] = None


@router.get("/version")
def get_version() -> Dict[str, Any]:
    """Returns application version and build info."""
    return {
        "version": APP_VERSION,
        "name": APP_NAME,
        "uptime_seconds": int(time.time() - SERVER_START_TIME)
    }


@router.get("/status")
def get_status() -> Dict[str, Any]:
    """Returns application status, auth state, version, and stream statistics."""
    now = int(time.time())
    last_update = int(config.get("access_token_last_update", 0))
    lifetime = int(config.get("access_token_lifetime", 0))
    remaining = max(0, (last_update + lifetime) - now) if last_update else 0

    channel_data = get_cached_channels()
    total_channels = len(channel_data.get("list", [])) if channel_data else 0

    return {
        "version": APP_VERSION,
        "logged": config.is_logged,
        "country_code": config.country_code,
        "mac": config.get("mac"),
        "uuid": config.get("uuid"),
        "token_expires_in_seconds": remaining,
        "token_lifetime_seconds": lifetime,
        "total_channels": total_channels,
        "external_url": config.external_url,
        "default_quality": config.default_quality,
        "direct_redirect": config.direct_redirect,
        "uptime_seconds": int(now - SERVER_START_TIME),
    }


@router.post("/auth/start")
def start_auth() -> Dict[str, Any]:
    """Initiates device link workflow, returns activation code and QR url."""
    resp = client.start_auth()
    if not resp or resp.get("result") != "OK":
        raise HTTPException(status_code=500, detail="Failed to initiate login with Sweet.tv.")

    auth_code = resp.get("auth_code")
    activate_url = f"https://sweet.tv/addDevice?connectCode={auth_code}"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?data={activate_url}&size=250x250"

    return {
        "result": "OK",
        "auth_code": auth_code,
        "activate_url": activate_url,
        "qr_url": qr_url,
    }


@router.get("/auth/status")
def check_auth(code: str = Query(..., description="The activation code from /auth/start")) -> Dict[str, Any]:
    """Checks whether the user entered the device code."""
    resp = client.check_auth(code)
    if resp and resp.get("result") == "COMPLETED":
        invalidate_cache()
        return {"status": "COMPLETED"}
    elif resp and resp.get("result") == "PENDING":
        return {"status": "PENDING"}
    return {"status": resp.get("result", "PENDING") if resp else "ERROR"}


@router.post("/auth/logout")
def logout() -> Dict[str, Any]:
    """Logs out from Sweet.tv and clears tokens."""
    client.logout()
    invalidate_cache()
    return {"status": "OK", "logged": False}


@router.get("/channels")
def get_channels_api() -> Dict[str, Any]:
    """Returns channel list formatted for the frontend player."""
    if not config.is_logged:
        raise HTTPException(status_code=401, detail="Unauthorized")

    data = get_cached_channels(need_epg=True)
    if not data or data.get("status") != "OK":
        raise HTTPException(status_code=502, detail="Failed to fetch channels from Sweet.tv")

    categories: Dict[int, str] = {cat["id"]: cat.get("caption", "") for cat in data.get("categories", [])}

    now = int(time.time())
    channel_list = []

    for ch in data.get("list", []):
        if not ch.get("available"):
            continue

        cid = ch.get("id")
        cname = ch.get("name")
        icon = ch.get("icon_v2_url") or ch.get("icon_url")
        slug = ch.get("slug")

        # Category captions
        cat_names = [categories[c] for c in ch.get("category", []) if c in categories and c != 1000]

        # EPG now and next
        current_prog = None
        next_prog = None
        epg_items = ch.get("epg", [])
        for i, p in enumerate(epg_items):
            start = p.get("time_start", 0)
            stop = p.get("time_stop", 0)
            if start <= now < stop:
                current_prog = {
                    "id": p.get("id"),
                    "title": p.get("text"),
                    "start": start,
                    "stop": stop,
                    "progress": int(((now - start) / max(1, stop - start)) * 100),
                    "available": p.get("available", False)
                }
                if i + 1 < len(epg_items):
                    np = epg_items[i + 1]
                    next_prog = {
                        "id": np.get("id"),
                        "title": np.get("text"),
                        "start": np.get("time_start", 0),
                        "stop": np.get("time_stop", 0),
                    }
                break

        channel_list.append({
            "id": cid,
            "name": cname,
            "slug": slug,
            "icon": icon,
            "categories": cat_names,
            "catchup": ch.get("catchup", False),
            "catchup_duration": ch.get("catchup_duration", 7),
            "current_programme": current_prog,
            "next_programme": next_prog,
        })

    return {
        "total": len(channel_list),
        "categories": [{"id": k, "caption": v} for k, v in categories.items()],
        "channels": channel_list,
    }


@router.get("/channel/{channel_id}/epg")
def get_channel_epg_schedule(channel_id: int) -> Dict[str, Any]:
    """Returns full program schedule with catchup availability for a channel."""
    if not config.is_logged:
        raise HTTPException(status_code=401, detail="Unauthorized")

    data = get_cached_channels(need_epg=True)
    if not data or data.get("status") != "OK":
        raise HTTPException(status_code=502, detail="Failed to fetch EPG")

    now = int(time.time())
    for ch in data.get("list", []):
        if ch.get("id") == channel_id:
            programs = []
            for p in ch.get("epg", []):
                programs.append({
                    "id": p.get("id"),
                    "title": p.get("text"),
                    "start": p.get("time_start"),
                    "stop": p.get("time_stop"),
                    "available": p.get("available", False),
                    "is_past": p.get("time_stop", 0) <= now,
                    "is_current": p.get("time_start", 0) <= now < p.get("time_stop", 0),
                    "can_replay": bool(ch.get("catchup") and p.get("available") and p.get("id")),
                })
            return {
                "channel_id": channel_id,
                "name": ch.get("name"),
                "catchup": ch.get("catchup", False),
                "catchup_duration": ch.get("catchup_duration", 7),
                "programs": programs
            }
    raise HTTPException(status_code=404, detail="Channel not found")


@router.get("/stream/{channel_id}/info")
def get_stream_info_api(channel_id: int, epg_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Returns available streaming qualities, bitrates, and video/audio codecs
    for a given channel.
    """
    if not config.is_logged:
        raise HTTPException(status_code=401, detail="Unauthorized")

    details = get_stream_details(channel_id, epg_id)
    if not details:
        raise HTTPException(status_code=502, detail="Failed to retrieve stream details.")

    return {
        "channel_id": channel_id,
        "epg_id": epg_id,
        "master_url": details.get("master_url"),
        "scheme": details.get("scheme"),
        "variants": details.get("variants", []),
    }


@router.post("/settings")
def update_settings(payload: SettingsUpdate) -> Dict[str, Any]:
    """Updates server settings."""
    changed = {}
    if payload.countryCode is not None and payload.countryCode.strip():
        new_cc = payload.countryCode.strip().lower()
        if new_cc != config.country_code:
            changed["countryCode"] = new_cc
            invalidate_cache()

    if payload.external_url is not None:
        changed["external_url"] = payload.external_url.strip().rstrip("/")

    if payload.default_quality is not None:
        changed["default_quality"] = payload.default_quality.strip().lower()

    if payload.direct_redirect is not None:
        changed["direct_redirect"] = payload.direct_redirect

    if payload.m3u_catchup is not None:
        changed["m3u_catchup"] = payload.m3u_catchup

    if changed:
        config.update(changed)

    return {"status": "OK", "settings": config.data}


@router.post("/cache/refresh")
def refresh_cache() -> Dict[str, Any]:
    """Forces cache refresh."""
    invalidate_cache()
    # Pre-warm channels
    get_cached_channels(force_refresh=True)
    return {"status": "OK"}
