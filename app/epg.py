import gzip
import logging
import threading
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

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
    """Retrieves channel list with caching (loads full 7-day EPG when need_epg is True)."""
    global _CHANNELS_CACHE, _CHANNELS_CACHE_TIME

    with _CACHE_LOCK:
        now = time.time()
        ttl = config.get("cache_ttl_channels", 900)

        if not force_refresh and _CHANNELS_CACHE and (now - _CHANNELS_CACHE_TIME < ttl):
            # If we don't need EPG, current cache is sufficient
            if not need_epg:
                return _CHANNELS_CACHE
            # If we need EPG, ensure cache actually contains deep schedule (> 2 items per channel)
            has_deep_epg = any(len(ch.get("epg", [])) > 2 for ch in _CHANNELS_CACHE.get("list", []))
            if has_deep_epg:
                return _CHANNELS_CACHE

        logger.info(f"Fetching channels from Sweet.tv API (need_epg={need_epg}, epg_limit_prev=250)...")
        data = client.get_channels(
            need_epg=need_epg,
            epg_limit_prev=250 if need_epg else 0,
            epg_limit_next=50 if need_epg else 0
        )
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


def generate_m3u_playlist(
    base_url: str,
    quality: Optional[str] = None,
    catchup: Optional[str] = None,
    no_epg: bool = False,
    legacy_id: bool = False,
    bare: bool = False,
    token: Optional[str] = None,
    token_mode: str = "query"
) -> str:
    """
    Generates clean, standard M3U/M3U8 playlist with full IPTV metadata,
    category groupings, channel logos, and optional catchup replay tags.
    Universally compatible with IPTV portals, set-top boxes, Kodi, TiviMate, VLC.
    Supports secure user token in query param or path prefix mode.
    """
    data = get_cached_channels(need_epg=False)
    if not data or data.get("status") != "OK":
        return "#EXTM3U\n"

    categories: Dict[int, str] = {cat.get("id"): cat.get("caption", "") for cat in data.get("categories", [])}

    # Build base stream path & query parameters
    use_path_token = bool(token and token_mode == "path")
    stream_prefix = f"{base_url}/t/{token}/stream" if use_path_token else f"{base_url}/stream"

    query_parts = []
    if token and not use_path_token:
        query_parts.append(f"token={token}")
    if quality and quality != "auto":
        query_parts.append(f"quality={quality}")
    q_param = f"?{'&'.join(query_parts)}" if query_parts else ""

    # EPG URL
    if use_path_token:
        epg_url = f"{base_url}/t/{token}/epg.xml"
    elif token:
        epg_url = f"{base_url}/epg.xml?token={token}"
    else:
        epg_url = f"{base_url}/epg.xml"

    # Determine whether catchup tags should be included in the playlist
    if catchup is not None:
        include_catchup = catchup.lower() in ("vod", "default", "1", "true", "kodi", "append")
        mode = catchup.lower()
    elif no_epg or bare:
        # In clean / bare mode, strictly omit catchup tags to avoid buggy client database parsers
        include_catchup = False
        mode = "none"
    else:
        include_catchup = bool(config.get("m3u_catchup", True))
        mode = "default"

    if not no_epg and not bare:
        lines = [f'#EXTM3U url-tvg="{epg_url}" x-tvg-url="{epg_url}"']
    else:
        lines = ['#EXTM3U']

    idx = 0
    for ch in data.get("list", []):
        if not ch.get("available"):
            continue

        idx += 1
        cid = ch.get("id")
        cname = (ch.get("name") or f"Channel {cid}").strip()
        icon = ch.get("icon_v2_url") or ch.get("icon_url") or ""

        # Primary category (clean, standard group-title)
        cat_names = [categories[c] for c in ch.get("category", []) if c in categories and c != 1000]
        group_title = cat_names[0] if cat_names else "General"

        # Standard numeric channel ID
        tvg_id = f"{cid}.id.com" if legacy_id else str(cid)

        # Standard stream URL
        stream_link = f"{stream_prefix}/{cid}.m3u8{q_param}"

        if bare:
            extinf = f'#EXTINF:-1,{cname}'
        else:
            catchup_tag = ""
            if include_catchup and ch.get("catchup"):
                catchup_days = max(1, int(ch.get("catchup_duration", 7) or 7))
                sep = "&" if q_param else "?"
                if mode == "append":
                    catchup_tag = f'catchup="append" catchup-source="{sep}utc={{utc}}&lutc={{lutc}}" catchup-days="{catchup_days}"'
                elif mode in ("vod", "kodi"):
                    catchup_source = f"{stream_prefix}/{cid}/{{catchup-id}}.m3u8{q_param}"
                    catchup_tag = f'catchup="vod" catchup-source="{catchup_source}" catchup-days="{catchup_days}"'
                else:
                    # Universal standard (IPTVnator, TiviMate, OTT Navigator, VLC, Televizo)
                    catchup_source = f"{stream_prefix}/{cid}.m3u8{q_param}{sep}utc={{utc}}&lutc={{lutc}}"
                    catchup_tag = f'catchup="default" catchup-source="{catchup_source}" catchup-days="{catchup_days}"'

            if catchup_tag:
                extinf = f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{cname}" tvg-logo="{icon}" group-title="{group_title}" tvg-chno="{idx}" {catchup_tag},{cname}'
            else:
                extinf = f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{cname}" tvg-logo="{icon}" group-title="{group_title}" tvg-chno="{idx}",{cname}'

        lines.append(extinf)
        lines.append(stream_link)

    return "\n".join(lines) + "\n"


