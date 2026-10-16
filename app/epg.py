import gzip
import logging
import threading
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from app.client import client
from app.config import config

logger = logging.getLogger("SweetTV.EPG")

# In-memory caches
_CHANNELS_CACHE: Optional[Dict[str, Any]] = None
_CHANNELS_CACHE_TIME: float = 0

_EPG_XML_CACHE: Optional[str] = None
_EPG_XML_GZ_CACHE: Optional[bytes] = None
_EPG_CACHE_TIME: float = 0

_CACHE_LOCK = threading.Lock()


def get_cached_channels(force_refresh: bool = False, need_epg: bool = False) -> Optional[Dict[str, Any]]:
    """Retrieves channel list with caching."""
    global _CHANNELS_CACHE, _CHANNELS_CACHE_TIME

    with _CACHE_LOCK:
        now = time.time()
        ttl = config.get("cache_ttl_channels", 900)

        if not force_refresh and _CHANNELS_CACHE and (now - _CHANNELS_CACHE_TIME < ttl):
            # If we need EPG but cached channels don't have it, we must fetch
            if not need_epg or any("epg" in ch for ch in _CHANNELS_CACHE.get("list", [])):
                return _CHANNELS_CACHE

        logger.info(f"Fetching channels from Sweet.tv API (need_epg={need_epg})...")
        data = client.get_channels(need_epg=need_epg)
        if data and data.get("status") == "OK":
            _CHANNELS_CACHE = data
            _CHANNELS_CACHE_TIME = now
            return data
        elif _CHANNELS_CACHE:
            logger.warning("Failed to refresh channels from API, returning stale cache.")
            return _CHANNELS_CACHE

        return None


def invalidate_cache():
    """Forces cache refresh on next request."""
    global _CHANNELS_CACHE, _CHANNELS_CACHE_TIME, _EPG_XML_CACHE, _EPG_XML_GZ_CACHE, _EPG_CACHE_TIME
    with _CACHE_LOCK:
        _CHANNELS_CACHE = None
        _CHANNELS_CACHE_TIME = 0
        _EPG_XML_CACHE = None
        _EPG_XML_GZ_CACHE = None
        _EPG_CACHE_TIME = 0
    logger.info("Channel and EPG caches invalidated.")


def generate_m3u_playlist(base_url: str, quality: Optional[str] = None) -> str:
    """
    Generates standard M3U/M3U8 playlist with full IPTV metadata,
    category groupings, channel logos, and catchup replay tags.
    """
    data = get_cached_channels(need_epg=False)
    if not data or data.get("status") != "OK":
        return "#EXTM3U\n"

    categories: Dict[int, str] = {cat.get("id"): cat.get("caption", "") for cat in data.get("categories", [])}

    q_param = f"?quality={quality}" if quality and quality != "auto" else ""
    encoded_ua = quote(client.DEFAULT_UA)
    encoded_ref = quote("https://sweet.tv/")
    header_suffix = f"|User-Agent={encoded_ua}&Referer={encoded_ref}"

    lines = ["#EXTM3U url-tvg=\"{}/epg.xml\"".format(base_url)]

    for ch in data.get("list", []):
        if not ch.get("available"):
            continue

        cid = ch.get("id")
        cname = (ch.get("name") or f"Channel {cid}").strip()
        icon = ch.get("icon_v2_url") or ch.get("icon_url") or ""

        # Build category group string
        cat_names = [categories[c] for c in ch.get("category", []) if c in categories and c != 1000]
        group_title = ";".join(cat_names) if cat_names else "General"

        stream_url_base = f"{base_url}/play/{cid}"

        catchup_tag = ""
        if ch.get("catchup"):
            catchup_days = max(1, int(ch.get("catchup_duration", 7) or 7))
            catchup_tag = f'catchup="vod" catchup-source="{stream_url_base}/{{catchup-id}}{q_param}{header_suffix}" catchup-days="{catchup_days}"'

        extinf = f'#EXTINF:-1 tvg-id="{cid}.id.com" tvg-name="{cname}" tvg-logo="{icon}" group-title="{group_title}" {catchup_tag},{cname}'.strip()
        stream_link = f"{stream_url_base}{q_param}{header_suffix}"

        lines.append(extinf)
        lines.append("#EXTVLCOPT:http-referrer=https://sweet.tv/")
        lines.append(f"#EXTVLCOPT:http-user-agent={client.DEFAULT_UA}")
        lines.append(stream_link)

    return "\n".join(lines) + "\n"


