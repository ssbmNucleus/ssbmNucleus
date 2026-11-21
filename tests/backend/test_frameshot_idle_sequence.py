from types import SimpleNamespace

from devtools.frameshot import expected_shot_files, parse_shot_specs


def test_idle_sequence_has_distinct_cache_frames_and_default_stays_single():
    assert parse_shot_specs(['idle']) == [('idle', [1])]
    shots = parse_shot_specs(['idle:1,3,5'])
    files = expected_shot_files(SimpleNamespace(orbit='0,90'), {'label':'shulk','shots':shots})
    assert len(files) == 6
    assert files[0] == ('shulk-idle-f01.png','idle',1,0.0)
    assert files[-1] == ('shulk-idle-f05-yaw090.png','idle',5,90.0)
    assert len({name for name,_,_,_ in files}) == len(files)


def test_measurement_group_settles_visibility_writes(monkeypatch):
    from contextlib import nullcontext
    from devtools import frameshot as f
    # Each poke initially returns the previous state, then its actual frame.
    frames = iter([b'full', b'full', b'full', b'actor', b'actor',
                   b'actor', b'background', b'background', b'background', b'full', b'full'])
    fresh = SimpleNamespace(grab=lambda *a, **kw: (next(frames), True))
    memory = SimpleNamespace(u32=lambda _: 10)
    monkeypatch.setattr(f, 'hidden_particles', lambda _: nullcontext())
    monkeypatch.setattr(f, 'hidden_fighter', lambda _: nullcontext())
    monkeypatch.setattr(f, 'camera_state', lambda _: dict(camera=1))
    png, _, info = f.measured_capture(fresh, memory, None, lambda *a: None, '404040', 42, log=lambda *_: None)
    assert png == b'full' and info['group_consistent']
    assert info['actor_png'] == b'actor' and info['background_png'] == b'background'
    assert all(info['state_settled'].values())
