"""Durable task journal: SQLite is the operational truth, JSONL is the export.

Location follows the app's existing per-user data directory -- the same
`config.STORAGE_PATH` that `assistant/store.py` (chats.db) resolves at call
time, so the `vault` test fixture's monkeypatch reaches this module too and a
packaged build never writes into a PyInstaller extraction directory that
disappears on exit:

    <STORAGE_PATH>/assistant/tasks/tasks.db          the journal
    <STORAGE_PATH>/assistant/tasks/artifacts/<task>/ that task's artifact dir
    <STORAGE_PATH>/assistant/tasks/traces/           exported JSONL

What is written here has to survive a crash mid-import and a restart, because
the coordinator resumes from recorded stages rather than replaying blindly. Two
consequences shape the schema:

* **Spans are append-only rows keyed by (span_id, attempt).** A retried request
  is a second row, never an update of the first, so two attempts and one charge
  cannot collapse into one attempt or two charges.
* **The tool journal records intent before the side effect and the result
  after.** A repeated model answer finds the `started` row and refuses, which is
  what stops a retry from downloading or committing twice.

Costs are stored as text so `unknown` stays `unknown` in the row. A NULL would
read as "not filled in yet" and a 0 would read as "free"; neither is true.
"""
import copy
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

from core import config, storage_handles
from . import contracts
from .contracts import UNKNOWN, ModelSpan, StageSpan, TaskResult, Wish

SCHEMA_VERSION = 1
_local = threading.local()
# Every thread's open connection, so close_all() can reach them all; a bumped
# generation makes each thread reopen on its next connect().
_open = set()
_open_lock = threading.Lock()
_generation = 0


class StaleRevision(RuntimeError):
    """A writer holding an older revision tried to overwrite a newer one."""


class SettlementRefused(ValueError):
    """A decision/approval response that does not name a live, matching request."""


class JournalConflict(ValueError):
    """An operation id already exists for a different task, tool or fingerprint."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL DEFAULT 1,
    chat_id TEXT,
    workflow TEXT,
    workflow_version INTEGER DEFAULT 1,
    family TEXT,
    request TEXT,
    envelope TEXT NOT NULL,
    state TEXT NOT NULL,
    outcome TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    config_snapshot TEXT
);
CREATE TABLE IF NOT EXISTS task_revisions (
    task_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    reason TEXT,
    request TEXT,
    created_at REAL NOT NULL,
    PRIMARY KEY (task_id, revision)
);
-- Append-only. One row per ATTEMPT: (span_id, attempt) is the key so a retry
-- adds a row instead of overwriting the attempt that already billed.
CREATE TABLE IF NOT EXISTS spans (
    span_id TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    task_id TEXT,
    task_revision INTEGER,
    parent_span_id TEXT,
    operation_id TEXT,
    kind TEXT NOT NULL,
    name TEXT,
    status TEXT,
    start_utc REAL,
    duration_ms REAL,
    reported_cost TEXT,
    cost_status TEXT,
    data TEXT NOT NULL,
    PRIMARY KEY (span_id, attempt)
);
CREATE INDEX IF NOT EXISTS spans_by_task ON spans (task_id, start_utc);
CREATE TABLE IF NOT EXISTS stages (
    task_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    status TEXT NOT NULL,
    parameter_hash TEXT,
    output TEXT,
    completed_at REAL,
    PRIMARY KEY (task_id, stage_name, operation_id)
);
-- The side-effect journal. `started` is written BEFORE the effect runs.
CREATE TABLE IF NOT EXISTS tool_journal (
    operation_id TEXT PRIMARY KEY,
    task_id TEXT,
    task_revision INTEGER,
    tool TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL,
    result TEXT,
    receipt TEXT,
    started_at REAL NOT NULL,
    completed_at REAL,
    reconciled_at REAL
);
CREATE INDEX IF NOT EXISTS journal_by_fingerprint ON tool_journal (task_id, fingerprint);
CREATE TABLE IF NOT EXISTS approvals (
    request_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    task_revision INTEGER NOT NULL,
    kind TEXT NOT NULL,
    operation_id TEXT,
    operation_digest TEXT,
    status TEXT NOT NULL,
    payload TEXT,
    created_at REAL NOT NULL,
    settled_at REAL
);
CREATE INDEX IF NOT EXISTS approvals_by_task ON approvals (task_id, status);
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,
    revision INTEGER,
    kind TEXT NOT NULL,
    at REAL NOT NULL,
    payload TEXT
);
CREATE INDEX IF NOT EXISTS events_by_task ON events (task_id, seq);
CREATE TABLE IF NOT EXISTS wishes (
    wish_id TEXT PRIMARY KEY,
    task_id TEXT,
    dedupe_key TEXT NOT NULL,
    capability TEXT NOT NULL,
    record_status TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS wishes_by_dedupe ON wishes (dedupe_key);
CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT);
"""


