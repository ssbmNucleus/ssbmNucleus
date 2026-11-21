"""
Shared access to the vault's storage/metadata.json — the single data-access
layer (DAL) for vault state.

Every backend module that reads or writes vault metadata should go through
load_metadata()/save_metadata()/metadata_transaction() instead of hand-rolling
the open/json boilerplate. Routing ALL access through this one module is what
lets the storage backend swap from metadata.json to SQLite in one place behind
a feature flag (see docs/dev/VAULT_SQLITE_MIGRATION.md).
"""

import json
import logging
import os
import tempfile
import threading
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

import file_retry
from .config import STORAGE_PATH

logger = logging.getLogger(__name__)

METADATA_FILE = STORAGE_PATH / 'metadata.json'

# Serializes read-modify-write of the shared vault metadata. Flask runs threaded,
# so concurrent imports (e.g. a multi-file drag firing many /import/file requests
# at once) otherwise race and lose entries — this silently dropped the seeded
# Giga Bowser from the vault. Defined here (next to the data it guards) and
# re-exported from core.state for backwards compatibility with existing imports.
metadata_lock = threading.RLock()


def metadata_write_transaction(func):
    """Serialize a route/service's complete metadata read-change-save cycle.

    This adapter is for existing handlers whose response branches are interleaved
    with mutation logic. New service code should prefer metadata_transaction().
    """
    @wraps(func)
    def locked(*args, **kwargs):
        with metadata_lock:
            return func(*args, **kwargs)
    return locked


class MetadataReadError(RuntimeError):
    """An existing JSON catalog could not be read without data loss."""

    def __init__(self, file: Path, cause: Exception):
        self.file = Path(file)
        super().__init__(f"Existing metadata catalog is unreadable: {self.file}: {cause}")


def _load_json(file: Path, default):
    if not file.exists():
        return default
    try:
        with open(file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to read {file}: {e}")
        raise MetadataReadError(file, e) from e


def _save_json(metadata, file: Path):
    """Atomic JSON write: sibling temp file then os.replace, so a concurrent
    reader never sees a half-written file and a crash mid-write can't truncate
    the vault."""
    with metadata_lock:
        file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=file.name + '.', suffix='.tmp', dir=file.parent)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            file_retry.replace(tmp, file)
        except Exception:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
            raise


def _use_db() -> bool:
    """Whether the vault store is the SQLite backend. Read live from config so
    it stays flippable at runtime and in tests."""
    from . import config
    return getattr(config, 'VAULT_BACKEND', 'json') == 'db'


def load_metadata(default=None, path: Path = None):
    """Load the vault metadata (metadata.json or the SQLite DB, per the flag).

    Returns `default` when the store is missing. Existing unreadable JSON raises
    MetadataReadError so a later mutation cannot overwrite recoverable bytes. Pass e.g.
    default={'characters': {}} to match the shape callers expect. An explicit
    `path` always means "this specific JSON file" (menu-mod catalogs, the duel
    assembler, etc.) and is NEVER redirected to the DB.
    """
    if path is not None:
        return _load_json(path, default)
    if _use_db():
        from . import vault
        blob = vault.load_blob()
        return blob if blob is not None else default
    return _load_json(METADATA_FILE, default)


def save_metadata(metadata, path: Path = None):
    """Persist the vault metadata (metadata.json or the SQLite DB, per the flag).

    JSON writes are atomic (temp + os.replace); DB writes are a single
    transaction. An explicit `path` always writes that specific JSON file and is
    never redirected to the DB.
    """
    if path is not None:
        _save_json(metadata, path)
        return
    if _use_db():
        from . import config, vault
        vault.save_blob(metadata)
        # Dual-write canary: mirror to metadata.json so it stays a live rollback
        # backup and path=-based JSON readers see current data.
        if getattr(config, 'VAULT_DUAL_WRITE', False):
            try:
                _save_json(metadata, METADATA_FILE)
            except Exception as e:
                logger.warning(f"Vault dual-write to {METADATA_FILE} failed: {e}")
        return
    _save_json(metadata, METADATA_FILE)


@contextmanager
def metadata_transaction(default=None, path: Path = None):
    """Locked read-modify-write of a metadata file.

    Acquires `metadata_lock`, loads the metadata, yields it for in-place
    mutation, then writes it back atomically on clean exit. An exception in the
    body propagates WITHOUT saving, so a failed mutation leaves the file
    untouched. This is the canonical primitive for "load, change, save" and
    replaces the per-module `with metadata_lock: read/mutate/write` blocks.

        with metadata_transaction(default={'custom_characters': []}) as data:
            data['custom_characters'].append(entry)
    """
    with metadata_lock:
        data = load_metadata(default=default, path=path)
        yield data
        save_metadata(data, path=path)


