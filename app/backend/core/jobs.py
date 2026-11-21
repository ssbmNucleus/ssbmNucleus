"""Background jobs: one status, one event, a record on disk, cleanup after a death.

Every long operation the app runs off the request thread goes through here
instead of keeping its own status dict, flags, events and poll route:

    job_id = jobs.start('vault_restore', run, label='Vault restore', params={...})

    def run(job):
        job.progress(0.1, 'Reading backup…')
        job.own('staging', str(staging))   # cleaned up if the process dies
        ...
        job.release('staging')
        return {'message': 'Done'}          # the job's result

What every job gets for free:

- **One status.** ``queued`` -> ``running`` -> ``done`` | ``failed`` |
  ``cancelled`` | ``interrupted``. ``running`` is set inside the ``try`` and the
  ``finally`` always writes a final status, so an exception can never leave a job
  "running" until restart. ``failed`` always carries an ``error``.
- **One event.** Every change emits ``job`` on the socket with the whole record
  (it carries the job's id and kind), and ``GET /api/jobs`` answers the same
  records, so the window can always ask instead of remembering.
- **A record on disk** (``output/jobs/<id>.json``), written on every status
  change and every ``own``/``release``, never on progress ticks. A kind
  registered with ``keep`` (one that runs often and owns nothing) stays in
  memory instead, its newest ``keep`` ended jobs only.
- **Cleanup.** A kind registers ``cleanup(name, value) -> note|None``. Whatever a
  job still owns when it ends is cleaned up then; whatever it owned when the
  process died is cleaned up by ``recover_interrupted()`` at the next start,
  which also marks the job ``interrupted``. The note it returns is shown to the
  user once (``seen``). Owned items are undone newest first, so a process is
  closed before the files it holds open are deleted.
- **critical** registers the job with ``core.critical_ops`` for its whole run,
  so quitting waits for it. **single** refuses a second job of the kind while
  one is active (``JobBusy`` carries the running job's id).

Records name the process that owns them (pid + start time). Recovery skips a
record whose owner is still alive, so a second backend (a worker child, the
test harness) never "recovers" a job another live backend is running.
"""
import itertools
import json
import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

ACTIVE = frozenset({'queued', 'running'})
FINAL = frozenset({'done', 'failed', 'cancelled', 'interrupted'})
KEEP_SECONDS = 7 * 24 * 3600

_lock = threading.RLock()
_jobs: dict = {}      # id -> Job, this process's jobs
_kinds: dict = {}     # kind -> {'cleanup': fn|None, 'label': str}
_seq = itertools.count(1)
_root_override = None
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}')


class JobBusy(Exception):
    """A ``single`` kind already has an active job."""

    def __init__(self, kind, job_id):
        super().__init__(f'A {kind} job is already running')
        self.kind = kind
        self.job_id = job_id


class Cancelled(Exception):
    """Raised by a job function (or ``job.check_stop()``) to end as ``cancelled``."""


def _record_path(job_id):
    """Where a job's record lives, or None for an id that is not a plain name
    (ids reach here from URLs)."""
    if not isinstance(job_id, str) or not _ID.fullmatch(job_id):
        return None
    return _root() / f'{job_id}.json'


def _root():
    if _root_override is not None:
        return Path(_root_override)
    from core.config import OUTPUT_PATH
    return Path(OUTPUT_PATH) / 'jobs'


def _owner():
    pid = os.getpid()
    try:
        import psutil
        created = psutil.Process(pid).create_time()
    except Exception:  # noqa: BLE001 - liveness check degrades to pid only
        created = None
    return {'pid': pid, 'created': created}


_OWNER = _owner()


def _owner_alive(owner):
    if not isinstance(owner, dict) or not owner.get('pid'):
        return False
    if owner['pid'] == _OWNER['pid'] and owner.get('created') == _OWNER['created']:
        return True
    try:
        import psutil
        process = psutil.Process(owner['pid'])
        created = owner.get('created')
        return created is None or abs(process.create_time() - created) < 1.0
    except Exception:  # noqa: BLE001 - gone, or not ours to inspect
        return False


def process_owner():
    """This process, as a record names its owner (other journals use it too)."""
    return dict(_OWNER)


def owner_alive(owner):
    """True while the process a record names is still running."""
    return _owner_alive(owner)