def root():
    """The task subsystem's directory under the app's existing data root."""
    directory = Path(config.STORAGE_PATH) / 'assistant' / 'tasks'
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def artifact_dir(task_id):
    """Where a task's produced bytes live: beside the journal, not in %TEMP%.

    A frozen build's `sys._MEIPASS` is deleted on exit, so an artifact written
    there cannot be re-verified after a restart -- and re-verification is the
    whole point of content-addressed evidence.
    """
    directory = root() / 'artifacts' / str(task_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def trace_dir():
    directory = root() / 'traces'
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _db_path():
    return root() / 'tasks.db'


def connect():
    """A per-thread connection, reopened when the storage root moves.

    Tests repoint `config.STORAGE_PATH` per test; caching the path alongside the
    handle means a stale connection is never silently reused against the
    previous test's temp directory.
    """
    path = _db_path()
    conn = getattr(_local, 'conn', None)
    if (conn is not None and getattr(_local, 'path', None) == path
            and getattr(_local, 'generation', None) == _generation):
        return conn
    if conn is not None:
        _drop(conn)
    generation = _generation
    conn = sqlite3.connect(path, timeout=15, check_same_thread=False)
    with _open_lock:
        _open.add(conn)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.executescript(SCHEMA)
    conn.execute('INSERT OR REPLACE INTO schema_meta VALUES (?,?)', ('version', str(SCHEMA_VERSION)))
    conn.commit()
    _local.conn, _local.path, _local.generation = conn, path, generation
    return conn


def _drop(conn):
    with _open_lock:
        _open.discard(conn)
    try:
        conn.close()
    except sqlite3.Error:
        pass


def close():
    conn = getattr(_local, 'conn', None)
    if conn is not None:
        _drop(conn)
    _local.conn = _local.path = None


def close_all():
    """Close every thread's connection to the journal, so nothing holds tasks.db open while a Vault restore swaps
    the storage folder (core/storage_handles.py). Each thread reopens on its next connect()."""
    global _generation
    with _open_lock:
        _generation += 1
        conns = list(_open)
        _open.clear()
    for conn in conns:
        try:
            conn.close()
        except sqlite3.Error:
            pass


storage_handles.register(close_all)


def _cost_text(value):
    """Store a charge as text so `unknown` survives the round trip."""
    return 'unknown' if isinstance(value, contracts._Unknown) or value is None else repr(float(value))


def _cost_value(text):
    if text in (None, '', 'unknown'):
        return UNKNOWN
    try:
        return float(text)
    except (TypeError, ValueError):
        return UNKNOWN


# --------------------------------------------------------------------- tasks

def create_task(envelope, *, chat_id=None, family='', request='', config_snapshot=None):
    """Insert a task, or return the existing one: creation is idempotent."""
    envelope.validate()
    conn = connect()
    now = time.time()
    with conn:
        conn.execute(
            'INSERT INTO tasks (task_id,revision,chat_id,workflow,workflow_version,family,request,'
            'envelope,state,outcome,created_at,updated_at,config_snapshot) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) '
            'ON CONFLICT(task_id) DO NOTHING',
            (envelope.task_id, envelope.revision, chat_id, envelope.workflow, envelope.workflow_version,
             family, request, json.dumps(envelope.to_dict()), envelope.state, envelope.outcome,
             now, now, json.dumps(config_snapshot or {})))
        conn.execute('INSERT OR IGNORE INTO task_revisions VALUES (?,?,?,?,?)',
                     (envelope.task_id, envelope.revision, 'created', request, now))
    return envelope.task_id


def save_task(envelope, *, expect_revision=None):
    """Persist an envelope, refusing a writer whose revision is already stale.

    The row's revision is the authority. A context that was started under
    revision 1 and kept working must not overwrite the envelope of revision 2;
    without the conditional UPDATE the older writer simply wins the race and the
    user's revision silently disappears.
    """
    envelope.validate()
    conn = connect()
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT revision FROM tasks WHERE task_id=?', (envelope.task_id,)).fetchone()
        if row is None:
            raise ValueError('Unknown task.')
        if expect_revision is not None and row['revision'] != expect_revision:
            raise StaleRevision(f'task revision moved to {row["revision"]}; this writer holds {expect_revision}')
        if envelope.revision < row['revision']:
            raise StaleRevision(f'task revision is {row["revision"]}; refusing a write for {envelope.revision}')
        conn.execute('UPDATE tasks SET revision=?,envelope=?,state=?,outcome=?,workflow=?,'
                     'workflow_version=?,updated_at=? WHERE task_id=?',
                     (envelope.revision, json.dumps(envelope.to_dict()), envelope.state, envelope.outcome,
                      envelope.workflow, envelope.workflow_version, time.time(), envelope.task_id))
    return envelope


def load_task(task_id):
    row = connect().execute('SELECT envelope FROM tasks WHERE task_id=?', (task_id,)).fetchone()
    return TaskResult.from_dict(json.loads(row['envelope'])) if row else None


def task_row(task_id):
    row = connect().execute('SELECT * FROM tasks WHERE task_id=?', (task_id,)).fetchone()
    return dict(row) if row else None


def revise_task(task_id, reason, request, envelope):
    """Bump the revision, stale every older pending request, and save the
    envelope -- as ONE commit.

    Three separate commits could be interrupted between any two of them, and
    each intermediate state is a lie the app would act on: a revision column
    ahead of its envelope, or an approval still pending for a request that no
    longer exists. `envelope` is mutated in place to the new revision.
    """
    conn = connect()
    now = time.time()
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT revision,state FROM tasks WHERE task_id=?', (task_id,)).fetchone()
        if not row:
            raise ValueError('Unknown task.')
        if row['state'] in ('completed', 'failed', 'cancelled'):
            raise ValueError('That task has finished; start a new one instead of revising it.')
        revision = row['revision'] + 1
        stale = [r['request_id'] for r in conn.execute(
            "SELECT request_id FROM approvals WHERE task_id=? AND status='pending'", (task_id,))]
        # Revise a COPY and publish it only after the commit succeeds. Mutating
        # the caller's envelope first meant an injected validation failure left
        # live revision 2 against durable revision 1 -- memory ahead of SQLite,
        # which is the state every other guard here assumes cannot happen.
        proposed = copy.deepcopy(envelope)
        proposed.revision = revision
        if proposed.next is not None:
            proposed.next.status = 'invalidated'
            if proposed.next.id not in stale:
                stale.append(proposed.next.id)
            proposed.next = None
        if proposed.state in ('waiting_decision', 'waiting_approval'):
            proposed.state = 'running'
        proposed.validate()
        conn.execute('INSERT OR REPLACE INTO task_revisions VALUES (?,?,?,?,?)',
                     (task_id, revision, reason, request, now))
        conn.executemany("UPDATE approvals SET status='invalidated',settled_at=? WHERE request_id=?",
                         [(now, request_id) for request_id in stale])
        conn.execute('UPDATE tasks SET revision=?,envelope=?,state=?,outcome=?,updated_at=? WHERE task_id=?',
                     (revision, json.dumps(proposed.to_dict()), proposed.state, proposed.outcome,
                      now, task_id))
    # Committed. Only now does the caller's live object move.
    envelope.revision = proposed.revision
    envelope.next = proposed.next
    envelope.state = proposed.state
    return revision, stale


def current_revision(task_id):
    row = connect().execute('SELECT revision FROM tasks WHERE task_id=?', (task_id,)).fetchone()
    return row['revision'] if row else None


def current_task_revision(task_id):
    """The authoritative revision of a task, or None when nothing tracks it.

    The proposal's own saved revision is what the user was shown; it cannot
    also be the thing that proves the request has not moved since. This reads
    the task store instead, so a revised or cancelled request invalidates an
    approval that was about the old one. The build commit
    (``nucleus_api/builds.py``) asks here; ``core.build_authorization.verify``
    takes the answer as an argument, so core never imports the assistant.

    Args:
        task_id: the task the proposal names.

    Returns:
        dict: ``{'revision': int|None, 'cancelled': bool, 'known': bool}``.

    Example:
        >>> current_task_revision('task_1')
        {'revision': 2, 'cancelled': False, 'known': True}
    """
    if not (task_id or '').strip():
        return {'revision': None, 'cancelled': False, 'known': False}
    try:
        row = task_row(task_id)
    except Exception:                                          # noqa: BLE001
        return {'revision': None, 'cancelled': False, 'known': False}
    if not row:
        return {'revision': None, 'cancelled': False, 'known': False}
    state = (row['state'] if 'state' in row.keys() else None) if hasattr(row, 'keys') \
        else getattr(row, 'state', None)
    revision = (row['revision'] if 'revision' in row.keys() else None) if hasattr(row, 'keys') \
        else getattr(row, 'revision', None)
    return {'revision': int(revision) if revision is not None else None,
            'cancelled': state == 'cancelled', 'known': revision is not None}


def last_task_for_chat(chat_id):
    """The most recent task for a conversation, with its facts and accounting.

    Used to carry a budget-blocked attempt's spend into the turn that continues
    it: a fresh "continue" must not silently reset a spending limit.
    """
    row = connect().execute('SELECT * FROM tasks WHERE chat_id=? ORDER BY created_at DESC LIMIT 1',
                            (chat_id,)).fetchone()
    if not row:
        return None
    envelope = json.loads(row['envelope'])
    return {**dict(row), 'facts': envelope.get('facts') or {},
            'outcome': envelope.get('outcome'), 'accounting': accounting(row['task_id'])}


def unfinished_tasks(limit=50):
    """Tasks a restart has to reconcile: still in flight when the process died."""
    rows = connect().execute(
        "SELECT * FROM tasks WHERE state NOT IN ('completed','failed','cancelled') "
        'ORDER BY updated_at DESC LIMIT ?', (limit,))
    return [dict(row) for row in rows]


# --------------------------------------------------------------------- spans

def record_span(span, *, name=''):
    """Append one span attempt. Never an UPDATE of a different attempt."""
    data = span.to_dict()
    conn = connect()
    reported = getattr(span, 'reported_cost_usd', None)
    with conn:
        conn.execute(
            'INSERT INTO spans (span_id,attempt,task_id,task_revision,parent_span_id,operation_id,'
            'kind,name,status,start_utc,duration_ms,reported_cost,cost_status,data) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) '
            'ON CONFLICT(span_id,attempt) DO UPDATE SET status=excluded.status,'
            'duration_ms=excluded.duration_ms,reported_cost=excluded.reported_cost,'
            'cost_status=excluded.cost_status,data=excluded.data',
            (span.span_id, span.attempt, span.task_id, span.task_revision, span.parent_span_id,
             span.operation_id, data.get('kind', 'span'),
             name or data.get('stage_name') or data.get('role') or data.get('decision_id') or '',
             span.status, span.start_utc, span.duration_ms,
             _cost_text(reported) if reported is not None else None,
             getattr(span, 'cost_status', None), json.dumps(data)))
    return span


def spans(task_id, *, kind=None):
    query = 'SELECT data FROM spans WHERE task_id=?' + (' AND kind=?' if kind else '') + ' ORDER BY start_utc, attempt'
    rows = connect().execute(query, (task_id, kind) if kind else (task_id,))
    return [json.loads(row['data']) for row in rows]


# Costs serialise as the string 'unknown' (see `_cost_text`); rehydrating them
# back into the sentinel is what keeps a missing charge missing rather than
# quietly becoming a plausible-looking string.
_COST_FIELDS = ('reserved_cost_usd', 'reported_cost_usd', 'reconciled_cost_usd')


def _rehydrate(cls, data):
    fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
    for name in _COST_FIELDS:
        if name in fields:
            fields[name] = _cost_value(fields[name]) if not isinstance(fields[name], (int, float))                 else float(fields[name])
    return cls(**fields)


def model_spans(task_id):
    return [_rehydrate(ModelSpan, d) for d in spans(task_id, kind='model')]


def stage_spans(task_id):
    return [_rehydrate(StageSpan, d) for d in spans(task_id, kind='stage')]


def reconcile_open_spans(task_id):
    """Mark attempts left in flight by a crash as `unresolved`.

    A dispatched request that nobody saw finish may well have billed. Deleting
    the row or calling it an error would both be guesses; `unresolved` keeps it
    in the accounting as an open charge, which is what it is.
    """
    conn = connect()
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        rows = conn.execute("SELECT span_id,attempt,data FROM spans WHERE task_id=? AND status='running'",
                            (task_id,)).fetchall()
        for row in rows:
            data = json.loads(row['data'])
            data['status'] = 'unresolved'
            conn.execute('UPDATE spans SET status=?,data=? WHERE span_id=? AND attempt=?',
                         ('unresolved', json.dumps(data), row['span_id'], row['attempt']))
    return [(row['span_id'], row['attempt']) for row in rows]


def carried_ledger(task_id):
    """Spend and calls this task inherited from the objective it continues."""
    row = connect().execute('SELECT config_snapshot FROM tasks WHERE task_id=?',
                            (task_id,)).fetchone()
    snapshot = json.loads((row['config_snapshot'] if row else None) or '{}')
    return (float(snapshot.get('carried_usd') or 0.0), int(snapshot.get('carried_calls') or 0))


def accounting(task_id):
    """Charges and attempts for a task, with the unresolved ones still visible.

    `attempts` counts rows; `logical_decisions` counts distinct decision_ids. A
    request retried twice is 1 decision and 3 attempts -- the spec asks the
    report to state both, and a single number cannot.
    """
    # The carried amount lives in the task's configuration snapshot, not in a
    # span, so a reconstruction that reads only spans silently drops it -- and
    # the NEXT continuation then started from zero again.
    carried_usd, carried_calls = carried_ledger(task_id)
    roll = contracts.CostRoll(carried_usd=carried_usd)
    attempts = 0
    decisions, billed, unresolved = set(), 0, 0
    for span in model_spans(task_id):
        attempts += 1
        if span.decision_id:
            decisions.add(span.decision_id)
        # Replay each attempt through the SAME reserve/release path the live
        # ledger used, so a rebuilt book reports the same committed total: an
        # unreported charge keeps its reservation as pending rather than
        # vanishing into a zero.
        reserved = span.reserved_cost_usd
        reserved = contracts.UNKNOWN_CHARGE_RESERVE_USD if isinstance(reserved, contracts._Unknown)             else float(reserved or 0.0)
        roll.reserve(reserved)
        if span.status in ('running', 'unresolved'):
            unresolved += 1
            roll.release(reserved, UNKNOWN)
        elif span.cost_status == 'free':
            roll.release(reserved, 0.0)
        elif span.cost_status in ('reported', 'reconciled'):
            roll.release(reserved, span.reconciled_cost_usd if span.cost_status == 'reconciled'
                         else span.reported_cost_usd)
            billed += 1
        else:
            roll.release(reserved, UNKNOWN)
    return {'attempts': attempts + carried_calls, 'own_attempts': attempts,
            'carried_calls': carried_calls,
            'logical_decisions': len(decisions) or attempts,
            'billed_attempts': billed, 'unresolved_attempts': unresolved, **roll.to_dict()}


# -------------------------------------------------------------------- stages

def record_stage(task_id, stage_name, operation_id, *, revision=1, status='completed',
                 parameter_hash='', output=None, completed_at=None):
    """Remember a stage under the revision it RAN under.

    Passing the current revision instead would attribute work to a request that
    did not ask for it, and would let a resume hand revision 2 an artifact that
    revision 1's parameters produced.
    """
    conn = connect()
    with conn:
        conn.execute('INSERT INTO stages VALUES (?,?,?,?,?,?,?,?) '
                     'ON CONFLICT(task_id,stage_name,operation_id) DO UPDATE SET '
                     'status=excluded.status,output=excluded.output,completed_at=excluded.completed_at',
                     (task_id, stage_name, operation_id, revision, status, parameter_hash,
                      json.dumps(output) if output is not None else None,
                      completed_at if completed_at is not None else (time.time() if status == 'completed' else None)))


def completed_stage(task_id, stage_name, operation_id):
    """The recorded result of a completed stage, or None.

    `operation_id` is the normalised parameter hash of the stage's inputs, so
    the same stage with different inputs does not resume the wrong one.
    """
    row = connect().execute(
        "SELECT output FROM stages WHERE task_id=? AND stage_name=? AND operation_id=? AND status='completed'",
        (task_id, stage_name, operation_id)).fetchone()
    if not row:
        return None
    return json.loads(row['output']) if row['output'] is not None else {}


def stage_duration_estimate(stage_name, *, parameter_hash=None, minimum_samples=3):
    """(seconds, sample_count) for this stage, or (None, count) when unknown.

    Three rules, each from a way the first version lied:

    * **Successful, non-reused executions only.** A resumed stage completes in
      microseconds because it did nothing; averaging those in told the user a
      two-minute import would take no time at all.
    * **Comparable executions only.** One bucket per (name, parameter hash), so
      "render one pose" and "render nine" stop being the same estimate. Without
      a hash the caller gets the name's own bucket and the count says how thin
      it is.
    * **A count, always.** Two samples are not a distribution; the caller shows
      the number so a reader can judge it rather than trust a median of two.
    """
    query = ("SELECT data FROM spans WHERE kind='stage' AND name=? AND status='ok' "
             'AND duration_ms IS NOT NULL ORDER BY start_utc DESC LIMIT 200')
    rows = connect().execute(query, (stage_name,)).fetchall()
    samples = []
    for row in rows:
        data = json.loads(row['data'])
        if data.get('cache_hit'):
            continue                            # reused: it measured nothing
        if parameter_hash is not None and data.get('parameter_hash') != parameter_hash:
            continue
        duration = data.get('duration_ms')
        if isinstance(duration, (int, float)) and duration >= 0:
            samples.append(duration)
    samples.sort()
    if len(samples) < minimum_samples:
        return None, len(samples)
    middle = len(samples) // 2
    median = (samples[middle] if len(samples) % 2
              else (samples[middle - 1] + samples[middle]) / 2)
    return round(median / 1000, 3), len(samples)


def stages(task_id):
    return [dict(row) for row in connect().execute(
        'SELECT * FROM stages WHERE task_id=? ORDER BY completed_at', (task_id,))]


# ------------------------------------------------------------- tool journal

def _journal_row(row):
    """One decoded journal record, whatever read it came from.

    `begin_tool` used to hand back a raw sqlite row whose `result` was still a
    JSON string while `tool_record` returned the decoded object, so a caller
    reusing a refused operation's result got a different type depending on which
    call it happened to come through.
    """
    if row is None:
        return None
    record = dict(row)
    for field in ('result', 'receipt'):
        if field in record:
            record[field] = json.loads(record[field]) if record[field] else None
    return record


def begin_tool(operation_id, tool, fingerprint, *, task_id=None, task_revision=1):
    """Claim a side effect before running it.

    Returns (claimed, record). `claimed` is False when this exact operation
    already started, finished or is unresolved, and `record` is the decoded
    journal entry. The INSERT is the lock: two threads racing the same
    operation_id cannot both win it.

    An operation id that exists for a DIFFERENT task, tool or fingerprint is a
    collision, not a duplicate, and raises rather than silently handing back
    somebody else's result.
    """
    conn = connect()
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM tool_journal WHERE operation_id=?', (operation_id,)).fetchone()
        if row:
            if (row['task_id'], row['tool'], row['fingerprint']) != (task_id, tool, fingerprint):
                raise JournalConflict(
                    f'operation {operation_id} already exists for a different task/tool/fingerprint')
            return False, _journal_row(row)
        conn.execute('INSERT INTO tool_journal (operation_id,task_id,task_revision,tool,fingerprint,'
                     'status,started_at) VALUES (?,?,?,?,?,?,?)',
                     (operation_id, task_id, task_revision, tool, fingerprint, 'started', time.time()))
    return True, None


def finish_tool(operation_id, status, result=None, *, receipt=None):
    """Close a journalled effect.

    Completion REQUIRES a receipt: the whole point of the entry is that a later
    caller can reuse what happened instead of doing it again, and an entry that
    says `completed` with nothing attached cannot be reused -- it can only be
    believed.
    """
    if status not in contracts.JOURNAL_STATUSES:
        raise ValueError(f'journal status must be one of {sorted(contracts.JOURNAL_STATUSES)}')
    if status == 'completed' and receipt is None and result is None:
        raise ValueError('a completed operation must record its result or receipt')
    conn = connect()
    with conn:
        conn.execute(
            'UPDATE tool_journal SET status=?,result=?,receipt=?,completed_at=?,reconciled_at=? '
            'WHERE operation_id=?',
            (status, json.dumps(result, default=str) if result is not None else None,
             json.dumps(receipt, default=str) if receipt is not None else None,
             time.time(), time.time() if status == 'reconciled' else None, operation_id))


def tool_record(operation_id):
    return _journal_row(connect().execute(
        'SELECT * FROM tool_journal WHERE operation_id=?', (operation_id,)).fetchone())


def open_tools(task_id=None):
    """Side effects that are still open: started, or unresolved after a crash.

    `unresolved` stays discoverable until something explicitly reconciles it.
    Searching only for `started` meant a second restart reported nothing to do
    while the operation was still, in fact, unresolved in the database.
    """
    marks = ','.join('?' * len(contracts.OPEN_JOURNAL_STATUSES))
    statuses = sorted(contracts.OPEN_JOURNAL_STATUSES)
    query = f'SELECT * FROM tool_journal WHERE status IN ({marks})'
    params = list(statuses)
    if task_id is not None:
        query += ' AND task_id=?'
        params.append(task_id)
    return [_journal_row(row) for row in connect().execute(query + ' ORDER BY started_at', params)]


# ------------------------------------------------------------------ approvals

def record_request(task_id, request):
    conn = connect()
    with conn:
        conn.execute('INSERT INTO approvals (request_id,task_id,task_revision,kind,operation_id,'
                     'operation_digest,status,payload,created_at) VALUES (?,?,?,?,?,?,?,?,?) '
                     'ON CONFLICT(request_id) DO UPDATE SET status=excluded.status,payload=excluded.payload',
                     (request.id, task_id, request.task_revision, request.kind, request.operation_id,
                      request.operation_digest, request.status, json.dumps(request.to_dict()), request.created_at))
    return request


def settle_request(request_id, response, *, task_id, expect_revision=None, allowed=None):
    """Settle one request, in a single transaction, or refuse and say why.

    Everything the settlement depends on is checked inside the same IMMEDIATE
    transaction that writes it: the request exists, belongs to THIS task, is
    still pending, was raised for the revision the caller believes is current,
    and the response is one the request offered. Reading the status in one
    transaction and writing it in another is how a revision can invalidate an
    approval and then have a late click overwrite it as approved.

    Returns ('settled' | 'idempotent', response). An identical repeat of a
    response already recorded is idempotent; a different one is a conflict.
    """
    conn = connect()
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM approvals WHERE request_id=?', (request_id,)).fetchone()
        if row is None:
            raise SettlementRefused('That request is not known to this app.')
        if row['task_id'] != task_id:
            raise SettlementRefused('That request belongs to a different task.')
        task = conn.execute('SELECT revision,state FROM tasks WHERE task_id=?', (task_id,)).fetchone()
        if task is None:
            raise SettlementRefused('Unknown task.')
        # The state was read and never tested. A task interrupted between
        # saving its terminal envelope and retiring its approvals left a
        # cancelled task with a pending approval, and this accepted it.
        if task['state'] in contracts.TERMINAL_STATES:
            raise SettlementRefused(
                f'That task has already {task["state"]}; it cannot authorize anything more.')
        if row['status'] == 'invalidated':
            raise SettlementRefused('That request is stale: the task changed since it was shown.')
        if row['status'] != 'pending':
            # A repeat of the same answer is the same answer; anything else is a
            # second, conflicting decision about a subject already decided.
            if row['status'] == response:
                return 'idempotent', response
            raise SettlementRefused(
                f'That request is already {row["status"]}; it cannot also be {response}.')
        if row['task_revision'] != task['revision']:
            raise SettlementRefused('That request is stale: the task changed since it was shown.')
        if expect_revision is not None and expect_revision != task['revision']:
            raise SettlementRefused('That request is stale: the task changed since it was shown.')
        offered = allowed
        if offered is None:
            offered = (json.loads(row['payload'] or '{}') or {}).get('allowed_responses') or []
        if offered and response not in offered:
            raise SettlementRefused(f'{response!r} is not one of the responses this request offered.')
        payload = json.loads(row['payload'] or '{}')
        payload['status'] = response
        conn.execute('UPDATE approvals SET status=?,settled_at=?,payload=? WHERE request_id=?',
                     (response, time.time(), json.dumps(payload), request_id))
    return 'settled', response


def finish_task(envelope, status='cancelled'):
    """Save a terminal envelope and retire its approvals as ONE commit.

    Two commits left a crash window in which SQLite held a finished task and a
    pending approval at the same time -- and a click arriving in that window
    was accepted. There is no ordering of two commits that closes it; there is
    only one commit.
    """
    envelope.validate()
    if envelope.state not in contracts.TERMINAL_STATES:
        raise ValueError('finish_task is for a terminal envelope only')
    conn = connect()
    now = time.time()
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT revision,state FROM tasks WHERE task_id=?',
                           (envelope.task_id,)).fetchone()
        if row is None:
            raise ValueError('Unknown task.')
        if envelope.revision < row['revision']:
            raise StaleRevision(
                f'task revision is {row["revision"]}; refusing a close for {envelope.revision}')
        ids = [r['request_id'] for r in conn.execute(
            "SELECT request_id FROM approvals WHERE task_id=? AND status='pending'",
            (envelope.task_id,))]
        conn.executemany('UPDATE approvals SET status=?,settled_at=? WHERE request_id=?',
                         [(status, now, request_id) for request_id in ids])
        conn.execute('UPDATE tasks SET revision=?,envelope=?,state=?,outcome=?,workflow=?,'
                     'workflow_version=?,updated_at=? WHERE task_id=?',
                     (envelope.revision, json.dumps(envelope.to_dict()), envelope.state,
                      envelope.outcome, envelope.workflow, envelope.workflow_version,
                      now, envelope.task_id))
    return ids


