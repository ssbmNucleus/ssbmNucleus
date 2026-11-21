"""core/jobs.py: one status, a final status always, cleanup on end and after a death."""
from tests.paths import BACKEND
import json
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, str(BACKEND))

from core import critical_ops, jobs


@pytest.fixture(autouse=True)
def job_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, '_root_override', tmp_path / 'jobs')
    monkeypatch.setattr(jobs, '_jobs', {})
    monkeypatch.setattr(jobs, '_kinds', {})
    return tmp_path / 'jobs'


def _wait(job_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = jobs.get(job_id)
        if record['status'] in jobs.FINAL and record.get('ended_at'):
            return record
        time.sleep(0.01)
    raise AssertionError(f'job {job_id} did not finish: {jobs.get(job_id)}')


def test_an_exception_before_any_progress_still_ends_failed_with_an_error():
    def boom(job):
        raise RuntimeError('disk full')
    record = _wait(jobs.start('t', boom))
    assert record['status'] == 'failed'
    assert record['error'] == 'disk full'


def test_an_exception_without_a_message_still_carries_an_error():
    def boom(job):
        raise KeyError()
    record = _wait(jobs.start('t', boom))
    assert record['status'] == 'failed'
    assert record['error']


def test_a_result_and_progress_reach_the_record():
    def work(job):
        job.progress(0.5, 'halfway', step=2)
        return {'made': 3}
    record = _wait(jobs.start('t', work, params={'mode': 'x'}))
    assert record['status'] == 'done'
    assert record['result'] == {'made': 3}
    assert record['progress'] == 1.0
    assert record['extra'] == {'step': 2}
    assert record['params'] == {'mode': 'x'}


def test_single_refuses_a_second_job_of_the_kind():
    gate = threading.Event()
    first = jobs.start('sync', lambda job: gate.wait(5), single=True)
    with pytest.raises(jobs.JobBusy) as busy:
        jobs.start('sync', lambda job: None, single=True)
    assert busy.value.job_id == first
    gate.set()
    _wait(first)
    _wait(jobs.start('sync', lambda job: None, single=True))


def test_a_job_whose_worker_never_started_ends_failed_and_frees_its_slot(monkeypatch):
    """A thread that cannot start leaves no worker to end the job: it must not
    hold a single kind's slot until restart."""
    cleaned = []
    jobs.register_kind('capture', cleanup=lambda name, value: cleaned.append(name))

    class NoThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    real_thread = threading.Thread
    monkeypatch.setattr(jobs.threading, 'Thread', NoThread)
    with pytest.raises(RuntimeError):
        jobs.start('capture', lambda job: None, single=True, owned={'dolphin': 1})
    monkeypatch.setattr(jobs.threading, 'Thread', real_thread)
    [record] = jobs.list_jobs(kind='capture')
    assert record['status'] == 'failed' and record['ended_at']
    assert "can't start new thread" in record['error']
    assert cleaned == ['dolphin'] and record['owned'] == {}
    _wait(jobs.start('capture', lambda job: None, single=True))


def test_a_critical_job_holds_shutdown_until_it_ends():
    gate = threading.Event()
    job_id = jobs.start('restore', lambda job: gate.wait(5), critical=True, label='Vault restore')
    deadline = time.time() + 2
    while 'Vault restore' not in critical_ops.active_ops() and time.time() < deadline:
        time.sleep(0.01)
    assert 'Vault restore' in critical_ops.active_ops()
    gate.set()
    _wait(job_id)
    # The final record goes out first, then the hold is let go (a quit must
    # not end the process before the record says how the job ended).
    deadline = time.time() + 2
    while 'Vault restore' in critical_ops.active_ops() and time.time() < deadline:
        time.sleep(0.01)
    assert 'Vault restore' not in critical_ops.active_ops()


def test_cancel_ends_cancelled_when_the_job_checks():
    started = threading.Event()

    def work(job):
        started.set()
        while True:
            job.check_stop()
            time.sleep(0.01)
    job_id = jobs.start('t', work)
    started.wait(2)
    assert jobs.cancel(job_id)
    assert _wait(job_id)['status'] == 'cancelled'


def test_whatever_a_job_still_owns_when_it_ends_is_cleaned_up():
    cleaned = []
    jobs.register_kind('rec', cleanup=lambda name, value: cleaned.append((name, value)) or 'Put back.')

    def work(job):
        job.own('dump_flags', 'on')
        job.own('temp', 'x')
        job.release('temp')
        raise RuntimeError('Dolphin crashed')
    record = _wait(jobs.start('rec', work))
    assert cleaned == [('dump_flags', 'on')]
    assert record['owned'] == {}
    assert record['notes'] == ['Put back.']


def test_cancel_runs_the_kinds_hook_so_work_that_cannot_check_ends():
    """A kind that waits on a process (a Dolphin) registers on_cancel to close it."""
    closed = threading.Event()
    jobs.register_kind('watch', on_cancel=lambda job: closed.set())
    job_id = jobs.start('watch', lambda job: closed.wait(5) and job.check_stop())
    assert jobs.cancel(job_id) is True
    assert _wait(job_id)['status'] == 'cancelled'


def test_a_failing_cancel_hook_still_leaves_the_stop_set():
    gate = threading.Event()

    def hook(job):
        raise RuntimeError('no Dolphin to close')
    jobs.register_kind('watch', on_cancel=hook)
    job_id = jobs.start('watch', lambda job: gate.wait(5) and job.check_stop())
    assert jobs.cancel(job_id) is True
    gate.set()
    assert _wait(job_id)['status'] == 'cancelled'


def test_a_job_whose_cancel_broke_its_work_ends_cancelled_not_failed():
    """Closing a watch's Dolphin makes what waited on it fail: that is the Cancel."""
    closed = threading.Event()
    jobs.register_kind('watch', on_cancel=lambda job: closed.set())

    def work(job):
        closed.wait(5)
        raise RuntimeError('Dolphin exited')
    job_id = jobs.start('watch', work)
    jobs.cancel(job_id)
    record = _wait(job_id)
    assert record['status'] == 'cancelled' and not record['error']


def test_a_plain_kind_that_fails_after_a_cancel_still_reports_the_failure():
    gate = threading.Event()
    jobs.register_kind('scan')

    def work(job):
        gate.wait(5)
        raise RuntimeError('disk full')
    job_id = jobs.start('scan', work)
    jobs.cancel(job_id)
    gate.set()
    record = _wait(job_id)
    assert record['status'] == 'failed' and record['error'] == 'disk full'


def _render_cleanup(order):
    """A render's cleanup: its throwaway ISO cannot be deleted while the
    Dolphin playing it is alive (Windows keeps an open file)."""
    alive = {'dolphin': True}

    def cleanup(name, value):
        if name == 'iso' and alive['dolphin']:
            raise PermissionError('the ISO is open in Dolphin')
        if name == 'dolphin':
            alive['dolphin'] = False
        order.append(name)
    return cleanup


def test_cleanup_undoes_the_newest_first_so_a_process_closes_before_its_files_go():
    order = []
    jobs.register_kind('render', cleanup=_render_cleanup(order))

    def work(job):
        job.own('project', 'P')
        job.own('iso', 'I')
        job.own('dolphin', {'pid': 1})
        job.own('recorder', 'R')
        job.release('recorder')
        job.own('dolphin', {'pid': 2})   # the next game's Dolphin is again the newest
        raise RuntimeError('Dolphin crashed')
    record = _wait(jobs.start('render', work))
    assert order == ['dolphin', 'iso', 'project']
    assert record['owned'] == {}


def test_recovery_undoes_the_newest_first_too(job_dir):
    order = []
    jobs.register_kind('render', cleanup=_render_cleanup(order))
    _dead_record(job_dir, kind='render',
                 owned={'project': 'P', 'iso': 'I', 'recorder': 'R', 'dolphin': {'pid': 1}})
    jobs.recover_interrupted()
    assert order == ['dolphin', 'recorder', 'iso', 'project']
    assert jobs.get('dead-1')['owned'] == {}


def test_a_single_kind_stays_active_until_its_cleanup_has_run():
    """The next job of the kind must not start while the last one's owned
    settings are still being put back (they would undo the new job's)."""
    seen = []

    def cleanup(name, value):
        seen.append(jobs.active_job('rec') is not None)
    jobs.register_kind('rec', cleanup=cleanup)
    job_id = jobs.start('rec', lambda job: job.own('dump_flags', 'on'), single=True)
    record = _wait(job_id)
    assert seen == [True]
    assert record['status'] == 'done' and record['owned'] == {}


def test_a_kind_that_keeps_few_stays_off_disk_and_forgets_old_runs(job_dir):
    jobs.register_kind('scan', keep=2)
    ids = [_wait(jobs.start('scan', lambda job: i))['id'] for i in range(4)]
    assert [r['id'] for r in jobs.list_jobs(kind='scan')] == ids[:1:-1]
    assert jobs.get(ids[0]) is None
    assert not job_dir.exists() or not list(job_dir.glob('*.json'))


def test_owned_resources_are_on_disk_before_the_job_ends(job_dir):
    gate = threading.Event()

    def work(job):
        job.own('staging', '/tmp/.vault-restore-1')
        gate.wait(5)
    job_id = jobs.start('restore', work)
    deadline = time.time() + 2
    record = {}
    while time.time() < deadline:
        try:
            record = json.loads((job_dir / f'{job_id}.json').read_text())
        except OSError:
            # Windows refuses the read while the job replaces its record.
            pass
        if record.get('owned'):
            break
        time.sleep(0.01)
    assert record['status'] == 'running'
    assert record['owned'] == {'staging': '/tmp/.vault-restore-1'}
    gate.set()
    _wait(job_id)


def _dead_record(job_dir, **fields):
    job_dir.mkdir(parents=True, exist_ok=True)
    record = {'id': 'dead-1', 'kind': 'restore', 'label': 'Vault restore', 'status': 'running',
              'owned': {'staging': 'S', 'previous': 'P'}, 'notes': [], 'created_at': time.time(),
              'owner': {'pid': 999999999, 'created': 1.0}, **fields}
    (job_dir / f"{record['id']}.json").write_text(json.dumps(record))
    return record


def test_recovery_marks_a_dead_job_interrupted_and_cleans_up_once(job_dir):
    cleaned = []

    def cleanup(name, value):
        cleaned.append(name)
        return 'Your vault was put back.' if name == 'previous' else None
    jobs.register_kind('restore', cleanup=cleanup)
    _dead_record(job_dir)

    recovered = jobs.recover_interrupted()
    assert [r['id'] for r in recovered] == ['dead-1']
    assert sorted(cleaned) == ['previous', 'staging']
    record = jobs.get('dead-1')
    assert record['status'] == 'interrupted'
    assert record['owned'] == {}
    assert record['notes'] == ['Your vault was put back.']
    assert [r['id'] for r in jobs.list_jobs()] == ['dead-1']

    assert jobs.recover_interrupted() == []
    assert sorted(cleaned) == ['previous', 'staging']
    assert jobs.mark_seen('dead-1')
    assert jobs.list_jobs() == []


def test_recovery_leaves_a_job_whose_owner_is_alive(job_dir):
    jobs.register_kind('restore', cleanup=lambda name, value: pytest.fail('cleaned a live job'))
    _dead_record(job_dir, owner=jobs._OWNER)
    assert jobs.recover_interrupted() == []
    assert jobs.get('dead-1')['status'] == 'running'


def test_a_failed_cleanup_stays_owned_for_the_next_start(job_dir):
    def cleanup(name, value):
        if name == 'previous':
            raise PermissionError('in use')
    jobs.register_kind('restore', cleanup=cleanup)
    _dead_record(job_dir)
    jobs.recover_interrupted()
    assert jobs.get('dead-1')['owned'] == {'previous': 'P'}


def test_a_cleanup_that_failed_at_one_start_is_retried_at_the_next(job_dir):
    fail = {'previous': True}

    def cleanup(name, value):
        if fail.get(name):
            raise PermissionError('in use')
        return f'{name} cleaned'
    jobs.register_kind('restore', cleanup=cleanup)
    _dead_record(job_dir)
    jobs.recover_interrupted()
    fail['previous'] = False
    assert jobs.recover_interrupted() == []
    record = jobs.get('dead-1')
    assert record['status'] == 'interrupted'
    assert record['owned'] == {}
    assert record['notes'] == ['staging cleaned', 'previous cleaned']


def test_recovery_cleans_what_an_ended_jobs_failed_cleanup_left_and_shows_it_again(job_dir):
    """A job that ended with a cleanup that failed is not interrupted, but what
    it still owned is undone at the next start and its note shown once more."""
    jobs.register_kind('restore', cleanup=lambda name, value: 'Your vault was put back.')
    _dead_record(job_dir, status='done', seen=True, owned={'previous': 'P'}, notes=['Restored.'])
    assert jobs.recover_interrupted() == []
    record = jobs.get('dead-1')
    assert record['status'] == 'done'
    assert record['owned'] == {}
    assert record['notes'] == ['Restored.', 'Your vault was put back.']
    assert record['seen'] is False


def test_recovery_drops_old_ended_records_and_keeps_recent_ones(job_dir):
    dead = {'pid': 999999999, 'created': 1.0}
    old = time.time() - jobs.KEEP_SECONDS - 60
    now = time.time()
    jobs._write({'id': 'old', 'kind': 't', 'status': 'done', 'owned': {},
                 'created_at': old, 'ended_at': old, 'owner': dead})
    jobs._write({'id': 'recent', 'kind': 't', 'status': 'failed', 'owned': {},
                 'created_at': now, 'ended_at': now, 'owner': dead})
    assert jobs.recover_interrupted() == []
    assert not (job_dir / 'old.json').exists()
    assert jobs.get('old') is None
    assert jobs.get('recent')['status'] == 'failed'


def test_a_kind_without_cleanup_keeps_what_its_job_owned():
    """Nothing knows how to undo it, so it stays on the record rather than
    being dropped as if it had been put back."""
    record = _wait(jobs.start('plain', lambda job: job.own('temp', 'x')))
    assert record['status'] == 'done'
    assert record['owned'] == {'temp': 'x'}


# ---- run_inline --------------------------------------------------------------

def test_run_inline_runs_on_the_calling_thread_and_returns_the_final_record():
    cleaned = []
    jobs.register_kind('save', cleanup=lambda name, value: cleaned.append(name))
    caller = threading.current_thread()
    seen = []

    def work(job):
        seen.append(threading.current_thread() is caller)
        job.own('staging', 'x')
        return {'saved': True}
    record = jobs.run_inline('save', work, params={'mode': 'merge'})
    assert seen == [True]
    assert record['status'] == 'done' and record['result'] == {'saved': True}
    assert record['ended_at'] and record['owned'] == {} and cleaned == ['staging']
    assert record['params'] == {'mode': 'merge'}
    assert jobs.get(record['id'])['status'] == 'done'


def test_run_inline_reports_a_failure_as_its_record_not_an_exception():
    record = jobs.run_inline('save', lambda job: 1 / 0)
    assert record['status'] == 'failed'
    assert 'division' in record['error']


def test_run_inline_single_refuses_while_a_job_of_the_kind_runs():
    gate = threading.Event()
    running = jobs.start('sync', lambda job: gate.wait(5), single=True)
    try:
        with pytest.raises(jobs.JobBusy) as busy:
            jobs.run_inline('sync', lambda job: pytest.fail('ran beside the running job'), single=True)
        assert busy.value.job_id == running
    finally:
        gate.set()
    _wait(running)
    assert jobs.run_inline('sync', lambda job: 'next', single=True)['result'] == 'next'


# ---- ids, cancel, progress, events -------------------------------------------

@pytest.mark.parametrize('job_id', ['../escape', '..\\escape', 'a/b', '', '.hidden', 'x' * 129])
def test_a_job_id_that_is_not_a_plain_name_never_reaches_the_disk(job_dir, job_id):
    with pytest.raises(ValueError):
        jobs.start('t', lambda job: None, job_id=job_id)
    assert jobs.list_jobs() == []
    assert not job_dir.exists() or list(job_dir.iterdir()) == []
    assert jobs.get(job_id) is None
    assert jobs.mark_seen(job_id) is False


def test_a_job_id_already_used_is_refused_even_by_a_later_process(job_dir):
    # inline, so its final record is on disk before the next line
    jobs.run_inline('t', lambda job: 'first', job_id='build_1')
    with pytest.raises(ValueError):
        jobs.start('t', lambda job: 'second', job_id='build_1')
    jobs._jobs.clear()          # a later process: only the record on disk names it
    with pytest.raises(ValueError):
        jobs.start('t', lambda job: 'second', job_id='build_1')
    assert jobs.get('build_1')['result'] == 'first'


def test_cancel_of_an_unknown_or_ended_job_stops_nothing():
    record = _wait(jobs.start('t', lambda job: None))
    assert jobs.cancel(record['id']) is False
    assert jobs.cancel('no-such-job') is False
    assert jobs.get(record['id'])['status'] == 'done'


def test_a_stopped_job_says_it_is_stopping_and_ends_cancelled_without_an_error():
    started = threading.Event()

    def work(job):
        started.set()
        while not job.should_stop():
            time.sleep(0.01)
        raise jobs.Cancelled()
    job_id = jobs.start('t', work)
    assert started.wait(2)
    assert jobs.cancel(job_id)
    assert jobs.get(job_id)['detail'] == 'Stopping…'
    record = _wait(job_id)
    assert record['status'] == 'cancelled'
    assert record['error'] is None


def test_a_critical_job_that_fails_still_lets_shutdown_go():
    job_id = jobs.start('restore', lambda job: 1 / 0, critical=True, label='Failing restore')
    assert _wait(job_id)['status'] == 'failed'
    deadline = time.time() + 2
    while 'Failing restore' in critical_ops.active_ops() and time.time() < deadline:
        time.sleep(0.01)
    assert 'Failing restore' not in critical_ops.active_ops()


def test_progress_is_clamped_and_a_job_that_never_reported_any_stays_indeterminate():
    seen = []

    def work(job):
        job.progress(1.7)
        seen.append(job.fraction)
        job.progress(-0.2)
        seen.append(job.fraction)
    assert jobs.run_inline('t', work)['progress'] == 1.0
    assert seen == [1.0, 0.0]
    assert jobs.run_inline('t', lambda job: None)['progress'] is None


def test_every_change_goes_out_as_one_job_event_carrying_the_whole_record(monkeypatch):
    from core import state
    sent = []

    class Socket:
        def emit(self, event, data):
            sent.append((event, data))
    monkeypatch.setattr(state, 'get_socketio', lambda: Socket())
    record = jobs.run_inline('t', lambda job: job.progress(0.5, 'half') or 'made')
    assert {name for name, _data in sent} == {'job'}
    statuses = [data['status'] for _name, data in sent]
    assert statuses[0] == 'queued' and 'running' in statuses and statuses[-1] == 'done'
    assert any(data['progress'] == 0.5 and data['detail'] == 'half' for _name, data in sent)
    assert all(data['id'] == record['id'] and data['kind'] == 't' for _name, data in sent)
    assert sent[-1][1] == record


def test_a_record_names_this_process_and_a_dead_or_reused_pid_is_not_its_owner():
    owner = jobs.process_owner()
    assert owner['pid'] == os.getpid()
    assert jobs.owner_alive(owner)
    assert not jobs.owner_alive({'pid': 999999999, 'created': 1.0})
    assert not jobs.owner_alive(None)
    if owner['created'] is not None:
        # this pid, started at another time: a reused pid, not the owner
        assert not jobs.owner_alive({'pid': owner['pid'], 'created': owner['created'] - 1000})


# ---- listing and seen ----------------------------------------------------------

def test_listing_filters_by_kind_and_active_and_lists_only_unseen_interrupted_jobs_from_disk(job_dir):
    gate = threading.Event()
    running = jobs.start('watch', lambda job: gate.wait(5))
    ended = _wait(jobs.start('scan', lambda job: None))['id']
    dead = {'pid': 999999999, 'created': 1.0}
    for record_id, status, seen in (('old-interrupted', 'interrupted', False),
                                    ('old-seen', 'interrupted', True),
                                    ('old-done', 'done', False)):
        jobs._write({'id': record_id, 'kind': 'watch', 'status': status, 'seen': seen,
                     'created_at': 1.0, 'owner': dead})
    try:
        assert [r['id'] for r in jobs.list_jobs(active=True)] == [running]
        assert {r['id'] for r in jobs.list_jobs()} == {running, ended, 'old-interrupted'}
        assert {r['id'] for r in jobs.list_jobs(kind='watch')} == {running, 'old-interrupted'}
        # an ended record is still answered by its id
        assert jobs.get('old-done')['status'] == 'done'
    finally:
        gate.set()
    _wait(running)


def test_seen_marks_an_ended_job_but_never_a_running_one(job_dir):
    gate = threading.Event()
    running = jobs.start('t', lambda job: gate.wait(5))
    assert jobs.mark_seen(running) is False
    assert jobs.get(running)['seen'] is False
    gate.set()
    _wait(running)
    assert [r['id'] for r in jobs.list_jobs(unseen=True)] == [running]
    assert jobs.mark_seen(running) is True
    assert jobs.get(running)['seen'] is True
    assert jobs.list_jobs(unseen=True) == []

    jobs._write({'id': 'disk-running', 'kind': 't', 'status': 'running', 'seen': False,
                 'owner': {'pid': 999999999, 'created': 1.0}})
    assert jobs.mark_seen('disk-running') is False
    assert jobs.get('disk-running')['seen'] is False


# ---- the routes ------------------------------------------------------------------

def test_the_routes_list_answer_cancel_and_mark_seen(job_dir):
    from flask import Flask
    from shared.routes.jobs import jobs_bp
    app = Flask(__name__)
    app.register_blueprint(jobs_bp)
    client = app.test_client()
    started = threading.Event()

    def work(job):
        started.set()
        while not job.should_stop():
            time.sleep(0.01)
        job.check_stop()
    running = jobs.start('watch', work)
    ended = _wait(jobs.start('scan', lambda job: 3))['id']
    assert started.wait(2)

    listing = client.get('/api/jobs?active=1').get_json()
    assert [r['id'] for r in listing['jobs']] == [running]
    assert listing['owner'] == jobs.process_owner()  # the window ends a dead process's jobs by it
    assert [r['id'] for r in client.get('/api/jobs?kind=scan').get_json()['jobs']] == [ended]
    assert client.get(f'/api/jobs/{ended}').get_json()['job']['result'] == 3
    assert client.get('/api/jobs/no-such-job').status_code == 404

    assert client.post(f'/api/jobs/{ended}/cancel').get_json() == {'success': True, 'stopping': False}
    assert client.post(f'/api/jobs/{running}/cancel').get_json() == {'success': True, 'stopping': True}
    assert _wait(running)['status'] == 'cancelled'

    assert client.post(f'/api/jobs/{ended}/seen').get_json() == {'success': True, 'seen': True}
    assert client.get(f'/api/jobs/{ended}').get_json()['job']['seen'] is True
    assert client.post('/api/jobs/..%5Csecret/seen').get_json()['seen'] is False
