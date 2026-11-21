"""The steps that change a build or the game copy: the approved install, the export, MexCLI's
remove, the build's mutation session, publishing the built disc and putting a kept copy back."""

from pathlib import Path

from core import config, playable_iso, state

from . import projects

from .deliver_policy import KEPT_BACKUPS, DeliveryError
from .deliver_receipts import _write_receipt


# --------------------------------------------------------------------------
# the seams: install, export, remove, promote
# --------------------------------------------------------------------------

def _default_install(install_args, sealed_plan):
    """Apply the APPROVED install plan, not a freshly computed one.

    `projects.apply_install` re-derives the plan and refuses if it no longer
    matches, which is its revalidation; handing it the sealed plan is what makes
    that check mean "the thing the user approved" rather than "whatever is true
    now".
    """
    return projects.apply_install(install_args, sealed_plan)


def _default_export(project, options=None, session=None):
    """Run the build the UI's Build button runs, inline, against THIS build.

    `projects.install.export_job.run_export_job` is the function behind
    `POST /api/mex/export/start`; `background=False` runs it on this thread so
    the caller knows whether a playable image exists before it says anything.
    The delivery's already-open build session is handed through rather than
    opening a second one on top of it. The outcome is the export job's record.
    """
    from projects.install.export_job import ExportRequestError, export_job, run_export_job
    from mexcli.project import MexManager
    project_path = Path(project['path'])
    manager = MexManager(str(config.MEXCLI_PATH), str(project_path))
    try:
        started = run_export_job(dict(options or {}), background=False,
                                 project_path=project_path, mex_manager=manager,
                                 build_guard=session)
    except ExportRequestError as exc:
        return {'state': 'failed', 'error': str(exc), 'artifactId': None}
    record = export_job(started['artifactId']) or {}
    result = record.get('result') or {}
    done = record.get('status') == 'done'
    return {'state': 'complete' if done else 'failed',
            'error': None if done else (record.get('error') or 'The export did not finish.'),
            'artifactId': started['artifactId'], 'path': result.get('path'),
            'warnings': result.get('warnings') or [],
            'filename': result.get('filename') or started.get('filename')}


def _default_remove(project, manifest, session=None):
    """MexCLI's own remove-costumes, the reverse of the import the install ran."""
    from mexcli.project import MexManager, MexManagerError
    with state.mexcli_lock:
        manager = MexManager(str(config.MEXCLI_PATH), str(project['path']))
        try:
            return manager.remove_costumes(manifest)
        except MexManagerError as exc:
            raise DeliveryError(f'The costume could not be removed from the build: {exc}') from exc
        finally:
            state.reload_mex_manager()


def _build_session(project):
    """Open the build's ONE mutation session for the whole delivery.

    A delivery installs and then exports, and both write the same build. The
    cross-process lock underneath is a file lock taken on a fresh handle, so
    taking it twice would deadlock against itself -- which is why the session is
    opened once here and handed to the exporter rather than re-entered there.
    Entering it also finishes or undoes whatever a crash left half-applied.

    Returns `(session, closer)`: the SESSION is what the exporter validates
    against (`session.directory`), and the closer is the context manager that
    owns it. There is no silent fallback -- if this cannot be entered, the
    delivery stops, because a build written without the lock is the split-state
    failure the lock exists to prevent.
    """
    from core import build_access
    manager = build_access.build_session(Path(project['path']).parent, timeout=600.0)
    try:
        session = manager.__enter__()
    except Exception as exc:  # noqa: BLE001 - BuildBusyError and friends
        raise DeliveryError(str(exc)) from exc
    return session, manager


def _promote_artifact(artifact_path, output_path, *, receipt, project, slots,
                      expect_digest):
    """Publish the built disc image to the copy the user plays.

    Every rule about what may be written lives in `core.playable_iso.publish`:
    the destination is refused unless it is ours, the staged bytes are hashed
    against the build, the destination is re-checked immediately before the
    replace, the old copy is hard-linked aside first, and the marker refuses to
    land on a file that is not a marker of ours.

    `expect_digest` is the digest the build was VERIFIED at. Publication of any
    other bytes is refused, which is what keeps verification authoritative
    through a retry.

    Returns `(saved, backup)`.
    """
    def journal(backup):
        # Journalled BEFORE the destination is replaced: a crash in the middle
        # must still leave a receipt that says where the old copy went.
        before_digest = ((receipt.get('before') or {}).get('output') or {}).get('digest')
        if before_digest and backup.get('digest') == before_digest and not receipt.get('backup'):
            receipt['backup'] = backup
        receipt.setdefault('backups_seen', []).append(backup)
        _write_receipt(receipt)

    try:
        result = playable_iso.publish(
            artifact_path, output_path,
            marker={'receipt_id': receipt['receipt_id'], 'project_id': project['id'],
                    'project_name': project['name'],
                    'costumes': [slot['filename'] for slot in slots]},
            expect_digest=expect_digest, keep_backups=KEPT_BACKUPS,
            backup_label=receipt['receipt_id'][-8:], on_backup=journal)
    except playable_iso.ProtectedPath as exc:
        raise DeliveryError(str(exc)) from exc
    return result['output'], result['backup']


def _restore_playable_copy(backup, output_path, *, receipt, project):
    """Put a preserved playable copy back, through the same publisher.

    The backup is only trusted when its bytes still hash to what was recorded
    when it was set aside: a file somebody replaced under that name is not the
    game the user was playing.
    """
    if not backup or not backup.get('path'):
        return None
    source = Path(backup['path'])
    if not source.is_file():
        return None
    if backup.get('digest') and playable_iso.digest_file(source) != backup['digest']:
        return None
    try:
        result = playable_iso.restore(
            source, output_path,
            marker={'receipt_id': receipt['receipt_id'], 'project_id': project['id'],
                    'project_name': project['name']},
            expect_digest=backup.get('digest'))
    except playable_iso.ProtectedPath as exc:
        raise DeliveryError(str(exc)) from exc
    return result['output']
