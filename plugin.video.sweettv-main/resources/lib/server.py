import os
import json
import time
import uuid
import random
import logging
import xml.etree.ElementTree as ET
from urllib.parse import quote
from flask import Flask, Response, redirect, request, render_template_string
import requests

try:
    from brotlipython import brotlidec
    HAS_BROTLI = True
except ImportError:
    HAS_BROTLI = False

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("SweetTVServer")

app = Flask(__name__)
CONFIG_FILE = "config.json"

# ==============================================================================
# CONFIGURATION MANAGER
# ==============================================================================
class ConfigManager:
    DEFAULT_CONFIG = {
        "uuid": "",
        "mac": "",
        "bearer": "",
        "refresh_token": "",
        "logged": False,
        "countryCode": "cs",  # Default Czech language code
        "access_token_last_update": 0,
        "access_token_lifetime": 0,
    }

    def __init__(self, filepath=CONFIG_FILE):
        self.filepath = filepath
        self.data = self.DEFAULT_CONFIG.copy()
        self.load()

    def load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    self.data.update(json.load(f))
            except Exception as e:
                logger.error(f"Failed to load config: {e}")
        self.ensure_defaults()

    def save(self):
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save config: {e}")

    def ensure_defaults(self):
        save_needed = False
        if not self.data.get("uuid"):
            self.data["uuid"] = str(uuid.uuid4())
            save_needed = True
        if not self.data.get("mac"):
            self.data["mac"] = ":".join("%02x" % random.randint(0, 255) for _ in range(6))
            save_needed = True
        if save_needed:
            self.save()

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self.save()

config = ConfigManager()

# ==============================================================================
# SWEET.TV API CLIENT
# ==============================================================================
class SweetTVClient:
    BASE_API_URL = "https://api.sweet.tv/{}"
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    VERSION = "3.7.1"

    def __init__(self):
        self.session = requests.Session()

    def _get_headers(self):
        headers = {
            "Host": "api.sweet.tv",
            "user-agent": self.UA,
            "accept": "application/json, text/plain, */*",
            "accept-language": config.get("countryCode", "cs"),
            "accept-encoding": "gzip, deflate",  # Force gzip
            "x-device": f"1;22;0;2;{self.VERSION}",
            "origin": "https://sweet.tv",
            "dnt": "1",
            "referer": "https://sweet.tv/",
        }
        bearer = config.get("bearer")
        if bearer:
            headers["authorization"] = bearer
        return headers

    def _get_device_payload(self):
        return {
            "device": {
                "type": "DT_AndroidTV",
                "mac": config.get("mac"),
                "firmware": {"versionCode": 1301, "versionString": self.VERSION, "modules": []},
                "sub_type": "DST_Unknown",
                "uuid": config.get("uuid"),
                "screen_info": {"width": 1920, "height": 1080, "aspectRatio": "AR_16_9"},
                "application": {"type": "AT_SWEET_TV_Player"},
                "vendor": "unknown",
                "supported_drm": {
                    "aes128": False,
                    "widevineModular": True,
                    "widevineClassic": False,
                    "playReady": False,
                    "fairPlay": False
                },
                "guid": "",
                "system": "",
                "system_info": {"network_connection_type": "NCT_Unknown", "os_version": "23", "total_memory": 2, "hardware": ""},
                "advertisingId": str(uuid.uuid4())
            }
        }

    def request(self, endpoint, method="post", json_data=None, params=None):
        url = self.BASE_API_URL.format(endpoint)
        headers = self._get_headers()
        try:
            if method.lower() == "post":
                resp = self.session.post(url, headers=headers, json=json_data, params=params, timeout=15, verify=False)
            else:
                resp = self.session.get(url, headers=headers, params=params, timeout=15, verify=False)
            return resp.json()
        except Exception as e:
            logger.error(f"Request error on {endpoint}: {e}")
            return None

    def refresh_token(self):
        if not config.get("logged"):
            return False

        last_update = int(config.get("access_token_last_update", 0))
        lifetime = int(config.get("access_token_lifetime", 0))
        now = int(time.time())

        if now - last_update > int(lifetime * 0.9):
            payload = self._get_device_payload()
            payload["refresh_token"] = config.get("refresh_token")
            jsdata = self.request("AuthenticationService/Token.json", json_data=payload)
            if jsdata and jsdata.get("access_token"):
                config.set("bearer", "Bearer " + str(jsdata.get("access_token")))
                config.set("access_token_last_update", now)
                config.set("access_token_lifetime", int(jsdata.get("expires_in", 3600)))
                return True
            else:
                config.set("logged", False)
                return False
        return True

    def start_auth(self):
        return self.request("SigninService/Start.json", json_data=self._get_device_payload())

    def check_auth(self, auth_code):
        url = self.BASE_API_URL.format("SigninService/GetStatus.json")
        headers = self._get_headers()
        headers["Content-Type"] = "application/json"
        try:
            resp = self.session.post(url, headers=headers, json={"auth_code": auth_code}, timeout=15, verify=False)
            return resp.json()
        except Exception as e:
            return None

    def get_channels(self, need_epg=False):
        self.refresh_token()
        payload = {
            "epg_limit_prev": 1 if need_epg else 0,
            "epg_limit_next": 30 if need_epg else 0,
            "epg_current_time": int(time.time()),
            "need_epg": need_epg,
            "need_list": True,
            "need_categories": True,
            "need_offsets": False,
            "need_hash": False,
            "need_icons": False,
            "need_big_icons": False,
        }
        return self.request("TvService/GetChannels.json", json_data=payload)

    def open_stream(self, channel_id, epg_id=None):
        self.refresh_token()
        payload = {
            "without_auth": True,
            "channel_id": int(channel_id),
            "accept_scheme": ["HTTP_HLS"], # Critical: Force HLS streams instead of Widevine DASH
            "multistream": True,
        }
        if epg_id:
            payload["epg_id"] = int(epg_id)

        return self.request("TvService/OpenStream.json", json_data=payload)

