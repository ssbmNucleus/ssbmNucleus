"""
Guards the wrapper seam between `validate_for_slippi()` and the costume
validator -- the layer the "Fix" button actually goes through.

test_costume_validator.py already proves the validator itself corrects bones
correctly. What went unguarded was the wrapper around it, and both halves broke
when the .exe was replaced by the pure-Python validator:

  * the exe fixed in place unconditionally, so the wrapper could ask for a
    check (`auto_fix=False`) and still get a corrected file back to copy over
    the original. The Python one only writes when asked, so the wrapper copied
    back untouched bytes and reported `fix_applied: True` anyway -- every
    "Fix" was a silent no-op that then marked the costume Slippi-safe.
  * the wrapper's self-copy guard renamed its temp copy `_temp_PlMsNr.dat`,
    which fails the validator's Pl-prefix gate, so any DAT already carrying its
    proper Melee name was skipped entirely.

Both are only visible end-to-end: the return dict alone looked fine. These
tests assert against the bytes on disk instead.
"""
from tests.paths import BACKEND
import hashlib
import shutil
import sys
from pathlib import Path

import pytest

BACKEND_DIR = BACKEND
NUCLEUS_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(NUCLEUS_DIR / 'utility' / 'tools' / 'processor'))
sys.path.insert(0, str(NUCLEUS_DIR / 'utility' / 'tools' / 'services'))

cv = pytest.importorskip('costume_validator')
dat_processor = pytest.importorskip('dat_processor')

VANILLA_DAT = NUCLEUS_DIR / 'utility' / 'assets' / 'vanilla' / 'Fox' / 'PlFxNr' / 'PlFxNr.dat'

pytestmark = pytest.mark.skipif(not VANILLA_DAT.exists(),
                                reason='vanilla assets not present')


def _md5(path):
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def _is_unsafe(path):
    """True when at least one bone still differs from vanilla."""
    changed, _ = cv.check_bytes(bytearray(Path(path).read_bytes()), apply_fix=False)
    return changed


@pytest.fixture
def unsafe_costume(tmp_path):
    """A real costume with one bone transform knocked off vanilla.

    Returns a factory so a test can choose the on-disk filename: the import and
    retest routes hand over a `tmpXXXX.dat` scratch file, but other callers pass
    a DAT that already has its proper Melee name, and that difference used to
    select between two different bugs.
    """
    buf = bytearray(VANILLA_DAT.read_bytes())
    _, root_off = next((s, o) for s, o in cv._iter_roots(buf)
                       if cv._is_skeleton_root(s))
    buf[root_off + 20] ^= 0x10  # perturb the root bone's rotation
    assert cv.check_bytes(bytearray(buf), apply_fix=False)[0], \
        'fixture must start out Slippi-unsafe'

    def make(filename):
        d = tmp_path / filename.replace('.', '_')
        d.mkdir()
        p = d / filename
        p.write_bytes(buf)
        return p
    return make


@pytest.mark.parametrize('filename', [
    'tmpa1b2c3d4.dat',  # what import/retest hand over (NamedTemporaryFile)
    'PlFxNr.dat',       # already the proper Melee name
])
def test_auto_fix_actually_rewrites_the_file(unsafe_costume, filename):
    dat = unsafe_costume(filename)
    before = _md5(dat)

    result = dat_processor.validate_for_slippi(str(dat), auto_fix=True)

    assert result['fix_applied'] is True
    assert result['slippi_safe'] is True
    # The claim above must be backed by the bytes, not just the dict.
    assert _md5(dat) != before, 'auto_fix reported success without writing anything'
    assert not _is_unsafe(dat), 'file is still Slippi-unsafe after a reported fix'


@pytest.mark.parametrize('filename', ['tmpa1b2c3d4.dat', 'PlFxNr.dat'])
def test_check_only_reports_the_problem_and_touches_nothing(unsafe_costume, filename):
    dat = unsafe_costume(filename)
    before = _md5(dat)

    result = dat_processor.validate_for_slippi(str(dat), auto_fix=False)

    assert result['needs_fix'] is True, 'unsafe costume must be reported as needing a fix'
    assert result['fix_applied'] is False
    assert result['slippi_safe'] is False
    assert _md5(dat) == before, 'a check must never modify the original'


@pytest.mark.parametrize('filename', ['tmpa1b2c3d4.dat', 'PlFxNr.dat'])
def test_already_safe_costume_is_left_alone(tmp_path, filename):
    d = tmp_path / 'safe'
    d.mkdir()
    dat = d / filename
    shutil.copy2(VANILLA_DAT, dat)
    before = _md5(dat)

    result = dat_processor.validate_for_slippi(str(dat), auto_fix=True)

    assert result['slippi_safe'] is True
    assert result['needs_fix'] is False
    assert result['fix_applied'] is False
    assert _md5(dat) == before


def test_unreachable_verdict_is_an_error_not_an_unsafe_verdict(tmp_path):
    """A validator that never reaches a verdict (unreadable DAT, unmatched
    symbol, crashed helper) must not be reported as a plain "unsafe" costume:
    that offers the user a Fix which has nothing to fix, so clicking it changes
    nothing and reports nothing. This is the shape the bug report hit.
    """
    junk = tmp_path / 'PlXxNr.dat'
    junk.write_bytes(b'not a DAT at all' * 64)

    result = dat_processor.validate_for_slippi(str(junk), auto_fix=True)

    assert result['slippi_safe'] is False
    assert result['needs_fix'] is False
    assert result['fix_applied'] is False
    assert result.get('error'), 'a failed check must be distinguishable from "unsafe"'


def test_retest_route_reports_a_failed_check_instead_of_marking_unsafe(vault, monkeypatch):
    """The route must surface the failure and leave the stored status alone,
    rather than recording a guess the user cannot act on."""
    from vault.routes import storage_costumes
    from vault.routes.storage_costumes import slippi as costume_slippi

    vault.write({'characters': {'Marth': {'skins': [
        {'id': 'lucina', 'character': 'Marth', 'color': 'Default',
         'slippi_safe': True, 'slippi_tested': True},
    ]}}})
    zip_path = vault.path('Marth', 'lucina.zip')
    import zipfile as _zip
    with _zip.ZipFile(zip_path, 'w') as z:
        z.writestr('PlMsNr.dat', b'unreadable')

    monkeypatch.setattr(costume_slippi, 'validate_for_slippi',
                        lambda *a, **k: {'is_valid': False, 'needs_fix': False,
                                         'fix_applied': False, 'slippi_safe': False,
                                         'error': 'validator did not run',
                                         'output': 'validator did not run'})

    client = vault.client(storage_costumes, 'storage_costumes_bp')
    resp = client.post('/api/mex/storage/costumes/retest-slippi',
                       json={'character': 'Marth', 'skinId': 'lucina', 'autoFix': True})

    assert resp.status_code == 500
    body = resp.get_json()
    assert body['success'] is False
    assert 'validator did not run' in body['error']
    # The previous verdict must survive a check that never ran.
    skins = vault.read()['characters']['Marth']['skins']
    assert skins[0]['slippi_safe'] is True


def test_no_temp_artifacts_left_beside_the_original(unsafe_costume):
    """The temp copy used to land next to the input; a crash could strand it
    inside the user's vault folder."""
    dat = unsafe_costume('PlFxNr.dat')
    dat_processor.validate_for_slippi(str(dat), auto_fix=True)
    assert [p.name for p in dat.parent.iterdir()] == ['PlFxNr.dat']
