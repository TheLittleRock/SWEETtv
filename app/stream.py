import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple
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


def parse_master_m3u8(content: str) -> List[Dict[str, Any]]:
    """Parses an HLS master playlist and returns available variants with metadata."""
    variants = []
    lines = [line.strip() for line in content.strip().splitlines() if line.strip()]

    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXT-X-STREAM-INF:"):
            attrs = _parse_stream_inf_tags(line[len("#EXT-X-STREAM-INF:"):])
            # Next non-comment line is the variant URL
            variant_url = None
            j = i + 1
            while j < len(lines):
                if not lines[j].startswith("#"):
                    variant_url = lines[j]
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

    # Sort descending by bandwidth (highest quality first)
    variants.sort(key=lambda x: x["bandwidth"], reverse=True)
    return variants


def get_stream_details(channel_id: int, epg_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    Fetches stream information from Sweet.tv and inspects master playlist for available
    qualities, bitrates, and video/audio codecs.
    """
    cache_key = f"{channel_id}_{epg_id or 'live'}"
    now = time.time()

    if cache_key in STREAM_CACHE:
        cached_time, cached_data = STREAM_CACHE[cache_key]
        if now - cached_time < CACHE_TTL_STREAM:
            return cached_data

    raw = client.open_stream(channel_id, epg_id)
    if not raw or raw.get("result") != "OK":
        logger.error(f"Failed to open stream for channel {channel_id}: {raw}")
        return None

    http_stream = raw.get("http_stream", {})
    host_addr = http_stream.get("host", {}).get("address")
    path = http_stream.get("url")

    master_url = raw.get("url")
    if not master_url and host_addr and path:
        master_url = f"https://{host_addr}{path}"

    if not master_url:
        return None

    # Inspect master playlist to fetch variants
    variants: List[Dict[str, Any]] = []
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
            variants = parse_master_m3u8(r.text)
    except Exception as e:
        logger.warning(f"Could not inspect variants for master URL {master_url}: {e}")

    result = {
        "channel_id": channel_id,
        "epg_id": epg_id,
        "master_url": master_url,
        "scheme": raw.get("scheme", "HTTP_HLS"),
        "stream_id": raw.get("stream_id"),
        "variants": variants,
        "highest_variant": variants[0] if variants else None,
        "lowest_variant": variants[-1] if variants else None,
        "opened_at": now,
    }

    STREAM_CACHE[cache_key] = (now, result)
    return result


def resolve_stream_url(
    channel_id: int,
    epg_id: Optional[int] = None,
    quality: Optional[str] = None
) -> Optional[str]:
    """
    Resolves the target stream URL.
    - quality in ('auto', None): returns master playlist (adaptive multi-bitrate).
    - quality in ('best', 'highest', 'max', '4k', 'uhd'): returns direct highest bandwidth variant.
    - quality matching height (e.g. '1080p', '720p', '360p'): returns variant matching resolution.
    """
    details = get_stream_details(channel_id, epg_id)
    if not details:
        return None

    selected_quality = (quality or config.default_quality).lower().strip()

    if selected_quality in ("auto", "", "adaptive"):
        return details["master_url"]

    variants = details.get("variants", [])
    if not variants:
        # If no variants could be parsed, fall back to master URL
        return details["master_url"]

    if selected_quality in ("best", "highest", "max", "4k", "uhd"):
        # First variant is highest bandwidth
        return variants[0]["url"]

    # Match specific resolution e.g. 1080p, 720p, 360p
    target_height = None
    if selected_quality.endswith("p") and selected_quality[:-1].isdigit():
        target_height = int(selected_quality[:-1])
    elif selected_quality.isdigit():
        target_height = int(selected_quality)

    if target_height:
        # Find exact or closest variant
        for v in variants:
            if v["height"] == target_height:
                return v["url"]
        # Find closest variant if exact not found
        variants_by_diff = sorted(variants, key=lambda v: abs(v["height"] - target_height))
        return variants_by_diff[0]["url"]

    # Fallback to master URL
    return details["master_url"]
