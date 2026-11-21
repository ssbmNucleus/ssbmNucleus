""""My game": the remembered relationship between a project, a playable file and a player.

Randall must never decide where someone's changes go. The destination is a
record the user created by an explicit action, it outlives whichever project
happens to be open, and a missing output or a changed project produces a repair
action rather than a fallback to another installation, the newest project, or
the last export. (artifacts/harness-experiment-20260922/ASTRA-ONBOARDING.md,
"designate My game" and the destination data model.)

**The file Nucleus writes is always one Nucleus made.**

This is the invariant the rest of the module exists to protect, and it has no
exceptions:

* The user's clean Melee ISO is a READ-ONLY SOURCE. Projects are created from
  it; nothing ever writes to it. `check_output_path` refuses it by resolved,
  case-insensitive path.
* "The game you play" is the SEPARATE modded ISO this app builds -- the
  project's export, which the user points Slippi Launcher or Dolphin at. It is
  never the clean ISO and never a file that arrived from somewhere else.
* An EXISTING file may be written over only when this app produced it. Proof is
  a marker written beside every promotion (``<name>.nucleus-build.json``) whose
  recorded digest still matches the file. No marker, or a digest that no longer
  matches, means somebody else's ISO -- including the one Slippi Launcher is
  currently pointed at -- and the answer is a new file name, not a warning.
* A path that does not exist yet, inside a folder that does, is always fine:
  Nucleus is about to create it.

Stored in `<STORAGE_PATH>/assistant/settings.json`, per local installation --
absolute paths stay here, and only IDs, labels and display filenames go to the
model. Moving to another PC means rebinding the paths.

    {
      "schema_version": 2,
      "revision": 7,                       # bumps on every write
      "default_destination_id": "dest_ab12…" | null,
      "destinations": {
        "dest_ab12…": {
          "id": "dest_ab12…",
          "kind": "slippi_netplay" | "offline_build" | "project",
          "label": "My Slippi setup",      # what Randall calls it
          "project_ref": {"project_id": "…", "path": "…/project.mexproj",
                          "name": "My Melee"} | null,
          "play_mode": "slippi_netplay" | "offline" | "unset",
          "source_iso_ref": {"path": "…", "bytes": 1459978240,
                             "verified_clean": true | false | null,
                             "checked_at": 1758…} | null,
          "output_iso_ref": {"path": "…/My Melee (Nucleus).iso",
                             "digest": "sha256:…" | null,
                             "produced_by_nucleus": true} | null,
          "player_ref": {"kind": "slippi_launcher" | "dolphin",
                         "path": "…", "config": "…"} | null,
          "launcher_settings_ref": {"iso_path": "…"} | null,
          "played_iso_decision": {"status": "…", "preserves_existing": bool|null,
                                  "played_path": "…"} | null,
          "designation": {"action": "use_this_as_my_game",
                          "at": 1758…, "settings_revision": 7},
          "last_delivery_ref": {"receipt_id": "delivery_…", "at": 1758…,
                                "output": {"path": "…", "bytes": …,
                                           "digest": "sha256:…"}} | null,
          "activation": {"status": "not_required" | "pending" | "verified"
                                   | "user_confirmed" | "unknown",
                         "evidence": "…", "at": 1758…}
        }
      }
    }

Three more rules are enforced here rather than left to a caller:

* **Detection never designates.** `candidates()` reports what is on this PC --
  a Slippi Launcher ISO, the app's projects -- and marks each one
  `selected: false`. Only `designate()`, which a user action calls, writes a
  destination, and only `make_default=True` sets `default_destination_id`.
* **One candidate is still a choice.** `resolve()` returns nothing when no
  destination was designated, even when exactly one project exists. Being the
  only option is not the same as having been chosen.
* **A modded played ISO is never quietly discarded.** Designating a Slippi
  setup whose current game file is not one of ours has to say what happens to
  it: either the played file is a build of the named project (lineage we can
  check through its marker), or the user explicitly asks for a separate copy
  from clean Melee -- which then has to go to a DIFFERENT file.
"""
import hashlib
import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import file_retry
from core import config, file_lock, playable_iso

