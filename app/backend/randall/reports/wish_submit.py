"""Sending a wish: the outgoing payload and the frozen, disclosed bundle the user approves, then one
leased, rate-limited, idempotent send and its truthful failure states."""

import io
import json
import time
import uuid
import zipfile
from dataclasses import dataclass, field

from randall.assistant import capabilities

from .wish_gate import submit_enabled
from .wish_keys import api_version, canonical_payload, safe_app_version, safe_workflow, _sha256, strict_bool
from .wish_ledger import (_bundle_dir, connection, contribution_id, evidence_codes_for,
                          _lease_is_live, _observation_row, _public_row, public_submission,
                          requesting_conversations, submission)


#: How long a send may hold the exclusive lease. A process that dies mid-upload
#: leaves a `sending` row; without an expiry that row blocks every future send
#: forever, which the review reproduced.
SEND_LEASE_S = 5 * 60
#: The first attempt plus at most two retries, per the design.
MAX_SEND_ATTEMPTS = 3


# ---------------------------------------------------------------------------
# The outgoing payload and the frozen, disclosed bundle
# ---------------------------------------------------------------------------

SUBMISSION_SCHEMA_VERSION = 1
#: Structured wish metadata is capped; the design's 8 KB, measured in UTF-8
#: BYTES rather than characters.
PAYLOAD_MAX_BYTES = 8 * 1024
#: One successful contribution update per key per installation per 24 hours.
PER_KEY_COOLDOWN_S = 24 * 60 * 60
#: Five successful wish submissions per installation per 24 hours. These are the
#: WISH allowance; they must not consume the ordinary bug-report allowance.
DAILY_SUBMISSION_LIMIT = 5


def approval_hash(payload, manifest):
    """One hash over EVERYTHING that would be sent.

    The payload, the identity choice and every attachment's bytes. The previous
    hash covered the payload alone, so an anonymous, attachment-free review and
    one that selected identity plus app logs produced the SAME hash -- the click
    authorised bytes it had never been shown. Attachment contents are in here
    too, because a log file that changes between review and send changes what
    was consented to.
    """
    return _sha256(canonical_payload([SUBMISSION_SCHEMA_VERSION, payload,
                                      manifest]).encode('utf-8'))


def build_payload(key, *, platform, submission_id=None, workflow=''):
    """The exact metadata a user will be asked to approve.

    Assembled from the CATALOGUE and the local counts -- never from the
    conversation and never from caller text. `workflow` is mapped through the
    known set, `platform` must be one the report channel accepts, and the result
    is size-checked in UTF-8 bytes.
    """
    row = _observation_row(key)
    if row is None:
        raise ValueError('Nothing is recorded for that feature request on this device.')
    definition = capabilities.by_name(row['capability'])
    if definition is None:
        raise ValueError('That feature request has no capability definition to describe it.')
    if platform not in ('windows', 'mac', 'linux'):
        raise ValueError('Unknown platform for a report.')
    payload = {
        'schema_version': SUBMISSION_SCHEMA_VERSION,
        'kind': 'capability_gap',
        'submission_id': submission_id or f'wsub_{uuid.uuid4().hex[:16]}',
        'contribution_id': contribution_id(key),
        'dedupe_key': key,
        'capability': definition.name,
        'blocked_operation': definition.operation,
        'implementation_version': definition.implementation_version,
        'variant': definition.variant_or_refuse(row['variant']),
        'app_version': safe_app_version(),
        'api_version': api_version(),
        'platform': platform,
        'workflow': safe_workflow(workflow),
        'requested_outcome': definition.requested_outcome,
        'limitation': definition.limitation,
        'alternative': definition.alternatives[0] if definition.alternatives else '',
        'requesting_conversations': requesting_conversations(key),
        'evidence_codes': evidence_codes_for(key),
    }
    if len(canonical_payload(payload).encode('utf-8')) > PAYLOAD_MAX_BYTES:
        raise ValueError('That feature request is larger than the submission allows.')
    return payload


def summary_sentence(payload):
    """The bounded summary that travels with a report.

    Assembled from catalogue fields only. There is no branch here that can
    reach a conversation, a path or an exception string.
    """
    lines = [f"Requested: {payload['requested_outcome'] or payload['capability']}",
             f"Limitation: {payload['limitation']}"]
    if payload.get('alternative'):
        lines.append(f"Available instead: {payload['alternative']}")
    if payload.get('variant'):
        lines.append(f"Variant: {payload['variant']}")
    lines.append(f"Encountered in {payload['requesting_conversations']} conversation(s) "
                 'on this device.')
    return '\n'.join(lines)


