"""One live snapshot of the application, for the turn that is about to start.

The engine reads this itself before any paid routing call and hands the result
in as context. Spending an AI round asking Randall to go and look up setup state
the application already knows is the waste the review names, and a model that
re-derives "is a game file configured" from conversation will eventually get it
wrong. (ASTRA-ONBOARDING.md, `app_context.read()`.)

Everything here is cheap and read-only. In particular:

* **Header checks are not hash checks.** `vanilla_iso.hash_verified` is only
  ever the value setup recorded when it ran the MD5 check. This read never
  performs one and never upgrades "the file is there and looks like a disc" into
  "verified clean Melee 1.02".
* **Nothing is written, created or probed with side effects.** No Dolphin
  settings are touched, no fallback folders are created, and discovery reports
  exactly where it looked.
* **Absolute paths stay in the backend.** `public()` is what goes to a model:
  IDs, labels, display filenames and states.

Shape (`schema_version` 1):

    {
      "schema_version": 1,
      "captured_at": 1758…,
      "settings_revision": 7,
      "vanilla_iso": {"configured": true, "filename": "melee.iso",
                      "exists": true, "bytes": 1459978240,
                      "hash_verified": true|false|null,
                      "note": "…header vs hash…"},
      "destination": {…destination.public()…} | null,
      "destination_availability": {"ready": bool, "blocker": str|null,
                                   "message": str},
      "candidates": {"slippi": [...], "projects": [...], "searched": [...]},
      "launcher_selection": {"status": "verified|pending|unknown", "evidence": "…"},
      "active_project": {"id": "…", "name": "…"} | null,
      "destination_project": {"id": "…", "name": "…"} | null,
      "access": {"assistant_enabled": bool, "credential_source": "patreon"},
      "recent_deliveries": [{"receipt_id", "subject", "project", "active"}],
      "actions": ["designate_destination", "deliver_to_game", …]
    }
"""
import time
from pathlib import Path

from core import config, gates

from randall.delivery import destination as destinations

SCHEMA_VERSION = 1

_HASH_NOTE = ('`exists` and `bytes` are a file check on the recorded path. `hash_verified` '
              'is null because the vanilla-source record keeps only the path: the clean-Melee '
              'MD5 check runs during setup and its result is not retained here, and this '
              'snapshot never runs one. Treat a configured source as "a file is set", not as '
              '"verified clean Melee 1.02".')


def _vanilla_iso():
    """The clean Melee source: whether one is set, and whether it is there.

    `hash_verified` stays None on purpose. The recorder stores a path and
    nothing else, so there is no retained verification to report; reporting a
    field it never writes would have read as "verified" the moment somebody
    added one with a different meaning.
    """
    from shared.vanilla_extract import vanilla_refs
    path = vanilla_refs.known_vanilla_iso()
    record = {}
    try:
        import json
        record = json.loads(Path(vanilla_refs.ISO_RECORD_PATH).read_text(encoding='utf-8'))
    except Exception:  # noqa: BLE001 - a missing record is "not configured"
        record = {}
    if path is None:
        return {'configured': bool(record.get('path')),
                'filename': Path(record['path']).name if record.get('path') else None,
                'exists': False, 'bytes': None, 'hash_verified': None, 'note': _HASH_NOTE}
    return {'configured': True, 'filename': path.name, 'exists': True,
            'bytes': path.stat().st_size, 'hash_verified': None, 'note': _HASH_NOTE}


def _active_project():
    from core import state
    active = state.get_current_project_path()
    if not active:
        return None
    from randall.delivery import projects as project_tools
    for project in project_tools.list_projects()['projects']:
        if Path(project['path']) == Path(active):
            return {'id': project['id'], 'name': project['name']}
    return {'id': None, 'name': Path(active).parent.name}


def read(*, include_candidates=True):
    """The snapshot. Cheap enough to take at the start of every turn."""
    settings = destinations.read_settings()
    record = destinations.default_destination()
    context = {
        'schema_version': SCHEMA_VERSION,
        'captured_at': time.time(),
        'settings_revision': settings.get('revision', 0),
        'vanilla_iso': _vanilla_iso(),
        'destination': destinations.public(record),
        'destination_availability': destinations.availability(record),
        'candidates': destinations.candidates() if include_candidates else None,
        # By PLAY MODE, not by kind: a project destination played on Slippi
        # needs the same Launcher step as a Slippi destination.
        'launcher_selection': (destinations.effective_activation(record)
                               if record and record.get('play_mode') == 'slippi_netplay'
                               else None),
        'active_project': _active_project(),
        'destination_project': ({'id': (record.get('project_ref') or {}).get('project_id'),
                                 'name': (record.get('project_ref') or {}).get('name')}
                                if record else None),
        'access': {'assistant_enabled': gates.enabled('assistant'),
                   'credential_source': 'patreon'},
    }
    from randall.delivery import deliver
    context['delivery_enabled'] = deliver.delivery_enabled()
    context['recent_deliveries'] = [
        {'receipt_id': row['receipt_id'], 'subject': (row['subject'] or {}).get('name'),
         'project': (row['project'] or {}).get('name'), 'kind': row['kind'],
         'status': row.get('status'), 'active': row['active']}
        for row in deliver.list_deliveries(limit=5)]
    context['actions'] = _actions(context)
    return context


def _actions(context):
    """What the app can offer right now. Named controls, not tool names."""
    actions = []
    if not context['vanilla_iso']['exists']:
        actions.append('choose_game_file')
    if context['destination'] is None:
        actions.append('designate_destination')
    elif not context['destination_availability']['ready']:
        actions.append('repair_destination')
    else:
        actions.append('deliver_to_game')
    if (context.get('launcher_selection') or {}).get('status') in ('pending', 'unknown'):
        actions.append('check_slippi_selection')
    if context.get('delivery_enabled') is False and 'deliver_to_game' in actions:
        actions.remove('deliver_to_game')
    return actions


def public(context=None):
    """The part of the snapshot a model may see. Already free of absolute paths."""
    context = context or read()
    trimmed = dict(context)
    candidates = context.get('candidates') or {}
    trimmed['candidates'] = {
        'slippi': [{'label': entry['label'], 'iso_filename': entry['iso_filename'],
                    'exists': entry['exists'], 'selected': entry['selected']}
                   for entry in candidates.get('slippi', [])],
        'projects': [{'project_id': entry['project_id'], 'label': entry['label'],
                      'selected': entry['selected']}
                     for entry in candidates.get('projects', [])],
        'searched': candidates.get('searched', [])}
    iso = dict(context['vanilla_iso'])
    iso.pop('bytes', None)
    trimmed['vanilla_iso'] = iso
    return trimmed
