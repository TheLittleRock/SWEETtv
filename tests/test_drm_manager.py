import base64
import pytest
from unittest.mock import MagicMock, patch
from starlette.testclient import TestClient

from app.drm.oneplay_wv import OneplayDRMManager, WIDEVINE_SYSTEM_ID_BYTES
from app.main import app


def test_extract_pssh_from_mpd():
    mgr = OneplayDRMManager()

    # Construct valid mock PSSH box containing Widevine System ID
    raw_payload = b"\x00\x00\x00\x24pssh\x00\x00\x00\x00" + WIDEVINE_SYSTEM_ID_BYTES + b"\x00\x00\x00\x04test"
    valid_b64 = base64.b64encode(raw_payload).decode("ascii")

    mpd_sample = f"""<?xml version="1.0" encoding="UTF-8"?>
    <MPD xmlns="urn:mpeg:dash:schema:mpd:2011" xmlns:cenc="urn:mpeg:cenc:2013">
        <Period>
            <AdaptationSet mimeType="video/mp4">
                <ContentProtection schemeIdUri="urn:uuid:edef8ba9-79d6-4ace-88c8-20d2ac11e1f1">
                    <cenc:pssh>{valid_b64}</cenc:pssh>
                </ContentProtection>
            </AdaptationSet>
        </Period>
    </MPD>
    """

    pssh = mgr.extract_pssh_from_mpd(mpd_sample)
    assert pssh == valid_b64


def test_get_decryption_keys_flow():
    mgr = OneplayDRMManager()

    mock_gen_resp = MagicMock()
    mock_gen_resp.status_code = 200
    mock_gen_resp.json.return_value = {
        "id": "SESSION_123",
        "request": base64.b64encode(b"MOCK_CHALLENGE_BYTES").decode("ascii")
    }

    mock_lic_resp = MagicMock()
    mock_lic_resp.status_code = 200
    mock_lic_resp.content = b"MOCK_LICENSE_BYTES"

    mock_extract_resp = MagicMock()
    mock_extract_resp.status_code = 200
    mock_extract_resp.json.return_value = {
        "keys": [
            {"type": "CONTENT", "kid": "100b1234abcd", "key": "a4f89999000011112222333344445555"}
        ]
    }

    with patch("requests.post") as mock_post:
        # Step 1: /generate, Step 2: /AcquireLicense, Step 3: /extract
        mock_post.side_effect = [mock_gen_resp, mock_lic_resp, mock_extract_resp]

        keys = mgr.get_decryption_keys(
            pssh="DUMMY_PSSH_BASE64",
            drm_token="AX_TOKEN_TEST"
        )

        assert len(keys) == 1
        assert keys[0] == ("100b1234abcd", "a4f89999000011112222333344445555")

        # Second call must hit the memory cache without new requests
        cached_keys = mgr.get_decryption_keys(
            pssh="DUMMY_PSSH_BASE64",
            drm_token="AX_TOKEN_TEST"
        )
        assert cached_keys == keys
        assert mock_post.call_count == 3


def test_drm_pipeline_diagnostic():
    mgr = OneplayDRMManager()

    mock_wv = MagicMock()
    mock_wv.status_code = 200
    mock_wv.json.return_value = {"id": "test_id"}

    mock_lic = MagicMock()
    mock_lic.status_code = 400

    with patch("requests.post") as mock_post:
        mock_post.side_effect = [mock_wv, mock_lic]
        report = mgr.test_drm_pipeline()

        assert report["wv_service_ok"] is True
        assert report["license_service_ok"] is True
        assert report["overall_status"] == "ok"


def test_xtream_drm_movie_streaming():
    client = TestClient(app)

    # Mock VOD cache with a DRM DASH item
    from app.routes.xtream import _vod_cache_by_id
    from app.config import config
    config.set("xtream_user", "sweettv")
    config.set("xtream_password", "sweet")
    config.set("oneplay_enabled", True)
    config.set("oneplay_logged", True)

    test_sid = 30099
    _vod_cache_by_id[test_sid] = {
        "id": "vod-drm-test",
        "title": "Testovací DRM Film",
        "is_drm": True,
        "payload": {"contentId": "12345"}
    }

    mock_stream_info = {
        "manifest_type": "mpd",
        "url": "https://cdn.oneplay.cz/vod/manifest.mpd",
        "is_drm": True,
        "drm": {
            "type": "widevine",
            "license_url": "https://drm-proxy-widevine.cms.jyxo-tls.cz/AcquireLicense",
            "token": "TEST_TOKEN"
        }
    }

    async def mock_generator(*args, **kwargs):
        yield b"MPEGTS_MOCK_STREAM_BYTES"

    with patch("app.providers.manager.provider_manager.oneplay.get_vod_stream", return_value=mock_stream_info), \
         patch("app.routes.xtream.requests.get") as mock_get_mpd, \
         patch("app.drm.oneplay_wv.drm_manager.extract_pssh_from_mpd", return_value="MOCK_PSSH"), \
         patch("app.drm.oneplay_wv.drm_manager.get_decryption_keys", return_value=[("KID", "00112233445566778899aabbccddeeff")]), \
         patch("app.routes.xtream.ffmpeg_stream_generator", side_effect=mock_generator):

        mock_get_mpd.return_value = MagicMock(status_code=200, text="<MPD></MPD>")

        # Test 302 redirect for TS URL
        resp_redir = client.get(f"/movie/sweettv/sweet/{test_sid}.ts", follow_redirects=False)
        assert resp_redir.status_code == 302
        assert f"/movie/sweettv/sweet/{test_sid}.m3u8" in resp_redir.headers["location"]

        # Test raw direct streaming when requested
        resp = client.get(f"/movie/sweettv/sweet/{test_sid}.ts?raw=1")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "video/mp2t"
        assert resp.content == b"MPEGTS_MOCK_STREAM_BYTES"


