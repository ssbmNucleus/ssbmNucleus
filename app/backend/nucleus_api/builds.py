"""Change the build you play - as one sealed, authorized, revocable step.

Every other module here writes a workspace copy. This one is the exception, and
the only one: it installs a prepared menu file and the codes it needs INTO a
managed build, through the single build-access service every app writer uses
(:mod:`core.build_access`), journaled so an interrupted change is repaired
before anything reads the build again.

It never takes a destination path. It takes a registered build id and registered
artifact ids; where an artifact lands is decided by its KIND
(:data:`ARTIFACT_KINDS`) at the moment of use, never by a stored field a caller
could edit.

The shape of a change:

    build  = builds.list_builds()[0]                      # an explicit choice
    art    = builds.register_artifact('out/MnSlChr.usd', 'css_menu_file')
    change = builds.prepare_change(build['id'], build['revision'], [art['id']])
    ask    = builds.authorization_request(change['prepared_change_id'])
    #   -> exactly what the user has to be shown and agree to. This library
    #      cannot answer it: `core.build_authorization.grant` is backend code
    #      the approval endpoint calls once the user has clicked.
    got    = builds.commit_change(change['prepared_change_id'], authorization_id)
    got['achieved']['installed']
    # False - the project's inputs changed; the ISO you boot is a separate build.

What this module will not do: decide which build you meant, authorize itself,
treat "it parses" as compatibility, treat an author's screenshot as a preview,
or call a changed project an installed game.
"""
import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

from ._workspace import in_path, library_path, workspace

#: Where a registered artifact of each kind is installed, and whether it is
#: installed at all. A caller picks a kind; the destination follows from it,
#: and is re-derived from this table every time it is used.
ARTIFACT_KINDS = {
    'css_menu_file': {'destination': 'files/MnSlChr.usd', 'menu_type': 'css', 'role': 'install'},
    'sss_menu_file': {'destination': 'files/MnSlMap.usd', 'menu_type': 'sss', 'role': 'install'},
    'reference_screenshot': {'destination': None, 'menu_type': None, 'role': 'reference'},
}

#: The one build format this module can commit to. Anything else is reported,
#: not guessed at.
COMMITTABLE_FORMAT = 'mex_project'


class BuildChangeRejected(ValueError):
    """A change was refused. ``code`` names which rule refused it."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _rejected(exc):
    """Re-raise an authorization error in this module's vocabulary."""
    return BuildChangeRejected(getattr(exc, 'code', 'authorization_error'), str(exc))


def _build_id(directory):
    key = str(Path(directory).resolve()).lower()
    return 'b' + hashlib.sha1(key.encode('utf-8')).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Registered builds
# ---------------------------------------------------------------------------

def _registry_override():
    """Extra build directories, as a JSON list in ``NUCLEUS_API_BUILDS``.

    The app has one projects folder; a test, a second data root or a harness
    has its own. When set it REPLACES the machine's builds, so a harness cannot
    reach the user's real projects by accident.
    """
    return os.environ.get('NUCLEUS_API_BUILDS', '').strip() or '[]'


