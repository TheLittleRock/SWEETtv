import asyncio
import logging
import os
import re
import shutil
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
from typing import AsyncGenerator, Dict, List, Optional
import requests

logger = logging.getLogger("SweetTV.DRM.Streamer")

DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0"


def find_ffmpeg_binary() -> Optional[str]:
    """Finds the best available FFmpeg binary (preferring static FFmpeg 7+ builds)."""
    candidates = [
        "/usr/local/bin/ffmpeg",
        "/tmp/ffstatic/ffmpeg",
        shutil.which("ffmpeg")
    ]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def rewrite_mpd_tokens(mpd_content: str, base_url: str) -> str:
    """
    Rewrites MPD manifest to propagate CDN query authentication tokens (e.g. ?token=...)
    to all SegmentTemplate initialization and media attributes, and ensures valid BaseURL.
    """
    parsed_base = urllib.parse.urlparse(base_url)
    query_str = parsed_base.query
    if not query_str:
        return mpd_content

    base_dir = base_url.split("?")[0].rsplit("/", 1)[0] + "/"

    # Register XML namespaces
    ET.register_namespace("", "urn:mpeg:dash:schema:mpd:2011")
    ET.register_namespace("cenc", "urn:mpeg:cenc:2013")
    ET.register_namespace("mspr", "urn:microsoft:playready")
    ET.register_namespace("up", "urn:mpeg:dash:schema:urlparam:2014")

    try:
        root = ET.fromstring(mpd_content)

        # Ensure BaseURL points to the CDN directory with auth query token
        ns = {"mpd": "urn:mpeg:dash:schema:mpd:2011"}
        base_elem = root.find("mpd:BaseURL", ns)
        if base_elem is None:
            base_elem = ET.Element("{urn:mpeg:dash:schema:mpd:2011}BaseURL")
            base_elem.text = f"{base_dir}?{query_str}"
            root.insert(0, base_elem)
        else:
            if base_elem.text and not base_elem.text.startswith("http"):
                base_elem.text = urllib.parse.urljoin(base_dir, base_elem.text)
            if base_elem.text and query_str not in base_elem.text:
                sep = "&" if "?" in base_elem.text else "?"
                base_elem.text = f"{base_elem.text}{sep}{query_str}"

        # Propagate token to segment templates
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag in ("SegmentTemplate", "Initialization", "SegmentURL"):
                for attr in ("initialization", "media", "sourceURL"):
                    val = elem.get(attr)
                    if val and query_str not in val:
                        sep = "&" if "?" in val else "?"
                        elem.set(attr, f"{val}{sep}{query_str}")

        return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")
    except Exception as e:
        logger.warning(f"Error parsing MPD with xml.etree, using regex fallback: {e}")
        def _append_token(match):
            attr_name = match.group(1)
            url_val = match.group(2)
            if query_str not in url_val:
                sep = "&" if "?" in url_val else "?"
                url_val = f"{url_val}{sep}{query_str}"
            return f'{attr_name}="{url_val}"'

        rewritten = re.sub(r'(initialization|media|sourceURL)=["\']([^"\']+)["\']', _append_token, mpd_content, flags=re.IGNORECASE)
        return rewritten