def test_rewrite_mpd_tokens():
    from app.drm.streamer import rewrite_mpd_tokens

    sample_mpd = """<?xml version="1.0" encoding="utf-8"?>
    <MPD xmlns="urn:mpeg:dash:schema:mpd:2011" minBufferTime="PT1.5S">
      <Period id="0">
        <AdaptationSet id="0" contentType="video">
          <SegmentTemplate initialization="init-$RepresentationID$.mp4" media="chunk-$RepresentationID$-$Number%05d$.m4s" startNumber="1"/>
          <Representation id="v0" bandwidth="2000000" width="1920" height="1080"/>
        </AdaptationSet>
      </Period>
    </MPD>"""

    base_url = "https://cdn.oneplay.cz/vod/123/manifest.mpd?token=SECRET_AUTH_TOKEN_999"
    rewritten = rewrite_mpd_tokens(sample_mpd, base_url)

    assert "token=SECRET_AUTH_TOKEN_999" in rewritten
    assert "init-$RepresentationID$.mp4?token=SECRET_AUTH_TOKEN_999" in rewritten
    assert "chunk-$RepresentationID$-$Number%05d$.m4s?token=SECRET_AUTH_TOKEN_999" in rewritten
    assert "BaseURL" in rewritten


def test_get_season_episodes_pagination_and_order():
    from app.providers.manager import provider_manager

    # Mock carousel.display with 2 pages
    page1 = {
        "data": {
            "carousel": {
                "paging": {"next": True},
                "tiles": [
                    {"id": "ep2", "title": "2. díl", "duration": 3000, "action": {"params": {"payload": {"contentId": "ep2"}}}},
                    {"id": "ep1", "title": "1. díl", "duration": 3000, "action": {"params": {"payload": {"contentId": "ep1"}}}},
                ]
            }
        }
    }
    page2 = {
        "data": {
            "carousel": {
                "paging": {"next": False},
                "tiles": [
                    {"id": "ep0", "title": "Pilotní díl", "duration": 3000, "action": {"params": {"payload": {"contentId": "ep0"}}}},
                ]
            }
        }
    }

    with patch.object(provider_manager.oneplay, "ensure_authenticated", return_value=True), \
         patch.object(provider_manager.oneplay.api, "call_api", side_effect=[page1, page2]):

        eps = provider_manager.oneplay.get_season_episodes("carousel:100", "crit:1", sort_order="DESC")
        # 3 total episodes paginated across 2 pages
        assert len(eps) == 3
        # Chronological ascending order (reversed from DESC)
        assert eps[0]["title"] == "Pilotní díl"
        assert eps[1]["title"] == "1. díl"
        assert eps[2]["title"] == "2. díl"


def test_get_series_info_unique_episode_ids():
    client = TestClient(app)

    series_sid = 40017
    from app.routes.xtream import _series_cache_by_id, _series_info_cache
    _series_info_cache.clear()

    _series_cache_by_id[series_sid] = {
        "id": "series-ulice",
        "title": "Ulice",
        "payload": {"contentId": "ulice"}
    }

    mock_detail = {
        "title": "Ulice",
        "seasons": [
            {"label": "1. série", "carouselId": "c1", "criteria": "s1"},
            {"label": "2. série", "carouselId": "c2", "criteria": "s2"},
        ]
    }

    s1_eps = [
        {"id": "s1e1", "title": "1. díl", "duration": 3000},
        {"id": "s1e2", "title": "2. díl", "duration": 3000},
    ]
    s2_eps = [
        {"id": "s2e1", "title": "1. díl", "duration": 3000},
        {"id": "s2e2", "title": "2. díl", "duration": 3000},
    ]

    with patch("app.providers.manager.provider_manager.oneplay.get_series_detail", return_value=mock_detail), \
         patch("app.providers.manager.provider_manager.oneplay.get_season_episodes", side_effect=[s1_eps, s2_eps]):

        resp = client.get(f"/player_api.php?username=sweettv&password=sweet&action=get_series_info&series_id={series_sid}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["seasons"]) == 2

        # Season 1
        s1_list = data["episodes"]["1"]
        assert len(s1_list) == 2
        # Season 2
        s2_list = data["episodes"]["2"]
        assert len(s2_list) == 2

        # Verify episode IDs do NOT collide across seasons:
        # sid * 1000000 + season * 1000 + ep_num
        assert s1_list[0]["id"] == 40017001001
        assert s1_list[1]["id"] == 40017001002
        assert s2_list[0]["id"] == 40017002001
        assert s2_list[1]["id"] == 40017002002
        assert s1_list[0]["id"] != s2_list[0]["id"]


def test_xtream_movie_head_request():
    client = TestClient(app)
    resp = client.head("/movie/sweettv/sweet/30001.ts")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "video/mp2t"


