"""The wish ledger on its own connection to `tasks.db`: schema and migration, recording a gap and
counting its conversations, the backlog, suppression, and reading submissions back."""

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass

from core import storage_handles
from randall.assistant import capabilities
from randall.assistant.tasks import store
from randall.assistant.tasks.contracts import Wish

from .wish_evidence import EVIDENCE_CODES, Observation, Requirement, classify_blocker
from .wish_keys import api_version, key_for, safe_app_version, safe_workflow, short_key, valid_key


WISHES_VERSION = 2


# ---------------------------------------------------------------------------
# Storage: this module's own connection to the shared journal file
# ---------------------------------------------------------------------------

_SCHEMA = """
-- The uniqueness ledger AND the authority for what was recorded. The store's
-- `wishes` table has no constraint this module may add, so the arbiter lives
-- here: the PRIMARY KEY is what makes a concurrent double-record impossible,
-- and the mirror into the store is written only after a claim succeeds.
CREATE TABLE IF NOT EXISTS wish_observations (
    task_id TEXT NOT NULL,
    task_revision INTEGER NOT NULL,
    dedupe_key TEXT NOT NULL,
    wish_id TEXT NOT NULL,
    capability TEXT NOT NULL,
    blocked_operation TEXT NOT NULL,
    implementation_version TEXT NOT NULL,
    variant TEXT NOT NULL,
    workflow TEXT NOT NULL,
    evidence_codes TEXT NOT NULL DEFAULT '[]',
    conversation_id TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    PRIMARY KEY (task_id, task_revision, dedupe_key)
);
CREATE INDEX IF NOT EXISTS wish_observations_by_key ON wish_observations (dedupe_key);
-- Demand, counted once per CONVERSATION per capability/version, never per task:
-- the engine opens a fresh task every turn, so counting tasks would inflate a
-- single request into a dozen. Retries, approvals and repeated tool calls in the
-- same conversation land on the same primary key and add nothing.
CREATE TABLE IF NOT EXISTS wish_occurrences (
    dedupe_key TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    capability TEXT NOT NULL,
    blocked_operation TEXT NOT NULL,
    implementation_version TEXT NOT NULL,
    variant TEXT NOT NULL,
    occurrences INTEGER NOT NULL DEFAULT 1,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    PRIMARY KEY (dedupe_key, conversation_id)
);
-- One random id per installation per capability family, retained across count
-- updates so the owner can take a MAXIMUM rather than summing snapshots. It is
-- not a device id: it never leaves its own capability row.
CREATE TABLE IF NOT EXISTS wish_contributions (
    dedupe_key TEXT PRIMARY KEY,
    contribution_id TEXT NOT NULL,
    created_at REAL NOT NULL
);
-- Submission state. Consent is a recorded time bound to `approval_hash`, which
-- covers the payload, the identity choice AND the frozen bundle bytes.
-- `lease_id`/`lease_expires_at` make sending exclusive without making a crash
-- permanent. `remote_id` is written BEFORE the upload so a lost acknowledgment
-- retries into the same remote report.
CREATE TABLE IF NOT EXISTS wish_submissions (
    submission_id TEXT PRIMARY KEY,
    dedupe_key TEXT NOT NULL,
    contribution_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    manifest TEXT NOT NULL DEFAULT '{}',
    approval_hash TEXT NOT NULL,
    bundle_path TEXT NOT NULL DEFAULT '',
    bundle_sha256 TEXT NOT NULL DEFAULT '',
    include_identity INTEGER NOT NULL DEFAULT 0,
    attachments TEXT NOT NULL DEFAULT '[]',
    approved_count INTEGER NOT NULL DEFAULT 0,
    consented_at REAL,
    state TEXT NOT NULL,
    remote_id TEXT NOT NULL DEFAULT '',
    receipt TEXT,
    retry_not_before REAL,
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_id TEXT NOT NULL DEFAULT '',
    lease_expires_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS wish_submissions_by_key ON wish_submissions (dedupe_key, state);
-- "Don't ask again for this feature": suppresses the invitation only. Local
-- counting continues, because the gap is still real.
CREATE TABLE IF NOT EXISTS wish_suppressions (
    dedupe_key TEXT PRIMARY KEY,
    at REAL NOT NULL
);
-- Observations recorded before this module existed. They have no consent, no
-- conversation identity and a versionless key, so they are preserved as
-- local-only history and never counted as demand or offered for sending.
CREATE TABLE IF NOT EXISTS wish_legacy (
    wish_id TEXT PRIMARY KEY,
    capability TEXT NOT NULL,
    blocked_operation TEXT NOT NULL,
    legacy_key TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS wish_meta (key TEXT PRIMARY KEY, value TEXT);
"""

