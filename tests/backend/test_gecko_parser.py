"""Tests for core.gecko — the Python mirror of mexLib's CodeLoader/MexCode.

Fixtures are inline INI text shaped exactly like real project files
(projects/<name>/files/codes.ini as written by CodeLoader.ToINI).
"""
import pytest

from core.gecko import (
    header,
    parse_ini,
    serialize_ini,
    smart_parse,
    split_header,
    trim_hex_line,
    validate_source,
)

# The real required code from projects/install/required_codes.py (first C2 block).
KELLZ_HEADER = "Skip Slippi SSS [KELLZ]"

SAMPLE_INI = (
    "$!Skip Slippi SSS [KELLZ]\n"
    "C20166B4 00000002\n"
    "3D808001 618C6204\n"
    "7D8903A6 00000000\n"
    "$QOL | Better Camera [Achilles,UnclePunch]\n"
    "*Removes camera restrictions\n"
    "*so it follows the action better\n"
    "04452C68 C0A00000  #zoom\n"
    "$No Hex Entry [Nobody]\n"
    "*this one has no code lines and is dropped\n"
)


# ---------------------------------------------------------------- trim/header

def test_trim_hex_line_strips_comments_and_spaces():
    assert trim_hex_line("04263384 48000010") == "0426338448000010"
    assert trim_hex_line("04263384 48000010  # label") == "0426338448000010"
    assert trim_hex_line("  0426 3384 4800 0010") == "0426338448000010"


@pytest.mark.parametrize("bad", [
    "", "04263384", "04263384 48000010 FF", "hello world",
    "0426338448 00001",  # 15 chars
    "GGGGGGGG48000010",  # C#'s loose regex would accept this; we must not
])
def test_trim_hex_line_rejects(bad):
    assert trim_hex_line(bad) is None


def test_header_round_trips_through_split():
    for name, creator in [("Skip Slippi SSS", "KELLZ"), ("UCF 0.84", "")]:
        assert split_header(header(name, creator)) == (name, creator)


def test_split_header_nested_brackets_matches_csharp():
    # CodeLoader.FromINI's lazy regex treats everything from the FIRST '[' to a
    # ']' at end-of-line as the creator; mirror that exactly, quirk included.
    assert split_header("A [B] C [D]") == ("A", "B] C [D")


def test_header_kellz_canonical():
    assert header("Skip Slippi SSS", "KELLZ") == KELLZ_HEADER
    assert split_header(KELLZ_HEADER) == ("Skip Slippi SSS", "KELLZ")


# ------------------------------------------------------------------ parse_ini

def test_parse_ini_sample():
    codes = parse_ini(SAMPLE_INI)
    # third entry has no hex lines -> dropped, like CodeLoader.FromINI
    assert [c["name"] for c in codes] == ["Skip Slippi SSS", "QOL | Better Camera"]
    kellz, cam = codes
    assert kellz["enabled"] is True and kellz["creator"] == "KELLZ"
    assert cam["enabled"] is False
    assert cam["creator"] == "Achilles,UnclePunch"
    assert cam["description"] == (
        "Removes camera restrictions\nso it follows the action better"
    )
    # source preserved verbatim, inline #comment included
    assert cam["source"] == "04452C68 C0A00000  #zoom"


def test_parse_ini_round_trip():
    codes = parse_ini(SAMPLE_INI)
    again = parse_ini(serialize_ini(codes))
    assert again == codes


def test_parse_ini_empty_and_zero_byte():
    assert parse_ini("") == []
    assert parse_ini("\n\n") == []


def test_serialize_ini_header_format():
    text = serialize_ini([
        {"name": "A", "creator": "B", "description": "", "source": "04000000 00000000", "enabled": True},
        {"name": "C", "creator": "", "description": "d1\nd2", "source": "04000000 00000000", "enabled": False},
    ])
    lines = text.splitlines()
    assert lines[0] == "$!A [B]"
    assert lines[2] == "$C"
    assert lines[3] == "*d1"
    assert lines[4] == "*d2"


# ------------------------------------------------------------ validate_source

def test_validate_04_write():
    assert validate_source("04263384 48000010")["ok"] is True


def test_validate_multi_c2():
    # two C2 blocks, 2 lines each (count includes the terminator line)
    src = (
        "C20166B4 00000002\n"
        "3D808001 618C6204\n"
        "7D8903A6 00000000\n"
        "C20163F8 00000001\n"
        "60000000 00000000"
    )
    assert validate_source(src)["ok"] is True


