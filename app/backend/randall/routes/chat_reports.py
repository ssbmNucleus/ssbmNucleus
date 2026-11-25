""""Report this chat" -- the HTTP surface and the network, nothing else.

`reports/chat_report.py` owns the payload, scrubbing, size cap, frozen
bundle and send state. This blueprint validates requests and builds the two
transport callables from the bug-report path (`shared.diagnostics.bug_report`
URL, the create/upload helpers of `reports/report_transport.py` that the wish
blueprint uses too), so there is one report pipeline and one set of worker limits.

    POST /api/mex/chat-reports/review   {surface, conversation_id, note?, contact?,
                                         app_version?, budget?, include_files?}
        -> freezes the bundle; returns submission_id, approval_hash and the
           disclosure (members, plain-language list, readable transcript,
           `files` for the toggle). Sends nothing. The user's attached files
           and Randall's preview images go only with `include_files: true`
           (a real boolean); the choice is part of the approval hash.
           Send passes `base_submission` (the previewed freeze): its files
           part is reused byte for byte, or 409 `review_again` asks the user
           to look at a new preview first.
    POST /api/mex/chat-reports/submit   {submission_id, approval_hash, consent: true}
        -> sends exactly the frozen bytes. 426 update_required / 429
           rate_limited pass through from the worker. Window only (the
           window's own key, core/ui_channel.py): the consent is the person's,
           and anything else holding the backend token could otherwise send a
           conversation off the machine in their name.

Reports are anonymous: no Discord bearer is attached.
"""
import logging
import os

from flask import Blueprint, jsonify, request

from core import ui_channel
from randall.reports import chat_report

logger = logging.getLogger(__name__)

chat_reports_bp = Blueprint('chat_reports', __name__)


def _transport():
    """The existing bug-report transport, read at call time (tests replace it)."""
    from shared.diagnostics import bug_report as setup_module
    from randall.reports import report_transport
    create = report_transport._make_create(setup_module)
    upload = report_transport._make_upload(setup_module)
    return (lambda meta: create(meta, {})), upload


@chat_reports_bp.route('/api/mex/chat-reports/review', methods=['POST'])
def review_chat_report():
    body = request.get_json(silent=True) or {}
    app_version = (os.environ.get('NUCLEUS_APP_VERSION') or '').strip() \
        or str(body.get('app_version') or '').strip()
    note = body.get('note') if isinstance(body.get('note'), str) else ''
    contact = body.get('contact') if isinstance(body.get('contact'), str) else ''
    try:
        prepared = chat_report.prepare(
            str(body.get('surface') or ''), body.get('conversation_id'),
            note=note, contact=contact, app_version=app_version,
            budget=body.get('budget') if isinstance(body.get('budget'), dict) else None,
            include_files=body.get('include_files') is True,
            base_submission=body.get('base_submission') if isinstance(body.get('base_submission'), str) else None)
    except chat_report.ReportError as exc:
        status = {'unknown_conversation': 404, 'review_again': 409, 'files_changing': 409}.get(str(exc), 400)
        return jsonify({'success': False, 'error': str(exc)}), status
    except Exception as exc:
        logger.error('Chat report review error: %s', exc, exc_info=True)
        return jsonify({'success': False, 'error': 'Could not prepare the report'}), 500
    return jsonify({'success': True, **prepared})


@chat_reports_bp.route('/api/mex/chat-reports/submit', methods=['POST'])
def submit_chat_report():
    refusal = ui_channel.window_refusal(request.headers)
    if refusal is not None:
        code, status = refusal
        return jsonify({'success': False, 'error': 'Only the person at the Nucleus window can send a report.',
                        'code': code}), status
    body = request.get_json(silent=True) or {}
    submission_id = str(body.get('submission_id') or '').strip()
    approval = str(body.get('approval_hash') or '').strip()
    if body.get('consent') is not True or not submission_id or not approval:
        return jsonify({'success': False, 'error': 'consent_required'}), 400
    create, upload = _transport()
    result = chat_report.submit(submission_id, approval_hash_presented=approval,
                                consent=True, create=create, upload=upload)
    state = result.get('state')
    if state == 'sent':
        logger.info('Chat report %s sent (%s bytes, notified=%s, confirmed=%s)',
                    result.get('id'), result.get('size'), result.get('notified'),
                    result.get('confirmed'))
        return jsonify({'success': True, **result})
    reason = result.get('reason')
    out = {'success': False, **result}
    if state == 'refused':
        status = {'unknown_submission': 404, 'consent_invalid': 409, 'already_sending': 409,
                  'retries_exhausted': 409, 'consent_required': 400}.get(reason, 409)
        out['error'] = reason
        return jsonify(out), status
    http = result.get('status')
    detail = result.get('detail') or {}
    if http == 426:
        out.update(error='update_required', latest=detail.get('latest'), url=detail.get('url'),
                   notes=detail.get('notes'))
        return jsonify(out), 426
    if http == 429:
        out.update(error='rate_limited', retry_after=detail.get('retry_after'))
        return jsonify(out), 429
    if reason == 'transport_error':
        out['error'] = 'Could not reach the report server'
        return jsonify(out), 502
    out['error'] = reason or 'failed'
    return jsonify(out), 502
