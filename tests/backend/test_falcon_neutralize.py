"""Guards the install-time Falcon neutralizer.

Falcon's vanilla skeleton differs per color slot, so any non-neutral Falcon
costume desyncs on Slippi netplay -- and the validator can't catch a costume
whose symbol says one color while it plays in another. `falcon_neutralize`
sidesteps the class of bug by converting every Falcon costume to the neutral
identity (Nr transforms + un-suffixed symbols) on install.

Like test_slippi_autofix.py, these assert against bytes, not return dicts:
the hard constraints are "the vault copy is never touched" and "the result is
byte-equal to what the stock validator considers neutral".
"""
from tests.paths import BACKEND
import hashlib
import os
import struct
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = BACKEND
NUCLEUS_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(NUCLEUS_DIR / 'utility' / 'tools' / 'processor'))

cv = pytest.importorskip('costume_validator')
fn = pytest.importorskip('falcon_neutralize')

VANILLA_FALCON = Path(os.environ.get('FALCON_TEST_ASSETS', NUCLEUS_DIR / 'utility' / 'assets' / 'vanilla' / 'C. Falcon'))
VANILLA_FOX = NUCLEUS_DIR / 'utility' / 'assets' / 'vanilla' / 'Fox' / 'PlFxNr' / 'PlFxNr.dat'

pytestmark = pytest.mark.skipif(
    not (VANILLA_FALCON / 'PlCaNr' / 'PlCaNr.dat').exists(),
    reason='vanilla assets not present')

COLORS = ['Re', 'Bu', 'Gr', 'Gy', 'Wh']


@pytest.mark.parametrize('source', ['Nr', *COLORS])
@pytest.mark.parametrize('target', ['Nr', *COLORS])
def test_slot_conversion_all_falcon_color_pairs(source, target):
    original = _vanilla(source)
    converted = fn.convert_falcon_to_color(original, target)
    expected = 'PlyCaptain5K' + ('' if target == 'Nr' else target) + '_Share_joint'
    assert expected in _root_symbols(converted)
    assert not cv.check_bytes(bytearray(converted), apply_fix=False)[0]
    assert struct.unpack_from('>I', converted)[0] == len(converted)
    # Retargeting does not relocate meshes, textures, or relocation entries.
    assert converted[4:20] == original[4:20]
    # Round-trip back to the source restores its vanilla skeleton identity.
    round_trip = fn.convert_falcon_to_color(converted, source)
    assert not cv.check_bytes(bytearray(round_trip), apply_fix=False)[0]


def _vanilla(color):
    # The module guard only checks Nr; the other slots are extracted separately.
    path = VANILLA_FALCON / f'PlCa{color}' / f'PlCa{color}.dat'
    if not path.exists():
        pytest.skip(f'vanilla Falcon {color} costume not extracted here')
    return path.read_bytes()


def _md5(data):
    return hashlib.md5(data).hexdigest()


def _root_symbols(buf):
    return [s for s, _ in cv._iter_roots(buf)]


@pytest.mark.parametrize('color', COLORS)
def test_colored_vanilla_becomes_neutral(color):
    original = _vanilla(color)
    buf = bytearray(original)
    changed, notes = fn.neutralize_dat_bytes(buf)

    assert changed, notes
    # Size-preserving: length unchanged and the size word still truthful
    assert len(buf) == len(original)
    assert struct.unpack_from('>I', buf, 0)[0] == len(buf)
    # Symbols are now the un-suffixed neutral ones
    for sym in _root_symbols(buf):
        assert not fn._COLOR_SYMBOL_RE.match(sym), sym
    assert 'PlyCaptain5K_Share_joint' in _root_symbols(buf)
    # The UNMODIFIED stock validator now exact-matches the Nr reference and
    # finds nothing to fix -- transforms are byte-equal to neutral vanilla.
    still_changed, _ = cv.check_bytes(bytearray(buf), apply_fix=False)
    assert not still_changed


def test_neutral_vanilla_is_untouched():
    original = _vanilla('Nr')
    buf = bytearray(original)
    changed, notes = fn.neutralize_dat_bytes(buf)
    assert not changed, notes
    assert _md5(bytes(buf)) == _md5(original)


def test_idempotent_on_a_converted_buffer():
    buf = bytearray(_vanilla('Re'))
    assert fn.neutralize_dat_bytes(buf)[0]
    once = bytes(buf)
    changed, notes = fn.neutralize_dat_bytes(buf)
    assert not changed, notes
    assert bytes(buf) == once


