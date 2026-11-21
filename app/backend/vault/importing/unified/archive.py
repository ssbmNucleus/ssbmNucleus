"""
Importing one uploaded archive (ZIP/7z/RAR/DAT/USD/xdelta/bundle): classify it,
dispatch it to the matching importer, and recurse into container archives
(a zip of zips), aggregating what happened to every inner file.

Also the archive plumbing the importers share: 7z to zip conversion (py7zr is
imported lazily), the operation's extraction budget, and error sentences
without local paths. The endpoint is vault/routes/import_unified/routes.py.
"""

import io
import os
import zipfile
import tempfile
import logging
import uuid
import importlib.util as _importlib_util
from pathlib import Path
from datetime import datetime
from core.config import STORAGE_PATH
from core.metadata import load_metadata, metadata_transaction
from core.safe_archive import safe_extract_7z
from core.rar_tools import rar_available, rar_to_temp_zip
from vault.importing.character_detector import detect_character_from_zip
from vault.importing.stage_detector import detect_stage_from_zip
from dat_processor import validate_for_slippi
from projects.install.xdelta import load_xdelta_metadata, save_xdelta_metadata
from vault.menus.icons import install_icon_grid_mod, looks_like_icon_grid_zip
from vault.menus.pause import install_pause_mods_from_zip, looks_like_pause_zip
from vault.menus.percent import install_percent_mods_from_zip, looks_like_percent_zip
from vault.importing.unified.detection import (
    _read_member, detect_content_type, MAX_CONTAINER_DEPTH, _PACKAGE_TYPES, _list_inner_archives)
from vault.importing.unified.helpers import (
    check_duplicate_patch, check_duplicate_skin, check_duplicate_stage, compute_dat_hash,
    sanitize_filename)
from vault.importing.unified.characters import fix_ice_climbers_pairing, import_character_costume
from vault.importing.unified.stages import import_stage_mod
from vault.importing.unified.effects import _import_effect_mod
from vault.importing.vanilla_stage_import import import_vanilla_stage_dats
from vault.importing.unified.menu_import import (_MENU_HINT_TYPES, _located,
    _mnslchr_is_ambiguous, _import_background, _percent_result, _import_menu_by_hint)
from vault.importing.unified.dialogs import _choice_dialog, _image_choice_dialog
from vault.importing.unified.detected_effects import (_effect_zip_name, _effect_located,
    _effect_duplicate_response, _import_detected_effects, _import_effect_image)

logger = logging.getLogger(__name__)


# py7zr is imported LAZILY, only when a .7z is actually handled. Importing it
# pulls in multiprocessing, and in a PyInstaller build that machinery can
# re-execute the app (see the freeze_support() note in app.py). find_spec
# answers "is 7z support available?" without paying that cost.
HAS_7Z = _importlib_util.find_spec("py7zr") is not None


def _py7zr():
    """Import py7zr on demand. Callers must check HAS_7Z first."""
    import py7zr
    return py7zr


# Diagnosis-only verdicts that just mean "no loose importable content here" —
# not worth reporting as a failure when the archive's real payload was its
# inner archives.
_NO_CONTENT_TYPES = {'unknown', 'nested_archive'}


def _convert_7z_to_temp_zip(archive_path, limits=None):
    """Repack a .7z into a temp .zip (stored, not recompressed).

    Nearly every consumer past detection — the Slippi/duplicate pre-check
    loops, import_character_costume, import_stage_mod, the menu-mod
    installers — opens the archive with zipfile directly, so a .7z upload
    used to 500 with BadZipFile the moment its costumes were detected.
    Converting once at entry makes the whole pipeline format-agnostic.

    Returns the new temp zip path (caller owns it), or None if py7zr is
    missing or the archive can't be read — callers keep the original path
    and fall through to the normal "could not detect" handling.
    """
    if not HAS_7Z:
        return None
    zip_path = None
    try:
        with tempfile.TemporaryDirectory(prefix='7z_convert_') as tmp_dir:
            with _py7zr().SevenZipFile(archive_path, 'r') as sz:
                if limits is not None:
                    safe_extract_7z(sz, tmp_dir, limits=limits)
                else:
                    safe_extract_7z(sz, tmp_dir)
            fd, zip_path = tempfile.mkstemp(suffix='.zip')
            os.close(fd)
            root = Path(tmp_dir)
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as zf:
                for p in sorted(root.rglob('*')):
                    if p.is_file():
                        zf.write(p, p.relative_to(root).as_posix())
        return zip_path
    except Exception as e:
        logger.warning(f'7z conversion failed for {archive_path}: {e}')
        if zip_path:
            try:
                os.unlink(zip_path)
            except OSError:
                pass
        return None


_ABSOLUTE_PATH = __import__('re').compile(
    r'(?:[A-Za-z]:[\\/]|\\\\|/)(?:[^\s"\']*[\\/])+[^\s"\']*')


def _client_error(exc):
    """One sentence for the user, with no local filesystem path in it.

    `str(e)` from an OSError or a converter carries absolute paths from THIS
    machine into an API response and a chat transcript. The archive's own
    member names are kept -- those are what the user needs -- but anything
    shaped like a local path is replaced (2026-09-22 re-review, 9).
    """
    from core.safe_extract import UnsafeArchiveMember
    if isinstance(exc, UnsafeArchiveMember):
        return exc.sentence()
    return _ABSOLUTE_PATH.sub('<a file on this computer>', str(exc))[:1000]


