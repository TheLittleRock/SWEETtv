import logging
import threading
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

from app.config import config
from app.providers.base import BaseProvider
from app.providers.oneplay import OneplayProvider
from app.providers.sweettv import SweetTVProvider

logger = logging.getLogger("SweetTV.Providers.Manager")


class ProviderManager:
    """Coordinates multi-source IPTV providers, aggregated channel numbering, and merged EPGs."""

    def __init__(self):
        self.lock = threading.Lock()
        self.providers: Dict[str, BaseProvider] = {
            "sweettv": SweetTVProvider(),
            "oneplay": OneplayProvider(),
        }

    def get_provider(self, name: str) -> Optional[BaseProvider]:
        return self.providers.get(name.lower().strip())

    @property
    def sweettv(self) -> SweetTVProvider:
        return self.providers["sweettv"]  # type: ignore

    @property
    def oneplay(self) -> OneplayProvider:
        return self.providers["oneplay"]  # type: ignore

    def get_channels(
        self,
        force_refresh: bool = False,
        source: Optional[str] = None,
        need_epg: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Retrieves aggregated channels from active providers based on source filter.
        Sources: 'all' (default), 'sweettv', 'oneplay'.
        """
        target = (source or "all").lower().strip()
        combined: List[Dict[str, Any]] = []

        # 1. Sweet.tv
        if target in ("all", "sweettv", "sweet"):
            try:
                sweet_channels = self.sweettv.get_channels(force_refresh=force_refresh, need_epg=need_epg)
                combined.extend(sweet_channels)
            except Exception as e:
                logger.error(f"Error fetching Sweet.tv channels: {e}")

        # 2. Oneplay
        if target in ("all", "oneplay") and config.oneplay_enabled:
            try:
                oneplay_channels = self.oneplay.get_channels(force_refresh=force_refresh, need_epg=need_epg)
                combined.extend(oneplay_channels)
            except Exception as e:
                logger.error(f"Error fetching Oneplay channels: {e}")

        return combined

    def resolve_channel(self, raw_id: str) -> Tuple[Optional[BaseProvider], str]:
        """
        Determines provider and clean channel ID from arbitrary input ID.
        Examples:
        - "oneplay:ct1" -> (oneplay, "ct1")
        - "sweet:851"   -> (sweettv, "851")
        - "ct1"         -> (oneplay if exists else sweettv, "ct1")
        - "851"         -> (sweettv, "851")
        """
        raw_str = str(raw_id).strip()
        if raw_str.startswith("oneplay:"):
            return self.oneplay, raw_str.replace("oneplay:", "")
        elif raw_str.startswith("sweet:"):
            return self.sweettv, raw_str.replace("sweet:", "")

        # If numeric string -> default to Sweet.tv
        if raw_str.isdigit():
            return self.sweettv, raw_str

        # If contains '~' (MD sport) or known Oneplay ID
        oneplay_channels = {c["id"]: c for c in self.oneplay.get_channels()}
        if raw_str in oneplay_channels:
            return self.oneplay, raw_str

        return self.sweettv, raw_str

    def generate_m3u(
        self,
        base_url: str,
        source: Optional[str] = None,
        quality: Optional[str] = None,
        catchup: Optional[str] = None,
        no_epg: bool = False,
        token: Optional[str] = None,
        token_mode: str = "query"
    ) -> str:
        """Generates aggregated or source-filtered M3U8 playlist with provider grouping tags."""
        channels = self.get_channels(source=source)
        lines = ["#EXTM3U"]
        if not no_epg:
            epg_query = f"?token={token}" if token else ""
            lines[0] += f' x-tvg-url="{base_url}/epg.xml.gz{epg_query}"'

        include_catchup = catchup is None or catchup.lower() not in ("none", "0", "false")
        use_path_token = bool(token and token_mode == "path")

        for ch in channels:
            cid = ch["id"]
            cname = ch["name"]
            provider = ch["provider"]
            chno = ch["channel_number"]
            logo = ch.get("icon", "")
            cat_list = ch.get("category", [])
            primary_cat = cat_list[0] if cat_list else "General"

            # Format provider group title
            group_prefix = "[Oneplay]" if provider == "oneplay" else "[Sweet]"
            group_title = f"{group_prefix} {primary_cat}"

            # Stream URL prefix
            if provider == "oneplay":
                stream_path = f"/t/{token}/stream/oneplay/{cid}.m3u8" if use_path_token else f"/stream/oneplay/{cid}.m3u8"
            else:
                stream_path = f"/t/{token}/stream/{cid}.m3u8" if use_path_token else f"/stream/{cid}.m3u8"

            q_params = []
            if token and not use_path_token:
                q_params.append(f"token={token}")
            if quality and quality != "auto":
                q_params.append(f"quality={quality}")

            q_str = f"?{'&'.join(q_params)}" if q_params else ""
            stream_link = f"{base_url}{stream_path}{q_str}"

            # Catchup tag
            catchup_tag = ""
            if include_catchup and ch.get("catchup"):
                catchup_days = ch.get("catchup_duration", 7)
                sep = "&" if q_str else "?"
                catchup_source = f"{stream_link}{sep}utc={{utc}}&lutc={{lutc}}"
                catchup_tag = f'catchup="default" catchup-source="{catchup_source}" catchup-days="{catchup_days}"'

            tvg_id = ch.get("canonical_id", f"{provider}:{cid}")
            extinf = f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{cname}" tvg-logo="{logo}" group-title="{group_title}" tvg-chno="{chno}" {catchup_tag},{cname}'

            lines.append(extinf)
            lines.append(stream_link)

        return "\n".join(lines) + "\n"

    def generate_xmltv_epg(self, source: Optional[str] = None) -> str:
        """Merges XMLTV EPG data from active providers into a single unified XMLTV document."""
        xml_root = ET.Element("tv", attrib={"generator-info-name": "SWEETtv-MultiSource"})

        # 1. Sweet.tv EPG
        sweet_data = self.sweettv.get_epg_schedule()
        for ch in sweet_data.get("list", []):
            cid = str(ch.get("id"))
            tvg_id = f"sweet:{cid}"
            ch_elem = ET.SubElement(xml_root, "channel", attrib={"id": tvg_id})
            ET.SubElement(ch_elem, "display-name", lang="cs").text = ch.get("name", f"Channel {cid}")
            icon = ch.get("icon_v2_url") or ch.get("icon_url")
            if icon:
                ET.SubElement(ch_elem, "icon", src=icon)

            for item in ch.get("epg", []):
                t_start = item.get("time_start", 0)
                t_stop = item.get("time_stop", 0)
                if not t_start or not t_stop:
                    continue
                start_str = time.strftime("%Y%m%d%H%M%S %z", time.localtime(t_start))
                stop_str = time.strftime("%Y%m%d%H%M%S %z", time.localtime(t_stop))
                prog = ET.SubElement(xml_root, "programme", attrib={"start": start_str, "stop": stop_str, "channel": tvg_id})
                ET.SubElement(prog, "title", lang="cs").text = item.get("text", "")
                desc = item.get("description") or item.get("genre")
                if desc:
                    ET.SubElement(prog, "desc", lang="cs").text = desc

        # 2. Oneplay EPG
        if config.oneplay_enabled and self.oneplay.is_authenticated():
            try:
                op_schedule = self.oneplay.get_epg_schedule(days_back=1, days_forward=2)
                for sch in op_schedule.get("schedule", []):
                    ch_id = str(sch.get("channelId"))
                    tvg_id = f"oneplay:{ch_id}"
                    ch_elem = ET.SubElement(xml_root, "channel", attrib={"id": tvg_id})
                    ET.SubElement(ch_elem, "display-name", lang="cs").text = f"Oneplay {ch_id}"

                    for item in sch.get("items", []):
                        start_iso = item.get("startAt")
                        end_iso = item.get("endAt")
                        if not start_iso or not end_iso:
                            continue
                        try:
                            # Convert ISO to XMLTV format
                            dt_start = time.strptime(start_iso[:19], "%Y-%m-%dT%H:%M:%S")
                            dt_end = time.strptime(end_iso[:19], "%Y-%m-%dT%H:%M:%S")
                            start_str = time.strftime("%Y%m%d%H%M%S +0000", dt_start)
                            stop_str = time.strftime("%Y%m%d%H%M%S +0000", dt_end)

                            prog = ET.SubElement(xml_root, "programme", attrib={"start": start_str, "stop": stop_str, "channel": tvg_id})
                            ET.SubElement(prog, "title", lang="cs").text = item.get("title", "")
                            if item.get("description"):
                                ET.SubElement(prog, "desc", lang="cs").text = item.get("description")
                        except Exception:
                            continue
            except Exception as e:
                logger.warning(f"Error parsing Oneplay EPG into XMLTV: {e}")

        return ET.tostring(xml_root, encoding="utf-8", xml_declaration=True).decode("utf-8")


# Global ProviderManager singleton
provider_manager = ProviderManager()
