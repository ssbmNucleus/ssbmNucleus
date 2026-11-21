"""Receipts of finished download operations: what one download+import created, whether it still
exists, and the stored result a retry of the same request returns instead of importing twice."""

import time


# Import types whose importer mints a fresh UUID and catalog entry every time
# instead of recognising the duplicate. Costumes, stages and effects do detect
# theirs, so repeating one of those is answered honestly by the importer with
# `skipped_count`; for everything else there is nothing between a repeat and a
# second copy but this ledger (2026-09-22 security review, 6). `multi` is a
# CONTAINER of those imports, so it belongs here too -- excluding it let a
# retried container recreate every menu and package inside it.
NO_DUPLICATE_DETECTION = frozenset({
    'menu_mod', 'bundle', 'custom_character', 'custom_stage', 'patch', 'multi',
})

# How long a receipt protects a retry. Long enough to cover a lost response, a
# partial batch and a restart; not a permanent ban on downloading a mod twice.
RECEIPT_TTL_SECONDS = 30 * 24 * 3600


def _destination_ids(payload):
    """What this import actually created, as {kind, id} rows.

    A receipt that only says "one menu was imported" cannot tell a recovery
    from a second copy, and cannot notice that the user deleted the thing it
    is protecting.
    """
    rows = []
    for mod in payload.get('mods') or []:
        if isinstance(mod, dict) and (mod.get('id') or mod.get('name')):
            rows.append({'kind': 'menu', 'id': str(mod.get('id') or mod.get('name'))[:120]})
    if payload.get('bundle_id'):
        rows.append({'kind': 'bundle', 'id': str(payload['bundle_id'])[:120]})
    character = payload.get('character')
    if isinstance(character, dict) and character.get('slug'):
        rows.append({'kind': 'custom_character', 'id': str(character['slug'])[:120]})
    stage = payload.get('stage')
    if isinstance(stage, dict) and (stage.get('slug') or stage.get('id')):
        rows.append({'kind': 'custom_stage', 'id': str(stage.get('slug') or stage['id'])[:120]})
    for entry in payload.get('custom_stages') or []:
        if isinstance(entry, dict) and (entry.get('slug') or entry.get('id')):
            rows.append({'kind': 'custom_stage', 'id': str(entry.get('slug') or entry['id'])[:120]})
    for patch in payload.get('patches') or []:
        if isinstance(patch, dict) and patch.get('id'):
            rows.append({'kind': 'patch', 'id': str(patch['id'])[:120]})
    seen, unique = set(), []
    for row in rows:
        marker = (row['kind'], row['id'])
        if marker not in seen:
            seen.add(marker)
            unique.append(row)
    return unique


def _destination_present(row, data):
    """Whether a recorded destination still exists. None when unknowable."""
    kind, item = row.get('kind'), row.get('id')
    if kind == 'custom_character':
        return any(c.get('slug') == item for c in data.get('custom_characters') or [])
    if kind == 'custom_stage':
        return any((c.get('slug') or c.get('id')) == item
                   for c in data.get('custom_stages') or [])
    if kind == 'bundle':
        return any(b.get('id') == item for b in data.get('bundles') or [])
    return None   # menus and patches live in their own catalogs


def _completed_operation(key):
    """The stored result of this exact operation, or None if it may run again.

    A receipt stops protecting a retry once what it created is gone: deleting
    the imported menu and asking for it again is a new import, not a repeat.
    """
    from core.metadata import load_metadata
    data = load_metadata(default={}) or {}
    entry = (data.get('_website_operations') or {}).get(key)
    if not isinstance(entry, dict) or not isinstance(entry.get('result'), dict):
        return None
    if time.time() - float(entry.get('at') or 0) > RECEIPT_TTL_SECONDS:
        return None
    verdicts = [_destination_present(row, data) for row in entry.get('destinations') or []]
    if verdicts and not any(v is not False for v in verdicts):
        return None   # everything it claims to have created has been deleted
    result = dict(entry['result'])
    result['repeat_of_completed_download'] = True
    result['vault_changed'] = False
    result['destinations'] = entry.get('destinations') or []
    result['note'] = ('This exact download already completed and its item is in your vault, '
                      'so it was not downloaded again. Import the file yourself if you really '
                      'want a second copy. ' + str(result.get('note') or ''))[:2000]
    return result


def _record_operation(key, result, payload, content=None):
    """Record this operation's completion and what it created, in one write.

    Called from INSIDE the import lock, immediately after the importer
    returns, so a concurrent request cannot slip between the lookup and the
    record. Receipts expire by age rather than by count: evicting the oldest
    entries was evicting exactly the recovery protection this exists for.
    """
    from core.metadata import metadata_transaction
    keep = {field: result.get(field) for field in
            ('imported_count', 'skipped_count', 'fixed_count', 'note', 'detected',
             'imported_items', 'imported_stages', 'imported_effects', 'website_mods')
            if result.get(field) is not None}
    entry = {'at': time.time(), 'result': keep,
             'destinations': _destination_ids(payload),
             'content_sha256': (content or {}).get('sha256'),
             'detected_type': (content or {}).get('type')}
    with metadata_transaction(default={}) as data:
        ledger = data.setdefault('_website_operations', {})
        ledger[key] = entry
        cutoff = time.time() - RECEIPT_TTL_SECONDS
        for stale in [k for k, v in ledger.items()
                      if float((v or {}).get('at') or 0) < cutoff]:
            ledger.pop(stale, None)
