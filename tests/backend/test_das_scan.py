"""
Tests for das_scan.detect_das_variants — DAS alternate-stage detection from an
extracted ISO files/ directory. Pure filesystem fixtures (no ISO/wit/Flask).

Covers both on-disc layouts:
  - m-ex DAS folder layout: files/Gr<code>/<name>.dat
  - 20XX flat layout:       files/Gr<code>.<X>at
"""
from tests.paths import BACKEND
import sys
import hashlib
from pathlib import Path

import pytest

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

import io
import zipfile

from vault.importing.das_scan import (
    detect_das_variants, LEGAL_STAGES,
    vault_variant_md5s, import_variant_to_vault,
)


def _write(p: Path, data: bytes) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


# ----------------------------- m-ex folder layout -----------------------------

def test_mex_folder_layout_detects_non_vanilla_variants(tmp_path):
    f = tmp_path / 'files'
    _write(f / 'GrNBa.dat', b'DAS-LOADER')          # root = loader, not a stage
    _write(f / 'GrNBa' / 'vanilla.dat', b'BASE')     # base inside folder -> skip
    _write(f / 'GrNBa' / 'Autumn.dat', b'AUTUMN')
    _write(f / 'GrNBa' / 'Neon(B).dat', b'NEON')

    got = detect_das_variants(f)
    names = sorted(v.name for v in got)
    assert names == ['Autumn', 'Neon(B)']
    assert all(v.stage_code == 'GrNBa' and v.source == 'mex' for v in got)
    assert all(v.folder == 'battlefield' for v in got)


def test_folder_vanilla_is_excluded_case_insensitive(tmp_path):
    f = tmp_path / 'files'
    _write(f / 'GrSt' / 'Vanilla.dat', b'BASE')      # different case still skipped
    _write(f / 'GrSt' / 'Spooky.dat', b'SPOOKY')
    got = detect_das_variants(f)
    assert [v.name for v in got] == ['Spooky']


# ------------------------------ 20XX flat layout ------------------------------

def test_20xx_flat_layout_detects_slot_variants(tmp_path):
    f = tmp_path / 'files'
    _write(f / 'GrNBa.dat', b'BASE')                 # base -> skip
    _write(f / 'GrNBa.0at', b'ALT0')
    _write(f / 'GrNBa.1at', b'ALT1')
    _write(f / 'GrNBa.lat', b'ALTL')

    got = detect_das_variants(f)
    slots = sorted(v.slot for v in got)
    assert slots == ['0at', '1at', 'lat']
    assert all(v.source == '20xx' and v.stage_code == 'GrNBa' for v in got)
    # generated names use the stage name + uppercased slot char
    assert {v.name for v in got} == {'Battlefield 0', 'Battlefield 1', 'Battlefield L'}


def test_pokemon_stadium_usd_slot_encoding(tmp_path):
    # 20XX encodes Stadium alternates as GrP<digit>.usd (GrPn.usd = neutral base);
    # GrPs1-4.dat are transform sub-stages, not alternates.
    f = tmp_path / 'files'
    _write(f / 'GrPn.usd', b'STADIUM-NEUTRAL')        # base -> skip
    _write(f / 'GrP0.usd', b'STADIUM-ALT0')
    _write(f / 'GrP1.usd', b'STADIUM-ALT1')
    _write(f / 'GrPa.usd', b'STADIUM-ALT-A')          # letter slot (slots cycle past 9)
    _write(f / 'GrP2.usd', b'STADIUM-NEUTRAL')        # byte-identical to neutral -> skip
    _write(f / 'GrPs.usd', b'STADIUM-BASE')           # base code 's' -> skip
    _write(f / 'GrPs1.dat', b'TRANSFORM-1')           # sub-stage -> ignore
    _write(f / 'GrPs2.dat', b'TRANSFORM-2')

    got = [v for v in detect_das_variants(f) if v.stage_code == 'GrPs']
    assert sorted(v.slot for v in got) == ['0', '1', 'a']
    assert all(v.stage_name == 'Pokemon Stadium' for v in got)
    assert {v.name for v in got} == {'Pokemon Stadium 0', 'Pokemon Stadium 1', 'Pokemon Stadium A'}


def test_usd_base_is_not_a_variant(tmp_path):
    f = tmp_path / 'files'
    _write(f / 'GrPs.usd', b'STADIUM-BASE')          # localized base -> skip
    _write(f / 'GrPs.0at', b'STADIUM-ALT')
    got = detect_das_variants(f)
    assert [v.slot for v in got] == ['0at']
    assert got[0].stage_code == 'GrPs'


# ------------------------------- exclusions ----------------------------------

def test_non_legal_stage_ignored(tmp_path):
    f = tmp_path / 'files'
    _write(f / 'GrXyz.0at', b'NOPE')                 # not a DAS stage
    _write(f / 'GrXyz' / 'whatever.dat', b'NOPE2')
    assert detect_das_variants(f) == []


def test_character_costume_files_ignored(tmp_path):
    f = tmp_path / 'files'
    _write(f / 'PlFx.0at', b'FOX-COSTUME')           # Pl*, same ext family, not Gr
    assert detect_das_variants(f) == []


