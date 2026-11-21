"""Journaled work inside a task: local stages (traced, or resumable from their persisted result),
the once-only claim that guards a tool's side effect, its completion, and the trace export."""

import contextlib
import os
import threading
import time

from . import events, store
from .contracts import StageSpan, digest

from .coordinator import (COORDINATOR_VERSION, _WORK_REVISION, RevisionSuperseded, TaskCancelled,
                          current, _guard, _pop_span, _push_span)


# --------------------------------------------------------------- stage spans

def stage_operation_id(name, version, parameters, inputs):
    """The identity of one stage invocation: name, version, parameters, inputs."""
    return digest([name, version, digest(parameters or {}), list(inputs or ())])


@contextlib.contextmanager
def stage(name, *, version='1', parameters=None, inputs=(), task=None,
          worker_identity=None, cache_hit=None, expected_revision=None):
    """Trace one local stage that ALWAYS executes.

    This context manager does not resume: a `with` block whose body the manager
    decided to skip is a contradiction Python cannot express, and the previous
    version's "cache hit" branch yielded anyway -- so the body ran twice while
    the second span claimed reuse. Resumable work goes through `run_stage`.
    """
    task = task or current()
    if expected_revision is None:
        # The unit of work's revision, not the live one: see `work_unit`.
        expected_revision = _WORK_REVISION.get()
    if expected_revision is None:
        expected_revision = task.revision
    task.checkpoint(expected_revision)
    parameter_hash = digest(parameters or {})
    operation_id = stage_operation_id(name, version, parameters, inputs)
    span = StageSpan(task_id=task.task_id, task_revision=expected_revision, operation_id=operation_id,
                     stage_name=name, stage_version=version, parameter_hash=parameter_hash,
                     input_artifact_hashes=list(inputs), component_version=COORDINATOR_VERSION,
                     queued_at=time.time(), cache_hit=cache_hit,
                     worker_identity=worker_identity or f'{os.getpid()}:{threading.get_ident()}')
    token = _push_span(span)
    span.running_at = time.time()
    task.emit(events.STAGE_STARTED, stage=name, stage_version=version)
    cpu_start = time.process_time()
    try:
        yield span
    except (TaskCancelled, RevisionSuperseded):
        span.cancellation_acknowledged = True
        span.finish('cancelled')
        raise
    except Exception as exc:
        # A body that already named the failure keeps its own name: wrapping a
        # returned `{'error': ...}` in an exception must not relabel it as that
        # wrapper's class.
        span.error_type = span.error_type or type(exc).__name__
        span.error_detail = span.error_detail or str(exc)[:500]
        span.finish('error')
        raise
    else:
        span.completed_at = time.time()
        span.finish('ok')
    finally:
        span.cpu_time_ms = round((time.process_time() - cpu_start) * 1000, 3)
        span.peak_memory_bytes = _peak_memory()
        _pop_span(token)
        task.record_span(span, name=name)
        task.emit(events.STAGE_FINISHED, stage=name, status=span.status, duration_ms=span.duration_ms)


def run_stage(name, function, *, version='1', parameters=None, inputs=(), task=None,
              verify=None, resume=True, expected_revision=None):
    """Run one resumable local stage and return its persisted result.

    The coordinator owns execution, so a recorded completion for the identical
    operation means the body is genuinely NOT called again. `function` receives
    the `StageSpan` and returns a JSON-serialisable result; that result is what
    a later resume hands back.

    `verify(recorded)` guards reuse: a cached result whose artifacts no longer
    exist, or no longer hash to what was recorded, is not reusable and the stage
    runs again. Returning a stale artifact is worse than recomputing one.
    """
    task = task or current()
    if expected_revision is None:
        # The unit of work's revision, not the live one: see `work_unit`.
        expected_revision = _WORK_REVISION.get()
    if expected_revision is None:
        expected_revision = task.revision
    task.checkpoint(expected_revision)
    operation_id = stage_operation_id(name, version, parameters, inputs)
    if resume and task.persist:
        recorded = _guard(store.completed_stage, task.task_id, name, operation_id)
        if recorded is not None and (verify is None or _guard(verify, recorded.get('result'))):
            span = StageSpan(task_id=task.task_id, task_revision=expected_revision,
                             operation_id=operation_id, stage_name=name, stage_version=version,
                             parameter_hash=digest(parameters or {}),
                             input_artifact_hashes=list(inputs),
                             component_version=COORDINATOR_VERSION, cache_hit=True,
                             reused_operation_id=operation_id,
                             output_artifact_hashes=recorded.get('output_artifact_hashes', []),
                             worker_identity=f'{os.getpid()}:{threading.get_ident()}')
            span.queued_at = span.running_at = span.completed_at = time.time()
            span.finish('ok')
            task.record_span(span, name=name)
            task.emit(events.STAGE_FINISHED, stage=name, reused=True, duration_ms=span.duration_ms)
            return recorded.get('result')
    with stage(name, version=version, parameters=parameters, inputs=inputs, task=task,
               cache_hit=False, expected_revision=expected_revision) as span:
        result = function(span)
        if task.persist:
            store.record_stage(task.task_id, name, operation_id, revision=expected_revision,
                               parameter_hash=span.parameter_hash,
                               output={'output_artifact_hashes': span.output_artifact_hashes,
                                       'result': result})
        return result