def build_bundle(payload, attachment_blobs=()):
    """The ZIP that will be uploaded: `wish.json`, plus what was opted into.

    Deliberately NOT built by the bug-report log collector: that walks the app
    log directory automatically, and a feature request must carry nothing the
    user did not choose. Returns `(bytes, members)` where members disclose each
    entry's name, size and hash so the user can be shown what is inside.
    """
    buffer = io.BytesIO()
    members = []
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        wish_json = json.dumps(payload, indent=2, sort_keys=True).encode('utf-8')
        archive.writestr(_bundle_entry('wish.json'), wish_json)
        members.append({'name': 'wish.json', 'bytes': len(wish_json),
                        'sha256': _sha256(wish_json)})
        for name, blob in attachment_blobs:
            archive.writestr(_bundle_entry(name), blob)
            members.append({'name': name, 'bytes': len(blob), 'sha256': _sha256(blob)})
    return buffer.getvalue(), members


def _bundle_entry(name):
    """A ZIP entry stamped with a fixed time, so the same contents zip to the
    same bytes.

    `writestr(name, ...)` stamps the current time, and the bundle's hash is part
    of the approval hash: a review two seconds after a send no longer matched
    the sent snapshot, so the completed send was hidden behind a new prepared
    row and repeating the original click answered 429 instead of returning its
    receipt (review finding 10, again). Compression and permissions are what
    `writestr(name, ...)` would have used.
    """
    entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    entry.compress_type = zipfile.ZIP_DEFLATED
    entry.external_attr = 0o600 << 16
    return entry


def disclosure_manifest(include_identity, members, bundle_bytes):
    """Exactly what the send will disclose, in the form the user is shown.

    Everything in here is hashed into `approval_hash`, so the click authorises
    this list and nothing else.
    """
    return {
        'include_discord_identity': bool(include_identity),
        'members': members,
        'bundle': {'bytes': len(bundle_bytes), 'sha256': _sha256(bundle_bytes)},
    }


class ConsentInvalid(ValueError):
    """The approved bytes are not the bytes that would be sent."""


class SubmissionBusy(RuntimeError):
    """An upload of this submission is in flight; it must not be disturbed."""