SCHEMA_VERSION = 2
KINDS = ('slippi_netplay', 'offline_build', 'project')
PLAY_MODES = ('slippi_netplay', 'offline', 'unset')
ACTIVATION_STATUSES = ('not_required', 'pending', 'verified', 'user_confirmed', 'unknown')

#: Written beside every playable copy this app promotes (see
#: `core.playable_iso`). Its presence plus a matching digest is the ONLY proof
#: that a file is ours to overwrite.
MARKER_SUFFIX = playable_iso.MARKER_SUFFIX
MARKER_SCHEMA = playable_iso.MARKER_SCHEMA

#: What Randall calls each kind in a sentence. Never "destination record".
SPOKEN = {'slippi_netplay': 'your Slippi setup',
          'offline_build': 'your offline build',
          'project': 'your {name} project'}

DEFAULT_LABELS = {'slippi_netplay': 'My Slippi setup',
                  'offline_build': 'My offline build',
                  'project': 'My project'}

_SETTINGS_LOCK = threading.RLock()


class DestinationError(ValueError):
    """The destination cannot be designated or used as asked. Nothing changed."""


# --------------------------------------------------------------------------
# file identity and write protection -- one implementation, in core
# --------------------------------------------------------------------------
# `core.playable_iso` owns the rule and every ISO write that obeys it, so the
# delivery workflow, its undo and the export screen's Save button cannot drift
# apart. These names stay here because this module is where the destination
# model talks about them.

digest_file = playable_iso.digest_file
marker_path = playable_iso.marker_path
read_marker = playable_iso.read_marker
write_marker = playable_iso.write_marker
produced_by_nucleus = playable_iso.produced_by_nucleus
FOREIGN_FILE = playable_iso.FOREIGN_FILE


def protected_sources():
    """Every file this app must never write to: the clean Melee ISO."""
    return playable_iso.clean_sources()


def _same_file(left, right):
    return playable_iso.same_file(left, right)


def check_output_path(output_path, *, source_iso=None):
    """May this app write the playable copy to `output_path`? Raises if not.

    Thin wrapper over `core.playable_iso.assert_writable`, which also refuses
    the file Slippi Launcher is configured to open even when that file does not
    exist yet -- a path the user is about to point a game at is not a free name.
    """
    if source_iso and playable_iso.same_file(output_path, source_iso):
        raise DestinationError(playable_iso.CLEAN_SOURCE)
    try:
        playable_iso.assert_writable(output_path)
    except playable_iso.ProtectedPath as exc:
        raise DestinationError(str(exc)) from exc
    return str(Path(output_path))


def suggested_output(project_name):
    """Where a playable copy goes when nobody chose: this app's own folder.

    Never the played ISO's path, never beside the clean Melee file, and always
    Nucleus-suffixed so the file says who made it before anyone opens it.
    """
    from werkzeug.utils import secure_filename
    stem = secure_filename(project_name or '') or 'nucleus-build'
    folder = Path(config.OUTPUT_PATH) / 'games'
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder / f'{stem[:60]} (Nucleus).iso')


@playable_iso.register_protected_provider
def _designated_output_paths():
    """Every designated game copy, so nothing may prune or clobber one."""
    try:
        return [(record.get('output_iso_ref') or {}).get('path')
                for record in read_settings()['destinations'].values()]
    except Exception:  # noqa: BLE001 - unreadable settings protect nothing extra
        return []


# --------------------------------------------------------------------------
# the settings file
# --------------------------------------------------------------------------

def settings_path():
    return Path(config.STORAGE_PATH) / 'assistant' / 'settings.json'


def _blank():
    return {'schema_version': SCHEMA_VERSION, 'revision': 0,
            'default_destination_id': None, 'destinations': {}}


