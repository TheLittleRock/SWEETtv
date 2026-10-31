import asyncio
import logging
import os
import re
import shutil
import struct
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
from typing import AsyncGenerator, Dict, List, Optional, Tuple
import requests

logger = logging.getLogger("SweetTV.DRM.Streamer")

DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0"

# ISO 639-1 / 639-2 language normalization mapping
ISO_639_MAP: Dict[str, str] = {
    "cs": "ces",
    "cze": "ces",
    "ces": "ces",
    "cz": "ces",
    "sk": "slk",
    "slo": "slk",
    "slk": "slk",
    "en": "eng",
    "eng": "eng",
    "de": "deu",
    "ger": "deu",
    "deu": "deu",
    "pl": "pol",
    "fr": "fra",
    "fre": "fra",
    "fra": "fra",
    "es": "spa",
    "spa": "spa",
    "it": "ita",
    "hu": "hun",
    "ru": "rus",
    "uk": "ukr",
    "ro": "ron",
    "bg": "bul",
    "hr": "hrv",
    "sr": "srp",
    "sl": "slv",
    "und": "ces",
}


def normalize_lang_code(code: Optional[str]) -> str:
    """Normalizes language code to ISO 639-2 3-letter code, defaulting to 'ces' if empty or unknown."""
    if not code:
        return "ces"
    clean = str(code).strip().lower()
    if clean in ISO_639_MAP:
        return ISO_639_MAP[clean]
    if len(clean) == 3:
        return clean
    return "ces"


def parse_iso8601_duration(dur_str: Optional[str]) -> float:
    """Parses ISO 8601 duration string (e.g. PT32M5.160S or PT1H45M30S) to float seconds."""
    if not dur_str:
        return 0.0
    pattern = r"PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?"
    m = re.match(pattern, str(dur_str).strip())
    if not m:
        return 0.0
    h = float(m.group("hours") or 0)
    minutes = float(m.group("minutes") or 0)
    s = float(m.group("seconds") or 0)
    return h * 3600.0 + minutes * 60.0 + s


def patch_mp4_duration(buffer: bytes, duration_sec: float) -> bytes:
    """
    Patches mvhd, tkhd, and mdhd boxes in the initial MP4 moov atom
    to report the presentation's real duration instead of 0.
    Ensures players (VLC, IPTVnator, web players) report the true movie/episode length.
    """
    if duration_sec <= 0 or len(buffer) < 32:
        return buffer

    data = bytearray(buffer)
    # 1. Locate and patch mvhd
    mvhd_idx = data.find(b"mvhd")
    if mvhd_idx == -1:
        return buffer

    ver = data[mvhd_idx + 4]
    mv_ts = 0
    if ver == 0:
        mv_ts = struct.unpack(">I", data[mvhd_idx + 16 : mvhd_idx + 20])[0]
        if mv_ts > 0:
            val = min(max(int(duration_sec * mv_ts), 0), 0xFFFFFFFF)
            data[mvhd_idx + 20 : mvhd_idx + 24] = struct.pack(">I", val)
    elif ver == 1:
        mv_ts = struct.unpack(">I", data[mvhd_idx + 24 : mvhd_idx + 28])[0]
        if mv_ts > 0:
            val = min(max(int(duration_sec * mv_ts), 0), 0xFFFFFFFFFFFFFFFF)
            data[mvhd_idx + 28 : mvhd_idx + 36] = struct.pack(">Q", val)

    # 2. Patch all tkhd boxes (Track headers)
    pos = 0
    while True:
        idx = data.find(b"tkhd", pos)
        if idx == -1:
            break
        t_ver = data[idx + 4]
        if t_ver == 0 and mv_ts > 0:
            val = min(max(int(duration_sec * mv_ts), 0), 0xFFFFFFFF)
            data[idx + 24 : idx + 28] = struct.pack(">I", val)
        elif t_ver == 1 and mv_ts > 0:
            val = min(max(int(duration_sec * mv_ts), 0), 0xFFFFFFFFFFFFFFFF)
            data[idx + 32 : idx + 40] = struct.pack(">Q", val)
        pos = idx + 4

    # 3. Patch all mdhd boxes (Media headers)
    pos = 0
    while True:
        idx = data.find(b"mdhd", pos)
        if idx == -1:
            break
        m_ver = data[idx + 4]
        if m_ver == 0:
            md_ts = struct.unpack(">I", data[idx + 16 : idx + 20])[0]
            if md_ts > 0:
                val = min(max(int(duration_sec * md_ts), 0), 0xFFFFFFFF)
                data[idx + 20 : idx + 24] = struct.pack(">I", val)
        elif m_ver == 1:
            md_ts = struct.unpack(">I", data[idx + 24 : idx + 28])[0]
            if md_ts > 0:
                val = min(max(int(duration_sec * md_ts), 0), 0xFFFFFFFFFFFFFFFF)
                data[idx + 28 : idx + 36] = struct.pack(">Q", val)
        pos = idx + 4

    return bytes(data)


