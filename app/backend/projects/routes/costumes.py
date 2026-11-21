"""
Costumes Blueprint - Costume import/remove/reorder routes for MEX project.

Handles importing costumes from storage, removing costumes, and reordering them.
"""

import json
import time
import logging
from contextlib import contextmanager
import tempfile
import zipfile
import hashlib
from pathlib import Path
from flask import Blueprint, request, jsonify

from core.config import PROJECT_ROOT, VANILLA_ASSETS_DIR, STORAGE_PATH
from core.constants import CHAR_PREFIXES, VANILLA_CSS_COLOR_ORDER, vanilla_costume_specs
from core.state import get_mex_manager, reload_mex_manager, mexcli_lock, get_current_project_path
from core.metadata import load_metadata
from core.active_portrait import prepare_install_zip

# Import MexManagerError for proper exception handling
from mexcli.project import MexManagerError

# On sys.path via core.config's PROCESSOR_DIR insert
from falcon_neutralize import convert_falcon_zip
from projects.install.project_fighters import vanilla_replacement_target

logger = logging.getLogger(__name__)


@contextmanager
def _workspace_write(label):
    """Hold the build for a MexCLI command that opens and SAVES the workspace.

    Every one of these rewrites the whole project in one pass. `mexcli_lock`
    alone only serialises writers inside THIS process, so a second Nucleus
    backend could save over a guarded transaction; and none of them can be
    undone file by file, so the save is bracketed in the build's journal and a
    death in the middle quarantines the build instead of leaving it half saved.
    """
    from core import build_access
    project_path = get_current_project_path()
    if project_path is None:
        with mexcli_lock:
            yield None
        return
    with build_access.build_session(Path(project_path).parent, timeout=120.0) as session:
        with session.external_save(label):
            yield session


# Falcon's vanilla skeleton differs per color slot, so non-neutral costumes
# desync on Slippi netplay. Every Falcon install is normalized to the neutral
# color via a temp copy -- the vault zip itself is never touched. The name
# gate only avoids unzipping other fighters; the converter is content-driven
# and leaves non-Falcon DATs alone regardless.
FALCON_FIGHTER = 'C. Falcon'

costumes_bp = Blueprint('costumes', __name__)


def _replacement_context(fighter, index):
    from projects.install.project_fighters import find_fighter_json_by_name
    project = get_current_project_path()
    path, data = find_fighter_json_by_name(fighter)
    if project is None or path is None:
        raise ValueError('Open a project containing this fighter')
    rows = data.get('costumes', [])
    if not 0 <= index < len(rows):
        raise ValueError('The costume slot no longer exists')
    row = rows[index]
    flat = {'fileName': (row.get('file') or {}).get('fileName'),
            'replacesVanillaFile': row.get('replacesVanillaFile')}
    target = vanilla_replacement_target(fighter, flat)
    if target is None:
        raise ValueError('Select a vanilla costume slot')
    version = hashlib.sha256(str(project.resolve()).encode() + path.read_bytes())
    if fighter == 'Ice Climbers':
        nana_path, _ = find_fighter_json_by_name('Nana')
        if nana_path is not None:
            version.update(nana_path.read_bytes())
    digest = version.hexdigest()
    return project, flat['fileName'], target, digest