#: Submission states. `local_only` is the honest terminal state for a wish that
#: was saved here and could not be accepted remotely.
SUBMISSION_STATES = ('prepared', 'consented', 'sending', 'sent', 'failed',
                     'local_only', 'declined')
#: What :func:`submit` can REPORT. `submission_disabled` is deliberately not a
#: stored state: a build whose gate is closed writes no row at all, so there is
#: nothing left behind that looks like an attempt.
RESULT_STATES = SUBMISSION_STATES + ('submission_disabled',)

_local = threading.local()
_initialised = set()
_init_lock = threading.Lock()
# Every thread's open connection, for close_all() (see store.close_all).
_open = set()
_open_lock = threading.Lock()
_generation = 0


def _db_path():
    return store.root() / 'tasks.db'


def _bundle_dir():
    directory = store.root() / 'wish_bundles'
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _initialise(path):
    """Create the tables ONCE, on a connection of its own, then close it.

    The previous shape ran `executescript()` + `commit()` on the store's cached
    per-thread connection on every call, so a plain read of the conversation
    count committed whatever transaction the caller had open -- the review
    inserted a row inside an owner transaction, called
    `requesting_conversations()`, raised, and the row survived the rollback.
    Schema setup is a one-time operation on a separate connection, and after it
    nothing in this module touches anyone else's transaction.
    """
    with _init_lock:
        if path in _initialised:
            return
        setup = sqlite3.connect(path, timeout=15)
        try:
            setup.execute('PRAGMA journal_mode=WAL')
            setup.executescript(_SCHEMA)
            setup.execute('INSERT OR REPLACE INTO wish_meta VALUES (?,?)',
                          ('schema_version', str(WISHES_VERSION)))
            setup.commit()
        finally:
            setup.close()
        _initialised.add(path)
    _migrate_legacy()


def connection():
    """This module's own connection to the shared journal file.

    Same database as `store.connect()` -- one `tasks.db`, one durable location
    that a frozen build does not lose -- but a separate handle, so a wish read
    or write can never commit or roll back a transaction the task journal has
    open. WAL makes the two handles coexist.
    """
    path = _db_path()
    conn = getattr(_local, 'conn', None)
    if (conn is not None and getattr(_local, 'path', None) == path
            and getattr(_local, 'generation', None) == _generation):
        return conn
    if conn is not None:
        _drop(conn)
    generation = _generation
    _initialise(path)
    conn = sqlite3.connect(path, timeout=15, check_same_thread=False)
    with _open_lock:
        _open.add(conn)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=15000')
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
    """Close every thread's ledger connection before a Vault restore swaps the storage folder
    (core/storage_handles.py). The restored folder may hold a tasks.db without the wish tables, so the one-time
    schema setup runs again on the next connection."""
    global _generation
    with _open_lock:
        _generation += 1
        conns = list(_open)
        _open.clear()
    with _init_lock:
        _initialised.clear()
    for conn in conns:
        try:
            conn.close()
        except sqlite3.Error:
            pass


storage_handles.register(close_all)


def _meta(key, default=''):
    row = connection().execute('SELECT value FROM wish_meta WHERE key=?', (key,)).fetchone()
    return row['value'] if row else default


