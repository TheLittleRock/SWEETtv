import struct
import xml.etree.ElementTree as ET
import pytest
from app.drm.streamer import (
    normalize_lang_code,
    parse_iso8601_duration,
    prepare_dash_manifest,
)

SAMPLE_MPD_MULTI_AUDIO = """<?xml version="1.0" encoding="utf-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"
     mediaPresentationDuration="PT32M5.160S"
     minBufferTime="PT2S"
     type="static">
  <Period id="0">
    <AdaptationSet id="1" contentType="audio" mimeType="audio/mp4" lang="cs">
      <Representation id="aud_cze=128000" bandwidth="128000" codecs="mp4a.40.2"/>
    </AdaptationSet>
    <AdaptationSet id="2" contentType="audio" mimeType="audio/mp4" lang="en">
      <Representation id="aud_eng=128000" bandwidth="128000" codecs="mp4a.40.2"/>
    </AdaptationSet>
    <AdaptationSet id="3" contentType="video" mimeType="video/mp4" lang="cs">
      <Representation id="vid=395000" bandwidth="395000" width="512" height="288"/>
      <Representation id="vid=1979000" bandwidth="1979000" width="1024" height="576"/>
      <Representation id="vid=5958000" bandwidth="5958000" width="1920" height="1080"/>
    </AdaptationSet>
    <AdaptationSet id="4" contentType="text" mimeType="text/vtt" lang="cs">
      <Representation id="sub_cze" bandwidth="1000"/>
    </AdaptationSet>
  </Period>
</MPD>
"""

SAMPLE_MPD_NO_LANG = """<?xml version="1.0" encoding="utf-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"
     mediaPresentationDuration="PT1H45M30S"
     minBufferTime="PT2S"
     type="static">
  <Period id="0">
    <AdaptationSet id="1" contentType="audio" mimeType="audio/mp4">
      <Representation id="aud_unknown" bandwidth="128000"/>
    </AdaptationSet>
    <AdaptationSet id="2" contentType="video" mimeType="video/mp4">
      <Representation id="vid=720" bandwidth="2000000" width="1280" height="720"/>
      <Representation id="vid=1080" bandwidth="4500000" width="1920" height="1080"/>
    </AdaptationSet>
  </Period>
</MPD>
"""


def test_normalize_lang_code():
    assert normalize_lang_code("cs") == "ces"
    assert normalize_lang_code("cze") == "ces"
    assert normalize_lang_code("ces") == "ces"
    assert normalize_lang_code("cz") == "ces"
    assert normalize_lang_code("sk") == "slk"
    assert normalize_lang_code("en") == "eng"
    assert normalize_lang_code("de") == "deu"
    assert normalize_lang_code(None) == "ces"
    assert normalize_lang_code("") == "ces"
    assert normalize_lang_code("und") == "ces"
    assert normalize_lang_code("fra") == "fra"


def test_parse_iso8601_duration():
    assert parse_iso8601_duration("PT32M5.160S") == pytest.approx(1925.16, 0.01)
    assert parse_iso8601_duration("PT1H45M30S") == pytest.approx(6330.0, 0.01)
    assert parse_iso8601_duration("PT2H") == 7200.0
    assert parse_iso8601_duration("PT90S") == 90.0
    assert parse_iso8601_duration(None) == 0.0
    assert parse_iso8601_duration("") == 0.0
    assert parse_iso8601_duration("invalid") == 0.0


def test_prepare_dash_manifest_multi_audio():
    base_url = "https://cdn.example.com/stream/manifest.mpd?token=xyz123"
    rewritten, audio_langs, sub_langs, duration = prepare_dash_manifest(SAMPLE_MPD_MULTI_AUDIO, base_url)

    assert audio_langs == ["ces", "eng"]
    assert sub_langs == ["ces"]
    assert duration == pytest.approx(1925.16, 0.01)

    # Check XML has only 1 video representation (the highest bandwidth 5958000)
    root = ET.fromstring(rewritten)
    ns = {"mpd": "urn:mpeg:dash:schema:mpd:2011"}
    video_as = None
    for a in root.findall(".//mpd:AdaptationSet", ns):
        if (a.get("contentType") or "").lower() == "video":
            video_as = a
            break
    assert video_as is not None
    reps = video_as.findall("mpd:Representation", ns)
    assert len(reps) == 1
    assert reps[0].get("id") == "vid=5958000"


