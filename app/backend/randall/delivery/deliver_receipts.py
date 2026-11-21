"""Delivery receipts, the operation journal, and the one reading of what a delivery achieved:
write, read, list and recover receipts; `current_state` and `achieved`."""

import json
import os
import time
from pathlib import Path

import file_retry
from core import config, playable_iso

from . import destination as destinations

from .deliver_policy import DeliveryError
from .deliver_project import _member_states


# --------------------------------------------------------------------------
# receipts: the operation journal
# --------------------------------------------------------------------------
# TODO(session-1): migrate these to assistant/tasks/store.py once that store's
# API settles. They live in the app's data directory rather than in the build
# because `projects._snapshot` hashes every file under the build directory to
# revalidate an approved install -- a receipt written there would invalidate the
# next install's own approval. The file here is authoritative for undo and for
# recovery, because both have to work after the tasks database is reset.

def _receipt_root():
    return Path(config.STORAGE_PATH) / 'assistant' / 'deliveries'


def _write_receipt(receipt):
    receipt['updated_at'] = time.time()
    folder = _receipt_root() / receipt['project']['id']
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{receipt['receipt_id']}.json"
    temporary = path.with_name(path.name + f'.{os.urandom(6).hex()}.part')
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding='utf-8')
    file_retry.replace(temporary, path)
    return path


def read_receipt(receipt_id):
    """One receipt by id, or None. Receipt ids are opaque and never a path."""
    if not isinstance(receipt_id, str) or not receipt_id.startswith('delivery_') \
            or not receipt_id[9:].isalnum():
        raise DeliveryError('Use a receipt ID from a delivery result.')
    for path in _receipt_root().glob(f'*/{receipt_id}.json'):
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
    return None


def _all_receipts(project_id=None):
    pattern = f'{project_id}/*.json' if project_id else '*/*.json'
    rows = []
    for path in _receipt_root().glob(pattern):
        try:
            rows.append(json.loads(path.read_text(encoding='utf-8')))
        except (OSError, ValueError):
            continue
    return sorted(rows, key=lambda row: row.get('created_at', 0), reverse=True)


def list_deliveries(project_id=None, limit=20):
    """Recent deliveries, newest first: what went where, and whether it stands."""
    return [{'receipt_id': row.get('receipt_id'), 'created_at': row.get('created_at', 0),
             'project': row.get('project', {}), 'subject': row.get('subject', {}),
             'kind': row.get('kind', 'delivery'), 'status': row.get('status'),
             'destination_id': row.get('destination_id'),
             'active': row.get('status') in ('running', 'completed', 'undoing'),
             'achieved': row.get('achieved', {})}
            for row in _all_receipts(project_id)[:limit]]


def public_deliveries(project_id=None, limit=20):
    """What the UI shows in a list of deliveries: names, states, no paths.

    The card that offers "take it back out" reads this, so it carries the
    receipt id, what went where, whether it still stands, and the live
    `achieved` -- derived from `current_state`, not from a stored flag.
    """
    rows = []
    for row in _all_receipts(project_id)[:limit]:
        state_now = current_state(row)
        rows.append({
            'receipt_id': row.get('receipt_id'),
            'created_at': row.get('created_at', 0),
            'updated_at': row.get('updated_at', 0),
            'kind': row.get('kind', 'delivery'),
            'status': row.get('status'),
            'change': row.get('change', ''),
            'costume': (row.get('subject') or {}).get('name'),
            'character': (row.get('subject') or {}).get('character'),
            'project_name': (row.get('project') or {}).get('name'),
            'destination': (row.get('destination') or {}).get('spoken'),
            'output_filename': (row.get('destination') or {}).get('output_filename'),
            'placement': [{'fighter': slot['fighter_name'], 'slot': slot['slot']}
                          for slot in row.get('added', [])],
            'achieved': _achieved(row, state_now),
            'can_undo': bool(row.get('status') in ('running', 'completed', 'undoing')
                             and state_now['in_project']),
            'activation': state_now['activation']['status']})
    return rows


def _standing_receipt(project_id, destination_id, subject_key, assets_digest=None):
    """The open delivery of THIS costume, to THIS game copy, from THESE bytes.

    Keyed by destination as well as project, so two game copies backed by the
    same project cannot inherit each other's deliveries -- and by the sealed
    asset digests, so a costume whose ZIP changed under the same vault ID is a
    NEW delivery rather than an old receipt reporting `installed` for bytes
    nobody ever imported.
    """
    for row in _all_receipts(project_id):
        if row.get('kind') != 'delivery' or row.get('status') not in ('running', 'completed'):
            continue
        if row.get('subject', {}).get('key') != subject_key:
            continue
        if (row.get('destination_id') or None) != (destination_id or None):
            continue
        if assets_digest and (row.get('seal') or {}).get('assets_digest') != assets_digest:
            continue
        return row
    return None


