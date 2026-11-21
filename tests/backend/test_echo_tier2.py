"""Tier 2 scaffolding + build: the move-logic table read from the DOL, the
generated project's shape, and (when MexTK is installed) a real compile
spliced into a Pl DAT and through package.materialize."""
from __future__ import annotations

from tests.paths import APP
import io
import json
import zipfile
from pathlib import Path

import pytest

from vault.echo.tier2 import codegen, build
from vault.echo.datroot import parse

NUCLEUS = APP
DONOR_ZIP = NUCLEUS / "storage" / "echo" / "donors" / "PlMs.zip"
DOLS = sorted((NUCLEUS / "projects").glob("*/sys/main.dol"))

needs_donor = pytest.mark.skipif(not DONOR_ZIP.is_file(), reason="Marth donor cache absent")
needs_dol = pytest.mark.skipif(not DOLS, reason="no project main.dol on disk")
needs_mextk = pytest.mark.skipif(build.find_mextk() is None, reason="MexTK not installed")


def _marth():
    with zipfile.ZipFile(DONOR_ZIP) as zf:
        fj = json.loads(zf.read("fighter.json").decode("utf-8"))
        pl = zf.read(fj["files"]["fighterDataPath"])
    return fj, pl


@needs_dol
def test_marth_move_logic_table_from_dol():
    dol = codegen.Dol(DOLS[0].read_bytes())
    rows = codegen.read_move_logic(dol, 0x803CF420)
    assert len(rows) == 32
    assert rows[0]["state"] == 341 and rows[0]["action_id"] == 295
    assert rows[0]["animation_callback"] == 0x80136844 and rows[0]["iasa_callback"] == 0x80136914
    assert rows[0]["flags"] == 0x00340211 and rows[0]["move_id"] == 18
    assert all(r["camera_callback"] == codegen.CAMERA_BOX for r in rows)
    with pytest.raises(KeyError):
        codegen.read_move_logic(dol, 0x80000000)


@needs_dol
@needs_donor
def test_scaffold_shape():
    fj, pl = _marth()
    files = codegen.scaffold(fj, DOLS[0].read_bytes(), pl, {0x80136844: "ftMs_SpecialNStart_Anim"},
                             name="Probe")
    assert set(files) == {"fighter.h", "fighter.c", "moves.c"}
    h, c, m = files["fighter.h"], files["fighter.c"], files["moves.c"]
    assert "#define DONOR_ONLOAD            0x801364AC" in h
    assert "DONOR_FTKIND            FTKIND_MARTH" in h
    assert "STATE_SPECIALNSTART = 341" in h and "ACTION_SPECIALNSTART = 295" in h
    assert c.count("/* state ") == 32
    assert "0x80136844 /* ftMs_SpecialNStart_Anim */" in c
    assert "FtWrap_Install(fd, PostPhysics)" in c and "MexCPU_InitSpoofData(gobj, DONOR_FTKIND)" in c
    assert "0x8006CC7C" in c  # Fighter_TakeDamage refund in the damage-taken hook
    for hook in ("Moves_OnLoad", "Moves_PostPhysics", "Moves_DamageTakenMult", "Moves_ResetAttributes"):
        assert hook in m and hook in h


def test_dol_reader_rejects_unmapped_address():
    hdr = bytearray(0x100)
    import struct
    struct.pack_into(">I", hdr, 0, 0x100)          # text0 offset
    struct.pack_into(">I", hdr, 0x48, 0x80003100)  # text0 addr
    struct.pack_into(">I", hdr, 0x90, 0x10)        # text0 size
    dol = codegen.Dol(bytes(hdr) + bytes(range(16)))
    assert dol.read(0x80003104, 2) == b"\x04\x05"
    with pytest.raises(KeyError):
        dol.read(0x80100000, 4)


@needs_mextk
@needs_dol
@needs_donor
def test_scaffold_compiles_and_splices(tmp_path):
    fj, pl = _marth()
    files = codegen.scaffold(fj, DOLS[0].read_bytes(), pl, None)
    for n, t in files.items():
        (tmp_path / n).write_text(t, encoding="utf-8")
    out = build.build_pl(pl, tmp_path)
    assert [n for _, n in parse(out)[2]] == ["ftDataMars", "ftFunction"]
    assert out[0x20:0x20 + parse(pl)[0].__len__()] == parse(pl)[0]
    with pytest.raises(build.BuildError):
        build.build_pl(out, tmp_path)   # refuses to stack a second code root
    bad = dict(files); bad["moves.c"] = files["moves.c"] + "\nvoid broken( { }\n"
    rep = build.check_files(bad)
    assert rep["ok"] is False and "error" in rep["error"].lower()


@needs_mextk
@needs_dol
@needs_donor
def test_materialize_with_code():
    from vault.echo import package
    fj, pl = _marth()
    files = codegen.scaffold(fj, DOLS[0].read_bytes(), pl, None)
    echo = {"donor": "Marth", "name": "Code Probe", "ops": [], "code": {"files": files}}
    fighter_zip, report = package.materialize(DONOR_ZIP.read_bytes(), echo)
    assert report["code"]["bytes"] > 0 and report["ok"]
    with zipfile.ZipFile(io.BytesIO(fighter_zip)) as zf:
        out = zf.read(fj["files"]["fighterDataPath"])
    assert "ftFunction" in [n for _, n in parse(out)[2]]
