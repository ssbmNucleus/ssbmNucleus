"""The build a delivery writes into, read with content identity: its costume table and revision,
the slots a delivery added and whether they still stand, and which build the user named."""

import hashlib
import json
from pathlib import Path

from core import playable_iso
from mexcli.project import fighter_files

from . import projects


# --------------------------------------------------------------------------
# the build's costume table, with content identity
# --------------------------------------------------------------------------

def _files_dir(project_path):
    return Path(project_path).parent / 'files'


def _file_digest(project_path, filename):
    """SHA-256 of one costume file inside the project, or None."""
    if not filename:
        return None
    return playable_iso.digest_file(_files_dir(project_path) / filename)


def _costume_table(project_path):
    """`{fighter_id: {'name', 'costumes': [{slot, name, filename}]}}` for the build.

    This is the shape undo restores, read from the project's own files rather
    than from whatever an install command reported. Content hashes are NOT taken
    here -- hashing every costume of every fighter would cost hundreds of
    megabytes of reading per snapshot. They are taken for the specific slots a
    delivery touches, which is where identity actually has to hold.
    """
    table = {}
    for path in fighter_files(project_path):
        if not path.stem.isdigit():
            continue
        fighter = json.loads(path.read_text(encoding='utf-8-sig'))
        table[str(int(path.stem))] = {
            'name': fighter.get('name', ''),
            'costumes': [{'slot': index + 1, 'name': costume.get('name', ''),
                          'filename': (costume.get('file') or {}).get('fileName', '')}
                         for index, costume in enumerate(fighter.get('costumes', []))]}
    return table


def _project_revision(project_path):
    """A content revision for the build, for sealing an approval against it."""
    payload = json.dumps(_costume_table(project_path), sort_keys=True)
    try:
        from core import build_transaction
        payload += json.dumps(build_transaction.managed_digests(Path(project_path).parent),
                              sort_keys=True)
    except Exception:  # noqa: BLE001 - a build without managed files still revs
        pass
    return 'sha256:' + hashlib.sha256(payload.encode()).hexdigest()


def _added_slots(project_path, before, after):
    """Exactly which slots appeared, per fighter, with the bytes that are in them.

    Compared by position, because an install appends; the sha256 recorded here
    is what makes the later removal a statement about THOSE bytes rather than
    about whatever ends up at that index.
    """
    added, disturbed = [], []
    for fighter_id, entry in after.items():
        previous = (before.get(fighter_id) or {}).get('costumes', [])
        current = entry['costumes']
        if current[:len(previous)] != previous:
            disturbed.append(fighter_id)
        for index in range(len(previous), len(current)):
            slot = current[index]
            added.append({'fighter': int(fighter_id), 'fighter_name': entry['name'],
                          'index': index, 'slot': index + 1,
                          'name': slot['name'], 'filename': slot['filename'],
                          'sha256': _file_digest(project_path, slot['filename'])})
    return added, disturbed


def _member_states(project_path, slots):
    """Classify every costume this delivery added: found, conflicting, or gone.

    Three states, not two. "Not all of them are present" is not "all of them
    were removed": a delivery that put two costumes in and lost one of them to
    an interrupted undo must not be reported as restored, and must not have its
    removal skipped.

    Members are located by FILENAME AND CONTENT HASH anywhere in the fighter's
    table rather than at the index they were recorded at, because removing an
    earlier costume shifts every later one. A filename that is still there
    holding different bytes is a `conflict`: somebody else's costume is using
    that name now, and removing it would take out their work.
    """
    table = _costume_table(project_path)
    found, conflict, missing = [], [], []
    for slot in slots:
        costumes = (table.get(str(slot['fighter'])) or {}).get('costumes', [])
        by_name = [index for index, entry in enumerate(costumes)
                   if entry['filename'] and entry['filename'] == slot['filename']]
        exact = [index for index in by_name
                 if not slot.get('sha256')
                 or _file_digest(project_path, costumes[index]['filename']) == slot['sha256']]
        if exact:
            found.append({**slot, 'current_index': exact[0]})
        elif by_name:
            conflict.append({**slot, 'current_index': by_name[0],
                             'why': 'that costume file has changed since'})
        else:
            missing.append({**slot, 'why': 'the slot is gone'})
    return {'found': found, 'conflict': conflict, 'missing': missing}


# --------------------------------------------------------------------------
# subject and destination
# --------------------------------------------------------------------------

def _builds():
    return projects.list_projects()


def _choose_build(builds, prompt=''):
    names = ' or '.join(build['name'] for build in builds) if len(builds) == 2 \
        else ', '.join(build['name'] for build in builds)
    return {'kind': 'choose_build',
            'prompt': prompt or (f'Choose the game copy here: {names}. '
                                 'I will add the costume to that copy.'),
            'responses': [{'project_id': build['id'], 'name': build['name']}
                          for build in builds],
            'builds': builds}


def _no_builds(listing):
    return {'kind': 'no_build',
            'prompt': 'There is no game copy to put this in yet. '
                      + ('I can make one from your clean Melee first (the clean file is never '
                         'changed), then add the costume and make it the game you play.'
                         if listing.get('can_create') else
                         'Set your clean Melee game file in Settings first, then create one.'),
            'responses': [{'action': 'create_project'}], 'builds': []}


def _resolve_build(project_id):
    """The project the user named -- or the decision that has to come first.

    Being the only project on the machine is not the same as having been
    chosen: with no designation and no named project, this asks, even when the
    list has one entry. The first version picked that one entry, which is the
    silent choice the review forbids.
    """
    listing = _builds()
    builds = listing['projects']
    if not builds:
        return None, _no_builds(listing)
    if project_id:
        match = next((build for build in builds if build['id'] == project_id), None)
        if match is not None:
            return match, None
        return None, _choose_build(
            builds, 'That game copy is not in the list any more. Choose one of these: '
                    + ', '.join(build['name'] for build in builds) + '.')
    return None, _choose_build(builds)
