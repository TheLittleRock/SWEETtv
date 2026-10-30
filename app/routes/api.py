import logging
import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel

from app.auth import (
    SESSION_COOKIE_NAME,
    User,
    authenticate_user,
    change_own_password,
    check_login_rate_limit,
    create_session,
    create_user,
    delete_session,
    delete_user,
    get_client_ip,
    get_current_user,
    is_request_https,
    list_users,
    record_login_failure,
    regenerate_token,
    require_admin,
    require_user,
    reset_login_failures,
    update_user,
)
from app.client import client
from app.config import config
from app.epg import get_cached_channels, invalidate_cache
from app.stream import get_stream_details
from app.version import APP_NAME, APP_VERSION

logger = logging.getLogger("SweetTV.Routes.API")
router = APIRouter(prefix="/api", tags=["API"])

SERVER_START_TIME = time.time()


# =========================================================================
# PYDANTIC SCHEMAS
# =========================================================================

class LoginRequest(BaseModel):
    username: str
    password: str
    remember: bool = True


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str


class StalkerMacRequest(BaseModel):
    mac: Optional[str] = None


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "user"
    expires_at: Optional[str] = None
    stalker_mac: Optional[str] = None


class UpdateUserRequest(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None
    expires_at: Optional[str] = None
    new_password: Optional[str] = None
    stalker_mac: Optional[str] = None


class SettingsUpdate(BaseModel):
    countryCode: Optional[str] = None
    external_url: Optional[str] = None
    default_quality: Optional[str] = None
    direct_redirect: Optional[bool] = None
    m3u_catchup: Optional[bool] = None
    xtream_user: Optional[str] = None
    xtream_password: Optional[str] = None


# =========================================================================
# WEB APP AUTHENTICATION ENDPOINTS
# =========================================================================

@router.post("/auth/login")
def login_api(payload: LoginRequest, request: Request, response: Response) -> Dict[str, Any]:
    """Authenticates web user and establishes HTTP-Only session cookie with brute-force protection."""
    client_ip = get_client_ip(request)
    check_login_rate_limit(client_ip)

    user = authenticate_user(payload.username, payload.password)
    if not user:
        record_login_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Neplatné uživatelské jméno nebo heslo."
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tento uživatelský účet byl zablokován správcem."
        )
    if user.is_expired():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platnost tohoto uživatelského účtu vypršela."
        )

    # Authentication succeeded, reset failed attempts
    reset_login_failures(client_ip)

    days = 30 if payload.remember else 1
    session_id = create_session(user.id, days=days)
    is_secure = is_request_https(request)

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        max_age=days * 86400,
        httponly=True,
        samesite="lax",
        secure=is_secure,
        path="/"
    )

    return {
        "status": "OK",
        "user": {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "token": user.token,
            "must_change_password": user.must_change_password,
        }
    }