@costumes_bp.route('/api/mex/replace-vanilla/<fighter>/<int:index>', methods=['GET', 'POST'])
def replace_vanilla_costume(fighter, index):
    """Replace one existing slot (and optionally its paired Nana) in one save."""
    temporary = []
    try:
        with mexcli_lock:
            project, expected, target, version = _replacement_context(fighter, index)
            if request.method == 'GET':
                return jsonify(success=True, version=version, target=target)
            data = request.get_json(silent=True)
            if not isinstance(data, dict) or data.get('version') != version:
                return jsonify(success=False, error='The project or costume changed. Select Replace again.'), 409
            entries = [(fighter, data.get('costumePath'), expected, target)]
            if fighter == 'Ice Climbers' and data.get('pairedCostumePath'):
                _, nana_file, nana_target, _ = _replacement_context('Nana', index)
                entries.append(('Nana', data['pairedCostumePath'], nana_file, nana_target))
            with tempfile.TemporaryDirectory(prefix='nucleus_slot_replace_') as td:
                manifest = []
                for character, source, old_file, destination in entries:
                    if not isinstance(source, str):
                        raise ValueError('Choose a costume from the vault')
                    archive_path = (PROJECT_ROOT / source).resolve()
                    if not archive_path.is_relative_to(STORAGE_PATH.resolve()) or not archive_path.is_file():
                        raise ValueError('The selected vault costume is unavailable')
                    portrait = prepare_install_zip(archive_path, load_metadata())
                    if portrait is not None:
                        temporary.append(portrait)
                    prepared = Path(td) / f'{len(manifest)}.zip'
                    with zipfile.ZipFile(portrait or archive_path) as src:
                        dats = [item for item in src.infolist() if Path(item.filename).suffix.lower() in ('.dat', '.usd')]
                        if len(dats) != 1:
                            raise ValueError('Choose a vault package containing one costume')
                        dat = dats[0]
                        stem = Path(dat.filename).stem
                        prefix = CHAR_PREFIXES[character]
                        colors = VANILLA_CSS_COLOR_ORDER[character]
                        # Match the fighter only, and ignore casing -- a mod ships its
                        # DAT as PlKpWh.dat or plkpwh.dat with equal enthusiasm.
                        if not stem.lower().startswith(f'Pl{prefix}'.lower()):
                            raise ValueError(f'The selected costume does not match {character}')
                        # A costume keeps the visibility lookup of the colour it was
                        # authored for, so a model built for one vanilla slot still shows
                        # the right parts in another. A colour this fighter never shipped
                        # (PlKpWh / PlKpYe -- Bowser has only Nr/Re/Bu/Bk) has no lookup
                        # to inherit, so it takes the one for the slot it lands in.
                        code = stem[4:6].capitalize()
                        visibility = colors.index(code) if code in colors else destination['visibilityIndex']
                        dat_bytes = src.read(dat)
                        if character == FALCON_FIGHTER:
                            from falcon_neutralize import convert_falcon_to_color
                            dat_bytes = convert_falcon_to_color(dat_bytes, destination['color'])
                            visibility = destination['visibilityIndex']
                        with zipfile.ZipFile(prepared, 'w', zipfile.ZIP_DEFLATED) as out:
                            for item in src.infolist():
                                out.writestr(item, dat_bytes if item == dat else src.read(item))
                    manifest.append({'fighter': character, 'index': index,
                                     'expectedFile': old_file, 'vanillaFile': destination['file'],
                                     'path': str(prepared), 'visibilityIndex': visibility})
                if get_current_project_path() != project:
                    return jsonify(success=False, error='Project changed. Select Replace again.'), 409
                path = Path(td) / 'manifest.json'
                path.write_text(json.dumps(manifest), encoding='utf-8')
                result = get_mex_manager()._run_command('replace-costume', str(project), str(path))
                reload_mex_manager()
                return jsonify(success=True, result=result)
    except (ValueError, FileNotFoundError, zipfile.BadZipFile) as exc:
        return jsonify(success=False, error=str(exc)), 400
    except Exception as exc:
        logger.exception('Vanilla slot replacement failed')
        return jsonify(success=False, error=str(exc)), 500
    finally:
        for path in temporary:
            path.unlink(missing_ok=True)


_VANILLA_COSTUME_NAMES = {
    'Nr': 'Normal', 'Re': 'Red', 'Bu': 'Blue', 'Gr': 'Green',
    'Ye': 'Yellow', 'Bk': 'Black', 'Wh': 'White', 'Pi': 'Pink',
    'Or': 'Orange', 'La': 'Purple', 'Aq': 'Aqua', 'Gy': 'Gray',
}

