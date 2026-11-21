"""
Custom Characters Blueprint - Manage m-ex custom fighters in the vault.

Custom characters are entirely new fighters added via m-ex. They come in
through the unified import (/api/mex/import/file: MexManager-exported ZIP
packages) or the m-ex content ISO scan (/api/mex/scan-iso/mex-content).
Each fighter is stored as:

    storage/custom_characters/<slug>/
        fighter.zip     (original ZIP preserved for re-export)
        fighter.json    (extracted metadata)
        css_icon.png    (CSS icon for grid display)
        csp_0.png ...   (per-costume CSP portraits)

Metadata is tracked under metadata.json["custom_characters"] (list of objects).

This package is the vault side. This module holds the blueprint and the
library itself: list, reorder, the m-ex content ISO scan, the staged
built-ins, detail, rename, delete and export. The rest of the
vault editing registers on the same `custom_characters_bp` from:

    skins.py    added skins, bundled costumes, default CSP pose, special fighters
    audio.py    victory theme, announcer name-call, sound bank edits
    assets.py   franchise (series), fighter.zip icon/banners, wall jump, team colors

Installing into the open project is projects/routes/custom_characters.py, also
on this blueprint. Shared non-route code: vault/catalog/custom_characters.py
(index, slugs, series, fighter.zip rewriting) and
vault/importing/custom_character_scan.py (what an ISO scan extracts).
"""

import json
import os
import re
import shutil
import tempfile
import zipfile
import logging
from pathlib import Path
from flask import Blueprint, request, jsonify, send_file

import file_retry
from core.config import (STORAGE_PATH, CUSTOM_CHARACTERS_PATH, MEXCLI_PATH, PROJECT_ROOT,
                         BACKEND_ASSETS_DIR)
import mexcli.commands
from core.helpers import friendly_iso_open_error, is_incompatible_iso_error
from core.state import metadata_lock
from core import jobs
# Slug naming, the bundled-costume meta sync and the vault's default shape are
# shared with Randall's clone adapter (vault/importing/custom_character_package.py).
from vault.importing.custom_character_package import sync_costume_meta as _sync_costume_meta
from vault.catalog.custom_characters import (FIGHTER_ASSET_SPECS, _active_csp_path_for_skin,
    _find_entry, _read_metadata, _rewrite_fighter_zip, _series_icon_path, _series_name,
    _write_metadata)
from vault.importing.custom_character_scan import _extract_custom_characters_from_project
from vault.importing.custom_character_zip import NUCLEUS_EXPORT_MARKER, NUCLEUS_EXPORT_KIND

logger = logging.getLogger(__name__)

custom_characters_bp = Blueprint('custom_characters', __name__)

CUSTOM_CHARACTERS_PATH.mkdir(parents=True, exist_ok=True)


def _storage_url(path):
    try:
        return f"/storage/{Path(path).relative_to(STORAGE_PATH).as_posix()}"
    except ValueError:
        return None


def _display_csp_url(storage_key, skin, fallback_url):
    active_path = _active_csp_path_for_skin(storage_key, skin)
    return _storage_url(active_path) if active_path else fallback_url


def _based_on_from_joint(fighter_data):
    """Derive the donor skeleton from a costume joint symbol, e.g.
    'PlyZelda5K_Share_joint' -> 'Zelda'."""
    for costume in fighter_data.get('costumes', []):
        joint = (costume.get('file') or {}).get('jointSymbol') or ''
        m = re.match(r'Ply(.+?)5K', joint)
        if m:
            return m.group(1)
    return None


