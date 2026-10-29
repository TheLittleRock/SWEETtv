import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, unquote, urljoin, urlparse
import requests

from app.client import client
from app.config import config

logger = logging.getLogger("SweetTV.Stream")

STREAM_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
CACHE_TTL_STREAM = 25  # seconds cache for recently opened streams


def _parse_stream_inf_tags(line: str) -> Dict[str, str]:
    """Parses key-value attributes from #EXT-X-STREAM-INF line."""
    attrs: Dict[str, str] = {}
    pattern = re.compile(r'([A-Z0-9\-]+)=("[^"]*"|[^,]*)')
    for match in pattern.finditer(line):
        k, v = match.group(1), match.group(2).strip('"')
        attrs[k] = v
    return attrs


def parse_master_m3u8(content: str, node_host: str = "") -> List[Dict[str, Any]]:
    """Parses an HLS master playlist (live or DVR catchup) and returns available variants with metadata."""
    variants = []
    lines = [line.strip() for line in content.strip().splitlines() if line.strip()]

    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXT-X-STREAM-INF:"):
            attrs = _parse_stream_inf_tags(line[len("#EXT-X-STREAM-INF:"):])
            # Next non-comment line is the variant URL (can be full URL or relative /dvr/...)
            variant_url = None
            j = i + 1
            while j < len(lines):
                if not lines[j].startswith("#"):
                    raw_path = lines[j].strip()
                    if raw_path.startswith("http"):
                        variant_url = raw_path
                    elif raw_path.startswith("/") and node_host:
                        variant_url = f"{node_host}{raw_path}"
                    elif node_host:
                        variant_url = f"{node_host}/{raw_path}"
                    else:
                        variant_url = raw_path
                    break
                j += 1

            if variant_url:
                bandwidth = int(attrs.get("BANDWIDTH", 0))
                resolution = attrs.get("RESOLUTION", "")
                codecs = attrs.get("CODECS", "")
                name = attrs.get("NAME", "")
                frame_rate = attrs.get("FRAME-RATE", "")

                height = 0
                width = 0
                if resolution and "x" in resolution:
                    try:
                        w_str, h_str = resolution.split("x")
                        width, height = int(w_str), int(h_str)
                    except ValueError:
                        pass

                if not name and height:
                    name = f"{height}p"

                variants.append({
                    "name": name or "Auto",
                    "bandwidth": bandwidth,
                    "resolution": resolution,
                    "width": width,
                    "height": height,
                    "codecs": codecs,
                    "frame_rate": frame_rate,
                    "url": variant_url,
                })
            i = j
        i += 1

    variants.sort(key=lambda x: x["bandwidth"], reverse=True)
    return variants


def safe_parse_timestamp(val: Any) -> Optional[int]:
    """
    Safely converts arbitrary timestamp inputs (epoch seconds, epoch milliseconds,
    ISO strings, XMLTV dates, Xtream format) into integer unix epoch seconds.
    """
    if val is None:
        return None
    val_str = str(val).strip()
    if not val_str or val_str.lower() in ("none", "null", "undefined", "0", "{utc}", "{start}"):
        return None

    # Check if numeric (seconds or milliseconds)
    try:
        ts = float(val_str)
        # If milliseconds (> 10 billion), convert to seconds
        if ts > 10_000_000_000:
            ts = ts / 1000.0
        return int(ts)
    except ValueError:
        pass

    # Try known date/time string formats
    formats = (
        "%Y-%m-%d:%H-%M",
        "%Y-%m-%d-%H-%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y%m%d%H%M%S",
    )
    from datetime import datetime
    base_part = val_str.split("+")[0].strip()
    for fmt in formats:
        try:
            dt = datetime.strptime(base_part, fmt)
            return int(dt.timestamp())
        except (ValueError, TypeError):
            continue

    return None