def read_settings():
    """The persisted assistant settings, or a blank record. Never raises."""
    try:
        data = json.loads(settings_path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return _blank()
    if not isinstance(data, dict):
        return _blank()
    base = _blank()
    base.update({k: v for k, v in data.items() if k in base or k not in ('destinations',)})
    if not isinstance(base.get('destinations'), dict):
        base['destinations'] = {}
    return base


def _write_settings(data):
    """Persist settings. Callers hold `settings_transaction()` across read+write.

    The temporary file carries a random name: a fixed `.part` beside the real
    one is a collision waiting for the second writer.
    """
    data['schema_version'] = SCHEMA_VERSION
    data['revision'] = int(data.get('revision') or 0) + 1
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{os.urandom(6).hex()}.part')
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True), encoding='utf-8')
    file_retry.replace(temporary, path)
    return data


@contextmanager
def settings_transaction(*, timeout=15.0):
    """Hold the settings across a read-modify-write, in this process and others.

    Two locks because there are two kinds of competing writer: another thread
    here, and a second Nucleus window. Lock ORDER matters and is fixed by
    `core.file_lock`: anything that also needs the build locks takes those
    FIRST. `designate` therefore resolves its project (which reaches for
    `mexcli_lock`) before entering this block.
    """
    with _SETTINGS_LOCK:
        try:
            with file_lock.exclusive(settings_path(), timeout=timeout):
                yield
        except file_lock.LockBusy as exc:
            raise DestinationError(str(exc)) from exc


def _new_id():
    return 'dest_' + os.urandom(8).hex()


def settings_revision():
    return read_settings().get('revision', 0)


# --------------------------------------------------------------------------
# discovery -- candidates, never selections
# --------------------------------------------------------------------------

def launcher_iso():
    """Only `settings.isoPath` from the Slippi Launcher config, or None.

    One reader, in `core.playable_iso`, so the file the protection rule refuses
    to overwrite and the file activation checks against are always the same
    answer. Deliberately narrow: the Launcher's settings document holds the
    user's netplay auth secret elsewhere, and none of the rest of it belongs
    anywhere near assistant context.
    """
    return playable_iso.launcher_iso()


def candidates():
    """What this PC offers as a destination. Nothing here is ever selected.

    Returns `{'slippi': [...], 'projects': [...], 'searched': [...]}` where each
    entry carries `selected: False`. The `searched` list says exactly where we
    looked, so a card cannot imply every install on the machine was found.
    """
    found = {'slippi': [], 'projects': [],
             'searched': ['the Slippi Launcher configuration',
                          'the projects folder in Nucleus']}
    iso = launcher_iso()
    if iso:
        file = Path(iso)
        found['slippi'].append({
            'kind': 'slippi_netplay', 'selected': False,
            'label': 'My Slippi setup', 'iso_path': iso,
            'iso_filename': file.name, 'exists': file.is_file(),
            'ours': produced_by_nucleus(file),
            'bytes': file.stat().st_size if file.is_file() else None})
    from . import projects as project_tools
    for project in project_tools.list_projects()['projects']:
        found['projects'].append({'kind': 'project', 'selected': False,
                                  'project_id': project['id'], 'label': project['name'],
                                  'path': project['path']})
    return found


# --------------------------------------------------------------------------
# designation
# --------------------------------------------------------------------------

def _project_ref(project_id):
    from . import projects as project_tools
    project = next((p for p in project_tools.list_projects()['projects']
                    if p['id'] == project_id), None)
    if project is None:
        raise DestinationError('That Nucleus project is not in the list any more. '
                               'Choose the game copy again by name.')
    return {'project_id': project['id'], 'path': project['path'], 'name': project['name']}