def prepare_submission(key, *, platform, workflow='', include_identity=False,
                       attachments=(), collect=None):
    """Freeze the complete outgoing contents and return them for approval.

    Builds the payload, collects the selected attachment BYTES now, assembles
    the finished ZIP, writes it beside the journal, and hashes payload +
    identity choice + every member into one `approval_hash`. Nothing is
    re-collected at send time, so the bytes the user approved are the bytes that
    go.

    Never disturbs work already in flight or already done:

    * a submission with a LIVE send lease is returned untouched,
    * a `sent` submission whose frozen contents still match is returned with its
      receipt, and a changed count gets a NEW snapshot rather than rewriting the
      completed one,
    * a `consented` submission is frozen: a different snapshot becomes a new
      row instead of clearing somebody's approval.
    """
    include_identity = strict_bool(include_identity)
    attachments = tuple(sorted({str(a) for a in attachments}))
    conn = connection()
    live = conn.execute(
        "SELECT * FROM wish_submissions WHERE dedupe_key=? AND state='sending' "
        'ORDER BY updated_at DESC LIMIT 1', (key,)).fetchone()
    if _lease_is_live(live):
        return _public_row(live)

    existing = conn.execute(
        'SELECT * FROM wish_submissions WHERE dedupe_key=? ORDER BY updated_at DESC LIMIT 1',
        (key,)).fetchone()
    blobs = []
    for name in attachments:
        if collect is None:
            raise ValueError(f'nothing can supply the attachment {name!r}')
        blobs.append((name, collect(name)))

    def snapshot_for(submission_id):
        payload = build_payload(key, platform=platform, workflow=workflow,
                                submission_id=submission_id)
        bundle, members = build_bundle(payload, blobs)
        manifest = disclosure_manifest(include_identity, members, bundle)
        return payload, bundle, manifest, approval_hash(payload, manifest)

    # Compare against the EXISTING submission under ITS OWN id. The id is part
    # of the payload, so minting a fresh one first would make every review look
    # like a change -- which is how a completed send ended up hidden behind a
    # new prepared row, and the original successful click then answered 429
    # instead of returning its receipt.
    payload = bundle = manifest = digest = None
    if existing is not None:
        payload, bundle, manifest, digest = snapshot_for(existing['submission_id'])
        if existing['approval_hash'] == digest and existing['state'] in (
                'prepared', 'consented', 'sent', 'failed', 'local_only'):
            return _public_row(existing)
    reuse_id = existing['submission_id'] if (
        existing is not None and existing['state'] == 'prepared') else None
    if reuse_id is None:
        # A new snapshot: an approved, sent or in-flight submission is frozen,
        # so a contribution update becomes its own row rather than rewriting it.
        payload, bundle, manifest, digest = snapshot_for(f'wsub_{uuid.uuid4().hex[:16]}')

    now = time.time()
    if reuse_id is not None:
        # Only a never-approved row may be rewritten in place.
        path = _freeze_bundle(reuse_id, bundle)
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute(
                'UPDATE wish_submissions SET payload=?,manifest=?,approval_hash=?,'
                'bundle_path=?,bundle_sha256=?,include_identity=?,attachments=?,'
                "approved_count=?,consented_at=NULL,state='prepared',updated_at=? "
                "WHERE submission_id=? AND state='prepared'",
                (canonical_payload(payload), canonical_payload(manifest), digest, str(path),
                 manifest['bundle']['sha256'], 1 if include_identity else 0,
                 json.dumps(list(attachments)), payload['requesting_conversations'],
                 now, reuse_id))
        return public_submission(reuse_id)

    submission_id = payload['submission_id']
    path = _freeze_bundle(submission_id, bundle)
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute(
            'INSERT INTO wish_submissions (submission_id,dedupe_key,contribution_id,payload,'
            'manifest,approval_hash,bundle_path,bundle_sha256,include_identity,attachments,'
            "approved_count,consented_at,state,remote_id,receipt,retry_not_before,attempts,"
            "lease_id,lease_expires_at,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL,'prepared','',NULL,NULL,0,'',NULL,?,?)",
            (submission_id, key, payload['contribution_id'], canonical_payload(payload),
             canonical_payload(manifest), digest, str(path), manifest['bundle']['sha256'],
             1 if include_identity else 0, json.dumps(list(attachments)),
             payload['requesting_conversations'], now, now))
    return public_submission(submission_id)


def _freeze_bundle(submission_id, bundle):
    """Write the approved ZIP to disk before anyone can consent to it.

    On disk rather than in the row so the bytes survive a restart: a retry after
    a crash must upload the bytes that were approved, not rebuild them from a
    log directory that has moved on.
    """
    path = _bundle_dir() / f'{submission_id}.zip'
    path.write_bytes(bundle)
    return path


def frozen_bundle(submission_id):
    """The approved bytes, verified against the hash they were approved under."""
    row = submission(submission_id)
    if row is None:
        raise ConsentInvalid('That feature request is no longer on this device.')
    try:
        data = open(row['bundle_path'], 'rb').read()
    except OSError as exc:
        raise ConsentInvalid('The approved attachment bytes are missing.') from exc
    if _sha256(data) != row['bundle_sha256']:
        raise ConsentInvalid('The approved attachment bytes changed on disk.')
    return data


# ---------------------------------------------------------------------------
# Sending: one transaction claims the lease, the consent and the attempt
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SubmissionResult:
    """What :func:`submit` did. `state` is the only thing callers branch on.

    `sent` is the single source of truth for "a report exists remotely", and it
    is True only for an ACCEPTED receipt. `notified: false` from the worker is
    still accepted -- R2 already holds the report -- so it does not become a
    failure, and nothing refiles merely to obtain a Discord ping.
    """
    state: str                             # one of RESULT_STATES
    submission_id: str = ''
    receipt: dict = field(default_factory=dict)
    reason: str = ''                       # a typed reason code, never a sentence
    retry_after: object = None
    http_status: object = None
    detail: dict = field(default_factory=dict)

    @property
    def sent(self):
        return self.state == 'sent'


