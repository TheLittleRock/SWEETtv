import logging
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, unquote
from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.auth import validate_token_or_session
from app.config import config
from app.epg import generate_m3u_playlist, generate_xmltv_epg, get_xmltv_epg_gz
from app.providers.manager import provider_manager
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


# =========================================================================
# M3U PLAYLIST ROUTES (TOKEN QUERY PARAM & PATH PREFIX /t/{token}/)
# =========================================================================

@router.get("/playlist.m3u", response_class=Response)
@router.get("/playlist.m3u8", response_class=Response)
@router.get("/playlist_clean.m3u", response_class=Response)
@router.get("/playlist_bare.m3u", response_class=Response)
@router.get("/t/{token}/playlist.m3u", response_class=Response)
@router.get("/t/{token}/playlist.m3u8", response_class=Response)
@router.get("/t/{token}/playlist_clean.m3u", response_class=Response)
@router.get("/t/{token}/playlist_bare.m3u", response_class=Response)
def get_playlist(
    request: Request,
    token: Optional[str] = None,
    source: Optional[str] = Query(None, description="Source filter: 'all', 'sweettv', 'oneplay'"),
    quality: Optional[str] = Query(None, description="Quality preset: 'auto', 'best', '1080p', '720p'"),
    catchup: Optional[str] = Query(None, description="Catchup mode: 'vod', 'default', 'none', '0'"),
    no_epg: Optional[bool] = Query(False, description="Omit url-tvg header to avoid triggering automatic EPG import"),
    legacy_id: Optional[bool] = Query(False, description="Use legacy .id.com suffix for channel IDs"),
    bare: Optional[bool] = Query(False, description="Ultra-minimal M3U with no attributes (for buggy parsers)")
):
    """
    Returns M3U/M3U8 playlist with full channel lineup, category groups, logos,
    and optional catchup replay support.
    Protected by user token or session.
    """
    user = validate_token_or_session(request, token)

    has_sweet = config.is_logged
    has_oneplay = config.oneplay_enabled and config.is_oneplay_logged

    target_source = (source or "all").lower().strip()
    if target_source in ("sweettv", "sweet") and not has_sweet:
        raise HTTPException(status_code=401, detail="Sweet.tv is not logged in.")
    elif target_source == "oneplay" and not has_oneplay:
        raise HTTPException(status_code=401, detail="Oneplay is not logged in.")
    elif not has_sweet and not has_oneplay:
        raise HTTPException(
            status_code=401,
            detail="Server is not logged in to any IPTV provider (Sweet.tv or Oneplay). Please authenticate first via Web UI."
        )

    # If requested via /playlist_clean.m3u or /playlist_bare.m3u
    is_bare = bool(bare) or request.url.path.endswith("playlist_bare.m3u")
    is_clean = is_bare or no_epg or request.url.path.endswith("playlist_clean.m3u")
    base_url = get_effective_base_url(request)

    is_path_token = request.url.path.startswith("/t/")
    token_mode = "path" if is_path_token else "query"

    playlist_text = provider_manager.generate_m3u(
        base_url=base_url,
        source=target_source,
        quality=quality or config.default_quality,
        catchup=catchup,
        no_epg=is_clean,
        token=user.token,
        token_mode=token_mode
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


# =========================================================================
# XMLTV EPG ROUTES
# =========================================================================

@router.get("/epg.xml", response_class=Response)
@router.get("/t/{token}/epg.xml", response_class=Response)
def get_epg(
    request: Request,
    token: Optional[str] = None,
    country: Optional[str] = Query(None, description="Language code override (e.g. 'cs', 'sk', 'hu')"),
    refresh: bool = Query(False, description="Force fresh download from Sweet.tv"),
    legacy_id: Optional[bool] = Query(False, description="Use legacy .id.com suffix for channel IDs")
):
    """Returns XMLTV Electronic Program Guide formatted XML."""
    validate_token_or_session(request, token)

    # Check if channel is an Oneplay channel
    raw_cid = channel_id.replace(".m3u8", "").strip()
    if raw_cid.startswith("oneplay:") or "~" in raw_cid or (not raw_cid.isdigit() and config.oneplay_enabled):
        target_cid = raw_cid.replace("oneplay:", "")
        return get_oneplay_stream(request, target_cid, token=token, utc=utc, start=start)

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
@router.get("/t/{token}/epg.xml.gz", response_class=Response)
def get_epg_gz(request: Request, token: Optional[str] = None):
    """Returns gzip-compressed XMLTV EPG for fast client downloads."""
    validate_token_or_session(request, token)

    # Check if channel is an Oneplay channel
    raw_cid = channel_id.replace(".m3u8", "").strip()
    if raw_cid.startswith("oneplay:") or "~" in raw_cid or (not raw_cid.isdigit() and config.oneplay_enabled):
        target_cid = raw_cid.replace("oneplay:", "")
        return get_oneplay_stream(request, target_cid, token=token, utc=utc, start=start)

    if not config.is_logged:
        raise HTTPException(status_code=401, detail="Sweet.tv login required.")

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


# =========================================================================
# STREAM PLAYBACK ROUTES
# =========================================================================

@router.get("/stream/oneplay/proxy_hls", response_class=Response)
def proxy_oneplay_hls(request: Request, url: str = Query(..., description="Target Oneplay HLS URL")):
    """
    Proxies child variant playlists for Oneplay using Firefox headers,
    while leaving video segment (.ts/.m4s) URLs directing to the CDN edge.
    """
    raw_url = unquote(url)
    base_url = get_effective_base_url(request)
    rewritten = provider_manager.oneplay.rewrite_manifest(raw_url, base_url)
    return Response(
        content=rewritten,
        media_type="application/vnd.apple.mpegurl",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        }
    )