def _migrate_legacy():
    """Preserve pre-existing `queued` observations as local-only history. Once.

    They were written before consent, conversation identity or the authoritative
    key existed. Converting them into demand would manufacture numbers nobody
    approved, and leaving them `queued` implies a submission that was never
    consented to, so they become their own local-only row: visible in the
    backlog as history, never counted, never offered for sending.

    Idempotent, marked in `wish_meta`, and best-effort -- a legacy table that
    cannot be read must not stop the app.
    """
    conn = connection()
    if _meta('legacy_migrated') == '1':
        return
    rows = []
    try:
        for wish in store.wishes():
            if valid_key(wish.dedupe_key):
                continue                       # already an authoritative key
            rows.append((wish.wish_id, wish.capability, wish.blocked_operation,
                         wish.dedupe_key or '', time.time()))
    except Exception:                          # noqa: BLE001 - history is optional
        rows = []
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.executemany('INSERT OR IGNORE INTO wish_legacy VALUES (?,?,?,?,?)', rows)
        conn.execute('INSERT OR REPLACE INTO wish_meta VALUES (?,?)', ('legacy_migrated', '1'))


def legacy_wishes():
    """Pre-module observations, as history. Never demand, never sendable."""
    return [dict(row) for row in connection().execute(
        'SELECT * FROM wish_legacy ORDER BY created_at')]


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

#: The bucket an observation with no conversation identity is counted in.
#: Deliberately ONE bucket: falling back to the task id would count every turn
#: of the same conversation as a different requesting conversation, which is the
#: inflation this whole counting scheme exists to avoid. Collapsing to a single
#: bucket undercounts instead, which is the safe direction.
UNKNOWN_CONVERSATION = '_no_conversation'


@dataclass(frozen=True)
class WishRecord:
    """The result of trying to record a gap.

    `recorded` -- a wish exists AND the write succeeded -- is the only thing
    that may justify printing "saved on this device".
    """
    wish: object                         # contracts.Wish, or None when not a wish
    persisted: bool
    already_recorded: bool = False       # this task/revision had already filed it
    requesting_conversations: int = 0
    error: str = ''
    #: The verdict this record came from. Present even when nothing was
    #: recorded, so a caller can say the right thing about a `not_a_blocker`
    #: or an `outage` without classifying it a second time.
    classification: object = None

    @property
    def dedupe_key(self):
        return self.wish.dedupe_key if self.wish is not None else ''

    @property
    def recorded(self):
        return self.wish is not None and self.persisted


