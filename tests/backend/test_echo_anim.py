"""
Animation overrides for the Echo pipeline (vault.echo.anim).

Pure-Python parts (validation, the .anim text transform, clip storage) run
everywhere. The end-to-end import shells out to HSDRawViewer's
`--anim` verbs and needs the built exe + the cached vanilla Falco AJ, so it is
skipped where those are absent.
"""
from __future__ import annotations

from tests.paths import APP
import struct
from pathlib import Path

import pytest

from vault.echo import anim as echo_anim
from vault.echo.subactions import FighterDat

BASE = APP / "storage" / "test-base" / "files"
FALCO = BASE / "PlFc.dat"
FALCO_AJ = BASE / "PlFcAJ.dat"
needs_falco = pytest.mark.skipif(not FALCO.is_file(), reason="vanilla PlFc.dat not cached")


def _hsdraw_available() -> bool:
    try:
        from core.config import HSDRAW_EXE
        return Path(HSDRAW_EXE).is_file()
    except Exception:
        return False


needs_hsdraw = pytest.mark.skipif(not (_hsdraw_available() and FALCO_AJ.is_file()),
                                  reason="HSDRawViewer not built or PlFcAJ.dat not cached")


@pytest.fixture
def clips_tmp(tmp_path, monkeypatch):
    d = tmp_path / "clips"
    d.mkdir()
    monkeypatch.setattr(echo_anim, "clips_dir", lambda: d)
    return d


MINI_ANIM = """animVersion 1.1;
mayaVersion 2015;
timeUnit ntscf;
linearUnit cm;
angularUnit rad;
startTime 0;
endTime 2;
anim translate.translateX translateX JOBJ_0 0 1 0;
animData {
 input time;
 output linear;
 keys {
 0 1.5 auto auto 1 1 0;
 2 3.0 auto auto 1 1 0;
 }
}
anim rotate.rotateZ rotateZ JOBJ_1 0 1 1;
animData {
 input time;
 output angular;
 keys {
 0 0.5 auto auto 1 1 0;
 1 -0.25 auto auto 1 1 0;
 2 0 auto auto 1 1 0;
 }
}
"""


def test_exaggerate_scales_rotation_keys_only():
    out, n = echo_anim.exaggerate_anim(MINI_ANIM, 2.0)
    assert n == 2                                   # 0.5 and -0.25 (the 0 key is left alone)
    assert " 0 1.000000 auto" in out and " 1 -0.500000 auto" in out
    assert " 0 1.5 auto" in out and " 2 3.0 auto" in out   # translate untouched
    assert out.count("anim ") == MINI_ANIM.count("anim ")


def test_store_and_resolve_clip(clips_tmp):
    info = echo_anim.store_clip("swing.anim", MINI_ANIM.encode())
    assert info["format"] == "anim" and info["bytes"] == len(MINI_ANIM)
    assert (clips_tmp / f"{info['clip']}.anim").is_file()
    again = echo_anim.store_clip("other-name.anim", MINI_ANIM.encode())
    assert again["clip"] == info["clip"]            # content-addressed: dedupes
    assert echo_anim.resolve_clip({"clip": info["clip"]}).name == f"{info['clip']}.anim"
    assert [c["clip"] for c in echo_anim.list_clips()] == [info["clip"]]
    with pytest.raises(echo_anim.AnimError):
        echo_anim.store_clip("notes.txt", b"hello")
    with pytest.raises(echo_anim.AnimError):
        echo_anim.store_clip("empty.anim", b"")
    with pytest.raises(echo_anim.AnimError):
        echo_anim.resolve_clip({"clip": "../../etc"})
    with pytest.raises(echo_anim.AnimError):
        echo_anim.resolve_clip({"clip": "deadbeefdeadbeef"})


@needs_falco
def test_validate_overrides_reports_everything_at_once(clips_tmp, tmp_path):
    dat = FALCO.read_bytes()
    good_clip = echo_anim.store_clip("ok.anim", MINI_ANIM.encode())["clip"]
    txt = tmp_path / "not-a-clip.txt"
    txt.write_text("x")
    overrides = [
        {"move": "ftilt", "source": "taunt"},                      # ok
        {"move": "ftilt", "exaggerate": 1.5, "error": 0.001},      # ok
        {"move": "ftilt", "clip": good_clip},                      # ok
        {"move": "nope", "source": "taunt"},                       # unknown move
        {"move": "ftilt"},                                         # no kind
        {"move": "ftilt", "source": "taunt", "exaggerate": 2},     # two kinds
        {"move": "ftilt", "clip": "0000000000000000"},             # unknown clip
        {"move": "ftilt", "file": str(txt)},                       # bad format
        {"move": "ftilt", "file": str(tmp_path / "missing.anim")},  # missing file
        {"move": "ftilt", "exaggerate": 0},                        # bad factor
        {"move": "ftilt", "source": "not-a-move"},                 # unknown source
        {"move": "ftilt", "source": "taunt", "error": -1},         # bad tolerance
        {"move": "ftilt", "source": "taunt", "map": str(tmp_path / "no.ini")},  # missing map
        "garbage",                                                 # not an object
    ]
    errors = echo_anim.validate_overrides(dat, overrides)
    idx = sorted(int(e.split("]")[0].split("[")[1]) for e in errors)
    assert idx == list(range(3, len(overrides)))
    joined = "\n".join(errors)
    assert "unknown move" in joined and "exactly one of" in joined
    assert "not found -- upload" in joined and "unsupported clip format" in joined
    assert "exaggerate must be" in joined and "joint map not found" in joined
    assert echo_anim.validate_overrides(dat, overrides[:3]) == []
    assert echo_anim.validate_overrides(dat, "nope") == ["animations must be a list"]


