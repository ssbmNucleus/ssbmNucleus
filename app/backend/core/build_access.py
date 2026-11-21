"""The one door every writer to a managed build goes through.

Before this module the app had several independent writers on one project -- the
CSS background installer, the door installer, the icon installer, ``sync-codes``,
the ISO export -- and each protected itself differently or not at all. A gate
only one of them honours is not a gate, so they all come through here now:

    with build_access.build_session(project_dir) as session:
        session.apply(writes=[...], code_ini=..., label='menu + codes')

or, for the MexCLI commands that do their own writing:

    with build_access.build_session(project_dir):
        subprocess.run([mexcli, 'set-css-icon', ...])

A session:

1. takes the build's exclusive mutation lock -- the in-process MexCLI RLock and
   an exclusive cross-process lock on the build directory;
2. **recovers first**: an interrupted change is rolled back, or, if it was
   already verified, its receipt is written out - before any new reader or
   writer sees the build;
3. journals related mutations together, so a menu file and the code list it
   needs are one transaction rather than two hopeful copies.

Opening a project also comes through :func:`recover_on_open`, so a build that
died mid-change is repaired when the user opens it rather than at the next
write.
"""
import logging
import secrets
import threading
from contextlib import contextmanager
from pathlib import Path

from . import build_transaction as bt
from .build_transaction import BuildBusyError, TransactionError   # noqa: F401 (re-export)

logger = logging.getLogger(__name__)


class BuildQuarantined(RuntimeError):
    """This build's last operation cannot be accounted for.

    An unreadable journal, a backup that does not hash to what it claims, a
    restore that did not complete, or an interrupted whole-workspace save. The
    build is not repaired silently and not reported as recovered: every reader
    and writer refuses it until a person looks, because the alternative is
    handing out a build whose contents nobody can state.
    """

    def __init__(self, directory, problems):
        self.directory = Path(directory)
        self.problems = list(problems)
        detail = '; '.join(str(p.get('problem')) for p in self.problems)
        super().__init__(
            f'{self.directory.name} is quarantined: {detail} '
            f'Nothing will read or write it until this is resolved.')


class BuildSession:
    """A held lock on one build, already recovered. Created by :func:`build_session`.

    A session knows whether it is still open and which thread holds it. A guard
    handed to another function - the export takes one - is checked against both:
    a closed session skips no lock, and a session from another thread cannot be
    reused, because the process lock underneath is re-entrant per thread and the
    file lock is not re-entrant at all.
    """

    def __init__(self, directory, recovery):
        self.directory = Path(directory)
        self.recovery = recovery
        self.token = 'session_' + secrets.token_hex(6)
        self.owner_thread = threading.get_ident()
        self.open = True

    def require_usable_for(self, directory, *, what='This operation'):
        """Raise unless this session really covers that build, here and now."""
        if not self.open:
            raise TransactionError(
                'session_closed',
                f'{what} was handed a build session that is already closed, so nothing '
                'would be holding the build while it ran.')
        if self.owner_thread != threading.get_ident():
            raise TransactionError(
                'session_foreign_thread',
                f'{what} was handed a build session held by another thread. The process '
                'lock under it is re-entrant per thread, so this one would not actually '
                'hold anything.')
        if self.directory.resolve() != Path(directory).resolve():
            raise TransactionError(
                'session_wrong_build',
                f'{what} was handed a session for {self.directory}, not {directory}.')
        return self

    @property
    def revision(self):
        """The build's current content revision."""
        return bt.build_revision(self.directory)

    def digests(self):
        """Current SHA-256 of every managed and identity file."""
        return bt.managed_digests(self.directory)

    def apply(self, writes=(), *, label, code_ini=None, verify=None,
              identities=None, finalize_builder=None):
        """Run one journaled transaction inside this session's lock."""
        return bt.apply_change(self.directory, list(writes), label=label,
                               identities=identities, code_ini=code_ini,
                               verify=verify, finalize_builder=finalize_builder)

    def replace_file(self, relpath, source, *, label, verify=None):
        """Journal a single managed file replacement (the door/menu installers)."""
        return self.apply([{'relpath': relpath, 'source': str(source),
                            'sha256': bt.sha256_file(source)}],
                          label=label, verify=verify)

    @contextmanager
    def external_save(self, label):
        """Bracket a MexCLI command that opens and SAVES the whole workspace.

        ``set-css-icon``, ``sync-codes``, a costume reorder and the custom
        character commands all rewrite many files in one pass. That cannot be
        journaled file by file and cannot be undone file by file - but it can be
        BRACKETED, so a death in the middle is detected instead of silently
        producing a half-saved build. A journal left open in this state
        quarantines the build; the next open says so rather than handing it out.
        """
        record = bt.begin_external_save(self.directory, label)
        try:
            yield record
        except BaseException:
            bt.end_external_save(self.directory, record, failed=True)
            raise
        bt.end_external_save(self.directory, record)


