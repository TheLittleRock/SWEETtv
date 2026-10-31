import struct
import xml.etree.ElementTree as ET
import pytest
from app.drm.streamer import (
    normalize_lang_code,
    parse_iso8601_duration,
    patch_mp4_duration,
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


def test_patch_mp4_duration():
    # Build a minimal synthetic moov buffer containing mvhd, tkhd, mdhd
    mvhd = bytearray(b"\x00\x00\x00\x6c" + b"mvhd" + b"\x00\x00\x00\x00" + b"\x00" * 8 + struct.pack(">II", 1000, 0) + b"\x00" * 80)
    tkhd = bytearray(b"\x00\x00\x00\x5c" + b"tkhd" + b"\x00\x00\x00\x00" + b"\x00" * 16 + struct.pack(">I", 0) + b"\x00" * 64)
    mdhd = bytearray(b"\x00\x00\x00\x20" + b"mdhd" + b"\x00\x00\x00\x00" + b"\x00" * 8 + struct.pack(">II", 12800, 0) + b"\x00" * 8)

    synthetic_buffer = bytes(mvhd + tkhd + mdhd)
    target_sec = 1925.16
    patched = patch_mp4_duration(synthetic_buffer, target_sec)

    # Verify mvhd duration patched
    mv_idx = patched.find(b"mvhd")
    mv_dur = struct.unpack(">I", patched[mv_idx + 20 : mv_idx + 24])[0]
    assert mv_dur == int(target_sec * 1000)

    # Verify tkhd duration patched
    tk_idx = patched.find(b"tkhd")
    tk_dur = struct.unpack(">I", patched[tk_idx + 24 : tk_idx + 28])[0]
    assert tk_dur == int(target_sec * 1000)

    # Verify mdhd duration patched
    md_idx = patched.find(b"mdhd")
    md_dur = struct.unpack(">I", patched[md_idx + 20 : md_idx + 24])[0]
    assert md_dur == int(target_sec * 12800)
