"""Review JJ, finding 9: the holding area between the preview and the import.

The first version named held objects after public post metadata, so two
preparations of the same post shared a pathname: they collided, and checking
the older hash deleted the newer object. Its cap counted objects rather than
bytes and only ran when something else happened, so 26 sequential holds left
25 under a limit of 24. These cover the replacement.
"""
import hashlib

import pytest

from randall.website import website_quarantine as q


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.setattr(q, '_STARTED', False)
    monkeypatch.setattr('core.config.SCRATCH_PATH', tmp_path)
    q._root()          # the startup sweep runs once per process
    yield
    monkeypatch.setattr(q, '_STARTED', False)


def _file(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_a_hold_is_a_random_capability_not_a_name_anyone_can_derive(tmp_path):
    one, _ = q.hold(_file(tmp_path, 'a.bin', b'one'), owner='post:1')
    two, _ = q.hold(_file(tmp_path, 'b.bin', b'one'), owner='post:1')
    assert one != two and len(one) == 32
    # Identical bytes, identical owner, still two independent objects.
    assert q.held(one, owner='post:1').read_bytes() == b'one'
    assert q.held(two, owner='post:1').read_bytes() == b'one'


def test_two_preparations_of_the_same_post_do_not_collide(tmp_path):
    """The reproduced collision: the older hash check deleted the newer object."""
    older, older_hash = q.hold(_file(tmp_path, 'a.bin', b'older'), owner='post:1:v1')
    newer, newer_hash = q.hold(_file(tmp_path, 'b.bin', b'newer'), owner='post:1:v1')
    assert q.held(older, older_hash, owner='post:1:v1') is not None
    assert q.held(newer, newer_hash, owner='post:1:v1').read_bytes() == b'newer'
    # Asking the OLDER hold for the newer hash answers no, and leaves both.
    assert q.held(older, newer_hash, owner='post:1:v1') is None
    assert q.held(newer, newer_hash, owner='post:1:v1') is not None


def test_another_owner_is_refused_and_the_object_is_left_alone(tmp_path):
    token, digest = q.hold(_file(tmp_path, 'a.bin', b'mine'), owner='post:1:v1')
    assert q.held(token, digest, owner='post:2:v1') is None
    assert q.held(token, digest, owner='post:1:v1').read_bytes() == b'mine'


def test_replaced_bytes_stop_being_the_held_object(tmp_path):
    token, digest = q.hold(_file(tmp_path, 'a.bin', b'approved'), owner='o')
    q.held(token, digest, owner='o').write_bytes(b'substituted')
    assert q.held(token, digest, owner='o') is None


def test_the_hash_is_the_one_recorded_at_hold_time(tmp_path):
    payload = b'bytes'
    token, digest = q.hold(_file(tmp_path, 'a.bin', payload), owner='o')
    assert digest == hashlib.sha256(payload).hexdigest()


def test_publication_leaves_no_partial_file(tmp_path):
    token, _ = q.hold(_file(tmp_path, 'a.bin', b'x' * 4096), owner='o')
    assert not list(q._root().glob('*.partial'))


def test_capacity_counts_objects_and_admits_nothing_beyond_it(tmp_path, monkeypatch):
    monkeypatch.setattr(q, 'MAX_HELD', 4)
    tokens = [q.hold(_file(tmp_path, f'{i}.bin', bytes([i])), owner='o')[0]
              for i in range(8)]
    live = [t for t in tokens if q.held(t, owner='o') is not None]
    # The cap is a cap: the incoming object is counted BEFORE it is admitted,
    # so the holding area never sits one over it.
    assert len(live) <= q.MAX_HELD
    assert len(list(q._root().glob('*.bin'))) <= q.MAX_HELD


def test_capacity_counts_bytes_too(tmp_path, monkeypatch):
    monkeypatch.setattr(q, 'MAX_HELD_BYTES', 8192)
    for i in range(4):
        q.hold(_file(tmp_path, f'{i}.bin', b'y' * 3000), owner='o')
    held = sum(p.stat().st_size for p in q._root().glob('*.bin'))
    assert held <= q.MAX_HELD_BYTES


def test_an_object_larger_than_the_whole_area_is_refused_not_admitted(tmp_path, monkeypatch):
    monkeypatch.setattr(q, 'MAX_HELD_BYTES', 1024)
    with pytest.raises(ValueError, match='too large to hold'):
        q.hold(_file(tmp_path, 'big.bin', b'z' * 4096), owner='o')
    assert not list(q._root().glob('*.bin'))


def test_expired_objects_are_dropped_by_the_next_hold(tmp_path, monkeypatch):
    stale, digest = q.hold(_file(tmp_path, 'a.bin', b'old'), owner='o')
    monkeypatch.setattr(q, 'TTL_SECONDS', -1)
    assert q.held(stale, digest, owner='o') is None
    q.hold(_file(tmp_path, 'b.bin', b'new'), owner='o')
    assert not (q._root() / f'{stale}.bin').exists()


def test_startup_clears_objects_left_by_a_previous_run(tmp_path, monkeypatch):
    token, _ = q.hold(_file(tmp_path, 'a.bin', b'left over'), owner='o')
    assert (q._root() / f'{token}.bin').exists()
    monkeypatch.setattr(q, '_STARTED', False)          # a fresh process
    q._root()
    assert not (q._root() / f'{token}.bin').exists()


def test_release_removes_both_halves_and_never_raises(tmp_path):
    token, _ = q.hold(_file(tmp_path, 'a.bin', b'x'), owner='o')
    q.release(token)
    assert not list(q._root().glob(f'{token}.*'))
    q.release(token)                  # again
    q.release('not a token')          # and nonsense
