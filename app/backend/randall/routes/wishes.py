"""The feature-request surface: the owner's local backlog, and one reviewed,
summary-only submission through the EXISTING bug-report transport.

Design source: artifacts/harness-experiment-20260922/ASTRA-WISH.md, section 4.
Review answered here: artifacts/harness-experiment-20260922/ASTRA-REVIEW-WISHES.md.

This module is the HTTP surface, nothing else; the two network callables are
`reports/report_transport.py`. `reports/wishes.py` owns the records, the counts, the payload, the
frozen bundle, the consent binding, the send lease, the retry policy, the
release gate and the state machine; `wishes.submit()` calls the two transport
callables this module hands it. Keeping the policy in one module is what stops a second
call site from growing its own rules -- and what let the review interleave a
rate check, a consent write and a `sending` claim into two uploads of one
report.

What this blueprint is careful about, and why:

* **It reuses the bug-report path, not the bug-report payload.** The transport
  is the same two-stage POST/PUT against the same Cloudflare worker, using
  `shared.diagnostics.bug_report`'s URL, platform channel and auth helper, so there is
  one report pipeline and one set of worker limits. What it does NOT reuse is
  `_build_logs_zip()`: that walks the app log directory automatically, and a
  feature request must carry nothing the user did not choose.
* **Review freezes; submit sends what was frozen.** `GET .../review` collects
  the attachment BYTES, assembles the finished ZIP, writes it to disk and
  returns the disclosure manifest plus one `approval_hash` over payload +
  identity choice + every member's hash. `POST .../submit` quotes that hash and
  the submission id back; nothing is re-collected, so logs that change between
  review and send cannot ride along unapproved.
* **Booleans must be booleans.** `consent` and `include_identity` are checked
  with `wishes.strict_bool`; the JSON string `"false"` is rejected, not
  coerced. The review switched identity ON with it.
* **Anonymous by default.** The backend's bug-report helper forwards a Discord
  session whenever one exists. Here it is passed to `wishes.submit`,
  which attaches it only when the FROZEN manifest says identity was approved.
* **Closing sends nothing.** There is no implicit submit and no model-callable
  submission action: every route here is user-driven.
* **`NUCLEUS_WISH_SUBMIT=0` closes sending only.** Wishes are still recorded and
  counted, the backlog still lists them, and `review` still shows what WOULD be
  sent -- with `can_send: false`. `submit` answers 403 `submission_disabled`
  without touching the network or writing a submission row.
"""
import json
import logging

from flask import Blueprint, jsonify, request

from randall.assistant import capabilities
from randall.reports.report_transport import _make_create, _make_upload
from randall.reports import wishes as wishlib

logger = logging.getLogger(__name__)

wishes_bp = Blueprint('wishes', __name__)

#: Attachments a user may opt into. Empty selection is the default and the
#: documented behaviour: no app logs, no Electron diagnostics, no Slippi logs,
#: no conversation excerpt. Anything not named here is refused rather than
#: silently dropped, so a client cannot believe it attached something.
ALLOWED_ATTACHMENTS = ('app_logs',)

#: Uncompressed budget for an opted-in log attachment. Well under the worker cap.
_ATTACHMENT_BUDGET = 16 * 1024 * 1024


def _transport():
    """The existing bug-report transport's own settings, read at call time."""
    from shared.diagnostics import bug_report as setup_module
    return setup_module


def _full_key(key):
    """Accept the bare sha256 hex the UI carries and restore the stored form."""
    key = (key or '').strip()
    return key if key.startswith('sha256:') else f'sha256:{key}'


def _collector(setup_module):
    """Supplies an opted-in attachment's BYTES, at review time.

    Called while the user is still deciding, so what they approve is a specific
    set of bytes with a specific hash rather than "whatever the log folder holds
    when they click".
    """
    def collect(name):
        if name == 'app_logs':
            logs, _added, _slippi, _truncated = setup_module._build_logs_zip(
                '', budget_bytes=_ATTACHMENT_BUDGET)
            return logs.getvalue()
        raise ValueError(f'unsupported attachment {name!r}')
    return collect


def _consent_text(manifest):
    """The sentence shown beside the send button.

    Generated from the FROZEN manifest, so it cannot describe something other
    than what the approval hash covers.
    """
    members = [m for m in manifest.get('members', []) if m['name'] != 'wish.json']
    parts = ['Sent privately to the Nucleus developer.']
    if not members:
        parts.append('No conversation or files included.')
    else:
        parts.append('Included: ' + ', '.join(
            f"{m['name']} ({m['bytes']} bytes)" for m in members) + '.')
    parts.append('Your Discord identity is included.'
                 if manifest.get('include_discord_identity') else 'Sent anonymously.')
    parts.append('Files stay behind a private link for 90 days.')
    return ' '.join(parts)


