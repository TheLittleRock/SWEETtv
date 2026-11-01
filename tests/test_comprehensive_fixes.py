import pytest
from unittest.mock import MagicMock, patch
from starlette.testclient import TestClient
from app.main import app
from app.catalog_db import get_or_create_stream_id, init_catalog_db
from app.config import config
from app.routes.xtream import _vod_cache_by_id, _series_cache_by_id


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    config.set("xtream_user", "admin")
    config.set("xtream_password", "Stepan-2002")
    config.set("oneplay_enabled", True)
    config.set("oneplay_logged", True)
    init_catalog_db()


def test_catalog_db_persistent_ids():
    """Verify stream IDs are persistent, deterministic, and Ulice is mapped to 40011."""
    # Ulice alias test
    ulice_id = get_or_create_stream_id("oneplay", "show.40482", "series", "Ulice")
    assert ulice_id == 40011

    # Movie ID range
    m1 = get_or_create_stream_id("oneplay", "movie.1001", "movie", "Film 1")
    assert 30001 <= m1 <= 39999
    # Idempotent call returns same ID
    m1_again = get_or_create_stream_id("oneplay", "movie.1001", "movie", "Film 1")
    assert m1_again == m1

    # Second movie gets distinct ID
    m2 = get_or_create_stream_id("oneplay", "movie.1002", "movie", "Film 2")
    assert 30001 <= m2 <= 39999
    assert m2 != m1

    # Series ID range
    s1 = get_or_create_stream_id("oneplay", "show.5001", "series", "Seriál 1")
    assert 40001 <= s1 <= 49999
    assert s1 != 40011


def test_hls_audio_rendition_playlist(monkeypatch):
    """Verify master playlist includes audio rendition URI and /vod_audio/ generates valid playlist."""
    test_sid = 30123
    _vod_cache_by_id[test_sid] = {
        "id": "movie.spider",
        "title": "Spider-Man: Bez domova",
        "duration": 120,
        "payload": {"contentId": "movie.spider"}
    }

    sample_mpd = """<?xml version="1.0" encoding="utf-8"?>
    <MPD xmlns="urn:mpeg:dash:schema:mpd:2011" mediaPresentationDuration="PT120.000S">
      <Period>
        <AdaptationSet contentType="video" mimeType="video/mp4">
          <Representation id="v1" bandwidth="6000000" width="1920" height="1080" />
        </AdaptationSet>
        <AdaptationSet contentType="audio" lang="ces" mimeType="audio/mp4">
          <Representation id="a1" bandwidth="128000" />
        </AdaptationSet>
        <AdaptationSet contentType="audio" lang="eng" mimeType="audio/mp4">
          <Representation id="a2" bandwidth="128000" />
        </AdaptationSet>
      </Period>
    </MPD>"""

    class MockResp:
        status_code = 200
        text = sample_mpd

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: MockResp())
    from app.providers.manager import provider_manager
    monkeypatch.setattr(
        provider_manager.oneplay,
        "get_vod_stream",
        lambda payload: {"manifest_type": "mpd", "url": "https://cdn.mock/spider.mpd", "is_drm": False}
    )

    client = TestClient(app)

    # 1. Verify Master Playlist declares URI on both audio renditions
    resp = client.get(f"/movie/admin/Stepan-2002/{test_sid}.m3u8")
    assert resp.status_code == 200
    m3u8_text = resp.text
    assert f'URI="http://testserver/vod_audio/admin/Stepan-2002/{test_sid}/0.m3u8"' in m3u8_text
    assert f'URI="http://testserver/vod_audio/admin/Stepan-2002/{test_sid}/1.m3u8"' in m3u8_text
    assert 'NAME="Čeština",LANGUAGE="cs"' in m3u8_text
    assert 'NAME="English",LANGUAGE="en"' in m3u8_text

    # 2. Verify Audio Rendition Playlist for audio track 1 (English)
    resp_audio = client.get(f"/vod_audio/admin/Stepan-2002/{test_sid}/1.m3u8")
    assert resp_audio.status_code == 200
    assert resp_audio.headers["content-type"] == "application/vnd.apple.mpegurl"
    a_text = resp_audio.text
    assert "#EXTM3U" in a_text
    assert "#EXT-X-TARGETDURATION:7" in a_text
    assert "#EXT-X-PLAYLIST-TYPE:VOD" in a_text
    assert f"/vod_audio_segment/admin/Stepan-2002/{test_sid}/1/0.ts" in a_text
    assert f"/vod_audio_segment/admin/Stepan-2002/{test_sid}/1/6.ts" in a_text
    assert "#EXT-X-ENDLIST" in a_text


