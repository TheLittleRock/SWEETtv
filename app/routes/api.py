import logging
import time
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError
from urllib.request import Request as URLRequest, urlopen
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response, status
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
from app.providers.manager import provider_manager
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
    oneplay_enabled: Optional[bool] = None
    oneplay_username: Optional[str] = None
    oneplay_password: Optional[str] = None
    oneplay_pin: Optional[str] = None
    oneplay_device_name: Optional[str] = None


class OneplayLoginRequest(BaseModel):
    username: str
    password: str
    pin: Optional[str] = "4321"
    device_name: Optional[str] = "SWEETtv-Oneplay"


class OneplayProfileRequest(BaseModel):
    profile_id: str
    pin: Optional[str] = "4321"



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
        "oneplay_enabled": config.oneplay_enabled,
        "oneplay_logged": config.is_oneplay_logged,
        "oneplay_username": config.get("oneplay_username", ""),
        "oneplay_profile": config.get("oneplay_profile", ""),
        "oneplay_token_expires_in": max(0, int(config.get("oneplay_token_valid_to", 0)) - now) if config.get("oneplay_token_valid_to") else 0,
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
# ONEPLAY PROVIDER AUTH & MANAGEMENT (ADMIN ONLY)
# =========================================================================

@router.post("/provider/oneplay/login")
def oneplay_login(payload: OneplayLoginRequest, admin: User = Depends(require_admin)) -> Dict[str, Any]:
    """Authenticates with Oneplay and stores session credentials."""
    config.update({
        "oneplay_username": payload.username.strip(),
        "oneplay_password": payload.password.strip(),
        "oneplay_pin": (payload.pin or "4321").strip(),
        "oneplay_device_name": (payload.device_name or "SWEETtv-Oneplay").strip(),
    })
    success = provider_manager.oneplay.ensure_authenticated()
    if not success:
        raise HTTPException(status_code=400, detail="Přihlášení k Oneplay se nezdařilo. Zkontrolujte přihlašovací údaje.")

    return {
        "status": "OK",
        "logged": True,
        "username": config.get("oneplay_username"),
        "profile": config.get("oneplay_profile"),
    }


@router.get("/provider/oneplay/profiles")
def oneplay_profiles(admin: User = Depends(require_admin)) -> Dict[str, Any]:
    """Retrieves available user profiles for the connected Oneplay account."""
    if not config.is_oneplay_logged:
        raise HTTPException(status_code=401, detail="Oneplay is not authenticated.")

    token = config.get("oneplay_token")
    res = provider_manager.oneplay.api.call_api("user.profiles.display", data={"payload": {"mode": "change"}}, token=token)
    p_data = res.get("data") or res.get("result", {}).get("data") or {}
    profiles_raw = (p_data.get("availableProfiles") or {}).get("profiles") or []

    profiles = []
    for p in profiles_raw:
        prof = p.get("profile") or {}
        profiles.append({
            "id": prof.get("id"),
            "name": prof.get("name"),
            "is_child": prof.get("isChild", False),
            "is_active": prof.get("id") == config.get("oneplay_profile_id"),
        })

    return {"status": "OK", "profiles": profiles}


@router.post("/provider/oneplay/select-profile")
def oneplay_select_profile(payload: OneplayProfileRequest, admin: User = Depends(require_admin)) -> Dict[str, Any]:
    """Selects and activates a specific Oneplay profile."""
    if not config.is_oneplay_logged:
        raise HTTPException(status_code=401, detail="Oneplay is not authenticated.")

    token = config.get("oneplay_token")
    pin = payload.pin or config.get("oneplay_pin", "4321")
    post_prof: Dict[str, Any] = {"payload": {"profileId": payload.profile_id}}
    if pin and pin != "4321":
        post_prof["authorization"] = [{"schema": "PinRequestAuthorization", "pin": str(pin), "type": "profile"}]

    res = provider_manager.oneplay.api.call_api("user.profile.select", data=post_prof, token=token)
    data = res.get("data") or res.get("result", {}).get("data") or {}
    new_token = data.get("bearerToken")
    if new_token:
        config.update({
            "oneplay_token": new_token,
            "oneplay_profile_id": payload.profile_id,
            "oneplay_token_valid_to": int(time.time() + 14400),
        })
        return {"status": "OK", "profile_id": payload.profile_id}

    raise HTTPException(status_code=400, detail="Výběr profilu Oneplay se nezdařil.")


