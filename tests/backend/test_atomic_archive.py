import threading
import uuid
import shutil
import zipfile
from pathlib import Path

import pytest

import core.atomic_archive as atomic_archive


@pytest.fixture
def tmp_path():
    root = Path(__file__).parent / '.tmp-vault-consistency'
    path = root / uuid.uuid4().hex
    path.mkdir(parents=True)
    yield path
    assert path.parent.resolve() == root.resolve()
    shutil.rmtree(path)


def _write_zip(path, members):
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in members.items():
            archive.writestr(name, data)


def test_replace_failure_preserves_original_archive_bytes(tmp_path, monkeypatch):
    archive_path = tmp_path / 'costume.zip'
    _write_zip(archive_path, {'fighter.dat': b'original'})
    original = archive_path.read_bytes()

    def rewrite(source, destination):
        destination.writestr('fighter.dat', b'changed')

    def fail_replace(source, destination):
        raise OSError('injected publication failure')

    monkeypatch.setattr(atomic_archive.os, 'replace', fail_replace)
    with pytest.raises(OSError, match='publication failure'):
        atomic_archive.rewrite_zip_atomic(archive_path, rewrite)

    assert archive_path.read_bytes() == original
    assert list(tmp_path.glob('costume.zip.*.tmp')) == []


def test_concurrent_archive_edits_both_survive(tmp_path):
    archive_path = tmp_path / 'costume.zip'
    _write_zip(archive_path, {'fighter.dat': b'base'})
    barrier = threading.Barrier(2)
    errors = []

    def add_member(name):
        try:
            barrier.wait(timeout=5)
            def rewrite(source, destination):
                for item in source.infolist():
                    destination.writestr(item, source.read(item.filename))
                destination.writestr(name, name.encode())
            atomic_archive.rewrite_zip_atomic(archive_path, rewrite)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=add_member, args=(name,))
               for name in ('csp.png', 'stc.png')]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert not errors
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {'fighter.dat', 'csp.png', 'stc.png'}
