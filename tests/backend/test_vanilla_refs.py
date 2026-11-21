"""
Tests for vanilla_refs.py -- lazy extraction of extras' vanilla reference DATs
from the user's vanilla ISO into storage/test-base/files/.

Uses a synthetic mini GameCube disc image (header + FST + file data) so no
real ISO is needed: the FST format is what matters, not Melee's contents.
"""
from tests.paths import BACKEND
import json
import struct
import sys
from pathlib import Path

import pytest

BACKEND_DIR = BACKEND
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from shared.vanilla_extract import vanilla_refs  # noqa: E402
import vault.extras.relocate as relocate  # noqa: E402

EF_BYTES = b"EF-TEST-CONTENT-" * 40
PL_BYTES = b"PL-OTHER-DATA!" * 11


def build_mini_iso(path: Path, files: dict[str, bytes]) -> Path:
    """A minimal GC disc: GALE01 header, FST at 0x1000 (root dir + one
    subdirectory entry + one file entry per item), file data from 0x4000."""
    fst_off = 0x1000
    table = bytearray()

    def add_name(name: str) -> int:
        off = len(table)
        table.extend(name.encode("ascii") + b"\0")
        return off

    num_entries = 2 + len(files)  # root + "audio" dir + files
    entries = bytearray()

    def pack_entry(flags: int, name_off: int, a: int, b: int) -> None:
        entries.extend(bytes([flags]) + name_off.to_bytes(3, "big")
                       + struct.pack(">II", a, b))

    pack_entry(1, 0, 0, num_entries)              # root
    pack_entry(1, add_name("audio"), 0, num_entries)  # a directory to skip
    data_off = 0x4000
    placed = []
    for name, content in files.items():
        pack_entry(0, add_name(name), data_off, len(content))
        placed.append((data_off, content))
        data_off += (len(content) + 0x1F) & ~0x1F

    fst = bytes(entries) + bytes(table)
    iso = bytearray(data_off)
    iso[0:6] = b"GALE01"
    iso[7] = 0x02
    struct.pack_into(">II", iso, 0x424, fst_off, len(fst))
    iso[fst_off:fst_off + len(fst)] = fst
    for off, content in placed:
        iso[off:off + len(content)] = content
    path.write_bytes(bytes(iso))
    return path


@pytest.fixture
def mini_iso(tmp_path):
    return build_mini_iso(tmp_path / "mini.iso",
                          {"EfTest.dat": EF_BYTES, "PlXx.dat": PL_BYTES})


@pytest.fixture
def recorded_iso(tmp_path, mini_iso, monkeypatch):
    """Point the module's ISO record at a temp file naming the mini ISO."""
    record = tmp_path / "vanilla_iso.json"
    record.write_text(json.dumps({"path": str(mini_iso)}), encoding="utf-8")
    monkeypatch.setattr(vanilla_refs, "ISO_RECORD_PATH", record)
    return mini_iso


# ---------------------------------------------------------------------------
# extract_file_from_iso
# ---------------------------------------------------------------------------

def test_extract_finds_file(mini_iso, tmp_path):
    dest = tmp_path / "out" / "EfTest.dat"
    assert vanilla_refs.extract_file_from_iso(mini_iso, "EfTest.dat", dest)
    assert dest.read_bytes() == EF_BYTES


def test_extract_is_case_insensitive(mini_iso, tmp_path):
    dest = tmp_path / "PlXx.dat"
    assert vanilla_refs.extract_file_from_iso(mini_iso, "plxx.DAT", dest)
    assert dest.read_bytes() == PL_BYTES


def test_extract_missing_file_returns_false(mini_iso, tmp_path):
    dest = tmp_path / "Nope.dat"
    assert not vanilla_refs.extract_file_from_iso(mini_iso, "Nope.dat", dest)
    assert not dest.exists()


