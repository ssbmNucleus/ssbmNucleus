"""
Stage Slots Blueprint -- the replace-slot stages (every versus stage that is
not one of the six DAS stages).

The six tournament stages get button-selectable alternates through the
Dynamic Alternate Stages loader (projects/routes/das.py). The other 23 versus
stages have no loader, so a skin for them is a *slot replacement*: the skin's
DAT is written straight over the vanilla root file(s) in the open project and
the vanilla file can be put back from the user's recorded ISO.

Which stages exist, their names, vault folders, dual-language roots and so on
all come from the single registry in core/stages.py -- adding a stage is one
row there, nothing here changes.

Where the skins come from: the SAME vault layout as DAS variants. A raw
``GrXx.dat`` mod for any versus stage imports (unified import ->
stage_detector -> import_stage_mod) into ``storage/das/<folder>/<id>.zip``
with metadata under ``stages.<folder>.variants``. The vault page, folders,
sort, rename, delete and export are therefore one code path for all 29
stages; this blueprint only adds the project-side install for the 23.

Slot state is derived, never stored: the project's root file is hashed and
compared against the vanilla reference and every vault skin for that code.
"""

import hashlib
import json
import logging
import re
import zipfile
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

import file_retry
from core.config import STORAGE_PATH
from core.metadata import load_metadata
from core.path_safety import validate_path_segment
from core.stages import (
    ALL_STAGES,
    LEGAL_STAGE_CODES,
    MORE_STAGE_CODES,
    VS_STAGES,
    catalog_entry,
    root_filenames,
    slot_mode,
    stage_by_code,
)
from core.state import get_current_project_path, mexcli_lock
from shared.vanilla_extract import vanilla_refs
from shared.vanilla_extract.menu_refs import stage_art_path

logger = logging.getLogger(__name__)

stage_slots_bp = Blueprint('stage_slots', __name__)

ART_KINDS = ('icon', 'banner')
_STADIUM_FORM_RE = re.compile(r'grps[1-4]\.(?:dat|usd)$', re.IGNORECASE)

# md5 cache keyed by (path, size, mtime_ns) -- vault zips and vanilla refs are
# immutable once written, so a hash is only ever recomputed after a rewrite.
_MD5_CACHE = {}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _das_dir(folder):
    # Resolved at call time so tests can repoint STORAGE_PATH on this module.
    return STORAGE_PATH / 'das' / folder


def _project_files_dir():
    """files/ of the open project, or None when no project is loaded."""
    project_path = get_current_project_path()
    if project_path is None:
        return None
    return Path(project_path).parent / 'files'


def _md5_bytes(data):
    return hashlib.md5(data).hexdigest()


def _md5_file(path):
    path = Path(path)
    try:
        st = path.stat()
    except OSError:
        return None
    key = (str(path), st.st_size, st.st_mtime_ns)
    cached = _MD5_CACHE.get(key)
    if cached:
        return cached
    h = hashlib.md5()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    digest = h.hexdigest()
    _MD5_CACHE[key] = digest
    return digest


def _find_screenshot(folder_dir, variant_id):
    """(url, ext) of a variant's vault screenshot, or (None, None)."""
    for shot in sorted(folder_dir.glob(f'{variant_id}_screenshot.*')):
        return (f"/storage/das/{folder_dir.name}/{shot.name}", shot.suffix)
    return None, None


def _select_stage_member(names, code):
    """The stage DAT inside a vault skin zip: the member naming this stage's
    code, else the only .dat/.usd that is not a Stadium transformation."""
    dats = [n for n in names
            if Path(n).suffix.lower() in ('.dat', '.usd')
            and not _STADIUM_FORM_RE.search(Path(n).name)]
    for name in dats:
        if code.lower() in Path(name).name.lower():
            return name
    return dats[0] if dats else None


def _vault_skin_dat(skin, code):
    """(bytes, md5, member) of a vault skin's stage DAT; all None if unreadable."""
    zip_path = Path(skin['zipPath'])
    if not zip_path.exists():
        return None, None, None
    try:
        with zipfile.ZipFile(zip_path) as zf:
            member = _select_stage_member(zf.namelist(), code)
            if member is None:
                return None, None, None
            data = zf.read(member)
            return data, _md5_bytes(data), member
    except (zipfile.BadZipFile, OSError, KeyError) as e:
        logger.warning(f"stage slot: unreadable vault skin {zip_path}: {e}")
        return None, None, None


