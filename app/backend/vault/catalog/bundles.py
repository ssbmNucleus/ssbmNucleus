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
from core.safe_extract import new_budget, preflight_zip

logger = logging.getLogger(__name__)

# What a bundle may hold. The patch rebuilds one disc (a GameCube ISO is 1.4 GB); a texture is one PNG.
BUNDLE_MAX_BYTES = 8 * 1024 ** 3          # every member, uncompressed
BUNDLE_MAX_MEMBER_BYTES = 4 * 1024 ** 3
BUNDLE_MAX_MEMBERS = 20_000
TEXTURE_MAX_BYTES = 128 * 1024 ** 2
MANIFEST_MAX_BYTES = 1024 ** 2
IMAGE_MAX_BYTES = 32 * 1024 ** 2


def _bundle_build_name(manifest):
    value = manifest.get('build_name', 'imported-mod')
    return validate_path_segment(value, field='bundle build_name')


def check_bundle(zf):
    """Check every member of an open bundle before anything is read or written: each name stays inside the
    folder it is written to (no drive, alternate data stream, '..', device name or collision:
    core.safe_extract.preflight_zip), and the sizes are within the limits above. Returns {name: PreparedMember}.
    Raises ValueError (UnsafeArchiveMember, ArchiveBudgetExceeded) for a bundle that is not."""
    budget = new_budget(max_bytes=BUNDLE_MAX_BYTES, max_members=BUNDLE_MAX_MEMBERS,
                        max_member_bytes=BUNDLE_MAX_MEMBER_BYTES,
                        message='This bundle is larger than a bundle can be. Nothing was read from it.')
    members = {member.name: member for member in preflight_zip(zf, budget=budget)}
    textures = texture_members(members)
    for name, member in members.items():
        cap = MANIFEST_MAX_BYTES if name == 'manifest.json' else TEXTURE_MAX_BYTES if name in textures else None
        if cap is not None and member.size > cap:
            raise ValueError(f'{name} is larger than {cap // (1024 * 1024)} MB')
    return members


def texture_members(members):
    """The bundle's texture pack: the PNGs directly in textures/, as {member name: the file name it is loaded as}."""
    return {name: validate_path_segment(member.parts[1], field='texture name')
            for name, member in members.items()
            if not member.is_dir and len(member.parts) == 2 and member.parts[0] == 'textures'
            and member.parts[1].lower().endswith('.png')}


def read_member(zf, name, cap):
    """A small member's bytes: never more than `cap`, whatever its header says."""
    if zf.getinfo(name).file_size > cap:
        raise ValueError(f'{name} is larger than {cap // (1024 * 1024)} MB')
    with zf.open(name) as member:
        data = member.read(cap + 1)
    if len(data) > cap:
        raise ValueError(f'{name} is larger than {cap // (1024 * 1024)} MB')
    return data


def read_manifest(zf):
    """The bundle's manifest.json, read within MANIFEST_MAX_BYTES."""
    manifest = json.loads(read_member(zf, 'manifest.json', MANIFEST_MAX_BYTES))
    if not isinstance(manifest, dict):
        raise ValueError('manifest.json is not an object')
    return manifest


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
    # Validate package-controlled names, sizes and destinations before creating any Vault files.
    try:
        with zipfile.ZipFile(src_path, 'r') as zf:
            members = check_bundle(zf)
            manifest = read_manifest(zf)
            _bundle_build_name(manifest)
    except Exception as e:
        raise ValueError(f'Invalid bundle: {e}')
    texture_count = len(texture_members(members))

    bundle_id = str(uuid.uuid4())[:8]
    bundle_path = BUNDLE_PATH / f"{bundle_id}.ssbm"
    shutil.copyfile(str(src_path), str(bundle_path))

    file_size = bundle_path.stat().st_size

    # Extract image if present in bundle (a larger one is left out, not the bundle)
    try:
        with zipfile.ZipFile(bundle_path, 'r') as zf:
            if 'image.png' in members:
                image_data = read_member(zf, 'image.png', IMAGE_MAX_BYTES)
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
