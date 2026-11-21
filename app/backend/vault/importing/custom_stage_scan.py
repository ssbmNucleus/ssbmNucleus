"""
Custom stages out of a scanned m-ex build: every stage the build adds (not the
vanilla roster) becomes a vault custom stage with its DAT(s), icon, banner and
playlist music, deduplicated by name against what the vault already holds.

No routes. The ISO scan routes (vault/routes/custom_stages.py and the m-ex
content scan in vault/routes/custom_characters/) build a temporary project from
the ISO and call _extract_custom_stages_from_project.
"""

import json
import shutil
import logging
import mexcli.commands
from pathlib import Path
from datetime import datetime
from core.config import MEXCLI_PATH
from core.images import resolve_asset_png
from vault.importing.custom_stage_package import (CUSTOM_STAGES_PATH, make_slug as _make_slug,
    dedupe_slug)
from vault.catalog.custom_stages import _is_folder, _read_metadata, _write_metadata

logger = logging.getLogger(__name__)


def _dedupe_slug(slug):
    """`slug` or `slug-N`, free under this module's CUSTOM_STAGES_PATH (the
    routes' root, which tests repoint)."""
    return dedupe_slug(slug, CUSTOM_STAGES_PATH)


VANILLA_STAGE_NAMES = {
    'Null', 'Test Stage', "Princess Peach's Castle", 'Rainbow Cruise',
    'Kongo Jungle', 'Jungle Japes', 'Great Bay', 'Temple', 'Brinstar',
    'Brinstar Depths', "Yoshi's Story", "Yoshi's Island",
    'Fountain of Dreams', 'Green Greens', 'Corneria', 'Venom',
    'Pokemon Stadium', 'Poke Floats', 'Mute City', 'Big Blue', 'Onett',
    'Fourside', 'Icicle Mountain', 'Ice Top', 'Kingdom', 'Kingdom II',
    'Akaneia', 'Flat Zone', 'Dream Land N64', "Yoshi's Island N64",
    'Kongo Jungle N64', 'Mushroom Kingdom (Adventure)', 'Underground Maze',
    'Brinstar Escape Shaft', 'F-Zero Grand Prix', 'Battlefield',
    'Final Destination', 'Trophy Collector', 'Race to the Finish',
    'Targets!Mario', 'Targets!C. Falcon', 'Targets!Young Link',
    'Targets!DK', 'Targets!Dr. Mario', 'Targets!Falco', 'Targets!Fox',
    'Targets!Ice Climbers', 'Targets!Kirby', 'Targets!Bowser',
    'Targets!Link', 'Targets!Luigi', 'Targets!Marth', 'Targets!Mewtwo',
    'Targets!Ness', 'Targets!Peach', 'Targets!Pichu', 'Targets!Pikachu',
    'Targets!Jigglypuff', 'Targets!Samus', 'Targets!Sheik',
    'Targets!Yoshi', 'Targets!Zelda', 'Targets!Game and Watch',
    'Targets!Roy', 'Targets!Ganon', 'All-Star Rest Area',
    'Home-Run Stadium', 'Trophy (Goomba)', 'Trophy (Entei)',
    "Trophy (Majora's Mask)",
}


def _extract_stage_playlist(project_dir, stage_data, stage_dir):
    """Copy a custom stage's playlist music (.hps files + names) into the
    vault. MexStage.FromPackage resets the playlist on install, so the
    vault carries the actual tracks to port them. Returns entry updates."""
    entries = ((stage_data.get('playlist') or {}).get('entries')) or []
    if not entries:
        return {}

    music_json = project_dir / 'data' / 'music.json'
    if not music_json.exists():
        return {}
    try:
        with open(music_json, 'r', encoding='utf-8') as f:
            music = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

    playlist = []
    for e in entries:
        mid = e.get('musicID')
        chance = e.get('chanceToPlay', 50)
        if not (isinstance(mid, int) and 0 <= mid < len(music)):
            continue
        m = music[mid] or {}
        fname = m.get('fileName')
        src = (project_dir / 'files' / 'audio' / fname) if fname else None
        if not (src and src.exists()):
            continue
        i = len(playlist)
        shutil.copy2(src, stage_dir / f'music_{i}.hps')
        cache = stage_dir / 'audio_cache' / f'track_{i}.wav'
        if cache.exists():
            cache.unlink()
        playlist.append({
            'name': (m.get('name') or '').strip() or Path(fname).stem,
            'chance': chance,
        })

    return {'playlist': playlist} if playlist else {}