def _vault_skin_md5(skin, code):
    """md5 of a vault skin's DAT, cached on the zip's identity."""
    zip_path = Path(skin['zipPath'])
    try:
        st = zip_path.stat()
    except OSError:
        return None
    key = ('skin', str(zip_path), st.st_size, st.st_mtime_ns)
    cached = _MD5_CACHE.get(key)
    if cached:
        return cached
    _data, digest, _member = _vault_skin_dat(skin, code)
    if digest:
        _MD5_CACHE[key] = digest
    return digest


def _vault_skins_for(code, metadata=None):
    """Vault skins for this stage, in the same order and from the same place
    as the DAS storage listing (storage/das/<folder>/, metadata order then
    disk-only zips)."""
    if metadata is None:
        metadata = load_metadata(default={})
    folder = ALL_STAGES[code]['folder']
    folder_dir = _das_dir(folder)
    out = []
    if not folder_dir.is_dir():
        return out
    zips = {p.stem: p for p in sorted(folder_dir.glob('*.zip'))}
    entries = (metadata.get('stages', {}).get(folder, {}) or {}).get('variants', []) or []
    for meta in entries:
        if not isinstance(meta, dict) or meta.get('type') == 'folder':
            continue
        vid = meta.get('id')
        zip_path = zips.pop(vid, None) if vid else None
        if zip_path is None:
            continue
        shot_url, _ext = _find_screenshot(folder_dir, vid)
        out.append({
            'id': vid,
            'name': meta.get('name') or vid,
            'zipPath': str(zip_path),
            'screenshotUrl': shot_url,
            'hasScreenshot': shot_url is not None,
            'slippi_safe': meta.get('slippi_safe'),
            'date_added': meta.get('date_added'),
        })
    for vid, zip_path in zips.items():
        shot_url, _ext = _find_screenshot(folder_dir, vid)
        out.append({
            'id': vid, 'name': vid, 'zipPath': str(zip_path),
            'screenshotUrl': shot_url, 'hasScreenshot': shot_url is not None,
            'slippi_safe': None, 'date_added': None,
        })
    return out


def _public_skin(skin):
    return {k: v for k, v in skin.items() if k != 'zipPath'}


def _vanilla_md5(filename):
    ref = vanilla_refs.ensure_vanilla_ref(filename)
    return _md5_file(ref) if ref else None


def _slot_state(code, files_dir, skins):
    """Describe what currently sits in the stage's root slot.

    state: 'vanilla' | 'installed' | 'modified' | 'unknown' | 'missing' | 'no-project'
    """
    if files_dir is None:
        return {'state': 'no-project', 'installed': None, 'files': []}

    roots = root_filenames(code)
    primary = files_dir / roots[0]
    files = []
    for name in roots:
        path = files_dir / name
        files.append({'name': name, 'exists': path.exists(),
                      'size': path.stat().st_size if path.exists() else 0})

    if not primary.exists():
        return {'state': 'missing', 'installed': None, 'files': files}

    current = _md5_file(primary)
    vanilla = _vanilla_md5(roots[0])
    if vanilla and current == vanilla:
        return {'state': 'vanilla', 'installed': None, 'files': files,
                'vanillaKnown': True}

    for skin in skins:
        if _vault_skin_md5(skin, code) == current:
            return {'state': 'installed', 'files': files,
                    'vanillaKnown': vanilla is not None,
                    'installed': _public_skin(skin)}

    # Not vanilla (or vanilla unknown) and not a vault skin: either the user
    # dropped a file in by hand or the vanilla ISO isn't recorded yet.
    return {'state': 'modified' if vanilla else 'unknown', 'installed': None,
            'files': files, 'vanillaKnown': vanilla is not None}


def _added_stages_for(code):
    """Custom stages in the open project that were ADDED from this vanilla
    stage (fileName GrXx.dat / GrXx_001.dat). Same shape as the
    custom-stages in-project list so the panel can reuse its remove flow."""
    project_path = get_current_project_path()
    if project_path is None:
        return []
    project_dir = Path(project_path).parent
    stages_dir = project_dir / 'data' / 'stages'
    if not stages_dir.exists() or not Path(project_path).exists():
        return []
    try:
        with open(project_path, 'r') as f:
            proj_data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []

    prefix = code.lower()
    added = []
    for i, stage_file in enumerate(proj_data.get('stageSaveMap', {}).get('filePaths', [])):
        if i <= 70:
            continue
        stage_json_path = stages_dir / stage_file
        if not stage_json_path.exists():
            continue
        try:
            with open(stage_json_path, 'r') as f:
                stage_data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        file_name = str(stage_data.get('fileName') or '').lower()
        stem = Path(file_name).stem
        if not (stem == prefix or stem.startswith(prefix + '_')):
            continue
        icon_ref = stage_data.get('assets', {}).get('icon')
        added.append({
            'index': i,
            'name': stage_data.get('name', f'Stage {i}'),
            'icon_url': f"/assets/{icon_ref.replace(chr(92), '/')}.png" if icon_ref else None,
        })
    return added