def _bad_choice(exc):
    return jsonify({'success': False, 'error': 'invalid_choice', 'detail': str(exc)}), 400


@wishes_bp.route('/api/mex/wishes', methods=['GET'])
def list_wishes():
    """The owner's local backlog: one row per capability and variant, with counts.

    Sorted by requesting conversations, which is the demand number the design
    defines. Locally saved, declined and pre-module `legacy` wishes are visible
    HERE (this is the user's own device); only submitted ones reach the
    developer.
    """
    try:
        wishlib.recover_stale_sends()
        rows = wishlib.backlog()
        return jsonify({'success': True, 'wishes': rows, 'count': len(rows),
                        'submission_enabled': wishlib.submit_enabled(),
                        'capabilities_version': capabilities.CAPABILITIES_VERSION})
    except Exception as exc:
        logger.error('Wish backlog error: %s', exc, exc_info=True)
        return jsonify({'success': False, 'error': str(exc)}), 500


@wishes_bp.route('/api/mex/wishes/capability_status', methods=['GET'])
def read_capability_status():
    """`supported` | `unsupported` | `outside_scope` | `unknown` for one operation.

    `scope` narrows it to one input -- a build format, a mask kind -- because
    most operations are missing for some inputs rather than absent.
    """
    operation = (request.args.get('operation') or '').strip()
    if not operation:
        return jsonify({'success': False, 'error': 'An operation is required'}), 400
    scope = (request.args.get('scope') or '').strip()
    return jsonify({'success': True, **capabilities.describe(operation, scope)})


@wishes_bp.route('/api/mex/wishes/<key>/review', methods=['GET'])
def review_wish(key):
    """Freeze the complete outgoing contents and return them for approval.

    Nothing is sent. The response carries the payload, the disclosure manifest
    (identity choice, every ZIP member with its size and hash), the single
    `approval_hash` over all of it, and the submission id to quote back.

    Never disturbs an upload in flight or a completed one: a live send is
    returned as-is, a completed send keeps its receipt, and a changed count
    becomes a NEW snapshot instead of rewriting an approval somebody already
    gave.

    Still answers with the gate closed, so the user can see what was recorded
    and what a future build would send -- `can_send` false,
    `blocked_reason: submission_disabled`.
    """
    key = _full_key(key)
    if not wishlib.valid_key(key):
        return jsonify({'success': False, 'error': 'unknown_feature_request'}), 404
    setup_module = _transport()
    try:
        include_identity = wishlib.strict_bool(request.args.get('identity') == '1')
        attachments = [a for a in (request.args.get('attachments') or '').split(',') if a]
        unsupported = [a for a in attachments if a not in ALLOWED_ATTACHMENTS]
        if unsupported:
            return jsonify({'success': False, 'error': 'unsupported_attachment',
                            'attachments': unsupported}), 400
        wishlib.recover_stale_sends()
        row = wishlib.prepare_submission(
            key, platform=setup_module.bugreport_channel(),
            workflow=(request.args.get('workflow') or '').strip(),
            include_identity=include_identity, attachments=attachments,
            collect=_collector(setup_module))
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 404
    except Exception as exc:
        logger.error('Wish review error: %s', exc, exc_info=True)
        return jsonify({'success': False, 'error': str(exc)}), 500

    still_unsupported, _name = wishlib.availability(key)
    if not wishlib.submit_enabled():
        allowed, reason, retry_after = False, 'submission_disabled', None
    elif not still_unsupported:
        allowed, reason, retry_after = False, 'capability_now_supported', None
    elif row['active']:
        allowed, reason, retry_after = False, 'another_submission_in_flight', None
    else:
        allowed, reason, retry_after = wishlib.rate_limit(key)
    return jsonify({
        'success': True,
        'submission_id': row['submission_id'],
        'payload': json.loads(wishlib.submission(row['submission_id'])['payload']),
        'approval_hash': row['approval_hash'],
        'manifest': row['manifest'],
        'requesting_conversations': row['approved_count'],
        'state': row['state'],
        'active': row['active'],
        'receipt': row['receipt'],
        'suppressed': wishlib.is_suppressed(key),
        'allowed_attachments': list(ALLOWED_ATTACHMENTS),
        'consent_text': _consent_text(row['manifest']),
        'submission_enabled': wishlib.submit_enabled(),
        'still_unsupported': still_unsupported,
        'can_send': allowed, 'blocked_reason': reason, 'retry_after': retry_after,
    })


