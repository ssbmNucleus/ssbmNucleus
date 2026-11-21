"""The approval card for a build change, and the only place one is granted.

``nucleus_api.builds`` can propose a change to the build the user plays. It
cannot approve one: minting an authorization is
:func:`core.build_authorization.grant`, and the only caller is this endpoint,
which runs when the user clicks the card.

    GET  /api/mex/builds/changes/<prepared_change_id>
        -> exactly what the card must show: the build, every destination with
           its before/after hash, the codes added/preserved/enabled, the three
           compatibility verdicts, the unknowns, the limitations, and the fact
           that no preview exists and no disc is being rebuilt.

    POST /api/mex/builds/changes/<prepared_change_id>/approve
        {"confirmed": true, "subjectDigest": "<what the card showed>",
         "taskId": "...", "taskRevision": 1, "acceptedUnknown": [...]}
        -> the authorization id, or 409 if the proposal has moved since.

``subjectDigest`` is what makes this an approval of something: the client sends
back the digest it displayed, and the grant is refused if the proposal on disk
no longer produces that digest. A client that did not read the card cannot
guess it.

``grantedBy`` is not accepted from the request. This is a local desktop app; the
grantor is the person at the machine, recorded as the OS account, not a string
the caller chose.
"""
import getpass
import logging

from flask import jsonify, request

from core import build_authorization, ui_channel

from vault.routes.menus import menus_bp

logger = logging.getLogger(__name__)


#: The window-only key (core/ui_channel.py): a SECOND secret, because the backend token is printed to stdout at
#: startup and separates nothing. It reaches the window through Electron's IPC and nothing else.
UI_KEY_ENV = ui_channel.UI_KEY_ENV
UI_KEY_HEADER = ui_channel.UI_KEY_HEADER

#: What this endpoint can and cannot establish, stated where it is served.
_CHANNEL_NOTE = (
    'This records a decision made in the Nucleus window: the approval carries a key only '
    'the window is given (never printed, never served), spends a single-use challenge minted '
    'with the card, and comes from a same-origin request. It does not prove WHO clicked; the '
    'OS account is audit context, not identity. While that key is unconfigured this endpoint '
    'refuses outright rather than accepting anything that can reach the port.')


def _refuse_non_ui_caller():
    """Refuse anything that is not the app's own window (core/ui_channel.py).

    The backend token does not distinguish a caller: the UI, the harness and the
    agent bridge all send the same one, and it is printed at startup. This
    requires the separate key Electron gives only the renderer, and refuses
    outright when there is no such key to check - fail closed, because an
    approval nobody can attribute is worse than an approval that did not happen.
    """
    refusal = ui_channel.window_refusal(request.headers)
    if refusal is None:
        return None
    code, status = refusal
    if code == 'automation_caller':
        return jsonify({'success': False, 'code': code,
                        'error': 'A build change is approved by a person in the Nucleus '
                                 'window, not by an agent session.'}), status
    if code == 'ui_approval_channel_unavailable':
        return jsonify({
            'success': False, 'code': code,
            'error': ('This installation has no trusted approval channel configured, so a '
                      'build change cannot be approved here. Nothing was authorized.'),
            'detail': _CHANNEL_NOTE}), status
    return jsonify({'success': False, 'code': code,
                    'error': 'This request did not come from the Nucleus window.'}), status


def _refuse_foreign_origin():
    """Refuse an approval that did not come from the app's own page.

    Enforced server-side rather than assumed: a same-origin policy the browser
    applies is not one this endpoint applied.
    """
    site = (request.headers.get('Sec-Fetch-Site') or '').lower()
    if site and site not in ('same-origin', 'none'):
        return jsonify({'success': False, 'code': 'foreign_origin',
                        'error': f'An approval cannot come from {site} context.'}), 403
    origin = (request.headers.get('Origin') or '').strip()
    if origin:
        allowed = {f'http://{request.host}', f'https://{request.host}',
                   'http://localhost', 'http://127.0.0.1'}
        if not any(origin == entry or origin.startswith(entry + ':') for entry in allowed):
            return jsonify({'success': False, 'code': 'foreign_origin',
                            'error': f'An approval cannot come from {origin}.'}), 403
    return None


def _local_user():
    try:
        return f'local user ({getpass.getuser()})'
    except Exception:                                          # noqa: BLE001
        return 'local user'