def _replace_slot_or_error(code):
    """Registry + mode guard shared by the slot routes."""
    stage = stage_by_code(code)
    if stage is None:
        return None, (jsonify({'success': False,
                               'error': f'Unknown stage code: {code}'}), 404)
    if slot_mode(code) != 'replace':
        return None, (jsonify({
            'success': False,
            'error': (f"{stage['name']} is a Dynamic Alternate Stages stage; "
                      "manage its variants through the DAS panel."),
            'reason': 'das_stage',
        }), 400)
    return stage, None


def _requested_skin(code, data):
    """Resolve the ``variantId`` of a request to a vault skin (or an error)."""
    variant_id = str(data.get('variantId') or '').strip()
    if not variant_id:
        return None, None, (jsonify({'success': False,
                                     'error': 'Missing variantId parameter'}), 400)
    try:
        validate_path_segment(variant_id, field='variant id')
    except ValueError as e:
        return None, None, (jsonify({'success': False, 'error': str(e)}), 400)
    skins = _vault_skins_for(code)
    skin = next((s for s in skins if s['id'] == variant_id), None)
    if skin is None:
        return None, skins, (jsonify({
            'success': False,
            'error': f"'{variant_id}' is not a {ALL_STAGES[code]['name']} skin in the vault",
        }), 404)
    return skin, skins, None


def _write_atomic(path, data):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_bytes(data)
    file_retry.replace(tmp, path)


def _import_custom_stage_package(package_bytes, name):
    """Vault-import a custom-stage package; split out so tests can stub it."""
    from vault.importing.custom_stage_package import import_custom_stage_zip_bytes
    return import_custom_stage_zip_bytes(package_bytes, name)


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------

@stage_slots_bp.route('/api/mex/stages/catalog', methods=['GET'])
def stages_catalog():
    """Every versus stage Nucleus knows, with its install mode and art URLs."""
    return jsonify({
        'success': True,
        'stages': [catalog_entry(s['code']) for s in VS_STAGES],
        'legal': list(LEGAL_STAGE_CODES),
        'more': list(MORE_STAGE_CODES),
    })