def register_kind(kind, *, label=None, cleanup=None, keep=None, on_cancel=None):
    """Declare a job kind: its user-facing label and how to clean up what it owned.

    ``cleanup(name, value)`` undoes one owned resource and returns a short note for
    the user (or None). It runs after the job ends with the resource still owned,
    and at the next start for a job the process died in. It must be idempotent.

    ``keep`` is for a kind that runs often and owns nothing (the replay scan the
    cloud loop starts every ten minutes): its records stay in memory, never on
    disk, so a death leaves nothing to recover or report, and only its newest
    ``keep`` ended jobs are remembered.

    ``on_cancel(job)`` is for a kind whose work blocks where it cannot check
    ``should_stop`` (it waits on a Dolphin): ``cancel`` calls it after setting the
    stop, and it makes that work end, for instance by closing the process. The
    job still ends through its own function. Because the hook breaks the work on
    purpose, a job of such a kind that fails after its Cancel ends ``cancelled``.
    """
    with _lock:
        _kinds[kind] = {'label': label or kind, 'cleanup': cleanup, 'keep': keep,
                        'on_cancel': on_cancel}


class Job:
    def __init__(self, kind, *, job_id=None, label=None, params=None, project=None):
        self.id = job_id or str(uuid.uuid4())
        self.kind = kind
        self.label = label or _kinds.get(kind, {}).get('label') or kind
        self.status = 'queued'
        self.fraction = None
        self.detail = ''
        self.error = None
        self.result = None
        self.params = dict(params or {})
        self.project = str(project) if project is not None else None
        self.owned = {}
        self.notes = []
        self.extra = {}
        self.seen = False
        self.created_at = time.time()
        self.started_at = None
        self.ended_at = None
        self.seq = next(_seq)
        self._stop = threading.Event()

    # -- for the job function -------------------------------------------------
    def progress(self, fraction=None, detail=None, **extra):
        """Report progress (0..1) and/or a status line; extra keys ride along."""
        with _lock:
            if fraction is not None:
                self.fraction = max(0.0, min(1.0, float(fraction)))
            if detail is not None:
                self.detail = str(detail)
            self.extra.update(extra)
            self.seq = next(_seq)
        _emit(self)

    def should_stop(self):
        return self._stop.is_set()

    @property
    def stop_event(self):
        """The stop as a ``threading.Event``, for work that waits on it or hands
        it to code that polls ``is_set()`` (the in-game Dolphin boot)."""
        return self._stop

    def check_stop(self):
        if self._stop.is_set():
            raise Cancelled()

    def own(self, name, value):
        """Record something to clean up if this job ends or dies holding it.
        Owning a name again makes it the newest (cleanup runs newest first)."""
        with _lock:
            self.owned.pop(name, None)
            self.owned[name] = value
            self.seq = next(_seq)
        _persist(self)

    def release(self, name):
        with _lock:
            self.owned.pop(name, None)
            self.seq = next(_seq)
        _persist(self)

    # -- the record -----------------------------------------------------------
    def snapshot(self):
        with _lock:
            return {
                'id': self.id, 'kind': self.kind, 'label': self.label,
                'status': self.status, 'progress': self.fraction, 'detail': self.detail,
                'error': self.error, 'result': self.result, 'params': self.params,
                'project': self.project, 'owned': dict(self.owned), 'notes': list(self.notes),
                'extra': dict(self.extra), 'seen': self.seen,
                'created_at': self.created_at, 'started_at': self.started_at,
                'ended_at': self.ended_at, 'seq': self.seq, 'owner': _OWNER,
            }


def _write(record):
    import file_retry
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    path = _record_path(record['id'])
    tmp = root / f".{record['id']}.{uuid.uuid4().hex}.tmp"
    tmp.write_text(json.dumps(record, default=str), encoding='utf-8')
    try:
        # Windows refuses the replace while a reader holds the record open.
        file_retry.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _persist(job):
    if _kinds.get(job.kind, {}).get('keep') is None:
        try:
            _write(job.snapshot())
        except Exception:  # noqa: BLE001 - the in-memory record still serves
            logger.exception('Could not persist job %s', job.id)
    _emit(job)


def _forget_old(kind):
    """Drop all but the newest ``keep`` ended jobs of a kind that keeps few."""
    keep = _kinds.get(kind, {}).get('keep')
    if keep is None:
        return
    with _lock:
        ended = sorted((job for job in _jobs.values()
                        if job.kind == kind and job.status in FINAL),
                       key=lambda job: job.seq, reverse=True)
        for job in ended[keep:]:
            _jobs.pop(job.id, None)