def _played_iso_decision(played_path, project_id, start_from_clean, output_path):
    """The played-ISO rule, applied before anything is written.

    The file Slippi plays today may carry mods this app did not make. Four
    outcomes, and only four:

    * it is the clean Melee file itself (the recorded source), which carries no
      mods to lose: it is left exactly as it is and the copy goes to a new file;
    * it is one of our builds of the named project -- lineage established by its
      marker, and a rebuild of that project legitimately replaces it;
    * the user explicitly asked to start a separate copy from clean Melee, which
      then has to be a DIFFERENT file, so what they play now is left alone;
    * otherwise: a blocker whose message is the question they have to answer.

    Nothing here ever resolves to writing into a played file we cannot account
    for, and "a project was supplied" is not by itself evidence of preservation.
    """
    file = Path(played_path) if played_path else None
    if file is None or not file.is_file():
        return {'status': 'no_played_file', 'preserves_existing': None,
                'played_path': str(file) if file else ''}
    if any(_same_file(file, clean) for clean in protected_sources()):
        # Slippi plays the clean Melee file itself. Nothing in it can be lost:
        # the project is built FROM it, and the new copy goes to a different file
        # (`check_output_path` refuses the clean source as an output, always).
        if _same_file(file, output_path):
            raise DestinationError(playable_iso.CLEAN_SOURCE)
        return {'status': 'played_is_clean_source', 'preserves_existing': True,
                'played_path': str(file)}
    marker = read_marker(file)
    ours = produced_by_nucleus(file)
    if ours and marker and project_id and marker.get('project_id') == project_id:
        return {'status': 'our_build_of_this_project', 'preserves_existing': True,
                'played_path': str(file)}
    if start_from_clean:
        if _same_file(file, output_path):
            raise DestinationError(
                f'Starting a separate copy from clean Melee cannot write over {file.name}, '
                'which is the file you play now. Choose a different name for the new copy.')
        return {'status': 'start_from_clean', 'preserves_existing': False,
                'played_path': str(file)}
    if ours:
        raise DestinationError(
            f'{file.name} is a Nucleus build, but not of the project you named, so I cannot '
            'tell what is in it. Point me at the project it came from, or tell me to start a '
            'separate copy from clean Melee.')
    raise DestinationError(
        f'{file.name} is the game you play now, and it is not a file Nucleus made, so I '
        'cannot tell what is already in it. I will not start over from a clean copy and lose '
        'it quietly. Tell me to start a separate copy from clean Melee and I will leave '
        f'{file.name} exactly as it is.')


def designate(kind, *, label=None, project_id=None, output_iso_path=None,
              play_mode=None, played_iso_path=None, start_from_clean=False,
              player_path=None, player_config=None, make_default=True,
              destination_id=None):
    """Record "this is my game", from an explicit user action. Returns the record.

    Args:
        kind: `slippi_netplay` | `offline_build` | `project`.
        project_id: the editable Nucleus project this destination builds from.
        output_iso_path: the exact file the user will play. Required for a
            Slippi or offline destination, and for any project destination whose
            play mode is not `unset`; that file is what "ready to play" means.
            It is checked against `check_output_path`, so it can never be the
            clean Melee ISO or a file this app did not produce.
        played_iso_path: for a Slippi designation, the file the Launcher plays
            today. Subject to the played-ISO rule above.
        start_from_clean: the user's explicit "start a separate copy from clean
            Melee" answer to that rule.
        make_default: `Use this as my game`. "Use here once" passes False.

    Raises:
        DestinationError: with the sentence the user has to answer.
    """
    if kind not in KINDS:
        raise DestinationError(f"kind must be one of {', '.join(KINDS)}.")
    if play_mode is not None and play_mode not in PLAY_MODES:
        raise DestinationError(f"play_mode must be one of {', '.join(PLAY_MODES)}.")
    if kind == 'project' and not project_id:
        raise DestinationError('Name the Nucleus project this destination uses.')
    if kind == 'project' and play_mode in (None, 'unset'):
        raise DestinationError('Say whether you play this project on Slippi or offline.')

    resolved_mode = play_mode or ('slippi_netplay' if kind == 'slippi_netplay'
                                  else 'offline' if kind == 'offline_build' else 'unset')
    # Resolving the project reaches for `mexcli_lock`, so it happens BEFORE the
    # settings lock is taken. The reverse order deadlocks against a delivery,
    # which holds the build locks and then records its result here.
    project = _project_ref(project_id) if project_id else None
    chosen = 'user'
    if resolved_mode != 'unset' and not output_iso_path:
        # A default that is safe by construction: inside this app's own output
        # folder, Nucleus-suffixed, never the game file they already have.
        output_iso_path = suggested_output((project or {}).get('name') or label)
        chosen = 'default'

    output = check_output_path(output_iso_path) if output_iso_path else None

    preservation = None
    if kind == 'slippi_netplay':
        preservation = _played_iso_decision(played_iso_path or launcher_iso(),
                                            project_id, start_from_clean, output)

    with settings_transaction():
        data = read_settings()
        record_id = destination_id or _new_id()
        existing = data['destinations'].get(record_id, {})
        record = {
            'id': record_id, 'kind': kind,
            'label': label or existing.get('label') or DEFAULT_LABELS[kind],
            'project_ref': project or existing.get('project_ref'),
            'play_mode': resolved_mode,
            'source_iso_ref': existing.get('source_iso_ref'),
            'output_iso_ref': ({'path': output, 'digest': digest_file(output),
                                'produced_by_nucleus': produced_by_nucleus(output)}
                               if output else existing.get('output_iso_ref')),
            'player_ref': ({'kind': 'slippi_launcher' if kind == 'slippi_netplay' else 'dolphin',
                            'path': player_path, 'config': player_config}
                           if player_path or player_config else existing.get('player_ref')),
            'launcher_settings_ref': ({'iso_path': launcher_iso()}
                                      if kind == 'slippi_netplay' else None),
            'played_iso_decision': preservation or existing.get('played_iso_decision'),
            'designation': {'action': 'use_this_as_my_game' if make_default else 'use_here_once',
                            'at': time.time(), 'settings_revision': data['revision'] + 1,
                            'output_chosen': chosen},
            'last_delivery_ref': existing.get('last_delivery_ref'),
            'activation': existing.get('activation') or {
                'status': 'not_required' if resolved_mode != 'slippi_netplay' else 'pending',
                'evidence': '', 'at': time.time()}}
        data['destinations'][record_id] = record
        if make_default:
            data['default_destination_id'] = record_id
        _write_settings(data)
    return record


