import asyncio
import os
import shutil
import tempfile
import time
import pytest
from app.audio_cache import AudioCacheManager


@pytest.fixture
def temp_cache_dir():
    d = tempfile.mkdtemp(prefix="test_audio_cache_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.mark.asyncio
async def test_audio_cache_lru_and_ttl(temp_cache_dir):
    # Set small max_bytes and short ttl
    mgr = AudioCacheManager(cache_dir=temp_cache_dir, max_bytes=1000, ttl_seconds=1)
    
    f1 = os.path.join(temp_cache_dir, "101_0.aac")
    f2 = os.path.join(temp_cache_dir, "102_0.aac")
    
    with open(f1, "wb") as f:
        f.write(b"A" * 600)
    with open(f2, "wb") as f:
        f.write(b"B" * 600)
    
    # Total is 1200 bytes > 1000 bytes max_bytes.
    # Set f1 as older atime
    t_old = time.time() - 100
    os.utime(f1, (t_old, t_old))
    
    mgr._cleanup_lru()
    
    # f1 should be evicted because it's older and cache exceeded limit
    assert not os.path.exists(f1)
    assert os.path.exists(f2)


@pytest.mark.asyncio
async def test_audio_cache_cleanup_tmp(temp_cache_dir):
    mgr = AudioCacheManager(cache_dir=temp_cache_dir, max_bytes=10000, ttl_seconds=3600)
    
    stale_tmp = os.path.join(temp_cache_dir, "stale.tmp")
    with open(stale_tmp, "wb") as f:
        f.write(b"temp data")
    
    # Set mtime to 15 minutes ago (> 600s)
    t_old = time.time() - 900
    os.utime(stale_tmp, (t_old, t_old))
    
    mgr._cleanup_lru()
    assert not os.path.exists(stale_tmp)


@pytest.mark.asyncio
async def test_audio_cache_deduplication(temp_cache_dir, monkeypatch):
    mgr = AudioCacheManager(cache_dir=temp_cache_dir)
    
    # Mock _extract_worker
    call_count = 0
    async def mock_worker(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.1)
    
    monkeypatch.setattr(mgr, "_extract_worker", mock_worker)
    
    mgr.start_precache(sid=1, audio_idx=0, mpd_path="http://dummy", keys=None, ffmpeg_bin="/bin/dummy")
    mgr.start_precache(sid=1, audio_idx=0, mpd_path="http://dummy", keys=None, ffmpeg_bin="/bin/dummy")
    
    assert len(mgr._tasks) == 1
    await asyncio.sleep(0.01)
    assert call_count == 1
    await list(mgr._tasks.values())[0]
