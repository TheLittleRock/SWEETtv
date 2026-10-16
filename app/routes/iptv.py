import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse, StreamingResponse
import requests

from app.config import config
from app.epg import generate_m3u_playlist, generate_xmltv_epg, get_xmltv_epg_gz
from app.stream import resolve_stream_url

logger = logging.getLogger("SweetTV.Routes.IPTV")
router = APIRouter(tags=["IPTV"])


def get_effective_base_url(request: Request) -> str:
    """Computes public base URL taking reverse proxies (NPM) and config into account."""
    if config.external_url:
        return config.external_url

    # Check reverse proxy headers
    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host")
    if forwarded_proto and forwarded_host:
        return f"{forwarded_proto}://{forwarded_host}".rstrip("/")

    # Fall back to host header or request url
    host = request.headers.get("host")
    if host:
        proto = "https" if request.url.scheme == "https" or request.headers.get("x-forwarded-ssl") == "on" else request.url.scheme
        return f"{proto}://{host}".rstrip("/")

    return str(request.base_url).rstrip("/")


@router.get("/playlist.m3u", response_class=Response)
@router.get("/playlist.m3u8", response_class=Response)
def get_playlist(
    request: Request,
    quality: Optional[str] = Query(None, description="Quality preset: 'auto', 'best' (highest bitrate), '1080p', '720p'")
):
    """
    Returns M3U/M3U8 playlist with full channel lineup, category groups, logos,
    and catchup replay support.
    """
    if not config.is_logged:
        raise HTTPException(
            status_code=401,
            detail="Server is not logged in to Sweet.tv. Please authenticate first via Web UI."
        )

    base_url = get_effective_base_url(request)
    playlist_text = generate_m3u_playlist(base_url, quality=quality or config.default_quality)

    return Response(
        content=playlist_text,
        media_type="application/x-mpegurl",
        headers={
            "Content-Disposition": 'inline; filename="sweettv.m3u8"',
            "Cache-Control": "public, max-age=600",
            "Access-Control-Allow-Origin": "*",
        }
    )


@router.get("/epg.xml", response_class=Response)
def get_epg(
    request: Request,
    country: Optional[str] = Query(None, description="Language code override (e.g. 'cs', 'sk', 'hu')"),
    refresh: bool = Query(False, description="Force fresh download from Sweet.tv")
):
    """Returns XMLTV Electronic Program Guide formatted XML."""
    if not config.is_logged:
        raise HTTPException(
            status_code=401,
            detail="Server is not logged in to Sweet.tv. Please authenticate first via Web UI."
        )

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
    """Returns gzip-compressed XMLTV EPG for clients that support compressed guides."""
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


@router.get("/play/{channel_id}")
@router.get("/play/{channel_id}/{epg_id}")
def play_channel(
    channel_id: str,
    epg_id: Optional[str] = None,
    quality: Optional[str] = Query(None, description="Force quality: 'auto', 'best', '1080p', '720p'"),
    proxy: Optional[bool] = Query(None, description="Stream via server proxy instead of 302 redirect")
):
    """
    Resolves live or archive stream for channel.
    Defaults to fast 302 redirect directly to Sweet.tv's CDN (zero CPU/bandwidth overhead),
    or proxies the stream if proxy=true.
    """
    if not config.is_logged:
        raise HTTPException(status_code=401, detail="Unauthorized. Sweet.tv login required.")

    # Strip any appended player headers
    if "|" in channel_id:
        channel_id = channel_id.split("|")[0]
    if epg_id and "|" in epg_id:
        epg_id = epg_id.split("|")[0]

    try:
        cid = int(channel_id)
        pid = int(epg_id) if epg_id and epg_id.lower() not in ("null", "none", "0") else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid channel or epg ID.")

    stream_url = resolve_stream_url(cid, pid, quality=quality)
    if not stream_url:
        raise HTTPException(status_code=502, detail="Failed to retrieve stream from Sweet.tv provider.")

    use_proxy = proxy if proxy is not None else (not config.direct_redirect)

    if use_proxy:
        # Proxy stream through server
        try:
            req = requests.get(
                stream_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "Referer": "https://sweet.tv/",
                    "Origin": "https://sweet.tv"
                },
                stream=True,
                verify=False,
                timeout=10
            )
            return StreamingResponse(
                req.iter_content(chunk_size=65536),
                status_code=req.status_code,
                media_type=req.headers.get("Content-Type", "application/vnd.apple.mpegurl"),
                headers={"Access-Control-Allow-Origin": "*"}
            )
        except Exception as e:
            logger.error(f"Error proxying stream {stream_url}: {e}")
            return RedirectResponse(url=stream_url, status_code=302)

    # Direct 302 redirect to CDN node
    return RedirectResponse(
        url=stream_url,
        status_code=302,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache, no-store, must-revalidate"
        }
    )
