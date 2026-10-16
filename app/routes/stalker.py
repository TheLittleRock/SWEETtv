import hashlib
import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import unquote
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import config
from app.epg import get_cached_channels
from app.routes.iptv import clean_id, get_effective_base_url
from app.version import APP_NAME, APP_VERSION

logger = logging.getLogger("SweetTV.Routes.Stalker")
router = APIRouter(tags=["Stalker / MAG Portal"])


def _extract_mac(request: Request, params: Dict[str, Any]) -> str:
    """Extracts MAC address from cookies, headers, or query/form params."""
    if "mac" in params and params["mac"]:
        return str(params["mac"]).strip().lower()

    cookie_mac = request.cookies.get("mac")
    if cookie_mac:
        return cookie_mac.strip().lower()

    auth_header = request.headers.get("authorization", "")
    if "bearer" in auth_header.lower():
        parts = auth_header.split()
        if len(parts) == 2:
            return parts[1].strip()

    return "00:1a:79:00:00:01"


@router.api_route("/load.php", methods=["GET", "POST"])
@router.api_route("/portal.php", methods=["GET", "POST"])
@router.api_route("/c/load.php", methods=["GET", "POST"])
@router.api_route("/server/load.php", methods=["GET", "POST"])
@router.api_route("/stalker_portal/server/load.php", methods=["GET", "POST"])
@router.api_route("/stalker_portal/c/load.php", methods=["GET", "POST"])
async def stalker_load(request: Request):
    """
    Core Stalker / Ministra Middleware API router.
    Emulates MAG set-top box load.php handler for Live TV, categories, EPG, and playback links.
    """
    params: Dict[str, Any] = dict(request.query_params)
    if request.method == "POST":
        try:
            form = await request.form()
            for k, v in form.items():
                params[k] = v
        except Exception:
            pass

    req_type = str(params.get("type", "")).strip().lower()
    action = str(params.get("action", "")).strip().lower()
    mac = _extract_mac(request, params)
    base_url = get_effective_base_url(request)

    logger.debug(f"Stalker API call: type={req_type}, action={action}, mac={mac}")

    # 1. STB Lifecycle Actions
    if req_type == "stb":
        if action == "handshake":
            salt = "12345678"
            token = hashlib.md5(f"{mac}:{salt}".encode("utf-8")).hexdigest()
            return JSONResponse({
                "js": {
                    "token": token,
                    "random": salt
                }
            })

        elif action == "get_profile":
            return JSONResponse({
                "js": {
                    "id": "1",
                    "name": "SweetTV User",
                    "sname": "SweetTV User",
                    "ls": "1",
                    "status": "1",
                    "tariff_plan_name": "Premium",
                    "account_number": "1001",
                    "mac": mac,
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

        elif action == "get_modules":
            return JSONResponse({
                "js": {
                    "disabled": [],
                    "default": "itv"
                }
            })

        elif action == "log":
            return JSONResponse({"js": True})

        elif action == "get_epg_info":
            # Overview of EPG table
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
                stream_url = f"{base_url}/stream/{cid}.m3u8{q_param}"

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
                        epg_id = parts[1]
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
                final_stream_url = f"{base_url}/stream/{cid}/{epg_id}.m3u8{q_param}"
            else:
                final_stream_url = f"{base_url}/stream/{cid}.m3u8{q_param}"

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

    # Default fallback for unhandled actions to keep portal STBs stable
    return JSONResponse({"js": {}})


@router.get("/c", response_class=HTMLResponse)
@router.get("/c/", response_class=HTMLResponse)
@router.get("/c/index.html", response_class=HTMLResponse)
@router.get("/stalker_portal/c", response_class=HTMLResponse)
@router.get("/stalker_portal/c/", response_class=HTMLResponse)
@router.get("/stalker_portal/c/index.html", response_class=HTMLResponse)
def stalker_portal_page(request: Request):
    """Informational landing page when portal URL is visited directly in browser."""
    base_url = get_effective_base_url(request)
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
                height: 100vh;
                margin: 0;
            }}
            .card {{
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 16px;
                padding: 32px;
                max-width: 520px;
                text-align: center;
                box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5);
            }}
            h1 {{ font-size: 22px; color: #38bdf8; margin-top: 0; }}
            p {{ font-size: 14px; color: #94a3b8; line-height: 1.6; }}
            .url-box {{
                background: #0f172a;
                border: 1px solid #0284c7;
                border-radius: 8px;
                padding: 12px 16px;
                font-family: monospace;
                font-size: 15px;
                color: #38bdf8;
                word-break: break-all;
                margin: 20px 0;
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
            a {{ color: #38bdf8; text-decoration: none; font-size: 13px; }}
            a:hover {{ text-decoration: underline; }}
        </style>
    </head>
    <body>
        <div class="card">
            <span class="badge">STALKER / MAG PORTAL ACTIVE</span>
            <h1>SweetTV MAG Portal</h1>
            <p>Tento server emuluje Stalker / MAG Middleware pro IPTV aplikace a set-top boxy (MAG250/322 a emulátory).</p>
            <div class="url-box">{base_url}/c/</div>
            <p>Vložte tuto adresu do nastavení <strong>Stalker portály</strong> ve vaší IPTV aplikaci nebo zařízení.</p>
            <a href="/">← Zpět na webový přehrávač a správu</a>
        </div>
    </body>
    </html>
    """)