def _emit(job):
    try:
        from core.state import get_socketio
        socketio = get_socketio()
        if socketio is not None:
            socketio.emit('job', job.snapshot())
    except Exception:  # noqa: BLE001 - a missed event is recovered by GET /api/jobs
        logger.debug('job emit failed', exc_info=True)


def _set(job, **fields):
    with _lock:
        for key, value in fields.items():
            setattr(job, key, value)
        job.seq = next(_seq)
    _persist(job)


def active_job(kind):
    """This process's active job of ``kind``, or None."""
    with _lock:
        for job in _jobs.values():
            if job.kind == kind and job.status in ACTIVE:
                return job
    return None


def start(kind, fn, *, label=None, params=None, project=None, job_id=None,
          single=False, critical=False, thread_name=None, owned=None):
    """Run ``fn(job)`` in a thread; returns the job id at once.

    ``fn`` returns the job's result (JSON-serialisable) or raises. Raise
    ``Cancelled`` (or call ``job.check_stop()``) to end as cancelled. ``owned``
    is what the job owns from its first record (an upload the caller saved), so
    it is cleaned up even if the process dies before ``fn`` runs.
    """
    with _lock:
        if single:
            running = active_job(kind)
            if running is not None:
                raise JobBusy(kind, running.id)
        if job_id is not None:
            if _record_path(job_id) is None:
                raise ValueError(f'Invalid job id: {job_id!r}')
            if job_id in _jobs or _record_path(job_id).exists():
                raise ValueError(f'Job id already used: {job_id}')
        job = Job(kind, job_id=job_id, label=label, params=params, project=project)
        job.owned.update(owned or {})
        _jobs[job.id] = job
    _persist(job)
    try:
        threading.Thread(target=_run, args=(job, fn, critical),
                         name=thread_name or f'job-{kind}', daemon=True).start()
    except Exception as e:
        # No thread will ever run it: end it here, or a single kind stays busy.
        _cleanup_owned(job)
        _set(job, status='failed', error=str(e) or type(e).__name__, ended_at=time.time())
        _forget_old(kind)
        raise
    return job.id


def run_inline(kind, fn, *, label=None, params=None, project=None, job_id=None,
               single=False, critical=False):
    """Run a job on the calling thread (a request that does its work while the
    client waits). Same record, events and cleanup as ``start``; returns the
    final snapshot."""
    with _lock:
        running = active_job(kind) if single else None
        if running is not None:
            raise JobBusy(kind, running.id)
        job = Job(kind, job_id=job_id, label=label, params=params, project=project)
        _jobs[job.id] = job
    _persist(job)
    _run(job, fn, critical)
    return job.snapshot()


def _run(job, fn, critical):
    token = None
    end = {'status': 'failed', 'error': 'The job ended without a result.'}
    try:
        if critical:
            from core import critical_ops
            token = critical_ops.begin(job.label)
        _set(job, status='running', started_at=time.time())
        result = fn(job)
        end = {'status': 'done', 'result': result,
               'fraction': 1.0 if job.fraction is not None else None}
    except Cancelled:
        end = {'status': 'cancelled', 'error': None}
    except Exception as e:  # noqa: BLE001 - every failure becomes the job's status
        if job._stop.is_set() and _kinds.get(job.kind, {}).get('on_cancel') is not None:
            # Its Cancel closed what the work waited on; that is why it failed.
            logger.info('Job %s (%s) ended by its Cancel: %s', job.id, job.kind, e)
            end = {'status': 'cancelled', 'error': None}
        else:
            logger.error('Job %s (%s) failed: %s', job.id, job.kind, e, exc_info=True)
            end = {'status': 'failed', 'error': str(e) or type(e).__name__}
    finally:
        # What it still owns is put back before the final status goes out, so
        # the next job of a single kind cannot start while this one holds it.
        _cleanup_owned(job)
        _set(job, ended_at=time.time(), **end)
        _forget_old(job.kind)
        if token is not None:
            from core import critical_ops
            critical_ops.end(token)


def _cleanup_owned(job):
    cleanup = _kinds.get(job.kind, {}).get('cleanup')
    # Newest first: what was taken last may hold what was taken before it
    # (a render's Dolphin has its throwaway ISO open).
    for name, value in reversed(list(job.owned.items())):
        if cleanup is None:
            logger.warning('Job %s ended owning %s=%s and its kind has no cleanup', job.id, name, value)
            continue
        try:
            note = cleanup(name, value)
            if note:
                job.notes.append(note)
            job.owned.pop(name, None)
        except Exception:  # noqa: BLE001 - keep it owned so the next start retries
            logger.exception('Cleanup of %s=%s for job %s failed', name, value, job.id)