class TransportRefused(RuntimeError):
    """The report server refused. `status` is its HTTP status when there was one."""

    def __init__(self, message, *, status=None, detail=None):
        super().__init__(message)
        self.status = status
        self.detail = detail or {}


def rate_limit(key, *, now=None, conn=None):
    """Is a NEW send allowed for this feature? ``(ok, reason, retry_after)``.

    Three local limits, all about WISHES only: one successful contribution
    update per key per 24 hours, five successful submissions per installation
    per 24 hours, and one live send at a time. Exposed for the review screen;
    the authoritative check runs inside :func:`claim_send`'s transaction, because
    checking here and claiming later is precisely the gap that let two clicks
    both reach the network.
    """
    now = time.time() if now is None else now
    conn = conn or connection()
    live = conn.execute("SELECT * FROM wish_submissions WHERE state='sending'").fetchall()
    if any(_lease_is_live(row, now) for row in live):
        return False, 'another_submission_in_flight', None
    row = conn.execute("SELECT updated_at FROM wish_submissions WHERE dedupe_key=? AND "
                       "state='sent' ORDER BY updated_at DESC LIMIT 1", (key,)).fetchone()
    if row is not None and now - row['updated_at'] < PER_KEY_COOLDOWN_S:
        return False, 'already_sent_today', round(PER_KEY_COOLDOWN_S - (now - row['updated_at']))
    sent = conn.execute("SELECT COUNT(*) AS n FROM wish_submissions WHERE state='sent' "
                        'AND updated_at>?', (now - PER_KEY_COOLDOWN_S,)).fetchone()
    if sent and int(sent['n']) >= DAILY_SUBMISSION_LIMIT:
        return False, 'daily_limit_reached', PER_KEY_COOLDOWN_S
    return True, '', None


def availability(key):
    """Is this gap still a gap? ``(still_unsupported, capability_name)``.

    Rechecked before review and before send: an app update can implement the
    capability while a saved wish is waiting, and sending a request for
    something the build now does is noise the owner has to triage.
    """
    row = _observation_row(key)
    if row is None:
        return False, ''
    definition = capabilities.by_name(row['capability'])
    if definition is None:
        return False, row['capability']
    # With the recorded variant: `builds.commit_change` is supported for a
    # Nucleus project and missing for an extracted folder, and the wish is
    # about the second.
    return definition.status_for(row['variant']) == 'unsupported', definition.name


def claim_send(submission_id, hash_presented, *, consent=False, now=None):
    """Check, consent and claim the exclusive send lease -- in ONE transaction.

    Returns ``(lease_id, reason, row)``; `lease_id` is empty when the claim was
    refused and `reason` says why, typed.

    Everything that could change between a check and a claim is inside the same
    `BEGIN IMMEDIATE`: the approval hash, the retry deadline, the attempt
    ceiling, the three rate limits, and the conditional state transition. The
    UPDATE names the states it will move from, so a row somebody else already
    claimed simply does not match and this caller is told `already_claimed`
    instead of starting a second upload of the same report.
    """
    now = time.time() if now is None else now
    consent = strict_bool(consent)
    conn = connection()
    lease = uuid.uuid4().hex
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM wish_submissions WHERE submission_id=?',
                           (submission_id,)).fetchone()
        if row is None:
            return '', 'unknown_submission', None
        if row['approval_hash'] != hash_presented:
            return '', 'consent_invalid', dict(row)
        if row['state'] == 'sent':
            return '', 'already_sent', dict(row)
        if row['state'] == 'declined':
            return '', 'declined', dict(row)
        if row['state'] == 'local_only':
            return '', 'retries_exhausted', dict(row)
        if _lease_is_live(row, now):
            return '', 'already_claimed', dict(row)
        if row['state'] == 'prepared' and not consent:
            return '', 'consent_required', dict(row)
        if int(row['attempts']) >= MAX_SEND_ATTEMPTS:
            conn.execute("UPDATE wish_submissions SET state='local_only',lease_id='',"
                         'lease_expires_at=NULL,updated_at=? WHERE submission_id=?',
                         (now, submission_id))
            return '', 'retries_exhausted', dict(row)
        if row['retry_not_before'] and now < row['retry_not_before']:
            return '', 'retry_too_soon', dict(row)
        allowed, reason, _retry = rate_limit(row['dedupe_key'], now=now, conn=conn)
        if not allowed:
            return '', reason, dict(row)
        moved = conn.execute(
            "UPDATE wish_submissions SET state='sending',lease_id=?,lease_expires_at=?,"
            'consented_at=COALESCE(consented_at,?),attempts=attempts+1,updated_at=? '
            "WHERE submission_id=? AND state IN ('prepared','consented','failed') "
            'AND approval_hash=?',
            (lease, now + SEND_LEASE_S, now if consent else None, now,
             submission_id, hash_presented)).rowcount
        if not moved:
            return '', 'already_claimed', dict(row)
    return lease, '', submission(submission_id)