@router.post("/auth/logout")
def logout_api(request: Request, response: Response) -> Dict[str, Any]:
    """Logs out web user and deletes session from DB."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        delete_session(session_id)
    is_secure = is_request_https(request)
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        secure=is_secure,
        httponly=True,
        samesite="lax"
    )
    return {"status": "OK"}


# =========================================================================
# USER SELF-MANAGEMENT / PROFILE
# =========================================================================

@router.post("/profile/password")
def change_password_api(
    payload: PasswordChangeRequest,
    current_user: User = Depends(require_user)
) -> Dict[str, Any]:
    """Allows authenticated user to change their own password."""
    try:
        success = change_own_password(current_user.id, payload.old_password, payload.new_password)
        if not success:
            raise HTTPException(status_code=400, detail="Původní heslo není správné.")
        return {"status": "OK", "message": "Heslo bylo úspěšně změněno."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/profile/regenerate-token")
def regenerate_own_token_api(current_user: User = Depends(require_user)) -> Dict[str, Any]:
    """Allows authenticated user to regenerate their personal M3U/EPG token."""
    new_token = regenerate_token(current_user.id)
    return {"status": "OK", "token": new_token}


@router.post("/profile/stalker-mac")
def update_own_stalker_mac_api(
    payload: StalkerMacRequest,
    current_user: User = Depends(require_user)
) -> Dict[str, Any]:
    """Allows authenticated user to register or clear their device MAC address."""
    try:
        raw_mac = payload.mac.strip() if payload.mac else ""
        user = update_user(current_user.id, stalker_mac=raw_mac if raw_mac else None)
        return {"status": "OK", "stalker_mac": user.stalker_mac if user else None}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =========================================================================
# USER MANAGEMENT (ADMIN ONLY)
# =========================================================================

@router.get("/users")
def get_users_list_api(admin: User = Depends(require_admin)) -> Dict[str, Any]:
    """Returns list of all users."""
    return {"status": "OK", "users": list_users()}


@router.post("/users")
def create_user_api(
    payload: CreateUserRequest,
    admin: User = Depends(require_admin)
) -> Dict[str, Any]:
    """Creates a new user."""
    try:
        user = create_user(
            username=payload.username,
            password=payload.password,
            role=payload.role,
            expires_at=payload.expires_at or None,
            stalker_mac=payload.stalker_mac
        )
        return {
            "status": "OK",
            "user": {
                "id": user.id,
                "username": user.username,
                "role": user.role,
                "token": user.token,
                "stalker_mac": user.stalker_mac,
                "is_active": user.is_active,
                "expires_at": user.expires_at,
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/users/{user_id}")
def update_user_api(
    user_id: int,
    payload: UpdateUserRequest,
    admin: User = Depends(require_admin)
) -> Dict[str, Any]:
    """Updates an existing user."""
    # Prevent admin from deactivating or demoting themselves
    if user_id == admin.id:
        if payload.is_active is False:
            raise HTTPException(status_code=400, detail="Nelze zablokovat vlastní administrátorský účet.")
        if payload.role and payload.role.lower() != "admin":
            raise HTTPException(status_code=400, detail="Nelze odebrat administrátorská práva vlastnímu účtu.")

    update_kwargs: Dict[str, Any] = {
        "user_id": user_id,
        "role": payload.role,
        "is_active": payload.is_active,
        "expires_at": payload.expires_at,
        "new_password": payload.new_password,
    }
    # Only update stalker_mac if field was explicitly present in request
    raw_dict = payload.dict(exclude_unset=True)
    if "stalker_mac" in raw_dict:
        update_kwargs["stalker_mac"] = payload.stalker_mac

    try:
        user = update_user(**update_kwargs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not user:
        raise HTTPException(status_code=404, detail="Uživatel nebyl nalezen.")

    return {
        "status": "OK",
        "user": {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "token": user.token,
            "stalker_mac": user.stalker_mac,
            "is_active": user.is_active,
            "expires_at": user.expires_at,
        }
    }


@router.delete("/users/{user_id}")
def delete_user_api(
    user_id: int,
    admin: User = Depends(require_admin)
) -> Dict[str, Any]:
    """Deletes a user."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Nelze smazat vlastní přihlášený administrátorský účet.")

    success = delete_user(user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Uživatel nebyl nalezen.")
    return {"status": "OK"}


@router.post("/users/{user_id}/regenerate-token")
def admin_regenerate_token_api(
    user_id: int,
    admin: User = Depends(require_admin)
) -> Dict[str, Any]:
    """Regenerates M3U token for target user."""
    new_token = regenerate_token(user_id)
    return {"status": "OK", "token": new_token}


# =========================================================================
# SYSTEM STATUS & GENERAL ENDPOINTS
# =========================================================================

@router.get("/version")
def get_version() -> Dict[str, Any]:
    """Returns application version and build info."""
    return {
        "version": APP_VERSION,
        "name": APP_NAME,
        "uptime_seconds": int(time.time() - SERVER_START_TIME)
    }


@router.get("/status")
def get_status(current_user: User = Depends(require_user)) -> Dict[str, Any]:
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
        "mac": config.get("mac") if current_user.is_admin else "Protected",
        "uuid": config.get("uuid") if current_user.is_admin else "Protected",
        "token_expires_in_seconds": remaining,
        "token_lifetime_seconds": lifetime,
        "total_channels": total_channels,
        "external_url": config.external_url,
        "default_quality": config.default_quality,
        "direct_redirect": config.direct_redirect,
        "xtream_user": current_user.username,
        "xtream_password": "••••••••",
        "m3u_catchup": config.get("m3u_catchup", True),
        "uptime_seconds": int(now - SERVER_START_TIME),
        "user": {
            "username": current_user.username,
            "role": current_user.role,
            "is_admin": current_user.is_admin,
            "token": current_user.token,
            "must_change_password": current_user.must_change_password,
        }
    }


