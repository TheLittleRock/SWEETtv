import logging
from typing import Any, Dict, List, Optional

from app.client import client
from app.config import config
from app.providers.base import BaseProvider
from app.stream import get_stream_details as sweet_get_stream_details

logger = logging.getLogger("SweetTV.Providers.SweetTV")


class SweetTVProvider(BaseProvider):
    provider_id = "sweettv"
    display_name = "Sweet.tv"

    def is_authenticated(self) -> bool:
        return config.is_logged

    def get_channels(self, force_refresh: bool = False, need_epg: bool = False) -> List[Dict[str, Any]]:
        if not self.is_authenticated():
            return []

        from app.epg import get_cached_channels
        data = get_cached_channels(force_refresh=force_refresh, need_epg=need_epg)
        if not data or data.get("status") != "OK":
            return []

        categories: Dict[int, str] = {cat["id"]: cat.get("caption", "") for cat in data.get("categories", [])}
        result = []
        idx = 1
        for ch in data.get("list", []):
            if not ch.get("available", True):
                continue
            cid = str(ch.get("id"))
            cname = ch.get("name", "")
            icon = ch.get("icon_v2_url") or ch.get("icon_url", "")
            cat_names = [categories[c] for c in ch.get("category", []) if c in categories and c != 1000]

            result.append({
                "id": cid,
                "canonical_id": f"sweet:{cid}",
                "name": cname,
                "channel_number": idx,
                "icon": icon,
                "category": cat_names or ["Všeobecné"],
                "catchup": ch.get("catchup", True),
                "catchup_duration": int(ch.get("catchup_duration") or 7),
                "epg": ch.get("epg", []),
                "provider": self.provider_id,
                "raw": ch,
            })
            idx += 1
        return result

    def get_stream_details(
        self,
        channel_id: str,
        epg_id: Optional[str] = None,
        utc_time: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        # Clean numeric ID
        cid_clean = int("".join(c for c in channel_id.replace("sweet:", "") if c.isdigit()))
        eid_clean = int("".join(c for c in epg_id if c.isdigit())) if epg_id else None

        if not eid_clean and utc_time:
            from app.stream import resolve_epg_id_from_utc
            eid_clean = resolve_epg_id_from_utc(cid_clean, utc_time)

        details = sweet_get_stream_details(cid_clean, eid_clean)
        if not details:
            return None

        return {
            "master_url": details.get("master_url"),
            "direct_redirect": config.direct_redirect,
            "node_host": details.get("node_host"),
            "master_content": details.get("master_content"),
            "variants": details.get("variants", []),
            "highest_variant": details.get("highest_variant"),
            "lowest_variant": details.get("lowest_variant"),
            "provider": self.provider_id,
        }

    def get_epg_schedule(self, days_back: int = 1, days_forward: int = 1) -> Dict[str, Any]:
        from app.epg import get_cached_channels
        return get_cached_channels(need_epg=True) or {}

