"""
Custom characters out of a scanned m-ex build: which fighters are added (not
the vanilla roster), and everything that has to travel with one into the vault
so it installs anywhere: its fighter.zip, CSS icon and per-costume portraits,
a custom franchise (series), the victory theme and announcer name-call, the
item-only clone patch, archives its code and single-player modes load by name,
and a repaired bone lookup count.

No routes. The ISO scan routes (vault/routes/custom_characters/) build a
temporary project from the ISO and call _extract_custom_characters_from_project.
"""

import json
import re
import shutil
import zipfile
import logging
from pathlib import Path
from datetime import datetime

import file_retry
from core.config import CUSTOM_CHARACTERS_PATH, MEXCLI_PATH
import mexcli.commands
from core.images import resolve_asset_png
from vault.importing.custom_character_package import make_slug as _make_slug
from vault.catalog.custom_characters import (
    SERIES_NAMES, _dedupe_slug, _read_metadata, _rewrite_fighter_zip, _write_metadata,
)

logger = logging.getLogger(__name__)


VANILLA_FIGHTER_NAMES = {
    'C. Falcon', 'Captain Falcon', 'DK', 'Donkey Kong', 'Fox',
    'Mr. Game & Watch', 'Game & Watch', 'Kirby', 'Bowser',
    'Link', 'Luigi', 'Mario', 'Marth', 'Mewtwo', 'Ness', 'Peach',
    'Pikachu', 'Ice Climbers', 'Jigglypuff', 'Samus', 'Yoshi', 'Zelda',
    'Sheik', 'Falco', 'Young Link', 'Dr. Mario', 'Roy', 'Pichu',
    'Ganondorf', 'Master Hand', 'Wireframe Male', 'Wireframe Female',
    'Giga Bowser', 'Crazy Hand', 'Sandbag', 'Nana',
    'NONE', 'Popo',
}


def _norm_fighter_name(name):
    """Normalize a fighter name for comparison: case, punctuation, and
    '&'-vs-'and' (some builds rename e.g. 'Mr. Game and Watch')."""
    n = (name or '').lower().replace(' and ', ' & ')
    return re.sub(r'[^a-z0-9&]', '', n)


VANILLA_FIGHTER_NAMES_NORM = {_norm_fighter_name(n) for n in VANILLA_FIGHTER_NAMES}

# ftData files of the vanilla roster. A scanned fighter that reuses a vanilla
# NAME but ships its own ftData is an added fighter, not the vanilla one: the
# ACE Build's playable Giga Bowser is "Giga Bowser" on PlGkp.dat beside the
# vanilla PlGk.dat boss, and the name check alone silently dropped it.
VANILLA_FIGHTER_DATA_FILES = {
    f'pl{code}.dat' for code in (
        'mr', 'fx', 'ca', 'dk', 'kb', 'kp', 'lk', 'sk', 'ns', 'pe', 'pp', 'nn',
        'pk', 'ss', 'ys', 'pr', 'mt', 'lg', 'ms', 'zd', 'cl', 'dr', 'fc', 'pc',
        'gw', 'gn', 'fe', 'mh', 'ch', 'bo', 'gl', 'gk', 'sb')
}


def _is_vanilla_fighter(fighter_data):
    """True for the vanilla roster (and the empty 'NONE' slot) in a scanned build."""
    if _norm_fighter_name(fighter_data.get('name', '')) not in VANILLA_FIGHTER_NAMES_NORM:
        return False
    files = fighter_data.get('files') if isinstance(fighter_data.get('files'), dict) else {}
    data_file = (files.get('fighterDataPath') or '').strip().lower()
    return not data_file or data_file in VANILLA_FIGHTER_DATA_FILES


def _build_ssm_index(project_dir):
    """Index every sound bank of a scanned build: [(ssm_path, startIndex,
    count)]. Built once per scan — announcer calls are absolute sound IDs
    that can live in ANY bank (usually a global announcer bank, not the
    fighter's own)."""
    index = []
    us_dir = project_dir / 'files' / 'audio' / 'us'
    if not us_dir.exists():
        return index
    for ssm_path in sorted(us_dir.glob('*.ssm')):
        info = mexcli.commands.run_json(['ssm-info', ssm_path])
        if info.get('success'):
            index.append((ssm_path, info['startIndex'], info['count']))
    return index


