import configparser
from types import SimpleNamespace

import pytest

from shared.ingame import boot, interactive, match_setup, runner
from shared.ingame.char_select import ckind
from shared.ingame.melee_sss import INTERNAL_STAGE_ID


@pytest.mark.parametrize('device', ['6', '12'])
def test_interactive_profile_preserves_port1_and_maps_pipe_to_port4(tmp_path, device):
    config = tmp_path / 'Config'
    config.mkdir()
    (config / 'Dolphin.ini').write_text(f'[Core]\nSIDevice0 = {device}\nSIDevice3 = 12\n', encoding='utf-8')
    (config / 'GCPadNew.ini').write_text('[GCPad1]\nDevice = XInput/2/Gamepad\nButtons/A = `Button A`\nMain Stick/Up = `Left Y+`\n', encoding='utf-8')
    boot._patch_dolphin_ini(str(tmp_path), 'slippibot7', interactive=True)
    dolphin = configparser.ConfigParser()
    dolphin.read(config / 'Dolphin.ini', encoding='utf-8')
    pads = configparser.ConfigParser()
    pads.read(config / 'GCPadNew.ini', encoding='utf-8')
    assert dolphin['Core']['SIDevice0'] == device
    assert dolphin['Core']['SIDevice3'] == '6'
    assert dict(pads['GCPad1']) == {'device': 'XInput/2/Gamepad', 'buttons/a': '`Button A`', 'main stick/up': '`Left Y+`'}
    assert pads['GCPad4']['Device'] == 'Pipe/0/slippibot7'
    assert pads['GCPad4']['Buttons/A'] == 'Button A'


def test_disabled_port1_is_actionable_and_does_not_get_overwritten(tmp_path):
    config = tmp_path / 'Config'
    config.mkdir()
    path = config / 'Dolphin.ini'
    original = b'[Core]\nSIDevice0 = 0\n'
    path.write_bytes(original)
    with pytest.raises(ValueError, match='port 1 in Slippi'):
        boot._patch_dolphin_ini(str(tmp_path), 'slippibot1', interactive=True)
    assert path.read_bytes() == original


@pytest.mark.parametrize('mapping', ['', 'Pipe/0/slippibot1'])
def test_standard_port1_needs_native_mapping(tmp_path, mapping):
    config = tmp_path / 'Config'
    config.mkdir()
    (config / 'Dolphin.ini').write_text('[Core]\nSIDevice0 = 6\n', encoding='utf-8')
    (config / 'GCPadNew.ini').write_text(f'[GCPad1]\nDevice = {mapping}\n', encoding='utf-8')
    with pytest.raises(ValueError, match='port-1 controller mapping'):
        boot._patch_dolphin_ini(str(tmp_path), 'slippibot1', interactive=True)


def test_prepare_edits_only_throwaway_profile(monkeypatch, tmp_path):
    template = tmp_path / 'real-user'
    config = template / 'Config'
    config.mkdir(parents=True)
    originals = {
        'Dolphin.ini': b'[Core]\nSIDevice0 = 6\nSIDevice3 = 12\n',
        'GCPadNew.ini': b'[GCPad1]\nDevice = XInput/0/Gamepad\nButtons/A = `Button A`\n',
    }
    for name, data in originals.items(): (config / name).write_bytes(data)
    monkeypatch.setattr(boot, 'resolve_dolphin', lambda _: ('fake-dolphin', str(template)))
    instance = boot.DolphinBoot('fake.iso', 'fake', tmp_path / 'runs', pipe_index=7, interactive=True)
    instance.prepare()
    for name, data in originals.items(): assert (config / name).read_bytes() == data
    copied = (instance.user_dir / 'Config' / 'GCPadNew.ini').read_text(encoding='utf-8')
    assert 'Device = XInput/0/Gamepad' in copied
    assert 'Device = Pipe/0/slippibot7' in copied


@pytest.mark.parametrize('manifest,fighter,color,stage', [
    ({'costume': {'fighter': 'luigi', 'colorIndex': 3}}, ckind('luigi'), 3, 'battlefield'),
    ({'character': {'name': 'Custom', 'colorIndex': 2, 'cssIcon': {'fighter': 47}}}, 47, 2, 'battlefield'),
    ({'customStage': {'sssIcon': {'stageId': 65}}}, ckind('mario'), 0, 65),
    ({'das': {'stage': 'dreamland', 'button': 'X', 'defaultVariant': True}}, ckind('mario'), 0, 'dreamland'),
])
def test_preview_uses_requested_target_without_variant_button(manifest, fighter, color, stage):
    plan = interactive.preview_plan(manifest)
    assert plan['fighter'] == fighter and plan['color'] == color
    assert plan['stage_id'] == (INTERNAL_STAGE_ID[stage] if isinstance(stage, str) else stage)
    assert plan['hold'] is None


