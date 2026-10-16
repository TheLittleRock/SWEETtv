import json
import logging
import threading
import time
import uuid
from typing import Any, Dict, Optional
import requests
import urllib3

from app.config import config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger("SweetTV.Client")


class SweetTVClient:
    """Robust client for Sweet.tv API with auto-reauthentication and stream opening."""

    BASE_API_URL = "https://api.sweet.tv/{}"
    DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    VERSION = "3.7.1"

    def __init__(self):
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=50, max_retries=2)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self._refresh_lock = threading.Lock()

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Host": "api.sweet.tv",
            "User-Agent": self.DEFAULT_UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": config.country_code,
            "Accept-Encoding": "gzip, deflate",
            "x-device": f"1;22;0;2;{self.VERSION}",
            "Origin": "https://sweet.tv",
            "DNT": "1",
            "Referer": "https://sweet.tv/",
        }
        bearer = config.get("bearer")
        if bearer:
            headers["Authorization"] = bearer
        return headers

    def _get_device_payload(self) -> Dict[str, Any]:
        return {
            "device": {
                "type": "DT_AndroidTV",
                "mac": config.get("mac"),
                "firmware": {
                    "versionCode": 1301,
                    "versionString": self.VERSION,
                    "modules": []
                },
                "sub_type": "DST_Unknown",
                "uuid": config.get("uuid"),
                "screen_info": {
                    "width": 3840,
                    "height": 2160,
                    "aspectRatio": "AR_16_9"
                },
                "application": {
                    "type": "AT_SWEET_TV_Player"
                },
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
                "system_info": {
                    "network_connection_type": "NCT_Unknown",
                    "os_version": "23",
                    "total_memory": 4,
                    "hardware": ""
                },
                "advertisingId": str(uuid.uuid4())
            }
        }

    def request(self, endpoint: str, method: str = "post", json_data: Any = None, params: Any = None, timeout: int = 15) -> Optional[Dict[str, Any]]:
        url = self.BASE_API_URL.format(endpoint)
        headers = self._get_headers()
        try:
            if method.lower() == "post":
                resp = self.session.post(url, headers=headers, json=json_data, params=params, timeout=timeout, verify=False)
            elif method.lower() == "get":
                resp = self.session.get(url, headers=headers, params=params, timeout=timeout, verify=False)
            else:
                resp = self.session.request(method, url, headers=headers, json=json_data, params=params, timeout=timeout, verify=False)

            if resp.status_code in (200, 201):
                return resp.json()
            elif resp.status_code == 401:
                logger.warning(f"Unauthorized (401) on {endpoint}. Attempting token refresh...")
                if self.refresh_token(force=True):
                    # Retry once with renewed bearer
                    headers = self._get_headers()
                    retry_resp = self.session.post(url, headers=headers, json=json_data, params=params, timeout=timeout, verify=False)
                    if retry_resp.status_code in (200, 201):
                        return retry_resp.json()
                logger.error(f"Request failed with 401 on {endpoint} and token refresh was unsuccessful.")
                return None
            else:
                logger.warning(f"Request to {endpoint} returned HTTP {resp.status_code}: {resp.text[:200]}")
                return resp.json() if "application/json" in resp.headers.get("Content-Type", "") else None
        except Exception as e:
            logger.error(f"Network error on {endpoint}: {e}")
            return None

    def refresh_token(self, force: bool = False) -> bool:
        """Refreshes JWT access token before expiration."""
        if not config.get("logged"):
            return False

        with self._refresh_lock:
            last_update = int(config.get("access_token_last_update", 0))
            lifetime = int(config.get("access_token_lifetime", 3600))
            now = int(time.time())

            # If token is still fresh and refresh not forced, return OK
            if not force and (now - last_update < int(lifetime * 0.85)):
                return True

            refresh_token = config.get("refresh_token")
            if not refresh_token:
                logger.warning("No refresh token available.")
                config.set("logged", False)
                return False

            payload = self._get_device_payload()
            payload["refresh_token"] = refresh_token

            logger.info("Refreshing access token with Sweet.tv...")
            resp = self.request("AuthenticationService/Token.json", method="post", json_data=payload)
            if resp and resp.get("access_token"):
                config.update({
                    "bearer": f"Bearer {resp['access_token']}",
                    "access_token_last_update": now,
                    "access_token_lifetime": int(resp.get("expires_in", 3600)),
                    "logged": True,
                })
                logger.info("Access token successfully refreshed.")
                return True
            else:
                logger.error(f"Failed to refresh token: {resp}")
                config.set("logged", False)
                return False

    def start_auth(self) -> Optional[Dict[str, Any]]:
        """Initiates device link workflow."""
        return self.request("SigninService/Start.json", json_data=self._get_device_payload())

    def check_auth(self, auth_code: str) -> Optional[Dict[str, Any]]:
        """Checks status of activation code."""
        url = self.BASE_API_URL.format("SigninService/GetStatus.json")
        headers = self._get_headers()
        headers["Content-Type"] = "application/json"
        try:
            resp = self.session.post(url, headers=headers, json={"auth_code": auth_code}, timeout=15, verify=False)
            data = resp.json()
            if data and data.get("result") == "COMPLETED":
                config.update({
                    "bearer": f"Bearer {data.get('access_token')}",
                    "refresh_token": str(data.get("refresh_token")),
                    "logged": True,
                    "access_token_last_update": int(time.time()),
                    "access_token_lifetime": int(data.get("expires_in", 3600)),
                })
                logger.info("Authentication completed successfully!")
            return data
        except Exception as e:
            logger.error(f"Error checking auth status: {e}")
            return None

    def logout(self) -> bool:
        """Logs out from current session."""
        refresh_token = config.get("refresh_token")
        if refresh_token:
            try:
                self.request("SigninService/Logout.json", json_data={"refresh_token": refresh_token})
            except Exception:
                pass
        config.update({
            "logged": False,
            "bearer": "",
            "refresh_token": "",
            "access_token_last_update": 0,
            "access_token_lifetime": 0,
        })
        logger.info("Logged out from Sweet.tv.")
        return True

    def get_channels(self, need_epg: bool = False, epg_limit_prev: int = 1, epg_limit_next: int = 30) -> Optional[Dict[str, Any]]:
        """Fetches channel list and optional EPG metadata."""
        self.refresh_token()
        payload = {
            "epg_limit_prev": epg_limit_prev if need_epg else 0,
            "epg_limit_next": epg_limit_next if need_epg else 0,
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

    def open_stream(self, channel_id: int, epg_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Requests HLS stream URL for a given live channel or catchup recording."""
        self.refresh_token()
        payload: Dict[str, Any] = {
            "without_auth": True,
            "channel_id": int(channel_id),
            "accept_scheme": ["HTTP_HLS"],
            "multistream": True,
        }
        if epg_id:
            payload["epg_id"] = int(epg_id)

        return self.request("TvService/OpenStream.json", json_data=payload)


# Global API client instance
client = SweetTVClient()