def forget(destination_id):
    """Drop a destination. The default falls back to nothing, never to another."""
    with settings_transaction():
        data = read_settings()
        if data['destinations'].pop(destination_id, None) is None:
            return False
        if data.get('default_destination_id') == destination_id:
            data['default_destination_id'] = None
        _write_settings(data)
    return True


# --------------------------------------------------------------------------
# resolution and readiness
# --------------------------------------------------------------------------

def get(destination_id):
    return read_settings()['destinations'].get(destination_id)


def default_destination():
    data = read_settings()
    return data['destinations'].get(data.get('default_destination_id') or '')


def for_project(project_id):
    return [record for record in read_settings()['destinations'].values()
            if (record.get('project_ref') or {}).get('project_id') == project_id]


def resolve(*, destination_id=None, project_id=None, task_destination_id=None):
    """"Put it in my game", in the order the review fixes.

    1. the destination named in this request, 2. the one already bound to this
    task, 3. the explicitly designated default, 4. nothing -- which is a
    decision for the user, never a guess. A one-time target never becomes the
    default, and a changed default never retargets work already bound.

    Returns `(record, reason)`; `record` is None when the user has to choose,
    and `reason` says why so the caller can word it.

    Raises:
        DestinationError: when the request names two targets that disagree, or
            one project backs several designated game copies. Both are
            ambiguity, and ambiguity is answered, never resolved by picking.
    """
    named = get(destination_id) if destination_id else None
    if destination_id and named is None:
        raise DestinationError('That game copy is not one I have on record. '
                               'Choose it again by name.')
    if named is not None and project_id:
        bound = (named.get('project_ref') or {}).get('project_id')
        if bound and bound != project_id:
            raise DestinationError(
                f"You named the {named.get('label')} game copy and a different project. "
                'Say which one this should go into; I will not build one and save the other.')
    if named is not None:
        return named, 'named_in_request'
    if project_id:
        matches = for_project(project_id)
        if len(matches) > 1:
            raise DestinationError(
                'That project backs more than one game copy of yours ('
                + ', '.join(record.get('label') or record['id'] for record in matches)
                + '). Say which one.')
        if matches:
            return matches[0], 'named_in_request'
        return None, 'project_named_without_destination'
    if task_destination_id:
        record = get(task_destination_id)
        if record is not None:
            return record, 'bound_to_task'
    record = default_destination()
    if record is not None:
        return record, 'designated_default'
    return None, 'no_designation'