def test_preview_rejects_unresolved_target_and_unproven_das_selection():
    with pytest.raises(ValueError, match='selected fighter'):
        interactive.preview_plan({'character': {'name': 'Missing fighter id'}})
    with pytest.raises(ValueError, match='selected stage'):
        interactive.preview_plan({'customStage': {'sssIcon': {}}})
    with pytest.raises(ValueError, match='default variant'):
        interactive.preview_plan({'das': {'stage': 'battlefield', 'button': 'X'}})


class Event:
    def __init__(self):
        self.stopped = False
        self.now = 0
        self.on_wait = lambda: None

    def is_set(self): return self.stopped
    def set(self): self.stopped = True
    def wait(self, seconds):
        self.now += seconds
        self.on_wait()
        return self.stopped


def fixture(monkeypatch, event):
    calls, states, values = [], [], {
        match_setup.HOOK_1P: match_setup.HOOK_1P_ORIG,
        0x80479D30: 2, 0x80479D33: 0,
        match_setup.PLAYER_BLOCK + 0xB0: 0x80001000,
        0x8000102C: 0x80002000,
    }
    alive = [True]

    class Boot:
        pid = 42
        def __init__(self, *_a, interactive, stop_event, render_size, **_k):
            assert interactive and stop_event is event
            assert render_size == (1280, 960) and _k.get('internal_res') == 2  # playable preview renders big + supersampled
        def check_cancelled(self):
            if event.is_set(): raise boot.DolphinBootCancelled()
        def check_graphics_startup(self): self.check_cancelled()
        def prepare(self): self.check_cancelled(); calls.append('prepare')
        def launch(self): self.check_cancelled(); calls.append('launch')
        def alive(self): return alive[0]
        def wait_for_pipe(self, **_): return True
        def open_pipe(self): return SimpleNamespace(neutral=lambda: calls.append('neutral'), close=lambda: calls.append('close-pipe'))
        def cleanup(self): calls.append('cleanup')

    class Memory:
        def __init__(self, _): pass
        def locate(self): return True
        def close(self): calls.append('close-memory')
        def u8(self, address): return values.get(address, 0)
        def u32(self, address):
            if address == interactive.FRAME_COUNTER:
                return int(event.now * values.get('fps', 60))
            return values.get(address, 0)
        def deref(self, address):
            assert address == interactive.nav.CSS_CURSOR_PTR + 4 * 3
            return values.get('cursor', 0x80003000) if event.now >= 0.2 else None
        def write_u8(self, address, value):
            values[address] = value
            if address == match_setup.LOOP_BREAK:
                calls.append(('warp', event.now))
                # Scene flags become visible before CSS setup completes. A
                # premature transition is lost when initialization resets it.
                if event.now * values.get('fps', 60) >= 90:
                    values[interactive.nav.SCENE_MINOR] = 1
                else:
                    values[address] = 0
                    values[match_setup.CSS_PLAYERS] = 0xFF
        def write_u32(self, address, value): values[address] = value

    class Stage:
        def __init__(self, *_): pass
        def wait_for_stage_select(self, **_):
            return values[interactive.nav.SCENE_MINOR] == 1
        def force_select(self, stage, hold=None):
            calls.append(('stage', stage, hold))
            values[0x80479D33] = 2
            return True

    monkeypatch.setattr(interactive, 'DolphinBoot', Boot)
    monkeypatch.setattr(interactive, 'Dolphin', Memory)
    monkeypatch.setattr(interactive, 'StageCursor', Stage)
    monkeypatch.setattr(interactive, 'time', SimpleNamespace(monotonic=lambda: event.now))
    monkeypatch.setattr(interactive.nav, 'nav_to_css', lambda *_a, check_startup, **_k: (check_startup() or True))
    return calls, states, values, alive