# ---------------------------------------------------------------------------
# end to end through HSDRawViewer
# ---------------------------------------------------------------------------
def _walk_aj(b: bytes) -> dict[str, tuple[int, int]]:
    """symbol -> (offset, size) by walking the concatenated DAT headers (independent
    of HSDRaw's own bookkeeping)."""
    out, off = {}, 0
    while off < len(b):
        size = struct.unpack(">I", b[off:off + 4])[0]
        if size == 0:
            break
        ds, rc, rn = struct.unpack(">III", b[off + 4:off + 16])
        strtab = off + 0x20 + ds + rc * 4 + rn * 8
        so = struct.unpack(">I", b[off + 0x20 + ds + rc * 4 + 4:off + 0x20 + ds + rc * 4 + 8])[0]
        sym = b[strtab + so:b.index(b"\0", strtab + so)].decode()
        out[sym] = (off, size)
        off += (size + 0x1F) & ~0x1F
    return out


@needs_hsdraw
def test_apply_overrides_end_to_end(tmp_path):
    aj0, pl0 = FALCO_AJ.read_bytes(), FALCO.read_bytes()
    new_aj, new_pl, report = echo_anim.apply_overrides(
        aj0, pl0, [{"move": "ftilt", "source": "taunt"},
                   {"move": "utilt", "exaggerate": 1.5}], workdir=tmp_path)
    assert len(report) == 2 and report[0]["kind"] == "source:taunt"
    assert "SUCCESS" in report[0]["log"] and "SUCCESS" in report[1]["log"]

    # The Pl file changed ONLY in action-table (offset, size) fields.
    old, new = FighterDat(pl0), FighterDat(new_pl)
    assert len(new_pl) == len(pl0)
    tbl, cnt = new.action_table
    allowed = set()
    for i in range(cnt):
        a = 0x20 + tbl + i * 0x18
        allowed.update(range(a + 4, a + 12))
    diffs = [i for i in range(len(pl0)) if pl0[i] != new_pl[i]]
    assert diffs and all(i in allowed for i in diffs)

    # Every fight action points exactly where the rebuilt AJ put its clip; the
    # demo-table entries (clips in Pl??DViWaitAJ) are untouched.
    layout = _walk_aj(new_aj)
    ftilt = [a for a in new.actions if a.motion == "AttackS3S"][0]
    for a, b in zip(old.actions, new.actions):
        assert (a.symbol, a.script_offset, a.flags, a.flags2) == (b.symbol, b.script_offset, b.flags, b.flags2)
        if a.symbol in layout:
            assert (b.anim_offset, b.anim_size) == layout[a.symbol]
        else:
            assert (a.anim_offset, a.anim_size) == (b.anim_offset, b.anim_size)
    # ftilt now carries the (much longer) taunt clip
    assert ftilt.anim_size > [a for a in old.actions if a.motion == "AttackS3S"][0].anim_size
    assert all(size <= 0x8000 for _, size in layout.values())


@needs_hsdraw
def test_apply_overrides_rejects_wrong_skeleton(tmp_path):
    kirby_aj = BASE / "PlKbAJ.dat"
    if not kirby_aj.is_file():
        pytest.skip("PlKbAJ.dat not cached")
    # export a Kirby clip (46 joints), then try to put it on Falco (67 joints)
    clip = tmp_path / "kirby.anim"
    echo_anim._run(["--anim", "export", str(kirby_aj), "ACTION_Wait1_figatree", str(clip)])
    with pytest.raises(echo_anim.AnimError) as ei:
        echo_anim.apply_overrides(FALCO_AJ.read_bytes(), FALCO.read_bytes(),
                                  [{"move": "ftilt", "file": str(clip)}], workdir=tmp_path)
    assert "46 joints" in str(ei.value) and "67" in str(ei.value)
