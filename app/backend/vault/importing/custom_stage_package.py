"""
Custom stage packages into the vault.

A MexManager-style stage package (ZIP: stage.json at the root, the stage
DAT(s), optional icon.png / banner.png and portable .hps music) becomes a
vault entry under storage/custom_stages/<slug>/ plus a `custom_stages`
metadata row. Every reference in stage.json is validated before anything is
written.

No routes. Shared by the Custom Stages routes (vault/routes/custom_stages.py),
the unified /import/file dispatcher, stage slots, and the raw vanilla-stage
importer (vanilla_stage_import.py).
"""
import json
import logging
import re
import zipfile
from datetime import datetime
from pathlib import Path

from core.config import STORAGE_PATH
from core.metadata import metadata_transaction
from core.path_safety import validate_path_segment

logger = logging.getLogger(__name__)

CUSTOM_STAGES_PATH = STORAGE_PATH / 'custom_stages'

# Default vault shape a stage import expects from a missing/empty metadata file.
DEFAULT_META = {'characters': {}, 'stages': {}, 'custom_stages': []}


def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip()


def make_slug(name):
    slug = sanitize_filename(name).lower().replace(' ', '-')
    slug = re.sub(r'-+', '-', slug).strip('-')
    if not slug:
        slug = 'custom-stage'
    return slug


def dedupe_slug(slug, root=None):
    """`slug`, or `slug-N` for the first N not taken under `root` (default:
    the vault's custom_stages folder)."""
    root = CUSTOM_STAGES_PATH if root is None else root
    if not (root / slug).exists():
        return slug
    counter = 2
    while (root / f"{slug}-{counter}").exists():
        counter += 1
    return f"{slug}-{counter}"


def validate_stage_package_references(stage_meta, member_names):
    """Reject stage.json references that could escape the native workspace."""
    referenced = []
    file_name = stage_meta.get('fileName')
    if file_name is not None:
        referenced.append(file_name)
    additional = stage_meta.get('additionalFiles', [])
    if not isinstance(additional, list):
        raise ValueError('stage.json additionalFiles must be a list')
    referenced.extend(additional)
    for value in referenced:
        validate_path_segment(value, field='stage file reference')
        if value not in member_names:
            raise ValueError(f'stage file reference is missing from ZIP: {value}')


def import_custom_stage_zip_bytes(zip_data, fallback_name):
    """Import a custom stage package (zip bytes) into the vault.
    Returns the metadata entry. Raises ValueError on an invalid package.
    Shared by the dedicated route, the unified /import/file dispatcher, stage
    slots and the raw vanilla-stage importer."""
    import io
    with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
        names = zf.namelist()

        stage_json_path = None
        dat_files = []
        icon_path = None
        banner_path = None

        for name in names:
            basename = name.split('/')[-1].lower()
            if basename == 'stage.json':
                stage_json_path = name
            elif basename.endswith('.dat'):
                dat_files.append(name)
            elif basename == 'icon.png':
                icon_path = name
            elif basename == 'banner.png':
                banner_path = name

        if not stage_json_path:
            raise ValueError('ZIP must contain a stage.json file')
        if stage_json_path != 'stage.json':
            raise ValueError('stage.json must be at the ZIP root')
        if not dat_files:
            raise ValueError('ZIP must contain at least one .dat file')

        stage_meta = json.loads(zf.read(stage_json_path))
        if not isinstance(stage_meta, dict):
            raise ValueError('stage.json must contain an object')
        validate_stage_package_references(stage_meta, set(names))
        portable_playlist = []
        playlist_data = stage_meta.get('playlist')
        if playlist_data is None:
            playlist_data = {}
        if not isinstance(playlist_data, dict):
            raise ValueError('stage.json playlist must be an object')
        playlist_entries = playlist_data.get('entries') or []
        if not isinstance(playlist_entries, list):
            raise ValueError('stage.json playlist entries must be a list')
        for playlist_entry in playlist_entries:
            if not isinstance(playlist_entry, dict):
                continue
            file_name = playlist_entry.get('fileName')
            if not file_name:
                continue
            validate_path_segment(file_name, field='stage music reference')
            if not file_name.lower().endswith('.hps'):
                raise ValueError('stage music reference must be an .hps file')
            if file_name not in names:
                raise ValueError(f'stage music reference is missing from ZIP: {file_name}')
            try:
                chance = max(0, min(100, int(playlist_entry.get('chanceToPlay', 50))))
            except (TypeError, ValueError):
                chance = 50
            portable_playlist.append((
                file_name,
                {'name': (playlist_entry.get('name') or Path(file_name).stem),
                 'chance': chance},
            ))
        stage_name = stage_meta.get('name', fallback_name)

        slug = dedupe_slug(make_slug(stage_name))
        stage_dir = CUSTOM_STAGES_PATH / slug
        stage_dir.mkdir(parents=True, exist_ok=True)

        (stage_dir / 'stage.zip').write_bytes(zip_data)

        with open(stage_dir / 'stage.json', 'w') as f:
            json.dump(stage_meta, f, indent=2)

        for index, (member, _track) in enumerate(portable_playlist):
            (stage_dir / f'music_{index}.hps').write_bytes(zf.read(member))

        has_icon = False
        if icon_path:
            (stage_dir / 'icon.png').write_bytes(zf.read(icon_path))
            has_icon = True

        has_banner = False
        if banner_path:
            (stage_dir / 'banner.png').write_bytes(zf.read(banner_path))
            has_banner = True

    entry = {
        'slug': slug,
        'name': stage_name,
        'source': 'zip',
        'date_added': datetime.now().isoformat(),
        'series_id': stage_meta.get('seriesID', 0),
        'sound_bank': stage_meta.get('soundBank', None),
        'dat_files': [n.split('/')[-1] for n in dat_files],
        'has_banner': has_banner,
        'has_icon': has_icon
    }
    if portable_playlist:
        entry['playlist'] = [track for _member, track in portable_playlist]

    # Raw vanilla-stage mods (vanilla_stage_import) carry a sidecar with what
    # MexStage.FromPackage resets on install (vanilla sound bank + playlist);
    # the install flow re-applies it via _apply_vanilla_stage_fixups.
    if isinstance(stage_meta.get('nucleusVanillaStage'), dict):
        entry['vanilla_stage'] = stage_meta['nucleusVanillaStage']

    # Locked read-append-write (see custom_characters import) — concurrent
    # multi-file imports otherwise race on the shared vault metadata.
    with metadata_transaction(default=dict(DEFAULT_META)) as metadata:
        metadata.setdefault('custom_stages', []).append(entry)

    logger.info(f"[OK] Imported custom stage '{stage_name}' as {slug}")
    return entry