def _resolve_announcer_sfx(project_dir, call):
    """The absolute sfx id a SEM script id (bank*10000 + script) plays in a
    scanned build, or None."""
    if not isinstance(call, int) or call == 540000:
        return None
    sem_files = sorted((Path(project_dir) / 'files' / 'audio' / 'us').glob('*.sem'))
    if not sem_files:
        return None
    resolved = mexcli.commands.run_json(['sem-resolve', sem_files[0], call])
    sfx_id = resolved.get('sfxId')
    return sfx_id if resolved.get('success') and isinstance(sfx_id, int) else None


def _extract_audio_meta(project_dir, fighter_data, char_dir, ssm_index=None,
                        source_clip_hashes=frozenset()):
    """Pull portable audio out of a scanned build for a fighter:

    - victory theme: the .hps file + track name (MexFighter.FromPackage
      resets victoryTheme on install, so the vault must carry the music
      itself to port it)
    - announcer call: located across the build's sound banks and decoded
      straight to announcer.wav (absolute sound IDs only mean something
      inside the source build)

    Returns a dict of metadata-entry updates.
    """
    updates = {}

    # victory theme
    vt = fighter_data.get('victoryTheme')
    music_json = project_dir / 'data' / 'music.json'
    if isinstance(vt, int) and music_json.exists():
        try:
            with open(music_json, 'r', encoding='utf-8') as f:
                music = json.load(f)
        except (json.JSONDecodeError, OSError):
            music = []
        if 0 <= vt < len(music):
            m = music[vt] or {}
            fname = m.get('fileName')
            src = (project_dir / 'files' / 'audio' / fname) if fname else None
            if src and src.exists():
                shutil.copy2(src, char_dir / 'victory_theme.hps')
                # stale decoded cache, if any
                cache = char_dir / 'audio_cache' / 'victory_theme.wav'
                if cache.exists():
                    cache.unlink()
                updates['victory_theme'] = {
                    'name': (m.get('name') or '').strip() or Path(fname).stem,
                }

    # announcer call: a SEM script id (bank*10000 + script) -> the script's
    # sound -> decoded to announcer.wav. The clip itself is what's portable;
    # install matches it by content (core/narrator.py). Many fighters can share
    # one clip (ACE 2.0's 29 "Bonus Character" fighters); each keeps a copy and
    # install ports it once. A re-scan refreshes a wav that an earlier scan
    # decoded (its PCM is one of the build's narrator clips); a wav the user
    # replaced is kept.
    from core.narrator import pcm_hash
    call = fighter_data.get('announcerCall')
    announcer_wav = char_dir / 'announcer.wav'
    if isinstance(call, int) and ssm_index:
        sfx_id = _resolve_announcer_sfx(project_dir, call)
        if sfx_id is not None:
            for ssm_path, start, count in ssm_index:
                idx = sfx_id - start
                if not 0 <= idx < count:
                    continue
                probe = char_dir / '.announcer_scan.wav'
                try:
                    out = mexcli.commands.run_json(['ssm-to-wav', ssm_path, idx, probe])
                    if out.get('success') and probe.exists():
                        keep_user = (announcer_wav.exists()
                                     and pcm_hash(announcer_wav) not in source_clip_hashes)
                        if not keep_user:
                            file_retry.replace(probe, announcer_wav)
                            updates['has_announcer'] = True
                            updates['announcer_hash'] = pcm_hash(announcer_wav)
                finally:
                    if probe.exists():
                        probe.unlink()
                break

    return updates


def _extract_custom_series(project_dir, series_id, char_dir):
    """Pull a custom series (beyond the vanilla 17) out of a scanned
    project: its icon texture, emblem model, and name. Returns the
    custom_series metadata dict, or None.
    """
    if not isinstance(series_id, int) or series_id < len(SERIES_NAMES):
        return None
    series_json = project_dir / 'data' / 'series.json'
    if not series_json.exists():
        return None
    try:
        with open(series_json, 'r', encoding='utf-8') as f:
            series_list = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if series_id >= len(series_list):
        return None

    src = series_list[series_id] or {}
    assets_dir = project_dir / 'assets'

    icon_file = resolve_asset_png(assets_dir, src.get('icon'))
    if icon_file:
        shutil.copy2(icon_file, char_dir / 'series_icon.png')

    model_ref = src.get('model')
    if model_ref:
        model_file = assets_dir / (model_ref.replace('\\', '/') + '.obj')
        if model_file.exists():
            shutil.copy2(model_file, char_dir / 'series_emblem.obj')

    name = (src.get('name') or '').strip()
    return {
        'name': name or None,
        'source_id': series_id,
        'active': True,
        'has_icon': icon_file is not None,
    }