# =========================================================================
# SWEET.TV PROVIDER PAIRING & MANAGEMENT (ADMIN ONLY)
# =========================================================================

@router.post("/provider/auth/start")
def start_auth(admin: User = Depends(require_admin)) -> Dict[str, Any]:
    """Initiates device link workflow with Sweet.tv, returns activation code and QR url."""
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


@router.get("/provider/auth/status")
def check_auth(
    code: str = Query(..., description="The activation code from /provider/auth/start"),
    admin: User = Depends(require_admin)
) -> Dict[str, Any]:
    """Checks whether the user entered the device code."""
    resp = client.check_auth(code)
    if resp and resp.get("result") == "COMPLETED":
        invalidate_cache()
        return {"status": "COMPLETED"}
    elif resp and resp.get("result") == "PENDING":
        return {"status": "PENDING"}
    return {"status": resp.get("result", "PENDING") if resp else "ERROR"}


@router.post("/provider/auth/logout")
def provider_logout(admin: User = Depends(require_admin)) -> Dict[str, Any]:
    """Logs out from Sweet.tv and clears provider tokens."""
    client.logout()
    invalidate_cache()
    return {"status": "OK", "logged": False}


@router.post("/provider/auth/reset-device")
def reset_device(admin: User = Depends(require_admin)) -> Dict[str, Any]:
    """Terminates Sweet.tv session and regenerates UUID/MAC hardware identity."""
    new_ids = client.reset_device_identity()
    invalidate_cache()
    return {"status": "OK", "logged": False, "uuid": new_ids["uuid"], "mac": new_ids["mac"]}


# =========================================================================
# CHANNELS & STREAM INFO (AUTHENTICATED USERS)
# =========================================================================

@router.get("/channels")
def get_channels_api(current_user: User = Depends(require_user)) -> Dict[str, Any]:
    """Returns channel list formatted for the frontend player."""
    if not config.is_logged:
        raise HTTPException(status_code=401, detail="Sweet.tv login required.")

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
def get_channel_epg_schedule(
    channel_id: int,
    current_user: User = Depends(require_user)
) -> Dict[str, Any]:
    """Returns full program schedule with catchup availability for a channel."""
    if not config.is_logged:
        raise HTTPException(status_code=401, detail="Sweet.tv login required.")

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
def get_stream_info_api(
    channel_id: int,
    epg_id: Optional[int] = None,
    current_user: User = Depends(require_user)
) -> Dict[str, Any]:
    """Returns available streaming qualities and variants for a channel."""
    if not config.is_logged:
        raise HTTPException(status_code=401, detail="Sweet.tv login required.")

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


# =========================================================================
# SERVER SETTINGS & CACHE (ADMIN ONLY)
# =========================================================================

@router.post("/settings")
def update_settings(
    payload: SettingsUpdate,
    admin: User = Depends(require_admin)
) -> Dict[str, Any]:
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
def refresh_cache(admin: User = Depends(require_admin)) -> Dict[str, Any]:
    """Forces cache refresh."""
    invalidate_cache()
    get_cached_channels(force_refresh=True)
    return {"status": "OK"}