def test_extract_rejects_non_disc(tmp_path):
    bogus = tmp_path / "bogus.iso"
    bogus.write_bytes(b"\xFF" * 0x2000)
    with pytest.raises(ValueError):
        vanilla_refs.extract_file_from_iso(bogus, "EfTest.dat", tmp_path / "x.dat")


# ---------------------------------------------------------------------------
# ensure_vanilla_ref
# ---------------------------------------------------------------------------

def test_ensure_returns_existing_ref_without_iso(tmp_path, monkeypatch):
    monkeypatch.setattr(vanilla_refs, "ISO_RECORD_PATH", tmp_path / "no-record.json")
    ref = tmp_path / "test-base" / "files" / "EfTest.dat"
    ref.parent.mkdir(parents=True)
    ref.write_bytes(EF_BYTES)
    got = vanilla_refs.ensure_vanilla_ref("EfTest.dat", storage_path=tmp_path)
    assert got == ref


def test_ensure_extracts_from_recorded_iso(tmp_path, recorded_iso):
    storage = tmp_path / "storage"
    got = vanilla_refs.ensure_vanilla_ref("EfTest.dat", storage_path=storage)
    assert got == storage / "test-base" / "files" / "EfTest.dat"
    assert got.read_bytes() == EF_BYTES


def test_ensure_caches_on_disk(tmp_path, recorded_iso):
    storage = tmp_path / "storage"
    assert vanilla_refs.ensure_vanilla_ref("EfTest.dat", storage_path=storage)
    recorded_iso.unlink()  # ISO gone -- the extracted copy must still resolve
    got = vanilla_refs.ensure_vanilla_ref("EfTest.dat", storage_path=storage)
    assert got is not None and got.read_bytes() == EF_BYTES


def test_ensure_without_recorded_iso_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(vanilla_refs, "ISO_RECORD_PATH", tmp_path / "no-record.json")
    assert vanilla_refs.ensure_vanilla_ref("EfTest.dat", storage_path=tmp_path) is None


def test_ensure_refuses_path_segments(tmp_path, recorded_iso):
    assert vanilla_refs.ensure_vanilla_ref("../evil.dat", storage_path=tmp_path) is None
    assert vanilla_refs.ensure_vanilla_ref("sub\\evil.dat", storage_path=tmp_path) is None


# ---------------------------------------------------------------------------
# record_vanilla_iso / known_vanilla_iso
# ---------------------------------------------------------------------------

def test_record_and_known_roundtrip(tmp_path, mini_iso, monkeypatch):
    record = tmp_path / "vanilla_iso.json"
    monkeypatch.setattr(vanilla_refs, "ISO_RECORD_PATH", record)
    vanilla_refs.record_vanilla_iso(mini_iso)
    assert vanilla_refs.known_vanilla_iso() == mini_iso


def test_record_ignores_non_melee_file(tmp_path, monkeypatch):
    record = tmp_path / "vanilla_iso.json"
    monkeypatch.setattr(vanilla_refs, "ISO_RECORD_PATH", record)
    other = tmp_path / "other.iso"
    other.write_bytes(b"NOTMELEE" * 4)
    vanilla_refs.record_vanilla_iso(other)
    assert vanilla_refs.known_vanilla_iso() is None


def test_known_none_when_iso_moved(tmp_path, recorded_iso):
    recorded_iso.unlink()
    assert vanilla_refs.known_vanilla_iso() is None


# ---------------------------------------------------------------------------
# relocate.vanilla_reference_path fallback wiring
# ---------------------------------------------------------------------------

def test_reference_path_extracts_when_missing(tmp_path, recorded_iso):
    storage = tmp_path / "storage"
    got = relocate.vanilla_reference_path(str(storage), "EfTest.dat")
    assert got is not None
    assert Path(got).read_bytes() == EF_BYTES


def test_reference_path_none_when_unobtainable(tmp_path, monkeypatch):
    monkeypatch.setattr(vanilla_refs, "ISO_RECORD_PATH", tmp_path / "no-record.json")
    assert relocate.vanilla_reference_path(str(tmp_path), "EfTest.dat") is None
