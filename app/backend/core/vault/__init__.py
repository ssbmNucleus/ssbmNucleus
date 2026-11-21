"""
SQLite backend for the vault store (opt-in via the NUCLEUS_VAULT_DB flag).

This is the DB half of the metadata.json -> SQLite migration
(docs/dev/VAULT_SQLITE_MIGRATION.md). core.metadata dispatches load/save to either
the JSON file or this module based on config.VAULT_BACKEND.

Design — "structured where it matters, verbatim everywhere":
  * The collections that suffer the index-based reorder bug (character skins and
    stage variants) — plus, for uniformity, per-character extras and the
    top-level lists — are decomposed into ROWS carrying an explicit `sort_order`.
    That explicit order is what Phase 2 mutates to kill the reorder bug class.
  * Each row stores its entry VERBATIM as `data_json` (not shredded into typed
    columns). Combined with a `__skeleton__` copy of the blob that holds all
    non-decomposed structure with those lists emptied, this guarantees a
    provably lossless round-trip: db_to_blob(blob_to_db(x)) == x for arbitrary
    x, including fields this module never enumerated. The round-trip is asserted
    as a hard gate during migration.

Ordering: integer `sort_order`, initially the source list index; reorders
renumber the affected group in a transaction (Phase 2). `seq` is a stable
per-group primary key so rows never collide even if entries lack unique ids.
"""
import copy
import json
import logging
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .. import config as _config

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# Top-level list collections decomposed into rows (order = list position).
_LIST_COLLECTIONS = ('xdelta', 'custom_characters', 'custom_stages', 'bundles')

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS costumes (
    character TEXT NOT NULL, seq INTEGER NOT NULL,
    sort_order INTEGER NOT NULL, data_json TEXT NOT NULL,
    PRIMARY KEY (character, seq)
);
CREATE TABLE IF NOT EXISTS character_extras (
    character TEXT NOT NULL, extra_type TEXT NOT NULL, seq INTEGER NOT NULL,
    sort_order INTEGER NOT NULL, data_json TEXT NOT NULL,
    PRIMARY KEY (character, extra_type, seq)
);
CREATE TABLE IF NOT EXISTS stage_variants (
    stage TEXT NOT NULL, seq INTEGER NOT NULL,
    sort_order INTEGER NOT NULL, data_json TEXT NOT NULL,
    PRIMARY KEY (stage, seq)
);
CREATE TABLE IF NOT EXISTS top_list_items (
    collection TEXT NOT NULL, seq INTEGER NOT NULL,
    sort_order INTEGER NOT NULL, data_json TEXT NOT NULL,
    PRIMARY KEY (collection, seq)
);
"""


class VaultMigrationError(RuntimeError):
    """Raised when a JSON -> DB migration fails its round-trip validation."""


def db_path(path=None) -> Path:
    """Resolve the vault DB path (config.VAULT_DB_PATH by default, read live).
    Always returns a Path, even if the config value was set to a str."""
    return Path(path) if path else Path(_config.VAULT_DB_PATH)


# ─────────────────────────────── connection ────────────────────────────────

def _connect(path=None) -> sqlite3.Connection:
    p = db_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def _conn(path=None):
    conn = _connect(path)
    try:
        yield conn
    finally:
        conn.close()


def init_db(path=None):
    """Create tables + record schema version if absent (idempotent)."""
    with _conn(path) as conn:
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO kv(key, value_json) VALUES('__schema_version__', ?)",
            (json.dumps(SCHEMA_VERSION),))
        conn.commit()


def is_initialized(path=None) -> bool:
    """True once a blob has been written (a __skeleton__ row exists)."""
    p = db_path(path)
    if not p.exists():
        return False
    try:
        with _conn(p) as conn:
            cur = conn.execute("SELECT 1 FROM kv WHERE key='__skeleton__'")
            return cur.fetchone() is not None
    except sqlite3.Error:
        return False


# ──────────────────────────── blob <-> rows ────────────────────────────────

def _skeletonize(blob):
    """Split a blob into (skeleton, costumes, extras, variants, top_items).

    The skeleton is a deep copy with every decomposed list emptied in place, so
    it preserves all other structure and key PRESENCE exactly. Row tuples carry
    (owner..., seq, sort_order, data_json)."""
    if not isinstance(blob, dict):
        return blob, [], [], [], []
    skel = copy.deepcopy(blob)
    costumes, extras, variants, top = [], [], [], []

    chars = skel.get('characters')
    if isinstance(chars, dict):
        for name, cdata in chars.items():
            if not isinstance(cdata, dict):
                continue
            skins = cdata.get('skins')
            if isinstance(skins, list):
                for i, item in enumerate(skins):
                    costumes.append((name, i, i, json.dumps(item)))
                cdata['skins'] = []
            ex = cdata.get('extras')
            if isinstance(ex, dict):
                for etype, elist in ex.items():
                    if isinstance(elist, list):
                        for i, item in enumerate(elist):
                            extras.append((name, etype, i, i, json.dumps(item)))
                        ex[etype] = []

    stages = skel.get('stages')
    if isinstance(stages, dict):
        for name, sdata in stages.items():
            if not isinstance(sdata, dict):
                continue
            vs = sdata.get('variants')
            if isinstance(vs, list):
                for i, item in enumerate(vs):
                    variants.append((name, i, i, json.dumps(item)))
                sdata['variants'] = []

    for coll in _LIST_COLLECTIONS:
        lst = skel.get(coll)
        if isinstance(lst, list):
            for i, item in enumerate(lst):
                top.append((coll, i, i, json.dumps(item)))
            skel[coll] = []

    return skel, costumes, extras, variants, top


def blob_to_db(blob, path=None):
    """Full-replace the DB contents with `blob` in a single transaction."""
    skel, costumes, extras, variants, top = _skeletonize(blob)
    with _conn(path) as conn:
        conn.executescript(_SCHEMA)
        try:
            conn.execute("BEGIN IMMEDIATE")
            for t in ('costumes', 'character_extras', 'stage_variants', 'top_list_items'):
                conn.execute(f"DELETE FROM {t}")
            conn.execute("DELETE FROM kv WHERE key='__skeleton__'")
            conn.execute("INSERT INTO kv(key, value_json) VALUES('__skeleton__', ?)",
                         (json.dumps(skel),))
            conn.executemany(
                "INSERT INTO costumes(character, seq, sort_order, data_json) VALUES(?,?,?,?)",
                costumes)
            conn.executemany(
                "INSERT INTO character_extras(character, extra_type, seq, sort_order, data_json) "
                "VALUES(?,?,?,?,?)", extras)
            conn.executemany(
                "INSERT INTO stage_variants(stage, seq, sort_order, data_json) VALUES(?,?,?,?)",
                variants)
            conn.executemany(
                "INSERT INTO top_list_items(collection, seq, sort_order, data_json) VALUES(?,?,?,?)",
                top)
            conn.execute(
                "INSERT OR IGNORE INTO kv(key, value_json) VALUES('__schema_version__', ?)",
                (json.dumps(SCHEMA_VERSION),))
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def db_to_blob(path=None):
    """Reconstruct the full blob from the DB, or None if uninitialized."""
    p = db_path(path)
    if not p.exists():
        return None
    with _conn(p) as conn:
        # Establish one read snapshot before the first SELECT. Without this,
        # separate table reads can observe different committed generations.
        conn.execute("BEGIN")
        row = conn.execute("SELECT value_json FROM kv WHERE key='__skeleton__'").fetchone()
        if row is None:
            return None
        blob = json.loads(row[0])
        if not isinstance(blob, dict):
            return blob

        chars = blob.get('characters')
        if isinstance(chars, dict):
            by_char = {}
            for name, dj in conn.execute(
                    "SELECT character, data_json FROM costumes ORDER BY character, sort_order, seq"):
                by_char.setdefault(name, []).append(json.loads(dj))
            by_ex = {}
            for name, etype, dj in conn.execute(
                    "SELECT character, extra_type, data_json FROM character_extras "
                    "ORDER BY character, extra_type, sort_order, seq"):
                by_ex.setdefault((name, etype), []).append(json.loads(dj))
            for name, cdata in chars.items():
                if not isinstance(cdata, dict):
                    continue
                if isinstance(cdata.get('skins'), list):
                    cdata['skins'] = by_char.get(name, [])
                if isinstance(cdata.get('extras'), dict):
                    for etype in cdata['extras']:
                        # Only refill types that were decomposed (list-valued).
                        # Non-list extras (e.g. a '_vanilla_laser' dict) were left
                        # verbatim in the skeleton and must stay untouched.
                        if isinstance(cdata['extras'][etype], list):
                            cdata['extras'][etype] = by_ex.get((name, etype), [])

        stages = blob.get('stages')
        if isinstance(stages, dict):
            by_stage = {}
            for name, dj in conn.execute(
                    "SELECT stage, data_json FROM stage_variants ORDER BY stage, sort_order, seq"):
                by_stage.setdefault(name, []).append(json.loads(dj))
            for name, sdata in stages.items():
                if isinstance(sdata, dict) and isinstance(sdata.get('variants'), list):
                    sdata['variants'] = by_stage.get(name, [])

        by_coll = {}
        for coll, dj in conn.execute(
                "SELECT collection, data_json FROM top_list_items ORDER BY collection, sort_order, seq"):
            by_coll.setdefault(coll, []).append(json.loads(dj))
        for coll in _LIST_COLLECTIONS:
            if isinstance(blob.get(coll), list):
                blob[coll] = by_coll.get(coll, [])

        return blob


# ─────────────────── high-level API used by core.metadata ───────────────────

def load_blob(path=None):
    """Return the vault blob from the DB, or None if uninitialized."""
    return db_to_blob(path)


def save_blob(blob, path=None):
    """Persist the whole vault blob to the DB (full replace, transactional)."""
    blob_to_db(blob, path)


# ─────────────────────────── migration / export ─────────────────────────────

def migrate_json_to_db(json_path=None, db=None, *, backup=True):
    """Import metadata.json into the DB with a backup + round-trip validation.

    Backs up the source JSON, writes it to the DB, then reconstructs the blob
    and asserts it equals the source — raising VaultMigrationError on any
    mismatch so a lossy migration can never silently become authoritative.
    """
    from ..metadata import METADATA_FILE
    jpath = Path(json_path) if json_path else METADATA_FILE
    if not jpath.exists():
        init_db(db)
        return {'migrated': False, 'reason': 'no source json', 'backup': None}

    with open(jpath, 'r', encoding='utf-8') as f:
        source = json.load(f)

    backup_path = None
    if backup:
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = jpath.with_name(jpath.name + f'.bak.{stamp}')
        shutil.copy2(jpath, backup_path)

    blob_to_db(source, db)
    reconstructed = db_to_blob(db)
    if reconstructed != source:
        raise VaultMigrationError(
            "round-trip validation failed: the DB does not reproduce metadata.json")

    logger.info("Vault migrated to SQLite (%s); backup=%s", db_path(db), backup_path)
    return {'migrated': True, 'backup': str(backup_path) if backup_path else None}


def export_db_to_json(json_path=None, db=None):
    """Write the DB contents back out as metadata.json (reversibility/fallback)."""
    from ..metadata import METADATA_FILE, save_metadata
    jpath = Path(json_path) if json_path else METADATA_FILE
    blob = db_to_blob(db)
    if blob is None:
        return False
    save_metadata(blob, path=jpath)
    return True


def ensure_migrated(json_path=None, db=None):
    """Make the DB backend safe to use: if selected but not yet built, migrate
    metadata.json into it (backup + round-trip validation). No-op once the DB is
    initialized. Call at startup when config.VAULT_BACKEND == 'db'; on failure
    the caller should fall back to the JSON backend so the vault never appears
    empty."""
    if is_initialized(db):
        return {'migrated': False, 'reason': 'already initialized'}
    return migrate_json_to_db(json_path, db, backup=True)
