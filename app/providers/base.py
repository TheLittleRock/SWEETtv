import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("SweetTV.Providers.Base")


class BaseProvider(ABC):
    """Abstract base class for IPTV streaming providers."""

    provider_id: str = "base"
    display_name: str = "Base Provider"

    @abstractmethod
    def is_authenticated(self) -> bool:
        """Returns True if the provider is currently logged in with active tokens."""
        pass

    @abstractmethod
    def get_channels(self, force_refresh: bool = False, need_epg: bool = False) -> List[Dict[str, Any]]:
        """
        Returns list of standardized channel dictionaries:
        {
            "id": str,
            "canonical_id": str,        # e.g. "sweet:851" or "oneplay:ct1"
            "name": str,
            "channel_number": int,
            "icon": str,
            "category": List[str],
            "catchup": bool,
            "catchup_duration": int,
            "epg": List[Dict[str, Any]],
            "provider": str,
        }
        """
        pass

    @abstractmethod
    def get_stream_details(
        self,
        channel_id: str,
        epg_id: Optional[str] = None,
        utc_time: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieves playback URL or manifest content.
        Returns dictionary containing:
        - master_url: URL to stream or CDN master
        - direct_redirect: whether client can be redirected (302) or requires proxying
        - variants: list of variant streams
        """
        pass

    @abstractmethod
    def get_epg_schedule(self, days_back: int = 1, days_forward: int = 1) -> Dict[str, Any]:
        """Returns raw schedule or XMLTV-compatible schedule data."""
        pass

