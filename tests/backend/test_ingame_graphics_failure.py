import ctypes
from ctypes import wintypes as wt
from types import SimpleNamespace

import pytest

import shared.ingame.boot as boot
import shared.ingame.boot_errors as errors
import shared.ingame.nav as nav
import shared.ingame.runner as runner


MESSAGE = 'Failed to initialize Direct3D. Make sure your video card supports at least D3D 10.0'
TITLE = 'Dolphin Direct3D 11 backend'


@pytest.mark.parametrize('title,body,recognized', [
    (TITLE, MESSAGE, True),
    (TITLE, 'Failed to enumerate adapters', True),
    ('Dolphin OpenGL backend', 'Could not create a context', True),
    ('Dolphin', MESSAGE, False),
    ('Another program Direct3D backend', MESSAGE, False),
    (TITLE, 'Graphics initialized', False),
])
def test_only_known_graphics_failures(title, body, recognized):
    result = errors.graphics_dialog_error(title, body)
    assert bool(result) is recognized
    if result:
        assert 'test did not run' in result


@pytest.mark.skipif(not hasattr(ctypes, 'WINFUNCTYPE'), reason='Win32 ABI harness')
def test_native_dialog_reader_ignores_unrelated_process_and_bounds_control_reads(monkeypatch):
    class Function:
        def __init__(self, call):
            self.call = call

        def __call__(self, *args):
            return self.call(*args)

    windows = {
        1: (99, '#32770', TITLE),  # another user's Dolphin is never read
        2: (42, 'wxWindowNR', TITLE),  # ordinary window is never a failure
        3: (42, '#32770', TITLE),
        4: (42, 'Static', MESSAGE),
        5: (99, 'Static', 'foreign child'),
        6: (42, 'Static', 'hung control'),
    }
    reads = []

    def set_owner(hwnd, pointer):
        ctypes.cast(pointer, ctypes.POINTER(wt.DWORD))[0] = windows[hwnd][0]
        return 1

    def get_text(hwnd, buf, count):
        buf.value = windows[hwnd][2][:count - 1]
        return len(buf.value)

    def get_class(hwnd, buf, count):
        buf.value = windows[hwnd][1]
        return len(buf.value)

    def enum_windows(callback, param):
        for hwnd in (1, 2, 3):
            if not callback(hwnd, param):
                break
        return 1

    def enum_children(hwnd, callback, param):
        assert hwnd == 3
        for child in (4, 5, 6):
            if not callback(child, param):
                break
        return 1

    def message(hwnd, message_id, capacity, destination, flags, timeout, result):
        assert message_id == 0x000D and flags == 0x0002 and timeout == 50
        reads.append(hwnd)
        if hwnd == 6:
            return 0
        text = windows[hwnd][2]
        ctypes.memmove(destination, ctypes.create_unicode_buffer(text),
                       (len(text) + 1) * ctypes.sizeof(ctypes.c_wchar))
        return 1

    api = SimpleNamespace(**{name: Function(call) for name, call in {
        'EnumWindows': enum_windows, 'EnumChildWindows': enum_children,
        'GetWindowThreadProcessId': set_owner, 'IsWindowVisible': lambda _: True,
        'GetClassNameW': get_class, 'GetWindowTextW': get_text,
        'SendMessageTimeoutW': message,
    }.items()})
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *_a, **_k: api)
    dialogs = errors._owned_dialogs(42)
    assert dialogs == [(TITLE, MESSAGE + ' ')]
    assert reads == [4, 6]


