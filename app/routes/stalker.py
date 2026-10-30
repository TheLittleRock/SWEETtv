import hashlib
import logging
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import unquote
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from app.auth import (
    User,
    get_current_user,
    get_user_by_id,
    get_user_by_stalker_mac,
    get_user_by_token,
    normalize_mac,
    update_user,
    validate_token_or_session,
)
from app.config import config
from app.epg import get_cached_channels
from app.routes.iptv import clean_id, get_effective_base_url
from app.version import APP_NAME, APP_VERSION

logger = logging.getLogger("SweetTV.Routes.Stalker")
router = APIRouter(tags=["Stalker / MAG Portal"])

# In-memory store for STB handshake session tokens: token -> {user_id, mac, created_at}
_stb_sessions: Dict[str, Dict[str, Any]] = {}


def _save_stb_session(stb_token: str, user_id: int, mac: Optional[str] = None):
    """Stores STB session token with timestamp and purges sessions older than 7 days."""
    now = time.time()
    expired = [k for k, v in _stb_sessions.items() if now - v.get("created_at", 0) > 7 * 86400]
    for k in expired:
        _stb_sessions.pop(k, None)
    _stb_sessions[stb_token] = {
        "user_id": user_id,
        "mac": mac,
        "created_at": now
    }


def _get_stb_session(stb_token: str) -> Optional[Dict[str, Any]]:
    """Retrieves valid STB session token if not expired."""
    sess = _stb_sessions.get(stb_token)
    if sess:
        if time.time() - sess.get("created_at", 0) <= 7 * 86400:
            return sess
        _stb_sessions.pop(stb_token, None)
    return None


def _extract_mac(request: Request, params: Dict[str, Any]) -> Optional[str]:
    """
    Extracts and normalizes MAC address from query/form params, cookies, or headers.
    Returns canonical lowercase colon-separated format (e.g. '00:1a:79:0d:d6:c1') or None.
    """
    candidates = []

    # 1. Query / Form parameters
    for key in ("mac", "stb_mac", "device_id"):
        val = params.get(key)
        if val:
            candidates.append(str(val))

    # 2. Cookies
    for key in ("mac", "stb_mac", "MAC"):
        val = request.cookies.get(key)
        if val:
            candidates.append(val)

    # 3. Custom Headers
    for header in ("x-mac", "x-user-mac", "mac", "stb-mac"):
        val = request.headers.get(header)
        if val:
            candidates.append(val)

    # 4. Raw Cookie header search (in case of URL-encoding or non-standard format)
    raw_cookie = request.headers.get("cookie", "")
    if raw_cookie:
        cookie_match = re.search(r"(?:^|;\s*)(?:mac|stb_mac)=([^;]+)", raw_cookie, re.IGNORECASE)
        if cookie_match:
            candidates.append(cookie_match.group(1))

    # 5. Authorization header check (e.g. Bearer 00:1A:79:...)
    auth_header = request.headers.get("authorization", "")
    if auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() in ("bearer", "mac"):
            candidates.append(parts[1])

    # Validate candidates against MAC format
    for cand in candidates:
        norm = normalize_mac(cand)
        if norm:
            return norm

    return None