def record(classification, *, task_id, task_revision=1, conversation_id='', workflow='',
           requested_outcome='', evidence_codes=()):
    """Claim an observation and count its conversation, atomically, then mirror.

    The ledger claim and the occurrence upsert are ONE `BEGIN IMMEDIATE`
    transaction, so two threads recording the same gap for the same task and
    revision cannot both win -- the review's interleaving probe produced two
    observations and two counted conversations. Whoever loses the claim gets the
    existing observation back.

    The mirror into the store's `wishes` table (which `export_trace` reads)
    happens after the claim. If it fails, the claim is rolled back by a
    compensating transaction, so the ledger, the counts and the trace cannot
    diverge, and the caller is told the truth: `persisted=False`.

    `requested_outcome` is accepted for call-site compatibility and is NOT
    stored on anything that leaves the machine; the projection takes that
    sentence from the catalogue.
    """
    if not classification.creates_wish:
        raise ValueError(f'{classification.outcome!r} does not create a wish; '
                         'only a confirmed unsupported required operation does')
    definition = capabilities.by_name(classification.capability)
    if definition is None:
        raise ValueError(f'no capability definition for {classification.capability!r}')
    key = key_for(classification)
    codes = sorted({c for c in (tuple(evidence_codes) or (classification.evidence,))
                    if c in EVIDENCE_CODES})
    workflow = safe_workflow(workflow)
    conversation = str(conversation_id).strip() or UNKNOWN_CONVERSATION
    wish = Wish(capability=classification.capability, task_id=str(task_id),
                task_revision=int(task_revision), workflow=workflow,
                requested_outcome=definition.requested_outcome,
                blocked_operation=classification.blocked_operation,
                available_alternative=(definition.alternatives[0]
                                       if definition.alternatives else ''),
                evidence_ids=list(codes), app_version=safe_app_version(),
                api_version=api_version(), dedupe_key=key)
    wish.validate()

    conn = connection()
    now = time.time()
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        claimed = conn.execute(
            'INSERT OR IGNORE INTO wish_observations (task_id,task_revision,dedupe_key,'
            'wish_id,capability,blocked_operation,implementation_version,variant,workflow,'
            'evidence_codes,conversation_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (wish.task_id, wish.task_revision, key, wish.wish_id, classification.capability,
             classification.blocked_operation, classification.implementation_version,
             classification.variant, workflow, json.dumps(codes), conversation, now)).rowcount
        if claimed:
            conn.execute(
                'INSERT INTO wish_occurrences (dedupe_key,conversation_id,capability,'
                'blocked_operation,implementation_version,variant,occurrences,first_seen,'
                'last_seen) VALUES (?,?,?,?,?,?,1,?,?) '
                'ON CONFLICT(dedupe_key,conversation_id) DO UPDATE SET '
                'occurrences=occurrences+1, last_seen=excluded.last_seen',
                (key, conversation, classification.capability,
                 classification.blocked_operation, classification.implementation_version,
                 classification.variant, now, now))
        existing = conn.execute(
            'SELECT wish_id FROM wish_observations WHERE task_id=? AND task_revision=? '
            'AND dedupe_key=?', (wish.task_id, wish.task_revision, key)).fetchone()
    if not claimed:
        # Somebody else's claim (or an earlier call in this task/revision) owns
        # the observation. Return THEIRS; demand does not move.
        wish.wish_id = existing['wish_id'] if existing else wish.wish_id
        return WishRecord(wish=wish, persisted=True, already_recorded=True,
                          requesting_conversations=requesting_conversations(key),
                          classification=classification)
    try:
        store.record_wish(wish)
    except Exception as exc:                       # storage is allowed to fail
        _undo_claim(wish.task_id, wish.task_revision, key, conversation)
        return WishRecord(wish=wish, persisted=False, classification=classification,
                          error=f'{type(exc).__name__}: {exc}')
    return WishRecord(wish=wish, persisted=True, requesting_conversations=
                      requesting_conversations(key), classification=classification)


def _undo_claim(task_id, task_revision, key, conversation):
    """Roll the ledger claim and its count back when the mirror failed.

    Without this the counts would report demand for an observation the trace
    never received, and the next call would find the claim taken and report
    `already_recorded` for something that was never recorded at all.
    """
    conn = connection()
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('DELETE FROM wish_observations WHERE task_id=? AND task_revision=? '
                     'AND dedupe_key=?', (task_id, task_revision, key))
        row = conn.execute('SELECT occurrences FROM wish_occurrences WHERE dedupe_key=? '
                           'AND conversation_id=?', (key, conversation)).fetchone()
        if row and int(row['occurrences']) <= 1:
            conn.execute('DELETE FROM wish_occurrences WHERE dedupe_key=? AND '
                         'conversation_id=?', (key, conversation))
        elif row:
            conn.execute('UPDATE wish_occurrences SET occurrences=occurrences-1 '
                         'WHERE dedupe_key=? AND conversation_id=?', (key, conversation))


