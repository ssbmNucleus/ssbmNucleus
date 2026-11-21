"""Who may change a build, recorded where the caller cannot reach it.

An authorization is the user's decision about one exact proposal. Three things
follow from that, and all three are enforced here rather than in the library the
model calls:

* **Only the app grants one.** :func:`grant` is backend code, reached from the
  approval endpoint (``POST /api/mex/builds/changes/<id>/approve``). Nothing in
  ``nucleus_api`` can mint one, so a model can ask for approval and cannot give
  itself approval.
* **It names its whole subject.** The record binds the task and task revision,
  the build and its revision, every destination with its before/after hash, the
  code list's exact text, the target signature, the compiler identity and the
  unknowns the user accepted. That binding is a digest computed from the
  proposal itself, so it cannot be satisfied by a stored string.
* **It is checked against the proposal again, at the moment of use.**
  :func:`verify` recomputes the digest from the manifest on disk. Editing the
  manifest after approval - including its ``codes.ini`` text, which is what
  actually gets executed - changes the recomputed digest and the commit is
  refused.

Registrations and authorizations live under :func:`trust_root`, which is app
data, not the model's workspace. The library's own workspace rules make that
directory unreachable from a caller-supplied path.
"""
import hashlib
import json
import os
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from .build_transaction import TransactionError, assert_contained, write_json_durably

ID_PATTERNS = {
    'artifact': re.compile(r'^art_[0-9a-f]{16}$'),
    'prepared_change': re.compile(r'^pc_b[0-9a-f]{12}_[0-9a-f]{12}$'),
    'authorization': re.compile(r'^auth_b[0-9a-f]{12}_[0-9a-f]{12}$'),
    'receipt': re.compile(r'^rc_b[0-9a-f]{12}_[0-9a-f]{12}$'),
    'build': re.compile(r'^b[0-9a-f]{12}$'),
}

#: Every field of a proposal the user's decision is bound to. A proposal that
#: does not carry one of these cannot be authorized: the user would be agreeing
#: to something the record does not describe.
BOUND_FIELDS = ('build_id', 'build_path', 'before_revision', 'target', 'writes',
                'codes_ini_sha256', 'codes_required', 'compiler', 'unknown_dimensions',
                'preview_status',
                # The task this was proposed for, and the revision of it the
                # user was looking at. Without these an authorization is about
                # a change, not about a request: it would survive the user
                # revising or cancelling what they asked for.
                'task_id', 'task_revision')


