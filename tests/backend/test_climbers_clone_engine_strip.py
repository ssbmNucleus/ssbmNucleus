"""Pairs no longer ship m-ex's `clone_engine` patch, and export strips a stale
copy from the project's MxPt.dat.

The kind alias already makes a pair leader answer every `fp->kind` check as its
donor (articles, effects, sounds), and the patch's effect hook breaks Kirby's
copied specials for the whole build (Falcon Punch drew the Final Cutter slash,
Warlock Punch crashed). Vanilla, a pair-free build and a pair build with the
patch removed all render the copied moves correctly; a Mario pair leader still
throws a fireball, a Fox pair leader still fires the blaster, without it.
"""
import struct

from vault.climbers import engine_code


def _hsd(roots: list[tuple[str, bytes]]) -> bytes:
    """A minimal HSD archive: one data blob per root, no relocations/refs."""
    data = b"".join(blob for _, blob in roots)
    names = b""
    root_table = b""
    off = 0
    for i, (name, blob) in enumerate(roots):
        root_table += struct.pack(">II", off, len(names))
        names += name.encode() + b"\0"
        off += len(blob)
    body = data + root_table + names
    return struct.pack(">5I", 0x20 + len(body), len(data), 0, len(roots), 0) + bytes(12) + body


def _fighter(name, symbol, sub=-1, behavior=0):
    return {"name": name, "subCharacter": sub, "subCharacterBehavior": behavior,
            "files": {"fighterDataSymbol": symbol}}


VANILLA = [_fighter("Mario", "ftDataMario"), _fighter("Fox", "ftDataFox"),
           _fighter("C. Falcon", "ftDataCaptain"), _fighter("Kirby", "ftDataKirby")]


def test_hsd_root_names_reads_the_root_table():
    archive = _hsd([("clone_engine", b"\x60\x00\x00\x00" * 4), ("other", b"\x4e\x80\x00\x20")])
    assert engine_code.hsd_root_names(archive) == ["clone_engine", "other"]


def test_drop_sole_root_collapses_to_a_bare_header():
    archive = _hsd([("clone_engine", b"\x60\x00\x00\x00" * 4)])
    out = engine_code.drop_hsd_root(archive, "clone_engine")
    assert out == struct.pack(">5I", 0x20, 0, 0, 0, 0) + bytes(12)
    assert engine_code.hsd_root_names(out) == []


def test_drop_one_root_keeps_the_others_parseable():
    archive = _hsd([("clone_engine", b"\x60\x00\x00\x00" * 4), ("other", b"\x4e\x80\x00\x20")])
    out = engine_code.drop_hsd_root(archive, "clone_engine")
    assert engine_code.hsd_root_names(out) == ["other"]
    assert len(out) == len(archive) - 8
    assert engine_code.drop_hsd_root(out, "clone_engine") == out   # absent: untouched


def test_removable_when_every_clone_is_an_aliased_pair_leader():
    fighters = VANILLA + [_fighter("C. Falcon & Kirby", "ftDataCaptain", sub=3)]
    assert engine_code.clone_engine_removable(fighters) is True


def test_kept_when_a_non_pair_clone_exists():
    fighters = VANILLA + [_fighter("C. Falcon & Kirby", "ftDataCaptain", sub=3),
                          _fighter("Metal Mario", "ftDataMario")]
    assert engine_code.clone_engine_removable(fighters) is False


def test_strip_rewrites_only_a_removable_patch_table(tmp_path):
    proj = tmp_path / "proj"
    (proj / "files").mkdir(parents=True)
    mxpt = proj / "files" / "MxPt.dat"
    mxpt.write_bytes(_hsd([("clone_engine", b"\x60\x00\x00\x00" * 4)]))
    pairs = VANILLA + [_fighter("C. Falcon & Kirby", "ftDataCaptain", sub=3)]

    assert engine_code.strip_clone_engine(proj / "project.mexproj", pairs) is True
    assert engine_code.hsd_root_names(mxpt.read_bytes()) == []
    # idempotent: nothing left to strip
    assert engine_code.strip_clone_engine(proj / "project.mexproj", pairs) is False

    mxpt.write_bytes(_hsd([("clone_engine", b"\x60\x00\x00\x00" * 4)]))
    with_other_clone = pairs + [_fighter("Metal Mario", "ftDataMario")]
    assert engine_code.strip_clone_engine(proj / "project.mexproj", with_other_clone) is False
    assert engine_code.hsd_root_names(mxpt.read_bytes()) == ["clone_engine"]


def test_strip_ignores_a_project_without_patch_tables(tmp_path):
    proj = tmp_path / "proj"
    (proj / "files").mkdir(parents=True)
    assert engine_code.strip_clone_engine(proj / "project.mexproj", VANILLA) is False