def sanitize_skin_metadata(default=None):
    """Repair partial vault skin entries in place, then persist if changed.

    Guards the viewer against half-written skin entries: an import that was
    interrupted or raced between two unlocked read-modify-write cycles could
    leave a skin row with `dat_hash`/`slippi_safe`/`filename` set but no
    `color`/`has_csp`/`has_stock`/`date_added`. Such an entry crashed the
    character page (the viewer indexed a missing `color`). The importer now
    commits entries whole under a lock, but this heals any partial rows left by
    older builds (or a hard crash mid-write) on the next load/serve.

    Runs under metadata_lock and writes atomically only when it actually
    repaired something, so it is idempotent and cheap on a healthy vault.
    Returns the (possibly repaired) metadata dict.

    Repairs, per skin missing `color`:
      - color: derived from the id slug (e.g. "plmrnr-plmrnr05" -> "plmrnr05",
        falling back to the whole id) so the UI always has a label.
      - has_csp / has_stock: recomputed from on-disk `<id>_csp.png` /
        `<id>_stc.png` existence.
      - date_added: backfilled to a stable placeholder so sorts don't blow up.
    """
    # Resolve STORAGE_PATH live from config (tests + a runtime storage move
    # repoint config.STORAGE_PATH; the module-level import would go stale).
    from . import config as _config
    storage_root = getattr(_config, 'STORAGE_PATH', STORAGE_PATH)

    with metadata_lock:
        metadata = load_metadata(default=default)
        if not isinstance(metadata, dict):
            return metadata

        repaired = 0
        for character, char_data in (metadata.get('characters') or {}).items():
            if not isinstance(char_data, dict):
                continue
            char_dir = storage_root / character
            for skin in char_data.get('skins', []) or []:
                # Folder rows and non-skin dict shapes carry no color; skip them.
                if not isinstance(skin, dict) or skin.get('type') == 'folder':
                    continue
                if 'filename' not in skin and 'id' not in skin:
                    continue
                if skin.get('color'):
                    continue  # already complete

                sid = skin.get('id') or ''
                # id slug like "<code>-<code>NN" -> the trailing token; else the id
                derived = sid.rsplit('-', 1)[-1] if sid else ''
                skin['color'] = derived or sid or 'Custom'

                if 'has_csp' not in skin:
                    skin['has_csp'] = (char_dir / f"{sid}_csp.png").exists()
                if 'has_stock' not in skin:
                    skin['has_stock'] = (char_dir / f"{sid}_stc.png").exists()
                skin.setdefault('date_added', '1970-01-01T00:00:00')

                repaired += 1
                logger.warning(
                    "Repaired partial vault skin entry %r (character %r): "
                    "backfilled color=%r has_csp=%s has_stock=%s",
                    sid, character, skin['color'],
                    skin['has_csp'], skin['has_stock'],
                )

        if repaired:
            save_metadata(metadata)
            logger.warning("sanitize_skin_metadata repaired %d partial skin entr%s",
                           repaired, 'y' if repaired == 1 else 'ies')
        return metadata


def custom_character_slug(character):
    """Slug for custom-character pseudo keys.

    Custom characters expose their skins to the canonical skin-editing stack
    under 'custom_characters/<slug>/skins' (added skins) and
    'custom_characters/<slug>/costumes' (bundled costumes, mirrored into a
    costume_meta list + materialized zips). STORAGE_PATH / key is the
    matching directory, so every path-join in the canonical endpoints works
    unchanged.
    """
    if character and character.startswith('custom_characters/') and \
            (character.endswith('/skins') or character.endswith('/costumes')):
        parts = character.split('/')
        if len(parts) == 3 and parts[1]:
            return parts[1]
    return None


def get_char_data(metadata, character):
    """Resolve a character's skins container.

    Canonical characters come from metadata['characters']. Custom-character
    pseudo keys resolve to a view over that character's added_skins or
    costume_meta — the SAME list object, so in-place skin mutations +
    save_metadata persist into the custom character entry.
    """
    if not isinstance(metadata, dict) or not character:
        return None
    chars = metadata.get('characters', {})
    if character in chars:
        return chars[character]
    slug = custom_character_slug(character)
    if slug:
        field = 'costume_meta' if character.endswith('/costumes') else 'added_skins'
        for entry in metadata.get('custom_characters', []):
            if entry.get('slug') == slug:
                return {'skins': entry.setdefault(field, [])}
    return None
