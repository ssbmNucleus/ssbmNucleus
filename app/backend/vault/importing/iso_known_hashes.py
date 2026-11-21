"""
Costumes an ISO scan already knows: DAT hashes of the skins in the vault (with
their saved previews) and of the vanilla costumes, and the hash a DAT has once
the Slippi auto-fix is applied, so a scan can mark duplicates and skip vanilla.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import quote
from core.config import STORAGE_PATH, VANILLA_ASSETS_DIR
from dat_processor import validate_for_slippi

logger = logging.getLogger(__name__)


# ---------- Helpers ----------

def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _md5_file(path: str | Path) -> str:
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _vault_preview(character: str, skin: dict) -> Optional[dict]:
    skin_id = skin.get('id')
    if not skin_id:
        return None
    csp = skin.get('csp_filename') or f'{skin_id}_csp.png'
    return {
        'id': skin_id,
        'character': character,
        'name': skin.get('name') or skin.get('color') or skin_id,
        'csp_url': f'/storage/{quote(character, safe="")}/{quote(csp, safe="")}'
        if (STORAGE_PATH / character / csp).is_file() else None,
    }


def _load_vault_hashes() -> dict[str, Optional[dict]]:
    """Map DAT hashes to saved vault previews for skins the user already has — both the *original* hash
    saved at import time and the actual stored zip contents.

    When `import_character_costume` runs with auto_fix=True (the default for
    scan-imports), metadata.json's `dat_hash` field records the PRE-fix hash
    of the source DAT, but the zip on disk stores the slippi-FIXED bytes.
    Those have different hashes. So when a modder distributes a skin in
    slippi-safe form and the user already has it, scanning that ISO would
    leak it as 'new' unless we also include the stored-zip hash. Solution:
    walk every storage/<Char>/*.zip, hash the inner DAT, and index the same saved portrait.
    Cheap one-shot at scan start.
    """
    out: dict[str, Optional[dict]] = {}
    previews = {}
    try:
        from core.metadata import load_metadata
        metadata = load_metadata(default={}) or {}
        for character, char_data in metadata.get('characters', {}).items():
            for skin in char_data.get('skins', []):
                preview = _vault_preview(character, skin)
                if preview:
                    previews[(character, skin['id'])] = preview
                    if skin.get('filename'):
                        previews[(character, Path(skin['filename']).stem)] = preview
                h = skin.get('dat_hash')
                if h:
                    out[h] = preview
    except Exception as e:
        logger.warning(f"[iso-scan][vault] metadata.json read failed: {e}")

    metadata_count = len(out)

    # Layer in hashes of the actual DAT bytes stored in each vault zip. These
    # may differ from metadata's dat_hash when auto_fix changed the file at
    # import time.
    import zipfile as _zipfile
    zip_count = 0
    if STORAGE_PATH.exists():
        for char_dir in STORAGE_PATH.iterdir():
            if not char_dir.is_dir() or char_dir.name in ('xdelta', 'das', 'bundles'):
                continue
            for zip_path in char_dir.glob('*.zip'):
                try:
                    with _zipfile.ZipFile(zip_path, 'r') as zf:
                        for inner in zf.namelist():
                            lower = inner.lower()
                            if lower.endswith(('.dat', '.usd')) and 'plco' not in lower:
                                preview = previews.get((char_dir.name, zip_path.stem))
                                if preview is None:
                                    preview = _vault_preview(char_dir.name, {'id': zip_path.stem})
                                out.setdefault(hashlib.md5(zf.read(inner)).hexdigest(), preview)
                                zip_count += 1
                                break  # one DAT per costume zip
                except Exception as e:
                    logger.debug(f"[iso-scan][vault] could not hash {zip_path}: {e}")

    logger.info(
        f"[iso-scan][vault] loaded {len(out)} unique hashes "
        f"({metadata_count} from metadata.json dat_hash, "
        f"{zip_count} from vault zip contents)"
    )
    return out


# Known vanilla DAT hashes that aren't always present in user vanilla folders.
# The first-run vanilla extraction occasionally drops costumes whose data is
# split across the `.dat` and `.usd` localized variants (Red Falcon is the
# known case: `utility/assets/vanilla/C. Falcon/PlCaRe/` exists with csp.png
# and stock.png but no PlCaRe.dat). Without this supplemental set, those
# costumes leak through every scan as bogus "new" skins because their ISO
# hash has no match in the vanilla folder.
_SUPPLEMENTAL_VANILLA_HASHES = {
    'ce3dfba030d0ecbeeaf0c288aca29f0b': 'PlCaRe.dat (Red Falcon, vanilla)',
}


def _load_vanilla_hashes() -> set[str]:
    out = set()
    if not VANILLA_ASSETS_DIR.exists():
        return out
    for dat in VANILLA_ASSETS_DIR.rglob('*.dat'):
        try:
            out.add(_md5_file(dat))
        except Exception:
            pass

    # Layer on the supplemental hashes and report which slots they cover so
    # gaps in the user's vanilla folder are visible at scan start.
    for h, label in _SUPPLEMENTAL_VANILLA_HASHES.items():
        if h not in out:
            out.add(h)
            logger.info(
                f"[iso-scan][vanilla] using supplemental hash for {label} — "
                f"missing from {VANILLA_ASSETS_DIR}"
            )

    # Warn for any vanilla subfolder named `PlXxYy` that has no DAT in it.
    # These slots will leak as 'new skins' in scans of any modded ISO until
    # the user re-runs vanilla extraction or we add the hash above.
    try:
        for char_dir in VANILLA_ASSETS_DIR.iterdir():
            if not char_dir.is_dir():
                continue
            for slot_dir in char_dir.iterdir():
                if not slot_dir.is_dir():
                    continue
                if not slot_dir.name.startswith('Pl') or len(slot_dir.name) != 6:
                    continue
                if not any(slot_dir.glob('*.dat')):
                    logger.warning(
                        f"[iso-scan][vanilla] {char_dir.name}/{slot_dir.name}/ "
                        f"has no .dat — that slot will leak as new in scans"
                    )
    except OSError:
        pass

    return out


def _slippi_fixed_hash(dat_path: str) -> Optional[str]:
    """Apply Slippi auto-fix to a copy of the DAT and hash the result.

    Returns the fixed-file MD5, or None if no fix was applied / on error.
    """
    try:
        with tempfile.NamedTemporaryFile(suffix='.dat', delete=False) as tmp:
            shutil.copy2(dat_path, tmp.name)
            tmp_path = tmp.name
        try:
            res = validate_for_slippi(tmp_path, auto_fix=True)
            if res.get('fix_applied'):
                return _md5_file(tmp_path)
            return None
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    except Exception:
        return None