async def ffmpeg_stream_generator(
    stream_url: str,
    decryption_keys: List[str],
    headers: Optional[Dict[str, str]] = None,
    chunk_size: int = 65536
) -> AsyncGenerator[bytes, None]:
    """
    Spawns modern FFmpeg to decrypt and remux a DASH/HLS CENC stream on-the-fly
    into a standard MPEG-TS byte stream without re-encoding (-c copy).
    Propagates CDN query tokens to relative segments to eliminate 403 Forbidden errors.
    """
    ffmpeg_bin = find_ffmpeg_binary()
    if not ffmpeg_bin:
        logger.error("FFmpeg binary not found on system PATH. Cannot stream decrypted content.")
        return

    ua = (headers or {}).get("User-Agent") or DEFAULT_UA
    custom_headers = []
    if headers:
        for k, v in headers.items():
            if k.lower() != "user-agent":
                custom_headers.append(f"{k}: {v}")
    if not any("referer" in h.lower() for h in custom_headers):
        custom_headers.append("Referer: https://www.oneplay.cz/")

    header_str = "\r\n".join(custom_headers) + "\r\n" if custom_headers else ""

    temp_mpd_path: Optional[str] = None
    input_target = stream_url

    # For DASH manifests, fetch and rewrite MPD to propagate CDN auth tokens to segments
    if ".mpd" in stream_url.lower():
        try:
            h = {"User-Agent": ua}
            for hdr in custom_headers:
                if ":" in hdr:
                    k, v = hdr.split(":", 1)
                    h[k.strip()] = v.strip()
            r = requests.get(stream_url, headers=h, timeout=10)
            if r.status_code == 200 and len(r.text) > 50:
                rewritten = rewrite_mpd_tokens(r.text, stream_url)
                fd, temp_mpd_path = tempfile.mkstemp(suffix=".mpd", prefix="vod_dash_")
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(rewritten)
                input_target = temp_mpd_path
                logger.info(f"Successfully prepared token-propagated DASH MPD manifest at {temp_mpd_path}")
            else:
                logger.warning(f"Failed to fetch MPD manifest for token rewriting (HTTP {r.status_code}), using direct URL")
        except Exception as e:
            logger.warning(f"Error fetching/rewriting MPD manifest: {e}, falling back to direct URL")

    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel", "warning",
        "-allowed_extensions", "ALL",
        "-user_agent", ua,
    ]

    if header_str:
        cmd.extend(["-headers", header_str])

    # Pass all available decryption keys using both cenc_decryption_key and decryption_key
    valid_keys = [k for k in decryption_keys if k and len(k) == 32]
    for key in valid_keys:
        cmd.extend(["-cenc_decryption_key", key, "-decryption_key", key])

    # Input target
    cmd.extend(["-i", input_target])

    # Passthrough copy to MPEG-TS container
    cmd.extend([
        "-c", "copy",
        "-f", "mpegts",
        "pipe:1"
    ])

    logger.info(f"Starting FFmpeg DRM streaming process ({ffmpeg_bin}) with {len(valid_keys)} key(s)...")
    proc = None
    stderr_lines = []
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        async def read_stderr():
            if proc and proc.stderr:
                while True:
                    line = await proc.stderr.readline()
                    if not line:
                        break
                    decoded = line.decode("utf-8", errors="replace").strip()
                    if decoded:
                        stderr_lines.append(decoded)
                        logger.warning(f"[FFmpeg] {decoded}")

        stderr_task = asyncio.create_task(read_stderr())

        total_bytes = 0
        while True:
            chunk = await proc.stdout.read(chunk_size)
            if not chunk:
                break
            total_bytes += len(chunk)
            yield chunk

        await proc.wait()
        stderr_task.cancel()

        if proc.returncode != 0 and total_bytes == 0:
            err_summary = " | ".join(stderr_lines[-5:]) if stderr_lines else f"exit code {proc.returncode}"
            logger.error(f"FFmpeg process exited abnormally with code {proc.returncode}: {err_summary}")
        else:
            logger.info(f"FFmpeg DRM stream finished normally, streamed {total_bytes} bytes")

    except (asyncio.CancelledError, GeneratorExit):
        logger.info("Client disconnected from DRM stream, closing FFmpeg process")
    except Exception as e:
        logger.error(f"Error during FFmpeg streaming: {e}", exc_info=True)
    finally:
        if proc and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
        if temp_mpd_path and os.path.exists(temp_mpd_path):
            try:
                os.remove(temp_mpd_path)
            except Exception:
                pass
        logger.debug("FFmpeg DRM streaming process cleanup complete")