def _bake_clone_patch(char_dir, fighter_data):
    """Put the item-only clone patch inside a vault fighter.zip
    (patches/clone_engine_items.dat) when the fighter is a clone that needs it,
    so the character is standalone: exported or shared zips carry it, and
    MexCLI/MexManager merge it on install anywhere. Returns True if the zip was
    rewritten. A zip that already carries any patches/*.dat is left alone."""
    from core.clone_patch import PATCH_ENTRY, fighter_needs_items_patch, items_patch_bytes
    zip_path = Path(char_dir) / 'fighter.zip'
    if not zip_path.exists() or not fighter_needs_items_patch(fighter_data or {}):
        return False
    try:
        with zipfile.ZipFile(zip_path) as zf:
            if any(n.lower().startswith('patches/') for n in zf.namelist()):
                return False
        patch = items_patch_bytes()
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        logger.warning(f"clone item patch not baked into {zip_path}: {e}")
        return False
    _rewrite_fighter_zip(Path(char_dir), replace_entries={PATCH_ENTRY: patch})
    logger.info(f"Baked {PATCH_ENTRY} into {zip_path}")
    return True


_DAT_NAME_RE = re.compile(rb'[A-Za-z0-9_\-]{2,40}\.dat')


def _code_referenced_files(project_dir, fighter_data):
    """Archives a fighter's compiled code loads BY NAME that fighter.json does
    not list. ACE 2.0's Raichu loads "largetrailrc.dat" and Skull Kid
    "mediumtrailevil.dat"/"mediumtrailevil2.dat" from their ftFunction code;
    export-fighter packs only fighter.json's files, so on any other disc the
    match crashed on load ("file isn't exist ... lbfile.c"). Returns
    {name as on the source disc: Path} for referenced files present in the
    source project's files/ folder."""
    files = fighter_data.get('files') if isinstance(fighter_data.get('files'), dict) else {}
    data_path = (files.get('fighterDataPath') or '').strip()
    files_dir = Path(project_dir) / 'files'
    src = files_dir / data_path if data_path else None
    if not src or not src.is_file():
        return {}
    listed = {str(v).lower() for v in files.values() if isinstance(v, str)}
    try:
        on_disc = {p.name.lower(): p for p in files_dir.iterdir() if p.is_file()}
    except OSError:
        return {}
    out = {}
    for m in set(_DAT_NAME_RE.findall(src.read_bytes())):
        name = m.decode('ascii', 'replace').lower()
        hit = on_disc.get(name)
        if hit is not None and name not in listed and hit != src:
            out[hit.name] = hit
    return out


def _standalone_demo_files(project_dir, fighter_data):
    """Optional Classic intro/ending archives, named after their public roots.

    m-ex tries <demoIntro>.dat / <demoEnding>.dat before the shared IrAls.dat /
    GmRegEnd.dat archives. export-fighter does not include those standalone
    files; losing them can leave a custom fighter with no animation at all.
    Embedded demos need no extra file, so only preserve files the source has.
    """
    files = fighter_data.get('files') if isinstance(fighter_data.get('files'), dict) else {}
    files_dir = Path(project_dir) / 'files'
    out = {}
    for key in ('demoIntro', 'demoEnding'):
        symbol = files.get(key)
        if (not isinstance(symbol, str) or not symbol or symbol.rstrip(' .') != symbol
                or any(ord(c) < 32 or c in '/\\:<>"|?*' for c in symbol)):
            continue
        path = files_dir / f'{symbol}.dat'
        if path.is_file() and path.resolve().is_relative_to(files_dir.resolve()):
            out[path.name] = path
    return out


def _bake_referenced_files(char_dir, fighter_data, project_dir):
    """Add archives a fighter's code and Classic demos load by name
    to its vault fighter.zip as loose .dat entries; MexCLI add-fighter copies
    loose .dat entries into the target project's files/. Returns the names
    added. Entries already in the zip are left alone."""
    zip_path = Path(char_dir) / 'fighter.zip'
    if not zip_path.exists():
        return []
    wanted = _code_referenced_files(project_dir, fighter_data)
    wanted.update(_standalone_demo_files(project_dir, fighter_data))
    if not wanted:
        return []
    try:
        with zipfile.ZipFile(zip_path) as zf:
            present = {n.split('/')[-1].lower() for n in zf.namelist()}
    except (OSError, zipfile.BadZipFile):
        return []
    add = {name: path.read_bytes() for name, path in wanted.items()
           if name.lower() not in present}
    if add:
        _rewrite_fighter_zip(Path(char_dir), replace_entries=add)
        logger.info(f"Added referenced files {sorted(add)} to {zip_path}")
    return sorted(add)


