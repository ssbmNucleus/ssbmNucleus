"""Exercise scan lifecycle and real disc extraction without touching a vault."""
import struct
import zipfile
from contextlib import nullcontext

import pytest
from flask import Flask
from core import jobs

from vault.routes import iso_scan
from vault.importing import iso_scanner as scanner
import vault.importing.iso_known_hashes as known_hashes


def mini_iso(path, content=b'test costume bytes'):
    """Small GC image with a real FST, DOL header and one costume file."""
    fst = (struct.pack('>III', 0x01000000, 0, 2)
           + struct.pack('>III', 0, 0x4000, len(content)) + b'PlFxNr.dat\0')
    disc = bytearray(0x4000 + len(content))
    disc[:6] = b'GALE01'
    struct.pack_into('>III', disc, 0x420, 0x2800, 0x3000, len(fst))
    disc[0x3000:0x3000 + len(fst)] = fst
    disc[0x4000:] = content
    path.write_bytes(disc)
    return path, content


@pytest.fixture
def isolated_scan(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, '_root_override', tmp_path / 'records')
    monkeypatch.setattr(jobs, '_jobs', {})
    monkeypatch.setattr(scanner, 'SCAN_WORK_ROOT', tmp_path / 'scans')
    monkeypatch.setattr(scanner, '_load_vault_hashes', lambda: {})
    monkeypatch.setattr(scanner, '_load_vanilla_hashes', lambda: set())
    monkeypatch.setattr(scanner, '_build_stock_maps', lambda *_: {})
    monkeypatch.setattr(scanner, '_build_csp_maps', lambda *_: {})
    monkeypatch.setattr(scanner, '_detect_diet_sources', lambda *_: set())
    monkeypatch.setattr(scanner, 'active_pool', lambda **_: nullcontext())
    return tmp_path


def run_scan(root, paths):
    from unittest.mock import patch
    events = []
    with patch.object(jobs, '_emit', lambda job: events.append(job.snapshot())):
        record = jobs.run_inline(scanner.SCAN_KIND, lambda job: scanner.run_scan(job, paths))
    return record, events


def test_scan_uses_native_reader_without_wit(isolated_scan, monkeypatch):
    iso, content = mini_iso(isolated_scan / 'valid.iso')
    # A known vanilla hash skips rendering but still exercises the real reader
    # and scan pipeline, including the costume file enumeration/hash filter.
    monkeypatch.setattr(scanner, '_load_vanilla_hashes', lambda: {known_hashes._md5(content)})
    job, events = run_scan(isolated_scan, [iso])
    assert job['status'] == 'done', job['error']
    assert job['result']['stats']['total_files'] == 1
    assert job['result']['stats']['vanilla'] == 1
    assert events[-1]['status'] == 'done'
    assert (scanner.SCAN_WORK_ROOT / job['id'] / 'extracted' / 'valid' / 'files' / 'PlFxNr.dat').read_bytes() == content


def test_empty_scan_never_starts_thumbnail_workers(isolated_scan, monkeypatch):
    iso, content = mini_iso(isolated_scan / 'vanilla.iso')
    monkeypatch.setattr(scanner, '_load_vanilla_hashes', lambda: {known_hashes._md5(content)})

    def unexpected_work(*args, **kwargs):
        raise AssertionError('Empty scan started thumbnail preparation')

    monkeypatch.setattr(scanner, 'active_pool', unexpected_work)
    monkeypatch.setattr(scanner, '_detect_diet_sources', unexpected_work)
    job, events = run_scan(isolated_scan, [iso])
    assert job['status'] == 'done', job['error']
    assert job['result']['total_new'] == 0
    assert not any(data['extra'].get('phase') == 'csp' for data in events)