def _peak_memory():
    """Peak RSS where the platform offers it; None rather than a guess."""
    try:
        import resource
        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
    except ImportError:
        pass
    try:                                         # Windows
        import ctypes
        from ctypes import wintypes

        class _Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                        ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                        ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                        ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                        ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]

        counters = _Counters()
        counters.cb = ctypes.sizeof(counters)
        if ctypes.windll.psapi.GetProcessMemoryInfo(
                ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return int(counters.PeakWorkingSetSize)
    except Exception:
        pass
    return None


# --------------------------------------------------------- side-effect journal

def tool_operation_id(task, tool, fingerprint):
    return digest([task.task_id, task.revision, tool, fingerprint])


@contextlib.contextmanager
def journal_tool(tool, fingerprint, *, task=None, operation_id='', receipt_required=True):
    """Guard one side effect so a repeated model answer cannot run it twice.

    Yields a `_ToolClaim`. When `claim.claimed` is False the operation already
    started, finished or is unresolved under this exact fingerprint, and the
    caller must reuse `claim.record['result']` rather than executing. Unlike the
    tracing helpers this is NOT best-effort: if the journal cannot be written,
    the effect does not run, because an unjournalled download is exactly the
    duplicate this prevents.

    Completing requires a receipt (`claim.complete(result)`): an entry that says
    `completed` with nothing attached cannot be reused, only believed.
    """
    task = task or current()
    operation_id = operation_id or tool_operation_id(task, tool, fingerprint)
    if not task.persist:
        yield _ToolClaim(True, None, operation_id, None, receipt_required=False)
        return
    claimed, record = store.begin_tool(operation_id, tool, fingerprint,
                                       task_id=task.task_id, task_revision=task.revision)
    claim = _ToolClaim(claimed, record, operation_id, task, receipt_required=receipt_required)
    if not claimed:
        yield claim
        return
    try:
        yield claim
    except (TaskCancelled, RevisionSuperseded):
        store.finish_tool(operation_id, 'cancelled', {'note': 'Cancelled before completion.'})
        raise
    except Exception as exc:
        store.finish_tool(operation_id, 'failed', {'error': f'{type(exc).__name__}: {str(exc)[:300]}'})
        raise
    else:
        if not claim.settled:
            if receipt_required:
                store.finish_tool(operation_id, 'unresolved',
                                  {'note': 'The operation ended without recording a result.'})
                raise RuntimeError(
                    f'{tool} finished without recording its result; the operation is unresolved.')
            store.finish_tool(operation_id, 'completed', {'note': 'completed'})


class _ToolClaim:
    """The handle `journal_tool` yields. Tuple-compatible with the old shape."""

    def __init__(self, claimed, record, operation_id, task, *, receipt_required=True):
        self.claimed = claimed
        self.record = record
        self.operation_id = operation_id
        self.task = task
        self.receipt_required = receipt_required
        self.settled = False

    def __iter__(self):                       # `claimed, previous = claim`
        return iter((self.claimed, self.record))

    @property
    def result(self):
        return (self.record or {}).get('result')

    def complete(self, result, *, receipt=None):
        """Record what the effect actually produced. Required to complete."""
        self.settled = True
        if self.task is not None and self.task.persist:
            store.finish_tool(self.operation_id, 'completed', result, receipt=receipt)
        return result

    def fail(self, error):
        self.settled = True
        if self.task is not None and self.task.persist:
            store.finish_tool(self.operation_id, 'failed', {'error': str(error)[:300]})


def export_trace(task_id=None, path=None):
    task_id = task_id or current().task_id
    return store.export_trace(task_id, path)
