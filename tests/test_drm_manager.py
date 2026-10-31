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

        resp = client.get(f"/movie/sweettv/sweet/{test_sid}.ts")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "video/mp2t"
        assert resp.content == b"MPEGTS_MOCK_STREAM_BYTES"