def _candidate_directories():
    from core import config
    seen, rows = set(), []
    override = json.loads(_registry_override() or '[]')
    if override:
        rows = [Path(path) for path in override]
    else:
        projects = Path(config.PROJECTS_PATH)
        if projects.is_dir():
            for marker in sorted(projects.glob('*/project.mexproj')):
                rows.append(marker.parent)
        storage = Path(config.STORAGE_PATH)
        if storage.is_dir():
            for menu in sorted(storage.glob('*/files/MnSlChr.*')):
                rows.append(menu.parent.parent)
    unique = []
    for row in rows:
        key = str(Path(row).resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(Path(row))
    return unique


def list_builds():
    """List the builds on this machine that a change can name.

    A build is a MEX project (``project.mexproj`` beside ``files/``) - those are
    committable. Extracted build folders under the storage root are listed too,
    marked ``committable=False``, so "which build?" is answered with the real
    set rather than the convenient subset.

    Returns:
        list[dict]: ``{'id', 'name', 'path', 'format', 'committable',
        'revision', 'menu_files', 'codes_path'}``. ``revision`` is a content
        revision of the build's managed AND identity files (its menu, its code
        list, its disc header, its m-ex marker), so anything that changes what
        the build IS also invalidates a pending authorization.

    Example:
        >>> from nucleus_api import builds
        >>> [b['name'] for b in builds.list_builds()][:2]
        ['My_Project', 'test-base']
    """
    from core import build_transaction as bt
    rows = []
    for directory in _candidate_directories():
        committable = bt.is_mex_build(directory)
        menu_files = {}
        for menu_type, stem in (('css', 'MnSlChr'), ('sss', 'MnSlMap')):
            for suffix in ('.usd', '.dat'):
                candidate = directory / 'files' / f'{stem}{suffix}'
                if candidate.is_file():
                    menu_files[menu_type] = str(candidate)
                    break
        rows.append({
            'id': _build_id(directory),
            'name': directory.name,
            'path': str(directory),
            'format': COMMITTABLE_FORMAT if committable else 'extracted_files',
            'committable': committable,
            'revision': bt.build_revision(directory) if committable else None,
            'menu_files': menu_files,
            'codes_path': str(directory / 'files' / 'codes.ini') if committable else None,
        })
    return rows


def _resolve(build_id):
    from core.build_authorization import AuthorizationError, require_id
    try:
        require_id('build', build_id)
    except AuthorizationError as exc:
        raise _rejected(exc) from None
    for row in list_builds():
        if row['id'] == build_id:
            return row
    raise BuildChangeRejected('unknown_build',
                              f'No build with id {build_id!r}. Call builds.list_builds() and '
                              'pass one of its ids; a path is not accepted here.')


def describe(build_id):
    """Everything a change needs to know about one build before proposing one.

    Args:
        build_id: an ``id`` from :func:`list_builds`.

    Returns:
        dict: the :func:`list_builds` row plus ``'target'`` (its game code, disc
        revision, menu variant and the digest of the menu file it currently
        carries), ``'managed_digests'``, ``'codes'`` (its current Gecko list)
        and ``'playable'`` (whether the game you boot reflects any of it).

    Example:
        >>> builds.describe(build_id)['target']['game_code']
        'GALE01'
    """
    from core import build_transaction as bt
    row = _resolve(build_id)
    directory = Path(row['path'])
    return {**row, 'target': target_signature(build_id),
            'managed_digests': bt.managed_digests(directory),
            'codes': _build_codes(directory),
            'playable': playable_status(build_id)}


def target_signature(build_id, menu_type='css'):
    """The game this build IS, read from its own boot header.

    Compatibility is judged against this, never against a build's name.

    Args:
        build_id: an ``id`` from :func:`list_builds`.
        menu_type: which screen's current file to report the digest of.

    Returns:
        dict: ``{'game_code', 'disc_revision', 'menu_variant',
        'current_menu_sha256'}``. Any field the build cannot answer for is
        None, which makes the target dimension ``unknown`` rather than assuming
        NTSC 1.02 - a recorded observation only covers the signature fields it
        recorded.

    Example:
        >>> builds.target_signature(build_id)['disc_revision']
        2
    """
    from core import build_transaction as bt
    row = _resolve(build_id)
    directory = Path(row['path'])
    boot = directory / 'sys' / 'boot.bin'
    game_code, revision = None, None
    if boot.is_file():
        header = boot.read_bytes()[:8]
        if len(header) >= 8:
            try:
                game_code = header[:6].decode('ascii')
            except UnicodeDecodeError:
                game_code = None
            revision = header[7]
    variant = 'mex' if (directory / 'data' / 'mex.json').is_file() else None
    menu = row['menu_files'].get(menu_type)
    return {'game_code': game_code, 'disc_revision': revision, 'menu_variant': variant,
            'current_menu_sha256': bt.sha256_file(menu) if menu else None}


def playable_status(build_id):
    """Whether the game you actually boot reflects this build's current files.

    Changing a project's files is not installing a game. The disc the user
    plays is produced by the app's separate ISO export, and this library does
    not run it, so it never reports one as verified.

    Args:
        build_id: an ``id`` from :func:`list_builds`.

    Returns:
        dict: ``{'status': 'not_verified', 'reason', 'required_operation',
        'artifacts_dir'}``.

    Example:
        >>> builds.playable_status(build_id)['status']
        'not_verified'
    """
    from core import config
    _resolve(build_id)
    return {
        'status': 'not_verified',
        'reason': ('This library changes the project a disc is built FROM. Producing and '
                   'booting that disc is the app\'s ISO export, which is a separate '
                   'operation and was not run, so nothing here has been seen in game.'),
        'required_operation': 'POST /api/mex/export (Export / Build ISO)',
        'artifacts_dir': str(Path(config.OUTPUT_PATH) / 'artifacts'),
    }


def _build_codes(directory):
    from core.gecko import parse_ini
    path = Path(directory) / 'files' / 'codes.ini'
    if not path.is_file():
        return []
    return parse_ini(path.read_text(encoding='utf-8', errors='replace'))


# ---------------------------------------------------------------------------
# Registered artifacts
# ---------------------------------------------------------------------------

def register_artifact(path, kind, name=None):
    """Register a workspace file as an artifact a change may install.

    Registration turns "a file somewhere" into a resource with an id, a hash and
    a KIND. The record is written under the app's trusted store, not the
    workspace: a registration a caller can rewrite is not a record of anything.
    Its destination and role are never read back from the record - they are
    re-derived from :data:`ARTIFACT_KINDS` wherever they are used.

    Args:
        path: workspace path to the file, e.g. the ``MnSlChr.usd`` that
            :func:`nucleus_api.menus.install_background` produced.
        kind: one of :data:`ARTIFACT_KINDS`. ``'reference_screenshot'`` has no
            destination and can never be installed.
        name: a label for receipts. Defaults to the file's name.

    Returns:
        dict: ``{'id', 'kind', 'role', 'path', 'sha256', 'bytes',
        'destination', 'registered_utc'}``. Registering the same bytes at the
        same path twice returns the same id.

    Example:
        >>> builds.register_artifact('out/MnSlChr.usd', 'css_menu_file')['role']
        'install'
    """
    from core.build_authorization import store_path
    from core.build_transaction import assert_contained, sha256_file
    if kind not in ARTIFACT_KINDS:
        raise BuildChangeRejected(
            'unknown_artifact_kind',
            f'{kind!r} is not an artifact kind. Use one of {sorted(ARTIFACT_KINDS)}.')
    source = in_path(path)
    assert_contained(workspace(), source, what='artifact')
    digest = sha256_file(source)
    artifact_id = 'art_' + hashlib.sha256(
        f'{str(source).lower()}|{digest}'.encode('utf-8')).hexdigest()[:16]
    record = {'id': artifact_id, 'kind': kind, 'path': str(source), 'sha256': digest,
              'bytes': source.stat().st_size, 'name': name or source.name,
              'registered_utc': _now(),
              **_kind_facts(kind)}
    from core.build_transaction import write_json_durably
    write_json_durably(store_path('artifacts', artifact_id, 'artifact'), record)
    return record


def _kind_facts(kind):
    """Role, menu type and destination, derived from the kind. Never stored-and-trusted."""
    facts = ARTIFACT_KINDS[kind]
    return {'role': facts['role'], 'menu_type': facts['menu_type'],
            'destination': facts['destination']}


def artifact(artifact_id):
    """The registration record for an artifact id.

    Args:
        artifact_id: an ``id`` from :func:`register_artifact`.

    Returns:
        dict: the record, with ``role``/``menu_type``/``destination``
        recomputed from its kind rather than read from the file.

    Example:
        >>> builds.artifact(art_id)['kind']
        'css_menu_file'
    """
    from core.build_authorization import AuthorizationError, store_path
    try:
        path = store_path('artifacts', artifact_id, 'artifact')
    except AuthorizationError as exc:
        raise _rejected(exc) from None
    if not path.is_file():
        raise BuildChangeRejected('unknown_artifact',
                                  f'No artifact {artifact_id!r} is registered. Call '
                                  'builds.register_artifact() first.')
    record = json.loads(path.read_text(encoding='utf-8'))
    kind = record.get('kind')
    if kind not in ARTIFACT_KINDS:
        raise BuildChangeRejected('unknown_artifact_kind',
                                  f'{artifact_id} names kind {kind!r}, which does not exist.')
    return {**record, **_kind_facts(kind)}


# ---------------------------------------------------------------------------
# Sealed proposal
# ---------------------------------------------------------------------------

def _receipt_destination(build_dir, identifier):
    """Where a receipt lives - derived from a validated id, inside its build."""
    from core.build_authorization import require_id
    from core.build_transaction import assert_contained, journal_root
    require_id('receipt', identifier)
    bucket = journal_root(Path(build_dir)) / 'receipts'
    bucket.mkdir(parents=True, exist_ok=True)
    return assert_contained(bucket, f'{identifier}.json', what='receipt path')


def _register_finalizers():
    from core.build_transaction import register_finalizer
    register_finalizer('receipt', _receipt_destination)


_register_finalizers()


def _store(directory, bucket):
    from core.build_transaction import journal_root
    path = journal_root(directory) / bucket
    path.mkdir(parents=True, exist_ok=True)
    return path


#: This module's build formats, mapped onto the variants
#: :mod:`assistant.capabilities` declares. A format with no entry here is not
#: guessed at - the gap is refused rather than filed against a nearby variant.
BUILD_FORMAT_VARIANTS = {
    'extracted_files': 'extracted_iso',
    'iso': 'iso',
    'gcm': 'gcm',
    'nkit': 'nkit',
}


def record_build_commit_gap(row, task_id='', task_revision=1, chat_id='',
                            workflow='install_menu'):
    """Record the unsupported-build gap - for a REQUESTED INSTALLATION only.

    :func:`prepare_change` meeting an uncommittable build is a validation
    result, not a request to install one, so it returns the typed error and
    records nothing. This is called from the install path, where the capability
    really was required for the user's outcome. The build FORMAT is the variant,
    because it is the missing implementation; an unknown build or a stale
    revision stays an ordinary validation failure and never reaches here.

    Args:
        row: a :func:`list_builds` entry for the build that cannot be committed.
        task_id: the task the install was requested in.
        task_revision: that task's revision.
        chat_id: the conversation, which is the unit demand is counted in.
        workflow: the workflow that needed the install.

    Returns:
        The ``wishes.WishRecord``, or None when the build's format has no
        declared variant (:data:`BUILD_FORMAT_VARIANTS`) or the classifier does
        not call it a gap.

    Example:
        >>> builds.record_build_commit_gap(row, task_id='task_1').persisted
        True
    """
    from randall.assistant import capabilities
    from randall.reports import wishes as wishlib
    fmt = (row.get('format') or '').strip()
    variant = BUILD_FORMAT_VARIANTS.get(fmt)
    if variant is None or variant not in capabilities.BUILD_COMMIT.variants:
        # A format nobody declared is not rounded to the nearest one: that
        # would file a gap this build never demonstrated. Refuse instead.
        return None
    verdict = wishlib.classify_blocker(
        wishlib.Observation(evidence='operation_unavailable',
                            operation='builds.commit_change', variant=variant),
        wishlib.Requirement(operation='builds.commit_change', required_for_outcome=True,
                            workflow=workflow))
    if not verdict.creates_wish:
        return None
    return wishlib.record(verdict, task_id=task_id, task_revision=task_revision,
                          conversation_id=chat_id or task_id, workflow=workflow)


def _commit_enabled():
    """Whether this installation lets the app write a build at all."""
    from core import gates
    return gates.enabled('build_commit')


def _unsupported(row, reason):
    return {
        'status': 'blocked',
        'build_id': row['id'],
        'error': {'code': 'unsupported_build_commit', 'message': reason,
                  'format': row['format']},
        'wish': {
            'kind': 'capability_gap',
            'capability': 'commit_change_to_' + row['format'],
            'requested_outcome': 'Install a menu and its codes into this build',
            'blocked_operation': 'builds.commit_change',
            'available_alternative': 'Prepare the menu file in the workspace and install it '
                                     'into a MEX project instead',
            'note': ('A typed candidate, not a record. prepare_change meeting an '
                     'uncommittable build is a validation result, not a request to install '
                     'one; record_build_commit_gap() files it from the install path, where '
                     'the capability really was required.'),
        },
        'preview': {'status': 'unavailable', 'previewed': False},
        'achieved': {'prepared': False, 'build_inputs_updated': False, 'exported': False,
                     'installed': False, 'previewed': False},
    }


def prepare_change(build_id, expected_revision, artifacts, code_changes=None,
                   preview_requested=False, task_id='', task_revision=1,
                   chat_id=''):
    """Seal a proposed change to a build: what would be written, and what is known.

    Nothing is written to the build. Everything the proposal depends on is read
    and sealed under the build's own lock, in one pass, so the facts it states
    were all true at one instant: the revision, the target signature, the
    current code list, the artifacts' bytes (copied into the journal), the
    compiler that will build the code list, and the compatibility verdict -
    which is computed against the SEALED copy, not the workspace file a later
    call could replace.

    Args:
        build_id: an ``id`` from :func:`list_builds`.
        expected_revision: the build's ``revision`` as the caller last saw it.
        artifacts: artifact ids from :func:`register_artifact`. Artifacts whose
            kind has no destination (a reference screenshot) are recorded and
            never installed.
        code_changes: optional ``{'add': [code dicts], 'enable_disabled': bool,
            'reason': str}``. The package's own required codes are added
            automatically; ``add`` is for codes on top of those, and they are
            judged with the rest. ``enable_disabled`` makes turning on a
            required code the build carries switched OFF an explicit part of
            the proposal instead of a side effect.
        preview_requested: the user asked to see the result. No renderer
            exists, so this makes the outcome ``partial`` rather than letting a
            missing preview pass unnoticed.
        task_id: the task this proposal belongs to, carried into the
            authorization and the wish.
        task_revision: that task's revision.
        chat_id: the conversation, which is the unit capability demand is
            counted in.

    Returns:
        dict: the sealed manifest -
        ``{'status', 'prepared_change_id', 'build_id', 'build_path',
        'before_revision', 'target', 'compiler', 'writes', 'references',
        'codes', 'codes_ini_sha256', 'codes_required', 'compatibility',
        'unknown_dimensions', 'preview', 'preview_status', 'rollback',
        'subject_digest', 'limitations'}``. ``status`` is ``'prepared'`` or
        ``'blocked'`` (with an ``error``, and a typed ``wish`` for a build
        format that cannot be committed to).

    Raises:
        BuildChangeRejected: unknown build or artifact, a stale
            ``expected_revision``, or an artifact whose bytes moved.

    Example:
        >>> change = builds.prepare_change(build_id, revision, [artifact_id])
        >>> change['status'], change['preview']['status']
        ('prepared', 'unavailable')
    """
    from core import build_access, build_transaction as bt
    from core.build_authorization import subject_digest
    from core.gecko import serialize_ini
    from . import codes as codes_module
    from . import menus as menus_module

    row = _resolve(build_id)
    directory = Path(row['path'])
    if not row['committable']:
        return _unsupported(row, f'{row["name"]} is an extracted {row["format"]} folder, not a '
                                 'MEX project. This library can only commit a change to a '
                                 'MEX project, which is the format the app builds an ISO from.')

    if not _commit_enabled():
        # With the gate closed this does not open a session, does not recover,
        # and does not seal anything into the build: "no build bytes change"
        # has to mean no bytes, including the journal's.
        return {
            'status': 'blocked',
            'build_id': build_id,
            'build_name': row['name'],
            'commit_enabled': False,
            'error': {
                'code': 'build_commit_disabled',
                'message': ('Writing a change into a build is switched off in this '
                            'installation (NUCLEUS_BUILD_COMMIT=0). Nothing was read from '
                            'or written to the build. There is no queue: when it is '
                            'enabled, prepare the change again so it is validated and '
                            'approved against the build as it is then.'),
            },
            'preview': {'status': 'unavailable', 'previewed': False},
            'achieved': {'prepared': False, 'build_inputs_updated': False,
                         'exported': False, 'installed': False, 'previewed': False},
        }

    records = [artifact(identifier) for identifier in (artifacts or [])]
    if not records:
        raise BuildChangeRejected('no_artifacts',
                                  'A change needs at least one registered artifact.')

    prepared_id = f'pc_{build_id}_{secrets.token_hex(6)}'
    enable_disabled = bool((code_changes or {}).get('enable_disabled'))

    # One pass under the lock: every fact below is true at the same instant.
    with build_access.build_session(directory) as session:
        current = session.revision
        if expected_revision != current:
            raise BuildChangeRejected(
                'stale_revision',
                f'{row["name"]} is at {current}, not {expected_revision}. Something changed '
                'it since you last looked; call builds.describe() again and prepare from '
                'that.')
        target = target_signature(build_id)
        existing = _build_codes(directory)
        compiler = bt.compiler_identity()
        sealed_dir = _store(directory, 'prepared') / prepared_id
        sealed_dir.mkdir(parents=True, exist_ok=True)

        writes, references, limitations = [], [], []
        compatibility, required_codes = {}, []
        extra_codes = list((code_changes or {}).get('add') or [])
        for record in records:
            source = Path(record['path'])
            if bt.sha256_file(source) != record['sha256']:
                raise BuildChangeRejected(
                    'artifact_hash_mismatch',
                    f'{record["name"]} no longer has the bytes it was registered with. '
                    'Register it again if the change is meant to carry the new file.')
            if record['role'] != 'install':
                references.append({**record, 'note': 'Recorded as evidence. A reference image '
                                                     'is never installed and never counts as '
                                                     'a preview of the produced menu.'})
                continue
            destination = ARTIFACT_KINDS[record['kind']]['destination']
            sealed = sealed_dir / Path(destination).name
            sealed.write_bytes(source.read_bytes())
            if bt.sha256_file(sealed) != record['sha256']:
                raise BuildChangeRejected('artifact_hash_mismatch',
                                          f'The sealed copy of {record["name"]} does not match '
                                          'the file it was taken from.')
            verdict = menus_module.check_compatibility(
                library_path(sealed, why='sealed copy in this build journal'),
                ARTIFACT_KINDS[record['kind']]['menu_type'], target=target,
                existing_codes=existing, extra_codes=extra_codes,
                enable_disabled=enable_disabled)
            compatibility[record['id']] = verdict
            required_codes.extend(verdict.get('required_codes') or [])
            writes.append({
                'artifact_id': record['id'], 'kind': record['kind'], 'name': record['name'],
                'destination': destination, 'sealed_path': str(sealed),
                'original_sha256': bt.sha256_file(directory / destination),
                'replacement_sha256': record['sha256'], 'bytes': record['bytes'],
            })
            limitations.extend(verdict.get('limitations') or [])

        if not writes:
            raise BuildChangeRejected('no_installable_artifacts',
                                      'Every artifact given is a reference; there is nothing '
                                      'to install.')

        merge = codes_module.merge(existing, required_codes, enable_disabled=enable_disabled)
        codes_ini = serialize_ini(merge['merged']) if required_codes else None
        rollback_set = {'files': {w['destination']: w['original_sha256'] for w in writes},
                        'codes_ini_sha256': bt.sha256_file(directory / 'files' / 'codes.ini'),
                        'codes_gct_sha256': bt.sha256_file(directory / 'files' / 'codes.gct')}

    # `required=preview_requested`: every prepared build calls this, and
    # recording each one would manufacture demand out of a routine status line.
    # The gap is recorded at the FIRST unmet preview requirement - here, when
    # the user asked to see the result - and never again at commit.
    preview = menus_module.preview(writes[0]['destination'], task_id=task_id,
                                   task_revision=task_revision,
                                   required=bool(preview_requested), chat_id=chat_id)
    order = {'fail': 0, 'unknown': 1, 'pass': 2}
    worst = 'pass'
    for verdict in compatibility.values():
        if order[verdict['status']] < order[worst]:
            worst = verdict['status']
    unknown_dimensions = sorted({
        f'{artifact_id}:{dimension}'
        for artifact_id, verdict in compatibility.items()
        for dimension in ('structure', 'target', 'codes')
        if verdict[dimension]['status'] == 'unknown'}
        # A code the caller added that the analyzer cannot model is an unknown
        # of this proposal too, even when the package's own dimension passed.
        | {f'code:{row["identity"]}' for row in merge['unknown']})

    manifest = {
        'status': 'prepared',
        'prepared_change_id': prepared_id,
        'build_id': build_id,
        'build_path': str(directory),
        'build_name': row['name'],
        'before_revision': current,
        'target': target,
        'compiler': compiler,
        'task_id': task_id,
        'task_revision': int(task_revision),
        'writes': writes,
        'references': references,
        'codes': {
            'added': merge['added'], 'preserved': merge['preserved'],
            'duplicates': merge['duplicates'], 'conflicts': merge['conflicts'],
            'unknown': merge['unknown'], 'enable_required': merge['enable_required'],
            'enabled': merge['enabled'], 'interactions': merge['interactions'],
            'ini': codes_ini,
            'before': {'count': len(existing),
                       'sha256': rollback_set['codes_ini_sha256']},
        },
        'codes_required': [{'identity': codes_module.identity(c),
                            'content_hash': codes_module.content_hash(c.get('source', '')),
                            'origin': c.get('origin'), 'reason': c.get('reason'),
                            'source': c.get('source')} for c in required_codes],
        # The digest of the EXACT text that will be executed. The authorization
        # binds to it, so editing the sealed proposal's code list after approval
        # cannot pass verification.
        'codes_ini_sha256': (hashlib.sha256(codes_ini.encode('utf-8')).hexdigest()
                             if codes_ini else None),
        'compatibility': compatibility,
        'compatibility_status': worst,
        'unknown_dimensions': unknown_dimensions,
        'preview': preview,
        'preview_status': preview['status'],
        'preview_requested': bool(preview_requested),
        'rollback': rollback_set,
        'limitations': sorted(set(limitations)),
        'commit_enabled': True,
        'prepared_utc': _now(),
    }
    if worst == 'fail' or not merge['ok']:
        reasons = [v[d]['evidence'] for v in compatibility.values()
                   for d in ('structure', 'target', 'codes') if v[d]['status'] == 'fail']
        manifest['status'] = 'blocked'
        manifest['error'] = {
            'code': 'incompatible' if worst == 'fail' else 'code_conflict',
            'message': ('This menu cannot be installed into this build. ' + '; '.join(reasons))
                       if reasons else
                       f'Code conflicts: {merge["conflicts"] or merge["enable_required"]!r}',
        }
    manifest['subject_digest'] = subject_digest(manifest)
    from core.build_transaction import write_json_durably
    write_json_durably(_store(directory, 'prepared') / f'{prepared_id}.json', manifest)
    return manifest


def prepared_change(prepared_change_id):
    """Read back a sealed proposal by its id.

    Args:
        prepared_change_id: from :func:`prepare_change`.

    Returns:
        dict: the sealed manifest, exactly as it was written.

    Example:
        >>> builds.prepared_change(change_id)['status']
        'prepared'
    """
    from core.build_authorization import AuthorizationError, require_id
    from core.build_transaction import assert_contained
    try:
        require_id('prepared_change', prepared_change_id)
    except AuthorizationError as exc:
        raise _rejected(exc) from None
    build_id = prepared_change_id.split('_')[1]
    row = _resolve(build_id)
    bucket = _store(Path(row['path']), 'prepared')
    path = assert_contained(bucket, f'{prepared_change_id}.json', what='proposal path')
    if not path.is_file():
        raise BuildChangeRejected('unknown_prepared_change',
                                  f'No prepared change {prepared_change_id!r} in '
                                  f'{row["name"]}.')
    return json.loads(path.read_text(encoding='utf-8'))


def authorization_request(prepared_change_id):
    """Exactly what the user has to be shown, and agree to, before a commit.

    This library cannot answer it. Granting an authorization is backend code
    (:func:`core.build_authorization.grant`, reached from the approval endpoint
    ``POST /api/mex/builds/changes/<id>/approve``), so a model can ask for a
    change to be approved and cannot approve one.

    Args:
        prepared_change_id: from :func:`prepare_change`.

    Returns:
        dict: ``{'prepared_change_id', 'build', 'destinations', 'codes',
        'compatibility', 'unknown_dimensions', 'limitations', 'preview',
        'granted_by', 'endpoint'}`` - the card's contents, and where a decision
        about it comes from.

    Example:
        >>> builds.authorization_request(change_id)['granted_by']
        'the user, through the approval endpoint'
    """
    manifest = prepared_change(prepared_change_id)
    return {
        'prepared_change_id': prepared_change_id,
        'status': manifest['status'],
        'build': {'id': manifest['build_id'], 'name': manifest['build_name'],
                  'path': manifest['build_path'], 'revision': manifest['before_revision'],
                  'target': manifest['target']},
        'destinations': [{'destination': w['destination'], 'name': w['name'],
                          'replaces_sha256': w['original_sha256'],
                          'with_sha256': w['replacement_sha256'], 'bytes': w['bytes']}
                         for w in manifest['writes']],
        'codes': {'added': [c['identity'] for c in manifest['codes']['added']],
                  'preserved': [c['identity'] for c in manifest['codes']['preserved']],
                  'enabled': manifest['codes']['enabled'],
                  'required': manifest['codes_required']},
        'compatibility': {a: {d: v[d]['status'] for d in ('structure', 'target', 'codes')}
                          for a, v in manifest['compatibility'].items()},
        'unknown_dimensions': manifest['unknown_dimensions'],
        'limitations': manifest['limitations'],
        'preview': manifest['preview'],
        'playable': ('This changes the project the disc is built from. The disc you boot is '
                     'produced by a separate Export and is not part of this decision.'),
        'granted_by': 'the user, through the approval endpoint',
        'endpoint': f'POST /api/mex/builds/changes/{prepared_change_id}/approve',
    }


# ---------------------------------------------------------------------------
# Commit
# ---------------------------------------------------------------------------

def commit_change(prepared_change_id, authorization_id):
    """Apply a sealed, authorized change to the build - the only write here.

    Takes the build's exclusive mutation lock through the one build-access
    service, recovers any interrupted change first, then revalidates everything
    from scratch: the authorization's binding is RECOMPUTED from the proposal on
    disk (so editing the proposal after approval invalidates it), the build is
    still at the revision that was authorized, the target and the code compiler
    are still the ones the proposal named, and every file - sealed copy,
    workspace original, and the bytes currently in the build - still hashes to
    what was agreed. Only then does it write, as one journaled transaction.

    The receipt and the authorization's consumption are recorded in the journal
    BEFORE they are written out, and written under the same lock, so a crash
    cannot lose the outcome or let the authorization be spent twice. Calling it
    again with a spent authorization returns the receipt that already exists.

    Args:
        prepared_change_id: from :func:`prepare_change`.
        authorization_id: granted by the app's approval endpoint.

    Returns:
        dict: the receipt - ``{'receipt_id', 'outcome', 'stage', 'achieved',
        'build_id', 'before_revision', 'after_revision', 'installed', 'codes',
        'verification', 'playable', 'preview', 'journal_id', 'next'}``.
        ``achieved['build_inputs_updated']`` is True and
        ``achieved['installed']`` is False: the project changed, the disc you
        boot has not been rebuilt. ``outcome`` is ``'partial'``.

        When ``NUCLEUS_BUILD_COMMIT=0`` this installation does not let the app
        write builds at all: the call returns
        ``outcome='build_commit_disabled'`` before taking a lock or writing a
        byte, rather than applying part of the change.

    Raises:
        BuildChangeRejected: stale or mismatched authorization, changed bytes,
            unaccepted unknown compatibility, or a verification failure. In
            every case the build is left exactly as it was.

    Example:
        >>> receipt = builds.commit_change(change_id, auth_id)
        >>> receipt['achieved']['installed'], receipt['preview']['status']
        (False, 'unavailable')
    """
    from core import build_access, build_authorization as auth_module, build_transaction as bt
    from core.build_authorization import AuthorizationError
    from core import gates

    if not gates.enabled('build_commit'):
        # Refused outright, before any lock and before any byte is written.
        # A gate that half-applies is worse than no gate: the build would be
        # left in a state nobody approved and nobody can name.
        return {
            'outcome': 'build_commit_disabled',
            'stage': 'refused',
            'prepared_change_id': prepared_change_id,
            'error': {
                'code': 'build_commit_disabled',
                'message': ('Writing a change into a build is switched off in this '
                            'installation (NUCLEUS_BUILD_COMMIT=0), so nothing was written. '
                            'The change is still prepared and can be inspected; it cannot be '
                            'applied here.'),
            },
            'achieved': {'prepared': True, 'build_inputs_updated': False, 'exported': False,
                         'installed': False, 'previewed': False},
            'next': {'operation': 'Enable build commits, or apply the prepared menu file by '
                                  'hand from the workspace',
                     'why': 'this installation does not allow the app to write builds'},
        }

    manifest = prepared_change(prepared_change_id)
    row = _resolve(manifest['build_id'])
    directory = Path(row['path'])

    with build_access.build_session(directory) as session:
        try:
            authorization = auth_module.load(authorization_id)
        except AuthorizationError as exc:
            raise _rejected(exc) from None
        if authorization['used']:
            existing = authorization.get('receipt_id')
            if existing:
                return receipt(existing)
            raise BuildChangeRejected('authorization_spent',
                                      f'{authorization_id} was already used.')
        if manifest['status'] != 'prepared':
            raise BuildChangeRejected(
                'blocked_change',
                f'{prepared_change_id} is {manifest["status"]} and cannot be committed.')
        current = session.revision
        # The AUTHORITATIVE task revision, not the one the proposal saved: a
        # request the user has since revised or cancelled must not be satisfied
        # by an approval that was about the old one.
        from randall.assistant.tasks import store as task_store
        task = task_store.current_task_revision(manifest.get('task_id'))
        if task['cancelled']:
            raise BuildChangeRejected(
                'task_cancelled',
                f'Task {manifest.get("task_id")} was cancelled. Nothing was applied.')
        try:
            auth_module.verify(authorization, manifest, build_revision=current,
                               task_revision=(task['revision'] if task['known']
                                              else manifest.get('task_revision')))
        except AuthorizationError as exc:
            raise _rejected(exc) from None

        if target_signature(manifest['build_id']) != manifest['target']:
            raise BuildChangeRejected(
                'stale_authorization',
                'This build is not the game the proposal described any more (its disc header '
                'or menu variant changed). Nothing was applied.')
        compiler = bt.compiler_identity()
        if compiler.get('sha256') != manifest['compiler'].get('sha256'):
            raise BuildChangeRejected(
                'compiler_changed',
                f'The code compiler changed since this was prepared '
                f'({manifest["compiler"]} -> {compiler}); the code list it produces may '
                'differ from the one that was approved.')
        if not compiler.get('available'):
            raise BuildChangeRejected(
                'code_compiler_unavailable',
                'The code compiler is not available, so the build\'s codes.gct cannot be '
                'rebuilt. Nothing was applied.')

        unaccepted = [name for name in manifest['unknown_dimensions']
                      if name not in authorization['accepted_unknown']]
        if unaccepted:
            raise BuildChangeRejected(
                'compatibility_unknown',
                f'These compatibility questions are unanswered and were not accepted: '
                f'{unaccepted}. Authorize them explicitly to install anyway - an unknown is '
                'not a pass.')

        writes = _revalidated_writes(manifest, directory, row)
        receipt_id = f'rc_{manifest["build_id"]}_{secrets.token_hex(6)}'
        identities = {'prepared_change_id': prepared_change_id,
                      'authorization_id': authorization_id,
                      'receipt_id': receipt_id, 'build_id': manifest['build_id'],
                      'task_id': manifest.get('task_id'),
                      'task_revision': manifest.get('task_revision')}

        def finalize_builder(journal):
            # A KIND and an IDENTITY, never a destination: recovery reads this
            # journal back out of the build directory, and a path written here
            # would be a path a project got to choose.
            record = _receipt_record(manifest, authorization, row, directory, journal,
                                     receipt_id)
            return [
                {'kind': 'receipt', 'id': receipt_id, 'json': record},
                {'kind': 'authorization', 'id': authorization_id,
                 'json': auth_module.consumption_record(authorization, receipt_id)},
            ]

        journal = session.apply(
            writes, label=f'menu + codes ({prepared_change_id})',
            identities=identities, code_ini=manifest['codes']['ini'],
            verify=_verifier(manifest), finalize_builder=finalize_builder)

    return receipt(journal['identities']['receipt_id'])


def _revalidated_writes(manifest, directory, row):
    from core import build_transaction as bt
    writes = []
    for write in manifest['writes']:
        destination = ARTIFACT_KINDS[write['kind']]['destination']
        if destination != write['destination']:
            raise BuildChangeRejected(
                'destination_mismatch',
                f'{write["name"]} is a {write["kind"]}, which installs to {destination}; the '
                f'proposal says {write["destination"]}.')
        sealed = bt.assert_contained(bt.journal_root(directory), write['sealed_path'],
                                     what='sealed artifact')
        if not sealed.is_file():
            raise BuildChangeRejected('sealed_artifact_missing',
                                      f'The sealed copy of {write["name"]} is gone.')
        if bt.sha256_file(sealed) != write['replacement_sha256']:
            raise BuildChangeRejected(
                'artifact_hash_mismatch',
                f'The sealed copy of {write["name"]} no longer matches the hash the user '
                'authorized.')
        registered = artifact(write['artifact_id'])
        live = Path(registered['path'])
        if live.is_file() and bt.sha256_file(live) != write['replacement_sha256']:
            raise BuildChangeRejected(
                'artifact_hash_mismatch',
                f'{write["name"]} was rewritten in the workspace after it was authorized. '
                'Register and prepare the new file if that is what should be installed.')
        if bt.sha256_file(directory / destination) != write['original_sha256']:
            raise BuildChangeRejected(
                'stale_authorization',
                f'{destination} in {row["name"]} is not the file this change was prepared '
                'against. Nothing was applied.')
        writes.append({'relpath': destination, 'source': sealed,
                       'sha256': write['replacement_sha256']})
    return writes


def _receipt_record(manifest, authorization, row, directory, journal, receipt_id):
    from core import build_transaction as bt
    after = bt.build_revision(directory)
    partial_because = ['The disc you boot was not rebuilt, so nothing here has been seen in '
                       'game: achieved.installed is False.']
    if manifest.get('preview_requested'):
        # Say what was RECORDED, not what was intended. `wish_recorded.stored`
        # is the database write's own result, carried through from
        # menus.preview; claiming a recording whether or not one happened is the
        # precise failure the wish design exists to stop. The gap is recorded
        # once, at preparation; a commit only reports it.
        stored = bool((manifest.get('preview') or {}).get('wish_recorded', {}).get('stored'))
        partial_because.append(
            'A preview of the produced menu was requested and no renderer exists; '
            + ('the menu_output_preview gap is saved on this device as a feature request.'
               if stored else
               'the gap could not be saved on this device and is reported here only.'))
    return {
        'receipt_id': receipt_id,
        'outcome': 'partial',
        'stage': 'build_inputs_updated',
        'partial_because': partial_because,
        'prepared_change_id': manifest['prepared_change_id'],
        'authorization_id': authorization['authorization_id'],
        'granted_by': authorization['granted_by'],
        'task_id': authorization.get('task_id'),
        'task_revision': authorization.get('task_revision'),
        'build_id': manifest['build_id'],
        'build_name': row['name'],
        'before_revision': manifest['before_revision'],
        'after_revision': after,
        'installed': [{'destination': w['destination'], 'name': w['name'],
                       'sha256': w['replacement_sha256'],
                       'replaced_sha256': w['original_sha256']} for w in manifest['writes']],
        'references': [{'name': r['name'], 'role': r['role'], 'sha256': r['sha256']}
                       for r in manifest['references']],
        'codes': {
            'required': manifest['codes_required'],
            'added': [c['identity'] for c in manifest['codes']['added']],
            'preserved': [c['identity'] for c in manifest['codes']['preserved']],
            'duplicates': [c['identity'] for c in manifest['codes']['duplicates']],
            'enabled': manifest['codes']['enabled'],
            'after_sha256': bt.sha256_file(directory / 'files' / 'codes.ini'),
            'gct_sha256': bt.sha256_file(directory / 'files' / 'codes.gct'),
        },
        'compatibility': {a: {d: v[d]['status'] for d in ('structure', 'target', 'codes')}
                          for a, v in manifest['compatibility'].items()},
        'accepted_unknown': authorization['accepted_unknown'],
        'verification': journal.get('verification'),
        'journal_id': journal['txn_id'],
        'rollback': {'call': 'builds.rollback(receipt_id)', 'restores': manifest['rollback']},
        'preview': manifest['preview'],
        'preview_requested': manifest.get('preview_requested', False),
        'playable': playable_status(manifest['build_id']),
        'achieved': {'prepared': True, 'build_inputs_updated': True, 'exported': False,
                     'installed': False, 'previewed': False},
        'next': {'operation': 'Export / Build ISO',
                 'why': 'so the change reaches the game you actually boot'},
        'limitations': sorted(set(manifest['limitations'] + partial_because)),
        'committed_utc': _now(),
    }


def _verifier(manifest):
    """Reopen what was written and check it is what was authorized."""
    from core import build_transaction as bt
    from core.gecko import parse_ini, _compiled_bytes
    from . import codes as codes_module
    from . import menus as menus_module

    def verify(directory):
        directory = Path(directory)
        checks = []
        for write in manifest['writes']:
            destination = ARTIFACT_KINDS[write['kind']]['destination']
            target = directory / destination
            digest = bt.sha256_file(target)
            checks.append({'check': 'installed_bytes', 'file': destination,
                           'status': 'pass' if digest == write['replacement_sha256'] else 'fail',
                           'expected': write['replacement_sha256'], 'measured': digest})
            menu_type = ARTIFACT_KINDS[write['kind']]['menu_type']
            if not menu_type:
                continue
            installed = library_path(target, why='the file this commit just wrote')
            graph = menus_module.menu_graph_check(installed, menu_type)
            checks.append({'check': 'menu_graph', 'file': destination,
                           'status': graph['status'], 'detail': graph['reason'],
                           'background_pointer': graph['background_pointer']})
            native = menus_module.NATIVE_MENU_READER(installed, menu_type)
            checks.append({'check': 'native_reopen', 'file': destination,
                           'status': 'pass' if native['status'] == 'pass' else native['status'],
                           'detail': native['reason'],
                           'background_sha256': native.get('background_sha256')})
            expected_bundle = _expected_bundle(manifest, write)
            if native.get('background_sha256'):
                if not expected_bundle:
                    checks.append({'check': 'background_semantics', 'file': destination,
                                   'status': 'unknown',
                                   'detail': 'no recorded re-export digest for this package, '
                                             'and comparing against the published bundle '
                                             'would fail on harmless reserialization',
                                   'measured': native['background_sha256']})
                else:
                    same = native['background_sha256'] == expected_bundle
                    checks.append({'check': 'background_semantics', 'file': destination,
                                   'status': 'pass' if same else 'fail',
                                   'expected': expected_bundle,
                                   'measured': native['background_sha256']})

        if manifest['codes']['ini'] is not None:
            after = parse_ini((directory / 'files' / 'codes.ini')
                              .read_text(encoding='utf-8', errors='replace'))
            present = {codes_module.identity(c).lower():
                       (codes_module.normalized_body(c['source']), c['enabled'])
                       for c in after}
            wanted = parse_ini(manifest['codes']['ini'])
            missing = [codes_module.identity(c) for c in wanted
                       if present.get(codes_module.identity(c).lower())
                       != (codes_module.normalized_body(c['source']), c['enabled'])]
            checks.append({'check': 'codes_present', 'status': 'fail' if missing else 'pass',
                           'missing': missing, 'count': len(after)})

            report = bt.gct_report(directory / 'files' / 'codes.gct')
            checks.append({'check': 'codes_compiled', 'status': report['status'],
                           'detail': report['reason'], 'bytes': report['bytes']})
            if report['status'] == 'pass':
                # Only the codes THIS change required. The compiler owns the
                # encoding of everything else: MexCLI compresses and re-encodes
                # the codes already in the build, so their raw bytes are not
                # expected to appear verbatim and asserting otherwise would be a
                # claim about the compiler, not about this change.
                absent, unverifiable = [], []
                required = {row['identity'].lower() for row in manifest['codes_required']}
                for code in wanted:
                    if not code['enabled']:
                        continue
                    if codes_module.identity(code).lower() not in required:
                        continue
                    blob, error, _ = _compiled_bytes(code['source'])
                    if error or not blob:
                        continue
                    if blob in report['body']:
                        continue
                    # MexCLI COMPRESSES a C2 injection whose body is short into
                    # plain 04 writes, so the raw form is legitimately absent.
                    # That is not evidence the code is missing, and calling it a
                    # failure would refuse correct output.
                    targets = codes_module.write_targets(code['source'])
                    if any(write.get('unmodelled_body') for write in targets['writes']):
                        unverifiable.append(codes_module.identity(code))
                    else:
                        absent.append(codes_module.identity(code))
                checks.append({
                    'check': 'codes_in_gct',
                    'status': ('fail' if absent else 'unknown' if unverifiable else 'pass'),
                    'missing': absent, 'unverifiable': unverifiable,
                    'detail': ('the compiler rewrites these into a form this check cannot '
                               'match byte for byte' if unverifiable else None),
                    'checked': sorted(required)})

        failed = [c for c in checks if c['status'] == 'fail']
        unknown = [c for c in checks if c['status'] == 'unknown']
        if failed:
            raise bt.TransactionError(
                'verification_failed',
                f'The build did not come back the way it was authorized: {failed!r}')
        return {'status': 'unknown' if unknown else 'pass', 'checks': checks,
                'unknown': [c['check'] for c in unknown],
                'preview': 'unavailable - no offline menu renderer',
                'playable': 'not rebuilt - the ISO export is a separate operation'}

    return verify


def _expected_bundle(manifest, write):
    """What the installed background should hash to when it is exported AGAIN.

    Not the published bundle's digest: the native reader re-serializes what it
    exports, so a correct install produces a bundle a few bytes different from
    the one that went in. The manifest records the measured re-export digest;
    a package that has none yields no comparison rather than a false failure.
    """
    verdict = manifest['compatibility'].get(write['artifact_id']) or {}
    package_id = (verdict.get('package') or {}).get('package_id')
    if not package_id:
        return None
    from . import menus as menus_module
    for package in menus_module.compatibility_manifest().get('packages', []):
        if package['package_id'] == package_id:
            return (package.get('digests') or {}).get('roundtrip_background_sha256')
    return None


def receipt(receipt_id):
    """Read a commit receipt back by its id.

    Args:
        receipt_id: from :func:`commit_change`.

    Returns:
        dict: the receipt as it was recorded.

    Example:
        >>> builds.receipt(receipt_id)['achieved']['build_inputs_updated']
        True
    """
    from core.build_authorization import AuthorizationError, require_id
    from core.build_transaction import assert_contained
    try:
        require_id('receipt', receipt_id)
    except AuthorizationError as exc:
        raise _rejected(exc) from None
    row = _resolve(receipt_id.split('_')[1])
    bucket = _store(Path(row['path']), 'receipts')
    path = assert_contained(bucket, f'{receipt_id}.json', what='receipt path')
    if not path.is_file():
        raise BuildChangeRejected('unknown_receipt', f'No receipt {receipt_id!r}.')
    return json.loads(path.read_text(encoding='utf-8'))


def rollback(receipt_id):
    """Undo a committed change, putting every original file back.

    Refuses when the build no longer holds what that change wrote: undoing it
    then would silently delete a later change nobody asked to lose.

    Args:
        receipt_id: from :func:`commit_change`.

    Returns:
        dict: ``{'receipt_id', 'restored', 'before_revision', 'after_revision'}``
        where ``after_revision`` is the build's revision once the originals are
        back - normally the receipt's ``before_revision`` again.

    Raises:
        BuildChangeRejected: ``stale_rollback`` or ``backup_not_intact``.

    Example:
        >>> builds.rollback(receipt_id)['after_revision'] == change['before_revision']
        True
    """
    from core import build_access, build_transaction as bt
    record = receipt(receipt_id)
    row = _resolve(record['build_id'])
    directory = Path(row['path'])
    # The updated receipt is part of the rollback's own journaled outcome, not a
    # write that happens after it: a crash between the restore and this update
    # used to leave a receipt describing the state the rollback had just undone.
    updated = {**record, 'rolled_back_utc': _now(), 'outcome': 'rolled_back'}
    with build_access.build_session(directory):
        try:
            undone = bt.rollback(
                directory, record['journal_id'],
                finalize=[{'kind': 'receipt', 'id': receipt_id, 'json': updated}])
        except bt.TransactionError as exc:
            raise BuildChangeRejected(exc.code, str(exc)) from None
    return {'receipt_id': receipt_id, 'restored': undone['restored'],
            'before_revision': record['after_revision'],
            'after_revision': undone['revision']}


def recover(build_id):
    """Finish or undo a change that was interrupted, before anything reads the build.

    Every entry point here does this already, and so does the app when it opens
    a project; call it directly only when you want the report.

    Args:
        build_id: an ``id`` from :func:`list_builds`.

    Returns:
        list[dict]: one entry per journal that needed attention, each
        ``{'txn_id', 'action', 'restored', 'finalized'}``. ``action`` is
        ``'rolled_back'`` for a change that never finished, or ``'finalized'``
        for one whose files were already written and verified - that one is
        completed, not undone, and its receipt appears.

    Example:
        >>> builds.recover(build_id)
        [{'txn_id': 'txn_ab12cd34ef56', 'action': 'rolled_back',
          'restored': ['files/MnSlChr.usd'], 'finalized': []}]
    """
    from core import build_access
    row = _resolve(build_id)
    with build_access.build_session(Path(row['path'])) as session:
        return session.recovery