@contextmanager
def build_session(directory, *, timeout=30.0):
    """Lock a build, recover it, and hand it over - or refuse it.

    Args:
        directory: the build (MEX project) directory.
        timeout: seconds to wait for the cross-process lock.

    Yields:
        BuildSession: holds the lock for the duration of the ``with`` block.

    Raises:
        BuildBusyError: another Nucleus process or operation holds the build.
        BuildQuarantined: recovery could not establish what the build contains.
            Nothing is handed out; the caller reports it.

    Example:
        >>> with build_session(project_dir) as session:
        ...     session.replace_file('files/MnSlChr.usd', staged, label='door art')
    """
    lock = bt.build_lock(directory, timeout=timeout)
    session = None
    try:
        recovery = bt.recover(directory)
        if recovery:
            logger.warning('Build %s had %d interrupted change(s); recovery: %s',
                           Path(directory).name, len(recovery), recovery)
        blocked = bt.quarantined(directory)
        if blocked:
            raise BuildQuarantined(directory, blocked)
        session = BuildSession(directory, recovery)
        yield session
    finally:
        if session is not None:
            session.open = False
        lock.release()


def recover_on_open(directory):
    """Repair a build when it is opened, and SAY what happened.

    The first version swallowed every failure and returned ``[]``, which is the
    same answer as "nothing was wrong". A build that could not be recovered, or
    one whose state nobody can establish, is exactly what the person opening it
    needs to be told about.

    Args:
        directory: the build (MEX project) directory.

    Returns:
        dict: ``{'status': 'clean'|'recovered'|'quarantined'|'busy'|'error',
        'actions': [...], 'problems': [...], 'message': str}``. ``quarantined``
        and ``error`` are refusals: the caller must not present the build as
        ready.

    Example:
        >>> build_access.recover_on_open(project_dir)
        {'status': 'clean', 'actions': [], 'problems': [], 'message': ''}
    """
    try:
        with build_session(directory, timeout=5.0) as session:
            return {'status': 'recovered' if session.recovery else 'clean',
                    'actions': session.recovery, 'problems': [],
                    'message': (f'{len(session.recovery)} interrupted change(s) were '
                                'finished or undone.' if session.recovery else '')}
    except BuildQuarantined as blocked:
        logger.error('Build %s is quarantined: %s', directory, blocked.problems)
        return {'status': 'quarantined', 'actions': [], 'problems': blocked.problems,
                'message': str(blocked)}
    except BuildBusyError as busy:
        logger.warning('Could not recover %s on open: %s', directory, busy)
        return {'status': 'busy', 'actions': [], 'problems': [],
                'message': str(busy)}
    except Exception as exc:                                    # noqa: BLE001
        logger.error('Could not recover %s on open: %s', directory, exc, exc_info=True)
        return {'status': 'error', 'actions': [], 'problems': [{'problem': str(exc)}],
                'message': f'This build could not be checked on open: {exc}'}


@contextmanager
def guard_mexcli(project_path, *, timeout=120.0, label='MexCLI write'):
    """Hold the build lock around a MexCLI command that writes the workspace.

    ``set-css-icon``, ``sync-codes``, the export and the costume commands all
    open and save the whole workspace. Two of those at once corrupts it, and
    ``mexcli_lock`` alone only stops two in THIS process.

    Args:
        project_path: the ``project.mexproj`` path the command is given.
        timeout: seconds to wait for the lock (an export is long).
        label: what to log.

    Yields:
        BuildSession: the held session.

    Example:
        >>> with guard_mexcli(project_path, label='set-css-icon'):
        ...     subprocess.run([mexcli, 'set-css-icon', str(project_path), ...])
    """
    directory = Path(project_path).parent
    logger.debug('%s waiting for the build lock on %s', label, directory)
    with build_session(directory, timeout=timeout) as session:
        yield session