# Vanilla team selections are not always the literal red/blue/green costume
# filenames (Mario, Peach, Luigi, Marth, etc. use different defaults).
_VANILLA_TEAM_SLOTS = {
    'Mario': (0, 3, 4), 'Fox': (1, 2, 3), 'C. Falcon': (2, 5, 4),
    'DK': (2, 3, 4), 'Kirby': (3, 2, 4), 'Bowser': (1, 2, 0),
    'Link': (1, 2, 0), 'Sheik': (1, 2, 3), 'Ness': (0, 2, 3),
    'Peach': (0, 3, 4), 'Ice Climbers': (3, 0, 1),
    'Pikachu': (1, 2, 3), 'Samus': (0, 4, 3), 'Yoshi': (1, 2, 0),
    'Jigglypuff': (1, 2, 3), 'Mewtwo': (1, 2, 3),
    'Luigi': (3, 2, 0), 'Marth': (1, 0, 2), 'Zelda': (1, 2, 3),
    'Young Link': (1, 2, 0), 'Dr. Mario': (1, 2, 3),
    'Falco': (1, 2, 3), 'Pichu': (1, 2, 3),
    'Mr. Game & Watch': (1, 2, 3), 'Ganondorf': (1, 2, 3),
    'Roy': (1, 2, 3),
}

_VANILLA_RESET_PAIRS = {
    'Zelda': ('Zelda', 'Sheik'),
    'Sheik': ('Zelda', 'Sheik'),
    'Ice Climbers': ('Ice Climbers', 'Nana'),
}

_GAW_COLORS = (
    ('#FF000000', '#80FFFFFF'),
    ('#FF6E0000', '#80FFFFFF'),
    ('#FF00006E', '#80FFFFFF'),
    ('#FF006E00', '#80FFFFFF'),
)
_GAW_COSTUME_NAMES = ('Black', 'Red', 'Blue', 'Green')