def cancel(job_id):
    """Ask a running job to stop; it ends ``cancelled`` when its function notices."""
    with _lock:
        job = _jobs.get(job_id)
    if job is None or job.status not in ACTIVE:
        return False
    job._stop.set()
    job.progress(detail='Stopping…')
    on_cancel = _kinds.get(job.kind, {}).get('on_cancel')
    if on_cancel is not None:
        try:
            on_cancel(job)
        except Exception:  # noqa: BLE001 - the stop is set; the job may still notice it
            logger.exception('Cancel hook for job %s failed', job.id)
    return True


def get(job_id):
    """A job's record: this process's, else the one on disk, else None."""
    with _lock:
        job = _jobs.get(job_id)
    if job is not None:
        return job.snapshot()
    path = _record_path(job_id)
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def list_jobs(*, kind=None, active=False, unseen=False):
    """This process's jobs plus, from disk, interrupted jobs the user has not
    seen yet (a restore the last session died in), newest first."""
    with _lock:
        records = {job.id: job.snapshot() for job in _jobs.values()}
    if not active:
        try:
            for path in _root().glob('*.json'):
                if path.stem in records:
                    continue
                try:
                    record = json.loads(path.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    continue
                if record.get('status') == 'interrupted' and not record.get('seen'):
                    records[record['id']] = record
        except OSError:
            pass
    out = [r for r in records.values()
           if (kind is None or r.get('kind') == kind)
           and (not active or r.get('status') in ACTIVE)
           and (not unseen or not r.get('seen'))]
    return sorted(out, key=lambda r: r.get('created_at') or 0, reverse=True)


def mark_seen(job_id):
    """The user has seen this ended job's outcome; it stops being listed.
    False for a job that has not ended (nothing is marked) or is unknown."""
    with _lock:
        job = _jobs.get(job_id)
        marked = job is not None and job.status in FINAL
        if marked:
            job.seen = True
            job.seq = next(_seq)
    if job is not None:
        if marked:
            _persist(job)
        return marked
    path = _record_path(job_id)
    if path is None:
        return False
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
        if record.get('status') not in FINAL:
            return False
        record['seen'] = True
        _write(record)
        return True
    except (OSError, ValueError):
        return False


def _clean_record(record, notes):
    """Run the kind's cleanup on what a dead job's record still owns; an item whose
    cleanup fails stays owned so the next start tries again."""
    cleanup = _kinds.get(record.get('kind'), {}).get('cleanup')
    owned = dict(record.get('owned') or {})
    for name, value in reversed(list(owned.items())):   # newest first, as at job end
        if cleanup is None:
            logger.warning('Job %s owned %s=%s; its kind registers no cleanup',
                           record.get('id'), name, value)
            continue
        try:
            note = cleanup(name, value)
            if note:
                notes.append(note)
            owned.pop(name, None)
        except Exception:  # noqa: BLE001 - left owned; the next start retries
            logger.exception('Recovery cleanup of %s=%s failed', name, value)
    return owned


def recover_interrupted():
    """At startup: every record still active whose owner is gone becomes
    ``interrupted``, and what it owned is cleaned up (also what an ended job's
    failed cleanup left owned). Old ended records go. Returns the records that
    were interrupted."""
    recovered = []
    now = time.time()
    try:
        paths = list(_root().glob('*.json'))
    except OSError:
        return recovered
    for path in paths:
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if _owner_alive(record.get('owner')):
            continue
        notes = list(record.get('notes') or [])
        if record.get('status') in FINAL:
            if record.get('owned'):
                record.update(owned=_clean_record(record, notes), notes=notes, seen=False)
                try:
                    _write(record)
                except OSError:
                    logger.exception('Could not update job %s', record.get('id'))
            elif now - (record.get('ended_at') or record.get('created_at') or now) > KEEP_SECONDS:
                path.unlink(missing_ok=True)
            continue
        owned = _clean_record(record, notes)
        record.update(status='interrupted', owned=owned, notes=notes, ended_at=now, seen=False,
                      error=record.get('error') or 'Nucleus closed while this was running.')
        try:
            _write(record)
        except OSError:
            logger.exception('Could not record interrupted job %s', record.get('id'))
        logger.warning('Job %s (%s) was interrupted by the last shutdown; notes: %s',
                       record.get('id'), record.get('kind'), notes)
        recovered.append(record)
    return recovered