def test_real_port1_handoff_stays_playable_past_old_timeout_until_stop(monkeypatch, tmp_path):
    event = Event()
    calls, states, memory, _ = fixture(monkeypatch, event)
    event.on_wait = lambda: event.set() if event.now >= 15 else None
    result = runner.run_test('fake.iso', 'fake', tmp_path, interactive=True,
        stop_event=event, on_interactive_state=states.append,
        manifest={'costume': {'fighter': 'luigi', 'colorIndex': 3}})
    assert event.now >= 15  # old automatic observation ended after nine seconds
    assert states[1]['phase'] == 'playing' and states[1]['controllerPort'] == 1
    assert memory[match_setup.CSS_PLAYERS] == ckind('luigi')
    assert memory[match_setup.CSS_PLAYERS + 3] == 3
    assert memory[match_setup.PLAYER_BLOCK + match_setup.STATIC_PLAYER_ID] == 0
    assert memory[0x80002000 + match_setup.FT_X618_PLAYER_ID] == 0
    assert ('stage', INTERNAL_STAGE_ID['battlefield'], None) in calls
    assert result['interactive'] and result['success'] and result['verdict'] == 'stopped'
    assert result['pass'] is False
    # F-A-7: the RAM handle is closed too, not only the pipe.
    assert calls[-4:] == ['neutral', 'close-pipe', 'close-memory', 'cleanup']


def test_closing_dolphin_ends_preview_without_test_pass(monkeypatch, tmp_path):
    event = Event()
    calls, states, _, alive = fixture(monkeypatch, event)
    event.on_wait = lambda: alive.__setitem__(0, False)
    result = runner.run_test('fake.iso', 'fake', tmp_path, interactive=True,
                            stop_event=event, on_interactive_state=states.append)
    assert result['success'] and result['verdict'] == 'closed' and not result['pass']
    assert calls[-1] == 'cleanup'


def test_stop_before_launch_and_during_menu_are_normal_cancellations(monkeypatch, tmp_path):
    event = Event()
    calls, states, _, _ = fixture(monkeypatch, event)
    event.set()
    result = runner.run_test('fake.iso', 'fake', tmp_path, interactive=True, stop_event=event)
    assert result['verdict'] == 'stopped' and 'launch' not in calls
    event.stopped = False
    calls.clear()

    def navigate(*_a, check_startup, **_k):
        event.set()
        check_startup()

    monkeypatch.setattr(interactive.nav, 'nav_to_css', navigate)
    result = runner.run_test('fake.iso', 'fake', tmp_path, interactive=True,
                            stop_event=event, on_interactive_state=states.append)
    assert result['success'] and result['verdict'] == 'stopped'
    assert not any(s['phase'] == 'playing' for s in states)
    assert calls[-1] == 'cleanup'


@pytest.mark.parametrize('busy_lock', [True, False])
def test_stop_interrupts_lock_or_other_dolphin_wait_without_launch(monkeypatch, tmp_path, busy_lock):
    from shared.ingame import dolphin_lock
    event = Event()
    event.on_wait = event.set
    instance = boot.DolphinBoot('fake.iso', 'fake', tmp_path, interactive=True, stop_event=event)
    monkeypatch.setenv('MELEE_DOLPHIN_LOCK', '1')
    monkeypatch.setenv('MELEE_DOLPHIN_LOCK_WAIT', '600')

    def acquire(*_a, **kwargs):
        assert kwargs['wait'] == 0
        if busy_lock:
            raise dolphin_lock.BusyError({'pid': 999, 'purpose': 'synthetic'})

    monkeypatch.setattr(dolphin_lock, 'acquire', acquire)
    monkeypatch.setattr(boot, 'dolphin_running', lambda: [999])
    monkeypatch.setattr(boot.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('must not launch'))
    with pytest.raises(boot.DolphinBootCancelled):
        instance.launch()
    assert event.now == 0.25


def test_log_preservation_failure_does_not_mask_stop(monkeypatch, tmp_path):
    event = Event()
    fixture(monkeypatch, event)
    event.set()

    def failed_cleanup(_):
        raise OSError('synthetic log stat failure')

    monkeypatch.setattr(interactive.DolphinBoot, 'cleanup', failed_cleanup)
    result = runner.run_test('fake.iso', 'fake', tmp_path, interactive=True, stop_event=event)
    assert result['success'] and result['verdict'] == 'stopped'
    assert result['cleanup_warning'] == 'synthetic log stat failure'