def pending_requests(task_id):
    return [json.loads(row['payload']) for row in connect().execute(
        "SELECT payload FROM approvals WHERE task_id=? AND status='pending' ORDER BY created_at", (task_id,))]


def request_status(request_id):
    row = connect().execute('SELECT status FROM approvals WHERE request_id=?', (request_id,)).fetchone()
    return row['status'] if row else None


# --------------------------------------------------------------------- events

def record_event(message):
    """Persist an event and stamp it with the DURABLE sequence number.

    The sequence a subscriber reconnects against has to survive a restart, so it
    is SQLite's rowid, not a counter in a process that has since exited.
    """
    conn = connect()
    payload = {k: v for k, v in message.items() if k not in ('type', 'task_id', 'revision', 'at', 'seq')}
    with conn:
        cursor = conn.execute('INSERT INTO events (task_id,revision,kind,at,payload) VALUES (?,?,?,?,?)',
                              (message.get('task_id'), message.get('revision'), message['type'],
                               message.get('at', time.time()), json.dumps(payload, default=str)))
        return {**message, 'seq': cursor.lastrowid}


def _event_row(row):
    return {'type': row['kind'], 'task_id': row['task_id'], 'revision': row['revision'],
            'at': row['at'], 'seq': row['seq'], **json.loads(row['payload'] or '{}')}