def record_wish(task, classification=None, *, operation='', variant='',
                evidence='operation_unavailable', required_for_outcome=True,
                requested_outcome='', evidence_codes=(), workflow='',
                conversation_id='', task_revision=None):
    """**The single public way to record a capability gap.** Use nothing else.

    Args:
        task: a task context (anything with `task_id`, `revision`, `chat_id`
            and `envelope.workflow`) or a bare task id string. Both are
            accepted so a facade with no context -- `nucleus_api/menus.py`,
            `nucleus_api/builds.py` -- has one entry point too.
        classification: the verdict from :func:`classify_blocker`, when the
            caller already has one. Leave it None and pass `operation` instead
            to have this function classify.
        operation: the operation that was unavailable, used only when
            `classification` is None.
        variant: a DECLARED variant of that capability, or ''. An undeclared
            one raises rather than forking the grouping key on arbitrary text.
        required_for_outcome: was this operation genuinely required for what the
            user asked for? False records nothing and comes back
            `not_a_blocker`.
        conversation_id: the CONVERSATION, which is the unit demand is counted
            in. A caller that cannot resolve it gets a single shared bucket, not
            the task id -- see :data:`UNKNOWN_CONVERSATION`.

    Returns:
        WishRecord. It ALWAYS comes back -- never raises for an ordinary
        blocker, because a delivery must not die on its own bookkeeping. Read
        `record.recorded` before saying anything was saved.
    """
    task_id = getattr(task, 'task_id', task) or ''
    revision = task_revision if task_revision is not None else getattr(task, 'revision', 1)
    envelope = getattr(task, 'envelope', None)
    workflow = workflow or getattr(envelope, 'workflow', '') or ''
    conversation_id = conversation_id or getattr(task, 'chat_id', '') or ''
    if classification is None:
        try:
            classification = classify_blocker(
                Observation(evidence=evidence, operation=operation, variant=variant),
                Requirement(operation=operation, required_for_outcome=required_for_outcome,
                            requested_outcome=requested_outcome, workflow=workflow))
        except ValueError as exc:
            return WishRecord(wish=None, persisted=False, error=str(exc))
    if not classification.creates_wish:
        return WishRecord(wish=None, persisted=False, classification=classification)
    try:
        return record(classification, task_id=str(task_id), task_revision=int(revision),
                      conversation_id=str(conversation_id), workflow=workflow,
                      requested_outcome=requested_outcome, evidence_codes=evidence_codes)
    except Exception as exc:                                  # noqa: BLE001
        # Bookkeeping never breaks the work it describes -- but it never
        # reports success it did not earn either.
        return WishRecord(wish=None, persisted=False, classification=classification,
                          error=f'{type(exc).__name__}: {exc}')


def requesting_conversations(key):
    row = connection().execute(
        'SELECT COUNT(*) AS n FROM wish_occurrences WHERE dedupe_key=?', (key,)).fetchone()
    return int(row['n']) if row else 0


def total_encounters(key):
    row = connection().execute(
        'SELECT COALESCE(SUM(occurrences),0) AS n FROM wish_occurrences WHERE dedupe_key=?',
        (key,)).fetchone()
    return int(row['n']) if row else 0


def contribution_id(key):
    """A random id for this installation and this capability family.

    Generated once and kept, so the owner can take the MAXIMUM of the counts a
    contribution reports rather than adding successive snapshots together. It is
    per-capability on purpose: there is no universal installation identifier to
    correlate rows across features.
    """
    conn = connection()
    row = conn.execute('SELECT contribution_id FROM wish_contributions WHERE dedupe_key=?',
                       (key,)).fetchone()
    if row:
        return row['contribution_id']
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('INSERT OR IGNORE INTO wish_contributions VALUES (?,?,?)',
                     (key, uuid.uuid4().hex, time.time()))
    return conn.execute('SELECT contribution_id FROM wish_contributions WHERE dedupe_key=?',
                        (key,)).fetchone()['contribution_id']


def _observation_row(key):
    return connection().execute(
        'SELECT capability, blocked_operation, implementation_version, variant, '
        'evidence_codes FROM wish_observations WHERE dedupe_key=? ORDER BY created_at LIMIT 1',
        (key,)).fetchone()


def evidence_codes_for(key):
    codes = set()
    for row in connection().execute(
            'SELECT evidence_codes FROM wish_observations WHERE dedupe_key=?', (key,)):
        try:
            codes |= {c for c in json.loads(row['evidence_codes']) if c in EVIDENCE_CODES}
        except (TypeError, ValueError):
            continue
    return sorted(codes)


