import logging
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, unquote
from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.config import config
from app.epg import generate_m3u_playlist, generate_xmltv_epg, get_xmltv_epg_gz
from app.stream import (
    build_proxy_master_m3u8,
    build_proxy_variant_m3u8,
    resolve_epg_id_from_utc,
    safe_parse_timestamp,
)

logger = logging.getLogger("SweetTV.Routes.IPTV")
router = APIRouter(tags=["IPTV"])


def parse_stream_query(request: Request) -> Dict[str, str]:
    """
    Extracts query parameters handling duplicate question marks (IPTVnator issue #579 bug workaround),
    ampersands, and unquoted values.
    """
    raw_query = request.url.query
    if "?" in raw_query:
        raw_query = raw_query.replace("?", "&")
    parsed = parse_qs(raw_query)
    return {k: v[0] for k, v in parsed.items() if v}


def get_effective_base_url(request: Request) -> str:
    """Computes public base URL taking reverse proxies (NPM) and config into account."""
    if config.external_url:
        return config.external_url

    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host")
    if forwarded_proto and forwarded_host:
        return f"{forwarded_proto}://{forwarded_host}".rstrip("/")

    host = request.headers.get("host")
    if host:
        proto = "https" if request.url.scheme == "https" or request.headers.get("x-forwarded-ssl") == "on" else request.url.scheme
        return f"{proto}://{host}".rstrip("/")

    return str(request.base_url).rstrip("/")


def clean_id(raw_id: str) -> int:
    """Strips file extensions, suffixes (.id.com), or pipe parameters from IDs."""
    clean = str(raw_id).split("|")[0].split(".")[0].strip()
    digits = "".join(c for c in clean if c.isdigit())
    if digits:
        return int(digits)
    raise ValueError(f"No numeric ID found in '{raw_id}'")


@router.get("/playlist.m3u", response_class=Response)
@router.get("/playlist.m3u8", response_class=Response)
@router.get("/playlist_clean.m3u", response_class=Response)
@router.get("/playlist_bare.m3u", response_class=Response)
def get_playlist(
    request: Request,
    quality: Optional[str] = Query(None, description="Quality preset: 'auto', 'best' (highest bitrate), '1080p', '720p'"),
    catchup: Optional[str] = Query(None, description="Catchup mode: 'vod', 'default', 'none', '0'"),
    no_epg: Optional[bool] = Query(False, description="Omit url-tvg header to avoid triggering automatic EPG import"),
    legacy_id: Optional[bool] = Query(False, description="Use legacy .id.com suffix for channel IDs"),
    bare: Optional[bool] = Query(False, description="Ultra-minimal M3U with no attributes (for buggy parsers)")
):
    """
    Returns M3U/M3U8 playlist with full channel lineup, category groups, logos,
    and optional catchup replay support.
    """
    if not config.is_logged:
        raise HTTPException(
            status_code=401,
            detail="Server is not logged in to Sweet.tv. Please authenticate first via Web UI."
        )

    # If requested via /playlist_clean.m3u or /playlist_bare.m3u
    is_bare = bool(bare) or request.url.path.endswith("playlist_bare.m3u")
    is_clean = is_bare or no_epg or request.url.path.endswith("playlist_clean.m3u")
    base_url = get_effective_base_url(request)
    playlist_text = generate_m3u_playlist(
        base_url,
        quality=quality or config.default_quality,
        catchup=catchup,
        no_epg=is_clean,
        legacy_id=bool(legacy_id),
        bare=is_bare
    )

    return Response(
        content=playlist_text,
        media_type="application/x-mpegurl",
        headers={
            "Content-Disposition": 'inline; filename="sweettv.m3u8"',
            "Cache-Control": "public, max-age=300",
            "Access-Control-Allow-Origin": "*",
        }
    )


@router.get("/epg.xml", response_class=Response)
def get_epg(
    country: Optional[str] = Query(None, description="Language code override (e.g. 'cs', 'sk', 'hu')"),
    refresh: bool = Query(False, description="Force fresh download from Sweet.tv"),
    legacy_id: Optional[bool] = Query(False, description="Use legacy .id.com suffix for channel IDs")
):
    """Returns XMLTV Electronic Program Guide formatted XML."""
    if not config.is_logged:
        raise HTTPException(status_code=401, detail="Sweet.tv login required.")

    xml_content = generate_xmltv_epg(country_code=country, force_refresh=refresh, legacy_id=bool(legacy_id))
    return Response(
        content=xml_content,
        media_type="text/xml; charset=utf-8",
        headers={
            "Content-Disposition": 'inline; filename="epg.xml"',
            "Cache-Control": "public, max-age=1800",
            "Access-Control-Allow-Origin": "*",
        }
    )