def test_external_players_302_redirects():
    """Verify .ts and .mp4 URLs issue 302 redirect to .m3u8 for full HLS scrubbing and compatibility."""
    client = TestClient(app)

    # 1. Live TV .ts redirect
    resp_live = client.get("/live/admin/Stepan-2002/11002.ts", follow_redirects=False)
    assert resp_live.status_code == 302
    assert "/live/admin/Stepan-2002/11002.m3u8" in resp_live.headers["location"]

    # 2. Timeshift .ts redirect
    resp_time = client.get("/timeshift/admin/Stepan-2002/60/2026-11-01:12-00/11002.ts", follow_redirects=False)
    assert resp_time.status_code == 302
    assert "/timeshift/admin/Stepan-2002/60/2026-11-01:12-00/11002.m3u8" in resp_time.headers["location"]

    # 3. Movie .mp4 redirect
    resp_movie = client.get("/movie/admin/Stepan-2002/30123.mp4", follow_redirects=False)
    assert resp_movie.status_code == 302
    assert "/movie/admin/Stepan-2002/30123.m3u8" in resp_movie.headers["location"]

    # 4. Series .ts redirect
    resp_series = client.get("/series/admin/Stepan-2002/40011002101.ts", follow_redirects=False)
    assert resp_series.status_code == 302
    assert "/series/admin/Stepan-2002/40011002101.m3u8" in resp_series.headers["location"]

    # 5. Verify HEAD requests also issue 302 redirects without 405 Method Not Allowed
    resp_live_head = client.head("/live/admin/Stepan-2002/11002.ts", follow_redirects=False)
    assert resp_live_head.status_code == 302
    assert "/live/admin/Stepan-2002/11002.m3u8" in resp_live_head.headers["location"]

    resp_time_head = client.head("/timeshift/admin/Stepan-2002/60/2026-11-01:12-00/11002.ts", follow_redirects=False)
    assert resp_time_head.status_code == 302
    assert "/timeshift/admin/Stepan-2002/60/2026-11-01:12-00/11002.m3u8" in resp_time_head.headers["location"]


def test_epg_utc_timestamps_formatting(monkeypatch):
    """Verify EPG start/end strings are output in canonical UTC to prevent 1-hour shifts in clients."""
    from app.providers.manager import provider_manager

    # 1793465700 is 2026-10-31 16:55:00 UTC (17:55:00 Prague)
    mock_epg = [
        {
            "id": "prog1",
            "title": "Zpátky do přírody 2",
            "time_start": 1793465700,
            "time_stop": 1793467500,
            "can_replay": True
        }
    ]
    monkeypatch.setattr(provider_manager.oneplay, "get_channel_epg", lambda cid: mock_epg)

    mock_ch = [{"id": "002", "channel_number": 1002, "name": "ČT1 HD", "provider": "oneplay"}]
    monkeypatch.setattr(provider_manager.oneplay, "get_channels", lambda: mock_ch)

    client = TestClient(app)
    resp = client.get("/player_api.php?username=admin&password=Stepan-2002&action=get_short_epg&stream_id=11002")
    assert resp.status_code == 200
    data = resp.json()
    listings = data.get("epg_listings") or []
    assert len(listings) == 1
    prog = listings[0]
    # start string must be UTC: 2026-10-31 16:55:00
    assert prog["start"] == "2026-10-31 16:55:00"
    assert prog["end"] == "2026-10-31 17:25:00"
    assert prog["start_timestamp"] == 1793465700
