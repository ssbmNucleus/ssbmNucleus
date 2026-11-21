"""An overlapping import must never publish two rows/files with one costume ID."""
from concurrent.futures import ThreadPoolExecutor
import threading
import zipfile

import pytest

import core.metadata as metadata
import vault.importing.unified.characters as characters
import vault.routes.storage_costumes.library as library


@pytest.fixture
def vault(dual_backend):
    return dual_backend


@pytest.fixture
def imports(vault, monkeypatch):
    vault.write({'characters': {}, 'stages': {}})
    monkeypatch.setattr(characters, 'STORAGE_PATH', vault.storage)
    monkeypatch.setattr(characters, 'validate_for_slippi',
                        lambda *a, **k: {'slippi_safe': True})
    monkeypatch.setattr(characters, '_maybe_diet_fix', lambda data, *a, **k: (data, False))

    def run(index):
        path = vault.path(f'upload-{index}.zip')
        payload = f'costume-{index}'.encode()
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('PlLgNr.dat', payload)
        info = {'character': 'Luigi', 'costume_code': 'PlLgNr', 'color': 'Green',
                'dat_file': 'PlLgNr.dat', 'csp_file': None, 'stock_file': None}
        return characters.import_character_costume(str(path), info, 'vibrant_luigi.zip')

    def render(character, code, dat, **kwargs):
        return {'csp': b'portrait-' + dat, 'csp_source': 'imported',
                'stock': b'stock-' + dat, 'stock_source': 'imported'}

    monkeypatch.setattr(characters, 'build_csp_and_stock', render)
    return run, render


def test_overlapping_same_name_imports_keep_distinct_files_and_ids(vault, monkeypatch, imports):
    run, render = imports
    barrier = threading.Barrier(2)

    def simultaneous_render(*args, **kwargs):
        barrier.wait(timeout=10)
        return render(*args, **kwargs)

    monkeypatch.setattr(characters, 'build_csp_and_stock', simultaneous_render)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, [1, 2]))
    assert all(result['success'] for result in results), results
    ids = [result['skin_id'] for result in results]
    assert len(set(ids)) == 2, 'two overlapping imports published the same identity'
    skins = vault.read()['characters']['Luigi']['skins']
    assert {skin['id'] for skin in skins} == set(ids)
    for index, result in zip([1, 2], results):
        sid = result['skin_id']
        payload = f'costume-{index}'.encode()
        with zipfile.ZipFile(vault.path('Luigi', sid + '.zip')) as archive:
            assert archive.testzip() is None
            assert archive.read('PlLgNrMod.dat') == payload
            assert archive.read('csp.png') == b'portrait-' + payload
        assert vault.path('Luigi', sid + '_csp.png').read_bytes() == b'portrait-' + payload
        assert vault.path('Luigi', sid + '_stc.png').read_bytes() == b'stock-' + payload


def test_delete_removes_all_legacy_rows_for_identity(vault):
    sid = 'vibrant-luigi-pllgnr'
    first = {'id': sid, 'color': 'Vibrant', 'filename': sid + '.zip'}
    second = {**first, 'alternate_csps': [{'filename': 'legacy-portrait.png'}]}
    sibling = {'id': sid + '01', 'color': 'Other', 'filename': sid + '01.zip'}
    vault.write({'characters': {'Luigi': {'skins': [first, sibling, second]}}})
    for name in (sid + '.zip', sid + '_csp.png', 'legacy-portrait.png', sid + '01.zip'):
        vault.touch('Luigi', name)
    client = vault.client(library, 'storage_costumes_bp')
    response = client.post('/api/mex/storage/costumes/delete', json={'character': 'Luigi', 'skinId': sid})
    assert response.status_code == 200
    assert vault.read()['characters']['Luigi']['skins'] == [sibling]
    assert not vault.path('Luigi', 'legacy-portrait.png').exists()
    assert vault.path('Luigi', sid + '01.zip').exists()
    assert client.post('/api/mex/storage/costumes/delete',
                       json={'character': 'Luigi', 'skinId': sid}).status_code == 404


def test_reimport_after_delete_can_reuse_identity(vault, imports):
    run, _ = imports
    first = run(1)
    assert first['success']
    client = vault.client(library, 'storage_costumes_bp')
    assert client.post('/api/mex/storage/costumes/delete',
                       json={'character': 'Luigi', 'skinId': first['skin_id']}).status_code == 200
    second = run(2)
    assert second['success']
    assert first['skin_id'] == second['skin_id']
    with zipfile.ZipFile(vault.path('Luigi', second['skin_id'] + '.zip')) as archive:
        assert archive.read('PlLgNrMod.dat') == b'costume-2'


def test_failed_metadata_commit_cleans_archive_and_sidecars(vault, imports, monkeypatch):
    run, _ = imports
    def fail_save(*args, **kwargs):
        raise OSError('catalog write failed')
    monkeypatch.setattr(metadata, 'save_metadata', fail_save)
    result = run(1)
    assert result == {'success': False, 'error': 'catalog write failed'}
    assert list(vault.path('Luigi').iterdir()) == []


def test_failed_render_cleans_private_archive(vault, imports, monkeypatch):
    run, _ = imports
    def fail_render(*args, **kwargs):
        raise RuntimeError('render failed')
    monkeypatch.setattr(characters, 'build_csp_and_stock', fail_render)
    assert run(1) == {'success': False, 'error': 'render failed'}
    assert list(vault.path('Luigi').iterdir()) == []