def test_boot_checks_only_retained_live_process_and_throttles(monkeypatch, tmp_path):
    instance = boot.DolphinBoot('fake.iso', 'fake', tmp_path)
    process = SimpleNamespace(pid=42, poll=lambda: None)
    instance.proc = process
    now = [0.0]
    seen = []
    monkeypatch.setattr(boot, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setattr(boot.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(boot, 'read_graphics_failure', lambda pid: seen.append(pid))
    instance.check_graphics_startup()
    instance.check_graphics_startup()
    assert seen == [42]
    now[0] = 0.5
    instance.check_graphics_startup()
    assert seen == [42, 42]
    process.poll = lambda: 0
    now[0] = 1
    instance.check_graphics_startup()
    assert seen == [42, 42]


def test_graphics_failure_interrupts_before_controller_probe(monkeypatch, tmp_path):
    instance = boot.DolphinBoot('fake.iso', 'fake', tmp_path)
    instance.proc = SimpleNamespace(pid=42, poll=lambda: None)
    monkeypatch.setattr(boot, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setattr(boot, 'read_graphics_failure', lambda _: MESSAGE)
    monkeypatch.setattr(boot, 'pipe_open', lambda _: pytest.fail('pipe must not be probed'))
    with pytest.raises(errors.DolphinGraphicsError, match='initialize Direct3D'):
        instance.wait_for_pipe()


def test_dialog_result_is_discarded_if_owned_process_exits_during_read(monkeypatch, tmp_path):
    instance = boot.DolphinBoot('fake.iso', 'fake', tmp_path)
    process = SimpleNamespace(pid=42, poll=lambda: None)
    instance.proc = process
    monkeypatch.setattr(boot, 'os', SimpleNamespace(name='nt'))

    def read(_):
        process.poll = lambda: 0
        return MESSAGE

    monkeypatch.setattr(boot, 'read_graphics_failure', read)
    instance.check_graphics_startup()


def test_graphics_failure_interrupts_menu_before_any_prompt_input():
    def fail():
        raise errors.DolphinGraphicsError(MESSAGE)

    scene = SimpleNamespace(u8=lambda _: pytest.fail('RAM must not be read'))
    pipe = SimpleNamespace(neutral=lambda: None, tap=lambda *_: pytest.fail('no button presses'))
    with pytest.raises(errors.DolphinGraphicsError):
        nav.nav_to_css(scene, pipe, check_startup=fail)


def _runner_fakes(monkeypatch, *, nav_ok=True, graphics_error=False):
    closed = []
    pipe = SimpleNamespace(close=lambda: closed.append('pipe'))

    class Boot:
        pid = 42

        def __init__(self, *_a, **_k):
            pass

        def prepare(self): pass
        def launch(self): pass
        def cleanup(self): closed.append('boot')
        def open_pipe(self): return pipe
        def wait_for_pipe(self, **_): return True

        def check_graphics_startup(self):
            if graphics_error:
                raise errors.DolphinGraphicsError(MESSAGE)

    monkeypatch.setattr(boot, 'wait_until_no_dolphin', lambda *_a, **_k: True)
    monkeypatch.setattr(runner, 'DolphinBoot', Boot)
    monkeypatch.setattr(runner, 'Dolphin', lambda _: SimpleNamespace(base=1, locate=lambda: True))
    monkeypatch.setattr(runner.match_setup, 'patch_one_player', lambda *_a, **_k: True)
    monkeypatch.setattr(runner.match_setup, 'force_time_infinite', lambda *_a, **_k: None)
    monkeypatch.setattr(runner, 'Observer', lambda _: SimpleNamespace(
        watch_health=lambda **_: ('healthy', 'RAM frames advance', {}),
        watch=lambda **_: ('healthy', 'match frames advance', {})))

    def navigate(*_a, check_startup, **_k):
        check_startup()
        return nav_ok

    monkeypatch.setattr(runner.nav, 'nav_to_css', navigate)
    monkeypatch.setattr(runner.nav, 'wait_css_ready', lambda *_a, **_k: True)
    monkeypatch.setattr(runner, 'Cursor', lambda *_: SimpleNamespace(hovered=lambda: 1))
    monkeypatch.setattr(runner, 'StageCursor', lambda *_: object())
    monkeypatch.setattr(runner, '_shot_b64', lambda _: 'diagnostic-image')
    monkeypatch.setattr(runner, '_select_char', lambda *_: True)
    monkeypatch.setattr(runner, '_internal_stage_id', lambda _: None)
    monkeypatch.setattr(runner, '_ensure_on_sss', lambda *_a, **_k: True)
    monkeypatch.setattr(runner, '_select_stage', lambda *_: True)
    return closed


def test_failed_navigation_with_healthy_ram_is_not_a_pass(monkeypatch, tmp_path):
    closed = _runner_fakes(monkeypatch, nav_ok=False)
    result = runner.run_test('fake.iso', 'fake', tmp_path, manifest={'costume': {'character': 'Mario'}})
    assert result['pass'] is False and result['verdict'] == 'error'
    assert result['checks'] == []
    assert result['boot_health']['verdict'] == 'healthy'
    assert result['screenshot'] == 'diagnostic-image'
    assert 'did not run' in result['reason']
    assert closed == ['pipe', 'boot']


def test_successful_match_still_passes(monkeypatch, tmp_path):
    _runner_fakes(monkeypatch)
    monkeypatch.setattr(runner, 'build_plan', lambda _: [{
        'label': 'Costume', 'covers': ['costume'],
        'char': {'kind': 'vanilla', 'name': 'Mario'}, 'stage': None,
    }])
    result = runner.run_test('fake.iso', 'fake', tmp_path, manifest={'costume': {}})
    assert result['pass'] is True and result['verdict'] == 'healthy'
    assert len(result['checks']) == 1 and result['checks'][0]['started'] is True


def test_graphics_failure_returns_actionable_error_and_skips_screenshot(monkeypatch, tmp_path):
    closed = _runner_fakes(monkeypatch, graphics_error=True)
    monkeypatch.setattr(runner, '_shot_b64', lambda _: pytest.fail('renderer unavailable'))
    result = runner.run_test('fake.iso', 'fake', tmp_path)
    assert result['pass'] is False and result['verdict'] == 'error'
    assert result['error_code'] == 'graphics_initialization_failed'
    assert result['reason'] == MESSAGE
    assert closed == ['pipe', 'boot']


@pytest.mark.parametrize('nav_ok', [True, False])
def test_the_ram_handle_is_closed_with_the_pipe_before_the_boot_cleans_up(monkeypatch, tmp_path, nav_ok):
    """F-A-7: the runner's Dolphin(pid) RAM handle leaked until Nucleus closed;
    it is closed like the pipe, however the test ends."""
    closed = _runner_fakes(monkeypatch, nav_ok=nav_ok)
    monkeypatch.setattr(runner, 'Dolphin', lambda _: SimpleNamespace(
        base=1, locate=lambda: True, close=lambda: closed.append('memory')))
    monkeypatch.setattr(runner, 'build_plan', lambda _: [{
        'label': 'Costume', 'covers': ['costume'],
        'char': {'kind': 'vanilla', 'name': 'Mario'}, 'stage': None,
    }])
    runner.run_test('fake.iso', 'fake', tmp_path, manifest={'costume': {}})
    assert closed == ['pipe', 'memory', 'boot']
