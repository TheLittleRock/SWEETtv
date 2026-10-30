import os
import sqlite3
from starlette.testclient import TestClient

from app.auth import (
    init_auth_db,
    get_user_by_stalker_mac,
    get_user_by_username,
    update_user,
    normalize_mac,
    create_session,
    SESSION_COOKIE_NAME,
    DB_PATH
)
from app.main import app

def test_stalker_mac_auth():
    print("Initializing auth DB...")
    init_auth_db()

    # 1. Check admin MAC binding
    admin = get_user_by_username("admin")
    assert admin is not None, "Admin user must exist"
    assert admin.stalker_mac == "00:1a:79:0d:d6:c1", f"Admin MAC should be pre-bound, got {admin.stalker_mac}"
    print(f"✓ Admin pre-bound with MAC: {admin.stalker_mac}")

    # 2. Test MAC normalization and lookups
    assert get_user_by_stalker_mac("00:1A:79:0D:D6:C1") is not None
    assert get_user_by_stalker_mac("00-1a-79-0d-d6-c1") is not None
    assert get_user_by_stalker_mac("00%3A1A%3A79%3A0D%3AD6%3AC1") is not None
    assert get_user_by_stalker_mac("001a790dd6c1") is not None
    assert get_user_by_stalker_mac("00:1a:79:99:99:99") is None
    print("✓ All MAC formats resolved correctly.")

    client = TestClient(app)

    # 3. Test IPTVnator handshake with MAC cookie (NO TOKEN in URL)
    resp = client.get(
        "/stalker_portal/server/load.php?type=stb&action=handshake",
        cookies={"mac": "00:1A:79:0D:D6:C1"}
    )
    print(f"Handshake response status: {resp.status_code}, body: {resp.text}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "js" in data
    assert "token" in data["js"]
    stb_token = data["js"]["token"]
    assert stb_token
    print(f"✓ IPTVnator handshake succeeded with stb_token: {stb_token}")

    # 4. Test handshake without credentials or with unknown MAC:
    # Under Ministra spec, handshake returns token + random (200), but subsequent get_profile or channel requests are rejected with 401.
    anon_handshake = client.get(
        "/stalker_portal/server/load.php?type=stb&action=handshake",
        cookies={"mac": "AA:BB:CC:DD:EE:FF"}
    )
    assert anon_handshake.status_code == 200, f"Handshake should return 200 with token, got {anon_handshake.status_code}"
    anon_token = anon_handshake.json()["js"]["token"]
    assert anon_token

    # Now verify unauthenticated access to get_profile is properly rejected with 401
    unauth_resp = client.get(
        f"/stalker_portal/server/load.php?type=stb&action=get_profile&token={anon_token}",
        cookies={"mac": "AA:BB:CC:DD:EE:FF"}
    )
    assert unauth_resp.status_code == 401
    assert "not registered" in unauth_resp.text
    print(f"✓ Unregistered MAC properly rejected with 401 on get_profile: {unauth_resp.json()}")

    # 5. Test get_profile using stb_token and MAC
    profile_resp = client.get(
        f"/stalker_portal/server/load.php?type=stb&action=get_profile&token={stb_token}",
        cookies={"mac": "00:1A:79:0D:D6:C1"}
    )
    assert profile_resp.status_code == 200
    profile_data = profile_resp.json()
    assert profile_data["js"]["name"] == "admin"
    assert profile_data["js"]["services"]["tv_archive"] == 1
    assert profile_data["js"]["tv_archive"] == 1
    assert profile_data["js"]["timeshift"] == 1
    print(f"✓ get_profile succeeded for user: {profile_data['js']['name']} with tv_archive service enabled")

    # Test get_modules
    modules_resp = client.get(
        f"/stalker_portal/server/load.php?type=stb&action=get_modules&token={stb_token}",
        cookies={"mac": "00:1A:79:0D:D6:C1"}
    )
    assert modules_resp.status_code == 200
    modules_data = modules_resp.json()
    assert "all_modules" in modules_data["js"]
    assert "tv_archive" in modules_data["js"]["all_modules"]
    print(f"✓ get_modules verified: all_modules={modules_data['js']['all_modules']}")

    # 6. Test get_all_channels and create_link with mock channel cache
    import time
    from app.epg import _CHANNELS_CACHE, _CHANNELS_CACHE_TIME
    import app.epg as epg_module
    epg_module._CHANNELS_CACHE = {
        "status": "OK",
        "categories": [{"id": 1, "caption": "Všeobecné"}],
        "list": [{
            "id": 851,
            "name": "ČT1 HD",
            "available": True,
            "catchup": True,
            "catchup_duration": 7,
            "category": [1],
            "epg": [
                {
                    "id": 9991,
                    "text": "Události",
                    "description": "Hlavní zpravodajská relace ČT",
                    "time_start": int(time.time()) - 3600,
                    "time_stop": int(time.time()) - 600
                },
                {
                    "id": 9992,
                    "text": "Film večera",
                    "description": "Česká komedie",
                    "time_start": int(time.time()) - 600,
                    "time_stop": int(time.time()) + 3600
                }
            ]
        }]
    }
    epg_module._CHANNELS_CACHE_TIME = time.time()

    channels_resp = client.get(
        f"/stalker_portal/server/load.php?type=itv&action=get_all_channels&token={stb_token}",
        cookies={"mac": "00:1A:79:0D:D6:C1"}
    )
    assert channels_resp.status_code == 200
    ch_data = channels_resp.json()
    assert "js" in ch_data
    assert "data" in ch_data["js"]
    raw_channels = ch_data["js"]["data"]
    assert len(raw_channels) == 1
    first_ch = raw_channels[0]
    assert first_ch["id"] == "851"
    assert first_ch["tvg-id"] == "851", "Must contain tvg-id for IPTVnator"
    assert first_ch["tvg_id"] == "851"
    assert first_ch["tvg"]["id"] == "851", "Must contain tvg object with id"
    assert first_ch["tvg_name"] == "ČT1 HD"
    assert first_ch["tv_archive"] == 1
    assert first_ch["archive"] == 1
    assert first_ch["catchup"] == 1
    assert "catchup_source" in first_ch
    assert first_ch["tv_archive_duration"] == 168, f"Expected 168 hours, got {first_ch['tv_archive_duration']}"
    print(f"✓ Channel EPG mapping verified: tvg-id={first_ch['tvg-id']}, tvg.id={first_ch['tvg']['id']}, tv_archive_duration={first_ch['tv_archive_duration']}h")

    # Test create_link for live TV
    create_link_resp = client.get(
        f"/stalker_portal/server/load.php?type=itv&action=create_link&cmd=ffmpeg%20http%3A%2F%2Ftestserver%2Fstream%2F851.m3u8&token={stb_token}",
        cookies={"mac": "00:1A:79:0D:D6:C1"}
    )
    assert create_link_resp.status_code == 200
    link_data = create_link_resp.json()
    assert "js" in link_data
    assert link_data["js"]["id"] == 851
    assert f"/t/{admin.token}/stream/851.m3u8" in link_data["js"]["cmd"]
    print(f"✓ create_link generated properly signed live URL: {link_data['js']['cmd']}")

    # Test create_link for catchup program_id
    catchup_resp = client.get(
        f"/stalker_portal/server/load.php?type=itv&action=create_link&ch_id=851&program_id=123456&token={stb_token}",
        cookies={"mac": "00:1A:79:0D:D6:C1"}
    )
    assert catchup_resp.status_code == 200
    catchup_data = catchup_resp.json()
    assert f"/t/{admin.token}/stream/851/123456.m3u8" in catchup_data["js"]["cmd"]
    print(f"✓ create_link with program_id: {catchup_data['js']['cmd']}")

    # Test create_link with cmd containing /archive/
    archive_cmd_resp = client.get(
        f"/stalker_portal/server/load.php?type=itv&action=create_link&cmd=ffmpeg%20%2Farchive%2F851%2F654321&token={stb_token}",
        cookies={"mac": "00:1A:79:0D:D6:C1"}
    )
    assert archive_cmd_resp.status_code == 200
    archive_cmd_data = archive_cmd_resp.json()
    assert f"/t/{admin.token}/stream/851/654321.m3u8" in archive_cmd_data["js"]["cmd"]
    print(f"✓ create_link with /archive/ cmd: {archive_cmd_data['js']['cmd']}")

    # Test short EPG
    short_epg_resp = client.get(
        f"/stalker_portal/server/load.php?type=itv&action=get_short_epg&ch_id=851&token={stb_token}",
        cookies={"mac": "00:1A:79:0D:D6:C1"}
    )
    assert short_epg_resp.status_code == 200
    short_epg_data = short_epg_resp.json()
    assert "js" in short_epg_data
    assert isinstance(short_epg_data["js"], list)
    print("✓ get_short_epg returned valid array structure.")

    # Test simple data table EPG (type=epg&action=get_simple_data_table)
    today_str = time.strftime("%Y-%m-%d")
    epg_table_resp = client.get(
        f"/stalker_portal/server/load.php?type=epg&action=get_simple_data_table&ch_id=851&date={today_str}&p=1&token={stb_token}",
        cookies={"mac": "00:1A:79:0D:D6:C1"}
    )
    assert epg_table_resp.status_code == 200
    epg_table_data = epg_table_resp.json()
    assert "js" in epg_table_data
    assert "total_items" in epg_table_data["js"]
    assert "data" in epg_table_data["js"]
    table_items = epg_table_data["js"]["data"]
    assert isinstance(table_items, list)
    assert len(table_items) >= 1
    p0 = table_items[0]
    assert "start_timestamp" in p0
    assert "stop_timestamp" in p0
    assert "mark_archive" in p0
    assert p0["mark_archive"] == 1, "Past catchup program must have mark_archive: 1"
    assert "cmd" in p0
    print(f"✓ get_simple_data_table verified: {len(table_items)} items, mark_archive={p0['mark_archive']}, start_timestamp={p0['start_timestamp']}")

    # Test forward EPG info (type=itv&action=get_epg_info&period=24)
    epg_info_resp = client.get(
        f"/stalker_portal/server/load.php?type=itv&action=get_epg_info&period=24&token={stb_token}",
        cookies={"mac": "00:1A:79:0D:D6:C1"}
    )
    assert epg_info_resp.status_code == 200
    epg_info_data = epg_info_resp.json()
    assert "js" in epg_info_data
    assert "data" in epg_info_data["js"]
    assert isinstance(epg_info_data["js"]["data"], dict), "get_epg_info data must be dict of channels"
    assert "851" in epg_info_data["js"]["data"]
    ch_progs = epg_info_data["js"]["data"]["851"]
    assert isinstance(ch_progs, list)
    if ch_progs:
        prog = ch_progs[0]
        assert "id" in prog
        assert "name" in prog
        assert "descr" in prog
        assert "start_timestamp" in prog
        assert "stop_timestamp" in prog
        print(f"✓ get_epg_info verified: channel '851' has {len(ch_progs)} forward programs with timestamps")

    # Test type=tv_archive&action=create_link (Catchup / TimeShift replay)
    archive_cmd = f"auto /media/archive/851/9991.mpg?utc={int(time.time()) - 3600}&lutc={int(time.time()) - 600}"
    from urllib.parse import quote
    tv_arch_resp = client.get(
        f"/stalker_portal/server/load.php?type=tv_archive&action=create_link&cmd={quote(archive_cmd)}&token={stb_token}",
        cookies={"mac": "00:1A:79:0D:D6:C1"}
    )
    assert tv_arch_resp.status_code == 200
    tv_arch_data = tv_arch_resp.json()
    assert "js" in tv_arch_data
    assert "cmd" in tv_arch_data["js"]
    final_arch_cmd = tv_arch_data["js"]["cmd"]
    assert f"/t/{admin.token}/stream/851/9991.m3u8" in final_arch_cmd
    assert "utc=" in final_arch_cmd
    assert "lutc=" in final_arch_cmd
    print(f"✓ type=tv_archive&action=create_link generated catchup URL: {final_arch_cmd}")

    # 7. Test /api/profile/stalker-mac update
    sess_id = create_session(admin.id)
    mac_update_resp = client.post(
        "/api/profile/stalker-mac",
        json={"mac": "00:1A:79:11:22:33"},
        cookies={SESSION_COOKIE_NAME: sess_id}
    )
    assert mac_update_resp.status_code == 200
    assert mac_update_resp.json()["stalker_mac"] == "00:1a:79:11:22:33"
    print("✓ Successfully updated user MAC to 00:1a:79:11:22:33")

    # Reset back to user's real MAC
    client.post(
        "/api/profile/stalker-mac",
        json={"mac": "00:1A:79:0D:D6:C1"},
        cookies={SESSION_COOKIE_NAME: sess_id}
    )
    admin_refreshed = get_user_by_username("admin")
    assert admin_refreshed.stalker_mac == "00:1a:79:0d:d6:c1"
    print("✓ Reset user MAC back to 00:1a:79:0d:d6:c1")

    print("\nALL STALKER MAC AUTHENTICATION TESTS PASSED!")

if __name__ == "__main__":
    test_stalker_mac_auth()
