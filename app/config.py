import json
import logging
import os
import random
import threading
import uuid
from typing import Any, Dict

logger = logging.getLogger("SweetTV.Config")

DEFAULT_DATA_DIR = os.getenv("SWEETTV_DATA_DIR", "data")
DEFAULT_CONFIG_PATH = os.path.join(DEFAULT_DATA_DIR, "config.json")
FALLBACK_PATHS = [
    DEFAULT_CONFIG_PATH,
    "config.json",
    os.path.join("plugin.video.sweettv-main", "resources", "lib", "config.json"),
]

DEFAULT_CONFIG: Dict[str, Any] = {
    "uuid": "",
    "mac": "",
    "bearer": "",
    "refresh_token": "",
    "logged": False,
    "countryCode": "cs",
    "access_token_last_update": 0,
    "access_token_lifetime": 0,
    "external_url": "",
    "default_quality": "1080p",  # '1080p', 'best', '720p', 'auto'
    "direct_redirect": True,   # Direct 302 to Sweet.tv CDN vs server proxy
    "cache_ttl_channels": 900,  # 15 mins
    "cache_ttl_epg": 3600,      # 1 hour
    "xtream_user": "sweettv",   # Xtream Codes API username
    "xtream_password": "sweet", # Xtream Codes API password
    "m3u_catchup": True,        # Include catchup tags in M3U by default
    # Oneplay Provider Configuration
    "oneplay_enabled": True,
    "oneplay_username": "",
    "oneplay_password": "",
    "oneplay_profile": "",
    "oneplay_profile_id": "",
    "oneplay_pin": "4321",
    "oneplay_device_name": "SWEETtv-Oneplay",
    "oneplay_account_id": "",
    "oneplay_token": "",
    "oneplay_token_valid_to": 0,
    "oneplay_api_version": "v1.11",
    "oneplay_logged": False,
    # Oneplay DRM Widevine & Upstream Configuration
    "oneplay_wv_api_url": "https://wv.api.md.sune.app/v1/",
    "oneplay_drm_license_url": "https://drm-proxy-widevine.cms.jyxo-tls.cz/AcquireLicense",
    "oneplay_drm_upstream_repo": "sunecz/Media-Downloader-Default-Plugins",
}


