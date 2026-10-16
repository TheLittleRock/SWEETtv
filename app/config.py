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
    "default_quality": "auto",  # 'auto', 'best', '1080p', '720p'
    "direct_redirect": True,   # Direct 302 to Sweet.tv CDN vs server proxy
    "cache_ttl_channels": 900,  # 15 mins
    "cache_ttl_epg": 3600,      # 1 hour
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

            # Environment variable overrides
            if os.getenv("SWEETTV_COUNTRY_CODE"):
                self.data["countryCode"] = os.getenv("SWEETTV_COUNTRY_CODE").lower()
            if os.getenv("EXTERNAL_URL"):
                self.data["external_url"] = os.getenv("EXTERNAL_URL").rstrip("/")
            if os.getenv("DEFAULT_QUALITY"):
                self.data["default_quality"] = os.getenv("DEFAULT_QUALITY")
            if os.getenv("DIRECT_REDIRECT"):
                self.data["direct_redirect"] = os.getenv("DIRECT_REDIRECT").lower() in ("true", "1", "yes")

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
        return self.get("default_quality", "auto")

    @property
    def direct_redirect(self) -> bool:
        return bool(self.get("direct_redirect", True))


# Global configuration instance
config = ConfigManager()