@stage_slots_bp.route('/api/mex/stages/slots', methods=['GET'])
def stages_slots():
    """Slot state + vault skin count for every replace-mode stage in one call
    (feeds the Stages list rows)."""
    try:
        files_dir = _project_files_dir()
        metadata = load_metadata(default={})
        slots = {}
        for code in MORE_STAGE_CODES:
            skins = _vault_skins_for(code, metadata)
            state = _slot_state(code, files_dir, skins)
            slots[code] = {
                'state': state['state'],
                'installed': state.get('installed'),
                'availableCount': len(skins),
            }
        return jsonify({'success': True, 'slots': slots})
    except Exception as e:
        logger.error(f"stage slots overview failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@stage_slots_bp.route('/api/mex/stages/<code>/slot', methods=['GET'])
def stage_slot(code):
    """Current slot content, vault skins that fit it, and stages added from it."""
    stage, error = _replace_slot_or_error(code)
    if error:
        return error
    try:
        files_dir = _project_files_dir()
        skins = _vault_skins_for(code)
        state = _slot_state(code, files_dir, skins)
        return jsonify({
            'success': True,
            'stage': catalog_entry(code),
            'slot': state,
            'available': [_public_skin(s) for s in skins],
            'added': _added_stages_for(code),
        })
    except Exception as e:
        logger.error(f"stage slot {code} failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@stage_slots_bp.route('/api/mex/stages/<code>/slot/install', methods=['POST'])
def stage_slot_install(code):
    """Write a vault skin over the stage's vanilla root file(s)."""
    stage, error = _replace_slot_or_error(code)
    if error:
        return error
    files_dir = _project_files_dir()
    if files_dir is None:
        return jsonify({'success': False,
                        'error': 'No project loaded. Open a project first.'}), 400

    skin, skins, error = _requested_skin(code, request.get_json(silent=True) or {})
    if error:
        return error

    result = _vault_skin_dat(skin, code)
    if not result or result[0] is None:
        return jsonify({'success': False,
                        'error': f"Stage file missing from vault skin '{skin['id']}'"}), 500
    payload, digest, _member = result

    try:
        files_dir.mkdir(parents=True, exist_ok=True)
        # Same lock the DAS/MexCLI paths hold: never rewrite a root file while
        # an export or reorder is walking files/.
        with mexcli_lock:
            for name in root_filenames(code):
                _write_atomic(files_dir / name, payload)
        logger.info(f"[OK] stage slot {code}: installed '{skin['name']}' "
                    f"({digest}) over {root_filenames(code)}")
        return jsonify({
            'success': True,
            'message': f"{skin['name']} is now {stage['name']}",
            'slot': _slot_state(code, files_dir, skins),
        })
    except Exception as e:
        logger.error(f"stage slot install {code}/{skin['id']} failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@stage_slots_bp.route('/api/mex/stages/<code>/slot/restore-vanilla', methods=['POST'])
def stage_slot_restore_vanilla(code):
    """Put the pristine root file(s) back from the recorded vanilla ISO."""
    stage, error = _replace_slot_or_error(code)
    if error:
        return error
    files_dir = _project_files_dir()
    if files_dir is None:
        return jsonify({'success': False,
                        'error': 'No project loaded. Open a project first.'}), 400
    try:
        sources = {}
        for name in root_filenames(code):
            ref = vanilla_refs.ensure_vanilla_ref(name)
            if ref is None:
                return jsonify({
                    'success': False,
                    'error': (f"Vanilla {name} is not available: no vanilla ISO is "
                              "recorded (run setup or open a vanilla ISO first)."),
                    'reason': 'no_vanilla_reference',
                }), 409
            sources[name] = Path(ref)

        with mexcli_lock:
            for name, ref in sources.items():
                _write_atomic(files_dir / name, ref.read_bytes())
        logger.info(f"[OK] stage slot {code}: vanilla restored ({list(sources)})")
        skins = _vault_skins_for(code)
        return jsonify({
            'success': True,
            'message': f"Vanilla {stage['name']} restored",
            'slot': _slot_state(code, files_dir, skins),
        })
    except Exception as e:
        logger.error(f"stage slot restore {code} failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@stage_slots_bp.route('/api/mex/stages/<code>/slot/add-as-stage', methods=['POST'])
def stage_slot_add_as_stage(code):
    """Wrap a vault skin as an ADDED custom-stage package (the vanilla stage's
    own code tables + SSS art, see vanilla_stage_import) and put it in the
    custom-stages vault. Returns the new package's slug; the client then
    installs it through the normal custom-stages route."""
    stage, error = _replace_slot_or_error(code)
    if error:
        return error
    skin, _skins, error = _requested_skin(code, request.get_json(silent=True) or {})
    if error:
        return error

    result = _vault_skin_dat(skin, code)
    if not result or result[0] is None:
        return jsonify({'success': False,
                        'error': f"Stage file missing from vault skin '{skin['id']}'"}), 500
    payload, _digest, member = result

    try:
        from vault.importing.vanilla_stage_import import build_vanilla_stage_package
        package, _spec = build_vanilla_stage_package(
            payload, code.lower(), skin['name'], dat_ext=Path(member).suffix.lower())
        entry = _import_custom_stage_package(package, skin['name'])
        logger.info(f"[OK] stage slot {code}: '{skin['name']}' wrapped as custom stage "
                    f"'{entry.get('slug')}'")
        return jsonify({'success': True, 'slug': entry.get('slug'),
                        'name': entry.get('name'), 'entry': entry})
    except Exception as e:
        logger.error(f"stage slot add-as-stage {code}/{skin['id']} failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@stage_slots_bp.route('/api/mex/stages/<code>/art/<kind>', methods=['GET'])
def stage_art(code, kind):
    """Vanilla SSS icon/banner for a stage, copied out of the user's own game
    at setup and on project open (shared/vanilla_extract/menu_refs.py)."""
    if stage_by_code(code) is None or kind not in ART_KINDS:
        return jsonify({'success': False, 'error': 'Unknown stage art'}), 404
    path = stage_art_path(code, kind)
    if path is None:
        return jsonify({'success': False, 'error': 'No art for this stage'}), 404
    resp = send_file(path, mimetype='image/png')
    resp.headers['Cache-Control'] = 'public, max-age=86400'
    return resp