@router.get("/epg.xml.gz", response_class=Response)
def get_epg_gz():
    """Returns gzip-compressed XMLTV EPG for fast client downloads."""
    if not config.is_logged:
        raise HTTPException(status_code=401, detail="Unauthorized")

    gz_content = get_xmltv_epg_gz()
    return Response(
        content=gz_content,
        media_type="application/gzip",
        headers={
            "Content-Disposition": 'attachment; filename="epg.xml.gz"',
            "Content-Encoding": "gzip",
            "Cache-Control": "public, max-age=1800",
            "Access-Control-Allow-Origin": "*",
        }
    )


@router.get("/stream/variant.m3u8", response_class=Response)
def get_stream_variant(request: Request, url: str = Query(..., description="Target Sweet.tv variant URL")):
    """
    Proxies variant M3U8 with legitimate headers and rewrites relative TS paths
    to absolute CDN URLs.
    """
    raw_url = unquote(url)
    base_url = get_effective_base_url(request)
    content, media_type = build_proxy_variant_m3u8(raw_url, base_url)

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        }
    )


@router.get("/stream/{channel_id}.m3u8", response_class=Response)
@router.get("/stream/{channel_id}", response_class=Response)
@router.get("/play/{channel_id}.m3u8", response_class=Response)
@router.get("/play/{channel_id}", response_class=Response)
def get_channel_stream(
    request: Request,
    channel_id: str,
    quality: Optional[str] = Query(None, description="Quality preset: 'auto', 'best', '1080p', '720p'"),
    epg_id: Optional[int] = Query(None, description="Direct EPG program ID for catchup archive"),
    utc: Optional[int] = Query(None, description="UTC timestamp for catchup replay"),
    start: Optional[int] = Query(None, description="Start timestamp for catchup replay")
):
    """
    Main HLS Stream Endpoint for Live TV & Timestamp Catchup.
    Proxies manifest with legit Chrome headers to prevent Sweet.tv CDN blocking,
    rewriting variant URLs for IPTVnator, Video.js, Kodi, and VLC.
    Supports both live streaming and timestamp-based archive replay.
    """
    if not config.is_logged:
        raise HTTPException(status_code=401, detail="Sweet.tv login required.")

    params = parse_stream_query(request)
    req_quality = params.get("quality") or quality or config.default_quality

    try:
        cid = clean_id(channel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid channel ID.")

    # 1. Direct epg_id from query parameter
    target_epg_id = epg_id
    if not target_epg_id and params.get("epg_id"):
        try:
            target_epg_id = int(params["epg_id"])
        except ValueError:
            pass

    # 2. Timestamp resolution from utc, start, or timestamp parameter
    if not target_epg_id:
        ts_val = params.get("utc") or params.get("start") or params.get("timestamp") or utc or start
        if ts_val:
            target_epg_id = resolve_epg_id_from_utc(cid, ts_val)

    base_url = get_effective_base_url(request)
    content, media_type = build_proxy_master_m3u8(
        channel_id=cid,
        base_url=base_url,
        epg_id=target_epg_id,
        quality=req_quality
    )

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        }
    )


@router.get("/stream/{channel_id}/{epg_id}.m3u8", response_class=Response)
@router.get("/stream/{channel_id}/{epg_id}", response_class=Response)
@router.get("/play/{channel_id}/{epg_id}.m3u8", response_class=Response)
@router.get("/play/{channel_id}/{epg_id}", response_class=Response)
def get_catchup_stream(
    request: Request,
    channel_id: str,
    epg_id: str,
    quality: Optional[str] = Query(None, description="Quality preset")
):
    """Catchup archive replay stream endpoint."""
    if not config.is_logged:
        raise HTTPException(status_code=401, detail="Sweet.tv login required.")

    params = parse_stream_query(request)
    req_quality = params.get("quality") or quality or config.default_quality

    try:
        cid = clean_id(channel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid channel ID.")

    pid = None
    epg_id_str = str(epg_id).strip()
    is_placeholder = (
        epg_id_str.startswith("{") or 
        epg_id_str.lower() in ("null", "none", "0", "undefined", "live")
    )
    if not is_placeholder:
        try:
            raw_clean = epg_id_str.split("|")[0].split(".")[0].strip()
            digits = "".join(c for c in raw_clean if c.isdigit())
            if digits:
                num_val = int(digits)
                # If number is in standard Unix timestamp range (1 to 3 billion), resolve via EPG
                if 1_000_000_000 <= num_val <= 3_000_000_000:
                    pid = resolve_epg_id_from_utc(cid, num_val) or num_val
                else:
                    pid = num_val
        except Exception:
            pid = None

    # If pid could not be determined from path, inspect query parameters
    if not pid:
        ts_val = params.get("utc") or params.get("start") or params.get("timestamp")
        if ts_val:
            pid = resolve_epg_id_from_utc(cid, ts_val)
        elif params.get("epg_id"):
            try:
                pid = int(params["epg_id"])
            except ValueError:
                pass

    base_url = get_effective_base_url(request)
    content, media_type = build_proxy_master_m3u8(
        channel_id=cid,
        base_url=base_url,
        epg_id=pid,
        quality=req_quality
    )

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        }
    )


