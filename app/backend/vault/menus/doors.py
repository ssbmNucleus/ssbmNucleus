"""
CSS door texture mods: the catalog and importing a door picture (stored as PNG).
"""

import json
import uuid
import logging
import file_retry
from datetime import datetime
from vault.menus.store import DOORS_METADATA, DOORS_PATH

logger = logging.getLogger(__name__)


def _load_doors_metadata():
    # NOTE: unlike the dict-shaped catalogs (icon grid / backgrounds), this is
    # a bare list and a corrupt metadata.json deliberately raises (surfacing as
    # a 500 from the routes) rather than silently returning an empty list — so
    # it isn't folded into core.metadata.load_metadata.
    if DOORS_METADATA.exists():
        return json.loads(DOORS_METADATA.read_text())
    return []


def _save_doors_metadata(mods):
    file_retry.retry_locked(DOORS_METADATA.write_text, json.dumps(mods, indent=2))


def _as_png(data):
    """Door textures are stored as door.png. Re-encode anything that is not
    already a PNG (a .jpg / .webp drop) so the HSDRaw importer always gets
    the format the filename promises. Returns the bytes unchanged when they
    are already PNG or cannot be decoded (the importer reports that later)."""
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return data
    try:
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.open(io.BytesIO(data)).convert('RGBA').save(buf, format='PNG')
        return buf.getvalue()
    except Exception as e:
        logger.warning(f'door image re-encode failed, storing as-is: {e}')
        return data


def import_door_image(data, name, description=''):
    """Store one image as a CSS door mod. Returns the mod dict (with imageUrl).
    Shared by the dedicated route and the unified /import/file dispatcher."""
    mod_id = str(uuid.uuid4())[:8]
    mod_dir = DOORS_PATH / mod_id
    mod_dir.mkdir(parents=True, exist_ok=True)
    (mod_dir / 'door.png').write_bytes(_as_png(data))

    mod = {
        'id': mod_id,
        'name': (name or '').strip() or 'Door',
        'created': datetime.now().isoformat(),
    }
    if description:
        mod['description'] = description

    mods = _load_doors_metadata()
    mods.append(mod)
    _save_doors_metadata(mods)
    logger.info(f"[OK] Imported door mod: {mod['name']} ({mod_id})")

    out = dict(mod)
    out['imageUrl'] = f'/api/mex/menus/css/doors/image/{mod_id}'
    return out