def availability(record):
    """Can this destination be delivered to right now, and if not, what repairs it.

    A missing output file or a vanished project is a repair action. It is never
    a reason to use a different project or the last export. Messages name files
    and labels, not directories: they end up in a model's context.
    """
    if not record:
        return {'ready': False, 'blocker': 'no_destination',
                'message': 'No game copy is set as yours yet.'}
    project = record.get('project_ref') or {}
    if not project.get('path') or not Path(project['path']).is_file():
        return {'ready': False, 'blocker': 'project_missing',
                'message': f"The Nucleus project behind {spoken(record)} is not where it was. "
                           'Point me at it again; I will not use a different one.'}
    output = (record.get('output_iso_ref') or {}).get('path')
    if record.get('play_mode', 'unset') != 'unset':
        if not output:
            return {'ready': False, 'blocker': 'no_output_location',
                    'message': f'Choose where the playable copy for {spoken(record)} lives.'}
        try:
            check_output_path(output)
        except DestinationError as exc:
            # The message goes into a model's context, so it names the file and
            # what is wrong with it -- never the folder it sits in.
            name = Path(output).name
            if not Path(output).parent.is_dir():
                return {'ready': False, 'blocker': 'output_folder_missing',
                        'message': f'The folder that held {name} is gone. Choose a new '
                                   'location for your playable copy; I will not pick another '
                                   'game for you.'}
            return {'ready': False, 'blocker': 'output_not_ours', 'message': str(exc)}
    return {'ready': True, 'blocker': None, 'message': ''}


def spoken(record):
    """How Randall names this destination in a sentence."""
    if not record:
        return 'your game'
    if record['kind'] == 'project':
        return SPOKEN['project'].format(name=(record.get('project_ref') or {}).get('name')
                                        or record.get('label') or 'Nucleus')
    return record.get('label') or SPOKEN[record['kind']]


def launcher_selection(record):
    """Has the player actually been pointed at this destination's copy?

    Decided by PLAY MODE, not by the record's kind: a project destination the
    user plays on Slippi needs the same Launcher step as a Slippi destination,
    and branching on kind quietly exempted it.

    `verified` only when the Launcher's own `settings.isoPath` resolves to the
    same file, and only when that configuration is the one this destination is
    bound to. `unknown` when the configuration cannot be read -- which is when
    the user gets to say "I selected this file" and have it recorded as their
    word, not as a check that passed.
    """
    if record.get('play_mode') != 'slippi_netplay':
        return {'status': 'not_required',
                'evidence': 'This game copy is not played through Slippi Launcher.'}
    output = (record.get('output_iso_ref') or {}).get('path')
    if not output:
        return {'status': 'pending', 'evidence': 'No playable copy has been built yet.'}
    configured = launcher_iso()
    if configured is None:
        return {'status': 'unknown',
                'evidence': 'I could not read the Slippi Launcher settings, so I cannot tell '
                            'which file it will open.'}
    bound = (record.get('player_ref') or {}).get('config')
    if bound and not _same_file(bound, _launcher_config_path()):
        return {'status': 'unknown',
                'evidence': 'The Slippi Launcher configuration I can read is not the one this '
                            'game copy is bound to.'}
    if _same_file(configured, output):
        return {'status': 'verified',
                'evidence': f'Slippi Launcher is set to {Path(output).name}.'}
    return {'status': 'pending',
            'evidence': f'Slippi Launcher is still set to {Path(configured).name}.'}