def test_vault_previews_resolve_original_and_stored_hashes(monkeypatch, tmp_path):
    from core import metadata
    storage = tmp_path / 'storage'
    char = storage / 'C. Falcon'
    char.mkdir(parents=True)
    (char / 'custom portrait.png').write_bytes(b'portrait')
    with zipfile.ZipFile(char / 'saved-costume.zip', 'w') as archive:
        archive.writestr('PlCaNr.dat', b'fixed costume')
    monkeypatch.setattr(known_hashes, 'STORAGE_PATH', storage)
    monkeypatch.setattr(metadata, 'load_metadata', lambda **_: {'characters': {
        'C. Falcon': {'skins': [{'id': 'captain', 'filename': 'saved-costume.zip',
            'color': 'Captain', 'dat_hash': 'original', 'csp_filename': 'custom portrait.png'}]}}})
    index = scanner._load_vault_hashes()
    assert index['original'] == index[known_hashes._md5(b'fixed costume')]
    assert index['original']['csp_url'] == '/storage/C.%20Falcon/custom%20portrait.png'
    assert index['original']['name'] == 'Captain'


def test_existing_skin_previews_are_unique_and_vanilla_stays_hidden(isolated_scan, monkeypatch):
    iso, content = mini_iso(isolated_scan / 'first.iso')
    second, _ = mini_iso(isolated_scan / 'second.iso')
    vanilla, vanilla_bytes = mini_iso(isolated_scan / 'vanilla.iso', b'vanilla costume')
    preview = {'id': 'fox', 'character': 'Fox', 'name': 'Cool Fox', 'csp_url': '/storage/Fox/fox_csp.png'}
    monkeypatch.setattr(scanner, '_load_vault_hashes', lambda: {
        known_hashes._md5(content): preview, known_hashes._md5(vanilla_bytes): {**preview, 'id': 'vanilla'}})
    monkeypatch.setattr(scanner, '_load_vanilla_hashes', lambda: {known_hashes._md5(vanilla_bytes)})
    job, _ = run_scan(isolated_scan, [iso, second, vanilla])
    assert job['status'] == 'done', job['error']
    assert job['result']['stats']['existing'] == 2
    assert job['result']['stats']['vanilla'] == 1
    assert job['result']['skipped_vault'] == [{**preview, 'source_iso': 'first'}]


def test_slippi_equivalent_vault_skin_keeps_its_preview(isolated_scan, monkeypatch):
    class Parser:
        def __init__(self, path): pass
        def read_dat(self): pass
        def is_character_costume(self): return True
        def detect_character(self): return 'Fox', 'PlyFox5K_Share_joint'
        def get_character_filename(self): return 'PlFxNr.dat'

    iso, _ = mini_iso(isolated_scan / 'unfixed.iso')
    preview = {'id': 'fox', 'character': 'Fox', 'name': 'Cool Fox', 'csp_url': '/storage/Fox/fox_csp.png'}
    monkeypatch.setattr(scanner, 'DATParser', Parser)
    monkeypatch.setattr(scanner, '_load_vault_hashes', lambda: {'fixed': preview})
    monkeypatch.setattr(scanner, '_slippi_fixed_hash', lambda _: 'fixed')
    job, _ = run_scan(isolated_scan, [iso])
    assert job['status'] == 'done', job['error']
    assert job['result']['stats']['slippi_matched'] == 1
    assert job['result']['skipped_vault'] == [{**preview, 'source_iso': 'unfixed'}]


@pytest.mark.parametrize('count, workers', [(1, 1), (2, 2), (8, 4)])
def test_thumbnail_workers_match_work_and_report_each_preview(isolated_scan, monkeypatch, count, workers):
    class Parser:
        def __init__(self, path): pass
        def read_dat(self): pass
        def is_character_costume(self): return True
        def detect_character(self): return 'Fox', 'PlyFox5K_Share_joint'
        def get_character_filename(self): return 'PlFxNr.dat'

    monkeypatch.setattr(scanner, 'DATParser', Parser)
    monkeypatch.setattr(scanner, '_slippi_fixed_hash', lambda _: None)
    monkeypatch.setattr(scanner, 'CSP_PARALLELISM', 4)
    pools = []
    monkeypatch.setattr(scanner, 'active_pool', lambda **options: pools.append(options) or nullcontext())
    monkeypatch.setattr(scanner, '_build_candidate', lambda *args: (None, None))
    isos = [mini_iso(isolated_scan / f'new-{i}.iso', f'costume {i}'.encode())[0] for i in range(count)]
    job, events = run_scan(isolated_scan, isos)
    assert job['status'] == 'done', job['error']
    assert pools == [{'workers': workers, 'enabled': False if count == 1 else None}]
    previews = [data['extra'] for data in events if data['status'] == 'running' and data['extra'].get('phase') == 'csp' and data['progress'] < 1]
    assert [p['phase_current'] for p in previews] == list(range(count + 1))
    assert all(p['phase_total'] == count for p in previews)
    assert job['extra']['phase_current'] == count


