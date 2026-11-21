"""A capture's Dolphin has a deadline, so a run that has stopped moving cannot
keep it. (On 2026-11-10 one pause capture sat in a blocked call for three hours
holding its Dolphin and the machine-wide Dolphin lock.) Nothing here boots
Dolphin: the process is a stand-in that only ends when it is told to."""
import threading
import time
import types

import pytest

import shared.ingame.capture as cap
from shared.ingame import boot, embed


class StandInDolphin:
    pid = 4242

    def __init__(self):
        self.ended = threading.Event()

    def poll(self):
        return 0 if self.ended.is_set() else None

    def terminate(self):
        self.ended.set()

    kill = terminate

    def wait(self, timeout=None):
        self.ended.wait(timeout)
        return 0


@pytest.fixture
def launch(tmp_path, monkeypatch):
    monkeypatch.setenv('MELEE_DOLPHIN_LOCK', '0')
    for name in ('set_active', 'park', 'clear_active'):
        monkeypatch.setattr(embed, name, lambda *a, **k: None)

    def launch(**kwargs):
        proc = StandInDolphin()
        monkeypatch.setattr(boot.subprocess, 'Popen', lambda *a, **k: proc)
        dolphin = boot.DolphinBoot(str(tmp_path / 'test.iso'), 'synthetic', tmp_path, **kwargs)
        dolphin.exe, dolphin.user_dir = str(tmp_path / 'Dolphin.exe'), tmp_path / 'User'
        dolphin.launch()
        return dolphin, proc

    return launch


def test_a_dolphin_still_running_at_its_deadline_is_ended(launch):
    dolphin, proc = launch(deadline=0.05)
    assert proc.ended.wait(5)
    assert dolphin.timed_out
    dolphin.cleanup()


def test_a_run_that_ends_in_time_is_not_called_stuck(launch):
    dolphin, proc = launch(deadline=0.2)
    dolphin.cleanup()
    assert proc.ended.is_set()      # by cleanup, as always
    time.sleep(0.4)                 # past the deadline
    assert not dolphin.timed_out


def test_a_boot_without_a_deadline_is_never_ended(launch):
    dolphin, proc = launch()
    assert dolphin._deadline_timer is None
    assert not proc.ended.is_set()
    dolphin.cleanup()


def test_a_capture_ended_at_its_deadline_says_so():
    stuck = types.SimpleNamespace(timed_out=True, deadline=300.0)

    failed = {'ok': False, 'png': None, 'reason': 'Could not reach the character-select screen.'}
    cap._note_deadline(stuck, failed)
    assert failed['timedOut']
    assert failed['reason'] == 'Dolphin stopped responding, so the capture was ended after 300 seconds.'

    cut_short = {'ok': True, 'shots': [{'id': 'a', 'png': b'PNG'}], 'reason': 'Dolphin exited mid-batch.',
                 'crashed_id': 'b'}
    cap._note_deadline(stuck, cut_short)
    assert 'stopped responding' in cut_short['reason']
    assert cut_short['ok'] and cut_short['crashed_id'] == 'b'      # its shots and its crasher stand

    already_taken = {'ok': True, 'png': b'PNG', 'reason': 'captured'}
    cap._note_deadline(stuck, already_taken)
    assert already_taken['reason'] == 'captured'

    in_time = {'ok': False, 'reason': 'Dolphin exited during boot.'}
    cap._note_deadline(types.SimpleNamespace(timed_out=False, deadline=300.0), in_time)
    assert in_time == {'ok': False, 'reason': 'Dolphin exited during boot.'}


def test_every_capture_gives_its_dolphin_a_deadline(monkeypatch):
    seen = []

    class RecordingBoot:
        timed_out = False

        def __init__(self, *args, **kwargs):
            self.deadline = kwargs.get('deadline')
            seen.append(self.deadline)

        def prepare(self):
            raise RuntimeError('far enough')

        def cleanup(self):
            pass

    monkeypatch.setattr(cap, 'DolphinBoot', RecordingBoot)
    monkeypatch.setattr(cap, 'wait_until_no_dolphin', lambda *a, **k: True)

    cap.capture_pause('x.iso', None, 'runs')
    cap.capture_stage('x.iso', None, 'runs', 2)
    cap.capture_stage('x.iso', None, 'runs', 2, framing_sweep=[{}, {}, {}, {}])
    cap.capture_stage('x.iso', None, 'runs', 3, stadium_form='fire', stadium_timeout=150.0)
    cap.capture_stage('x.iso', None, 'runs', 3, stadium_forms=['fire', 'grass'], stadium_timeout=150.0)
    cap.capture_stage_batch('x.iso', None, 'runs', [{}, {}, {}])
    cap.capture_pause('x.iso', None, 'runs', deadline=30)

    assert seen == [300.0, 300.0, 320.0, 450.0, 1060.0, 480.0, 30]