@router.post("/provider/oneplay/logout")
def oneplay_logout(admin: User = Depends(require_admin)) -> Dict[str, Any]:
    """Clears Oneplay tokens and session."""
    config.update({
        "oneplay_token": "",
        "oneplay_token_valid_to": 0,
        "oneplay_logged": False,
    })
    return {"status": "OK", "logged": False}


# =========================================================================
# CHANNELS & STREAM INFO (AUTHENTICATED USERS)
# =========================================================================

@router.get("/channels")
def get_channels_api(
    source: Optional[str] = Query(None, description="Source filter: 'all', 'sweettv', 'oneplay'"),
    current_user: User = Depends(require_user)
) -> Dict[str, Any]:
    """Returns channel list formatted for the frontend player."""
    has_sweet = config.is_logged
    has_oneplay = config.oneplay_enabled and config.is_oneplay_logged

    if not has_sweet and not has_oneplay:
        raise HTTPException(status_code=401, detail="No active IPTV provider logged in.")

    now = int(time.time())
    channel_list = []
    categories_set = set()

    channels = provider_manager.get_channels(source=source, need_epg=True)
    for ch in channels:
        cid = ch.get("id")
        provider = ch.get("provider")
        cname = ch.get("name")
        icon = ch.get("icon")
        cats = ch.get("category", [])
        for c in cats:
            categories_set.add(c)

        # Build now/next EPG
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
            "canonical_id": ch.get("canonical_id", f"{provider}:{cid}"),
            "provider": provider,
            "name": cname,
            "slug": cid,
            "icon": icon,
            "categories": cats,
            "catchup": ch.get("catchup", False),
            "catchup_duration": ch.get("catchup_duration", 7),
            "current_programme": current_prog,
            "next_programme": next_prog,
        })

    return {
        "total": len(channel_list),
        "categories": [{"id": c, "caption": c} for c in sorted(categories_set)],
        "channels": channel_list,
    }


@router.get("/channel/{channel_id}/epg")
def get_channel_epg_schedule(
    channel_id: str,
    current_user: User = Depends(require_user)
) -> Dict[str, Any]:
    """Returns full program schedule with catchup availability for a channel (Sweet.tv or Oneplay)."""
    clean_cid = str(channel_id).replace("oneplay:", "").strip()
    is_oneplay = str(channel_id).startswith("oneplay:") or "~" in clean_cid or not clean_cid.isdigit()

    if not is_oneplay:
        op_channels = {c["id"]: c for c in provider_manager.oneplay.get_channels()}
        if clean_cid in op_channels:
            is_oneplay = True

    now = int(time.time())

    # Oneplay Channel EPG
    if is_oneplay:
        if not (config.oneplay_enabled and config.is_oneplay_logged):
            if not provider_manager.oneplay.ensure_authenticated():
                raise HTTPException(status_code=401, detail="Oneplay přihlášení vyžadováno.")

        raw_programs = provider_manager.oneplay.get_channel_epg(clean_cid)
        programs = []
        for p in raw_programs:
            t_start = p.get("time_start", 0)
            t_stop = p.get("time_stop", 0)
            programs.append({
                "id": str(p.get("id")),
                "title": p.get("title", ""),
                "description": p.get("description", ""),
                "start": t_start,
                "stop": t_stop,
                "available": True,
                "is_past": t_stop <= (now - 5),
                "is_current": t_start <= now < t_stop,
                "can_replay": bool(p.get("can_replay")),
                "cover": p.get("cover", ""),
                "payload": p.get("payload", {})
            })

        return {
            "channel_id": clean_cid,
            "name": f"Oneplay {clean_cid}",
            "catchup": True,
            "catchup_duration": 7,
            "programs": programs
        }

    # Sweet.tv numeric channel
    if not config.is_logged:
        raise HTTPException(status_code=401, detail="Sweet.tv login required.")

    data = get_cached_channels(need_epg=True)
    if not data or data.get("status") != "OK":
        raise HTTPException(status_code=502, detail="Failed to fetch EPG")

    target_int = int(clean_cid) if clean_cid.isdigit() else 0
    for ch in data.get("list", []):
        if ch.get("id") == target_int:
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
                "channel_id": target_int,
                "name": ch.get("name"),
                "catchup": ch.get("catchup", False),
                "catchup_duration": ch.get("catchup_duration", 7),
                "programs": programs
            }
    raise HTTPException(status_code=404, detail="Channel not found")