def _find_epg_match(data: Dict[str, Any], channel_id: int, utc_time: int) -> Optional[int]:
    """Helper to match a timestamp to an EPG program in channel data."""
    best_id = None
    min_distance = float("inf")

    for ch in data.get("list", []):
        if ch.get("id") == channel_id:
            epg_list = ch.get("epg", [])
            for p in epg_list:
                t_start = p.get("time_start", 0)
                t_stop = p.get("time_stop", 0)
                if not t_start or not t_stop:
                    continue
                # 1. Exact containment
                if t_start <= utc_time < t_stop:
                    return p.get("id")
                # 2. Track nearest candidate within 30 minutes tolerance (drift / client rounding)
                dist = min(abs(utc_time - t_start), abs(utc_time - t_stop))
                if dist < min_distance and dist <= 1800:
                    min_distance = dist
                    best_id = p.get("id")

    return best_id


def resolve_epg_id_from_utc(channel_id: int, utc_time_raw: Any) -> Optional[int]:
    """Finds the corresponding EPG program ID for a channel at a given UTC timestamp."""
    utc_time = safe_parse_timestamp(utc_time_raw)
    if not utc_time:
        return None

    from app.epg import get_cached_channels
    data = get_cached_channels(need_epg=True)
    if data:
        matched = _find_epg_match(data, channel_id, utc_time)
        if matched:
            return matched

    # If no match in current cache, force-refresh deep 7-day EPG and retry
    logger.info(f"EPG entry not in cache for channel {channel_id} at {utc_time}, fetching fresh 7-day EPG...")
    fresh_data = get_cached_channels(force_refresh=True, need_epg=True)
    if fresh_data:
        return _find_epg_match(fresh_data, channel_id, utc_time)

    return None