class AuthorizationError(ValueError):
    """An authorization is missing, malformed, spent, or no longer describes reality."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def valid_id(kind, value):
    """True when ``value`` is a well-formed id of that kind.

    Ids are used as filenames, so they are opaque and strictly shaped: a value
    that is not exactly ``<prefix>_<hex>`` never reaches the filesystem.

    Args:
        kind: one of :data:`ID_PATTERNS`.
        value: the candidate id.

    Returns:
        bool: whether it matches.

    Example:
        >>> valid_id('artifact', '../../etc/passwd')
        False
    """
    pattern = ID_PATTERNS.get(kind)
    return bool(pattern and isinstance(value, str) and pattern.match(value))


def require_id(kind, value):
    """Return ``value`` if it is a well-formed id of that kind, else raise.

    Args:
        kind: one of :data:`ID_PATTERNS`.
        value: the candidate id.

    Returns:
        str: the id.

    Raises:
        AuthorizationError: ``malformed_id``.

    Example:
        >>> require_id('build', 'b0123456789ab')
        'b0123456789ab'
    """
    if not valid_id(kind, value):
        raise AuthorizationError('malformed_id',
                                 f'{value!r} is not a {kind} id. Ids come from this library; '
                                 'they are not paths and cannot be composed by hand.')
    return value


def trust_root():
    """The app-owned directory holding registrations and authorizations.

    ``NUCLEUS_BUILD_TRUST_ROOT`` when set (the harness and the tests point it at
    their own directory), otherwise ``<app data root>/build_changes``. It is
    deliberately NOT the library workspace: a record the model can rewrite is
    not a record of the user's decision.

    Returns:
        pathlib.Path: the created directory.

    Example:
        >>> trust_root().name
        'build_changes'
    """
    override = os.environ.get('NUCLEUS_BUILD_TRUST_ROOT', '').strip()
    if override:
        root = Path(override).expanduser().resolve()
    else:
        from . import config
        root = Path(config.PROJECT_ROOT).resolve() / 'build_changes'
    root.mkdir(parents=True, exist_ok=True)
    return root


def store_path(bucket, identifier, kind):
    """The file for one record, with the id validated before it becomes a path."""
    require_id(kind, identifier)
    directory = trust_root() / bucket
    directory.mkdir(parents=True, exist_ok=True)
    return assert_contained(directory, f'{identifier}.json', what='record path')


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def subject_digest(manifest):
    """Recompute the digest of everything a user's decision is bound to.

    Computed from the proposal itself every time it is needed - never read back
    from a stored field - so an edited manifest cannot keep an old approval.

    Args:
        manifest: a sealed proposal from
            :func:`nucleus_api.builds.prepare_change`.

    Returns:
        str: 64 hex characters.

    Raises:
        AuthorizationError: ``incomplete_proposal`` when a bound field is absent.

    Example:
        >>> subject_digest(manifest) == manifest['subject_digest']
        True
    """
    bound = {}
    for field in BOUND_FIELDS:
        if field not in manifest:
            raise AuthorizationError(
                'incomplete_proposal',
                f'This proposal has no {field!r}; a user cannot authorize what it does not '
                'describe.')
        bound[field] = manifest[field]
    # The code list is bound by the digest of the text that will actually be
    # EXECUTED, measured here - not by the field sitting next to it. Editing the
    # INI while keeping its stored digest is the exact escape this closes.
    ini = (manifest.get('codes') or {}).get('ini')
    measured = hashlib.sha256(ini.encode('utf-8')).hexdigest() if ini else None
    if measured != manifest['codes_ini_sha256']:
        raise AuthorizationError(
            'proposal_tampered',
            "This proposal's code list is not the text its own digest describes. It was "
            'edited after it was sealed; nothing will be committed from it.')
    bound['codes_ini_sha256'] = measured
    canonical = json.dumps(bound, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def grant(manifest, *, granted_by, task_id, task_revision, accepted_unknown=(),
          consent_reference=''):
    """Record the user's decision about one proposal. Backend only.

    Called by the approval endpoint after the user clicked its card. Not
    exported through ``nucleus_api``: model-facing code can build a proposal and
    ask for it to be shown, and cannot grant it.

    Args:
        manifest: the sealed proposal the user was shown.
        granted_by: the identity the app authenticated, not a caller's string.
        task_id: the task this decision belongs to.
        task_revision: that task's revision when the card was shown. A later
            revision invalidates the decision.
        accepted_unknown: the unknown compatibility dimensions the user
            explicitly accepted. Anything not listed blocks the commit.
        consent_reference: the app's own record of the click, for the receipt.

    Returns:
        dict: the authorization record.

    Raises:
        AuthorizationError: the proposal is blocked, incomplete, or accepts an
            unknown it does not have.

    Example:
        >>> grant(manifest, granted_by='user', task_id='task_1', task_revision=1,
        ...       accepted_unknown=manifest['unknown_dimensions'])['used']
        False
    """
    if manifest.get('status') != 'prepared':
        raise AuthorizationError(
            'blocked_change',
            f'{manifest.get("prepared_change_id")} is {manifest.get("status")}: '
            f'{(manifest.get("error") or {}).get("message")}. It cannot be authorized.')
    if not (granted_by or '').strip():
        raise AuthorizationError('no_grantor', 'An authorization must name who granted it.')
    if not (task_id or '').strip():
        raise AuthorizationError('no_task', 'An authorization must name its task.')
    if task_id != manifest.get('task_id') or int(task_revision) != int(
            manifest.get('task_revision') or 0):
        raise AuthorizationError(
            'task_mismatch',
            f'This proposal was prepared for task {manifest.get("task_id")!r} revision '
            f'{manifest.get("task_revision")}, and the approval names {task_id!r} revision '
            f'{task_revision}. An authorization is a decision about one request.')
    unknown = set(manifest.get('unknown_dimensions') or [])
    accepted = set(accepted_unknown or [])
    stray = sorted(accepted - unknown)
    if stray:
        raise AuthorizationError(
            'unknown_not_in_proposal',
            f'{stray} are not unknowns of this proposal; accepting them would record a '
            'decision the user was never shown.')
    prepared_change_id = require_id('prepared_change', manifest.get('prepared_change_id'))
    build_id = require_id('build', manifest.get('build_id'))
    record = {
        'authorization_id': f'auth_{build_id}_{secrets.token_hex(6)}',
        'prepared_change_id': prepared_change_id,
        'build_id': build_id,
        'build_path': manifest['build_path'],
        'subject_digest': subject_digest(manifest),
        'build_revision': manifest['before_revision'],
        'destinations': sorted(w['destination'] for w in manifest['writes']),
        'codes_ini_sha256': manifest['codes_ini_sha256'],
        'target': manifest['target'],
        'compiler': manifest['compiler'],
        'granted_by': granted_by,
        'task_id': task_id,
        'task_revision': int(task_revision),
        'accepted_unknown': sorted(accepted),
        'consent_reference': consent_reference,
        'granted_utc': _utc(),
        'used': False,
        'receipt_id': None,
    }
    write_json_durably(store_path('authorizations', record['authorization_id'],
                                  'authorization'), record)
    return record


def load(authorization_id):
    """Read an authorization record, or raise ``unknown_authorization``."""
    path = store_path('authorizations', authorization_id, 'authorization')
    if not path.is_file():
        raise AuthorizationError('unknown_authorization',
                                 f'No authorization {authorization_id!r} was granted.')
    return json.loads(path.read_text(encoding='utf-8'))


def verify(authorization, manifest, *, build_revision, task_revision=None):
    """Check, at the moment of use, that the decision still describes reality.

    Args:
        authorization: the record from :func:`load`.
        manifest: the sealed proposal as it is on disk NOW.
        build_revision: the build's revision measured under the lock.
        task_revision: the task's current revision, when the caller tracks one.

    Returns:
        dict: the authorization.

    Raises:
        AuthorizationError: ``authorization_mismatch``, ``stale_authorization``
            or ``authorization_spent``.

    Example:
        >>> verify(auth, manifest, build_revision=rev)['used']
        False
    """
    if authorization['prepared_change_id'] != manifest['prepared_change_id']:
        raise AuthorizationError(
            'authorization_mismatch',
            f'{authorization["authorization_id"]} authorizes '
            f'{authorization["prepared_change_id"]}, not {manifest["prepared_change_id"]}.')
    recomputed = subject_digest(manifest)
    if recomputed != authorization['subject_digest']:
        raise AuthorizationError(
            'stale_authorization',
            'The proposal is not the one that was authorized any more - its destinations, '
            'hashes, code list, target or accepted unknowns changed. Prepare it again and '
            'ask the user again.')
    if authorization['build_revision'] != build_revision:
        raise AuthorizationError(
            'stale_authorization',
            f'The build is at {build_revision}; this decision was made about '
            f'{authorization["build_revision"]}. Something else wrote it in between.')
    if task_revision is not None and int(task_revision) != authorization['task_revision']:
        raise AuthorizationError(
            'stale_authorization',
            f'The task moved to revision {task_revision}; this decision was made at '
            f'revision {authorization["task_revision"]}.')
    return authorization


# ---------------------------------------------------------------------------
# The approval challenge
# ---------------------------------------------------------------------------

#: How long a challenge minted for one card stays usable.
CHALLENGE_SECONDS = 300


def mint_challenge(prepared_change_id, subject_digest):
    """A single-use, expiring secret that only the displayed card carries.

    Knowing the proposal's digest proves the proposal, not that anybody looked
    at it. The challenge is minted when the card is fetched and consumed when it
    is approved, so a replayed digest cannot mint a second authorization.

    Args:
        prepared_change_id: the proposal being shown.
        subject_digest: what the card will display it as.

    Returns:
        dict: ``{'challenge': str, 'expires_utc': str}``.

    Example:
        >>> mint_challenge(change_id, digest)['challenge'][:4]
        'a1b2'
    """
    require_id('prepared_change', prepared_change_id)
    record = {'prepared_change_id': prepared_change_id, 'subject_digest': subject_digest,
              'challenge': secrets.token_urlsafe(24),
              'issued': time.time(), 'used': False}
    write_json_durably(store_path('challenges', prepared_change_id, 'prepared_change'), record)
    return {'challenge': record['challenge'],
            'expires_utc': datetime.fromtimestamp(record['issued'] + CHALLENGE_SECONDS,
                                                  timezone.utc).isoformat(timespec='seconds')}


def consume_challenge(prepared_change_id, challenge, subject_digest):
    """Spend the challenge for this card, or refuse.

    Args:
        prepared_change_id: the proposal being approved.
        challenge: the secret the card carried.
        subject_digest: what the card displayed it as.

    Returns:
        dict: the consumed record.

    Raises:
        AuthorizationError: no challenge, expired, already used, or for
            something else.

    Example:
        >>> consume_challenge(change_id, challenge, digest)['used']
        True
    """
    path = store_path('challenges', prepared_change_id, 'prepared_change')
    if not path.is_file():
        raise AuthorizationError(
            'no_challenge',
            'Nothing was displayed for this change, so there is no decision to record. '
            'Open the approval card first.')
    record = json.loads(path.read_text(encoding='utf-8'))
    if record.get('used'):
        raise AuthorizationError('challenge_spent',
                                 'That approval card was already answered.')
    if time.time() - float(record.get('issued') or 0) > CHALLENGE_SECONDS:
        raise AuthorizationError('challenge_expired',
                                 'That approval card is older than five minutes. Open it '
                                 'again so the decision is about the change as it is now.')
    if not challenge or not secrets.compare_digest(str(record.get('challenge')),
                                                   str(challenge)):
        raise AuthorizationError('challenge_mismatch',
                                 'This approval does not carry the card that was shown.')
    if record.get('subject_digest') != subject_digest:
        raise AuthorizationError('challenge_stale',
                                 'The change moved since that card was shown.')
    record['used'] = True
    record['used_at'] = time.time()
    write_json_durably(path, record)
    return record


def consumption_record(authorization, receipt_id):
    """The authorization as it will be written once it has been spent."""
    return {**authorization, 'used': True, 'receipt_id': receipt_id,
            'used_utc': _utc()}


def _authorization_destination(build_dir, identifier):
    """Where an authorization record lives - derived, never taken from a journal.

    Recovery reads journals out of a build directory, which a project someone
    else authored can contain. The journal names a KIND and an id; this resolves
    the only place that id may be written, after validating it.
    """
    require_id('authorization', identifier)
    return store_path('authorizations', identifier, 'authorization')


def _register_finalizers():
    from .build_transaction import register_finalizer
    register_finalizer('authorization', _authorization_destination)


_register_finalizers()
