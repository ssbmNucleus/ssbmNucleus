"""No MCP request runs for minutes: every tools/call works on a thread of its own, and one still running after
``INLINE_SECONDS`` is answered with a job id instead of its result. The work goes on; ``job_status`` with that id
returns the result when it is in (the same content the call would have returned).

MCP clients time out a request after about a minute (Claude Desktop) and the relay is a plain HTTP request, so
this keeps a slow call (a portrait render, a batch download, a delivery that rebuilds a disc) from failing in the
client while it still runs in the app. These call jobs are memory only: they belong to this backend process, and a
restart forgets them. The model import is a real app job instead (model_jobs.py).
"""
import logging
import threading
import time
import uuid

from . import content

INLINE_SECONDS = 45.0       # how long a call is waited for before it is answered with a job id
KEEP_SECONDS = 3600.0       # a finished call's result is kept this long for job_status
KEEP_COUNT = 64             # and at most this many finished calls
PREFIX = 'call-'

_lock = threading.Lock()
_calls = {}                 # id -> record

_log = logging.getLogger(__name__)


def _trim(now):
    finished = sorted((r for r in _calls.values() if r['ended_at'] is not None), key=lambda r: r['ended_at'])
    excess = len(finished) - KEEP_COUNT
    for index, record in enumerate(finished):
        if index < excess or now - record['ended_at'] > KEEP_SECONDS:
            _calls.pop(record['id'], None)


def run(tool, work, *, wait=None):
    """Run ``work()`` (-> an MCP tools/call result) for ``tool``. -> its result, or a job reply when it is still
    running after ``wait`` seconds (default ``INLINE_SECONDS``)."""
    call_id = PREFIX + uuid.uuid4().hex
    record = {'id': call_id, 'tool': tool, 'started_at': time.time(), 'ended_at': None, 'result': None,
              'done': threading.Event()}

    def body():
        try:
            record['result'] = work()
        except Exception as exc:  # noqa: BLE001 - a call that fails is an isError result, never a dead thread
            _log.exception('MCP tool %s failed', tool)
            record['result'] = content.error(f'{tool} failed unexpectedly: {type(exc).__name__}: {str(exc)[:400]}')
        finally:
            record['ended_at'] = time.time()
            record['done'].set()

    with _lock:
        _trim(time.time())
        _calls[call_id] = record
    threading.Thread(target=body, name=f'mcp-{tool}', daemon=True).start()
    if record['done'].wait(INLINE_SECONDS if wait is None else wait):
        with _lock:
            _calls.pop(call_id, None)
        return record['result']
    return content.tool_result(tool, {
        'job_id': call_id, 'status': 'running', 'tool': tool,
        'note': f'{tool} is still working in Nucleus. It keeps running; call job_status with this job_id to get its '
                'result (job_status waits for it). Do not call it again meanwhile.'})


def status(call_id, wait=0):
    """A call job's state as an MCP result, or None when this process has no such call. ``wait`` seconds are given
    to a running call to end first (job_status long-polls, so a client needs no sleep tool)."""
    with _lock:
        record = _calls.get(call_id)
    if record is None:
        return None
    if wait:
        record['done'].wait(wait)
    ended = record['ended_at']
    head = {'job_id': call_id, 'tool': record['tool'], 'status': 'running' if ended is None else 'done',
            'seconds': round((ended or time.time()) - record['started_at'], 1)}
    if ended is None:
        return content.tool_result(record['tool'], dict(head, note='Still running. Call job_status again.'))
    result = record['result'] or content.error('The call ended without a result.')
    return {'content': [content.text(head)] + list(result.get('content') or []),
            'isError': bool(result.get('isError'))}