def get_stream_details(channel_id: int, epg_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    Fetches stream information from Sweet.tv (live or 7-day catchup)
    and inspects master playlist for available qualities, bitrates, and codecs.
    """
    cache_key = f"{channel_id}_{epg_id or 'live'}"
    now = time.time()

    if cache_key in STREAM_CACHE:
        cached_time, cached_data = STREAM_CACHE[cache_key]
        if now - cached_time < CACHE_TTL_STREAM:
            return cached_data

    raw = client.open_stream(channel_id, epg_id)
    if not raw or raw.get("result") != "OK":
        logger.error(f"Failed to open stream for channel {channel_id} (epg_id={epg_id}): {raw}")
        return None

    http_stream = raw.get("http_stream", {})
    host_addr = http_stream.get("host", {}).get("address")
    path = http_stream.get("url")

    master_url = raw.get("url")
    if not master_url and host_addr and path:
        master_url = f"https://{host_addr}{path}"

    if not master_url:
        return None

    parsed_master = urlparse(master_url)
    node_host = f"{parsed_master.scheme}://{parsed_master.netloc}"

    # Inspect master playlist to fetch variants using Chrome headers
    variants: List[Dict[str, Any]] = []
    raw_master_text = ""
    try:
        r = client.session.get(
            master_url,
            headers={
                "User-Agent": client.DEFAULT_UA,
                "Referer": "https://sweet.tv/",
                "Origin": "https://sweet.tv",
            },
            verify=False,
            timeout=8,
        )
        if r.status_code == 200:
            raw_master_text = r.text
            variants = parse_master_m3u8(raw_master_text, node_host=node_host)
    except Exception as e:
        logger.warning(f"Could not inspect variants for master URL {master_url}: {e}")

    result = {
        "channel_id": channel_id,
        "epg_id": epg_id,
        "master_url": master_url,
        "node_host": node_host,
        "master_content": raw_master_text,
        "scheme": raw.get("scheme", "HTTP_HLS"),
        "stream_id": raw.get("stream_id"),
        "variants": variants,
        "highest_variant": variants[0] if variants else None,
        "lowest_variant": variants[-1] if variants else None,
        "opened_at": now,
    }

    STREAM_CACHE[cache_key] = (now, result)
    return result


def build_proxy_master_m3u8(
    channel_id: int,
    base_url: str,
    epg_id: Optional[int] = None,
    quality: Optional[str] = None
) -> Tuple[str, str]:
    """
    Builds a proxy HLS manifest for the channel (live or catchup).
    Rewrites variant URLs so players fetch variants via our proxy, bypassing
    Sweet.tv's strict user-agent blocking on manifest endpoints.
    Handles both live and DVR relative variant paths.
    """
    details = get_stream_details(channel_id, epg_id)
    if not details or not details.get("master_content"):
        return "#EXTM3U\n", "application/vnd.apple.mpegurl"

    master_content = details["master_content"]
    node_host = details.get("node_host", "")
    is_master = "#EXT-X-STREAM-INF" in master_content

    # If the response from Sweet.tv is a media playlist (single stream or direct DVR catchup variant),
    # rewrite relative segment paths directly to absolute Sweet.tv CDN URLs!
    if not is_master:
        master_url = details.get("master_url", "")
        lines = master_content.splitlines()
        rewritten = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                rewritten.append(line)
            else:
                abs_segment = urljoin(master_url, stripped)
                rewritten.append(abs_segment)
        return "\n".join(rewritten) + "\n", "application/vnd.apple.mpegurl"

    selected_quality = (quality or config.default_quality).lower().strip()

    # If 'best' / 'highest' / '4k' requested, redirect to highest quality variant directly
    if selected_quality in ("best", "highest", "max", "4k", "uhd") and details.get("highest_variant"):
        highest_url = details["highest_variant"]["url"]
        return build_proxy_variant_m3u8(highest_url, base_url)

    # Specific height matching (e.g. 1080p, 720p)
    target_height = None
    if selected_quality.endswith("p") and selected_quality[:-1].isdigit():
        target_height = int(selected_quality[:-1])
    elif selected_quality.isdigit():
        target_height = int(selected_quality)

    if target_height and details.get("variants"):
        for v in details["variants"]:
            if v["height"] == target_height:
                return build_proxy_variant_m3u8(v["url"], base_url)

    # Rewrite master manifest lines (Auto Adaptive Multi-Bitrate)
    master_url = details.get("master_url", "")
    lines = master_content.splitlines()
    rewritten = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#EXT-X-MEDIA:"):
            # Rewrite URI="..." in audio/subs media tags if present
            def _rewrite_media_uri(match):
                raw_uri = match.group(1)
                abs_media = urljoin(master_url, raw_uri)
                enc = quote(abs_media, safe="")
                return f'URI="{base_url}/stream/variant.m3u8?url={enc}"'
            rewritten.append(re.sub(r'URI="([^"]+)"', _rewrite_media_uri, stripped))
        elif stripped.startswith("#"):
            rewritten.append(line)
        else:
            # Variant stream URI: resolve against master_url and route through variant proxy
            abs_variant_url = urljoin(master_url, stripped)
            encoded_url = quote(abs_variant_url, safe="")
            rewritten.append(f"{base_url}/stream/variant.m3u8?url={encoded_url}")

    return "\n".join(rewritten) + "\n", "application/vnd.apple.mpegurl"


def build_proxy_variant_m3u8(variant_url: str, base_url: str) -> Tuple[str, str]:
    """
    Fetches the variant M3U8 from Sweet.tv CDN using legitimate headers,
    rewrites relative TS segment paths to absolute URLs (which Sweet.tv CDN permits without UA check).
    """
    try:
        r = client.session.get(
            variant_url,
            headers={
                "User-Agent": client.DEFAULT_UA,
                "Referer": "https://sweet.tv/",
                "Origin": "https://sweet.tv",
            },
            verify=False,
            timeout=8,
        )
        if r.status_code != 200:
            logger.error(f"Failed fetching variant {variant_url}: HTTP {r.status_code}")
            return "#EXTM3U\n", "application/vnd.apple.mpegurl"

        lines = r.text.splitlines()
        rewritten = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                if stripped.startswith("#EXT-X-KEY:") and 'URI="' in stripped:
                    def _rewrite_key_uri(match):
                        raw_kuri = match.group(1)
                        abs_kurl = urljoin(variant_url, raw_kuri)
                        return f'URI="{abs_kurl}"'
                    rewritten.append(re.sub(r'URI="([^"]+)"', _rewrite_key_uri, stripped))
                else:
                    rewritten.append(line)
            else:
                # Segment path: resolve against variant_url directly to absolute CDN URL
                abs_segment_url = urljoin(variant_url, stripped)
                rewritten.append(abs_segment_url)

        return "\n".join(rewritten) + "\n", "application/vnd.apple.mpegurl"
    except Exception as e:
        logger.error(f"Error fetching variant playlist {variant_url}: {e}")
        return "#EXTM3U\n", "application/vnd.apple.mpegurl"
