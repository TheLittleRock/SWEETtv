import gzip
import json
import logging
import os
import re
import socket
import threading
import time
import urllib.parse
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import requests
import websocket

from app.config import config
from app.providers.base import BaseProvider

logger = logging.getLogger("SweetTV.Providers.Oneplay")

FALLBACK_URL = "http://sledovanietv.sk/download/noAccess-cs.m3u8"


class OneplayAPI:
    """Handles communication with the Oneplay / Jyxo CMS backend via HTTP & WebSockets."""

    BASE_URL = "https://http.cms.jyxo.cz/api/"
    WS_URL = "wss://ws.cms.jyxo.cz/websocket/{}"
    APP_VERSION = "R11.33"
    DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0"

    def __init__(self):
        self.api_version = config.get("oneplay_api_version", "v1.11")
        self.ua = self.DEFAULT_UA

    def discover_api_version(self) -> str:
        """Probes for the highest active API version supported by the backend."""
        logger.info("Probing Oneplay API version...")
        try:
            start_num = int(self.api_version.split(".")[1])
        except (IndexError, ValueError):
            start_num = 11

        detected = self.api_version
        for minor in range(start_num, 50):
            v_str = f"v1.{str(minor).zfill(2)}"
            url = f"{self.BASE_URL}{v_str}/user.login.step"
            try:
                r = requests.post(url, json={}, timeout=6)
                if r.status_code == 400:
                    detected = v_str
                    logger.info(f"Detected valid Oneplay API version: {detected}")
                    config.set("oneplay_api_version", detected)
                elif r.status_code == 404:
                    if detected != self.api_version:
                        break
            except Exception as e:
                logger.warning(f"Error testing Oneplay version {v_str}: {e}")
                break

        self.api_version = detected
        return detected

    def call_api(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        token: Optional[str] = None,
        retry: bool = False
    ) -> Dict[str, Any]:
        """Executes a hybrid REST + WebSocket call to Jyxo CMS."""
        url = f"{self.BASE_URL}{self.api_version}/{endpoint}"
        client_id = f"sweettv-{os.urandom(8).hex()}"
        request_id = f"req-{os.urandom(8).hex()}"

        headers = {
            "User-Agent": self.ua,
            "Accept-Encoding": "gzip",
            "Accept": "*/*",
            "Content-Type": "application/json;charset=UTF-8",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        ws = None
        try:
            # 1. Connect WebSocket
            ws = websocket.create_connection(self.WS_URL.format(client_id), timeout=10)
            ws_greeting = json.loads(ws.recv())
            server_id = ws_greeting.get("data", {}).get("serverId") or "server-unknown"

            # 2. Build Post Body
            payload = {
                "deviceInfo": {
                    "deviceType": "web",
                    "appVersion": self.APP_VERSION,
                    "deviceManufacturer": "Unknown",
                    "deviceOs": "Linux",
                },
                "capabilities": {"async": "websockets"},
                "context": {
                    "requestId": request_id,
                    "clientId": client_id,
                    "sessionId": server_id,
                    "serverId": server_id,
                },
            }
            if data:
                payload.update(data)

            # 3. HTTP POST
            body_bytes = json.dumps(payload).encode("utf-8")
            req = Request(url=url, data=body_bytes, headers=headers)
            with urlopen(req, timeout=15) as resp:
                resp_bytes = resp.read()
                if resp.getheader("Content-Encoding") == "gzip":
                    resp_bytes = gzip.decompress(resp_bytes)

            res_json = json.loads(resp_bytes.decode("utf-8")) if resp_bytes else {}
            res_status = res_json.get("result", {}).get("status")

            # 4. Handle Async Response over WebSocket
            if res_status == "OkAsync":
                for _ in range(3):
                    msg = ws.recv()
                    if msg:
                        parsed_msg = json.loads(msg)
                        ws_resp = parsed_msg.get("response", {})
                        if ws_resp.get("context", {}).get("requestId") == request_id:
                            return ws_resp
                return {"result": {"status": "Error", "message": "WebSocket response timeout"}}

            return res_json

        except HTTPError as e:
            logger.warning(f"Oneplay HTTP error calling {url}: {e}")
            if e.code == 404 and not retry:
                self.discover_api_version()
                return self.call_api(endpoint, data=data, token=token, retry=True)
            return {"result": {"status": "Error", "message": f"HTTP {e.code}: {e.reason}"}}
        except Exception as e:
            logger.error(f"Oneplay unexpected error calling {endpoint}: {e}")
            return {"result": {"status": "Error", "message": str(e)}}
        finally:
            if ws:
                try:
                    ws.close()
                except Exception:
                    pass


class OneplayProvider(BaseProvider):
    provider_id = "oneplay"
    display_name = "Oneplay"

    MD_CHANNELS = {
        "Oneplay Sport 1": 8,
        "Oneplay Sport 2": 8,
        "Oneplay Sport 3": 4,
        "Oneplay Sport 4": 4,
    }

    def __init__(self):
        self.api = OneplayAPI()
        self._lock = threading.Lock()
        self._channels_cache: Optional[List[Dict[str, Any]]] = None
        self._channels_cache_time: float = 0
        self._stream_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    def is_authenticated(self) -> bool:
        token = config.get("oneplay_token")
        valid_to = int(config.get("oneplay_token_valid_to") or 0)
        return bool(token and valid_to > int(time.time()))

    def ensure_authenticated(self) -> bool:
        """Ensures an active session exists; re-authenticates if expired."""
        with self._lock:
            if self.is_authenticated():
                return True

            username = config.get("oneplay_username")
            password = config.get("oneplay_password")
            if not username or not password:
                return False

            logger.info(f"Authenticating with Oneplay as {username}...")
            # Step 1: Login
            post = {
                "payload": {
                    "command": {
                        "schema": "LoginWithCredentialsCommand",
                        "email": username,
                        "password": password,
                    }
                }
            }
            res = self.api.call_api("user.login.step", data=post)
            res_data = res.get("data") or res.get("result", {}).get("data") or {}
            step = res_data.get("step") or {}

            # Step 2: Account Selection (if prompted)
            if step.get("schema") == "ShowAccountChooserStep":
                account_id = config.get("oneplay_account_id")
                if not account_id:
                    # Select first active or last account
                    accounts = [
                        a for g in (step.get("groups") or [])
                        for a in (g.get("accounts") or [])
                        if a.get("accountId")
                    ]
                    account_id = accounts[0].get("accountId") if accounts else None

                if account_id:
                    post_account = {
                        "payload": {
                            "command": {
                                "schema": "LoginWithAccountCommand",
                                "accountId": account_id,
                                "authCode": step.get("authToken"),
                            }
                        }
                    }
                    res_acc = self.api.call_api("user.login.step", data=post_account)
                    res_data = res_acc.get("data") or res_acc.get("result", {}).get("data") or {}
                    step = res_data.get("step") or {}

            token = step.get("bearerToken")
            current_user = step.get("currentUser") or step.get("user", {}).get("loggedUser", {})
            current_device = current_user.get("currentDevice") or {}
            device_id = current_device.get("id")

            # Step 3: Manage Device Slots
            if device_id and token:
                self._manage_devices(device_id, token)

            # Step 4: Profile Selection
            target_profile_id = config.get("oneplay_profile_id")
            if not target_profile_id and token:
                profiles_res = self.api.call_api("user.profiles.display", data={"payload": {"mode": "change"}}, token=token)
                p_data = profiles_res.get("data") or profiles_res.get("result", {}).get("data") or {}
                profiles = (p_data.get("availableProfiles") or {}).get("profiles") or []
                wanted_name = config.get("oneplay_profile")
                for p in profiles:
                    prof = p.get("profile") or {}
                    if not target_profile_id or prof.get("name") == wanted_name:
                        target_profile_id = prof.get("id")

            if target_profile_id and token:
                pin = config.get("oneplay_pin", "4321")
                post_prof: Dict[str, Any] = {"payload": {"profileId": target_profile_id}}
                if pin and pin != "4321":
                    post_prof["authorization"] = [{"schema": "PinRequestAuthorization", "pin": str(pin), "type": "profile"}]
                prof_res = self.api.call_api("user.profile.select", data=post_prof, token=token)
                prof_data = prof_res.get("data") or prof_res.get("result", {}).get("data") or {}
                if prof_data.get("bearerToken"):
                    token = prof_data.get("bearerToken")

            if token:
                valid_to = int(time.time() + (4 * 3600))  # 4 hours
                config.update({
                    "oneplay_token": token,
                    "oneplay_token_valid_to": valid_to,
                    "oneplay_logged": True,
                })
                logger.info("Successfully authenticated with Oneplay.")
                return True

            logger.error("Failed to complete Oneplay authentication.")
            return False

    def _manage_devices(self, current_device_id: str, token: str):
        """Names current device and auto-prunes stale duplicates to avoid account lockout."""
        device_name = config.get("oneplay_device_name", "SWEETtv-Oneplay")
        try:
            self.api.call_api("user.device.change", data={"payload": {"id": current_device_id, "name": device_name}}, token=token)
            devices_res = self.api.call_api("setting.display", data={"payload": {"screen": "devices"}}, token=token)
            d_data = devices_res.get("data") or devices_res.get("result", {}).get("data") or {}
            screen = d_data.get("screen") or {}
            devices = []
            for b in screen.get("blocks") or []:
                if b.get("schema") == "SettingUserDevicesBlock":
                    devices = b.get("devices", {}).get("devices") or []
                    break

            for d in devices:
                if d.get("id") != current_device_id and d.get("name") == device_name:
                    logger.info(f"Pruning stale Oneplay duplicate device {d.get('id')}")
                    self.api.call_api("user.device.remove", data={"payload": {"criteria": {"schema": "UserDeviceIdCriteria", "id": d.get("id")}}}, token=token)
        except Exception as e:
            logger.warning(f"Error managing Oneplay devices: {e}")

    def get_channels(self, force_refresh: bool = False, need_epg: bool = False) -> List[Dict[str, Any]]:
        now = time.time()
        with self._lock:
            if not force_refresh and self._channels_cache and (now - self._channels_cache_time < 900):
                return self._channels_cache

        if not self.ensure_authenticated():
            return []

        token = config.get("oneplay_token")
        profile_id = config.get("oneplay_profile_id")
        res = self.api.call_api("epg.channels.display", data={"payload": {"profileId": str(profile_id or "")}}, token=token)
        data = res.get("data") or res.get("result", {}).get("data") or {}
        channel_list = data.get("channelList") or []

        channels = []
        base_order = 1000  # Oneplay channels offset

        for ch in channel_list:
            flags = ch.get("flags") or []
            if ch.get("upsell") or "upsell" in flags:
                continue

            cid = str(ch.get("id"))
            cname = ch.get("name", "")
            try:
                order_num = base_order + int(ch.get("order", 0))
            except (ValueError, TypeError):
                order_num = base_order + len(channels) + 1

            logo_raw = ch.get("logo") or ""
            icon = logo_raw.replace("{WIDTH}", "390").replace("{HEIGHT}", "228") if logo_raw else ""

            ch_dict = {
                "id": cid,
                "canonical_id": f"oneplay:{cid}",
                "name": cname,
                "channel_number": order_num,
                "icon": icon,
                "category": ["Oneplay"],
                "catchup": True,
                "catchup_duration": 7,
                "adult": "adult" in flags,
                "epg": [],
                "provider": self.provider_id,
            }
            channels.append(ch_dict)

            # Check for Multi-Dimension (MD) sub-streams (e.g. Oneplay Sport 1..4)
            if cname in self.MD_CHANNELS:
                count = self.MD_CHANNELS[cname]
                for stream_idx in range(1, count + 1):
                    md_id = f"{cid}~{stream_idx}"
                    channels.append({
                        "id": md_id,
                        "canonical_id": f"oneplay:{md_id}",
                        "name": f"{cname} MD {stream_idx}",
                        "channel_number": order_num + (stream_idx * 100),
                        "icon": icon,
                        "category": ["Oneplay Sport MD"],
                        "catchup": True,
                        "catchup_duration": 7,
                        "adult": False,
                        "epg": [],
                        "provider": self.provider_id,
                    })

        with self._lock:
            self._channels_cache = channels
            self._channels_cache_time = now

        return channels

    def get_stream_details(
        self,
        channel_id: str,
        epg_id: Optional[str] = None,
        utc_time: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        clean_cid = channel_id.replace("oneplay:", "")
        if not self.ensure_authenticated():
            return None

        token = config.get("oneplay_token")
        md = "~" in clean_cid
        base_cid = clean_cid.split("~")[0] if md else clean_cid
        md_stream_num = int(clean_cid.split("~")[1]) if md else 1

        # Check adult PIN
        post: Dict[str, Any] = {
            "payload": {
                "criteria": {"schema": "ContentCriteria", "contentId": f"channel.{base_cid}"},
                "startMode": "start",
            },
            "playbackCapabilities": {
                "protocols": ["dash", "hls"],
                "drm": ["widevine", "fairplay"],
                "altTransfer": "Unicast",
                "subtitle": {"formats": ["vtt"], "locations": ["InstreamTrackLocation", "ExternalTrackLocation"]},
                "liveSpecificCapabilities": {
                    "protocols": ["dash", "hls"],
                    "drm": ["widevine", "fairplay"],
                    "altTransfer": "Unicast",
                    "multipleAudio": False,
                },
            },
        }

        pin = config.get("oneplay_pin", "4321")
        if pin and pin != "4321":
            post["authorization"] = [{"schema": "PinRequestAuthorization", "pin": str(pin), "type": "parental"}]

        # Catchup seek handling
        now_ts = int(time.time())
        if utc_time and utc_time < (now_ts - 10):
            # Query specific catchup payload or use timeshift begin
            logger.info(f"Requesting Oneplay catchup for {clean_cid} at UTC {utc_time}")

        play_res = self.api.call_api("content.play", data=post, token=token)
        play_data = play_res.get("data") or play_res.get("result", {}).get("data") or {}

        # Handle MD stream selection from mosaic
        if md:
            live_ctrl = play_data.get("playerControl", {}).get("liveControl", {})
            mosaic_items = live_ctrl.get("mosaic", {}).get("items") or []
            if len(mosaic_items) >= md_stream_num:
                md_item = mosaic_items[md_stream_num - 1]
                md_payload = md_item.get("play", {}).get("params", {}).get("payload") or {}
                md_content_id = md_payload.get("criteria", {}).get("contentId") or md_payload.get("contentId")
                if md_content_id:
                    md_post = dict(post)
                    md_post["payload"] = {"criteria": {"schema": "MDPlaybackCriteria", "contentId": md_content_id, "position": 0}, "startMode": "start"}
                    md_res = self.api.call_api("content.play", data=md_post, token=token)
                    play_data = md_res.get("data") or md_res.get("result", {}).get("data") or {}

        # Extract clear HLS asset
        media = play_data.get("media") or {}
        stream = media.get("stream") or {}
        assets = stream.get("assets") or []

        stream_url = None
        for asset in assets:
            if asset.get("protocol") == "hls" and "drm" not in asset:
                src = asset.get("src")
                if src and ("clear" in src or "free" in src or not stream_url):
                    stream_url = src

        if not stream_url:
            for asset in assets:
                if asset.get("protocol") == "hls":
                    stream_url = asset.get("src")
                    break

        if not stream_url:
            logger.error(f"No HLS stream URL returned from Oneplay for channel {clean_cid}")
            return None

        # Apply catchup offset if requested
        if utc_time and "begin=" in stream_url:
            stream_url = re.sub(r'([?&]begin=)[^&#]*', rf'\g<1>{int(utc_time)}', stream_url, count=1)

        return {
            "master_url": stream_url,
            "direct_redirect": False,  # Oneplay requires manifest proxying due to Firefox UA header requirement
            "provider": self.provider_id,
            "channel_id": clean_cid,
        }

    def rewrite_manifest(self, url: str, base_url: str) -> str:
        """
        Fetches master/variant manifest with browser headers, proxies variant .m3u8 playlists
        and leaves .ts segment chunks pointing DIRECTLY to Oneplay CDN nodes for zero bandwidth usage.
        """
        headers = {
            "User-Agent": self.api.ua,
            "Accept": "*/*",
            "Accept-Encoding": "gzip",
        }
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=12) as resp:
                final_url = resp.geturl() or url
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)

            text = raw.decode("utf-8", errors="replace")
            lines = text.splitlines()
            base_dir = final_url.rsplit("/", 1)[0] + "/"
            parsed_parent = urllib.parse.urlparse(final_url)
            parent_query = urllib.parse.parse_qs(parsed_parent.query)

            result = []
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    result.append(line)
                    continue

                if line.startswith("#"):
                    if 'URI="' in line:
                        def repl_uri(m):
                            sub_uri = m.group(1)
                            if not sub_uri.startswith("http"):
                                sub_uri = urllib.parse.urljoin(base_dir, sub_uri)
                            proxy_url = f"{base_url}/stream/oneplay/proxy_hls?url={urllib.parse.quote(sub_uri, safe='')}"
                            return f'URI="{proxy_url}"'
                        result.append(re.sub(r'URI="([^"]+)"', repl_uri, line))
                    else:
                        result.append(line)
                else:
                    # Media variant or chunk line
                    full_uri = stripped if stripped.startswith("http") else urllib.parse.urljoin(base_dir, stripped)
                    if ".m3u8" in full_uri:
                        # Variant playlist -> route via proxy
                        proxy_url = f"{base_url}/stream/oneplay/proxy_hls?url={urllib.parse.quote(full_uri, safe='')}"
                        result.append(proxy_url)
                    else:
                        # Video TS segment -> Direct CDN URL!
                        result.append(full_uri)

            return "\n".join(result)

        except Exception as e:
            logger.error(f"Error rewriting Oneplay manifest from {url}: {e}")
            return "#EXTM3U\n"

    def get_epg_schedule(self, days_back: int = 1, days_forward: int = 1) -> Dict[str, Any]:
        """Fetches EPG schedule for all subscribed channels."""
        if not self.ensure_authenticated():
            return {}

        token = config.get("oneplay_token")
        now_ts = int(time.time())
        from_ts = now_ts - (days_back * 86400)
        to_ts = now_ts + (days_forward * 86400)

        post = {
            "payload": {
                "criteria": {
                    "channelSetId": "channel_list.1",
                    "viewport": {
                        "channelRange": {"from": 0, "to": 200},
                        "timeRange": {
                            "from": datetime.fromtimestamp(from_ts).strftime("%Y-%m-%dT%H:%M:%S") + ".000Z",
                            "to": datetime.fromtimestamp(to_ts).strftime("%Y-%m-%dT%H:%M:%S") + ".000Z",
                        },
                        "schema": "EpgViewportAbsolute",
                    },
                },
                "requestedOutput": {
                    "channelList": "none",
                    "datePicker": False,
                    "channelSets": False,
                },
            }
        }
        res = self.api.call_api("epg.display", data=post, token=token)
        return res.get("data") or res.get("result", {}).get("data") or {}