@router.api_route("/load.php", methods=["GET", "POST"])
@router.api_route("/portal.php", methods=["GET", "POST"])
@router.api_route("/c/load.php", methods=["GET", "POST"])
@router.api_route("/c/server/load.php", methods=["GET", "POST"])
@router.api_route("/server/load.php", methods=["GET", "POST"])
@router.api_route("/stalker_portal/server/load.php", methods=["GET", "POST"])
@router.api_route("/stalker_portal/c/load.php", methods=["GET", "POST"])
@router.api_route("/t/{token}/load.php", methods=["GET", "POST"])
@router.api_route("/t/{token}/portal.php", methods=["GET", "POST"])
@router.api_route("/t/{token}/c/load.php", methods=["GET", "POST"])
@router.api_route("/t/{token}/c/server/load.php", methods=["GET", "POST"])
@router.api_route("/t/{token}/server/load.php", methods=["GET", "POST"])
@router.api_route("/t/{token}/stalker_portal/server/load.php", methods=["GET", "POST"])
@router.api_route("/t/{token}/stalker_portal/c/load.php", methods=["GET", "POST"])
async def stalker_load(request: Request, token: Optional[str] = None):
    """
    Core Stalker / Ministra Middleware API router.
    Emulates MAG set-top box load.php handler for Live TV, categories, EPG, and playback links.
    Secured by user token (in URL path /t/{token}/... or query parameter ?token=...)
    or device MAC address registered to a user account.
    """
    params: Dict[str, Any] = dict(request.query_params)
    if request.method == "POST":
        try:
            form = await request.form()
            for k, v in form.items():
                params[k] = v
        except Exception:
            pass

    mac = _extract_mac(request, params)
    token_candidate = token or params.get("token") or params.get("t")

    user: Optional[User] = None

    # 1. Authenticate via token in path / query parameter
    if token_candidate:
        user = get_user_by_token(str(token_candidate).strip())

    # 2. Authenticate via previous STB handshake session token
    if not user and token_candidate:
        stb_sess = _get_stb_session(str(token_candidate).strip())
        if stb_sess:
            user = get_user_by_id(stb_sess["user_id"])

    # 3. Authenticate via web browser session cookie
    if not user:
        user = get_current_user(request)

    # 4. Authenticate via registered device MAC address
    if not user and mac:
        user = get_user_by_stalker_mac(mac)

    # Validate user permissions if found
    if user:
        if not user.is_active:
            logger.warning(f"Stalker access rejected: user '{user.username}' is disabled.")
            return JSONResponse(
                {"js": {"error": f"Authorization failed: Account '{user.username}' is disabled."}},
                status_code=403
            )
        if user.is_expired():
            logger.warning(f"Stalker access rejected: user '{user.username}' has expired.")
            return JSONResponse(
                {"js": {"error": f"Authorization failed: Account '{user.username}' has expired."}},
                status_code=403
            )

        # Auto-bind MAC to this user if token-authorized and user has no MAC registered yet
        if mac and not user.stalker_mac:
            existing_owner = get_user_by_stalker_mac(mac)
            if not existing_owner:
                try:
                    update_user(user.id, stalker_mac=mac)
                    logger.info(f"Auto-bound MAC {mac} to user '{user.username}' upon authorized request.")
                except Exception as e:
                    logger.warning(f"Failed to auto-bind MAC {mac}: {e}")

    else:
        # Neither token nor MAC matched a registered user
        logger.warning(
            f"Stalker authentication failed: MAC={mac or 'none'} is not registered and token={token_candidate or 'none'} is invalid."
        )
        return JSONResponse(
            {
                "js": {
                    "error": f"Authorization failed: MAC address '{mac or 'unknown'}' is not registered."
                }
            },
            status_code=401
        )

    req_type = str(params.get("type", "")).strip().lower()
    action = str(params.get("action", "")).strip().lower()
    effective_mac = mac or user.stalker_mac or "00:1a:79:00:00:01"
    base_url = get_effective_base_url(request)

    logger.debug(f"Stalker API call: user={user.username}, type={req_type}, action={action}, mac={effective_mac}")

    # 1. STB Lifecycle Actions
    if req_type == "stb":
        if action == "handshake":
            salt = "12345678"
            stb_token = hashlib.md5(f"{effective_mac}:{salt}:{time.time()}".encode("utf-8")).hexdigest()
            _save_stb_session(stb_token, user.id, effective_mac)
            return JSONResponse({
                "js": {
                    "token": stb_token,
                    "random": salt
                }
            })

        elif action == "get_profile":
            return JSONResponse({
                "js": {
                    "id": str(user.id),
                    "name": user.username,
                    "sname": user.username,
                    "ls": "1",
                    "status": "1",
                    "tariff_plan_name": "SweetTV Premium",
                    "account_number": str(1000 + user.id),
                    "mac": effective_mac,
                    "playback_buffer_bytes": 0,
                    "playback_buffer_size": 0,
                    "audio_out": 1,
                    "video_out": "hdmi",
                    "parent_password": "0000",
                    "pass": "0000",
                    "timezone": "Europe/Prague",
                    "locale": "cs_CZ.utf8",
                    "city_id": 0,
                    "services": {
                        "tv": 1,
                        "video": 1,
                        "radio": 0,
                        "audio": 0
                    }
                }
            })

        elif action in ("get_modules", "do_auth", "log", "set_volume"):
            return JSONResponse({
                "js": {
                    "disabled": [],
                    "default": "itv"
                } if action == "get_modules" else True
            })

        elif action == "get_localization":
            return JSONResponse({
                "js": {
                    "locale": "cs_CZ.utf8",
                    "tz": "Europe/Prague"
                }
            })

        elif action == "get_epg_info":
            # Overview of EPG table
            return JSONResponse({
                "js": {
                    "data": [],
                    "total_items": 0
                }
            })
            return JSONResponse({
                "js": {
                    "data": [],
                    "total_items": 0
                }
            })

    # 2. Account Information
    elif req_type == "account_info":
        if action == "get_main_info":
            return JSONResponse({
                "js": {
                    "mac": mac,
                    "phone": "",
                    "ls": "1",
                    "account_number": "1001",
                    "tariff_plan_name": "SweetTV Premium"
                }
            })

    # 3. Live TV (ITV) Actions
    elif req_type == "itv":
        if action == "get_genres":
            channel_data = get_cached_channels(need_epg=False) or {}
            raw_cats = channel_data.get("categories", [])

            genres = [
                {"id": "*", "title": "Všechny kanály", "alias": "all", "censored": 0}
            ]
            for cat in raw_cats:
                cid = cat.get("id")
                caption = cat.get("caption") or f"Category {cid}"
                genres.append({
                    "id": str(cid),
                    "title": caption,
                    "alias": f"cat_{cid}",
                    "censored": 0
                })

            return JSONResponse({"js": genres})

        elif action in ("get_all_channels", "get_ordered_list"):
            channel_data = get_cached_channels(need_epg=False) or {}
            channels_raw = channel_data.get("list", [])
            categories_map = {cat["id"]: cat.get("caption", "") for cat in channel_data.get("categories", [])}

            target_genre = str(params.get("genre", "*")).strip()
            quality = config.default_quality
            q_param = f"?quality={quality}" if quality and quality != "auto" else ""

            stb_channels = []
            idx = 0
            for ch in channels_raw:
                if not ch.get("available"):
                    continue

                ch_cats = ch.get("category", [])
                cat_id = ch_cats[0] if ch_cats else 1

                if target_genre not in ("*", "", "all") and str(cat_id) != target_genre:
                    continue

                idx += 1
                cid = ch.get("id")
                cname = (ch.get("name") or f"Channel {cid}").strip()
                icon = ch.get("icon_v2_url") or ch.get("icon_url") or ""
                stream_url = f"{base_url}/t/{user.token}/stream/{cid}.m3u8{q_param}"

                is_catchup = 1 if ch.get("catchup") else 0
                catchup_days = int(ch.get("catchup_duration", 7) or 7) if is_catchup else 0

                stb_channels.append({
                    "id": str(cid),
                    "name": cname,
                    "number": str(idx),
                    "censored": 0,
                    "lock": 0,
                    "fav": 0,
                    "adult": 0,
                    "status": 1,
                    "archive": is_catchup,
                    "tv_archive": is_catchup,
                    "tv_archive_duration": catchup_days,
                    "tv_genre_id": str(cat_id),
                    "genre_id": str(cat_id),
                    "xmltv_id": str(cid),
                    "logo": icon,
                    "cmd": f"ffmpeg {stream_url}"
                })

            return JSONResponse({
                "js": {
                    "total_items": len(stb_channels),
                    "max_page_items": len(stb_channels),
                    "selected_item": 0,
                    "cur_page": 1,
                    "data": stb_channels
                }
            })

        elif action == "create_link":
            raw_cmd = unquote(str(params.get("cmd", ""))).strip()
            # Clean possible 'ffmpeg ' prefix
            if raw_cmd.lower().startswith("ffmpeg "):
                raw_cmd = raw_cmd[7:].strip()

            cid = None
            epg_id = None
            # If cmd is a direct URL or contains channel ID
            if "/stream/" in raw_cmd or "/play/" in raw_cmd:
                try:
                    seg = raw_cmd.split("/stream/")[-1].split("/play/")[-1]
                    parts = seg.split("?")[0].split("/")
                    if len(parts) >= 2:
                        cid = clean_id(parts[0])
                        epg_id = parts[1].replace(".m3u8", "").strip()
                    else:
                        cid = clean_id(parts[0])
                except Exception:
                    pass
            elif raw_cmd.isdigit():
                cid = int(raw_cmd)

            if not cid:
                # Default to first channel
                cid = 851

            quality = config.default_quality
            q_param = f"?quality={quality}" if quality and quality != "auto" else ""
            if epg_id:
                final_stream_url = f"{base_url}/t/{user.token}/stream/{cid}/{epg_id}.m3u8{q_param}"
            else:
                final_stream_url = f"{base_url}/t/{user.token}/stream/{cid}.m3u8{q_param}"

            return JSONResponse({
                "js": {
                    "id": cid,
                    "cmd": final_stream_url,
                    "error": "",
                    "cached": 0
                }
            })

        elif action == "get_short_epg":
            ch_id_raw = params.get("ch_id")
            if not ch_id_raw:
                return JSONResponse({"js": {"data": [], "total_items": 0}})

            try:
                cid = clean_id(str(ch_id_raw))
            except ValueError:
                return JSONResponse({"js": {"data": [], "total_items": 0}})

            data = get_cached_channels(need_epg=True) or {}
            ch = next((c for c in data.get("list", []) if c.get("id") == cid), None)

            now = int(time.time())
            items = []
            if ch and ch.get("epg"):
                for p in ch["epg"]:
                    t_start = p.get("time_start", 0)
                    t_stop = p.get("time_stop", 0)
                    if t_stop < now - 3600:
                        continue
                    if t_start > now + 43200:
                        continue

                    items.append({
                        "id": str(p.get("id") or idx),
                        "time": time.strftime("%H:%M", time.localtime(t_start)),
                        "time_to": time.strftime("%H:%M", time.localtime(t_stop)),
                        "timestamp": t_start,
                        "timestamp_to": t_stop,
                        "name": p.get("text", ""),
                        "descr": p.get("description") or p.get("genre") or "",
                        "duration": max(0, t_stop - t_start),
                        "cur_playing": 1 if t_start <= now < t_stop else 0
                    })
                    if len(items) >= 6:
                        break

            return JSONResponse({
                "js": {
                    "data": items,
                    "total_items": len(items)
                }
            })

    # 4. Electronic Program Guide (EPG) Table
    elif req_type == "epg":
        if action == "get_simple_data_table":
            return JSONResponse({
                "js": {
                    "total_items": 0,
                    "max_page_items": 0,
                    "selected_item": 0,
                    "cur_page": 0,
                    "data": []
                }
            })

    # Default fallback for unhandled actions to keep portal STBs stable
    return JSONResponse({"js": {}})


