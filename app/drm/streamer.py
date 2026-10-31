import asyncio
import logging
import os
import shutil
from typing import AsyncGenerator, Dict, List, Optional

logger = logging.getLogger("SweetTV.DRM.Streamer")

DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0"


async def ffmpeg_stream_generator(
    stream_url: str,
    decryption_keys: List[str],
    headers: Optional[Dict[str, str]] = None,
    chunk_size: int = 65536
) -> AsyncGenerator[bytes, None]:
    """
    Spawns FFmpeg to decrypt and remux a DASH/HLS CENC stream on-the-fly
    into a standard MPEG-TS byte stream without re-encoding (-c copy).
    """
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        logger.error("FFmpeg binary not found on system PATH. Cannot stream decrypted content.")
        return

    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel", "warning",
    ]

    # Set user agent and HTTP headers
    ua = (headers or {}).get("User-Agent") or DEFAULT_UA
    cmd.extend(["-user_agent", ua])

    custom_headers = []
    if headers:
        for k, v in headers.items():
            if k.lower() != "user-agent":
                custom_headers.append(f"{k}: {v}")
    if not any("referer" in h.lower() for h in custom_headers):
        custom_headers.append("Referer: https://www.oneplay.cz/")

    if custom_headers:
        header_str = "\r\n".join(custom_headers) + "\r\n"
        cmd.extend(["-headers", header_str])

    # Pass all available decryption keys
    for key in decryption_keys:
        if key and len(key) == 32:
            cmd.extend(["-decryption_key", key])

    # Input stream URL
    cmd.extend(["-i", stream_url])

    # Passthrough copy to MPEG-TS container
    cmd.extend([
        "-c", "copy",
        "-f", "mpegts",
        "pipe:1"
    ])

    logger.info(f"Starting FFmpeg DRM remuxing process for URL: {stream_url[:60]}... with {len(decryption_keys)} key(s)")
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Async background reader for stderr to log any ffmpeg warnings/errors
        async def read_stderr():
            if proc and proc.stderr:
                while True:
                    line = await proc.stderr.readline()
                    if not line:
                        break
                    decoded = line.decode("utf-8", errors="replace").strip()
                    if decoded:
                        logger.warning(f"[FFmpeg] {decoded}")

        stderr_task = asyncio.create_task(read_stderr())

        while True:
            chunk = await proc.stdout.read(chunk_size)
            if not chunk:
                break
            yield chunk

        await proc.wait()
        stderr_task.cancel()

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
        logger.debug("FFmpeg DRM streaming process terminated")