def _build_vanilla_costume_package(temp_dir, character, color, slot):
    """Create one ordinary MexCostume ZIP from the user's extracted vanilla set."""
    prefix = CHAR_PREFIXES.get(character)
    if not prefix:
        raise ValueError(f'No vanilla costume mapping for {character}')

    code = f'Pl{prefix}{color}'
    costume_dir = VANILLA_ASSETS_DIR / character / code
    dat_path = costume_dir / f'{code}.dat'
    csp_path = costume_dir / 'csp.png'
    stock_path = costume_dir / 'stock.png'

    if not dat_path.exists():
        raise FileNotFoundError(
            f'Vanilla costume {dat_path.name} is unavailable. '
            'Refresh vanilla assets in Settings and try again.')

    gaw_sidecar = None
    if character == 'Mr. Game & Watch':
        # G&W's four vanilla colors share one DAT; color lives in the MxDt row.
        # Generate the correctly colored portraits/icons from the pristine model.
        from shared.rendering.costume_assets import build_csp_and_stock
        assets = build_csp_and_stock(
            character,
            code,
            dat_path.read_bytes(),
            color_index=slot,
            allow_stock_gen=False,
        )
        csp_bytes = assets.get('csp')
        stock_bytes = assets.get('stock')
        fill, outline = _GAW_COLORS[slot]
        gaw_sidecar = {'fill': fill, 'outline': outline}
    else:
        csp_bytes = csp_path.read_bytes() if csp_path.exists() else None
        stock_bytes = stock_path.read_bytes() if stock_path.exists() else None
        if character == 'Nana' and (not csp_bytes or not stock_bytes):
            # Nana has no separate portrait/icon files in the extracted
            # vanilla set. Her costume slots use the paired Popo artwork,
            # matching the canonical Ice Climbers import path.
            popo_color = VANILLA_CSS_COLOR_ORDER['Ice Climbers'][slot]
            popo_code = f"Pl{CHAR_PREFIXES['Ice Climbers']}{popo_color}"
            popo_dir = VANILLA_ASSETS_DIR / 'Ice Climbers' / popo_code
            popo_csp = popo_dir / 'csp.png'
            popo_stock = popo_dir / 'stock.png'
            if not csp_bytes and popo_csp.exists():
                csp_bytes = popo_csp.read_bytes()
            if not stock_bytes and popo_stock.exists():
                stock_bytes = popo_stock.read_bytes()

    if not csp_bytes or not stock_bytes:
        raise FileNotFoundError(
            f'Vanilla portraits for {character} {color} are unavailable. '
            'Refresh vanilla assets in Settings and try again.')

    safe_name = character.lower().replace(' ', '-').replace('&', 'and')
    package_path = Path(temp_dir) / f'{safe_name}-{slot}.zip'
    with zipfile.ZipFile(package_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.write(dat_path, dat_path.name)
        archive.writestr('csp.png', csp_bytes)
        archive.writestr('stock.png', stock_bytes)
        if gaw_sidecar:
            archive.writestr('gaw.json', json.dumps(gaw_sidecar))

    return {
        'path': str(package_path),
        'name': (_GAW_COSTUME_NAMES[slot]
                 if character == 'Mr. Game & Watch'
                 else _VANILLA_COSTUME_NAMES.get(color, color)),
        'visibilityIndex': slot,
    }


def _build_vanilla_reset_manifest(temp_dir, requested_character):
    targets = _VANILLA_RESET_PAIRS.get(
        requested_character, (requested_character,))
    fighters = []
    for character in targets:
        specs = vanilla_costume_specs(character)
        if not specs:
            raise ValueError(f'{character} does not have a vanilla costume set')

        entry = {
            'fighter': character,
            'costumes': [
                _build_vanilla_costume_package(
                    temp_dir, character, color, slot)
                for color, slot in specs
            ],
        }
        team = _VANILLA_TEAM_SLOTS.get(character)
        if team:
            entry.update({
                'redCostumeIndex': team[0],
                'blueCostumeIndex': team[1],
                'greenCostumeIndex': team[2],
            })
        fighters.append(entry)
    return {'fighters': fighters}, list(targets)


@costumes_bp.route('/api/mex/restore-vanilla-costumes', methods=['POST'])
def restore_vanilla_costumes():
    """Reset one vanilla fighter (or its required pair) to every vanilla skin."""
    data = request.get_json(silent=True) or {}
    character = data.get('fighter')
    if not character or character == 'Nana' or (
            character not in VANILLA_CSS_COLOR_ORDER
            and character != 'Mr. Game & Watch'):
        return jsonify({
            'success': False,
            'error': 'A supported vanilla fighter is required',
        }), 400

    try:
        with tempfile.TemporaryDirectory(
                prefix='nucleus_vanilla_costumes_') as temp_dir:
            manifest, affected = _build_vanilla_reset_manifest(
                temp_dir, character)
            with _workspace_write('mexcli reset-vanilla-costumes'):
                mex = get_mex_manager()
                result = mex.reset_vanilla_costumes(manifest)
                reload_mex_manager()
        return jsonify({
            'success': True,
            'affectedFighters': affected,
            'result': result,
        })
    except MexManagerError as e:
        logger.error('Vanilla costume reset failed: %s', e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    except Exception as e:
        logger.error('Vanilla costume reset failed: %s', e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@costumes_bp.route('/api/mex/import', methods=['POST'])
def import_costume():
    """
    Import costume to MEX project

    Body:
    {
        "fighter": "Fox",
        "costumePath": "storage/Fox/PlFxNr_custom/PlFxNr_custom.zip"
    }
    """
    try:
        data = request.json
        fighter_name = data.get('fighter')
        costume_path = data.get('costumePath')

        logger.info(f"=== IMPORT REQUEST ===")
        logger.info(f"Fighter: {fighter_name}")
        logger.info(f"Costume Path: {costume_path}")
        logger.info(f"Request Data: {json.dumps(data, indent=2)}")

        if not fighter_name or not costume_path:
            logger.error("Missing fighter or costumePath parameter")
            return jsonify({
                'success': False,
                'error': 'Missing fighter or costumePath parameter'
            }), 400

        # Resolve costume path relative to project root
        full_costume_path = PROJECT_ROOT / costume_path

        logger.info(f"Full costume path: {full_costume_path}")
        logger.info(f"Path exists: {full_costume_path.exists()}")

        if not full_costume_path.exists():
            logger.error(f"Costume ZIP not found: {costume_path}")
            return jsonify({
                'success': False,
                'error': f'Costume ZIP not found: {costume_path}'
            }), 404

        # NOTE on Ice Climbers: do NOT bundle the Popo and Nana DATs into
        # one zip here. MexCLI's import-costume treats each `.dat` it finds
        # in a zip as a NEW costume entry, not as halves of one slot — so
        # a bundled zip with PlPpBu + PlNnBu under fighter="Ice Climbers"
        # ends up with the second DAT overwriting the first slot's Popo
        # half (game shows the Nana skin on both halves of the pair).
        # The frontend (CharacterMode.jsx:533-589) already handles IC by
        # making two separate calls: Popo zip → fighter "Ice Climbers",
        # Nana zip → fighter "Nana" (internalId 11, which is MexCLI's view
        # onto the Nana half of the IC slot). That's the correct path.
        logger.info(f"Calling MexCLI to import costume...")
        temp_zip = None
        portrait_zip = None
        try:
            if fighter_name == FALCON_FIGHTER:
                temp_zip = convert_falcon_zip(full_costume_path)
            install_path = temp_zip or full_costume_path
            # The zip's csp.png is only ever the ORIGINAL portrait; ship the
            # one the user made active in Portraits (temp copy, vault untouched).
            portrait_zip = prepare_install_zip(
                full_costume_path, load_metadata(), source_zip=install_path)
            if portrait_zip is not None:
                install_path = portrait_zip
            with _workspace_write('mexcli import-costume'):
                mex = get_mex_manager()
                result = mex.import_costume(fighter_name, str(install_path))

                logger.info(f"Import result: {json.dumps(result, indent=2)}")

                # Small delay to ensure file system has flushed the write
                time.sleep(0.15)

                # Force reload to pick up file changes for subsequent requests
                reload_mex_manager()
                logger.info(f"Reloaded MEX manager to pick up changes")
        finally:
            for t in (temp_zip, portrait_zip):
                if t is not None:
                    try:
                        t.unlink()
                    except OSError:
                        pass

        logger.info(f"=== IMPORT COMPLETE ===")

        return jsonify({
            'success': True,
            'result': result
        })
    except MexManagerError as e:
        logger.error(f"MexManagerError: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'Unexpected error: {str(e)}'
        }), 500


@costumes_bp.route('/api/mex/import-batch', methods=['POST'])
def import_costumes_batch():
    """
    Batch-import many costumes in ONE workspace save -- ~2x faster than calling
    /import N times (each of those re-runs the full project recompile). The result
    is byte-identical to N sequential imports.

    Body:
    {
        "items": [
            {"fighter": "Fox",   "costumePath": "storage/Fox/.../a.zip"},
            {"fighter": "Falco", "costumePath": "storage/Falco/.../b.zip"}
        ]
    }
    """
    temp_zips = []
    try:
        data = request.json or {}
        items = data.get('items') or []
        if not items:
            return jsonify({'success': False, 'error': 'No items provided'}), 400

        manifest = {}
        metadata = load_metadata()
        for it in items:
            fighter_name = it.get('fighter')
            costume_path = it.get('costumePath')
            if not fighter_name or not costume_path:
                return jsonify({'success': False,
                                'error': 'Each item needs fighter and costumePath'}), 400
            full_costume_path = PROJECT_ROOT / costume_path
            if not full_costume_path.exists():
                return jsonify({'success': False,
                                'error': f'Costume ZIP not found: {costume_path}'}), 404
            install_path = full_costume_path
            if fighter_name == FALCON_FIGHTER:
                converted = convert_falcon_zip(full_costume_path)
                if converted:
                    temp_zips.append(converted)
                    install_path = converted
            # Ship the portrait the user made active in Portraits (see /import).
            portrait_zip = prepare_install_zip(
                full_costume_path, metadata, source_zip=install_path)
            if portrait_zip is not None:
                temp_zips.append(portrait_zip)
                install_path = portrait_zip
            manifest.setdefault(fighter_name, []).append(str(install_path))

        logger.info(f"=== BATCH IMPORT ({sum(len(v) for v in manifest.values())} costumes, "
                    f"{len(manifest)} fighters) ===")
        with _workspace_write('mexcli import-costumes'):
            mex = get_mex_manager()
            result = mex.import_costumes(manifest)
            time.sleep(0.15)
            reload_mex_manager()
        return jsonify({'success': True, 'result': result})
    except MexManagerError as e:
        logger.error(f"Batch import MexManagerError: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    except Exception as e:
        logger.error(f"Batch import error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        # Neutralized temps must outlive the mexcli call (it re-checks paths)
        for t in temp_zips:
            try:
                t.unlink()
            except OSError:
                pass


@costumes_bp.route('/api/mex/remove', methods=['POST'])
def remove_costume():
    """
    Remove costume from MEX project

    Body:
    {
        "fighter": "Fox",
        "costumeIndex": 3
    }
    """
    try:
        data = request.json
        fighter_name = data.get('fighter')
        costume_index = data.get('costumeIndex')

        logger.info(f"=== REMOVE REQUEST ===")
        logger.info(f"Fighter: {fighter_name}")
        logger.info(f"Costume Index: {costume_index}")

        if fighter_name is None or costume_index is None:
            logger.error("Missing fighter or costumeIndex parameter")
            return jsonify({
                'success': False,
                'error': 'Missing fighter or costumeIndex parameter'
            }), 400

        # Validate costume index
        if not isinstance(costume_index, int) or costume_index < 0:
            logger.error(f"Invalid costume index: {costume_index}")
            return jsonify({
                'success': False,
                'error': 'costumeIndex must be a non-negative integer'
            }), 400

        logger.info(f"Calling MexCLI to remove costume...")
        with _workspace_write('mexcli remove-costume'):
            mex = get_mex_manager()
            result = mex.remove_costume(fighter_name, costume_index)

            logger.info(f"Remove result: {json.dumps(result, indent=2)}")

            # Force reload to pick up file changes for subsequent requests
            reload_mex_manager()
            logger.info(f"Reloaded MEX manager to pick up changes")

        logger.info(f"=== REMOVE COMPLETE ===")

        return jsonify({
            'success': True,
            'result': result
        })
    except MexManagerError as e:
        logger.error(f"MexManagerError: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'Unexpected error: {str(e)}'
        }), 500


@costumes_bp.route('/api/mex/remove-batch', methods=['POST'])
def remove_costumes_batch():
    """
    Batch-remove many costumes in ONE workspace save -- ~Nx faster than calling
    /remove N times. Same final costume set as N sequential removes (the generated
    IfAll stock-icon file can differ in HSD layout but is functionally identical;
    stock icons are regenerated from the final costume set).

    Body:
    {
        "items": [
            {"fighter": "Fox",  "costumeIndex": 5},
            {"fighter": "Nana", "costumeIndex": 3}
        ]
    }
    """
    try:
        data = request.json or {}
        items = data.get('items') or []
        if not items:
            return jsonify({'success': False, 'error': 'No items provided'}), 400

        manifest = {}
        for it in items:
            fighter_name = it.get('fighter')
            costume_index = it.get('costumeIndex')
            if fighter_name is None or costume_index is None:
                return jsonify({'success': False,
                                'error': 'Each item needs fighter and costumeIndex'}), 400
            if not isinstance(costume_index, int) or costume_index < 0:
                return jsonify({'success': False,
                                'error': 'costumeIndex must be a non-negative integer'}), 400
            manifest.setdefault(fighter_name, []).append(costume_index)

        logger.info(f"=== BATCH REMOVE ({sum(len(v) for v in manifest.values())} costumes, "
                    f"{len(manifest)} fighters) ===")
        with _workspace_write('mexcli remove-costumes'):
            mex = get_mex_manager()
            result = mex.remove_costumes(manifest)
            time.sleep(0.15)
            reload_mex_manager()
        return jsonify({'success': True, 'result': result})
    except MexManagerError as e:
        logger.error(f"Batch remove MexManagerError: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    except Exception as e:
        logger.error(f"Batch remove error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@costumes_bp.route('/api/mex/reorder', methods=['POST'])
def reorder_costume():
    """
    Reorder costume in MEX project (swap positions)

    Body:
    {
        "fighter": "Fox",
        "fromIndex": 2,
        "toIndex": 0
    }

    Note: For Ice Climbers (Popo), paired Nana costumes are automatically reordered
    """
    try:
        data = request.json
        fighter_name = data.get('fighter')
        from_index = data.get('fromIndex')
        to_index = data.get('toIndex')

        logger.info(f"=== REORDER REQUEST ===")
        logger.info(f"Fighter: {fighter_name}")
        logger.info(f"From Index: {from_index}")
        logger.info(f"To Index: {to_index}")

        if fighter_name is None or from_index is None or to_index is None:
            logger.error("Missing fighter, fromIndex, or toIndex parameter")
            return jsonify({
                'success': False,
                'error': 'Missing fighter, fromIndex, or toIndex parameter'
            }), 400

        # Validate indices
        if not isinstance(from_index, int) or from_index < 0:
            logger.error(f"Invalid from_index: {from_index}")
            return jsonify({
                'success': False,
                'error': 'fromIndex must be a non-negative integer'
            }), 400

        if not isinstance(to_index, int) or to_index < 0:
            logger.error(f"Invalid to_index: {to_index}")
            return jsonify({
                'success': False,
                'error': 'toIndex must be a non-negative integer'
            }), 400

        logger.info(f"Calling MexCLI to reorder costume...")
        # Hold the workspace lock for the whole open+save+reload so a concurrent
        # export/import/remove can't run a second MexCLI process on the project.
        with _workspace_write('mexcli reorder-costume'):
            mex = get_mex_manager()
            result = mex.reorder_costume(fighter_name, from_index, to_index)

            logger.info(f"Reorder result: {json.dumps(result, indent=2)}")

            # Force reload to pick up file changes for subsequent requests
            reload_mex_manager()
            logger.info(f"Reloaded MEX manager to pick up changes")

        logger.info(f"=== REORDER COMPLETE ===")

        return jsonify({
            'success': True,
            'result': result
        })
    except MexManagerError as e:
        logger.error(f"MexManagerError: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'Unexpected error: {str(e)}'
        }), 500


@costumes_bp.route('/api/mex/reorder-batch', methods=['POST'])
def reorder_costumes_batch():
    """
    Batch-reorder costumes in ONE workspace save.

    A move here is a SPLICE (remove + insert), which is what a drag actually does.
    /reorder only swaps, so the UI had to replay one drag as |to-from| adjacent
    swaps -- |to-from| full project recompiles (~3s each) for a single drag. This
    endpoint takes the whole queue of drags and pays ONE recompile for all of them.

    Moves apply in the order given, each against the list as it stands after the
    previous move (a faithful replay of the user's drags).

    Body:
    {
        "moves": [
            {"fighter": "Fox",   "fromIndex": 15, "toIndex": 0},
            {"fighter": "Falco", "fromIndex": 2,  "toIndex": 1}
        ]
    }

    Note: Ice Climbers (Popo/Nana), Kirby hats and G&W color rows are moved in
    lockstep by MexCLI, same as /reorder.
    """
    try:
        data = request.json or {}
        moves = data.get('moves') or []
        if not moves:
            return jsonify({'success': False, 'error': 'No moves provided'}), 400

        manifest = {}
        for mv in moves:
            fighter_name = mv.get('fighter')
            from_index = mv.get('fromIndex')
            to_index = mv.get('toIndex')
            if fighter_name is None or from_index is None or to_index is None:
                return jsonify({'success': False,
                                'error': 'Each move needs fighter, fromIndex and toIndex'}), 400
            if not isinstance(from_index, int) or from_index < 0:
                return jsonify({'success': False,
                                'error': 'fromIndex must be a non-negative integer'}), 400
            if not isinstance(to_index, int) or to_index < 0:
                return jsonify({'success': False,
                                'error': 'toIndex must be a non-negative integer'}), 400
            manifest.setdefault(fighter_name, []).append([from_index, to_index])

        logger.info(f"=== BATCH REORDER ({len(moves)} moves, {len(manifest)} fighters) ===")
        with _workspace_write('mexcli reorder-costumes'):
            mex = get_mex_manager()
            result = mex.reorder_costumes(manifest)
            time.sleep(0.15)
            reload_mex_manager()
        logger.info(f"=== BATCH REORDER COMPLETE ===")
        return jsonify({'success': True, 'result': result})
    except MexManagerError as e:
        logger.error(f"Batch reorder MexManagerError: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    except Exception as e:
        logger.error(f"Batch reorder error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