def generate_xmltv_epg(country_code: Optional[str] = None, force_refresh: bool = False) -> str:
    """Generates XMLTV electronic program guide for all channels."""
    global _EPG_XML_CACHE, _EPG_XML_GZ_CACHE, _EPG_CACHE_TIME

    lang = country_code or config.country_code
    now = time.time()
    ttl = config.get("cache_ttl_epg", 3600)

    with _CACHE_LOCK:
        if not force_refresh and _EPG_XML_CACHE and (now - _EPG_CACHE_TIME < ttl):
            return _EPG_XML_CACHE

    data = get_cached_channels(force_refresh=force_refresh, need_epg=True)
    if not data or data.get("status") != "OK":
        return '<?xml version="1.0" encoding="utf-8"?>\n<tv></tv>'

    xml_root = ET.Element("tv", attrib={"generator-info-name": "SweetTV-IPTV-Proxy"})

    # 1. Channel entries
    for ch in data.get("list", []):
        cid = ch.get("id")
        ch_elem = ET.SubElement(xml_root, "channel", attrib={"id": f"{cid}.id.com"})
        ET.SubElement(ch_elem, "display-name", lang=lang).text = ch.get("name", f"Channel {cid}")
        icon = ch.get("icon_v2_url") or ch.get("icon_url")
        if icon:
            ET.SubElement(ch_elem, "icon", src=icon)

    # 2. Programme entries
    for ch in data.get("list", []):
        cid = ch.get("id")
        ch_id = f"{cid}.id.com"
        epg_list = ch.get("epg", [])

        if epg_list:
            for item in epg_list:
                t_start = item.get("time_start", 0)
                t_stop = item.get("time_stop", 0)
                if not t_start or not t_stop:
                    continue

                start_str = time.strftime("%Y%m%d%H%M%S +0100", time.localtime(t_start))
                stop_str = time.strftime("%Y%m%d%H%M%S +0100", time.localtime(t_stop))

                attribs = {"start": start_str, "stop": stop_str, "channel": ch_id}
                if ch.get("catchup") and item.get("available") and item.get("id"):
                    attribs["catchup-id"] = str(item.get("id"))

                prog_elem = ET.SubElement(xml_root, "programme", attrib=attribs)
                title_text = item.get("text", "")
                if not item.get("available") and ch.get("live_blackout"):
                    title_text = f"!UNAVAILABLE! {title_text}"

                ET.SubElement(prog_elem, "title", lang=lang).text = title_text

                # Optional description / plot
                desc = item.get("description") or item.get("genre")
                if desc:
                    ET.SubElement(prog_elem, "desc", lang=lang).text = desc

                preview_url = item.get("preview_url_ext") or item.get("preview_url")
                if preview_url:
                    ET.SubElement(prog_elem, "icon", src=preview_url)
        else:
            # Fallback programme block if no EPG schedule returned
            start_str = time.strftime("%Y%m%d%H%M%S +0100", time.localtime(now))
            stop_str = time.strftime("%Y%m%d%H%M%S +0100", time.localtime(now + 43200))

            prog_elem = ET.SubElement(xml_root, "programme", attrib={"start": start_str, "stop": stop_str, "channel": ch_id})
            ET.SubElement(prog_elem, "title", lang=lang).text = ch.get("name", "Live Broadcast")

    xml_str = '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(xml_root, encoding="utf-8").decode("utf-8")

    with _CACHE_LOCK:
        _EPG_XML_CACHE = xml_str
        _EPG_XML_GZ_CACHE = gzip.compress(xml_str.encode("utf-8"))
        _EPG_CACHE_TIME = now

    return xml_str


def get_xmltv_epg_gz() -> bytes:
    """Returns gzip-compressed XMLTV EPG for clients supporting compression."""
    global _EPG_XML_GZ_CACHE
    if _EPG_XML_GZ_CACHE is None:
        generate_xmltv_epg()
    return _EPG_XML_GZ_CACHE or b""