client = SweetTVClient()

# ==============================================================================
# FLASK ROUTE HANDLERS
# ==============================================================================

@app.route("/")
def index():
    logged_in = config.get("logged")
    country = config.get("countryCode")
    host = request.host_url.rstrip("/")

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Sweet.tv IPTV Proxy Server</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; background: #f4f4f9; color: #333; }}
            .card {{ background: #fff; padding: 20px; border-radius: 8px; max-width: 600px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
            a {{ color: #007bff; text-decoration: none; }}
            .btn {{ display: inline-block; padding: 8px 12px; background: #28a745; color: white; border-radius: 4px; font-weight: bold; border: none; cursor: pointer; }}
            .status {{ font-weight: bold; color: {"green" if logged_in else "red"}; }}
            input[type="text"] {{ padding: 6px; width: 60px; text-align: center; font-size: 14px; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h2>Sweet.tv IPTV Proxy Server</h2>
            <p>Status: <span class="status">{"Logged In" if logged_in else "Not Logged In"}</span></p>
            <form action="/set_country" method="post">
                <p>Country Code: 
                    <input type="text" name="countryCode" value="{country}">
                    <button type="submit" class="btn" style="background:#007bff;">Save</button>
                </p>
            </form>
            <hr>
            <h3>Endpoints for your IPTV Player:</h3>
            <ul>
                <li><strong>M3U Playlist:</strong> <a href="{host}/playlist.m3u">{host}/playlist.m3u</a></li>
                <li><strong>EPG Guide:</strong> <a href="{host}/epg.xml">{host}/epg.xml</a></li>
            </ul>
            <hr>
            {"<p><a href='/logout' class='btn' style='background:#dc3545;'>Logout</a></p>" if logged_in else "<p><a href='/login' class='btn'>Login with Device Code</a></p>"}
        </div>
    </body>
    </html>
    """
    return render_template_string(html)

@app.route("/set_country", methods=["POST"])
def set_country():
    new_code = request.form.get("countryCode", "cs").strip().lower()
    config.set("countryCode", new_code)
    return redirect("/")

@app.route("/login")
def login_route():
    jsdata = client.start_auth()
    if not jsdata or jsdata.get("result") != "OK":
        return "Failed to initiate login.", 500

    auth_code = jsdata.get("auth_code")
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?data=sweet.tv/addDevice?connectCode={auth_code}"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Sweet.tv Login</title>
        <style>
            body {{ font-family: Arial, sans-serif; text-align: center; margin-top: 50px; background-color: #1a1a1a; color: white; }}
            .code {{ font-size: 32px; font-weight: bold; color: #ffcc00; margin: 20px; letter-spacing: 2px; }}
            .card {{ display: inline-block; background: #2a2a2a; padding: 30px; border-radius: 12px; }}
        </style>
        <script>
            function checkStatus() {{
                fetch('/check_login?code={auth_code}').then(r => r.json()).then(data => {{
                    if(data.status === 'COMPLETED') window.location.href = '/?success=1';
                }});
            }}
            setInterval(checkStatus, 3000);
        </script>
    </head>
    <body>
        <div class="card">
            <h2>Connect Your Sweet.tv Account</h2>
            <p>Enter this activation code at <strong>sweet.tv/addDevice</strong>:</p>
            <div class="code">{auth_code}</div>
            <p>Or scan this QR code with your mobile device:</p>
            <img src="{qr_url}" alt="QR Code" width="220" height="220">
        </div>
    </body>
    </html>
    """
    return render_template_string(html)

@app.route("/check_login")
def check_login():
    auth_code = request.args.get("code")
    if not auth_code:
        return json.dumps({"status": "ERROR"})

    jsdata = client.check_auth(auth_code)
    if jsdata and jsdata.get("result") == "COMPLETED":
        config.set("bearer", "Bearer " + str(jsdata.get("access_token")))
        config.set("refresh_token", str(jsdata.get("refresh_token")))
        config.set("logged", True)
        config.set("access_token_last_update", int(time.time()))
        config.set("access_token_lifetime", int(jsdata.get("expires_in", 3600)))
        return json.dumps({"status": "COMPLETED"})

    return json.dumps({"status": "PENDING"})

@app.route("/logout")
def logout_route():
    config.set("logged", False)
    config.set("bearer", "")
    config.set("refresh_token", "")
    return redirect("/")

@app.route("/playlist.m3u")
def playlist():
    if not config.get("logged"):
        return "Unauthorized. Please log in first.", 401

    jsdata = client.get_channels(need_epg=False)
    if not jsdata or jsdata.get("status") != "OK":
        return "Failed to fetch channel list.", 500

    categories = {cat.get("id"): cat.get("caption") for cat in jsdata.get("categories", [])}
    host = request.host_url.rstrip("/")
    
    encoded_ua = quote(client.UA)
    encoded_ref = quote("https://sweet.tv/")

    lines = ["#EXTM3U"]
    for ch in jsdata.get("list", []):
        if not ch.get("available"):
            continue

        cid = ch.get("id")
        cname = ch.get("name", "")
        img = ch.get("icon_v2_url", "")
        
        cat_names = [categories[c] for c in ch.get("category", []) if c in categories and c != 1000]
        group_title = ";".join(cat_names)

        stream_url_base = f"{host}/play/{cid}"
        header_suffix = f"|User-Agent={encoded_ua}&Referer={encoded_ref}"

        catchup_tag = ""
        if ch.get("catchup"):
            catchup_tag = f'catchup="vod" catchup-source="{stream_url_base}/{{catchup-id}}{header_suffix}"'

        extinf = f'#EXTINF:0 tvg-id="{cid}.id.com" tvg-name="{cname}" tvg-logo="{img}" group-title="{group_title}" {catchup_tag},{cname}'
        stream_link = f"{stream_url_base}{header_suffix}"

        lines.append(extinf)
        # Dedicated headers explicitly for VLC
        lines.append(f'#EXTVLCOPT:http-referrer=https://sweet.tv/')
        lines.append(f'#EXTVLCOPT:http-user-agent={client.UA}')
        lines.append(stream_link)

    playlist_content = "\n".join(lines)
    return Response(playlist_content, mimetype="application/x-mpegurl")

@app.route("/epg.xml")
def epg():
    if not config.get("logged"):
        return "Unauthorized. Please log in first.", 401

    jsdata = client.get_channels(need_epg=True)
    if not jsdata or jsdata.get("status") != "OK":
        return "Failed to fetch EPG.", 500

    country_code = config.get("countryCode", "cs")
    xml_root = ET.Element("tv")

    for ch in jsdata.get("list", []):
        channel_elem = ET.SubElement(xml_root, "channel", attrib={"id": f"{ch.get('id')}.id.com"})
        ET.SubElement(channel_elem, "display-name", lang=country_code).text = ch.get("name")
        if ch.get("icon_url"):
            ET.SubElement(channel_elem, "icon", src=ch.get("icon_url"))

    for ch in jsdata.get("list", []):
        ch_id = f"{ch.get('id')}.id.com"
        epg_list = ch.get("epg", [])

        if epg_list:
            for item in epg_list:
                start_time = time.strftime("%Y%m%d%H%M%S +0100", time.localtime(item.get("time_start")))
                stop_time = time.strftime("%Y%m%d%H%M%S +0100", time.localtime(item.get("time_stop") - 1))

                attribs = {"start": start_time, "stop": stop_time, "channel": ch_id}
                if ch.get("catchup") and ch.get("available") and item.get("available"):
                    attribs["catchup-id"] = str(item.get("id"))

                prog_elem = ET.SubElement(xml_root, "programme", attrib=attribs)
                title_text = item.get("text", "")
                if not item.get("available") and ch.get("live_blackout"):
                    title_text = f"!NOT AVAILABLE! {title_text}"

                ET.SubElement(prog_elem, "title", lang=country_code).text = title_text
        else:
            now = time.time()
            start_time = time.strftime("%Y%m%d%H%M%S +0100", time.localtime(now))
            stop_time = time.strftime("%Y%m%d%H%M%S +0100", time.localtime(now + 43200))

            prog_elem = ET.SubElement(xml_root, "programme", attrib={"start": start_time, "stop": stop_time, "channel": ch_id})
            ET.SubElement(prog_elem, "title", lang=country_code).text = ch.get("name")

    xml_str = '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(xml_root, encoding="utf-8").decode("utf-8")
    return Response(xml_str, mimetype="text/xml")

@app.route("/play/<string:channel_id>")
@app.route("/play/<string:channel_id>/<string:epg_id>")
def play(channel_id, epg_id=None):
    if not config.get("logged"):
        return "Unauthorized", 401

    # Safely strip any lingering |User-Agent tags if strict players append them to the request
    if "|" in channel_id:
        channel_id = channel_id.split("|")[0]
    if epg_id and "|" in epg_id:
        epg_id = epg_id.split("|")[0]

    try:
        cid = int(channel_id)
        pid = int(epg_id) if epg_id and epg_id.lower() != "null" else None
    except ValueError:
        return "Invalid ID format", 400

    jsdata = client.open_stream(cid, pid)
    if not jsdata or jsdata.get("result") != "OK":
        return f"Unable to open stream.", 500

    http_stream = jsdata.get("http_stream", {})
    stream_host = http_stream.get("host", {}).get("address")
    path = http_stream.get("url")

    if not stream_host or not path:
        return "Stream URL not available.", 504

    stream_url = f"https://{stream_host}{path}"
    return redirect(stream_url, code=302)

if __name__ == "__main__":
    requests.packages.urllib3.disable_warnings()
    logger.info("Starting Sweet.tv Standalone Proxy Server on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)