def events(task_id=None, *, after=0, limit=1000):
    """Durable replay: everything after `seq`, in the order it was committed."""
    query = 'SELECT * FROM events WHERE seq>?'
    params = [after]
    if task_id is not None:
        query += ' AND task_id=?'
        params.append(task_id)
    return [_event_row(row) for row in
            connect().execute(query + ' ORDER BY seq LIMIT ?', [*params, limit])]


# --------------------------------------------------------------------- wishes

def record_wish(wish):
    """Persist a capability gap, deduplicated by capability + implementation.

    A duplicate is recorded as an occurrence rather than a new ticket, so demand
    can be counted without filing the same gap twenty times.
    """
    wish.validate()
    conn = connect()
    existing = conn.execute('SELECT wish_id FROM wishes WHERE dedupe_key=? ORDER BY created_at LIMIT 1',
                            (wish.dedupe_key,)).fetchone()
    # Set it on the object before serialising: the stored blob is what readers
    # get back, so a status only written to the column would not survive.
    if existing:
        wish.record_status = 'duplicate'
    with conn:
        conn.execute('INSERT OR REPLACE INTO wishes VALUES (?,?,?,?,?,?,?)',
                     (wish.wish_id, wish.task_id, wish.dedupe_key, wish.capability,
                      wish.record_status, json.dumps(wish.to_dict()), time.time()))
    return wish.wish_id


