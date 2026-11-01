import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from app.providers.oneplay import OneplayProvider
from app.stream import safe_parse_timestamp


def test_safe_parse_timestamp_prague_tz():
    # 2026-10-31 10:30 in Europe/Prague is 09:30 UTC = epoch 1793439000
    ts = safe_parse_timestamp("2026-10-31:10-30")
    assert ts == 1793439000

    ts2 = safe_parse_timestamp("2026-10-31 10:30:00")
    assert ts2 == 1793439000


def test_rewrite_manifest_token_merge_and_start_offset():
    provider = OneplayProvider()
    base_url = "https://tvdev.thelittlerock.cz"

    # Mock manifest with relative chunk and child playlist
    sample_m3u8 = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-STREAM-INF:BANDWIDTH=5000000
variant.m3u8
#EXTINF:6.0,
segment_001.ts
#EXT-X-ENDLIST
"""

    mock_resp = MagicMock()
    mock_resp.geturl.return_value = "https://cdn.oneplay.cz/live/master.m3u8?token=AUTH123&expires=9999"
    mock_resp.read.return_value = sample_m3u8.encode("utf-8")
    mock_resp.headers = {"Content-Encoding": "identity"}
    mock_resp.__enter__.return_value = mock_resp

    with patch("app.providers.oneplay.urlopen", return_value=mock_resp):
        # Test standard rewrite
        rewritten = provider.rewrite_manifest(
            "https://cdn.oneplay.cz/live/master.m3u8?token=AUTH123&expires=9999",
            base_url,
            start_at_begin=False
        )

        lines = rewritten.splitlines()
        # Segment 1 must have token from parent URL!
        ts_line = next(l for l in lines if "segment_001.ts" in l)
        assert "token=AUTH123" in ts_line
        assert "expires=9999" in ts_line
        assert ts_line.startswith("https://cdn.oneplay.cz/live/segment_001.ts")

        # Variant line must be routed to proxy
        var_line = next(l for l in lines if "proxy_hls" in l)
        assert "variant.m3u8" in var_line

        # Test with start_at_begin=True (catchup)
        rewritten_catchup = provider.rewrite_manifest(
            "https://cdn.oneplay.cz/live/master.m3u8?token=AUTH123&expires=9999",
            base_url,
            start_at_begin=True
        )
        assert "#EXT-X-START:TIME-OFFSET=0,PRECISE=YES" in rewritten_catchup


def test_get_season_episodes_carousel_structure():
    provider = OneplayProvider()
    provider.ensure_authenticated = MagicMock(return_value=True)

    # Mock carousel.display returning {"carousel": {"tiles": [...]}}
    mock_tiles = [
        {
            "id": "ep1",
            "title": "Epizoda 1",
            "description": "První díl",
            "duration": 3600,
            "action": {
                "params": {
                    "payload": {"contentId": "101"}
                }
            }
        }
    ]
    provider.api.call_api = MagicMock(return_value={
        "status": "success",
        "data": {
            "carousel": {
                "tiles": mock_tiles
            }
        }
    })

    # Test with string criteria
    eps = provider.get_season_episodes("page:10;carousel:20", "season_1")
    assert len(eps) == 1
    assert eps[0]["id"] == "101"
    assert eps[0]["title"] == "Epizoda 1"

    # Test with dict criteria wrapper: {"criteria": "season_1"}
    eps2 = provider.get_season_episodes("page:10;carousel:20", {"criteria": "season_1"})
    assert len(eps2) == 1
    assert eps2[0]["id"] == "101"


def test_get_series_detail_ignores_similar_titles():
    provider = OneplayProvider()
    provider.ensure_authenticated = MagicMock(return_value=True)

    # Mock movie response that has "Podobné tituly" carousel
    mock_movie_data = {
        "metadata": {"title": "Rychle a zběsile 10", "type": "movie"},
        "layout": {
            "blocks": [
                {
                    "schema": "CarouselBlock",
                    "carousels": [
                        {
                            "title": "Podobné tituly",
                            "tiles": [
                                {
                                    "id": "movie2",
                                    "title": "Kurýr: Restart",
                                    "action": {"params": {"payload": {"contentId": "999"}}}
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    }
    provider.api.call_api = MagicMock(return_value={"status": "success", "data": mock_movie_data})

    detail = provider.get_series_detail({"contentId": "fast10"})
    assert detail["title"] == "Rychle a zběsile 10"
    # Episodes MUST be empty because "Podobné tituly" is not an episode carousel!
    assert len(detail["episodes"]) == 0
    assert len(detail["seasons"]) == 0


def test_get_season_episodes_nested_criteria_id():
    provider = OneplayProvider()
    provider.ensure_authenticated = MagicMock(return_value=True)

    # Tile with nested criteria.contentId (like Robin Hood)
    mock_tiles = [
        {
            "id": None,
            "title": "1. díl - Vidím ho",
            "description": "Popis",
            "duration": 3600,
            "action": {
                "params": {
                    "payload": {"criteria": {"schema": "ContentCriteria", "contentId": "episode.3308377"}}
                }
            }
        }
    ]
    provider.api.call_api = MagicMock(return_value={
        "status": "success",
        "data": {"carousel": {"tiles": mock_tiles}}
    })

    eps = provider.get_season_episodes("show:258795", "season:100478")
    assert len(eps) == 1
    assert eps[0]["id"] == "episode.3308377"
    assert eps[0]["id"] != "None"


def test_vod_categories_correct_mapping():
    provider = OneplayProvider()
    provider.ensure_authenticated = MagicMock(return_value=True)

    # Mock app.init menu
    mock_init = {
        "menu": {
            "groups": [
                {
                    "position": "top",
                    "items": [
                        {"id": "1", "title": "Domů", "action": {"call": "page.category.display", "params": {"payload": {"categoryId": "1"}}}},
                        {"id": "4", "title": "Pořady", "action": {"call": "page.category.display", "params": {"payload": {"categoryId": "4"}}}},
                        {"id": "2", "title": "Filmy", "action": {"call": "page.category.display", "params": {"payload": {"categoryId": "2"}}}},
                        {"id": "8", "title": "Můj seznam", "action": {"call": "page.category.display", "params": {"payload": {"categoryId": "8"}}}},
                    ]
                }
            ]
        }
    }
    provider.api.call_api = MagicMock(return_value={"status": "success", "data": mock_init})

    cats = provider.get_vod_categories()
    cat_by_id = {c["id"]: c for c in cats}

    assert cat_by_id["movies"]["categoryId"] == "2"
    assert cat_by_id["series"]["categoryId"] == "4"
    assert cat_by_id["recordings"]["categoryId"] == "8"
    assert cat_by_id["all"]["categoryId"] == "1"


def test_fetch_category_filtered_items_pagination():
    provider = OneplayProvider()
    provider.ensure_authenticated = MagicMock(return_value=True)

    # Mock page 1 and page 2 responses for Category 25
    def mock_call_api(endpoint, data=None, token=None, retry=False):
        criteria = (data or {}).get("payload", {}).get("criteria", {}).get("filterCriterias", "")
        import base64, json
        # Decode base64 filter
        b64 = criteria.replace("filter:", "")
        filter_obj = json.loads(base64.b64decode(b64).decode())
        page = filter_obj.get("page", "1")
        if page == "1":
            return {
                "status": "success",
                "data": {
                    "layout": {
                        "blocks": [
                            {
                                "carousels": [
                                    {
                                        "tiles": [
                                            {"id": "m1", "title": "Spider-Man: Homecoming", "action": {"params": {"payload": {"contentId": "movie.10999"}}}}
                                        ],
                                        "paging": {"pageCount": 2, "next": True}
                                    }
                                ]
                            }
                        ]
                    }
                }
            }
        else:
            return {
                "status": "success",
                "data": {
                    "layout": {
                        "blocks": [
                            {
                                "carousels": [
                                    {
                                        "tiles": [
                                            {"id": "m2", "title": "Spider-Man: Bez domova", "action": {"params": {"payload": {"contentId": "movie.11037"}}}}
                                        ],
                                        "paging": {"pageCount": 2, "next": False}
                                    }
                                ]
                            }
                        ]
                    }
                }
            }

    provider.api.call_api = mock_call_api
    items = provider._fetch_category_filtered_items("oneplay-2", "fake_token")
    assert len(items) == 2
    titles = [it["title"] for it in items]
    assert "Spider-Man: Homecoming" in titles
    assert "Spider-Man: Bez domova" in titles


@pytest.mark.asyncio
async def test_xtream_vod_subs_vtt_utf8_and_timestamp_map(monkeypatch):
    """Verifies that xtream_vod_subs_vtt preserves UTF-8 Czech characters and normalizes X-TIMESTAMP-MAP."""
    from app.routes import xtream
    from unittest.mock import MagicMock

    raw_vtt = (
        "WEBVTT\n"
        "X-TIMESTAMP-MAP=MPEGTS:900000,LOCAL:00:00:00.000\n\n"
        "1\n"
        "00:00:39.520 --> 00:00:43.840\n"
        "-Můžu vám pomoct?\n"
        "Příliš žluťoučký kůň úpěl ďábelské ódy.\n"
    ).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = raw_vtt

    async def mock_vod_session(sid):
        return {"subtitle_tracks": [{"vtt_url": "https://cdn.cra.cz/test.vtt"}]}

    monkeypatch.setattr(xtream, "validate_xtream_user", lambda u, p: True)
    monkeypatch.setattr(xtream, "_get_or_create_vod_session", mock_vod_session)
    monkeypatch.setattr(xtream.requests, "get", lambda *args, **kwargs: mock_resp)

    mock_request = MagicMock()
    resp = await xtream.xtream_vod_subs_vtt(mock_request, "admin", "admin", "12345", 0)
    body = resp.body.decode("utf-8")

    assert "X-TIMESTAMP-MAP=MPEGTS:0,LOCAL:00:00:00.000" in body
    assert "MPEGTS:900000" not in body
    assert "Můžu vám pomoct?" in body
    assert "Příliš žluťoučký kůň úpěl ďábelské ódy." in body


@pytest.mark.asyncio
async def test_xtream_vod_segment_zero_omits_ss(monkeypatch):
    """Verifies that xtream_vod_segment omits -ss when start_sec == 0 to prevent 3s video drop."""
    from app.routes import xtream
    from unittest.mock import MagicMock

    captured_cmds = []

    async def mock_subprocess_exec(*args, **kwargs):
        captured_cmds.append(list(args))
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"TS_DATA", b""))
        return proc

    async def mock_vod_session(sid):
        return {"mpd_path": "/tmp/test.mpd", "keys": ["00112233445566778899aabbccddeeff"], "duration": 1800.0}

    monkeypatch.setattr(xtream, "validate_xtream_user", lambda u, p: True)
    monkeypatch.setattr(xtream, "_get_or_create_vod_session", mock_vod_session)
    monkeypatch.setattr(xtream, "find_ffmpeg_binary", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(xtream.asyncio, "create_subprocess_exec", mock_subprocess_exec)

    mock_req = MagicMock()
    mock_req.method = "GET"
    mock_req.query_params = {}

    # Segment 0: start_sec = 0
    await xtream.xtream_vod_segment(mock_req, "admin", "admin", "12345", 0)
    cmd0 = captured_cmds[0]
    assert "-ss" not in cmd0, f"Expected no -ss for start_sec=0, got {cmd0}"

    # Segment 1: start_sec = 6
    await xtream.xtream_vod_segment(mock_req, "admin", "admin", "12345", 6)
    cmd1 = captured_cmds[1]
    assert "-ss" in cmd1
    ss_idx = cmd1.index("-ss")
    assert cmd1[ss_idx + 1] == "7.5"