class ConfigManager:
    """Thread-safe configuration manager for Sweet.tv IPTV server."""

    def __init__(self, filepath: str = None):
        self.lock = threading.Lock()
        self.filepath = filepath or os.getenv("SWEETTV_CONFIG_PATH", DEFAULT_CONFIG_PATH)
        self.data: Dict[str, Any] = DEFAULT_CONFIG.copy()
        self.load()

    def _ensure_dir(self):
        dirname = os.path.dirname(self.filepath)
        if dirname and not os.path.exists(dirname):
            try:
                os.makedirs(dirname, exist_ok=True)
            except Exception as e:
                logger.error(f"Failed to create config directory {dirname}: {e}")

    def load(self):
        with self.lock:
            loaded = False
            # Try designated path
            if os.path.exists(self.filepath):
                try:
                    with open(self.filepath, "r", encoding="utf-8") as f:
                        self.data.update(json.load(f))
                    loaded = True
                    logger.info(f"Loaded configuration from {self.filepath}")
                except Exception as e:
                    logger.error(f"Error loading config from {self.filepath}: {e}")

            # Try fallback paths if not yet loaded
            if not loaded:
                for fallback in FALLBACK_PATHS:
                    if fallback != self.filepath and os.path.exists(fallback):
                        try:
                            with open(fallback, "r", encoding="utf-8") as f:
                                self.data.update(json.load(f))
                            loaded = True
                            logger.info(f"Migrated configuration from fallback {fallback} to {self.filepath}")
                            break
                        except Exception as e:
                            logger.warning(f"Failed loading fallback config {fallback}: {e}")

            # Environment variable overrides (only if explicitly set and non-empty)
            env_cc = (os.getenv("SWEETTV_COUNTRY_CODE") or "").strip()
            if env_cc:
                self.data["countryCode"] = env_cc.lower()

            env_ext = (os.getenv("EXTERNAL_URL") or "").strip()
            if env_ext:
                self.data["external_url"] = env_ext.rstrip("/")

            env_quality = (os.getenv("DEFAULT_QUALITY") or "").strip()
            if env_quality:
                self.data["default_quality"] = env_quality.lower()

            env_redirect = (os.getenv("DIRECT_REDIRECT") or "").strip()
            if env_redirect:
                self.data["direct_redirect"] = env_redirect.lower() in ("true", "1", "yes")

            env_x_user = (os.getenv("XTREAM_USER") or "").strip()
            if env_x_user:
                self.data["xtream_user"] = env_x_user

            env_x_pwd = (os.getenv("XTREAM_PASSWORD") or "").strip()
            if env_x_pwd:
                self.data["xtream_password"] = env_x_pwd

            env_catchup = (os.getenv("M3U_CATCHUP") or "").strip()
            if env_catchup:
                self.data["m3u_catchup"] = env_catchup.lower() in ("true", "1", "yes")

            # Oneplay Environment Overrides
            env_op_user = (os.getenv("ONEPLAY_USERNAME") or "").strip()
            if env_op_user:
                self.data["oneplay_username"] = env_op_user

            env_op_pwd = (os.getenv("ONEPLAY_PASSWORD") or "").strip()
            if env_op_pwd:
                self.data["oneplay_password"] = env_op_pwd

            env_op_pin = (os.getenv("ONEPLAY_PIN") or "").strip()
            if env_op_pin:
                self.data["oneplay_pin"] = env_op_pin

            env_op_profile = (os.getenv("ONEPLAY_PROFILE") or "").strip()
            if env_op_profile:
                self.data["oneplay_profile"] = env_op_profile

            env_op_dev = (os.getenv("ONEPLAY_DEVICE_NAME") or "").strip()
            if env_op_dev:
                self.data["oneplay_device_name"] = env_op_dev

            env_op_enabled = (os.getenv("ONEPLAY_ENABLED") or "").strip()
            if env_op_enabled:
                self.data["oneplay_enabled"] = env_op_enabled.lower() in ("true", "1", "yes")

            self._ensure_defaults()

    def _ensure_defaults(self):
        save_needed = False
        if not self.data.get("uuid"):
            self.data["uuid"] = str(uuid.uuid4())
            save_needed = True
        if not self.data.get("mac"):
            self.data["mac"] = ":".join("%02x" % random.randint(0, 255) for _ in range(6))
            save_needed = True

        if save_needed or not os.path.exists(self.filepath):
            self._save_internal()

    def _save_internal(self):
        self._ensure_dir()
        try:
            temp_path = f"{self.filepath}.tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4)
            os.replace(temp_path, self.filepath)
        except Exception as e:
            logger.error(f"Failed to save configuration to {self.filepath}: {e}")

    def save(self):
        with self.lock:
            self._save_internal()

    def reset_device(self) -> Dict[str, str]:
        """Generates a fresh UUID and MAC address and clears authentication tokens."""
        with self.lock:
            new_uuid = str(uuid.uuid4())
            new_mac = ":".join("%02x" % random.randint(0, 255) for _ in range(6))
            self.data.update({
                "uuid": new_uuid,
                "mac": new_mac,
                "logged": False,
                "bearer": "",
                "refresh_token": "",
                "access_token_last_update": 0,
                "access_token_lifetime": 0,
            })
            self._save_internal()
            return {"uuid": new_uuid, "mac": new_mac}

    def get(self, key: str, default: Any = None) -> Any:
        with self.lock:
            return self.data.get(key, default)

    def set(self, key: str, value: Any):
        with self.lock:
            self.data[key] = value
            self._save_internal()

    def update(self, mapping: Dict[str, Any]):
        with self.lock:
            self.data.update(mapping)
            self._save_internal()

    @property
    def is_logged(self) -> bool:
        return bool(self.get("logged")) and bool(self.get("bearer"))

    @property
    def country_code(self) -> str:
        return self.get("countryCode", "cs")

    @property
    def external_url(self) -> str:
        return (self.get("external_url") or "").rstrip("/")

    @property
    def default_quality(self) -> str:
        return self.get("default_quality", "1080p")

    @property
    def direct_redirect(self) -> bool:
        return bool(self.get("direct_redirect", True))

    @property
    def xtream_user(self) -> str:
        return self.get("xtream_user", "sweettv")

    @property
    def xtream_password(self) -> str:
        return self.get("xtream_password", "sweet")

    @property
    def oneplay_enabled(self) -> bool:
        return bool(self.get("oneplay_enabled", True))

    @property
    def is_oneplay_logged(self) -> bool:
        return bool(self.get("oneplay_logged")) and bool(self.get("oneplay_token"))

    @property
    def oneplay_wv_api_url(self) -> str:
        url = self.get("oneplay_wv_api_url", "https://wv.api.md.sune.app/v1/")
        return url.rstrip("/") + "/"

    @property
    def oneplay_drm_license_url(self) -> str:
        return self.get("oneplay_drm_license_url", "https://drm-proxy-widevine.cms.jyxo-tls.cz/AcquireLicense")

    @property
    def oneplay_drm_upstream_repo(self) -> str:
        return self.get("oneplay_drm_upstream_repo", "sunecz/Media-Downloader-Default-Plugins")


# Global configuration instance
config = ConfigManager()
