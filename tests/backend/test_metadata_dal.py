"""
Unit tests for the core.metadata data-access layer (DAL): atomic save, the
locked metadata_transaction() primitive, and the metadata_lock re-export.

These guard the single seam that the metadata.json -> SQLite migration swaps
behind (see docs/VAULT_SQLITE_MIGRATION.md).
"""
import threading
import json
from pathlib import Path
import uuid
import shutil

import pytest

import core.metadata as cm


@pytest.fixture
def tmp_path():
    root = Path(__file__).parent / '.tmp-vault-consistency'
    path = root / uuid.uuid4().hex
    path.mkdir(parents=True)
    yield path
    assert path.parent.resolve() == root.resolve()
    shutil.rmtree(path)


def test_load_returns_default_when_missing(vault):
    assert cm.load_metadata(default={'characters': {}}) == {'characters': {}}


def test_existing_corrupt_json_raises_and_transaction_preserves_bytes(vault):
    broken = b'{"characters":'
    cm.METADATA_FILE.write_bytes(broken)
    with pytest.raises(cm.MetadataReadError, match='unreadable'):
        with cm.metadata_transaction(default={'characters': {}}) as data:
            data['characters']['Fox'] = {'skins': []}
    assert cm.METADATA_FILE.read_bytes() == broken


def test_concurrent_atomic_saves_use_distinct_temp_files(vault, monkeypatch):
    real_replace = cm.os.replace
    barrier = threading.Barrier(2)
    staged = []

    def synchronized_replace(source, destination):
        staged.append(source)
        real_replace(source, destination)

    monkeypatch.setattr(cm.os, 'replace', synchronized_replace)
    errors = []
    def writer(value):
        try:
            barrier.wait(timeout=5)
            cm.save_metadata({'value': value})
        except Exception as exc:
            errors.append(exc)
    threads = [threading.Thread(target=writer, args=(value,)) for value in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert not errors
    assert len(set(staged)) == 2
    assert json.loads(cm.METADATA_FILE.read_text(encoding='utf-8')) in ({'value': 1}, {'value': 2})


def test_save_is_atomic_and_roundtrips(vault):
    cm.save_metadata({'characters': {'Fox': {'skins': []}}})
    assert cm.load_metadata()['characters']['Fox'] == {'skins': []}
    # no leftover temp file
    assert not (vault.storage / 'metadata.json.tmp').exists()


def test_transaction_commits_on_clean_exit(vault):
    vault.write({'custom_characters': []})
    with cm.metadata_transaction() as data:
        data['custom_characters'].append({'slug': 'wolf'})
    assert vault.read()['custom_characters'] == [{'slug': 'wolf'}]


def test_transaction_uses_default_when_file_missing(vault):
    with cm.metadata_transaction(default={'bundles': []}) as data:
        data['bundles'].append({'id': 'b1'})
    assert vault.read() == {'bundles': [{'id': 'b1'}]}


def test_transaction_does_not_save_on_exception(vault):
    vault.write({'x': 1})
    with pytest.raises(ValueError):
        with cm.metadata_transaction() as data:
            data['x'] = 999          # mutate...
            raise ValueError('boom')  # ...then fail before save
    assert vault.read()['x'] == 1     # original untouched


def test_transaction_serializes_concurrent_appends(vault):
    """The metadata-concurrency guarantee, now via the DAL primitive: N threads
    appending under metadata_transaction lose nothing."""
    vault.write({'items': [{'id': 'seed'}]})
    n = 24
    barrier = threading.Barrier(n)

    def worker(i):
        barrier.wait()
        with cm.metadata_transaction() as data:
            data['items'].append({'id': f'item-{i}'})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ids = {it['id'] for it in vault.read()['items']}
    assert 'seed' in ids
    assert all(f'item-{i}' in ids for i in range(n))
    assert len(vault.read()['items']) == n + 1


def test_metadata_lock_is_reexported_from_state():
    import core.state as cs
    assert cs.metadata_lock is cm.metadata_lock


def test_metadata_lock_is_reentrant():
    # RLock: same thread may acquire twice without deadlocking (transactions nest)
    assert cm.metadata_lock.acquire(blocking=False)
    try:
        assert cm.metadata_lock.acquire(blocking=False)
        cm.metadata_lock.release()
    finally:
        cm.metadata_lock.release()
