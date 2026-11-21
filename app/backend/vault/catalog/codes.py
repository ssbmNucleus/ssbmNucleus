"""
The vault's Gecko code catalog, outside the routes.

A doors-style side catalog at storage/codes/metadata.json holding small text
entries (hex inline, no per-entry directories), lazily seeded from the bundled
49-code community library (core.config.BUNDLED_CODES_INI).

    storage/codes/
        metadata.json    # bare list of code entries (corrupt file -> 500)
        seed_state.json  # {"md5": ..., "seededHeaders": [...]} seed bookkeeping

No routes. The vault Codes routes (vault/routes/codes.py) list and edit it; the
project code routes (projects/routes/codes.py) read it to flag which of a
project's codes are already in the vault.
"""

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime

import file_retry
from core.config import STORAGE_PATH, BUNDLED_CODES_INI
from core.gecko import header, parse_ini, validate_source

logger = logging.getLogger(__name__)


def _codes_dir():
    return STORAGE_PATH / 'codes'


def _load_catalog():
    # Bare-list catalog, doors-style: a corrupt metadata.json deliberately
    # raises (surfacing as a 500) rather than silently returning [].
    meta = _codes_dir() / 'metadata.json'
    if meta.exists():
        return json.loads(meta.read_text(encoding='utf-8'))
    return []


def _save_catalog(entries):
    d = _codes_dir()
    d.mkdir(parents=True, exist_ok=True)
    file_retry.retry_locked((d / 'metadata.json').write_text, json.dumps(entries, indent=2), encoding='utf-8')


def _ini_name(entry):
    """The name an entry uses inside a project's codes.ini. Builtin library
    codes keep their 'CATEGORY | Name' prefix so the ini stays byte-compatible
    with what MexManager's own GUI shows for the same library."""
    if entry.get('builtin') and entry.get('category'):
        return f"{entry['category']} | {entry['name']}"
    return entry['name']


def _entry_header(entry):
    return header(_ini_name(entry), entry.get('creator', ''))


def _split_category(name):
    """'QOL | Better Camera' -> ('QOL', 'Better Camera'); no prefix -> ('CUSTOM', name)."""
    if ' | ' in name:
        cat, rest = name.split(' | ', 1)
        return cat.strip(), rest.strip()
    return 'CUSTOM', name.strip()


def _clean_name(name):
    """Drop a literal trailing '[]' — the bundled library writes empty creator
    brackets ('Use Save Banner #1 []') and the loader keeps them in the name
    (its creator regex needs at least one char between brackets)."""
    return re.sub(r'\s*\[\s*\]$', '', name or '').strip()


# ---------------------------------------------------------------------------
# Seeding from the bundled library
# ---------------------------------------------------------------------------

def _seed_state_path():
    return _codes_dir() / 'seed_state.json'


def _seed_from_bundled_library():
    """Insert bundled-library codes the catalog has never seen. Runs lazily on
    vault list. seededHeaders is an ever-seeded set: a user-deleted builtin is
    never re-inserted, and a future library update only adds new codes."""
    if not BUNDLED_CODES_INI.exists():
        return
    raw = BUNDLED_CODES_INI.read_bytes()
    md5 = hashlib.md5(raw).hexdigest()

    state_path = _seed_state_path()
    state = {'md5': None, 'seededHeaders': []}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding='utf-8'))
        except Exception:
            logger.warning('codes seed_state.json unreadable; reseeding conservatively')
    if state.get('md5') == md5:
        return

    entries = _load_catalog()
    existing = {_entry_header(e).lower() for e in entries}
    seeded = {h.lower() for h in state.get('seededHeaders', [])}

    added = 0
    for code in parse_ini(raw.decode('utf-8', 'replace')):
        full_header = header(code['name'], code['creator'])
        key = full_header.lower()
        if key in seeded:
            continue
        seeded.add(key)
        if key in existing:
            continue
        if not validate_source(code['source'])['ok']:
            logger.warning(f'bundled code does not validate, skipping: {full_header}')
            continue
        category, bare_name = _split_category(code['name'])
        entries.append({
            'id': str(uuid.uuid4())[:8],
            'name': _clean_name(bare_name),
            'creator': code['creator'],
            'category': category,
            'description': code['description'],
            'source': code['source'],
            'builtin': True,
            'created': datetime.now().isoformat(),
        })
        added += 1

    if added:
        _save_catalog(entries)
    _codes_dir().mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        'md5': md5,
        'seededHeaders': sorted(seeded),
    }, indent=2), encoding='utf-8')
    if added:
        logger.info(f'Seeded {added} gecko codes from the bundled library')