def _extract_custom_stages_from_project(project_dir, source_label):
    """Extract custom stages from a MEX project directory into the vault.
    Returns (imported, skipped) name lists."""
    files_dir = project_dir / 'files'
    stages_dir = project_dir / 'data' / 'stages'
    assets_dir = project_dir / 'assets'
    project_path = project_dir / 'project.mexproj'

    if not stages_dir.exists():
        raise FileNotFoundError('Project data/stages/ directory not found')

    with open(project_path, 'r') as f:
        proj_data = json.load(f)

    stage_files = proj_data.get('stageSaveMap', {}).get('filePaths', [])
    if not stage_files:
        return [], []

    metadata = _read_metadata()
    existing_names = {
        s['name'].lower()
        for s in metadata.get('custom_stages', [])
        if not _is_folder(s) and s.get('name')
    }

    imported = []
    skipped = []

    mexcli_path = str(MEXCLI_PATH)

    for stage_index, stage_file in enumerate(stage_files):
        stage_json_path = stages_dir / stage_file
        if not stage_json_path.exists():
            continue

        try:
            with open(stage_json_path, 'r') as f:
                stage_data = json.load(f)

            stage_name = stage_data.get('name', '')
            if not stage_name or stage_name in VANILLA_STAGE_NAMES:
                continue

            if stage_name.lower() in existing_names:
                # backfill playlist music for stages scanned before audio
                # extraction existed
                existing = next((s for s in metadata.get('custom_stages', [])
                                 if not _is_folder(s) and (s.get('name') or '').lower() == stage_name.lower()), None)
                if existing is not None:
                    existing_dir = CUSTOM_STAGES_PATH / existing['slug']
                    if existing_dir.exists():
                        playlist_updates = _extract_stage_playlist(project_dir, stage_data, existing_dir)
                        if playlist_updates:
                            existing.update(playlist_updates)
                            _write_metadata(metadata)
                skipped.append(stage_name)
                continue

            slug = _dedupe_slug(_make_slug(stage_name))
            stage_dir = CUSTOM_STAGES_PATH / slug
            stage_dir.mkdir(parents=True, exist_ok=True)

            # Export full stage ZIP via MexCLI
            zip_path = stage_dir / 'stage.zip'
            if Path(mexcli_path).exists():
                export_result = mexcli.commands.run(
                    ['export-stage', project_path, stage_index, zip_path], check=False)
                if export_result.returncode != 0:
                    logger.warning(f"Failed to export stage ZIP for '{stage_name}': {export_result.stderr or export_result.stdout}")

            with open(stage_dir / 'stage.json', 'w') as f:
                json.dump(stage_data, f, indent=2)

            assets_obj = stage_data.get('assets', {})
            has_icon = False
            icon_ref = assets_obj.get('icon')
            icon_file = resolve_asset_png(assets_dir, icon_ref)
            if icon_file:
                shutil.copy2(icon_file, stage_dir / 'icon.png')
                has_icon = True

            has_banner = False
            banner_ref = assets_obj.get('banner')
            banner_file = resolve_asset_png(assets_dir, banner_ref)
            if banner_file:
                shutil.copy2(banner_file, stage_dir / 'banner.png')
                has_banner = True

            file_name = stage_data.get('fileName') or ''
            dat_files_found = []
            if file_name and files_dir.exists():
                clean = file_name.lstrip('/')
                if not clean.endswith('.dat'):
                    clean += '.dat'
                main_dat = files_dir / clean
                if main_dat.exists():
                    dat_files_found.append(main_dat.name)
                for extra in stage_data.get('additionalFiles', []):
                    extra_path = files_dir / extra.lstrip('/')
                    if extra_path.exists():
                        dat_files_found.append(extra_path.name)

            entry = {
                'slug': slug,
                'name': stage_name,
                'source': source_label,
                'date_added': datetime.now().isoformat(),
                'series_id': stage_data.get('seriesID', 0),
                'sound_bank': stage_data.get('soundBank', None),
                'dat_files': dat_files_found,
                'has_banner': has_banner,
                'has_icon': has_icon
            }

            entry.update(_extract_stage_playlist(project_dir, stage_data, stage_dir))

            metadata['custom_stages'].append(entry)
            existing_names.add(stage_name.lower())
            imported.append(stage_name)

        except (json.JSONDecodeError, KeyError):
            continue

    if imported:
        _write_metadata(metadata)

    return imported, skipped