@router.get("/stream/oneplay/{channel_id}.m3u8", response_class=Response)
@router.get("/stream/oneplay/{channel_id}", response_class=Response)
@router.get("/play/oneplay/{channel_id}.m3u8", response_class=Response)
@router.get("/play/oneplay/{channel_id}", response_class=Response)
@router.get("/t/{token}/stream/oneplay/{channel_id}.m3u8", response_class=Response)
@router.get("/t/{token}/stream/oneplay/{channel_id}", response_class=Response)
@router.get("/t/{token}/play/oneplay/{channel_id}.m3u8", response_class=Response)
@router.get("/t/{token}/play/oneplay/{channel_id}", response_class=Response)
def get_oneplay_stream(
    request: Request,
    channel_id: str,
    token: Optional[str] = None,
    utc: Optional[int] = Query(None, description="UTC timestamp for catchup"),
    start: Optional[int] = Query(None, description="Start timestamp for catchup")
):
    """Main HLS Stream Endpoint for Oneplay Live TV & Catchup."""
    validate_token_or_session(request, token)
    params = parse_stream_query(request)
    ts_val = params.get("utc") or params.get("start") or params.get("timestamp") or utc or start
    utc_time = safe_parse_timestamp(ts_val)

    clean_cid = channel_id.replace(".m3u8", "").strip()
    stream_info = provider_manager.oneplay.get_stream_details(clean_cid, utc_time=utc_time)
    if not stream_info or not stream_info.get("master_url"):
        raise HTTPException(status_code=502, detail="Failed to retrieve stream from Oneplay.")

    base_url = get_effective_base_url(request)
    rewritten_manifest = provider_manager.oneplay.rewrite_manifest(stream_info["master_url"], base_url)

    return Response(
        content=rewritten_manifest,
        media_type="application/vnd.apple.mpegurl",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        }
    )


@router.get("/stream/variant.m3u8", response_class=Response)
@router.get("/t/{token}/stream/variant.m3u8", response_class=Response)
def get_stream_variant(
    request: Request,
    url: str = Query(..., description="Target Sweet.tv variant URL"),
    token: Optional[str] = None
):
    """
    Proxies variant M3U8 with legitimate headers and rewrites relative TS paths
    to absolute CDN URLs.
    """
    validate_token_or_session(request, token)

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
@router.get("/t/{token}/stream/{channel_id}.m3u8", response_class=Response)
@router.get("/t/{token}/stream/{channel_id}", response_class=Response)
@router.get("/t/{token}/play/{channel_id}.m3u8", response_class=Response)
@router.get("/t/{token}/play/{channel_id}", response_class=Response)
def get_channel_stream(
    request: Request,
    channel_id: str,
    token: Optional[str] = None,
    quality: Optional[str] = Query(None, description="Quality preset: 'auto', 'best', '1080p', '720p'"),
    epg_id: Optional[int] = Query(None, description="Direct EPG program ID for catchup archive"),
    utc: Optional[int] = Query(None, description="UTC timestamp for catchup replay"),
    start: Optional[int] = Query(None, description="Start timestamp for catchup replay")
):
    """
    Main HLS Stream Endpoint for Live TV & Timestamp Catchup.
    Protected by user token or session.
    """
    validate_token_or_session(request, token)

    # Check if channel is an Oneplay channel
    raw_cid = channel_id.replace(".m3u8", "").strip()
    if raw_cid.startswith("oneplay:") or "~" in raw_cid or (not raw_cid.isdigit() and config.oneplay_enabled):
        target_cid = raw_cid.replace("oneplay:", "")
        return get_oneplay_stream(request, target_cid, token=token, utc=utc, start=start)

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
@router.get("/t/{token}/stream/{channel_id}/{epg_id}.m3u8", response_class=Response)
@router.get("/t/{token}/stream/{channel_id}/{epg_id}", response_class=Response)
@router.get("/t/{token}/play/{channel_id}/{epg_id}.m3u8", response_class=Response)
@router.get("/t/{token}/play/{channel_id}/{epg_id}", response_class=Response)
def get_catchup_stream(
    request: Request,
    channel_id: str,
    epg_id: str,
    token: Optional[str] = None,
    quality: Optional[str] = Query(None, description="Quality preset")
):
    """Catchup archive replay stream endpoint."""
    validate_token_or_session(request, token)

    # Check if channel is an Oneplay channel
    raw_cid = channel_id.replace(".m3u8", "").strip()
    if raw_cid.startswith("oneplay:") or "~" in raw_cid or (not raw_cid.isdigit() and config.oneplay_enabled):
        target_cid = raw_cid.replace("oneplay:", "")
        return get_oneplay_stream(request, target_cid, token=token, utc=utc, start=start)

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
                if 1_000_000_000 <= num_val <= 3_000_000_000:
                    pid = resolve_epg_id_from_utc(cid, num_val) or num_val
                else:
                    pid = num_val
        except Exception:
            pid = None

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