def find_ffmpeg_binary() -> Optional[str]:
    """Finds the best available FFmpeg binary (preferring static FFmpeg builds)."""
    candidates = [
        "/usr/local/bin/ffmpeg",
        os.path.expanduser("~/.local/bin/ffmpeg"),
        shutil.which("ffmpeg")
    ]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def rewrite_mpd_tokens(mpd_content: str, base_url: str) -> str:
    """Legacy helper for rewriting MPD manifests with CDN tokens."""
    rewritten, _, _, _ = prepare_dash_manifest(mpd_content, base_url)
    return rewritten


def prepare_dash_manifest(
    mpd_content: str,
    base_url: str
) -> Tuple[str, List[str], List[str], float]:
    """
    Prepares a DASH manifest for streaming:
    1. Propagates CDN query tokens to absolute BaseURL and SegmentTemplate/Initialization URLs.
    2. Prunes video representations to keep only the highest bitrate representation (e.g. 1080p).
    3. Extracts all audio track languages, normalized to ISO 639-2 (defaulting to 'ces').
    4. Extracts all subtitle track languages, normalized to ISO 639-2 (defaulting to 'ces').
    5. Extracts media presentation duration in seconds.
    Returns (rewritten_mpd_content, audio_languages, subtitle_languages, duration_secs).
    """
    parsed_base = urllib.parse.urlparse(base_url)
    query_str = parsed_base.query
    base_dir = base_url.split("?")[0].rsplit("/", 1)[0] + "/"

    audio_languages: List[str] = []
    subtitle_languages: List[str] = []
    duration_secs: float = 0.0

    # Register XML namespaces
    ET.register_namespace("", "urn:mpeg:dash:schema:mpd:2011")
    ET.register_namespace("cenc", "urn:mpeg:cenc:2013")
    ET.register_namespace("mspr", "urn:microsoft:playready")
    ET.register_namespace("up", "urn:mpeg:dash:schema:urlparam:2014")

    try:
        root = ET.fromstring(mpd_content)
        ns = {"mpd": "urn:mpeg:dash:schema:mpd:2011"}

        # Extract duration
        dur_attr = root.get("mediaPresentationDuration")
        if dur_attr:
            duration_secs = parse_iso8601_duration(dur_attr)

        # Ensure BaseURL points to the absolute CDN directory with auth query token if any
        base_elem = root.find("mpd:BaseURL", ns)
        if base_elem is None:
            base_elem = ET.Element("{urn:mpeg:dash:schema:mpd:2011}BaseURL")
            base_elem.text = f"{base_dir}?{query_str}" if query_str else base_dir
            root.insert(0, base_elem)
        else:
            if base_elem.text and not base_elem.text.startswith("http"):
                base_elem.text = urllib.parse.urljoin(base_dir, base_elem.text)
            if query_str and base_elem.text and query_str not in base_elem.text:
                sep = "&" if "?" in base_elem.text else "?"
                base_elem.text = f"{base_elem.text}{sep}{query_str}"

        # Propagate token to segment templates if query_str present
        if query_str:
            for elem in root.iter():
                tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                if tag in ("SegmentTemplate", "Initialization", "SegmentURL"):
                    for attr in ("initialization", "media", "sourceURL"):
                        val = elem.get(attr)
                        if val and query_str not in val:
                            sep = "&" if "?" in val else "?"
                            elem.set(attr, f"{val}{sep}{query_str}")

        # Scan and prune AdaptationSets
        for as_elem in root.findall(".//mpd:AdaptationSet", ns):
            ct = (as_elem.get("contentType") or "").lower()
            mime = (as_elem.get("mimeType") or "").lower()
            lang = as_elem.get("lang")

            is_video = ct == "video" or "video/" in mime
            is_audio = ct == "audio" or "audio/" in mime
            is_text = ct in ("text", "subtitles") or "vtt" in mime or "text/" in mime

            if is_video:
                # Retain only the highest bandwidth video representation
                reps = as_elem.findall("mpd:Representation", ns)
                if reps:
                    def _rep_bw(r):
                        try:
                            return int(r.get("bandwidth", 0))
                        except Exception:
                            return 0
                    best_rep = max(reps, key=_rep_bw)
                    for rep in reps:
                        if rep != best_rep:
                            as_elem.remove(rep)

            elif is_audio:
                # Track audio stream language
                track_lang = normalize_lang_code(lang)
                audio_languages.append(track_lang)

            elif is_text:
                # Track subtitle stream language
                track_lang = normalize_lang_code(lang)
                subtitle_languages.append(track_lang)

        # Fallback if no audio adaptation set was explicitly flagged
        if not audio_languages:
            audio_languages.append("ces")

        rewritten = ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")
        return rewritten, audio_languages, subtitle_languages, duration_secs

    except Exception as e:
        logger.warning(f"Error parsing MPD with xml.etree, using fallback: {e}")
        def _append_token(match):
            attr_name = match.group(1)
            url_val = match.group(2)
            if query_str and query_str not in url_val:
                sep = "&" if "?" in url_val else "?"
                url_val = f"{url_val}{sep}{query_str}"
            return f'{attr_name}="{url_val}"'

        rewritten = re.sub(
            r'(initialization|media|sourceURL)=["\']([^"\']+)["\']',
            _append_token,
            mpd_content,
            flags=re.IGNORECASE
        )
        return rewritten, ["ces"], [], 0.0


