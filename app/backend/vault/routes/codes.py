"""
Gecko Codes endpoints, vault side: the vault Codes section.

The catalog itself (storage/codes/metadata.json, lazily seeded from the bundled
community library) lives in vault/catalog/codes.py. The per-project code
routes (what the open project carries, sync, what Slippi Dolphin applies) are
in projects/routes/codes.py and register on this same `codes_bp`.
"""

import logging
import uuid
from datetime import datetime
from flask import Blueprint, request, jsonify

from core.gecko import (
    smart_parse,
    validate_source,
)
from vault.catalog.codes import (
    _clean_name, _entry_header, _load_catalog, _save_catalog, _seed_from_bundled_library,
)

logger = logging.getLogger(__name__)

codes_bp = Blueprint('codes', __name__)


# ---------------------------------------------------------------------------
# Vault endpoints
# ---------------------------------------------------------------------------

@codes_bp.route('/api/mex/codes/vault/list', methods=['GET'])
def list_vault_codes():
    try:
        _seed_from_bundled_library()
        entries = _load_catalog()
        # Self-heal entries seeded before names were cleaned of trailing '[]'.
        healed = False
        for e in entries:
            cleaned = _clean_name(e.get('name'))
            if cleaned and cleaned != e.get('name'):
                e['name'] = cleaned
                healed = True
        if healed:
            _save_catalog(entries)
        categories = sorted({e.get('category') or 'CUSTOM' for e in entries})
        return jsonify({'success': True, 'codes': entries, 'categories': categories})
    except Exception as e:
        logger.error(f'List vault codes error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@codes_bp.route('/api/mex/codes/vault/parse', methods=['POST'])
def parse_pasted_codes():
    """Smart-parse a pasted blob into normalized codes. Preview only."""
    try:
        payload = request.get_json(silent=True) or {}
        result = smart_parse(payload.get('text') or '')
        return jsonify({'success': True, **result})
    except Exception as e:
        logger.error(f'Parse pasted codes error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@codes_bp.route('/api/mex/codes/vault/save', methods=['POST'])
def save_vault_codes():
    """Save parsed/edited codes into the vault. Body: {codes: [...]}.
    Dedupes by header against existing entries; validates every source."""
    try:
        payload = request.get_json(silent=True) or {}
        incoming = payload.get('codes') or []
        if not incoming:
            return jsonify({'success': False, 'error': 'no codes given'}), 400

        entries = _load_catalog()
        existing = {_entry_header(e).lower() for e in entries}
        added, skipped = [], []
        for c in incoming:
            name = (c.get('name') or '').strip()
            if not name:
                skipped.append({'name': '', 'reason': 'missing name'})
                continue
            check = validate_source(c.get('source') or '')
            if not check['ok']:
                skipped.append({'name': name, 'reason': check['error']})
                continue
            category = (c.get('category') or '').strip() or 'CUSTOM'
            entry = {
                'id': str(uuid.uuid4())[:8],
                'name': name,
                'creator': (c.get('creator') or '').strip(),
                'category': category,
                'description': c.get('description') or '',
                'source': c['source'],
                'builtin': False,
                'created': datetime.now().isoformat(),
            }
            key = _entry_header(entry).lower()
            if key in existing:
                skipped.append({'name': name, 'reason': 'already in vault'})
                continue
            existing.add(key)
            entries.append(entry)
            added.append(entry)

        if added:
            _save_catalog(entries)
        return jsonify({'success': True, 'added': added, 'skipped': skipped})
    except Exception as e:
        logger.error(f'Save vault codes error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@codes_bp.route('/api/mex/codes/vault/update/<code_id>', methods=['POST'])
def update_vault_code(code_id):
    """Edit a vault code. Body: any of {name, creator, category, description, source}."""
    try:
        entries = _load_catalog()
        entry = next((e for e in entries if e['id'] == code_id), None)
        if not entry:
            return jsonify({'success': False, 'error': 'Code not found'}), 404
        payload = request.get_json(silent=True) or {}
        if 'source' in payload:
            check = validate_source(payload['source'] or '')
            if not check['ok']:
                return jsonify({'success': False, 'error': check['error']}), 400
            entry['source'] = payload['source']
        for field in ('name', 'creator', 'category', 'description'):
            if field in payload:
                value = (payload[field] or '').strip() if field != 'description' else (payload[field] or '')
                if field == 'name' and not value:
                    return jsonify({'success': False, 'error': 'name cannot be empty'}), 400
                entry[field] = value
        _save_catalog(entries)
        return jsonify({'success': True, 'code': entry})
    except Exception as e:
        logger.error(f'Update vault code error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@codes_bp.route('/api/mex/codes/vault/delete/<code_id>', methods=['POST'])
def delete_vault_code(code_id):
    try:
        entries = _load_catalog()
        remaining = [e for e in entries if e['id'] != code_id]
        if len(remaining) == len(entries):
            return jsonify({'success': False, 'error': 'Code not found'}), 404
        _save_catalog(remaining)
        # Deleted builtins stay deleted: their header remains in seededHeaders,
        # so the lazy seeder never re-inserts them.
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f'Delete vault code error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# The project half of this blueprint (the open project's codes, sync, what
# Slippi Dolphin applies) lives in projects/routes/codes.py and adds its routes
# to codes_bp. Importing it here makes the blueprint complete before anything
# registers it: Flask refuses routes added after registration.
from projects.routes import codes as _project_routes  # noqa: E402,F401
