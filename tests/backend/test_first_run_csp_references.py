from tests.paths import BACKEND
import json
import sys
from pathlib import Path


BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

from shared.vanilla_extract.first_run_setup import FirstRunSetup


def _write_fighter_json(temp_project, *, missing_costume=False):
    fighters = temp_project / 'data' / 'fighters'
    files = temp_project / 'files'
    fighters.mkdir(parents=True)
    files.mkdir(parents=True)

    fighter = {
        'name': 'Fox',
        'files': {'fighterDataPath': 'PlFx.dat'},
        'costumes': [
            {'file': {'fileName': 'PlFxNr.dat'}},
            # Red Falcon's retail JSON uses a trailing dot for region lookup.
            {'file': {'fileName': 'PlCaRe.'}},
        ],
    }
    (fighters / '000.json').write_text(json.dumps(fighter), encoding='utf-8')
    (files / 'PlFx.dat').write_bytes(b'fighter-data')
    (files / 'PlFxNr.dat').write_bytes(b'normal-costume')
    if not missing_costume:
        (files / 'PlCaRe.usd').write_bytes(b'region-costume')


def _small_setup(tmp_path):
    setup = FirstRunSetup(
        tmp_path / 'project',
        tmp_path / 'mexcli.exe',
        storage_path=tmp_path / 'storage',
    )
    setup.VANILLA_FIGHTER_COUNT = 1
    setup.CSP_REFERENCE_EXTRA_FIGHTER_INDICES = ()
    setup.CSP_REFERENCE_EXPECTED_FILE_COUNT = 3
    setup.CSP_REFERENCE_FTDATA_COUNT = 1
    setup.CSP_REFERENCE_COSTUME_COUNT = 2
    return setup


def test_first_run_copies_complete_csp_reference_bank(tmp_path):
    temp_project = tmp_path / 'temp-project'
    _write_fighter_json(temp_project)
    setup = _small_setup(tmp_path)

    result = setup._copy_csp_reference_dats(temp_project)

    assert result == {'success': True, 'copied': 3}
    assert (setup.csp_reference_dir / 'PlFx.dat').read_bytes() == b'fighter-data'
    assert (setup.csp_reference_dir / 'PlFxNr.dat').read_bytes() == b'normal-costume'
    # A .usd source is normalized to the name generate_csp searches for.
    assert (setup.csp_reference_dir / 'PlCaRe.dat').read_bytes() == b'region-costume'
    manifest = json.loads(setup.csp_reference_manifest.read_text(encoding='utf-8'))
    assert manifest == {
        'version': setup.CSP_REFERENCE_MANIFEST_VERSION,
        'source': 'user-verified-iso',
        'files': ['PlCaRe.dat', 'PlFx.dat', 'PlFxNr.dat'],
    }
    assert setup._csp_reference_bank_status()['complete'] is True
    assert not list(setup.csp_reference_dir.glob('*.setup.tmp'))


def test_first_run_refuses_incomplete_csp_reference_bank(tmp_path):
    temp_project = tmp_path / 'temp-project'
    _write_fighter_json(temp_project, missing_costume=True)
    setup = _small_setup(tmp_path)

    result = setup._copy_csp_reference_dats(temp_project)

    assert result['success'] is False
    assert 'PlCaRe.' in result['error']
    assert not setup.csp_reference_manifest.exists()
    assert setup._csp_reference_bank_status()['complete'] is False


def test_csp_reference_status_detects_deleted_manifest_file(tmp_path):
    temp_project = tmp_path / 'temp-project'
    _write_fighter_json(temp_project)
    setup = _small_setup(tmp_path)
    assert setup._copy_csp_reference_dats(temp_project)['success'] is True

    (setup.csp_reference_dir / 'PlFx.dat').unlink()

    status = setup._csp_reference_bank_status()
    assert status['complete'] is False
    assert 'PlFx.dat' in status['details']