@wishes_bp.route('/api/mex/wishes/<key>/submit', methods=['POST'])
def submit_wish(key):
    """Send one reviewed feature request through the existing report worker.

    Body: ``{submission_id, approval_hash, consent: true}``. The submission id
    names the exact approved snapshot -- not "the latest row for this feature",
    which let any non-empty hash collect somebody else's receipt -- and the hash
    covers the payload, the identity choice and the frozen bundle bytes.

    The policy lives in `wishes.submit()`; this handler validates the request,
    builds the two transport callables, and translates the typed result into a
    status code.
    """
    key = _full_key(key)
    body = request.get_json(silent=True) or {}
    approved_hash = (body.get('approval_hash') or body.get('payload_hash') or '').strip()
    submission_id = (body.get('submission_id') or '').strip()
    try:
        consent = wishlib.strict_bool(body.get('consent'))
    except ValueError as exc:
        return _bad_choice(exc)
    if not consent or not approved_hash or not submission_id:
        return jsonify({'success': False, 'error': 'consent_required'}), 400

    setup_module = _transport()
    row = wishlib.submission(submission_id)
    if row is None or row['dedupe_key'] != key:
        return jsonify({'success': False, 'error': 'unknown_submission'}), 404

    result = wishlib.submit(
        submission_id, approval_hash_presented=approved_hash, consent=consent,
        create=_make_create(setup_module), upload=_make_upload(setup_module),
        auth_headers=setup_module._bugreport_auth_headers())

    if result.state == 'submission_disabled':
        # Recorded and counted; simply not sendable in this build. Say exactly
        # that rather than implying the request was lost.
        return jsonify({'success': False, 'error': 'submission_disabled',
                        'state': result.state,
                        'detail': 'Feature requests are saved on this device in this build; '
                                  'sending them is not enabled yet.'}), 403
    if result.sent:
        logger.info('Feature request %s sent (%s, notified=%s)', wishlib.short_key(key),
                    result.receipt.get('id'), result.receipt.get('notified'))
        return jsonify({'success': True, 'state': 'sent',
                        'submission_id': result.submission_id, **result.receipt})

    out = {'success': False, 'state': result.state, 'reason': result.reason}
    if result.retry_after is not None:
        out['retry_after'] = result.retry_after
    for field in ('latest', 'url', 'notes'):
        if (result.detail or {}).get(field) is not None:
            out[field] = result.detail[field]
    status, error = _status_for(result)
    out['error'] = error
    return jsonify(out), status


def _status_for(result):
    """Map a typed submission outcome onto an HTTP status and error name."""
    if result.reason == 'consent_invalid':
        return 409, 'consent_invalid'
    if result.reason in ('consent_required',):
        return 400, 'consent_required'
    if result.reason in ('unknown_submission', 'declined'):
        return 404, result.reason
    if result.reason == 'capability_now_supported':
        return 409, 'capability_now_supported'
    if result.reason in ('already_sent_today', 'daily_limit_reached',
                         'another_submission_in_flight', 'already_claimed',
                         'retry_too_soon'):
        return 429, 'rate_limited'
    if result.reason == 'retries_exhausted':
        # Truthful terminal state: it is saved here and it was not sent.
        return 409, 'retries_exhausted'
    if result.http_status in (426, 429):
        return result.http_status, ('update_required' if result.http_status == 426
                                    else 'rate_limited')
    if result.reason == 'transport_error':
        return 502, 'Could not reach the report server'
    return 502, result.reason or 'failed'


@wishes_bp.route('/api/mex/wishes/<key>/decline', methods=['POST'])
def decline_wish(key):
    """"Keep on this device", and optionally "don't ask again for this feature".

    Sends nothing, and refuses to cancel an upload already in flight.
    Suppression hides the invitation; local counting continues, because the gap
    has not stopped being real.
    """
    key = _full_key(key)
    body = request.get_json(silent=True) or {}
    try:
        suppress = wishlib.strict_bool(body.get('suppress', False))
    except ValueError as exc:
        return _bad_choice(exc)
    try:
        wishlib.decline(key)
    except wishlib.SubmissionBusy as exc:
        return jsonify({'success': False, 'error': 'another_submission_in_flight',
                        'detail': str(exc)}), 409
    if suppress:
        wishlib.suppress(key)
    return jsonify({'success': True, 'state': 'declined',
                    'suppressed': wishlib.is_suppressed(key)})