@pytest.mark.skipif(not VANILLA_FOX.exists(), reason='vanilla Fox not present')
def test_non_falcon_dat_is_untouched():
    original = VANILLA_FOX.read_bytes()
    buf = bytearray(original)
    changed, notes = fn.neutralize_dat_bytes(buf)
    assert not changed
    assert notes == []
    assert _md5(bytes(buf)) == _md5(original)


def test_tree_mismatch_skips_everything():
    """A custom skeleton must leave the DAT fully untouched -- no rename
    without the matching transform retarget."""
    buf = bytearray(_vanilla('Re'))
    _, root_off = next((s, o) for s, o in cv._iter_roots(buf)
                       if cv._is_skeleton_root(s))
    # Give the root a bogus sibling pointing back at its own child subtree:
    # the walk then visits far more bones than the reference stream holds,
    # which is a guaranteed lockstep failure. (Merely truncating the tree is
    # NOT reliably detected -- the walker just ends early, matching the
    # original .exe's behaviour.)
    child_ptr = buf[root_off + 8:root_off + 12]
    assert child_ptr != b'\x00\x00\x00\x00'
    buf[root_off + 12:root_off + 16] = child_ptr
    before = bytes(buf)
    changed, notes = fn.neutralize_dat_bytes(buf)
    assert not changed
    assert any('skipped' in n for n in notes), notes
    assert bytes(buf) == before


def test_zip_roundtrip_preserves_everything_else(tmp_path):
    src = tmp_path / 'PlCaRe_mod.zip'
    fake_csp = b'\x89PNG not really'
    with zipfile.ZipFile(src, 'w') as zf:
        zf.writestr('PlCaReMod.dat', _vanilla('Re'))
        zf.writestr('csp.png', fake_csp)
    vault_md5 = _md5(src.read_bytes())

    out = fn.convert_falcon_zip(src, temp_dir=tmp_path)
    assert out is not None
    try:
        # Hard constraint: the vault zip is byte-identical afterwards
        assert _md5(src.read_bytes()) == vault_md5
        with zipfile.ZipFile(out) as zf:
            assert zf.namelist() == ['PlCaReMod.dat', 'csp.png']
            assert zf.read('csp.png') == fake_csp
            converted = bytearray(zf.read('PlCaReMod.dat'))
        assert 'PlyCaptain5K_Share_joint' in _root_symbols(converted)
        assert not cv.check_bytes(converted, apply_fix=False)[0]
    finally:
        out.unlink()


def test_zip_already_neutral_passes_through(tmp_path):
    src = tmp_path / 'PlCaNr_mod.zip'
    with zipfile.ZipFile(src, 'w') as zf:
        zf.writestr('PlCaNrMod.dat', _vanilla('Nr'))
        zf.writestr('csp.png', b'png')
    assert fn.convert_falcon_zip(src, temp_dir=tmp_path) is None


def test_corrupt_zip_fails_open(tmp_path):
    src = tmp_path / 'broken.zip'
    src.write_bytes(b'this is not a zip')
    assert fn.convert_falcon_zip(src, temp_dir=tmp_path) is None


def test_neutralize_resolves_reference_through_ref_dir(tmp_path, monkeypatch):
    """Frozen builds ship the bundled CostumeValidator/bin EMPTY (the tables
    are Nintendo data, derived from the user's ISO into storage instead), so
    the neutral reference must resolve through ref_dir() -- env override,
    then the backend's provider. Resolving via the static REF_DIR constant
    made neutralize silently fail-open on every packaged install while every
    dev checkout and test run passed (the 0.7.0 bug)."""
    derived = tmp_path / 'bone-refs'
    derived.mkdir()
    (derived / fn.NR_REF_NAME).write_bytes(
        (cv.BUNDLED_REF_DIR / fn.NR_REF_NAME).read_bytes())
    empty_bundled = tmp_path / 'empty-bundled'
    empty_bundled.mkdir()

    monkeypatch.delenv('NUCLEUS_BONE_REF_DIR', raising=False)
    monkeypatch.setattr(cv, 'BUNDLED_REF_DIR', empty_bundled)
    # Put back the provider core.config registered, not None: None leaves every
    # later validation in this worker on the in-tree tables instead.
    previous = cv._ref_dir_provider
    cv.set_ref_dir_provider(lambda: derived)
    try:
        buf = bytearray(_vanilla('Re'))
        changed, notes = fn.neutralize_dat_bytes(buf)
        assert changed, notes
        assert 'PlyCaptain5K_Share_joint' in _root_symbols(buf)
    finally:
        cv.set_ref_dir_provider(previous)