def wishes(task_id=None):
    query = 'SELECT data FROM wishes' + (' WHERE task_id=?' if task_id else '') + ' ORDER BY created_at'
    rows = connect().execute(query, (task_id,) if task_id else ())
    return [Wish(**json.loads(row['data'])) for row in rows]


# ------------------------------------------------------------- JSONL export

def export_trace(task_id, path=None):
    """Write one task's whole trace as JSONL, for the grader and bug reports.

    SQLite stays the operational source of truth; this is a flat, diffable,
    append-ordered copy that an evaluation harness can read without the app.
    Line one is the envelope, then revisions, spans, stages, journal entries,
    approvals, events and wishes -- each line self-describing via `record`.
    """
    row = task_row(task_id)
    if not row:
        raise ValueError('Unknown task.')
    path = Path(path) if path else trace_dir() / f'{task_id}.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect()
    lines = [{'record': 'task', 'schema_version': SCHEMA_VERSION,
              'contracts_version': contracts.CONTRACTS_VERSION,
              'exported_at': time.time(), 'task': json.loads(row['envelope']),
              'family': row['family'], 'chat_id': row['chat_id'],
              'config_snapshot': json.loads(row['config_snapshot'] or '{}'),
              'accounting': accounting(task_id)}]
    for revision in conn.execute('SELECT * FROM task_revisions WHERE task_id=? ORDER BY revision', (task_id,)):
        lines.append({'record': 'revision', **dict(revision)})
    for span in spans(task_id):
        lines.append({'record': 'span', **span})
    for stage in stages(task_id):
        lines.append({'record': 'stage', **stage})
    for entry in conn.execute('SELECT * FROM tool_journal WHERE task_id=? ORDER BY started_at', (task_id,)):
        entry = dict(entry)
        entry['result'] = json.loads(entry['result']) if entry['result'] else None
        lines.append({'record': 'tool', **entry})
    for approval in conn.execute('SELECT * FROM approvals WHERE task_id=? ORDER BY created_at', (task_id,)):
        approval = dict(approval)
        approval['payload'] = json.loads(approval['payload'] or '{}')
        lines.append({'record': 'approval', **approval})
    for message in events(task_id):
        lines.append({'record': 'event', **message})
    for wish in wishes(task_id):
        lines.append({'record': 'wish', **wish.to_dict()})
    with open(path, 'w', encoding='utf-8', newline='\n') as handle:
        for line in lines:
            handle.write(json.dumps(line, default=contracts._plain) + '\n')
    return path


def read_trace(path):
    with open(path, encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]
