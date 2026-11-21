"""An automated in-game test gives its Dolphin a deadline, as a capture does
(test_capture_deadline.py), and a run ended there is a harness error, never a
verdict on the build. No Dolphin is booted."""
import types

import shared.ingame.runner as runner
from shared.ingame import boot


def test_a_run_ended_at_its_deadline_is_an_error_not_a_crash():
    stuck = types.SimpleNamespace(timed_out=True, deadline=411.0)
    result = {'verdict': 'crashed', 'pass': False, 'reason': 'Dolphin process exited.',
              'boot_health': {'verdict': 'crashed', 'reason': 'dolphin process exited'},
              'checks': [{'label': 'costume', 'verdict': 'healthy', 'reason': 'ran'},
                         {'label': 'stage', 'verdict': 'crashed', 'reason': 'Dolphin process exited.'}]}
    runner._note_deadline(stuck, result)
    assert result['verdict'] == 'error' and result['pass'] is False and result['timedOut']
    assert 'boot_health' not in result
    assert 'ended after 411 seconds' in result['reason'] and 'not a verdict on the build' in result['reason']
    # the check that finished keeps its verdict; the one in flight saw OUR kill, not a crash of the mod
    assert [c['verdict'] for c in result['checks']] == ['healthy', 'error']
    assert result['checks'][0]['reason'] == 'ran'
    assert result['checks'][1]['reason'] == result['reason']


def test_a_run_that_ended_in_time_keeps_its_verdict():
    result = {'verdict': 'crashed', 'pass': False, 'reason': 'Dolphin process exited.',
              'checks': [{'label': 'stage', 'verdict': 'crashed', 'reason': 'Dolphin process exited.'}]}
    before = {**result, 'checks': [dict(c) for c in result['checks']]}
    runner._note_deadline(types.SimpleNamespace(timed_out=False, deadline=300.0), result)
    assert result == before


def test_an_automated_run_gives_its_dolphin_a_deadline(monkeypatch):
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

    monkeypatch.setattr(runner, 'DolphinBoot', RecordingBoot)
    monkeypatch.setattr(boot, 'wait_until_no_dolphin', lambda *a, **k: True)
    monkeypatch.setattr(runner, 'build_plan', lambda manifest: [{}] * (manifest or {}).get('checks', 0))

    runner.run_test('x.iso', None, 'runs')                                              # boot health only
    runner.run_test('x.iso', None, 'runs', manifest={'checks': 2})
    runner.run_test('x.iso', None, 'runs', manifest={'checks': 2}, observe_seconds=30)   # a longer watch is paid for
    runner.run_test('x.iso', None, 'runs', manifest={'checks': 2}, deadline=45)

    assert seen == [312.0, 510.0, 570.0, 45]