def _repair_truncated_bone_count(char_dir, fighter_data):
    """Restore a bone lookup count that an older MexCLI truncated in the vault
    fighter.zip. MexCLI linked a stale HSDRaw.dll (fixed 2026-09-21) whose
    SBM_BoneLookupTable rebuilt boneCount as "highest mapped joint + 1", so a
    fighter with trailing unmapped joints (ACE 2.0's Meta Knight: 84 -> 82)
    was packed short and froze on match load on every disc. A re-scan reads the
    source build with the fixed binary; when the zip's count is lower than the
    scanned one, copy the scanned boneDefinitions into the zip. Returns True if
    the zip was rewritten."""
    zip_path = Path(char_dir) / 'fighter.zip'
    scanned = (fighter_data.get('boneDefinitions') or {})
    want = ((scanned.get('lookup') or {}).get('boneCount'))
    if not zip_path.exists() or not isinstance(want, int):
        return False
    try:
        with zipfile.ZipFile(zip_path) as zf:
            fj = next((n for n in zf.namelist() if n.split('/')[-1].lower() == 'fighter.json'), None)
            if fj is None:
                return False
            have = ((json.loads(zf.read(fj)).get('boneDefinitions') or {}).get('lookup') or {}).get('boneCount')
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError):
        return False
    if not isinstance(have, int) or have >= want:
        return False

    def _mutate(meta):
        meta['boneDefinitions'] = scanned
        return meta
    _rewrite_fighter_zip(Path(char_dir), mutate_json=_mutate)
    logger.info(f"Restored bone count {have} -> {want} in {zip_path}")
    return True