def effective_activation(record):
    """What we may say about the player right now, live evidence first.

    A live reading always wins when it establishes something: `verified` and
    `not_required` are facts, and `pending` is positive evidence that the player
    is pointed somewhere else -- the user's earlier "I selected it" cannot
    survive that. Only when the configuration cannot be READ at all does a
    stored `user_confirmed` stand, because then their word is the only evidence
    there is, and it is reported as their word.

    Selection is about the PATH, so a new build at the same path does not
    invalidate it.
    """
    live = launcher_selection(record) if record else {
        'status': 'not_required', 'evidence': 'No playable copy is designated for this build.'}
    stored = (record or {}).get('activation') or {}
    if live['status'] == 'unknown' and stored.get('status') == 'user_confirmed':
        return {'status': 'user_confirmed',
                'evidence': stored.get('evidence') or 'You told me you selected it yourself.'}
    return live


def _launcher_config_path():
    try:
        from shared.ingame.boot import launcher_dir
        return launcher_dir('Settings')
    except Exception:  # noqa: BLE001
        return None


def confirm_activation(destination_id, *, by_user=False):
    """Re-check the player, or record the user's own "I selected this file"."""
    with settings_transaction():
        data = read_settings()
        record = data['destinations'].get(destination_id)
        if record is None:
            raise DestinationError('That game copy is not one I have on record.')
        if by_user:
            state = {'status': 'user_confirmed',
                     'evidence': 'You told me you selected it yourself.',
                     'at': time.time()}
        else:
            state = {**launcher_selection(record), 'at': time.time()}
        record['activation'] = state
        _write_settings(data)
    return state


def record_delivery(destination_id, receipt_id, output, activation=None):
    """Bind the durable receipt for what was built and saved to this destination."""
    with settings_transaction():
        data = read_settings()
        record = data['destinations'].get(destination_id)
        if record is None:
            return None
        record['last_delivery_ref'] = {'receipt_id': receipt_id, 'at': time.time(),
                                       'output': output}
        if output and output.get('path'):
            record['output_iso_ref'] = {'path': output['path'],
                                        'digest': output.get('digest'),
                                        'produced_by_nucleus': True}
        if activation:
            record['activation'] = {**activation, 'at': time.time()}
        _write_settings(data)
    return record


def seal(record):
    """The exact target an approval authorizes, without carrying its paths.

    A basename is not an identity: `D:\\A\\game.iso` and `D:\\B\\game.iso` look
    the same in a card. What is sealed is the settings revision the destination
    was read at, a digest of the resolved output PATH, and the digest of
    whatever file is at that path right now -- so a destination edited between
    approval and execution invalidates the approval instead of silently
    retargeting it.
    """
    if not record:
        return None
    output = (record.get('output_iso_ref') or {}).get('path')
    return {'destination_id': record['id'], 'kind': record['kind'],
            'play_mode': record.get('play_mode'),
            'settings_revision': settings_revision(),
            'output_path_digest': ('sha256:' + hashlib.sha256(
                os.path.normcase(str(Path(output).resolve() if Path(output).parent.is_dir()
                                     else Path(output))).encode()).hexdigest()) if output else None,
            'output_digest': digest_file(output) if output else None,
            'output_filename': Path(output).name if output else None}


def reseal_matches(record, sealed):
    """Is the live destination still the one the approval named?"""
    if sealed is None:
        return record is None
    current = seal(record)
    if current is None:
        return False
    return all(current.get(key) == sealed.get(key)
               for key in ('destination_id', 'kind', 'play_mode',
                           'output_path_digest', 'output_digest'))


def public(record):
    """The model-safe view: IDs, labels and display filenames. No absolute paths."""
    if not record:
        return None
    output = (record.get('output_iso_ref') or {}).get('path')
    player = record.get('player_ref') or {}
    return {'destination_id': record['id'], 'kind': record['kind'],
            'label': record.get('label'), 'spoken': spoken(record),
            'play_mode': record.get('play_mode'),
            # Whether a player is BOUND, not which one: "Open game" may only be
            # offered for a player the user actually chose.
            'player_bound': bool(player.get('path') or player.get('config')),
            'player_kind': player.get('kind'),
            'project_name': (record.get('project_ref') or {}).get('name'),
            'project_id': (record.get('project_ref') or {}).get('project_id'),
            'output_filename': Path(output).name if output else None,
            'activation': (record.get('activation') or {}).get('status'),
            'last_delivery_receipt': (record.get('last_delivery_ref') or {}).get('receipt_id')}