def test_failed_extraction_is_an_error_not_an_empty_success(isolated_scan, monkeypatch):
    iso = isolated_scan / 'broken.iso'
    iso.write_bytes(b'not a disc')
    job, events = run_scan(isolated_scan, [iso])
    assert job['status'] == 'failed'
    assert 'extract' in job['error'].lower()
    assert 'broken.iso' in job['error']
    assert events[-1]['status'] == 'failed'


def test_partial_extraction_keeps_results_and_reports_failed_iso(isolated_scan, monkeypatch):
    iso, content = mini_iso(isolated_scan / 'valid.iso')
    bad = isolated_scan / 'broken.iso'
    bad.write_bytes(b'not a disc')
    monkeypatch.setattr(scanner, '_load_vanilla_hashes', lambda: {known_hashes._md5(content)})
    job, _ = run_scan(isolated_scan, [bad, iso])
    assert job['status'] == 'done', job['error']
    assert job['result']['stats']['vanilla'] == 1
    assert job['result']['extraction_failures'] == ['broken.iso']


def test_preflight_reports_native_reader():
    app = Flask(__name__)
    app.register_blueprint(iso_scan.iso_scan_bp)
    response = app.test_client().get('/api/mex/iso-scan/preflight')
    assert response.status_code == 200
    assert response.json['native_available'] is True
    assert 'wit_available' not in response.json


def test_scan_recovery_cleans_owned_extraction_and_previews(isolated_scan):
    work = scanner.SCAN_WORK_ROOT / 'dead-scan'
    work.mkdir(parents=True)
    (work / 'partial.dat').write_bytes(b'partial')
    record = jobs.Job(scanner.SCAN_KIND, job_id='dead-scan').snapshot()
    record.update(status='running', owner=None, owned={'work_dir': str(work.resolve())})
    jobs._write(record)
    [recovered] = jobs.recover_interrupted()
    assert recovered['status'] == 'interrupted'
    assert recovered['owned'] == {}
    assert not work.exists()


def test_cancelled_scan_cleans_work_and_never_returns_candidates(isolated_scan, monkeypatch):
    iso, _ = mini_iso(isolated_scan / 'cancel.iso')
    def cancelled(job):
        jobs.cancel(job.id)
        return scanner.run_scan(job, [str(iso)])
    record = jobs.run_inline(scanner.SCAN_KIND, cancelled)
    assert record['status'] == 'cancelled'
    assert record['result'] is None
    assert not (scanner.SCAN_WORK_ROOT / record['id']).exists()


def test_scan_routes_use_shared_status_and_cancel(isolated_scan, monkeypatch):
    from shared.routes.jobs import jobs_bp
    iso, content = mini_iso(isolated_scan / 'valid.iso')
    monkeypatch.setattr(scanner, '_load_vanilla_hashes', lambda: {known_hashes._md5(content)})
    app = Flask(__name__)
    app.register_blueprint(iso_scan.iso_scan_bp)
    app.register_blueprint(jobs_bp)
    client = app.test_client()
    record, _ = run_scan(isolated_scan, [iso])
    assert client.get(f"/api/jobs/{record['id']}").json['job']['result'] == record['result']
    assert client.get(f"/api/mex/iso-scan/{record['id']}").status_code == 405
    assert client.post(f"/api/mex/iso-scan/{record['id']}/cancel").status_code == 404
    assert client.delete(f"/api/mex/iso-scan/{record['id']}").json['success']