# ---------------------------------------------------------------------------
# The backlog view
# ---------------------------------------------------------------------------

def backlog():
    """Every gap on this device, with its counts and submission state.

    Grouped by the authoritative key, so repeated tasks, revisions and app
    releases collapse into one row and a changed implementation version does
    not. Pre-module observations appear too, flagged `legacy` with zero
    conversations: they are history, not demand, and they carry no consent, so
    they can never be sent.
    """
    conn = connection()
    rows = []
    for row in conn.execute(
            'SELECT dedupe_key, capability, blocked_operation, implementation_version, variant, '
            'COUNT(*) AS conversations, SUM(occurrences) AS encounters, '
            'MIN(first_seen) AS first_seen, MAX(last_seen) AS last_seen '
            'FROM wish_occurrences GROUP BY dedupe_key '
            'ORDER BY conversations DESC, last_seen DESC'):
        entry = dict(row)
        definition = capabilities.by_name(entry['capability'])
        entry['short_key'] = short_key(entry['dedupe_key'])
        entry['limitation'] = definition.limitation if definition else ''
        entry['alternatives'] = list(definition.alternatives) if definition else []
        entry['requested_outcome'] = definition.requested_outcome if definition else ''
        entry['supported_scope'] = definition.supported_scope if definition else ''
        # A gap the build has since implemented is not a live request any more.
        # Asked WITH the variant, because an operation is missing for an input,
        # not in general.
        entry['still_unsupported'] = (
            definition is not None
            and definition.status_for(entry['variant']) == 'unsupported')
        entry['legacy'] = False
        entry['suppressed'] = is_suppressed(entry['dedupe_key'])
        entry['submission'] = latest_submission(entry['dedupe_key'])
        rows.append(entry)
    for old in legacy_wishes():
        rows.append({'dedupe_key': '', 'short_key': '', 'capability': old['capability'],
                     'blocked_operation': old['blocked_operation'],
                     'implementation_version': '', 'variant': '',
                     'conversations': 0, 'encounters': 0,
                     'first_seen': old['created_at'], 'last_seen': old['created_at'],
                     'limitation': '', 'alternatives': [], 'requested_outcome': '',
                     'supported_scope': '', 'still_unsupported': False, 'legacy': True,
                     'suppressed': False, 'submission': None})
    return rows


def is_suppressed(key):
    row = connection().execute('SELECT 1 FROM wish_suppressions WHERE dedupe_key=?',
                               (key,)).fetchone()
    return bool(row)


def suppress(key):
    """"Don't ask again for this feature". Local counting continues."""
    conn = connection()
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('INSERT OR REPLACE INTO wish_suppressions VALUES (?,?)', (key, time.time()))
    return True


def _public_row(row):
    """A submission row without its internal machinery."""
    if row is None:
        return None
    row = dict(row)
    for hidden in ('payload', 'lease_id', 'bundle_path'):
        row.pop(hidden, None)
    row['receipt'] = json.loads(row['receipt']) if row.get('receipt') else None
    row['manifest'] = json.loads(row['manifest'] or '{}')
    row['attachments'] = json.loads(row['attachments'] or '[]')
    row['include_identity'] = bool(row['include_identity'])
    row['active'] = _lease_is_live(row)
    return row


def latest_submission(key):
    row = connection().execute(
        'SELECT * FROM wish_submissions WHERE dedupe_key=? ORDER BY updated_at DESC LIMIT 1',
        (key,)).fetchone()
    return _public_row(row)


def submission(submission_id):
    row = connection().execute('SELECT * FROM wish_submissions WHERE submission_id=?',
                               (submission_id,)).fetchone()
    return dict(row) if row else None


def public_submission(submission_id):
    return _public_row(submission(submission_id))


def _lease_is_live(row, now=None):
    now = time.time() if now is None else now
    return bool(row and row['state'] == 'sending'
                and (row['lease_expires_at'] or 0) > now)
