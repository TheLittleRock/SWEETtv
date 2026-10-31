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
        self._epg_cache: Dict[str, Dict[int, Dict[str, Any]]] = {}  # cid -> {startts: item}
        self._epg_cache_time: float = 0

    def is_authenticated(self) -> bool:
        token = config.get("oneplay_token")
        if not token:
            return False
        valid_to = int(config.get("oneplay_token_valid_to") or 0)
        # If valid_to is 0 or unset, token remains active while oneplay_logged is true
        if valid_to == 0:
            return bool(config.get("oneplay_logged"))
        return valid_to > int(time.time())

    def ensure_authenticated(self) -> bool:
        """Ensures an active session exists; re-authenticates if expired."""
        with self._lock:
            if self.is_authenticated():
                return True

            username = config.get("oneplay_username")
            password = config.get("oneplay_password")
            if not username or not password:
                # If credentials not configured, preserve active session if token exists
                token = config.get("oneplay_token")
                return bool(token and config.get("oneplay_logged"))

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

    def _extract_image_url(self, img_obj: Any, width: int = 320, height: int = 480) -> str:
        """Robustly extracts and formats image URL from Jyxo CMS image objects or strings."""
        if not img_obj:
            return ""
        if isinstance(img_obj, dict):
            url = (
                img_obj.get("urlTemplate") or
                img_obj.get("image") or
                img_obj.get("src") or
                img_obj.get("url") or
                img_obj.get("poster") or
                ""
            )
        elif isinstance(img_obj, str):
            url = img_obj
        else:
            url = ""
        if url:
            url = (
                url.replace("{WIDTH}", str(width))
                   .replace("{HEIGHT}", str(height))
                   .replace("{w}", str(width))
                   .replace("{h}", str(height))
            )
        return url

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

            icon = self._extract_image_url(ch.get("logo"), 390, 228)

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
            logger.info(f"Resolving Oneplay catchup for {clean_cid} at UTC {utc_time}")
            # Ensure EPG cache for base_cid is available
            if base_cid not in self._epg_cache or not self._epg_cache[base_cid]:
                self.get_channel_epg(base_cid)

            channel_shows = self._epg_cache.get(base_cid, {})
            target_show = None
            if epg_id:
                target_show = next((s for s in channel_shows.values() if str(s.get("referenceid")) == str(epg_id)), None)

            if not target_show and channel_shows:
                # Find show containing utc_time or closest preceding show
                for s_ts, s_item in sorted(channel_shows.items()):
                    if s_item["startts"] <= utc_time < s_item["endts"]:
                        target_show = s_item
                        break
                if not target_show:
                    # Pick closest within 4 hours
                    closest = min(channel_shows.values(), key=lambda x: abs(x["startts"] - utc_time))
                    if abs(closest["startts"] - utc_time) < (4 * 3600):
                        target_show = closest

            if target_show and target_show.get("payload"):
                logger.info(f"Found catchup show: '{target_show.get('title')}' - requesting play payload via _resolve_playable_payload")
                resolved_payload = self._resolve_playable_payload(target_show["payload"])
                if resolved_payload:
                    post["payload"] = resolved_payload

        play_res = self.api.call_api("content.play", data=post, token=token)
        play_data = play_res.get("data") or play_res.get("result", {}).get("data") or {}

        if not play_data.get("media") and post.get("payload", {}).get("startMode") != "live":
            # Fallback to live start mode if catchup payload failed
            logger.info("Catchup payload did not return media, falling back to startMode live")
            post["payload"] = {
                "criteria": {"schema": "ContentCriteria", "contentId": f"channel.{base_cid}"},
                "startMode": "live"
            }
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
            parsed_u = urllib.parse.urlparse(stream_url)
            q = urllib.parse.parse_qs(parsed_u.query)
            if "begin" in q:
                cur_begin = int(q["begin"][0])
                target_begin = int(utc_time)
                new_begin = max(cur_begin, target_begin)
                if "end" in q:
                    end_val = int(q["end"][0])
                    new_begin = min(new_begin, end_val - 1)
                stream_url = re.sub(r'([?&]begin=)[^&#]*', rf'\g<1>{new_begin}', stream_url, count=1)
            else:
                stream_url = re.sub(r'([?&]begin=)[^&#]*', rf'\g<1>{int(utc_time)}', stream_url, count=1)

        return {
            "master_url": stream_url,
            "direct_redirect": False,  # Oneplay requires manifest proxying due to Firefox UA header requirement
            "provider": self.provider_id,
            "channel_id": clean_cid,
            "is_catchup": bool(utc_time)
        }

    def rewrite_manifest(self, url: str, base_url: str, start_at_begin: bool = False) -> str:
        """
        Fetches master/variant manifest with browser headers, proxies variant .m3u8 playlists
        and leaves .ts segment chunks pointing DIRECTLY to Oneplay CDN nodes with merged query tokens
        for zero bandwidth usage and no 403 Forbidden errors.
        """
        headers = {
            "User-Agent": self.api.ua,
            "Accept": "*/*",
            "Accept-Encoding": "gzip",
        }
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=15) as resp:
                final_url = resp.geturl() or url
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)

            text = raw.decode("utf-8", errors="replace")
            lines = text.splitlines()

            # If start_at_begin is requested for catchup/timeshift, inject #EXT-X-START:TIME-OFFSET=0,PRECISE=YES
            if start_at_begin and any(line.startswith("#EXTINF:") for line in lines):
                lines = [l for l in lines if not l.startswith("#EXT-X-START:")]
                extm3u_idx = next((i for i, l in enumerate(lines) if l.startswith("#EXTM3U")), None)
                if extm3u_idx is not None:
                    lines.insert(extm3u_idx + 1, "#EXT-X-START:TIME-OFFSET=0,PRECISE=YES")

            base_dir = final_url.rsplit("/", 1)[0] + "/"
            base_dir = base_dir.split("?")[0]
            if not base_dir.endswith("/"):
                base_dir += "/"

            parsed_parent = urllib.parse.urlparse(final_url)
            parent_query = urllib.parse.parse_qs(parsed_parent.query)

            def _merge_url(uri: str) -> str:
                if not uri.startswith("http"):
                    uri = urllib.parse.urljoin(base_dir, uri)
                parsed_uri = urllib.parse.urlparse(uri)
                sub_params = urllib.parse.parse_qs(parsed_uri.query)
                merged = dict(parent_query)
                merged.update(sub_params)
                return urllib.parse.urlunparse(parsed_uri._replace(query=urllib.parse.urlencode(merged, doseq=True)))

            start_param = "&start_at_begin=1" if start_at_begin else ""

            def make_proxy_url(uri: str) -> str:
                merged_uri = _merge_url(uri)
                return f"{base_url}/stream/oneplay/proxy_hls?url={urllib.parse.quote(merged_uri, safe='')}{start_param}"

            result = []
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    result.append(line)
                    continue

                if line.startswith("#"):
                    if 'URI="' in line:
                        def repl_uri(m):
                            return f'URI="{make_proxy_url(m.group(1))}"'
                        result.append(re.sub(r'URI="([^"]+)"', repl_uri, line))
                    else:
                        result.append(line)
                else:
                    # Media variant or chunk line
                    if stripped.endswith(".m3u8") or ".m3u8?" in stripped:
                        result.append(make_proxy_url(stripped))
                    else:
                        # Video TS segment -> Direct CDN URL with merged CDN auth token!
                        result.append(_merge_url(stripped))

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

    def get_channel_epg(self, channel_id: str, days_back: int = 7, days_forward: int = 2) -> List[Dict[str, Any]]:
        """
        Fetches up to 7 days of past EPG (with catchup capability) and 2 days of future schedule.
        Caches results per channel in memory.
        """
        clean_cid = channel_id.replace("oneplay:", "").strip()
        base_cid = clean_cid.split("~")[0]
        now_ts = int(time.time())

        # Check if cache is fresh (< 30 mins) and contains base_cid
        with self._lock:
            if (now_ts - self._epg_cache_time < 1800) and base_cid in self._epg_cache and self._epg_cache[base_cid]:
                items = list(self._epg_cache[base_cid].values())
                items.sort(key=lambda x: x["startts"])
                return [
                    {
                        "id": str(p.get("referenceid") or f"{clean_cid}_{p['startts']}"),
                        "title": p.get("title", ""),
                        "description": p.get("description", ""),
                        "time_start": p["startts"],
                        "time_stop": p["endts"],
                        "duration": p["endts"] - p["startts"],
                        "can_replay": p["endts"] <= (now_ts - 5) and p["startts"] >= (now_ts - (7 * 86400)),
                        "cover": p.get("cover", ""),
                        "payload": p.get("payload", {})
                    }
                    for p in items
                ]

        if not self.ensure_authenticated():
            return []

        token = config.get("oneplay_token")
        from_ts = now_ts - (days_back * 86400)
        to_ts = now_ts + (days_forward * 86400)

        post = {
            "payload": {
                "criteria": {
                    "channelSetId": "channel_list.1",
                    "viewport": {
                        "channelRange": {"from": 0, "to": 250},
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

        logger.info(f"Fetching Oneplay EPG schedule ({days_back}d past, {days_forward}d ahead)...")
        res = self.api.call_api("epg.display", data=post, token=token)
        data = res.get("data") or res.get("result", {}).get("data") or {}
        schedule = data.get("schedule") or []

        with self._lock:
            for ch in schedule:
                cid = str(ch.get("channelId"))
                if cid not in self._epg_cache:
                    self._epg_cache[cid] = {}
                for it in (ch.get("items") or []):
                    try:
                        s_iso = it.get("startAt", "")
                        e_iso = it.get("endAt", "")
                        if not s_iso or not e_iso:
                            continue
                        s_ts = int(datetime.fromisoformat(s_iso.replace("Z", "+00:00")).timestamp())
                        e_ts = int(datetime.fromisoformat(e_iso.replace("Z", "+00:00")).timestamp())
                        img = self._extract_image_url(it.get("image"), 480, 320)
                        actions = it.get("actions") or [{}]
                        params = actions[0].get("params") or {}
                        payload = params.get("payload") or {}
                        ref_id = it.get("referenceId") or f"{cid}_{s_ts}"

                        self._epg_cache[cid][s_ts] = {
                            "referenceid": ref_id,
                            "title": it.get("title", ""),
                            "description": it.get("description", ""),
                            "startts": s_ts,
                            "endts": e_ts,
                            "cover": img,
                            "payload": payload,
                            "contentType": params.get("contentType")
                        }
                    except Exception:
                        continue

            self._epg_cache_time = now_ts

        channel_items = list(self._epg_cache.get(base_cid, {}).values())
        channel_items.sort(key=lambda x: x["startts"])
        return [
            {
                "id": str(p.get("referenceid") or f"{clean_cid}_{p['startts']}"),
                "title": p.get("title", ""),
                "description": p.get("description", ""),
                "time_start": p["startts"],
                "time_stop": p["endts"],
                "duration": p["endts"] - p["startts"],
                "can_replay": p["endts"] <= (now_ts - 5) and p["startts"] >= (now_ts - (7 * 86400)),
                "cover": p.get("cover", ""),
                "payload": p.get("payload", {})
            }
            for p in channel_items
        ]

    def _parse_tiles(self, tiles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Standardizes VOD tile objects from Jyxo CMS into app VOD format."""
        parsed = []
        for tile in tiles:
            params = tile.get("action", {}).get("params") or {}
            if tile.get("tracking", {}).get("upsell") or params.get("action", {}).get("call") == "user.upsell.preview":
                continue

            tracking = tile.get("tracking") or {}
            raw_type = str(tracking.get("type") or params.get("contentType") or "").lower()
            if raw_type in ("show", "series", "podcast", "serial"):
                content_type = "show"
            elif raw_type in ("recording", "dvr", "nahravka"):
                content_type = "recording"
            else:
                content_type = "movie"

            payload = params.get("payload") or {}
            content_id = payload.get("contentId") or payload.get("criteria", {}).get("contentId") or tile.get("id") or str(tile.get("referenceId", ""))
            if not content_id and payload.get("deeplink"):
                content_id = str(payload.get("deeplink", {}).get("epgItem") or "")

            poster = self._extract_image_url(tile.get("image"), 320, 480)

            year = tracking.get("year") or tile.get("year") or ""
            duration = tracking.get("duration") or tile.get("duration") or 0

            parsed.append({
                "id": str(content_id or os.urandom(6).hex()),
                "title": tile.get("title") or "Bez názvu",
                "content_type": content_type,
                "image": poster,
                "description": tile.get("description") or tile.get("subTitle") or "",
                "year": str(year) if year else "",
                "duration": duration,
                "is_drm": True,
                "payload": payload,
            })
        return parsed

    def get_vod_categories(self) -> List[Dict[str, Any]]:
        """Returns top-level VOD categories."""
        default_cats = [
            {"id": "all", "title": "⭐ Vše", "categoryId": "2"},
            {"id": "movies", "title": "🎬 Filmy", "categoryId": "2"},
            {"id": "series", "title": "📺 Seriály", "categoryId": "1"},
            {"id": "recordings", "title": "📼 Nahrávky (Cloud DVR)", "categoryId": "8"},
        ]
        if not self.ensure_authenticated():
            return default_cats

        token = config.get("oneplay_token")
        try:
            init_res = self.api.call_api("app.init", data={"payload": {"reason": "start"}}, token=token)
            init_data = init_res.get("data") or init_res.get("result", {}).get("data") or {}
            cats = [{"id": "all", "title": "⭐ Vše", "categoryId": "2"}]
            for group in (init_data.get("menu", {}).get("groups") or []):
                if group.get("position") == "top":
                    for item in (group.get("items") or []):
                        action = item.get("action", {})
                        if action.get("call") == "page.category.display":
                            p = action.get("params", {}).get("payload") or {}
                            cat_id = p.get("categoryId") or item.get("id")
                            cats.append({
                                "id": str(cat_id),
                                "title": item.get("title", f"Kategorie {cat_id}"),
                                "categoryId": str(cat_id),
                            })
            if len(cats) > 1:
                if not any(c.get("categoryId") == "8" or c["id"] == "recordings" for c in cats):
                    cats.append({"id": "8", "title": "📼 Nahrávky (Cloud DVR)", "categoryId": "8"})
                return cats
        except Exception as e:
            logger.warning(f"Error fetching Oneplay categories via app.init: {e}")

        return default_cats

    def get_vod_items(
        self,
        category: str = "all",
        page: int = 1,
        query: Optional[str] = None,
        all_pages: bool = False
    ) -> Dict[str, Any]:
        """Fetches catalog items for a category or search query with pagination."""
        if not self.ensure_authenticated():
            return {"items": [], "page": page, "has_more": False}

        token = config.get("oneplay_token")
        items: List[Dict[str, Any]] = []
        has_more = False

        try:
            if query:
                res = self.api.call_api("page.search.display", data={"payload": {"query": query}}, token=token)
                data = res.get("data") or res.get("result", {}).get("data") or {}
                layout = data.get("layout") or {}
                blocks = layout.get("blocks") or []
                carousels = self._find_all_carousels(blocks)
                for c in carousels:
                    items.extend(self._parse_tiles(c.get("tiles") or []))
            else:
                cat_id = "2" if category == "movies" else ("1" if category == "series" else ("8" if category == "recordings" else category))
                if cat_id in ("all", ""):
                    cat_id = "2"

                res = self.api.call_api("page.category.display", data={"payload": {"categoryId": str(cat_id)}}, token=token)
                data = res.get("data") or res.get("result", {}).get("data") or []
                blocks = data if isinstance(data, list) else (data.get("layout", {}).get("blocks") or [])

                all_carousels = self._find_all_carousels(blocks)
                for c in all_carousels:
                    c_tiles = c.get("tiles") or []
                    items.extend(self._parse_tiles(c_tiles))
                    paging = c.get("paging") or {}

                    # If all_pages is requested (e.g. for Xtream catalog indexing), paginate carousels
                    if all_pages and paging.get("criteria"):
                        pos = len(c_tiles) + 1
                        while pos <= 300:
                            c_post = {
                                "payload": {
                                    "criteria": paging.get("criteria"),
                                    "carouselId": c.get("id"),
                                    "paging": {"count": 24, "position": pos}
                                }
                            }
                            c_res = self.api.call_api("carousel.display", data=c_post, token=token)
                            c_data = c_res.get("data") or c_res.get("result", {}).get("data") or {}
                            c_more_tiles = c_data.get("tiles") or []
                            if not c_more_tiles:
                                break
                            items.extend(self._parse_tiles(c_more_tiles))
                            if not c_data.get("paging", {}).get("next") or len(c_more_tiles) < 24:
                                break
                            pos += len(c_more_tiles)
                    elif page > 1 and paging.get("criteria"):
                        c_post = {
                            "payload": {
                                "criteria": paging.get("criteria"),
                                "carouselId": c.get("id"),
                                "paging": {"count": 24, "position": (page - 1) * 24 + 1}
                            }
                        }
                        c_res = self.api.call_api("carousel.display", data=c_post, token=token)
                        c_data = c_res.get("data") or c_res.get("result", {}).get("data") or {}
                        c_more_tiles = c_data.get("tiles") or []
                        items.extend(self._parse_tiles(c_more_tiles))
                        has_more = bool(c_data.get("paging", {}).get("next"))
                    else:
                        has_more = bool(paging.get("next")) or has_more

        except Exception as e:
            logger.error(f"Error fetching Oneplay VOD items: {e}")

        # Deduplicate
        unique_items = []
        seen = set()
        for item in items:
            iid = item.get("id")
            if iid and iid not in seen:
                seen.add(iid)
                unique_items.append(item)

        # Filter according to category
        if category == "series":
            filtered_items = [it for it in unique_items if it.get("content_type") == "show"]
        elif category == "movies":
            filtered_items = [it for it in unique_items if it.get("content_type") == "movie"]
        elif category == "recordings":
            filtered_items = [it for it in unique_items if it.get("content_type") == "recording"]
        else:
            filtered_items = unique_items

        return {
            "items": filtered_items,
            "page": page,
            "has_more": has_more or len(filtered_items) >= 24
        }

    def _find_all_carousels(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Recursively traverses layout blocks to locate all carousels at any nesting level."""
        found = []
        for b in blocks:
            if not isinstance(b, dict):
                continue
            for c in (b.get("carousels") or []):
                if isinstance(c, dict):
                    found.append(c)
            # Nested layout blocks (TabBlock, SectionBlock, LayoutBlock, etc.)
            nested = b.get("layout", {}).get("blocks") or b.get("blocks") or []
            if nested:
                found.extend(self._find_all_carousels(nested))
        return found

    def get_series_detail(self, series_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Fetches seasons and episodes for a TV series from Jyxo CMS layout."""
        if not self.ensure_authenticated():
            return {}
        token = config.get("oneplay_token")
        try:
            res = self.api.call_api("page.content.display", data={"payload": series_payload}, token=token)
            data = res.get("data") or res.get("result", {}).get("data") or {}
            meta = data.get("metadata") or {}
            layout = data.get("layout") or {}
            blocks = layout.get("blocks") or []

            show_play_payload = None
            is_movie = False
            for b in blocks:
                if b.get("schema") == "ContentHeaderBlock":
                    act = b.get("mainAction", {}).get("action") or {}
                    if act.get("call") == "content.play":
                        show_play_payload = act.get("params", {}).get("payload")
                    c_type = str(b.get("contentType") or b.get("tracking", {}).get("type") or "").lower()
                    if c_type in ("movie", "film"):
                        is_movie = True
                if not meta and b.get("schema") == "ContentHeaderBlock":
                    meta = b

            raw_type = str(data.get("metadata", {}).get("contentType") or data.get("tracking", {}).get("type") or "").lower()
            if raw_type in ("movie", "film"):
                is_movie = True

            seasons = []
            episodes = []

            # If this is a movie, it does not have seasons or episodes (avoid treating franchise/similar movies as episodes)
            if not is_movie:
                # Find all carousels recursively across all blocks and tabs
                carousels = self._find_all_carousels(blocks)

                for carousel in carousels:
                    c_title = str(carousel.get("title") or "").lower()
                    # CRITICAL: Never treat recommendations, franchise collections or similar movies as episodes!
                    if any(ignored in c_title for ignored in ("podobné", "doporuč", "další filmy", "mohlo by se", "podobne", "kolekce", "související", "ze série")):
                        continue

                    # Check for seasons criteria (template == "showSeason")
                    criteria_list = carousel.get("criteria") or []
                    has_season_criteria = False
                    for crit in criteria_list:
                        if crit.get("template") == "showSeason":
                            has_season_criteria = True
                            for item in (crit.get("items") or []):
                                if item.get("label") and item.get("criteria"):
                                    seasons.append({
                                        "label": str(item["label"]),
                                        "carouselId": carousel.get("id"),
                                        "criteria": item["criteria"],
                                    })

                    # If this is an episode carousel (has season criteria, or title specifically mentions episodes)
                    is_episode_carousel = has_season_criteria or any(k in c_title for k in ("epizod", "díl", "episodes"))
                    if is_episode_carousel and not seasons:
                        for t in (carousel.get("tiles") or []):
                            t_action = t.get("action") or {}
                            if t_action.get("call") == "content.play" or "contentId" in (t_action.get("params") or {}).get("payload", {}):
                                p = (t_action.get("params") or {}).get("payload") or {}
                                episodes.append({
                                    "id": str(p.get("contentId") or t.get("id")),
                                    "title": t.get("title", ""),
                                    "description": t.get("description") or t.get("subTitle") or "",
                                    "duration": t.get("duration", 0),
                                    "image": self._extract_image_url(t.get("image"), 480, 270),
                                    "payload": p,
                                    "is_drm": True,
                                })

                if seasons:
                    import re
                    def _season_sort_key(s):
                        lbl = str(s.get("label", ""))
                        nums = re.findall(r"\d+", lbl)
                        return int(nums[0]) if nums else 999
                    seasons.sort(key=_season_sort_key)

                    # Pre-fetch first season episodes if episodes list is empty
                    if not episodes and seasons[0].get("carouselId") and seasons[0].get("criteria"):
                        episodes = self.get_season_episodes(seasons[0]["carouselId"], seasons[0]["criteria"])

            poster = self._extract_image_url(meta.get("image") or data.get("image") or data.get("backdrop"), 800, 450)

            return {
                "title": meta.get("title") or data.get("title", ""),
                "description": meta.get("description") or meta.get("plot") or data.get("description", ""),
                "image": poster,
                "seasons": seasons,
                "episodes": episodes,
                "payload": show_play_payload or series_payload
            }
        except Exception as e:
            logger.error(f"Error fetching series detail: {e}")
            return {}

    def get_season_episodes(self, carousel_id: str, criteria: Any, sort_order: str = "DESC") -> List[Dict[str, Any]]:
        """
        Fetches all episodes of a given series season via pagination loop.
        Reverses the episode list to chronological ascending order (oldest episode first).
        """
        if not self.ensure_authenticated():
            return []
        token = config.get("oneplay_token")
        try:
            crit_val = criteria
            if isinstance(criteria, dict):
                crit_val = criteria.get("filterCriterias") or criteria.get("criteria") or criteria

            all_tiles: List[Dict[str, Any]] = []
            position = 1
            max_episodes = 500  # Cap per season

            while position <= max_episodes:
                c_post = {
                    "payload": {
                        "carouselId": carousel_id,
                        "criteria": {"filterCriterias": crit_val, "sortOption": sort_order},
                        "paging": {"count": 12, "position": position}
                    }
                }
                res = self.api.call_api("carousel.display", data=c_post, token=token)
                data = res.get("data") or res.get("result", {}).get("data") or {}

                tiles = []
                carousel_obj = data.get("carousel") if isinstance(data, dict) else {}
                if isinstance(carousel_obj, dict):
                    tiles = carousel_obj.get("tiles") or []
                if not tiles and isinstance(data, dict):
                    tiles = data.get("tiles") or []
                if not tiles and isinstance(data, dict):
                    for c in (data.get("carousels") or []):
                        if c.get("tiles"):
                            tiles.extend(c["tiles"])

                # Fallback to ASC sort order on first page if DESC returned nothing
                if not tiles and position == 1 and sort_order != "ASC":
                    c_post["payload"]["criteria"]["sortOption"] = "ASC"
                    res_asc = self.api.call_api("carousel.display", data=c_post, token=token)
                    data_asc = res_asc.get("data") or res_asc.get("result", {}).get("data") or {}
                    carousel_obj = data_asc.get("carousel") if isinstance(data_asc, dict) else {}
                    if isinstance(carousel_obj, dict):
                        tiles = carousel_obj.get("tiles") or []
                    if not tiles and isinstance(data_asc, dict):
                        tiles = data_asc.get("tiles") or []
                    if tiles:
                        sort_order = "ASC"

                if not tiles:
                    break

                all_tiles.extend(tiles)

                # Check if there are further pages
                has_next = False
                if isinstance(carousel_obj, dict):
                    has_next = bool(carousel_obj.get("paging", {}).get("next"))
                if not has_next:
                    break

                position += len(tiles)

            # Reverse DESC order to chronological ascending order (oldest first)
            if sort_order == "DESC":
                all_tiles.reverse()

            episodes = []
            for tile in all_tiles:
                params = tile.get("action", {}).get("params") or {}
                payload = params.get("payload") or {}
                poster = self._extract_image_url(tile.get("image"), 480, 270)
                episodes.append({
                    "id": str(payload.get("contentId") or tile.get("id")),
                    "title": tile.get("title", ""),
                    "description": tile.get("description") or tile.get("subTitle") or "",
                    "duration": tile.get("duration", 0),
                    "image": poster,
                    "payload": payload,
                    "is_drm": True,
                })
            return episodes
        except Exception as e:
            logger.error(f"Error fetching season episodes: {e}")
            return []

    def get_recordings(self) -> List[Dict[str, Any]]:
        """Fetches Cloud DVR recordings for current user."""
        res = self.get_vod_items(category="8", page=1)
        return res.get("items", [])

    def _resolve_playable_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        If payload is a display payload (e.g. from catalog tile or EPG),
        resolves it via page.content.display into the actual ContentHeaderBlock play payload.
        """
        if not payload:
            return {}
        criteria = payload.get("criteria", {})
        if "startMode" in payload or criteria.get("schema") in ("MDPlaybackCriteria", "ContentPlaybackCriteria", "ChannelPlaybackCriteria"):
            return payload

        token = config.get("oneplay_token")
        try:
            disp_res = self.api.call_api("page.content.display", data={"payload": payload}, token=token)
            disp_data = disp_res.get("data") or disp_res.get("result", {}).get("data") or {}
            for block in (disp_data.get("layout", {}).get("blocks") or []):
                if block.get("schema") == "ContentHeaderBlock":
                    action = block.get("mainAction", {}).get("action") or {}
                    if action.get("call") == "content.play":
                        resolved = action.get("params", {}).get("payload")
                        if resolved:
                            return resolved
        except Exception as e:
            logger.warning(f"Error resolving playable payload: {e}")
        return payload

    def get_vod_stream(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Calls content.play to retrieve stream URLs and DRM parameters for a VOD title.
        Supports clear HLS and Widevine DRM DASH.
        """
        if not self.ensure_authenticated():
            return None
        token = config.get("oneplay_token")
        try:
            playable_payload = self._resolve_playable_payload(payload)
            if not playable_payload:
                playable_payload = payload
            if "startMode" not in playable_payload:
                playable_payload = dict(playable_payload)
                playable_payload["startMode"] = "start"

            post = {
                "payload": playable_payload,
                "playbackCapabilities": {
                    "protocols": ["dash", "hls"],
                    "drm": ["widevine", "fairplay"],
                    "altTransfer": "Unicast",
                    "subtitle": {
                        "formats": ["vtt"],
                        "locations": ["InstreamTrackLocation", "ExternalTrackLocation"]
                    },
                    "liveSpecificCapabilities": {
                        "protocols": ["dash", "hls"],
                        "drm": ["widevine", "fairplay"],
                        "altTransfer": "Unicast",
                        "multipleAudio": False
                    }
                }
            }
            pin = config.get("oneplay_pin", "4321")
            if pin and pin != "4321":
                post["authorization"] = [{"schema": "PinRequestAuthorization", "pin": str(pin), "type": "parental"}]

            res = self.api.call_api("content.play", data=post, token=token)
            data = res.get("data") or res.get("result", {}).get("data") or {}
            assets = data.get("media", {}).get("stream", {}).get("assets") or []

            # 1. Clear HLS
            for asset in assets:
                if asset.get("protocol") == "hls" and "drm" not in asset:
                    return {
                        "manifest_type": "hls",
                        "url": asset.get("src"),
                        "is_drm": False,
                        "drm": None,
                    }

            # 2. Widevine DRM DASH
            for asset in assets:
                if asset.get("protocol") == "dash" and "drm" in asset:
                    drm_info = asset.get("drm") or [{}]
                    lic_url = drm_info[0].get("licenseAcquisitionURL")
                    ax_token = drm_info[0].get("drmAuthorization", {}).get("value") or ""
                    return {
                        "manifest_type": "mpd",
                        "url": asset.get("src"),
                        "is_drm": True,
                        "drm": {
                            "type": "widevine",
                            "license_url": lic_url,
                            "token": ax_token,
                        }
                    }

            # 3. Any DASH
            for asset in assets:
                if asset.get("protocol") == "dash":
                    return {
                        "manifest_type": "mpd",
                        "url": asset.get("src"),
                        "is_drm": False,
                        "drm": None,
                    }

            # 4. Fallback HLS
            for asset in assets:
                if asset.get("protocol") == "hls":
                    return {
                        "manifest_type": "hls",
                        "url": asset.get("src"),
                        "is_drm": False,
                        "drm": None,
                    }

        except Exception as e:
            logger.error(f"Error fetching Oneplay VOD stream: {e}")

        return None



