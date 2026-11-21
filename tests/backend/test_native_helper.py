"""core.native_helper: the bounded HSDRaw run, moved out of the retired assistant/model_import.py."""
import pytest


@pytest.mark.parametrize('changed', [False, True])
def test_native_timeout_only_cleans_up_verified_child(vault, monkeypatch, changed):
    import os
    import subprocess
    import psutil
    from types import SimpleNamespace
    from core import config, native_helper
    executable = vault.path('test-native.exe'); executable.write_bytes(b'test')
    monkeypatch.setattr(config, 'HSDRAW_EXE', executable)
    state = {'identity': 0, 'communicate': 0, 'killed': False}
    class Child:
        pid = 12345
        def communicate(self, timeout=None):
            state['communicate'] += 1
            if state['communicate'] == 1:
                raise subprocess.TimeoutExpired('test-native', timeout)
            return 'stopped', None
        def poll(self):
            return None
        def kill(self):
            state['killed'] = True
    def process(pid):
        assert pid == 12345
        state['identity'] += 1
        created = 2 if changed and state['identity'] > 1 else 1
        return SimpleNamespace(pid=pid, create_time=lambda: created, ppid=os.getpid, exe=lambda: str(executable))
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: Child())
    monkeypatch.setattr(psutil, 'Process', process)
    with pytest.raises((ValueError, RuntimeError), match='identity changed' if changed else 'exceeded 90 seconds'):
        native_helper.native_run(['--model', 'import'])
    assert state['killed'] is (not changed)