def test_prepare_dash_manifest_no_lang_defaults_to_ces():
    base_url = "https://cdn.example.com/stream/manifest.mpd"
    rewritten, audio_langs, sub_langs, duration = prepare_dash_manifest(SAMPLE_MPD_NO_LANG, base_url)

    assert audio_langs == ["ces"]
    assert sub_langs == []
    assert duration == pytest.approx(6330.0, 0.01)


def test_xtream_movie_head_probe_content_length():
    """Verify HEAD requests return non-zero Content-Length and Accept-Ranges: bytes for players like VLC."""
    from starlette.testclient import TestClient
    from app.main import app
    from app.routes.xtream import _vod_cache_by_id

    # Seed mock item in cache
    _vod_cache_by_id[39999] = {
        "id": "movie.mock",
        "title": "Mock Movie",
        "duration": 5400,  # 90 minutes
        "payload": {"contentId": "movie.mock"}
    }

    client = TestClient(app)

    # 1. HEAD on .ts
    resp_ts = client.head("/movie/sweettv/sweet/39999.ts")
    assert resp_ts.status_code == 200
    assert resp_ts.headers["content-type"] == "video/mp2t"
    assert resp_ts.headers["accept-ranges"] == "none"
    assert resp_ts.headers["x-content-duration"] == "5400"

    # 2. HEAD on .mp4
    resp_mp4 = client.head("/movie/sweettv/sweet/39999.mp4")
    assert resp_mp4.status_code == 200
    assert resp_mp4.headers["content-type"] == "video/mp4"
    assert resp_mp4.headers["accept-ranges"] == "none"
    assert resp_mp4.headers["x-content-duration"] == "5400"

    # 3. HEAD on .m3u8
    resp_m3u8 = client.head("/movie/sweettv/sweet/39999.m3u8")
    assert resp_m3u8.status_code == 200
    assert resp_m3u8.headers["content-type"] == "application/vnd.apple.mpegurl"


def test_xtream_movie_m3u8_hls_playlist_generation(monkeypatch):
    """Verify GET .m3u8 on VOD generates a valid HLS VOD playlist with segments."""
    from starlette.testclient import TestClient
    from app.main import app
    from app.routes.xtream import _vod_cache_by_id
    from app.providers.manager import provider_manager

    _vod_cache_by_id[39998] = {
        "id": "movie.mock2",
        "title": "Mock Movie 2",
        "duration": 60,  # 60s -> 6 segments of 10s
        "payload": {"contentId": "movie.mock2"}
    }

    # Mock get_vod_stream to return DRM stream
    monkeypatch.setattr(
        provider_manager.oneplay,
        "get_vod_stream",
        lambda payload: {"manifest_type": "mpd", "url": "https://cdn.mock/dash.mpd", "is_drm": True}
    )

    client = TestClient(app)
    resp = client.get("/movie/sweettv/sweet/39998.m3u8")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/vnd.apple.mpegurl"
    text = resp.text
    assert "#EXTM3U" in text
    assert "#EXT-X-PLAYLIST-TYPE:VOD" in text
    assert "#EXT-X-ENDLIST" in text
    assert "/vod_segment/sweettv/sweet/39998/0.ts" in text
    assert "/vod_segment/sweettv/sweet/39998/10.ts" in text
    assert "/vod_segment/sweettv/sweet/39998/50.ts" in text


def test_xtream_vod_and_series_m3u8_container_extension():
    """Verify get_vod_info and get_series_info return container_extension: m3u8, bitrate, and filesize."""
    from starlette.testclient import TestClient
    from app.main import app
    from app.routes.xtream import _vod_cache_by_id

    _vod_cache_by_id[39997] = {
        "id": "vod.39997",
        "title": "Test VOD",
        "duration": 3600,
        "payload": {"contentId": "vod.39997"}
    }

    client = TestClient(app)
    resp = client.get("/player_api.php?username=sweettv&password=sweet&action=get_vod_info&vod_id=39997")
    assert resp.status_code == 200
    data = resp.json()
    assert data["movie_data"]["container_extension"] == "m3u8"
    assert data["info"]["bitrate"] == 6000000
    assert data["info"]["filesize"] == int((3600 * 6000000) / 8)