def _charge_archive(path, budget):
    """Preflight an archive on disk against the operation's budget.

    For the importers that read members themselves (bundles, the custom-stage
    package importer, the classic stage converter) this is the one place the
    declared expansion is counted and hostile member names are refused. The
    budget is keyed to archive identity, so charging here and again downstream
    costs the allowance once.
    """
    if budget is None:
        return
    try:
        with zipfile.ZipFile(path) as zf:
            from core.safe_extract import preflight_zip
            preflight_zip(zf, budget=budget)
    except zipfile.BadZipFile:
        return


def _charge_archive_bytes(data, budget):
    """The same, for an archive that only exists in memory (a conversion)."""
    if budget is None:
        return
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            from core.safe_extract import preflight_zip
            preflight_zip(zf, budget=budget)
    except zipfile.BadZipFile:
        return


def _import_single_archive(temp_zip_path, filename, *, slippi_action=None,
                           duplicate_action=None, custom_title=None,
                           mod_type=None, effect_type=None, character=None,
                           depth=0, recurse_containers=True, budget=None):
    """Run the full detection/dispatch cascade on one archive already on disk.

    Returns (payload_dict, http_status). Never deletes temp_zip_path — the
    caller owns the file. Recursion into container zips re-enters this
    function per inner archive (recurse_containers=False processes only the
    archive's own loose content).

    `budget` is ONE cumulative extraction budget for the whole user-visible
    operation (core.safe_extract). Classification, container recursion and
    every package converter spend the same instance, so nested archives cannot
    each claim a fresh allowance. A chat download hands in the tighter budget
    its safety preflight already started spending.
    """
    from core.safe_extract import new_budget
    budget = budget or new_budget()
    # The archive on disk, not the upload name: .7z uploads are repacked to a
    # temp .zip at entry (route + container both convert), raw .dat/.usd get
    # wrapped in one — so the temp suffix says what zipfile can actually open.
    is_zip = Path(temp_zip_path).suffix.lower() == '.zip'

    logger.info(f"=== UNIFIED IMPORT: {filename} (depth {depth}) ===")

    # EXPLICIT EFFECT ROUTING: If website told us this is an effect mod,
    # bypass auto-detection (which would misidentify the .dat as a costume)
    if mod_type == 'effect' and effect_type:
        logger.info(f"Explicit effect import: type={effect_type}")
        zip_name = _effect_zip_name(filename, character)
        dup = _effect_duplicate_response(temp_zip_path, zip_name, effect_type, duplicate_action)
        if dup is not None:
            return dup
        result = _import_effect_mod(temp_zip_path, zip_name, effect_type, custom_title)
        if result:
            if result.get('success'):
                result['message'] = _effect_located(result.get('message', 'Imported effect'), result.get('character'))
                return result, 200
            return result, 400
        return {'success': False, 'error': 'No supported effect payload found in this archive'}, 400

    if mod_type == 'effect_image' and effect_type and character:
        logger.info(f"Explicit effect image import: {character} / {effect_type}")
        return _import_effect_image(temp_zip_path, character, effect_type, custom_title)

    if mod_type in _MENU_HINT_TYPES:
        logger.info(f'Explicit menu import: {mod_type}')
        return _import_menu_by_hint(temp_zip_path, filename, mod_type, custom_title)

    # EXPLICIT CSS ICON GRID ROUTING
    if mod_type == 'css_icon_grid':
        logger.info('Explicit CSS icon grid import')
        try:
            icon_grid_name = custom_title or Path(filename).stem
            mods = install_icon_grid_mod(temp_zip_path, name=icon_grid_name)
            names = ', '.join(m.get('name', '?') for m in mods)
            return {
                'success': True,
                'type': 'menu_mod',
                'menu_mod_type': 'css_icon_grid',
                'mods': mods,
                'imported_count': len(mods),
                'message': f"Imported {len(mods)} icon grid mod(s): {names}"
            }, 200
        except zipfile.BadZipFile:
            return {'success': False, 'error': 'Invalid or corrupt zip file'}, 400

    # PHASE 0: package/bundle markers. A custom-character fighter.zip
    # or custom-stage package is full of Pl*/Gr* dats that the
    # character/stage detectors would happily misclassify as loose
    # costumes, so the marker check must dispatch BEFORE them.
    shallow = detect_content_type(temp_zip_path, filename, deep=False, budget=budget)

    if shallow['type'] == 'custom_character' and is_zip:
        from vault.importing.custom_character_zip import import_custom_character_zip_bytes
        logger.info('[OK] Detected custom character package (fighter.json)')
        try:
            entry = import_custom_character_zip_bytes(
                Path(temp_zip_path).read_bytes(), Path(filename).stem, budget)
        except ValueError as e:
            return {'success': False, 'error': _client_error(e)}, 400
        return {
            'success': True,
            'type': 'custom_character',
            'character': entry,
            'message': f"Imported custom character: {entry['name']}"
        }, 200

    if shallow['type'] == 'custom_stage' and is_zip:
        from vault.importing.custom_stage_package import import_custom_stage_zip_bytes
        logger.info('[OK] Detected custom stage package (stage.json)')
        try:
            _charge_archive(temp_zip_path, budget)
            entry = import_custom_stage_zip_bytes(
                Path(temp_zip_path).read_bytes(), Path(filename).stem)
        except ValueError as e:
            return {'success': False, 'error': _client_error(e)}, 400
        return {
            'success': True,
            'type': 'custom_stage',
            'stage': entry,
            'message': f"Imported custom stage: {entry['name']}"
        }, 200

    if shallow['type'] == 'bundle' and is_zip:
        from vault.catalog.bundles import import_bundle_file
        logger.info('[OK] Detected texture bundle (manifest.json + textures/)')
        try:
            _charge_archive(temp_zip_path, budget)
            result = import_bundle_file(temp_zip_path, Path(filename).stem)
        except ValueError as e:
            return {'success': False, 'error': str(e)}, 400
        return {
            'success': True,
            'type': 'bundle',
            'bundle_id': result['bundle_id'],
            'name': result['name'],
            'message': f"Imported bundle: {result['name']}"
        }, 200

    if shallow['type'] == 'mex_stage_yml' and is_zip:
        # Classic MexTK package: convert stage.yml -> stage.json
        # (incl. the embedded map-GOBJ / moving-collision tables that
        # the extended mexLib now carries into MxDt) and import it as
        # a regular custom stage.
        from vault.importing.stage_yml_converter import convert_stage_yml_zip
        from vault.importing.custom_stage_package import import_custom_stage_zip_bytes
        logger.info('[OK] Detected classic m-ex stage package (stage.yml), converting...')
        try:
            _charge_archive(temp_zip_path, budget)
            converted, conv_info = convert_stage_yml_zip(
                Path(temp_zip_path).read_bytes(),
                custom_title or Path(filename).stem)
            _charge_archive_bytes(converted, budget)
            entry = import_custom_stage_zip_bytes(
                converted, Path(filename).stem)
        except ValueError as e:
            return {
                'success': False,
                'type': 'mex_stage_yml',
                'error': f'Classic stage package could not be converted: {_client_error(e)}'
            }, 400
        message = f"Imported custom stage: {entry['name']} (converted from classic m-ex format)"
        if conv_info.get('skipped_sound'):
            message += ' — custom sound effects not carried over (.spk unsupported)'
        return {
            'success': True,
            'type': 'custom_stage',
            'stage': entry,
            'converted_from': 'stage_yml',
            'conversion': conv_info,
            'message': message
        }, 200

    if shallow['type'] == 'mex_fighter_yml' and is_zip:
        # Classic mexTool fighter package: convert fighter.yml ->
        # fighter.json (incl. sound.spk -> sound.zip, announcer and
        # victory theme carry-over) and import it as a regular custom
        # character.
        from vault.importing.fighter_yml_converter import convert_fighter_yml_zip
        from vault.importing.custom_character_zip import import_custom_character_zip_bytes
        logger.info('[OK] Detected classic m-ex fighter package (fighter.yml), converting...')
        try:
            converted, conv_info = convert_fighter_yml_zip(
                Path(temp_zip_path).read_bytes(),
                custom_title or Path(filename).stem, budget=budget)
            entry = import_custom_character_zip_bytes(
                converted, Path(filename).stem, budget)
        except ValueError as e:
            return {
                'success': False,
                'type': 'mex_fighter_yml',
                'error': f'Classic fighter package could not be converted: {_client_error(e)}'
            }, 400
        message = (f"Imported custom character: {entry['name']} "
                   f"(converted from classic m-ex format)")
        if conv_info.get('warnings'):
            message += ' — ' + '; '.join(conv_info['warnings'][:3])
        return {
            'success': True,
            'type': 'custom_character',
            'converted_from': 'fighter_yml',
            'character': entry,
            'conversion': conv_info,
            'message': message
        }, 200

    # PHASE 0.5: container recursion. A zip that carries other archives
    # (the "one giant zip of my skin folder" case) previously imported only
    # its loose dats and silently ignored every inner zip. Recurse instead.
    if (recurse_containers and depth < MAX_CONTAINER_DEPTH
            and mod_type is None and shallow['type'] not in _PACKAGE_TYPES):
        container = _import_container_archive(
            temp_zip_path, filename,
            slippi_action=slippi_action,
            duplicate_action=duplicate_action,
            custom_title=custom_title,
            depth=depth, budget=budget)
        if container is not None:
            return container

    # PHASE 1: Try character detection first
    logger.info("Phase 1: Attempting character detection...")
    character_infos = detect_character_from_zip(temp_zip_path)

    if character_infos:
        logger.info(f"[OK] Detected {len(character_infos)} character costume(s)")

        # SLIPPI VALIDATION: Check if any costume needs slippi validation dialog
        if slippi_action is None:
            # First time upload - validate slippi safety
            unsafe_costumes = []
            with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                for char_info in character_infos:
                    # Extract DAT to temp file for validation
                    dat_data = zip_ref.read(char_info['dat_file'])
                    with tempfile.NamedTemporaryFile(suffix='.dat', delete=False) as tmp_dat:
                        tmp_dat.write(dat_data)
                        tmp_dat_path = tmp_dat.name

                    try:
                        validation = validate_for_slippi(tmp_dat_path, auto_fix=False)
                        if not validation['slippi_safe']:
                            unsafe_costumes.append({
                                'character': char_info['character'],
                                'color': char_info['color']
                            })
                    finally:
                        os.unlink(tmp_dat_path)

            # If any costume is not slippi safe, ask user what to do
            if unsafe_costumes:
                return {
                    'success': False,
                    'type': 'slippi_dialog',
                    'unsafe_costumes': unsafe_costumes,
                    'message': 'This costume is not Slippi safe. Choose an action:'
                }, 200

        # DUPLICATE DETECTION: Check if any costume already exists (by
        # DAT hash). A ZIP can contain several costumes, so "skip"
        # filters matching entries and keeps importing the rest.
        skipped_duplicate_count = 0
        skipped_duplicates = []
        if duplicate_action != 'import_anyway':
            # Run the check-and-backfill under one locked read-modify-write.
            # check_duplicate_skin caches computed dat_hash values onto
            # existing skins in `metadata`; persisting that via a bare,
            # unlocked save_metadata on a stale snapshot could clobber a
            # concurrent import (lost update). metadata_transaction re-reads
            # under metadata_lock and writes atomically, so only the hash
            # backfill is merged and nothing else is lost.
            duplicate_skins = []
            duplicate_dat_files = set()
            with metadata_transaction(default={'characters': {}, 'stages': {}}) as metadata:
                with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                    for char_info in character_infos:
                        dat_data = zip_ref.read(char_info['dat_file'])
                        dat_hash = compute_dat_hash(dat_data)

                        existing_skin = check_duplicate_skin(char_info['character'], dat_hash, metadata)
                        if existing_skin:
                            duplicate_dat_files.add(char_info['dat_file'])
                            # Build CSP URL for preview
                            csp_url = f"/storage/{char_info['character']}/{existing_skin['id']}_csp.png"
                            duplicate_skins.append({
                                'character': char_info['character'],
                                'color': char_info['color'],
                                'existing_skin': {
                                    'id': existing_skin['id'],
                                    'name': f"{char_info['character']} - {existing_skin.get('color', existing_skin['id'])}",
                                    'csp_url': csp_url
                                }
                            })

            # On the first pass, ask what to do. On a Skip retry,
            # remove only the duplicates and continue through the ZIP.
            if duplicate_skins:
                if duplicate_action is None:
                    return {
                        'success': False,
                        'type': 'duplicate_dialog',
                        'duplicate_skins': duplicate_skins,
                        'message': 'You already have this skin!'
                    }, 200
                if duplicate_action == 'skip':
                    character_infos = [
                        info for info in character_infos
                        if info['dat_file'] not in duplicate_dat_files
                    ]
                    skipped_duplicate_count = len(duplicate_dat_files)
                    skipped_duplicates = duplicate_skins

        # Sort Ice Climbers: Popo before Nana (Nana copies Popo's CSP)
        def ice_climbers_sort_key(char_info):
            if char_info.get('is_popo'):
                return 0  # Popo first
            elif char_info.get('is_nana'):
                return 1  # Nana second
            else:
                return 0  # Other characters

        character_infos_sorted = sorted(character_infos, key=ice_climbers_sort_key)

        # Determine auto_fix setting based on user choice
        auto_fix = (slippi_action == 'fix')

        # Special fighters (Giga Bowser, the wireframes, the hands, Sandbag)
        # have no tile in the Characters grid: their costumes belong to the
        # matching custom character. Filing them under `characters` produced
        # the phantom "G" tab a bulk-imported Bowser pack left behind.
        from vault.catalog.custom_character_skins import SPECIAL_FIGHTER_NAMES, add_special_fighter_costume
        special_infos = [ci for ci in character_infos_sorted
                         if ci['character'] in SPECIAL_FIGHTER_NAMES]
        character_infos_sorted = [ci for ci in character_infos_sorted
                                  if ci['character'] not in SPECIAL_FIGHTER_NAMES]
        routed_special = []
        skipped_special = []
        if special_infos:
            with zipfile.ZipFile(temp_zip_path, 'r') as source_zip:
                for ci in special_infos:
                    buf = io.BytesIO()
                    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as costume_zip:
                        costume_zip.writestr(Path(ci['dat_file']).name, source_zip.read(ci['dat_file']))
                        if ci.get('csp_file'):
                            costume_zip.writestr('csp.png', source_zip.read(ci['csp_file']))
                        if ci.get('stock_file'):
                            costume_zip.writestr('stc.png', source_zip.read(ci['stock_file']))
                    skin_name = ci.get('color') if ci.get('color') not in (None, '', 'Unknown Color') \
                        else Path(ci['dat_file']).stem
                    with metadata_transaction(default={'characters': {}, 'stages': {},
                                                       'custom_characters': []}) as metadata:
                        skin_entry, reason = add_special_fighter_costume(
                            metadata, ci['character'], buf.getvalue(), skin_name)
                    if skin_entry:
                        routed_special.append({'character': ci['character'], 'color': skin_name,
                                               'id': skin_entry['id'], 'slug': skin_entry['slug'],
                                               'custom_character': True})
                    else:
                        skipped_special.append({'character': ci['character'],
                                                'file': Path(ci['dat_file']).name, 'reason': reason})
                        logger.warning(f"Special fighter costume not imported: {ci['dat_file']}: {reason}")
        if not character_infos_sorted and not routed_special:
            if skipped_duplicate_count and not skipped_special:
                # Every costume in this archive is already in the vault. That
                # is the duplicate skipping the preview promised, not a failed
                # import (2026-09-22 review MM, 3).
                names = ', '.join(sorted(
                    f"{d['character']} {d['color']}" for d in skipped_duplicates)) or 'them'
                return {
                    'success': True,
                    'type': 'character',
                    'imported_count': 0,
                    'skipped_count': skipped_duplicate_count,
                    'skipped_duplicates': skipped_duplicates,
                    'costumes': [],
                    'message': f'Already in your vault, so nothing was added: {names}',
                }, 200
            reasons = '; '.join(sorted({s['reason'] for s in skipped_special})) or 'no importable costume'
            return {'success': False, 'error': reasons,
                    'skipped_special': skipped_special}, 422

        # Import each detected costume
        results = list(routed_special)
        fixed_count = 0
        imported_skin_ids = {}  # Track actual skin IDs: costume_code -> skin_id
        should_play_camera_sound = False
        for character_info in character_infos_sorted:
            logger.info(f"  - Importing {character_info['character']} - {character_info['color']}")
            logger.info(f"[DEBUG] Calling import_character_costume with custom_name='{custom_title}'")
            result = import_character_costume(temp_zip_path, character_info, filename, auto_fix=auto_fix, custom_name=custom_title)
            if result.get('success'):
                should_play_camera_sound = should_play_camera_sound or result.get('camera_sound', False)
                if result.get('slippi_fixed'):
                    fixed_count += 1
                results.append({
                    'character': character_info['character'],
                    'id': result.get('skin_id'),
                    'color': character_info['color'],
                    'csp_source': result.get('csp_source')
                })
                # Track the actual skin ID that was created
                if result.get('skin_id'):
                    imported_skin_ids[character_info['costume_code']] = result['skin_id']

        # Post-process: Fix Ice Climbers pairing with actual skin IDs
        pairing_complete = None
        if any(ci.get('is_popo') or ci.get('is_nana') for ci in character_infos_sorted):
            pairing_complete = bool(fix_ice_climbers_pairing(character_infos_sorted, imported_skin_ids))

        message = f"Imported {len(results)} costume(s)"
        if fixed_count:
            message += f"; auto-fixed {fixed_count} for Slippi"
        if skipped_duplicate_count:
            message += f"; skipped {skipped_duplicate_count} already owned"

        return {
            'success': True,
            'type': 'character',
            'camera_sound': should_play_camera_sound,
            'imported_count': len(results),
            **({'pairing_complete': pairing_complete} if pairing_complete is not None else {}),
            'skipped_count': skipped_duplicate_count,
            'skipped_duplicates': skipped_duplicates,
            'fixed_count': fixed_count,
            'costumes': results,
            'message': message
        }, 200

    # PHASE 2: Try stage detection
    logger.info("Phase 2: Attempting stage detection...")
    stage_infos = detect_stage_from_zip(temp_zip_path)

    if stage_infos:
        logger.info(f"[OK] Detected {len(stage_infos)} stage mod(s)")

        # DUPLICATE DETECTION for stages. Like costumes: first pass asks,
        # a 'skip' retry drops only the owned variants and imports the rest.
        skipped_stage_count = 0
        skipped_duplicates = []
        if duplicate_action != 'import_anyway':
            stage_metadata = load_metadata(default={'characters': {}, 'stages': {}})

            duplicate_skins = []
            duplicate_stage_files = set()
            with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                for stage_info in stage_infos:
                    dat_data = zip_ref.read(stage_info['stage_file'])
                    dat_hash = compute_dat_hash(dat_data)
                    existing = check_duplicate_stage(stage_info['folder'], dat_hash, stage_metadata)
                    if existing:
                        duplicate_stage_files.add(stage_info['stage_file'])
                        screenshot_url = (
                            f"/storage/das/{stage_info['folder']}/{existing['screenshot_filename']}"
                            if existing.get('screenshot_filename') else None
                        )
                        duplicate_skins.append({
                            'character': stage_info['stage_name'],
                            'color': existing['name'],
                            'existing_skin': {
                                'id': existing['id'],
                                'name': f"{stage_info['stage_name']} - {existing['name']}",
                                'csp_url': screenshot_url
                            }
                        })
            if duplicate_skins:
                if duplicate_action is None:
                    return {
                        'success': False,
                        'type': 'duplicate_dialog',
                        'mod_type': 'stage',
                        'duplicate_skins': duplicate_skins,
                        'message': 'You already have this stage!'
                    }, 200
                if duplicate_action == 'skip':
                    stage_infos = [
                        info for info in stage_infos
                        if info['stage_file'] not in duplicate_stage_files
                    ]
                    skipped_stage_count = len(duplicate_stage_files)
                    skipped_duplicates = duplicate_skins

        # Import each detected stage. Stages imported without a bundled
        # screenshot stay previewless on purpose — previews are generated
        # via the bulk DAS "capture screenshots" flow, which is far less
        # disruptive than booting Dolphin once per stage during import.
        results = []
        for stage_info in stage_infos:
            logger.info(f"  - Importing {stage_info['stage_name']}")
            result = import_stage_mod(temp_zip_path, stage_info, filename, custom_name=custom_title)
            if result.get('success'):
                results.append({
                    'stage': stage_info['stage_name'],
                    'variant': result.get('variant_id')
                })

        message = f"Imported {len(results)} stage variant(s)"
        if skipped_stage_count:
            message += f"; skipped {skipped_stage_count} already owned"

        return {
            'success': True,
            'type': 'stage',
            'imported_count': len(results),
            'skipped_count': skipped_stage_count,
            'skipped_duplicates': skipped_duplicates,
            'stages': results,
            'message': message
        }, 200

    # PHASE 2.5: raw vanilla-stage dats the stage detector did not claim.
    # Every versus stage is a vault stage skin now (Phase 2), so this only
    # fires for archives the detector rejected outright; it wraps the dat
    # into an ADDED m-ex custom stage (own SSS entry, vanilla untouched).
    logger.info("Phase 2.5: Attempting vanilla-stage dat detection...")
    vanilla_entries = import_vanilla_stage_dats(
        temp_zip_path, Path(filename).stem, custom_title=custom_title)
    if vanilla_entries:
        names = ', '.join(e['name'] for e in vanilla_entries)
        logger.info(f"[OK] Imported {len(vanilla_entries)} vanilla-stage mod(s): {names}")
        return {
            'success': True,
            'type': 'custom_stage',
            'converted_from': 'vanilla_stage_dat',
            'imported_count': len(vanilla_entries),
            'stage': vanilla_entries[0],
            'custom_stages': vanilla_entries,
            'message': f"Imported as custom stage(s): {names}"
        }, 200

    # PHASE 3: Try patch (xdelta) detection
    logger.info("Phase 3: Attempting patch detection...")
    try:
        with zipfile.ZipFile(temp_zip_path, 'r') as zf:
            xdelta_files = [n for n in zf.namelist() if n.lower().endswith('.xdelta')]
            image_exts = {'.png', '.jpg', '.jpeg', '.gif'}
            image_files = [n for n in zf.namelist()
                           if Path(n).suffix.lower() in image_exts
                           and not n.startswith('__MACOSX')]

            if xdelta_files:
                logger.info(f"[OK] Detected {len(xdelta_files)} xdelta patch(es)")
                xdelta_dir = STORAGE_PATH / "xdelta"
                xdelta_dir.mkdir(exist_ok=True)

                patches = load_xdelta_metadata()
                results = []
                skipped_patch_count = 0
                skipped_duplicates = []

                for xdelta_name in xdelta_files:
                    # Read data first for duplicate check and writing
                    xdelta_data = zf.read(xdelta_name)
                    file_hash = compute_dat_hash(xdelta_data)

                    # DUPLICATE DETECTION for patches
                    if duplicate_action != 'import_anyway':
                        existing = check_duplicate_patch(file_hash, patches)
                        if existing:
                            screenshot_url = f"/storage/xdelta/{existing['id']}.png"
                            duplicate_detail = {
                                'character': 'Patch',
                                'color': existing['name'],
                                'existing_skin': {
                                    'id': existing['id'],
                                    'name': existing['name'],
                                    'csp_url': screenshot_url
                                }
                            }
                            if duplicate_action == 'skip':
                                skipped_patch_count += 1
                                skipped_duplicates.append(duplicate_detail)
                                continue
                            return {
                                'success': False,
                                'type': 'duplicate_dialog',
                                'mod_type': 'patch',
                                'duplicate_skins': [duplicate_detail],
                                'message': 'You already have this patch!'
                            }, 200

                    patch_id = str(uuid.uuid4())[:8]

                    # Save xdelta file
                    xdelta_path = xdelta_dir / f"{patch_id}.xdelta"
                    xdelta_path.write_bytes(xdelta_data)

                    # Save first image as screenshot
                    if image_files:
                        img_data = zf.read(image_files[0])
                        img_path = xdelta_dir / f"{patch_id}.png"
                        img_path.write_bytes(img_data)

                    # Derive name from custom_title, xdelta filename, or zip filename
                    patch_name = custom_title or Path(xdelta_name).stem or Path(filename).stem
                    patch_name = sanitize_filename(patch_name)

                    patches.append({
                        'id': patch_id,
                        'name': patch_name,
                        'description': '',
                        'filename': Path(xdelta_name).name,
                        'created': datetime.now().isoformat(),
                        'file_hash': file_hash
                    })
                    results.append({'id': patch_id, 'name': patch_name})
                    logger.info(f"  - Imported patch: {patch_name} ({patch_id})")

                save_xdelta_metadata(patches)

                message = f"Imported {len(results)} patch(es)"
                if skipped_patch_count:
                    message += f"; skipped {skipped_patch_count} already owned"

                return {
                    'success': True,
                    'type': 'patch',
                    'imported_count': len(results),
                    'skipped_count': skipped_patch_count,
                    'skipped_duplicates': skipped_duplicates,
                    'patches': results,
                    'message': message
                }, 200
    except zipfile.BadZipFile:
        pass  # Not a valid zip, fall through to error

    # PHASE 4: Try CSS icon grid detection
    logger.info('Phase 4: Attempting CSS icon grid detection...')
    # `shallow` also recognises a character-select file by its root symbol,
    # so a MnSlChr saved under any name ("Halo3CSS.dat") reaches the same
    # icon-grid-or-background question as one called MnSlChr.
    if looks_like_icon_grid_zip(temp_zip_path) or shallow['type'] == 'css_icon_grid':
        if _mnslchr_is_ambiguous(shallow):
            # A compiled MnSlChr carries the icons AND the backdrop; without
            # loose icon PNGs nothing says which one the user wants.
            return _choice_dialog(
                filename,
                'This file is a whole character select screen. Import it as:',
                [
                    {'key': 'css_icon_grid', 'label': 'Icon grid',
                     'description': 'The character icons from this screen.',
                     'hints': {'mod_type': 'css_icon_grid'}},
                    {'key': 'css_background', 'label': 'CSS background',
                     'description': "The screen's backdrop model and animation.",
                     'hints': {'mod_type': 'css_background'}},
                ],
                default='css_icon_grid')
        logger.info('[OK] Detected CSS icon grid mod')
        try:
            icon_grid_name = custom_title or Path(filename).stem
            mods = install_icon_grid_mod(temp_zip_path, name=icon_grid_name)
            names = ', '.join(m.get('name', '?') for m in mods)
            return {
                'success': True,
                'type': 'menu_mod',
                'menu_mod_type': 'css_icon_grid',
                'mods': mods,
                'imported_count': len(mods),
                'message': _located(f"Imported {len(mods)} icon grid mod(s): {names}", 'css_icon_grid')
            }, 200
        except (zipfile.BadZipFile, RuntimeError):
            pass

    # PHASE 4.5: Try pause screen (GmPause) detection
    logger.info('Phase 4.5: Attempting pause screen detection...')
    if looks_like_pause_zip(temp_zip_path):
        logger.info('[OK] Detected pause screen mod')
        try:
            pause_name = custom_title or Path(filename).stem
            mods = install_pause_mods_from_zip(temp_zip_path, name=pause_name)
            names = ', '.join(m.get('name', '?') for m in mods)
            return {
                'success': True,
                'type': 'menu_mod',
                'menu_mod_type': 'pause_screen',
                'mods': mods,
                'imported_count': len(mods),
                'message': _located(f"Imported {len(mods)} pause screen mod(s): {names}", 'pause_screen')
            }, 200
        except (zipfile.BadZipFile, RuntimeError):
            pass

    # PHASE 4.6: Try percent font / HUD (IfAll) detection
    logger.info('Phase 4.6: Attempting percent font detection...')
    if looks_like_percent_zip(temp_zip_path):
        logger.info('[OK] Detected percent font mod')
        try:
            percent_name = custom_title or Path(filename).stem
            mods = install_percent_mods_from_zip(temp_zip_path, name=percent_name)
            return _percent_result(mods), 200
        except (zipfile.BadZipFile, RuntimeError):
            pass

    # PHASE 5: nothing matched the import pipelines. Run the full
    # classifier once more for an actionable answer — either a
    # late-dispatchable type (SSS background) or a specific
    # explanation instead of a generic "could not detect".
    logger.info('Phase 5: Running full classification for diagnosis...')
    verdict = detect_content_type(temp_zip_path, filename, deep=True)
    vtype = verdict['type']
    detail = verdict['detail']

    if vtype == 'css_background':
        logger.info('[OK] Detected menu background source (MnSlMap/MnSlChr)')
        menu_type = 'sss' if detail.get('source') == 'sss' else 'css'
        return _import_background(temp_zip_path, filename, menu_type, custom_title)

    if vtype in ('css_doors', 'pause_picture', 'effect_image'):
        # Loose pictures are never filed on a guess: a PNG could be a door,
        # a pause picture, a shield, a shine image, or none of these. Ask,
        # with the detector's best reading preselected. The Menus page's
        # per-kind "+" cards send an explicit mod_type and skip this.
        return _image_choice_dialog(filename, verdict)

    if vtype == 'percent_font':
        # loose glyph / word packs the name-based installer check missed
        try:
            mods = install_percent_mods_from_zip(temp_zip_path,
                                                 name=custom_title or Path(filename).stem)
            return _percent_result(mods), 200
        except (zipfile.BadZipFile, RuntimeError) as e:
            return {'success': False, 'error': str(e)}, 400

    if vtype == 'effect':
        return _import_detected_effects(temp_zip_path, filename, detail,
                                        custom_title, duplicate_action)

    explanations = {
        'character_renamed': lambda d: (
            'This contains costume file(s) with non-standard names — detected '
            + ', '.join(f"{c['character']} ({c['costume_code']}) in {c['dat']}"
                        for c in d.get('costumes', []))
            + '. Rename each file to its costume code (e.g. '
            + (d.get('costumes') or [{}])[0].get('costume_code', 'PlFxNr')
            + '.dat) and import again.'),
        'custom_fighter_costume': lambda d: (
            'This looks like a costume for a custom fighter (not a vanilla '
            'character): ' + ', '.join(d.get('dats', []))
            + '. Add it to a custom character via Custom Characters → Add Skin.'),
        'ic_half': lambda d: (
            f"This zip only contains {d.get('half', 'one')}-half Ice Climbers "
            'costumes. Popo and Nana must be imported together — select both '
            'zips at once, or use a zip that contains the matching '
            f"{'Nana' if d.get('half') == 'popo' else 'Popo'} file."),
        'music': lambda d: (
            'This contains .hps music track(s). Music import from the vault '
            'is not supported yet — add tracks to a build via stage playlists.'),
        'dolphin_textures': lambda d: (
            'This is a Dolphin texture pack (tex1_*.png). It belongs in '
            "Slippi Dolphin's Load/Textures folder, not the vault."),
        'sound_bank': lambda d: (
            'This contains sound bank files (.spk/.ssm), which are not yet '
            'importable on their own.'),
        'unsupported_audio': lambda d: (
            'This contains regular audio files ('
            + ', '.join(d.get('extensions', [])) +
            '). Melee needs .hps audio — convert tracks first.'),
        'effect_unsupported': lambda d: (
            'This looks like an effect mod for '
            + ', '.join(d.get('characters', [])) + ' (' + ', '.join(d.get('dats', [])[:3])
            + "), but Nucleus has no editable effect in that file yet, so it can't be "
            'imported as an extra. Effects that can be imported are listed on each '
            "character's Extras page."),
        'nested_archive': lambda d: (
            'This archive only contains other archives ('
            + ', '.join(d.get('archives', [])[:5]) +
            '). Extract it and import the inner files.'),
    }

    if vtype in explanations:
        logger.info(f'Classified as {vtype} (no import pipeline)')
        return {
            'success': False,
            'type': vtype,
            'detail': {k: v for k, v in detail.items()
                       if k not in ('char_infos', 'stage_infos')},
            'error': explanations[vtype](detail)
        }, 400

    logger.warning("Could not detect mod type")
    return {
        'success': False,
        'type': 'unknown',
        'error': 'Could not detect mod type. ZIP does not contain any recognized files (.dat, .xdelta, GrXx stage files)'
    }, 400


