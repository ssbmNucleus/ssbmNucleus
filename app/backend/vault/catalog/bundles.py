"""
The vault's .ssbm bundles, outside the routes: where they are stored, their
index in the shared vault metadata, and the manifest's build name check.

    storage/bundles/
        <bundle_id>.ssbm    # the bundle (xdelta patch + texture pack + manifest)
        <bundle_id>.png     # optional image

No routes. import_bundle_file stores an uploaded bundle (the vault bundle
routes and the unified import use it). The vault bundle routes
(vault/routes/bundles.py) list, edit and import bundles; the build routes
(projects/routes/bundles.py) export, install and play them.
"""

import json
import logging
import shutil
import uuid
import zipfile
from datetime import datetime

from core.config import STORAGE_PATH
from core.metadata import load_metadata, metadata_transaction
from core.path_safety import validate_path_segment

logger = logging.getLogger(__name__)


def _bundle_build_name(manifest):
    value = manifest.get('build_name', 'imported-mod')
    return validate_path_segment(value, field='bundle build_name')


# Bundle storage path
BUNDLE_PATH = STORAGE_PATH / "bundles"
BUNDLE_PATH.mkdir(parents=True, exist_ok=True)


def load_bundle_metadata():
    """Load the bundles list from the shared vault metadata (via the DAL)."""
    return (load_metadata() or {}).get('bundles', [])


def save_bundle_metadata(bundles_list):
    """Save the bundles list into the SHARED vault metadata.

    The vault metadata also holds custom_characters/stages; an unguarded
    read-modify-write here can clobber those (the same race that dropped the
    seeded Giga Bowser). metadata_transaction holds the shared lock and writes
    atomically. See [[metadata-concurrency]]."""
    with metadata_transaction(default={'version': '1.0', 'characters': {}, 'stages': {}}) as metadata:
        metadata['bundles'] = bundles_list
    logger.info(f"Saved {len(bundles_list)} bundles to vault metadata")


def _append_bundle(entry):
    """Thread-safe append of one bundle entry: the load-append-save runs in one
    locked transaction so two concurrent bundle exports can't lose each other's
    entry (read-modify-write race)."""
    with metadata_transaction(default={'version': '1.0', 'characters': {}, 'stages': {}}) as metadata:
        metadata.setdefault('bundles', []).append(entry)


def import_bundle_file(src_path, fallback_name):
    """Copy a .ssbm bundle into storage and register it (does NOT install).
    Returns {'bundle_id', 'name'}. Raises ValueError on an invalid bundle.
    Shared by the dedicated route and the unified /import/file dispatcher."""
    # Validate package-controlled destinations before creating any Vault files.
    try:
        with zipfile.ZipFile(src_path, 'r') as zf:
            manifest = json.loads(zf.read('manifest.json'))
            _bundle_build_name(manifest)
    except Exception as e:
        raise ValueError(f'Invalid bundle: {e}')

    bundle_id = str(uuid.uuid4())[:8]
    bundle_path = BUNDLE_PATH / f"{bundle_id}.ssbm"
    shutil.copyfile(str(src_path), str(bundle_path))

    file_size = bundle_path.stat().st_size

    # Count textures in bundle
    texture_count = 0
    try:
        with zipfile.ZipFile(bundle_path, 'r') as zf:
            texture_count = len([n for n in zf.namelist() if n.startswith('textures/') and n.endswith('.png')])
    except:
        pass

    # Extract image if present in bundle
    try:
        with zipfile.ZipFile(bundle_path, 'r') as zf:
            if 'image.png' in zf.namelist():
                image_data = zf.read('image.png')
                image_dest = BUNDLE_PATH / f"{bundle_id}.png"
                with open(image_dest, 'wb') as f:
                    f.write(image_data)
                logger.info(f"Extracted image from bundle: {image_dest}")
    except Exception as e:
        logger.warning(f"Failed to extract image from bundle: {e}")

    name = manifest.get('name', fallback_name)
    bundles = load_bundle_metadata()
    bundles.append({
        'id': bundle_id,
        'name': name,
        'description': manifest.get('description', ''),
        'size': file_size,
        'size_mb': round(file_size / (1024 * 1024), 2),
        'texture_count': texture_count,
        'created': datetime.now().isoformat()
    })
    save_bundle_metadata(bundles)

    logger.info(f"[OK] Imported bundle to storage: {bundle_id} - {name}")
    return {'bundle_id': bundle_id, 'name': name}