def _later_active_deliveries(receipt):
    """Deliveries to the same project made AFTER this one and still standing.

    Undoing out of order shifts the slots a later receipt recorded, which would
    silently invalidate it. Rather than rewrite somebody else's receipt, this is
    reported and the removal is refused.
    """
    return [row for row in _all_receipts(receipt['project']['id'])
            if row.get('kind') == 'delivery'
            and row.get('receipt_id') != receipt['receipt_id']
            and row.get('status') in ('running', 'completed')
            and row.get('created_at', 0) > receipt.get('created_at', 0)]


def recover_deliveries(project_id=None):
    """Reconcile deliveries this process did not see finish.

    A `running` receipt means the app went away between a mutation and its next
    checkpoint. Nothing is replayed: the receipt is re-read against what is
    actually on disk now, and left in a state a retry or an undo can act on.
    """
    reconciled = []
    for row in _all_receipts(project_id):
        if row.get('status') not in ('running', 'undoing'):
            continue
        state_now = current_state(row)
        row['recovered_at'] = time.time()
        row['achieved'] = _achieved(row, state_now)
        if row['status'] == 'running':
            row['status'] = 'completed' if state_now['complete'] else 'running'
        elif state_now['restored']:
            row['status'] = 'undone'
            row['undone_at'] = row.get('undone_at') or time.time()
        _write_receipt(row)
        reconciled.append({'receipt_id': row['receipt_id'], 'status': row['status'],
                           'state': state_now})
    return reconciled


# --------------------------------------------------------------------------
# one reading of reality
# --------------------------------------------------------------------------

def current_state(receipt):
    """Re-read what is actually true about this delivery, right now.

    ONE predicate, used for the receipt's status, for `achieved` and for the
    sentence, so those three can never disagree. It never trusts a recorded
    flag: the project is read, the playable copy is hashed, the player is asked.
    """
    project_path = receipt['project']['path']
    exists = Path(project_path).is_file()
    slots = receipt.get('added') or []
    members = (_member_states(project_path, slots) if exists
               else {'found': [], 'conflict': [], 'missing': list(slots)})
    # "All of them are there" and "none of them are there" are different
    # questions, and the first version answered both with one boolean.
    in_project = bool(slots) and len(members['found']) == len(slots)
    none_present = not members['found'] and not members['conflict']
    record = destinations.get(receipt['destination_id']) if receipt.get('destination_id') else None
    playable = record is not None and record.get('play_mode', 'unset') != 'unset'
    built = (receipt.get('after') or {}).get('artifact') or {}
    # The file THIS delivery was approved for, not whatever the destination
    # points at now. A destination repointed after the fact is a repair, not a
    # different file to quietly write.
    output_path = (receipt.get('output_resource') or {}).get('path') \
        or ((record or {}).get('output_iso_ref') or {}).get('path')
    saved = False
    if playable and output_path and built.get('digest'):
        saved = playable_iso.digest_file(output_path) == built['digest']
    activation = destinations.effective_activation(record)
    active = activation['status'] in ('not_required', 'verified', 'user_confirmed')
    verified = (receipt.get('phases', {}).get('verify_build', {}).get('status') == 'done')
    complete = bool(in_project and (not playable or (saved and active))
                    and (receipt.get('requested_outcome') == 'prepare' or verified))
    # Restoration: the slots are gone AND the previous playable copy is back.
    before_output = (receipt.get('before') or {}).get('output') or {}
    restored_output = True
    if playable and output_path:
        current = playable_iso.digest_file(output_path)
        if before_output.get('digest'):
            restored_output = current == before_output['digest']
        else:
            restored_output = current != built.get('digest')
    # Restored means both halves: the slots this delivery added are not in the
    # project any more, and the file the user launches is the one from before.
    restored = bool(exists and none_present and restored_output)
    return {'project_exists': exists, 'in_project': in_project, 'members': members,
            'members_found': len(members['found']), 'members_total': len(slots),
            'mismatched': members['conflict'] + members['missing'],
            'playable': playable, 'saved': saved, 'verified': verified,
            'activation': activation, 'active': active, 'complete': complete,
            'restored': restored, 'output_path': output_path}


def _achieved(receipt, state_now):
    """`achieved`, derived from that one reading and from nothing else."""
    prepared = bool(state_now['in_project'])
    exported = bool(prepared and state_now['verified'])
    installed = bool(exported and state_now['playable']
                     and state_now['saved'] and state_now['active'])
    return {'prepared': prepared, 'exported': exported,
            'installed': installed, 'previewed': False}