def _import_container_archive(temp_zip_path, filename, *, slippi_action,
                              duplicate_action, custom_title, depth, budget=None):
    """Handle a container archive: recurse into every inner archive, then
    import the container's own loose content, and aggregate everything.

    Returns None when the archive has no inner archives (not a container —
    the caller continues with the normal cascade). Otherwise returns
    (payload, status) with type='multi'.

    A container import is a batch, so dialogs are answered automatically the
    same way the frontend answers them for multi-file selections: Slippi
    issues are fixed, owned duplicates are skipped — and the summary message
    says so.
    """
    inner = _list_inner_archives(temp_zip_path)
    if not inner:
        return None

    logger.info(f"[OK] Container archive: {len(inner)} inner archive(s) in {filename}")
    slippi_action = slippi_action or 'fix'
    duplicate_action = duplicate_action or 'skip'

    imported_total = 0
    skipped_total = 0
    skipped_duplicates = []
    fixed_total = 0
    types = set()
    units = []
    costumes = []
    failed = []

    def accumulate(name, payload, status):
        nonlocal imported_total, skipped_total, fixed_total
        if payload.get('success'):
            count = payload.get('imported_count', 1)
            imported_total += count
            skipped_total += payload.get('skipped_count', 0)
            skipped_duplicates.extend(payload.get('skipped_duplicates', []))
            fixed_total += payload.get('fixed_count', 0)
            costumes.extend(payload.get('costumes', []))
            if payload.get('type') == 'multi':
                types.update(payload.get('types', []))
                failed.extend(payload.get('failed', []))
            elif count:
                types.add(payload.get('type'))
            units.append({'name': name, 'type': payload.get('type'),
                          'imported_count': count,
                          'skipped_count': payload.get('skipped_count', 0)})
        else:
            failed.append({'name': name,
                           'type': payload.get('type'),
                           'error': payload.get('error') or payload.get('message')
                           or 'import failed'})

    for member in inner:
        base = Path(member).name
        suffix = Path(member).suffix.lower()
        if suffix == '.rar' and not rar_available():
            failed.append({'name': base, 'type': 'rar',
                           'error': 'the bundled UnRAR tool is missing — extract it and import the contents'})
            continue

        data = _read_member(temp_zip_path, member)
        if not data:
            failed.append({'name': base, 'type': 'unreadable',
                           'error': 'could not be read from the archive'})
            continue

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            inner_path = tmp.name
        del data
        if suffix in ('.7z', '.rar'):
            # The remaining allowance, not a fresh one: these extractors run
            # inside py7zr/UnRAR, so this is where their bounds are set.
            bounds = budget.archive_limits() if budget is not None else None
            converted = (_convert_7z_to_temp_zip(inner_path, limits=bounds) if suffix == '.7z'
                         else rar_to_temp_zip(inner_path, limits=bounds) if bounds
                         else rar_to_temp_zip(inner_path))
            try:
                os.unlink(inner_path)
            except OSError:
                pass
            if not converted:
                # Handing the raw archive to the cascade only yields a
                # BadZipFile traceback and a "could not detect" message.
                failed.append({'name': base, 'type': suffix.lstrip('.'),
                               'error': f'could not be opened as a {suffix.lstrip(".")} archive'})
                continue
            inner_path = converted
        try:
            payload, status = _import_single_archive(
                inner_path, base,
                slippi_action=slippi_action,
                duplicate_action=duplicate_action,
                depth=depth + 1, budget=budget)
        except Exception as e:
            logger.error(f"Container inner import failed for {base}: {e}", exc_info=True)
            payload, status = {'success': False, 'error': str(e)}, 500
        finally:
            try:
                os.unlink(inner_path)
            except OSError:
                pass
        accumulate(base, payload, status)

    # Loose content sitting next to the inner archives (stray dats, xdeltas,
    # menu files...) goes through the normal cascade once, recursion off.
    try:
        payload, status = _import_single_archive(
            temp_zip_path, filename,
            slippi_action=slippi_action,
            duplicate_action=duplicate_action,
            custom_title=custom_title,
            depth=depth + 1,
            recurse_containers=False, budget=budget)
    except Exception as e:
        logger.error(f"Container loose-content import failed: {e}", exc_info=True)
        payload, status = {'success': False, 'error': str(e)}, 500
    # 'unknown' / 'nested_archive' here just means the container had no loose
    # importable content besides the inner archives — not a failure.
    if payload.get('success') or payload.get('type') not in _NO_CONTENT_TYPES:
        accumulate('(loose files)', payload, status)

    success = imported_total > 0 or (skipped_total > 0 and not failed)
    parts = [f"Imported {imported_total} item(s) from {filename}"]
    if fixed_total:
        parts.append(f"auto-fixed {fixed_total} costume(s) for Slippi")
    if skipped_total:
        parts.append(f"skipped {skipped_total} already owned")
    if failed:
        sample = '; '.join(f"{f['name']}: {f['error']}" for f in failed[:3])
        parts.append(f"{len(failed)} file(s) not imported ({sample}"
                     + (', …)' if len(failed) > 3 else ')'))
    message = ' — '.join(parts)
    logger.info(f"Container import done: {message}")

    return {
        'success': success,
        'type': 'multi',
        'types': sorted(t for t in types if t),
        'imported_count': imported_total,
        'skipped_count': skipped_total,
        'skipped_duplicates': skipped_duplicates,
        'fixed_count': fixed_total,
        'units': units,
        'costumes': costumes,
        'failed': failed,
        'message': message
    }, (200 if success else 400)