@pytest.mark.parametrize('fps', [60, 15])
def test_css_initialization_cannot_discard_fighter_or_stage_transition(monkeypatch, tmp_path, fps):
    event = Event()
    calls, states, memory, _ = fixture(monkeypatch, event)
    memory['fps'] = fps
    event.on_wait = lambda: event.set() if memory[interactive.nav.SCENE_MINOR] == 2 else None
    result = runner.run_test('fake.iso', 'fake', tmp_path, interactive=True,
        stop_event=event, on_interactive_state=states.append,
        manifest={'costume': {'fighter': 'luigi', 'colorIndex': 3}})
    assert result['verdict'] == 'stopped'
    assert any(state['phase'] == 'playing' for state in states)
    assert memory[match_setup.CSS_PLAYERS] == ckind('luigi')
    assert memory[match_setup.CSS_PLAYERS + 3] == 3
    warp_times = [call[1] for call in calls if isinstance(call, tuple) and call[0] == 'warp']
    assert len(warp_times) == 1 and warp_times[0] >= 90 / fps


@pytest.mark.parametrize('failure', ['no_cursor', 'stalled', 'stop', 'left_css', 'online'])
def test_unready_css_never_writes_selection_or_launches_stage(monkeypatch, tmp_path, failure):
    event = Event()
    calls, states, memory, _ = fixture(monkeypatch, event)
    if failure == 'no_cursor': memory['cursor'] = None
    if failure == 'stalled': memory['fps'] = 0
    if failure == 'stop': event.on_wait = event.set
    if failure == 'left_css':
        event.on_wait = lambda: memory.__setitem__(interactive.nav.SCENE_MINOR, 1)
    if failure == 'online':
        event.on_wait = lambda: memory.__setitem__(interactive.nav.SCENE_MAJOR, 8)
    result = runner.run_test('fake.iso', 'fake', tmp_path, interactive=True,
                            stop_event=event, on_interactive_state=states.append)
    assert result['verdict'] == ('stopped' if failure == 'stop' else 'error')
    assert not any(isinstance(call, tuple) and call[0] in ('warp', 'stage') for call in calls)
    assert match_setup.CSS_PLAYERS not in memory
    assert match_setup.RULES_MODE not in memory
    assert not any(state['phase'] == 'playing' for state in states)
    assert calls[-1] == 'cleanup'
    assert event.now <= 15.1


def test_css_pointer_replacement_restarts_settle_interval(monkeypatch, tmp_path):
    event = Event()
    calls, states, memory, _ = fixture(monkeypatch, event)

    def advance():
        if event.now >= 1: memory['cursor'] = 0x80004000
        if memory[interactive.nav.SCENE_MINOR] == 2: event.set()

    event.on_wait = advance
    result = runner.run_test('fake.iso', 'fake', tmp_path, interactive=True,
                            stop_event=event, on_interactive_state=states.append)
    assert result['verdict'] == 'stopped'
    warp_times = [call[1] for call in calls if isinstance(call, tuple) and call[0] == 'warp']
    assert len(warp_times) == 1 and warp_times[0] >= 2.5


def test_css_frame_reset_restarts_settle_interval(monkeypatch, tmp_path):
    event = Event()
    calls, states, memory, _ = fixture(monkeypatch, event)
    read_u32 = interactive.Dolphin.u32

    def reset_counter(self, address):
        if address == interactive.FRAME_COUNTER and event.now >= 1:
            return int((event.now - 1) * 60)
        return read_u32(self, address)

    monkeypatch.setattr(interactive.Dolphin, 'u32', reset_counter)
    event.on_wait = lambda: event.set() if memory[interactive.nav.SCENE_MINOR] == 2 else None
    result = runner.run_test('fake.iso', 'fake', tmp_path, interactive=True, stop_event=event)
    assert result['verdict'] == 'stopped'
    warp_times = [call[1] for call in calls if isinstance(call, tuple) and call[0] == 'warp']
    assert len(warp_times) == 1 and warp_times[0] >= 2.5


def test_failed_transition_reports_menu_phase_and_never_starts_stage(monkeypatch, tmp_path):
    event = Event()
    calls, states, _, _ = fixture(monkeypatch, event)
    monkeypatch.setattr(interactive.StageCursor, 'wait_for_stage_select', lambda *_a, **_k: False)
    logs = []
    result = runner.run_test('fake.iso', 'fake', tmp_path, interactive=True,
                            stop_event=event, on_interactive_state=states.append, log=logs.append)
    assert result['verdict'] == 'error'
    assert 'character select to stage select' in result['reason']
    assert any('CSS-to-SSS transition failed: scene=' in line for line in logs)
    assert not any(isinstance(call, tuple) and call[0] == 'stage' for call in calls)
    assert not any(state['phase'] == 'playing' for state in states)