@custom_characters_bp.route('/api/mex/custom-characters/list', methods=['GET'])
def list_custom_characters():
    try:
        metadata = _read_metadata()
        characters = metadata.get('custom_characters', [])
        for char in characters:
            char['icon_url'] = f"/api/mex/custom-characters/{char['slug']}/icon"
            char['has_fsm'] = (CUSTOM_CHARACTERS_PATH / char['slug'] / 'fsm.txt').exists()
        return jsonify({'success': True, 'characters': characters})
    except Exception as e:
        logger.error(f"List custom characters error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_characters_bp.route('/api/mex/custom-characters/reorder', methods=['POST'])
def reorder_custom_characters():
    """Move a custom character to a new position. The grid renders the
    metadata list in order, so reordering is just splicing that list."""
    try:
        data = request.json or {}
        from_index = data.get('fromIndex')
        to_index = data.get('toIndex')
        if not isinstance(from_index, int) or not isinstance(to_index, int):
            return jsonify({'success': False, 'error': 'fromIndex and toIndex must be integers'}), 400

        metadata = _read_metadata()
        chars = metadata.get('custom_characters', [])
        n = len(chars)
        if not (0 <= from_index < n) or not (0 <= to_index < n):
            return jsonify({'success': False, 'error': 'Index out of range'}), 400

        moved = chars.pop(from_index)
        chars.insert(to_index, moved)
        _write_metadata(metadata)

        logger.info(f"[OK] Reordered custom character '{moved['slug']}' {from_index} -> {to_index}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Reorder custom characters error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_characters_bp.route('/api/mex/scan-iso/mex-content', methods=['POST'])
def scan_iso_for_mex_content():
    """Build the temp m-ex project ONCE per ISO and extract custom characters
    and/or stages from it. Folding both into one build halves the cost of a
    bulk scan when both targets are selected (each build is a ~1-2 min
    import-iso). DAS variants are wit-based and stay on their own endpoint."""
    try:
        data = request.json or {}
        iso_path = (data.get('isoPath') or '').strip()
        want_chars = bool(data.get('characters'))
        want_stages = bool(data.get('stages'))
        if not iso_path:
            return jsonify({'success': False, 'error': 'Missing isoPath parameter'}), 400
        if not (want_chars or want_stages):
            return jsonify({'success': True})

        iso_file = Path(iso_path)
        if not iso_file.exists():
            return jsonify({'success': False, 'error': f'ISO not found: {iso_path}'}), 404
        if iso_file.suffix.lower() not in ('.iso', '.gcm'):
            return jsonify({'success': False, 'error': 'File must be an .iso or .gcm'}), 400
        if '.nkit' in iso_file.name.lower():
            logger.info(f"Skipping NKit ISO for m-ex content scan: {iso_path}")
            out = {'success': True, 'nkit': True, 'message': 'Skipped NKit ISO (not supported)'}
            if want_chars:
                out['characters'] = {'imported': [], 'skipped': [iso_file.name]}
            if want_stages:
                out['stages'] = {'imported': [], 'skipped': [iso_file.name]}
            return jsonify(out)

        mexcli_path = str(MEXCLI_PATH)
        if not Path(mexcli_path).exists():
            return jsonify({'success': False, 'error': 'MexCLI not found. Build MexCLI first.'}), 500

        # stages extractor lives in the stages blueprint; lazy import avoids a
        # module-load cycle.
        from vault.importing.custom_stage_scan import _extract_custom_stages_from_project

        temp_dir = tempfile.mkdtemp(prefix='nucleus_mex_scan_')
        try:
            result = mexcli.commands.run(['import-iso', iso_file, temp_dir, 'temp_scan'], check=False)
            if result.returncode != 0:
                err = result.stderr or result.stdout or 'Unknown error'
                # A non-vanilla/m-ex build (e.g. 20XX) isn't a failure — in a
                # bulk scan we just get what we can and move on, no error shown.
                if is_incompatible_iso_error(err):
                    logger.info(f"Skipping non-vanilla/m-ex ISO for content scan: {iso_file.name}")
                    out = {'success': True, 'incompatible': True}
                    if want_chars:
                        out['characters'] = {'imported': [], 'skipped': []}
                    if want_stages:
                        out['stages'] = {'imported': [], 'skipped': []}
                    return jsonify(out)
                logger.error(f"MexCLI import-iso failed: {err}")
                return jsonify({'success': False, 'error': friendly_iso_open_error(err)}), 500

            project_dir = Path(temp_dir)
            if not (project_dir / 'project.mexproj').exists():
                return jsonify({'success': False, 'error': 'MexCLI created project but .mexproj not found'}), 500

            # Hold the metadata lock across both extractions so a concurrent
            # import can't interleave a read-modify-write and drop entries.
            out = {'success': True}
            with metadata_lock:
                if want_chars:
                    ci, cs = _extract_custom_characters_from_project(project_dir, 'iso-scan')
                    out['characters'] = {'imported': ci, 'skipped': cs}
                if want_stages:
                    si, ss = _extract_custom_stages_from_project(project_dir, 'iso-scan')
                    out['stages'] = {'imported': si, 'skipped': ss}
            logger.info(
                f"[OK] m-ex content scan: "
                f"chars={len(out.get('characters', {}).get('imported', []))} "
                f"stages={len(out.get('stages', {}).get('imported', []))}")
            return jsonify(out)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception as e:
        logger.error(f"m-ex content ISO scan error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# ── Built-in fighters (Giga Bowser): staged at setup, built on demand ────────
# First-run setup only parks the raw inputs in storage/builtin_seed/ because the
# renders cost minutes. The grid shows the staged fighter greyed out; the first
# click runs a shared job whose status survives a window reconnect.

BUILTIN_KIND = 'builtin_character'


def _clean_builtin(name, value):
    path = Path(value)
    if name == 'recolors' and path.name.startswith('giga_recolors_') and path.exists():
        shutil.rmtree(path)


jobs.register_kind(BUILTIN_KIND, label='Built-in character setup', cleanup=_clean_builtin)


def _first_run_setup():
    # Local import: first_run_setup pulls in the CSP renderer, and this blueprint
    # is imported at app start.
    from shared.vanilla_extract.first_run_setup import FirstRunSetup
    return FirstRunSetup(PROJECT_ROOT, MEXCLI_PATH)


@custom_characters_bp.route('/api/mex/custom-characters/builtins', methods=['GET'])
def list_pending_builtin_characters():
    """Built-in fighters that are staged but not built yet, plus the state of
    any build currently running."""
    try:
        pending = _first_run_setup().builtin_pending_characters()
        for char in pending:
            char['icon_url'] = f"/api/mex/custom-characters/builtins/{char['slug']}/icon"
        for job in jobs.list_jobs(kind=BUILTIN_KIND, active=True):
            slug = job['params']['slug']
            if not any(c['slug'] == slug for c in pending):
                pending.append({'slug': slug, 'name': job['params']['name'],
                                'pending_setup': True, 'builtin': True,
                                'costume_count': job['params']['total'],
                                'has_css_icon': False})
        return jsonify({'success': True, 'builtins': pending})
    except Exception as e:
        logger.error(f"List built-in characters error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_characters_bp.route('/api/mex/custom-characters/builtins/<slug>/icon', methods=['GET'])
def get_pending_builtin_icon(slug):
    """The bundled CSS icon for a not-yet-built built-in fighter (the vault
    folder that normally serves it does not exist yet)."""
    icon_path = BACKEND_ASSETS_DIR / 'builtin' / slug / 'icon.png'
    if icon_path.exists():
        return send_file(icon_path, mimetype='image/png')
    return jsonify({'success': False, 'error': 'Icon not found'}), 404


def run_builtin_setup(job, setup, slug):
    def progress(phase, percentage, message, completed, total):
        job.check_stop()
        job.progress(percentage / 100, message, completed=completed, total=total)

    job.check_stop()
    result = setup.build_builtin_character(slug, progress, job=job)
    if not result.get('success'):
        raise RuntimeError(result.get('error') or 'Setup failed')
    return result


@custom_characters_bp.route('/api/mex/custom-characters/builtins/<slug>/setup', methods=['POST'])
def setup_builtin_character(slug):
    """Build a staged fighter; follow the returned id through the shared jobs API."""
    try:
        setup = _first_run_setup()
        pending = {c['slug']: c for c in setup.builtin_pending_characters()}
        if slug not in pending:
            return jsonify({'success': False,
                            'error': f"'{slug}' is not awaiting setup"}), 404
        char = pending[slug]
        job_id = jobs.start(BUILTIN_KIND, lambda job: run_builtin_setup(job, setup, slug),
                            single=True, critical=True,
                            params={'slug': slug, 'name': char['name'],
                                    'total': char.get('costume_count', 0)})
        return jsonify({'success': True, 'job_id': job_id})
    except jobs.JobBusy as e:
        return jsonify({'success': False, 'error': 'A built-in setup is already running',
                        'job_id': e.job_id}), 409
    except Exception as e:
        logger.error(f"Setup built-in character error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/icon', methods=['GET'])
def get_custom_character_icon(slug):
    icon_path = CUSTOM_CHARACTERS_PATH / slug / 'css_icon.png'
    if icon_path.exists():
        return send_file(icon_path, mimetype='image/png')
    return jsonify({'success': False, 'error': 'Icon not found'}), 404


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/detail', methods=['GET'])
def get_custom_character_detail(slug):
    """Return full character detail including costume info with image URLs."""
    try:
        char_dir = CUSTOM_CHARACTERS_PATH / slug
        fighter_json_path = char_dir / 'fighter.json'
        if not fighter_json_path.exists():
            return jsonify({'success': False, 'error': 'Character not found'}), 404

        with open(fighter_json_path, 'r', encoding='utf-8') as f:
            fighter_data = json.load(f)

        metadata = _read_metadata()
        entry = _find_entry(metadata, slug) or {}

        # Keep the costume mirror (costume_meta + materialized zips) in sync
        # so the shared edit stack can open bundled costumes directly
        if entry and _sync_costume_meta(entry, char_dir, fighter_data):
            _write_metadata(metadata)
        meta_by_id = {m['id']: m for m in entry.get('costume_meta', [])}

        costumes = []
        for i, costume in enumerate(fighter_data.get('costumes', [])):
            dat = (costume.get('file') or {}).get('fileName')
            stem = Path(dat).stem if dat else None
            meta = meta_by_id.get(stem, {})
            # prefer the materialized (editable) preview over the scan-time one
            if stem and (char_dir / 'costumes' / f'{stem}_csp.png').exists():
                csp_url = f"/storage/custom_characters/{slug}/costumes/{stem}_csp.png"
            elif (char_dir / f'csp_{i}.png').exists():
                csp_url = f"/api/mex/custom-characters/{slug}/csp/{i}"
            else:
                csp_url = None
            csp_url = _display_csp_url(f'custom_characters/{slug}/costumes', meta, csp_url)
            if stem and (char_dir / 'costumes' / f'{stem}_stc.png').exists():
                stock_url = f"/storage/custom_characters/{slug}/costumes/{stem}_stc.png"
            elif (char_dir / f'stock_{i}.png').exists():
                stock_url = f"/api/mex/custom-characters/{slug}/stock/{i}"
            else:
                stock_url = None
            costumes.append({
                **meta,
                'index': i,
                'edit_id': stem,
                'name': meta.get('color') or costume.get('name', f'Costume {i}'),
                'dat': dat,
                'csp_url': csp_url,
                'stock_url': stock_url,
            })

        # which fixed-name assets exist in fighter.zip (banners are only
        # in the zip; the css icon also has a vault display copy)
        zip_assets = {}
        basenames = set()
        zip_path = char_dir / 'fighter.zip'
        if zip_path.exists():
            with zipfile.ZipFile(zip_path) as zf:
                basenames = {n.split('/')[-1].lower() for n in zf.namelist()}
            for key, (entry_name, size) in FIGHTER_ASSET_SPECS.items():
                if entry_name in basenames:
                    zip_assets[key] = {
                        'url': f"/api/mex/custom-characters/{slug}/zip-asset/{key}",
                        'width': size[0],
                        'height': size[1],
                    }

        added_skins = []
        for skin in entry.get('added_skins', []):
            sid = skin['id']
            csp_url = f"/api/mex/custom-characters/{slug}/skins/{sid}/csp" if skin.get('has_csp') else None
            csp_url = _display_csp_url(f'custom_characters/{slug}/skins', skin, csp_url)
            # full entry (canonical skin fields) so the shared EditModal /
            # CSP manager stack can drive it, plus display conveniences
            added_skins.append({
                **skin,
                'name': skin.get('color') or skin.get('name') or 'Custom Skin',
                'csp_url': csp_url,
                'stock_url': f"/api/mex/custom-characters/{slug}/skins/{sid}/stock" if skin.get('has_stock') else None,
            })

        cs = entry.get('custom_series')
        custom_series = None
        if cs:
            custom_series = {
                'name': cs.get('name'),
                'active': bool(cs.get('active')),
                'source_id': cs.get('source_id'),
                'icon_url': (f"/api/mex/custom-characters/{slug}/custom-series-icon"
                             if (char_dir / 'series_icon.png').exists() else None),
            }

        series_id = fighter_data.get('seriesID', 0)
        detail = {
            'name': fighter_data.get('name', ''),
            'series_id': series_id,
            'series_name': _series_name(series_id),
            'series_icon_url': (f"/api/mex/custom-characters/series-icon/{series_id}"
                                if isinstance(series_id, int) and _series_icon_path(series_id) else None),
            'custom_series': custom_series,
            'can_wall_jump': fighter_data.get('canWallJump', False),
            'team_colors': {
                'red': fighter_data.get('redCostumeIndex', 0),
                'blue': fighter_data.get('blueCostumeIndex', 0),
                'green': fighter_data.get('greenCostumeIndex', 0),
            },
            'sound_bank': fighter_data.get('soundBank'),
            'victory_theme': fighter_data.get('victoryTheme'),
            'victory_theme_info': ({
                'name': (entry.get('victory_theme') or {}).get('name'),
                'available': (char_dir / 'victory_theme.hps').exists(),
            } if entry.get('victory_theme') else None),
            'announcer_available': (char_dir / 'announcer.wav').exists(),
            'announcer_call': fighter_data.get('announcerCall'),
            'target_test_stage': fighter_data.get('targetTestStage'),
            'based_on': _based_on_from_joint(fighter_data),
            'anim_count': (fighter_data.get('files') or {}).get('animCount'),
            'has_kirby_cap': bool((fighter_data.get('files') or {}).get('kirbyCapFileName')),
            'has_sound_pack': 'sound.zip' in basenames,
            'ending_movies': sum(1 for v in (fighter_data.get('media') or {}).values() if v),
            'costumes': costumes,
            'added_skins': added_skins,
            'default_pose': entry.get('default_pose'),
            'has_css_icon': (char_dir / 'css_icon.png').exists(),
            'icon_url': f"/api/mex/custom-characters/{slug}/icon",
            'zip_assets': zip_assets,
            'files': fighter_data.get('files', {}),
        }

        return jsonify({'success': True, 'detail': detail})
    except Exception as e:
        logger.error(f"Get custom character detail error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/csp/<int:index>', methods=['GET'])
def get_custom_character_csp(slug, index):
    csp_path = CUSTOM_CHARACTERS_PATH / slug / f'csp_{index}.png'
    if csp_path.exists():
        return send_file(csp_path, mimetype='image/png')
    return jsonify({'success': False, 'error': 'CSP not found'}), 404


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/stock/<int:index>', methods=['GET'])
def get_custom_character_stock(slug, index):
    stock_path = CUSTOM_CHARACTERS_PATH / slug / f'stock_{index}.png'
    if stock_path.exists():
        return send_file(stock_path, mimetype='image/png')
    return jsonify({'success': False, 'error': 'Stock icon not found'}), 404


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/delete', methods=['POST'])
def delete_custom_character(slug):
    try:
        char_dir = CUSTOM_CHARACTERS_PATH / slug
        if char_dir.exists():
            shutil.rmtree(char_dir)

        metadata = _read_metadata()
        metadata['custom_characters'] = [
            c for c in metadata.get('custom_characters', []) if c['slug'] != slug
        ]
        _write_metadata(metadata)

        logger.info(f"[OK] Deleted custom character '{slug}'")
        return jsonify({'success': True, 'message': f'Deleted {slug}'})
    except Exception as e:
        logger.error(f"Delete custom character error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/rename', methods=['POST'])
def rename_custom_character(slug):
    try:
        data = request.json
        new_name = data.get('newName', '').strip()
        if not new_name:
            return jsonify({'success': False, 'error': 'New name is required'}), 400

        metadata = _read_metadata()

        for existing in metadata.get('custom_characters', []):
            if existing['slug'] != slug and existing['name'].lower() == new_name.lower():
                return jsonify({'success': False, 'error': f"A character named '{existing['name']}' already exists"}), 400

        char_entry = None
        for c in metadata.get('custom_characters', []):
            if c['slug'] == slug:
                c['name'] = new_name
                char_entry = c
                break

        if not char_entry:
            return jsonify({'success': False, 'error': f'Character {slug} not found'}), 404

        fighter_json_path = CUSTOM_CHARACTERS_PATH / slug / 'fighter.json'
        if fighter_json_path.exists():
            with open(fighter_json_path, 'r', encoding='utf-8') as f:
                fighter_data = json.load(f)
            fighter_data['name'] = new_name
            with file_retry.retry_locked(open, fighter_json_path, 'w', encoding='utf-8') as f:
                json.dump(fighter_data, f, indent=2)

        # add-fighter reads the zip's own fighter.json — keep it in sync so
        # the rename survives install
        def _set_name(meta):
            meta['name'] = new_name
            return meta
        _rewrite_fighter_zip(CUSTOM_CHARACTERS_PATH / slug, mutate_json=_set_name)

        _write_metadata(metadata)

        logger.info(f"[OK] Renamed custom character '{slug}' to '{new_name}'")
        return jsonify({'success': True, 'character': char_entry})
    except Exception as e:
        logger.error(f"Rename custom character error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


def _build_full_vault_export_bytes(slug):
    """Zip the WHOLE storage/custom_characters/<slug>/ folder plus a
    nucleus_export.json marker carrying the metadata entry. Returns zip bytes,
    or None if the folder is missing. See export_custom_character for why."""
    import io
    char_dir = CUSTOM_CHARACTERS_PATH / slug
    if not char_dir.is_dir() or not (char_dir / 'fighter.json').exists():
        return None

    metadata = _read_metadata()
    entry = next((c for c in metadata.get('custom_characters', [])
                  if c.get('slug') == slug), None)
    payload = {
        'nucleus_export': NUCLEUS_EXPORT_KIND,
        'version': 1,
        'entry': entry or {'slug': slug, 'name': slug},
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(NUCLEUS_EXPORT_MARKER, json.dumps(payload, indent=2))
        for path in sorted(char_dir.rglob('*')):
            if path.is_file():
                zf.write(path, path.relative_to(char_dir).as_posix())
    return buf.getvalue()


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/export', methods=['GET'])
def export_custom_character(slug):
    """Export EVERYTHING the vault knows about a custom character.

    The old behaviour just sent the bare fighter.zip, which drops the display
    assets (csp_N.png, stock_N.png, costumes/, banners, series icon/emblem,
    fsm.txt, victory_theme.hps, announcer.wav) — so a re-import on another
    install showed "N" placeholders instead of CSPs. We now zip the WHOLE
    folder plus a nucleus_export.json marker, and the importer restores it
    verbatim. A zip without the marker is still treated as a bare fighter.zip
    (back-compat)."""
    char_dir = CUSTOM_CHARACTERS_PATH / slug
    if not char_dir.is_dir() or not (char_dir / 'fighter.json').exists():
        # imported from a project scan with no folder, or a bad slug
        zip_path = char_dir / 'fighter.zip'
        if zip_path.exists():
            return send_file(zip_path, as_attachment=True, download_name=f'{slug}.zip')
        return jsonify({'success': False, 'error': 'Custom character folder not found'}), 404

    export_bytes = _build_full_vault_export_bytes(slug)
    # Stream from the scratch temp dir; send_file reads it before the request
    # ends, so it's safe to leave for the OS to reap.
    fd, tmp_zip = tempfile.mkstemp(prefix=f'{slug}_export_', suffix='.zip')
    os.close(fd)
    Path(tmp_zip).write_bytes(export_bytes)
    return send_file(tmp_zip, as_attachment=True, download_name=f'{slug}.zip',
                     mimetype='application/zip')


# The rest of the vault editing registers on custom_characters_bp from the
# package's submodules; the install half (install into / remove from the open
# project) lives in projects/routes/custom_characters.py. Importing them here
# makes the blueprint complete before anything registers it: Flask refuses
# routes added after registration.
from . import skins  # noqa: E402,F401
from . import audio  # noqa: E402,F401
from . import assets  # noqa: E402,F401
from projects.routes import custom_characters as _project_routes  # noqa: E402,F401