def _extract_custom_characters_from_project(project_dir, source_label):
    """Extract custom characters from a MEX project directory into the vault.
    Returns (imported, skipped) name lists."""
    fighters_dir = project_dir / 'data' / 'fighters'
    assets_dir = project_dir / 'assets'
    project_path = project_dir / 'project.mexproj'

    if not fighters_dir.exists():
        raise FileNotFoundError('Project data/fighters/ directory not found')

    with open(project_path, 'r', encoding='utf-8') as f:
        proj_data = json.load(f)

    fighter_files = proj_data.get('fighterSaveMap', {}).get('filePaths', [])
    if not fighter_files:
        return [], []

    metadata = _read_metadata()
    existing_names = {c['name'].lower() for c in metadata.get('custom_characters', [])}

    # one pass over the build's sound banks for announcer-call resolution
    ssm_index = _build_ssm_index(project_dir)

    # An added fighter that reuses a vanilla name (the ACE Build's playable
    # Giga Bowser) is filed under "<name> (<build>)" so it can't collide with
    # the vanilla fighter or Nucleus's own built-in Giga Bowser entry.
    build_info = proj_data.get('build') if isinstance(proj_data.get('build'), dict) else {}
    build_label = (build_info.get('shortName') or build_info.get('name') or '').strip() or 'Custom'


    # PCM hashes of every clip in the build's narrator bank: tells a wav an
    # earlier scan decoded from one the user replaced (_extract_audio_meta).
    source_clip_hashes = set()
    if ssm_index:
        try:
            from core.narrator import narrator_clip_hashes
            source_clip_hashes = set(narrator_clip_hashes(project_dir, MEXCLI_PATH).values())
        except (OSError, ValueError, KeyError) as e:
            logger.warning(f"narrator clips not hashed for {project_dir}: {e}")

    imported = []
    skipped = []

    mexcli_path = str(MEXCLI_PATH)

    for fighter_index, fighter_file in enumerate(fighter_files):
        fighter_json_path = fighters_dir / fighter_file
        if not fighter_json_path.exists():
            continue

        try:
            with open(fighter_json_path, 'r', encoding='utf-8') as f:
                fighter_data = json.load(f)

            fighter_name = fighter_data.get('name', '')
            if not fighter_name or _is_vanilla_fighter(fighter_data):
                continue
            if _norm_fighter_name(fighter_name) in VANILLA_FIGHTER_NAMES_NORM:
                fighter_name = f"{fighter_name} ({build_label})"

            if fighter_name.lower() in existing_names:
                existing = next((c for c in metadata.get('custom_characters', [])
                                 if c['name'].lower() == fighter_name.lower()), None)
                existing_dir = CUSTOM_CHARACTERS_PATH / existing['slug'] if existing else None
                if existing is not None and existing_dir.exists():
                    # Backfill custom series for characters scanned before
                    # series extraction existed (e.g. Chun-Li's series 19)
                    if not existing.get('custom_series'):
                        cs = _extract_custom_series(
                            project_dir, fighter_data.get('seriesID', 0), existing_dir)
                        if cs:
                            existing['custom_series'] = cs
                            _write_metadata(metadata)
                            logger.info(f"Backfilled custom series for '{fighter_name}': {cs}")

                    # Refresh result banners + CSS icon inside fighter.zip —
                    # an old importer bug assigned every custom fighter its
                    # neighbour's banner (Wolf showed SHEIK etc.)
                    assets_obj = fighter_data.get('assets', {})
                    replace = {}
                    for ref_key, entry_name in (('resultBannerBig', 'big_banner.png'),
                                                ('resultSmallBig', 'small_banner.png'),
                                                ('cssIcon', 'icon.png')):
                        asset_file = resolve_asset_png(assets_dir, assets_obj.get(ref_key))
                        if asset_file:
                            replace[entry_name] = asset_file.read_bytes()
                    if replace and (existing_dir / 'fighter.zip').exists():
                        _rewrite_fighter_zip(existing_dir, replace_entries=replace)
                        if 'icon.png' in replace:
                            (existing_dir / 'css_icon.png').write_bytes(replace['icon.png'])
                        logger.info(f"Refreshed {sorted(replace)} for '{fighter_name}'")

                    _bake_clone_patch(existing_dir, fighter_data)
                    _bake_referenced_files(existing_dir, fighter_data, project_dir)
                    _repair_truncated_bone_count(existing_dir, fighter_data)


                    # backfill portable audio (victory theme, announcer call)
                    audio_updates = _extract_audio_meta(project_dir, fighter_data, existing_dir, ssm_index,
                                                        source_clip_hashes)
                    if audio_updates:
                        existing.update(audio_updates)
                        _write_metadata(metadata)
                skipped.append(fighter_name)
                continue

            slug = _dedupe_slug(_make_slug(fighter_name))
            char_dir = CUSTOM_CHARACTERS_PATH / slug
            char_dir.mkdir(parents=True, exist_ok=True)

            # Export full fighter ZIP via MexCLI
            zip_path = char_dir / 'fighter.zip'
            if Path(mexcli_path).exists():
                export_result = mexcli.commands.run(
                    ['export-fighter', project_path, fighter_index, zip_path], check=False)
                if export_result.returncode != 0:
                    logger.warning(f"Failed to export fighter ZIP for '{fighter_name}': {export_result.stderr or export_result.stdout}")

            with file_retry.retry_locked(open, char_dir / 'fighter.json', 'w', encoding='utf-8') as f:
                json.dump(fighter_data, f, indent=2)
            _bake_clone_patch(char_dir, fighter_data)
            _bake_referenced_files(char_dir, fighter_data, project_dir)

            assets_obj = fighter_data.get('assets', {})
            has_css_icon = False
            icon_ref = assets_obj.get('cssIcon')
            icon_file = resolve_asset_png(assets_dir, icon_ref)
            if icon_file:
                shutil.copy2(icon_file, char_dir / 'css_icon.png')
                has_css_icon = True

            costumes = fighter_data.get('costumes', [])
            for i, costume in enumerate(costumes):
                csp_ref = costume.get('csp')
                csp_file = resolve_asset_png(assets_dir, csp_ref)
                if csp_file:
                    shutil.copy2(csp_file, char_dir / f'csp_{i}.png')
                stock_ref = costume.get('icon')
                stock_file = resolve_asset_png(assets_dir, stock_ref)
                if stock_file:
                    shutil.copy2(stock_file, char_dir / f'stock_{i}.png')

            entry = {
                'slug': slug,
                'name': fighter_name,
                'source': source_label,
                'date_added': datetime.now().isoformat(),
                'series_id': fighter_data.get('seriesID', 0),
                'costume_count': len(costumes),
                'has_css_icon': has_css_icon
            }

            custom_series = _extract_custom_series(
                project_dir, fighter_data.get('seriesID', 0), char_dir)
            if custom_series:
                entry['custom_series'] = custom_series

            entry.update(_extract_audio_meta(project_dir, fighter_data, char_dir, ssm_index,
                                             source_clip_hashes))

            metadata['custom_characters'].append(entry)
            existing_names.add(fighter_name.lower())
            imported.append(fighter_name)

        except (json.JSONDecodeError, KeyError):
            continue

    if imported:
        _write_metadata(metadata)

    return imported, skipped