@router.get("/c", response_class=HTMLResponse)
@router.get("/c/", response_class=HTMLResponse)
@router.get("/c/index.html", response_class=HTMLResponse)
@router.get("/stalker_portal/c", response_class=HTMLResponse)
@router.get("/stalker_portal/c/", response_class=HTMLResponse)
@router.get("/stalker_portal/c/index.html", response_class=HTMLResponse)
@router.get("/t/{token}/c", response_class=HTMLResponse)
@router.get("/t/{token}/c/", response_class=HTMLResponse)
@router.get("/t/{token}/c/index.html", response_class=HTMLResponse)
def stalker_portal_page(request: Request, token: Optional[str] = None):
    """Informational landing page when portal URL is visited directly in browser."""
    base_url = get_effective_base_url(request)
    portal_token = token or request.query_params.get("token") or request.query_params.get("t") or ""
    user_mac = None
    if not portal_token:
        user = get_current_user(request)
        if user:
            portal_token = user.token
            user_mac = user.stalker_mac

    portal_url = f"{base_url}/c/"
    token_url = f"{base_url}/t/{portal_token}/c/" if portal_token else f"{base_url}/t/&lt;váš-token&gt;/c/"
    mac_display = user_mac or "Není nastavena"

    return HTMLResponse(content=f"""
    <!DOCTYPE html>
    <html lang="cs">
    <head>
        <meta charset="utf-8">
        <title>Stalker / MAG Portal - SweetTV</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{
                background-color: #0b0f19;
                color: #e2e8f0;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                display: flex;
                align-items: center;
                justify-content: center;
                min-height: 100vh;
                margin: 0;
                padding: 16px;
            }}
            .card {{
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 16px;
                padding: 32px;
                max-width: 540px;
                text-align: center;
                box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5);
            }}
            h1 {{ font-size: 22px; color: #38bdf8; margin-top: 0; }}
            p {{ font-size: 14px; color: #94a3b8; line-height: 1.6; margin: 8px 0; }}
            .label {{ font-size: 12px; color: #64748b; text-transform: uppercase; font-weight: 600; margin-top: 14px; display: block; }}
            .url-box {{
                background: #0f172a;
                border: 1px solid #0284c7;
                border-radius: 8px;
                padding: 10px 14px;
                font-family: monospace;
                font-size: 14px;
                color: #38bdf8;
                word-break: break-all;
                margin: 6px 0 14px 0;
                user-select: all;
            }}
            .badge {{
                display: inline-block;
                background: #0284c7;
                color: white;
                font-weight: bold;
                font-size: 12px;
                padding: 4px 10px;
                border-radius: 20px;
                margin-bottom: 12px;
            }}
            .mac-box {{
                background: #0f172a;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 10px 14px;
                font-family: monospace;
                font-size: 14px;
                color: #a5f3fc;
                margin: 6px 0 14px 0;
            }}
            a {{ color: #38bdf8; text-decoration: none; font-size: 13px; }}
            a:hover {{ text-decoration: underline; }}
        </style>
    </head>
    <body>
        <div class="card">
            <span class="badge">STALKER / MAG PORTAL ACTIVE</span>
            <h1>SweetTV MAG Portal</h1>
            <p>Tento server emuluje Stalker / MAG Middleware pro IPTV aplikace (IPTVnator, TiviMate) a fyzické set-top boxy (MAG250/254/322).</p>
            
            <span class="label">URL Portálu pro aplikace a set-top boxy:</span>
            <div class="url-box">{portal_url}</div>

            <span class="label">Registrovaná MAC adresa vašeho účtu:</span>
            <div class="mac-box">{mac_display}</div>

            <p style="font-size: 12px; color: #64748b;">Aplikace a zařízení se ověřují přes MAC adresu. Svou MAC adresu můžete změnit ve webové administraci.</p>
            <div style="margin-top: 20px;">
                <a href="/">← Zpět na webový přehrávač a správu</a>
            </div>
        </div>
    </body>
    </html>
    """)
