"""Test-in-Game retention: newest run stamps and ISOs survive, older ones go."""
import os

from core.run_retention import prune_runs, prune_test_builds


def _stamp(root, name, with_log=True):
    d = root / f'test-{name}'
    d.mkdir()
    (d / 'blob.bin').write_bytes(b'x')
    if with_log:
        (root / f'test-{name}-dolphin.log').write_text('log')


def test_prune_runs_keeps_newest_five_with_logs(tmp_path):
    names = [f'20260101_00000{i}' for i in range(8)]
    for n in names:
        _stamp(tmp_path, n)
    (tmp_path / 'notes.txt').write_text('unrelated')
    removed = prune_runs(tmp_path, keep=5)
    assert len(removed) == 6  # 3 dirs + 3 logs
    for n in names[:3]:
        assert not (tmp_path / f'test-{n}').exists()
        assert not (tmp_path / f'test-{n}-dolphin.log').exists()
    for n in names[3:]:
        assert (tmp_path / f'test-{n}').is_dir()
        assert (tmp_path / f'test-{n}-dolphin.log').is_file()
    assert (tmp_path / 'notes.txt').exists()


def test_prune_runs_handles_suffix_and_missing_log(tmp_path):
    _stamp(tmp_path, '20260101_000000')
    _stamp(tmp_path, '20260101_000000-2', with_log=False)
    _stamp(tmp_path, '20260101_000001')
    prune_runs(tmp_path, keep=2)
    assert not (tmp_path / 'test-20260101_000000').exists()
    assert (tmp_path / 'test-20260101_000000-2').exists()
    assert (tmp_path / 'test-20260101_000001').exists()


def test_prune_runs_never_removes_protected(tmp_path):
    names = [f'20260101_00000{i}' for i in range(4)]
    for n in names:
        _stamp(tmp_path, n)
    prune_runs(tmp_path, keep=1, protect=['test-20260101_000000'])
    assert (tmp_path / 'test-20260101_000000').exists()
    assert (tmp_path / 'test-20260101_000003').exists()
    assert not (tmp_path / 'test-20260101_000001').exists()
    assert not (tmp_path / 'test-20260101_000002').exists()


def test_prune_runs_missing_root_is_noop(tmp_path):
    assert prune_runs(tmp_path / 'nope') == []


def test_prune_test_builds_keeps_newest_two_isos(tmp_path):
    for i in range(4):
        p = tmp_path / f'test_{i}.iso'
        p.write_bytes(b'iso')
        os.utime(p, (1000 + i, 1000 + i))
    (tmp_path / 'proj').mkdir()
    prune_test_builds(tmp_path, keep=2)
    assert sorted(p.name for p in tmp_path.glob('*.iso')) == ['test_2.iso', 'test_3.iso']
    assert (tmp_path / 'proj').is_dir()