def _release(submission_id, lease, state, *, receipt=None, remote_id=None,
             retry_not_before=None):
    """Finish a leased send, and only if this caller still holds the lease."""
    conn = connection()
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute(
            'UPDATE wish_submissions SET state=?,receipt=COALESCE(?,receipt),'
            "remote_id=COALESCE(?,remote_id),retry_not_before=?,lease_id='',"
            'lease_expires_at=NULL,updated_at=? WHERE submission_id=? AND lease_id=?',
            (state, json.dumps(receipt) if receipt is not None else None, remote_id,
             retry_not_before, time.time(), submission_id, lease))
    return public_submission(submission_id)


def _persist_remote_id(submission_id, lease, remote_id):
    """Write the created report's id BEFORE uploading into it.

    A lost PUT acknowledgment otherwise retries by CREATING a second remote
    report, which the review reproduced: two reports, one wish, demand counted
    twice by the owner's importer.
    """
    conn = connection()
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('UPDATE wish_submissions SET remote_id=?,updated_at=? '
                     'WHERE submission_id=? AND lease_id=?',
                     (remote_id, time.time(), submission_id, lease))


def recover_stale_sends(*, now=None):
    """Return expired `sending` rows to a retryable state. Idempotent.

    A process that dies mid-upload leaves a lease behind; without this the row
    stays `sending` forever and the one-in-flight rule blocks every future send
    on the installation. The row keeps its attempts, its approval and its
    `remote_id`, so the recovery retries INTO the same remote report.
    """
    now = time.time() if now is None else now
    conn = connection()
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        changed = conn.execute(
            "UPDATE wish_submissions SET state='failed',lease_id='',lease_expires_at=NULL,"
            "updated_at=? WHERE state='sending' AND COALESCE(lease_expires_at,0)<=?",
            (now, now)).rowcount
    return changed