def generate_xmltv_epg(
    country_code: Optional[str] = None,
    force_refresh: bool = False,
    legacy_id: bool = False
) -> str:
    """Generates XMLTV electronic program guide for all channels conforming to XMLTV DTD."""
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
        tvg_id = f"{cid}.id.com" if legacy_id else str(cid)
        ch_elem = ET.SubElement(xml_root, "channel", attrib={"id": tvg_id})
        ET.SubElement(ch_elem, "display-name", lang=lang).text = ch.get("name", f"Channel {cid}")
        icon = ch.get("icon_v2_url") or ch.get("icon_url")
        if icon:
            ET.SubElement(ch_elem, "icon", src=icon)

    # 2. Programme entries
    for ch in data.get("list", []):
        cid = ch.get("id")
        ch_id = f"{cid}.id.com" if legacy_id else str(cid)
        epg_list = ch.get("epg", [])

        if epg_list:
            for item in epg_list:
                t_start = item.get("time_start", 0)
                t_stop = item.get("time_stop", 0)
                if not t_start or not t_stop:
                    continue

                start_str = time.strftime("%Y%m%d%H%M%S %z", time.localtime(t_start))
                stop_str = time.strftime("%Y%m%d%H%M%S %z", time.localtime(t_stop))

                # Standard XMLTV attributes only
                attribs = {"start": start_str, "stop": stop_str, "channel": ch_id}

                prog_elem = ET.SubElement(xml_root, "programme", attrib=attribs)
                title_text = item.get("text", "")
                if not item.get("available") and ch.get("live_blackout"):
                    title_text = f"!UNAVAILABLE! {title_text}"

                ET.SubElement(prog_elem, "title", lang=lang).text = title_text

                desc = item.get("description") or item.get("genre")
                if desc:
                    ET.SubElement(prog_elem, "desc", lang=lang).text = desc

                genre = item.get("genre")
                if genre:
                    ET.SubElement(prog_elem, "category", lang=lang).text = genre

                preview_url = item.get("preview_url_ext") or item.get("preview_url")
                if preview_url:
                    ET.SubElement(prog_elem, "icon", src=preview_url)
        else:
            # Fallback programme block if no EPG schedule returned
            start_str = time.strftime("%Y%m%d%H%M%S %z", time.localtime(now))
            stop_str = time.strftime("%Y%m%d%H%M%S %z", time.localtime(now + 43200))

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
