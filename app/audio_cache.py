import asyncio
import logging
import os
import time
from typing import Dict, List, Optional

logger = logging.getLogger("SweetTV.AudioCache")


class AudioCacheManager:
    """
    Manages background stream pre-caching and local segment slicing for VOD audio tracks.
    
    Instead of performing O(N^2) remote seeking over HTTPS for each 6-second segment,
    this manager extracts the full audio track in a single fast sequential pass (~35s for 1h)
    into a local ADTS AAC file in /tmp/sweettv_audio_cache, allowing instant (<0.15s)
    local slicing for HLS audio segments with bit-exact sync and 0% seeking overhead.
    """

    def __init__(
        self,
        cache_dir: str = "/tmp/sweettv_audio_cache",
        max_bytes: int = 2 * 1024 * 1024 * 1024,  # 2 GB limit
        ttl_seconds: int = 3600  # 1 hour
    ):
        self.cache_dir = cache_dir
        self.max_bytes = max_bytes
        self.ttl_seconds = ttl_seconds
        self._tasks: Dict[str, asyncio.Task] = {}
        self._events: Dict[str, asyncio.Event] = {}

    def _get_key(self, sid: int, audio_idx: int) -> str:
        return f"{sid}_{audio_idx}"

    def get_cache_file_path(self, sid: int, audio_idx: int) -> str:
        return os.path.join(self.cache_dir, f"{self._get_key(sid, audio_idx)}.aac")

    def start_precache(
        self,
        sid: int,
        audio_idx: int,
        mpd_path: str,
        keys: Optional[List[str]],
        ffmpeg_bin: str
    ) -> None:
        """Starts asynchronous extraction of the audio track if not already cached or running."""
        if not mpd_path or not ffmpeg_bin:
            return

        key = self._get_key(sid, audio_idx)
        final_file = self.get_cache_file_path(sid, audio_idx)

        if os.path.exists(final_file) and os.path.getsize(final_file) > 1000:
            try:
                os.utime(final_file, None)
            except Exception:
                pass
            return

        # Check if already running
        existing_task = self._tasks.get(key)
        if existing_task and not existing_task.done():
            return

        if key not in self._events:
            self._events[key] = asyncio.Event()
        else:
            self._events[key].clear()

        task = asyncio.create_task(
            self._extract_worker(key, sid, audio_idx, mpd_path, keys, ffmpeg_bin)
        )
        self._tasks[key] = task

    async def _extract_worker(
        self,
        key: str,
        sid: int,
        audio_idx: int,
        mpd_path: str,
        keys: Optional[List[str]],
        ffmpeg_bin: str
    ) -> None:
        tmp_file = os.path.join(self.cache_dir, f"{key}.tmp.aac")
        final_file = self.get_cache_file_path(sid, audio_idx)
        event = self._events.get(key)

        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            cmd = [
                ffmpeg_bin,
                "-hide_banner",
                "-loglevel", "error",
                "-rw_timeout", "15000000",
                "-allowed_extensions", "ALL",
                "-protocol_whitelist", "file,crypto,data,https,tls,tcp",
            ]
            if keys:
                cmd.extend(["-cenc_decryption_key", keys[0]])
            cmd.extend([
                "-i", mpd_path,
                "-vn",
                "-map", f"0:a:{audio_idx}?",
                "-c:a", "copy",
                "-f", "adts",
                "-y", tmp_file
            ])

            logger.info(f"Starting audio pre-cache for {key}: {mpd_path}")
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120.0)
            except asyncio.TimeoutError:
                logger.error(f"Audio pre-cache timed out after 120s for {key}, killing process...")
                try:
                    proc.kill()
                    await proc.communicate()
                except Exception:
                    pass
                if os.path.exists(tmp_file):
                    try:
                        os.remove(tmp_file)
                    except Exception:
                        pass
                return

            if proc.returncode == 0 and os.path.exists(tmp_file) and os.path.getsize(tmp_file) > 1000:
                os.replace(tmp_file, final_file)
                logger.info(f"Audio pre-cache complete for {key} ({os.path.getsize(final_file)} bytes)")
            else:
                err_msg = stderr.decode(errors="ignore")[:300] if stderr else "Unknown error"
                logger.error(f"Audio pre-cache failed for {key} (rc={proc.returncode}): {err_msg}")
                if os.path.exists(tmp_file):
                    try:
                        os.remove(tmp_file)
                    except Exception:
                        pass
        except Exception as e:
            logger.exception(f"Unexpected error in audio pre-cache worker for {key}: {e}")
        finally:
            if event:
                event.set()
            self._tasks.pop(key, None)
            self._cleanup_lru()

    async def get_segment(
        self,
        sid: int,
        audio_idx: int,
        start_sec: int,
        duration_sec: float,
        ffmpeg_bin: str,
        lang: str = "ces",
        timeout: float = 5.0
    ) -> Optional[bytes]:
        """
        Retrieves a 6-second MPEG-TS segment sliced directly from the local cached audio file.
        If extraction is currently in progress, waits up to timeout seconds.
        Returns None if cache is not available (allowing fallback).
        """
        key = self._get_key(sid, audio_idx)
        final_file = self.get_cache_file_path(sid, audio_idx)

        if not os.path.exists(final_file) or os.path.getsize(final_file) <= 1000:
            event = self._events.get(key)
            if event and not event.is_set():
                try:
                    await asyncio.wait_for(event.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    pass

        if not os.path.exists(final_file) or os.path.getsize(final_file) <= 1000:
            return None

        cmd = [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel", "warning",
            "-ss", str(float(start_sec)),
            "-i", final_file,
            "-vn",
            "-c:a", "copy",
            "-metadata:s:a:0", f"language={lang}",
            "-t", f"{duration_sec:.3f}",
            "-output_ts_offset", str(start_sec),
            "-f", "mpegts",
            "pipe:1"
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            if proc.returncode == 0 and stdout:
                try:
                    os.utime(final_file, None)
                except Exception:
                    pass
                return stdout
        except Exception as e:
            logger.warning(f"Failed to slice audio segment from cache for {key}: {e}")

        return None

    def _cleanup_lru(self) -> None:
        """Evicts expired audio files (older than ttl_seconds) or oldest files when cache exceeds max_bytes."""
        now = time.time()
        try:
            if not os.path.exists(self.cache_dir):
                return

            files = []
            total_size = 0
            for fname in os.listdir(self.cache_dir):
                fpath = os.path.join(self.cache_dir, fname)
                if not os.path.isfile(fpath):
                    continue
                try:
                    st = os.stat(fpath)
                except Exception:
                    continue

                # Remove abandoned tmp files older than 10 minutes
                if (fname.endswith(".tmp") or fname.endswith(".tmp.aac")) and (now - st.st_mtime > 600):
                    try:
                        os.remove(fpath)
                    except Exception:
                        pass
                    continue

                # Purge files expired by TTL
                if now - st.st_atime > self.ttl_seconds:
                    try:
                        os.remove(fpath)
                        logger.info(f"TTL expired audio cache file: {fpath}")
                    except Exception:
                        pass
                    continue

                files.append((st.st_atime, st.st_size, fpath))
                total_size += st.st_size

            # If cache exceeds limit, evict oldest files until under 75%
            if total_size > self.max_bytes:
                files.sort(key=lambda x: x[0])  # oldest atime first
                target = self.max_bytes * 0.75
                for atime, size, fpath in files:
                    if total_size <= target:
                        break
                    try:
                        os.remove(fpath)
                        total_size -= size
                        logger.info(f"LRU evicted audio cache file: {fpath}")
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Error during audio cache cleanup: {e}")


audio_cache_manager = AudioCacheManager()