def test_validate_kellz_real_source():
    from projects.install.required_codes import REQUIRED_GECKO_CODES
    _, source = REQUIRED_GECKO_CODES[0]
    assert validate_source(source)["ok"] is True


def test_validate_unsupported_opcode():
    res = validate_source("06263384 00000004\n48000010 00000000")
    assert res["ok"] is False
    assert "0x06" in res["error"]
    assert "not supported" in res["error"]


def test_validate_truncated_c2():
    res = validate_source("C20166B4 00000005\n3D808001 618C6204")
    assert res["ok"] is False
    assert "truncated" in res["error"]


def test_validate_zero_count_c2():
    res = validate_source("C20166B4 00000000")
    assert res["ok"] is False


def test_validate_bad_hex_line():
    res = validate_source("04263384 48000010\nnot hex at all")
    assert res["ok"] is False
    assert res["error"].startswith("line 2")


def test_validate_empty():
    assert validate_source("")["ok"] is False


# ---------------------------------------------------------------- smart_parse

def test_smart_parse_raw_hex():
    out = smart_parse("04263384 48000010\n04452C68 C0A00000")
    assert len(out["codes"]) == 1
    c = out["codes"][0]
    assert c["name"] == "Pasted code"
    assert c["valid"] is True
    assert c["source"].count("\n") == 1


def test_smart_parse_ini_block_multi():
    out = smart_parse(SAMPLE_INI)
    assert [c["name"] for c in out["codes"]] == [
        "Skip Slippi SSS", "QOL | Better Camera",
    ]
    # pasted codes default to enabled regardless of $ vs $!
    assert all(c["enabled"] for c in out["codes"])
    # the hex-less third entry is reported, not silently dropped
    assert any("no valid hex" in w for w in out["warnings"])


def test_smart_parse_dolphin_ini():
    out = smart_parse(
        "[Gecko]\n"
        "$Widescreen 16:9 [dan]\n"
        "04452C68 C0A00000\n"
        "[Gecko_Enabled]\n"
    )
    assert len(out["codes"]) == 1
    assert out["codes"][0]["name"] == "Widescreen 16:9"
    assert out["codes"][0]["creator"] == "dan"


def test_smart_parse_smashboards_style():
    out = smart_parse(
        "Here is my favorite code, works on 1.02 only.\n"
        "\n"
        "Flatzone Forever (Achilles)\n"
        "04263384 48000010\n"
        "04452C68 C0A00000\n"
    )
    assert len(out["codes"]) == 1
    c = out["codes"][0]
    assert c["name"] == "Flatzone Forever"
    assert c["creator"] == "Achilles"
    assert "favorite code" in c["description"]
    assert c["valid"] is True


def test_smart_parse_two_loose_codes():
    out = smart_parse(
        "Code One\n"
        "04263384 48000010\n"
        "Code Two [X]\n"
        "04452C68 C0A00000\n"
    )
    assert [c["name"] for c in out["codes"]] == ["Code One", "Code Two"]
    assert out["codes"][1]["creator"] == "X"


def test_smart_parse_slash_comments():
    out = smart_parse("04263384 48000010 // return\n04452C68 C0A00000")
    assert len(out["codes"]) == 1
    assert out["codes"][0]["valid"] is True


def test_smart_parse_invalid_opcode_marked():
    out = smart_parse("Some Code\n06263384 00000004\n48000010 00000000")
    assert len(out["codes"]) == 1
    assert out["codes"][0]["valid"] is False
    assert "0x06" in out["codes"][0]["error"]


def test_smart_parse_garbage():
    out = smart_parse("hello there\ngeneral kenobi")
    assert out["codes"] == []
    assert any("no gecko code lines" in w for w in out["warnings"])


def test_smart_parse_empty():
    out = smart_parse("   \n")
    assert out["codes"] == []


def test_smart_parse_gct_magic_warns():
    out = smart_parse("00D0C0DE 00D0C0DE\n04263384 48000010\nF0000000 00000000")
    assert any("GCT" in w for w in out["warnings"])


def test_smart_parse_bom_and_crlf():
    out = smart_parse("﻿My Code\r\n04263384 48000010\r\n")
    assert len(out["codes"]) == 1
    assert out["codes"][0]["name"] == "My Code"