@menus_bp.route('/api/mex/builds/changes/<prepared_change_id>', methods=['GET'])
def get_build_change(prepared_change_id):
    """What the approval card has to show before anyone can agree to it."""
    from nucleus_api import builds
    refusal = _refuse_non_ui_caller()
    if refusal is not None:
        # The card carries the single-use challenge, so handing it to a caller
        # that cannot approve would hand over the approval.
        return refusal
    try:
        card = builds.authorization_request(prepared_change_id)
        manifest = builds.prepared_change(prepared_change_id)
        digest = build_authorization.subject_digest(manifest)
        card['subjectDigest'] = digest
        # Minted HERE, for the card being displayed, and spent by the approval.
        # Knowing the digest proves the proposal; it does not prove that anyone
        # was shown it, and a replayed digest used to mint a second approval.
        challenge = build_authorization.mint_challenge(prepared_change_id, digest)
        card.update(challenge)
        card['approvalChannel'] = _CHANNEL_NOTE
        return jsonify({'success': True, 'change': card})
    except build_authorization.AuthorizationError as exc:
        return jsonify({'success': False, 'error': str(exc), 'code': exc.code}), 409
    except ValueError as exc:
        code = getattr(exc, 'code', 'invalid_request')
        return jsonify({'success': False, 'error': str(exc), 'code': code}), 400


@menus_bp.route('/api/mex/builds/changes/<prepared_change_id>/approve', methods=['POST'])
def approve_build_change(prepared_change_id):
    """Record the user's decision about one sealed build change.

    Refuses unless the request confirms explicitly, echoes the subject digest
    the card displayed, AND spends the single-use challenge that card carried,
    from a same-origin request. Task identity comes from the proposal, never
    from the request.
    """
    from core import gates
    from nucleus_api import builds
    if not gates.enabled('build_commit'):
        # No authorization is minted while the gate is closed. A stored
        # approval would outlive the switch and be spendable the moment it
        # opened, against a proposal nobody re-validated.
        return jsonify({'success': False, 'code': 'build_commit_disabled',
                        'error': 'Writing a change into a build is switched off in this '
                                 'installation, so there is nothing to approve. The '
                                 'proposal can still be inspected.'}), 409
    body = request.get_json(silent=True) or {}
    if body.get('confirmed') is not True:
        return jsonify({'success': False, 'code': 'not_confirmed',
                        'error': 'An approval has to be an explicit confirmation.'}), 400
    shown = (body.get('subjectDigest') or '').strip()
    if not shown:
        return jsonify({'success': False, 'code': 'no_subject',
                        'error': 'Send back the subjectDigest the card displayed, so this '
                                 'approves the proposal the user actually saw.'}), 400
    refusal = _refuse_non_ui_caller() or _refuse_foreign_origin()
    if refusal is not None:
        return refusal
    try:
        manifest = builds.prepared_change(prepared_change_id)
        current = build_authorization.subject_digest(manifest)
        if current != shown:
            return jsonify({'success': False, 'code': 'stale_card',
                            'error': 'This change is not the one that was displayed any '
                                     'more. Reload it and ask again.'}), 409
        build_authorization.consume_challenge(
            prepared_change_id, (body.get('challenge') or '').strip(), current)
        # Task identity comes from the PROPOSAL, not the request. A caller that
        # could name the task could approve a change on behalf of a request the
        # user never made.
        authorization = build_authorization.grant(
            manifest,
            granted_by=_local_user(),
            task_id=manifest.get('task_id') or '',
            task_revision=int(manifest.get('task_revision') or 1),
            accepted_unknown=body.get('acceptedUnknown') or [],
            consent_reference=(body.get('consentReference') or 'approval card click'))
    except build_authorization.AuthorizationError as exc:
        return jsonify({'success': False, 'error': str(exc), 'code': exc.code}), 409
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc),
                        'code': getattr(exc, 'code', 'invalid_request')}), 400
    logger.info('Build change %s authorized as %s', prepared_change_id,
                authorization['authorization_id'])
    return jsonify({'success': True,
                    'authorizationId': authorization['authorization_id'],
                    'grantedBy': authorization['granted_by'],
                    'acceptedUnknown': authorization['accepted_unknown']})


@menus_bp.route('/api/mex/menus/compatibility', methods=['GET'])
def menu_compatibility_manifest():
    """The versioned menu-compatibility manifest this install ships."""
    from nucleus_api import menus
    manifest = menus.compatibility_manifest()
    return jsonify({'success': True,
                    'manifestVersion': manifest.get('manifest_version', 0),
                    'policy': manifest.get('policy', {}),
                    'packages': [{k: package.get(k) for k in
                                  ('package_id', 'name', 'menu_type', 'source', 'targets',
                                   'required_codes')}
                                 for package in manifest.get('packages', [])]})
