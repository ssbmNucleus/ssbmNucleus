"""Persistent website provenance, checked against the current vault catalog."""
import json
import sqlite3
from contextlib import closing

from core import config
from core.metadata import load_metadata, metadata_transaction


def _references(result):
    return [*({'kind': 'costume', 'owner': item['character'], 'id': item['id']}
              for item in result.get('imported_items', []) if item.get('character') and item.get('id')),
            *({'kind': 'stage', 'owner': item['folder'], 'id': item['id']}
              for item in result.get('imported_stages', []) if item.get('folder') and item.get('id')),
            *({'kind': 'effect', 'owner': item['character'], 'effect_type': item['effect_type'], 'id': item['id']}
              for item in result.get('imported_effects', []) if item.get('character') and item.get('id'))]


def _merge(ledger, post_id, references):
    if not references:
        return
    existing = ledger.setdefault(str(post_id), [])
    for reference in references:
        if reference not in existing:
            existing.append(reference)


def record_import(post_id, result, existing=()):
    references = [*_references(result), *existing]
    if references:
        with metadata_transaction(default={}) as data:
            _merge(data.setdefault('_website_imports', {}), post_id, references)


def recover_history():
    """One-time recovery of exact item IDs from pre-provenance chat receipts.

    Copy references out of chat history so deleting a conversation cannot erase
    ownership. Never infer ownership from titles or a success/count alone.
    """
    if (load_metadata(default={}) or {}).get('_website_imports_history_v1'):
        return
    recovered = {}
    path = config.STORAGE_PATH / 'assistant' / 'chats.db'
    if path.is_file():
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
            for (raw,) in conn.execute('SELECT messages FROM chats'):
                for message in json.loads(raw):
                    for tool in message.get('tools', []):
                        result = tool.get('result') or {}
                        if tool.get('name') == 'download_website_mod':
                            for mod in result.get('website_mods', []):
                                _merge(recovered, mod['post_id'], _references(result))
                        elif tool.get('name') == 'download_website_mods':
                            for entry in result.get('downloads', []):
                                _merge(recovered, entry['post_id'], _references(entry.get('result') or {}))
    with metadata_transaction(default={}) as data:
        ledger = data.setdefault('_website_imports', {})
        for post_id, references in recovered.items():
            _merge(ledger, post_id, references)
        data['_website_imports_history_v1'] = True


def vault_status(post_ids):
    data = load_metadata(default={}) or {}
    live = {('costume', owner, item.get('id'))
            for owner, character in data.get('characters', {}).items()
            for item in character.get('skins', [])
            if item.get('type') != 'folder' and item.get('visible') is not False}
    live.update(('stage', owner, item.get('id'))
                for owner, stage in data.get('stages', {}).items()
                for item in stage.get('variants', []))
    live.update(('effect', owner, item.get('id'))
                for owner, character in data.get('characters', {}).items()
                for items in character.get('extras', {}).values() if isinstance(items, list)
                for item in items)
    ledger = data.get('_website_imports', {})
    # Unknown provenance is distinct from a linked import that was deleted.
    # Preserve legacy receipt behavior for formats without stable vault IDs.
    return {str(post_id): (any((ref['kind'], ref['owner'], ref['id']) in live
                              for ref in ledger[str(post_id)]) if str(post_id) in ledger else None)
            for post_id in post_ids}