def test_exact_code_match_no_prefix_bleed(tmp_path):
    f = tmp_path / 'files'
    _write(f / 'GrNBaX.0at', b'X')                   # stem != legal code
    _write(f / 'GrNBa.0at', b'REAL')
    got = detect_das_variants(f)
    assert len(got) == 1 and got[0].path.name == 'GrNBa.0at'


def test_variant_identical_to_vanilla_base_is_skipped(tmp_path):
    f = tmp_path / 'files'
    _write(f / 'GrNBa.dat', b'SAME')
    _write(f / 'GrNBa.0at', b'SAME')                 # byte-identical to base
    _write(f / 'GrNBa.1at', b'DIFFERENT')
    got = detect_das_variants(f)
    assert [v.slot for v in got] == ['1at']


# --------------------------------- dedup -------------------------------------

def test_skip_md5s_excludes_known_variants(tmp_path):
    f = tmp_path / 'files'
    _write(f / 'GrIz.0at', b'KNOWN')
    _write(f / 'GrIz.1at', b'NEW')
    got = detect_das_variants(f, skip_md5s={_md5(b'KNOWN')})
    assert [v.slot for v in got] == ['1at']


def test_duplicate_bytes_detected_once(tmp_path):
    f = tmp_path / 'files'
    _write(f / 'GrOp.0at', b'DUP')
    _write(f / 'GrOp.1at', b'DUP')                   # same bytes -> one entry
    got = detect_das_variants(f)
    assert len(got) == 1


# ------------------------------- mixed / md5 ---------------------------------

def test_mixed_folder_and_flat_for_same_stage(tmp_path):
    f = tmp_path / 'files'
    _write(f / 'GrNLa.dat', b'BASE')
    _write(f / 'GrNLa.0at', b'FLAT-ALT')
    _write(f / 'GrNLa' / 'FolderAlt.dat', b'FOLDER-ALT')
    got = detect_das_variants(f)
    assert {v.source for v in got} == {'mex', '20xx'}
    assert len(got) == 2


def test_md5_is_reported_correctly(tmp_path):
    f = tmp_path / 'files'
    _write(f / 'GrIz.0at', b'HASHME')
    got = detect_das_variants(f)
    assert got[0].md5 == _md5(b'HASHME')


def test_missing_dir_returns_empty(tmp_path):
    assert detect_das_variants(tmp_path / 'does-not-exist') == []


def test_all_six_legal_stages_detected(tmp_path):
    f = tmp_path / 'files'
    for i, code in enumerate(LEGAL_STAGES):
        _write(f / f'{code}.0at', f'ALT-{code}'.encode())
    got = detect_das_variants(f)
    assert {v.stage_code for v in got} == set(LEGAL_STAGES)
    assert len(got) == 6


# ----------------------------- vault import ----------------------------------

def _dat_in_zip(zip_path: Path) -> bytes:
    with zipfile.ZipFile(zip_path) as zf:
        name = next(n for n in zf.namelist() if n.endswith('.dat'))
        return zf.read(name)


def test_import_writes_zip_with_dat_and_returns_entry(tmp_path):
    f = tmp_path / 'files'
    _write(f / 'GrNBa.0at', b'ALT-BYTES')
    vault = tmp_path / 'das'
    [variant] = detect_das_variants(f)

    entry = import_variant_to_vault(variant, vault)
    zip_path = vault / 'battlefield' / f"{entry['id']}.zip"
    assert zip_path.is_file()
    assert _dat_in_zip(zip_path) == b'ALT-BYTES'        # original dat preserved
    assert entry['name'] == 'Battlefield 0'
    assert entry['md5'] == variant.md5
    assert entry['source'] == 'iso-scan:20xx'
    # the entry must carry the zip filename so the vault delete handler can find
    # it (without this key, delete KeyError'd: "Delete failed: 'filename'")
    assert entry['filename'] == f"{entry['id']}.zip"
    assert zip_path.name == entry['filename']


def test_import_makes_unique_ids_on_name_collision(tmp_path):
    f = tmp_path / 'files'
    # two distinct variants in the same stage whose names sanitize to "Autumn"
    _write(f / 'GrNBa' / 'Autumn.dat', b'ONE')
    _write(f / 'GrNBa' / 'Autumn!.dat', b'TWO')
    vault = tmp_path / 'das'

    taken, ids = set(), []
    for v in detect_das_variants(f):
        e = import_variant_to_vault(v, vault, taken_ids=taken)
        taken.add(e['id'])
        ids.append(e['id'])

    assert len(ids) == 2 and len(set(ids)) == 2          # no id collision
    for vid in ids:
        assert (vault / 'battlefield' / f'{vid}.zip').is_file()


def test_vault_md5s_roundtrip_enables_rescan_dedup(tmp_path):
    f = tmp_path / 'files'
    _write(f / 'GrIz.0at', b'FIRST')
    vault = tmp_path / 'das'
    [v] = detect_das_variants(f)
    import_variant_to_vault(v, vault)

    # a second scan of the same ISO, skipping what's already in the vault
    skip = vault_variant_md5s(vault)
    again = detect_das_variants(f, skip_md5s=skip)
    assert again == []                                  # nothing new