@router.get("/stream/{channel_id}/info")
def get_stream_info_api(
    channel_id: str,
    epg_id: Optional[str] = None,
    current_user: User = Depends(require_user)
) -> Dict[str, Any]:
    """Returns available streaming qualities and variants for a channel."""
    clean_str = str(channel_id).replace(".m3u8", "").strip()
    if clean_str.startswith("oneplay:") or "~" in clean_str or (not clean_str.isdigit() and config.oneplay_enabled):
        cid_op = clean_str.replace("oneplay:", "")
        details = provider_manager.oneplay.get_stream_details(cid_op, epg_id=epg_id)
        if not details or not details.get("master_url"):
            raise HTTPException(status_code=502, detail="Failed to retrieve stream from Oneplay.")
        return {
            "channel_id": clean_str,
            "provider": "oneplay",
            "master_url": details.get("master_url"),
            "direct_redirect": False,
            "variants": [],
        }

    if not config.is_logged:
        raise HTTPException(status_code=401, detail="Sweet.tv login required.")

    cid_clean = int("".join(c for c in clean_str if c.isdigit()))
    eid_clean = int("".join(c for c in epg_id if c.isdigit())) if epg_id else None
    details = get_stream_details(cid_clean, eid_clean)
    if not details:
        raise HTTPException(status_code=502, detail="Failed to retrieve stream details.")

    return {
        "channel_id": cid_clean,
        "provider": "sweettv",
        "epg_id": eid_clean,
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

    if payload.oneplay_enabled is not None:
        changed["oneplay_enabled"] = payload.oneplay_enabled

    if payload.oneplay_username is not None:
        changed["oneplay_username"] = payload.oneplay_username.strip()

    if payload.oneplay_password is not None and payload.oneplay_password.strip():
        changed["oneplay_password"] = payload.oneplay_password.strip()

    if payload.oneplay_pin is not None:
        changed["oneplay_pin"] = payload.oneplay_pin.strip()

    if payload.oneplay_device_name is not None:
        changed["oneplay_device_name"] = payload.oneplay_device_name.strip()

    if changed:
        config.update(changed)

    return {"status": "OK", "settings": config.data}


@router.post("/cache/refresh")
def refresh_cache(admin: User = Depends(require_admin)) -> Dict[str, Any]:
    """Forces cache refresh."""
    invalidate_cache()
    get_cached_channels(force_refresh=True)
    return {"status": "OK"}


# =========================================================================
# ONEPLAY VOD & DRM LICENSE PROXY ENDPOINTS
# =========================================================================

@router.get("/provider/oneplay/vod/categories")
def get_oneplay_vod_categories_api(
    current_user: User = Depends(require_user)
) -> Dict[str, Any]:
    """Returns top-level VOD categories from Oneplay."""
    categories = provider_manager.oneplay.get_vod_categories()
    return {"categories": categories}


@router.get("/provider/oneplay/vod/items")
def get_oneplay_vod_items_api(
    category: str = Query("all", description="Category ID: 'all', 'movies', 'series', 'recordings', etc."),
    page: int = Query(1, ge=1, description="Page number"),
    query: Optional[str] = Query(None, description="Search query string"),
    current_user: User = Depends(require_user)
) -> Dict[str, Any]:
    """Returns paginated VOD catalog items for movies, series, or cloud recordings."""
    return provider_manager.oneplay.get_vod_items(category=category, page=page, query=query)


@router.post("/provider/oneplay/vod/series")
def get_oneplay_series_detail_api(
    payload: Dict[str, Any] = Body(..., description="Show payload"),
    current_user: User = Depends(require_user)
) -> Dict[str, Any]:
    """Returns seasons and episodes list for a TV series."""
    return provider_manager.oneplay.get_series_detail(payload)


@router.post("/provider/oneplay/vod/season")
def get_oneplay_season_episodes_api(
    carousel_id: str = Query(..., description="Season carousel ID"),
    criteria: Any = Body(..., description="Season criteria"),
    sort_order: str = Query("ASC", description="Sort order: ASC or DESC"),
    current_user: User = Depends(require_user)
) -> Dict[str, Any]:
    """Returns episode tiles for a specific series season."""
    episodes = provider_manager.oneplay.get_season_episodes(carousel_id, criteria, sort_order)
    return {"episodes": episodes}


@router.post("/provider/oneplay/vod/play")
def get_oneplay_vod_play_stream_api(
    payload: Dict[str, Any] = Body(..., description="VOD item play payload"),
    current_user: User = Depends(require_user)
) -> Dict[str, Any]:
    """
    Obtains stream playback info (manifest URL and Widevine DRM parameters) for a VOD item.
    """
    stream_info = provider_manager.oneplay.get_vod_stream(payload)
    if not stream_info:
        raise HTTPException(status_code=502, detail="Failed to retrieve VOD stream from Oneplay.")
    return stream_info


@router.api_route("/provider/oneplay/drm-license", methods=["POST", "OPTIONS"])
async def oneplay_drm_license_proxy(
    request: Request,
    target: Optional[str] = Query(None, description="Target Axinom License Acquisition URL"),
    token: Optional[str] = Query(None, description="Axinom DRM Message Token")
):
    """
    Proxies raw binary Widevine CDM challenge from Shaka Player to Axinom license server.
    Appends required 'X-AxDRM-Message' token and forwards binary Widevine license.
    """
    if request.method == "OPTIONS":
        return Response(
            content="",
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
            }
        )

    license_url = target or request.headers.get("X-Target-License-Url")
    drm_token = token or request.headers.get("X-AxDRM-Message")

    if not license_url:
        raise HTTPException(status_code=400, detail="Missing target Axinom license URL")

    # Read binary challenge bytes from Shaka Player
    challenge_bytes = await request.body()

    headers = {
        "User-Agent": provider_manager.oneplay.api.ua,
        "Content-Type": "application/octet-stream",
        "Accept": "*/*",
    }
    if drm_token:
        headers["X-AxDRM-Message"] = drm_token

    try:
        req = URLRequest(license_url, data=challenge_bytes, headers=headers)
        with urlopen(req, timeout=12) as resp:
            license_bytes = resp.read()
            return Response(
                content=license_bytes,
                media_type="application/octet-stream",
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "*",
                    "Access-Control-Allow-Methods": "POST, OPTIONS",
                }
            )
    except HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="replace")
        logger.error(f"Axinom DRM license proxy HTTP {e.code}: {err_msg}")
        raise HTTPException(status_code=e.code, detail=f"Axinom DRM error: {err_msg}")
    except Exception as e:
        logger.error(f"Axinom DRM license proxy unexpected error: {e}")
        raise HTTPException(status_code=502, detail=str(e))