def submit(submission_id, *, approval_hash_presented, create, upload, consent=False,
           auth_headers=None, now=None):
    """**The single way a wish leaves this machine.**

    Args:
        submission_id: the exact submission the user approved. Keyed on the
            submission, not on "the latest row for this feature" -- the review
            showed any non-empty hash retrieving somebody else's receipt.
        approval_hash_presented: the hash the user was shown, covering the
            payload, the identity choice AND the frozen bundle bytes.
        create: ``callable(meta, headers) -> report_id``.
        upload: ``callable(report_id, zip_bytes) -> {'notified': bool}``.
            Both raise :class:`TransportRefused` for a refusal.
        consent: must be the boolean `True` for a first send.

    Returns:
        SubmissionResult. Never raises for an ordinary refusal.

    The gate is checked FIRST: with `NUCLEUS_WISH_SUBMIT=0` nothing is claimed,
    no attempt is counted and no state is written -- a build that cannot send
    must not leave rows behind that look like it tried.
    """
    if not submit_enabled():
        return SubmissionResult(state='submission_disabled', reason='submission_disabled',
                                submission_id=submission_id)
    recover_stale_sends(now=now)
    row = submission(submission_id)
    if row is None:
        return SubmissionResult(state='failed', reason='unknown_submission')
    # An already-completed send returns ITS receipt -- matched by submission id
    # AND approval hash, so a repeated click is a lost acknowledgment rather
    # than an excuse to file again.
    if row['state'] == 'sent' and row['receipt'] and row['approval_hash'] == approval_hash_presented:
        return SubmissionResult(state='sent', submission_id=submission_id,
                                receipt=json.loads(row['receipt']), reason='already_sent')
    still_unsupported, _name = availability(row['dedupe_key'])
    if not still_unsupported:
        return SubmissionResult(state='failed', submission_id=submission_id,
                                reason='capability_now_supported')

    lease, reason, claimed = claim_send(submission_id, approval_hash_presented,
                                        consent=consent, now=now)
    if not lease:
        if reason == 'already_sent' and claimed and claimed.get('receipt'):
            return SubmissionResult(state='sent', submission_id=submission_id,
                                    receipt=json.loads(claimed['receipt']),
                                    reason='already_sent')
        state = 'local_only' if reason == 'retries_exhausted' else (
            claimed['state'] if claimed else 'failed')
        retry_after = None
        if reason == 'retry_too_soon' and claimed:
            retry_after = max(0, round((claimed['retry_not_before'] or 0) - time.time()))
        return SubmissionResult(state=state, submission_id=submission_id, reason=reason,
                                retry_after=retry_after)

    try:
        bundle = frozen_bundle(submission_id)
    except ConsentInvalid as exc:
        _release(submission_id, lease, 'failed')
        return SubmissionResult(state='failed', submission_id=submission_id,
                                reason='consent_invalid', detail={'error': str(exc)})

    payload = json.loads(claimed['payload'])
    meta = {
        'kind': 'capability_gap',
        'app_version': payload['app_version'],
        'platform': payload['platform'],
        # The approved, bounded summary: catalogue text, never chat text.
        'description': summary_sentence(payload),
        'contact': '',
        'zip_size': len(bundle),
        'wish': payload,
    }
    headers = auth_headers if claimed['include_identity'] else {}
    remote_id = claimed['remote_id']
    try:
        if not remote_id:
            remote_id = create(meta, headers or {})
            if not remote_id:
                raise TransportRefused('report server returned no id')
            _persist_remote_id(submission_id, lease, remote_id)
        receipt = upload(remote_id, bundle) or {}
    except TransportRefused as exc:
        return _failed(submission_id, lease, claimed, reason='transport_refused',
                       status=exc.status, detail=exc.detail, remote_id=remote_id)
    except Exception as exc:                                    # noqa: BLE001
        return _failed(submission_id, lease, claimed, reason='transport_error',
                       detail={'error': str(exc)}, remote_id=remote_id)

    receipt = {'id': remote_id, 'notified': bool(receipt.get('notified')),
               'size': len(bundle)}
    _release(submission_id, lease, 'sent', receipt=receipt, remote_id=remote_id)
    return SubmissionResult(state='sent', submission_id=submission_id, receipt=receipt)


def _failed(submission_id, lease, claimed, *, reason, status=None, detail=None,
            remote_id=None):
    """Record a failed attempt truthfully, with its backoff or its exhaustion."""
    detail = detail or {}
    # `claimed` was read AFTER the claim transaction bumped it, so this IS the
    # attempt that just failed -- not one before it.
    attempts = int(claimed['attempts'])
    retry_after = detail.get('retry_after')
    try:
        retry_after = float(retry_after) if retry_after is not None else None
    except (TypeError, ValueError):
        retry_after = None
    exhausted = attempts >= MAX_SEND_ATTEMPTS
    # Exponential backoff when the server did not name a delay, and always at
    # least what it did name: `retry_after` was stored and never enforced.
    delay = retry_after if retry_after is not None else min(300, 15 * (2 ** (attempts - 1)))
    _release(submission_id, lease, 'local_only' if exhausted else 'failed',
             remote_id=remote_id or None,
             retry_not_before=None if exhausted else time.time() + delay)
    return SubmissionResult(state='local_only' if exhausted else 'failed',
                            submission_id=submission_id,
                            reason='retries_exhausted' if exhausted else reason,
                            http_status=status, detail=detail,
                            retry_after=None if exhausted else round(delay))


def decline(key):
    """Keep it on this device. Refuses to cancel an upload already in flight."""
    row = connection().execute(
        'SELECT * FROM wish_submissions WHERE dedupe_key=? ORDER BY updated_at DESC LIMIT 1',
        (key,)).fetchone()
    if _lease_is_live(row):
        raise SubmissionBusy('That feature request is being sent right now.')
    if row is not None and row['state'] not in ('sent',):
        conn = connection()
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute("UPDATE wish_submissions SET state='declined',lease_id='',"
                         'lease_expires_at=NULL,updated_at=? WHERE submission_id=? '
                         "AND state NOT IN ('sent','sending')",
                         (time.time(), row['submission_id']))
    return True
