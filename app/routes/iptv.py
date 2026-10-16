import logging
from typing import Optional
from urllib.parse import unquote
from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.config import config
from app.epg import generate_m3u_playlist, generate_xmltv_epg, get_xmltv_epg_gz
from app.stream import build_proxy_master_m3u8, build_proxy_variant_m3u8

logger = logging.getLogger("SweetTV.Routes.IPTV")
router = APIRouter(tags=["IPTV"])


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
    """Strips file extensions or pipe parameters from IDs."""
    clean = raw_id.split("|")[0].split(".")[0].strip()
    return int(clean)


@router.get("/playlist.m3u", response_class=Response)
@router.get("/playlist.m3u8", response_class=Response)
def get_playlist(
    request: Request,
    quality: Optional[str] = Query(None, description="Quality preset: 'auto', 'best' (highest bitrate), '1080p', '720p'"),
    catchup: Optional[str] = Query(None, description="Catchup mode: 'vod', 'default', 'none', '0'")
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

    base_url = get_effective_base_url(request)
    playlist_text = generate_m3u_playlist(
        base_url,
        quality=quality or config.default_quality,
        catchup=catchup
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
    refresh: bool = Query(False, description="Force fresh download from Sweet.tv")
):
    """Returns XMLTV Electronic Program Guide formatted XML."""
    if not config.is_logged:
        raise HTTPException(status_code=401, detail="Sweet.tv login required.")

    xml_content = generate_xmltv_epg(country_code=country, force_refresh=refresh)
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

    try:
        cid = clean_id(channel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid channel ID.")

    # Resolve catchup epg_id if timestamp provided
    target_epg_id = epg_id
    if not target_epg_id and (utc or start):
        from app.stream import resolve_epg_id_from_utc
        target_epg_id = resolve_epg_id_from_utc(cid, utc or start)

    base_url = get_effective_base_url(request)
    content, media_type = build_proxy_master_m3u8(
        channel_id=cid,
        base_url=base_url,
        epg_id=target_epg_id,
        quality=quality or config.default_quality
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

    try:
        cid = clean_id(channel_id)
        pid = clean_id(epg_id) if epg_id.lower() not in ("null", "none", "0") else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid IDs.")

    base_url = get_effective_base_url(request)
    content, media_type = build_proxy_master_m3u8(
        channel_id=cid,
        base_url=base_url,
        epg_id=pid,
        quality=quality or config.default_quality
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