async def ffmpeg_stream_generator(
    stream_url: str,
    decryption_keys: List[str],
    headers: Optional[Dict[str, str]] = None,
    output_format: str = "ts",
    duration_secs: Optional[float] = None,
    chunk_size: int = 65536
) -> AsyncGenerator[bytes, None]:
    """
    Spawns modern FFmpeg to decrypt and remux a DASH/HLS CENC stream on-the-fly
    into a standard MPEG-TS or fragmented MP4 byte stream without re-encoding (-c copy).
    Preserves all audio streams, language codes (defaulting to Czech 'ces'), and subtitles.
    Injects presentation duration into initial MP4 moov atom so players report full length.
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
    audio_languages: List[str] = ["ces"]
    subtitle_languages: List[str] = []
    target_duration: float = float(duration_secs or 0.0)

    # For DASH manifests, fetch, prune, rewrite MPD with absolute BaseURL and extract language metadata
    if ".mpd" in stream_url.lower():
        try:
            h = {"User-Agent": ua}
            for hdr in custom_headers:
                if ":" in hdr:
                    k, v = hdr.split(":", 1)
                    h[k.strip()] = v.strip()
            r = requests.get(stream_url, headers=h, timeout=10)
            if r.status_code == 200 and len(r.text) > 50:
                rewritten, a_langs, s_langs, mpd_dur = prepare_dash_manifest(r.text, stream_url)
                if a_langs:
                    audio_languages = a_langs
                if s_langs:
                    subtitle_languages = s_langs
                if mpd_dur > 0 and target_duration <= 0:
                    target_duration = mpd_dur

                fd, temp_mpd_path = tempfile.mkstemp(suffix=".mpd", prefix="vod_dash_")
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(rewritten)
                input_target = temp_mpd_path
                logger.info(
                    f"Prepared DASH MPD: {temp_mpd_path} | Audio: {audio_languages} | Subs: {subtitle_languages} | Duration: {target_duration}s"
                )
            else:
                logger.warning(f"Failed to fetch MPD manifest (HTTP {r.status_code}), using direct URL")
        except Exception as e:
            logger.warning(f"Error preparing DASH MPD manifest: {e}, falling back to direct URL")

    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel", "warning",
        "-allowed_extensions", "ALL",
        "-protocol_whitelist", "file,crypto,data,https,tls,tcp",
    ]

    # Only pass HTTP protocol headers/user_agent if input target is an HTTP(S) URL
    if input_target.startswith("http://") or input_target.startswith("https://"):
        cmd.extend(["-user_agent", ua])
        if header_str:
            cmd.extend(["-headers", header_str])

    # Pass all available decryption keys using cenc_decryption_key
    valid_keys = [k for k in decryption_keys if k and len(k) == 32]
    if valid_keys:
        cmd.extend(["-cenc_decryption_key", valid_keys[0]])

    # Input target
    cmd.extend(["-i", input_target])

    # Stream mapping: 1 video stream, all audio streams
    cmd.extend([
        "-map", "0:v:0",
        "-c:v", "copy",
        "-map", "0:a?",
        "-c:a", "copy",
    ])

    # Tag all audio streams with their ISO 639-2 language codes
    for idx, lang in enumerate(audio_languages):
        cmd.extend([f"-metadata:s:a:{idx}", f"language={lang}"])

    # Subtitle stream mapping
    if subtitle_languages:
        cmd.extend(["-map", "0:s?"])
        if output_format.lower() == "mp4":
            cmd.extend(["-c:s", "mov_text"])
        else:
            cmd.extend(["-c:s", "copy"])
        for idx, lang in enumerate(subtitle_languages):
            cmd.extend([f"-metadata:s:s:{idx}", f"language={lang}"])
    else:
        cmd.append("-sn")

    # Output container format
    if output_format.lower() == "mp4":
        cmd.extend([
            "-f", "mp4",
            "-movie_timescale", "1000",
            "-movflags", "frag_keyframe+empty_moov+default_base_moof",
            "pipe:1"
        ])
    else:
        cmd.extend([
            "-f", "mpegts",
            "pipe:1"
        ])

    logger.info(
        f"Starting FFmpeg DRM streaming ({ffmpeg_bin}) -> format={output_format}, "
        f"keys={len(valid_keys)}, audio_tracks={len(audio_languages)}, duration={target_duration}s..."
    )
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
        first_chunk_patched = False
        while True:
            chunk = await proc.stdout.read(chunk_size)
            if not chunk:
                break

            # Patch initial MP4 moov atom with real presentation duration
            if not first_chunk_patched and output_format.lower() == "mp4" and target_duration > 0:
                chunk = patch_mp4_duration(chunk, target_duration)
                first_chunk_patched = True

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
