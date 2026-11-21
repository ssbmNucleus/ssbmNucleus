"""
Custom character franchise and fighter assets (vault editing): the series a
fighter belongs to (a vanilla one, or a custom series carried from its source
build with its own icon), the icon and result banners inside fighter.zip, and
fighter properties (wall jump, team colors). Changes are mirrored into the
fighter.zip that install reads.

Registers on `custom_characters_bp` (vault/routes/custom_characters/__init__.py).
"""

import json
import zipfile
import logging
from flask import request, jsonify, send_file

import file_retry
from core.config import CUSTOM_CHARACTERS_PATH
from core.images import normalized_png
from vault.catalog.custom_characters import (
    FIGHTER_ASSET_SPECS, SERIES_NAMES, _find_entry, _read_metadata, _rewrite_fighter_zip,
    _series_icon_path, _update_fighter_json_everywhere, _write_metadata,
)

from . import custom_characters_bp

logger = logging.getLogger(__name__)


# ============= Franchise / series =============

@custom_characters_bp.route('/api/mex/custom-characters/series-list', methods=['GET'])
def list_series():
    series = []
    for i, name in enumerate(SERIES_NAMES):
        series.append({
            'id': i,
            'name': name,
            'icon_url': f"/api/mex/custom-characters/series-icon/{i}" if _series_icon_path(i) else None,
        })
    return jsonify({'success': True, 'series': series})


@custom_characters_bp.route('/api/mex/custom-characters/series-icon/<int:series_id>', methods=['GET'])
def get_series_icon(series_id):
    p = _series_icon_path(series_id)
    if p:
        return send_file(p, mimetype='image/png')
    return jsonify({'success': False, 'error': 'Series icon not found'}), 404


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/set-series', methods=['POST'])
def set_custom_character_series(slug):
    """Change a custom character's franchise (seriesID)."""
    try:
        data = request.json or {}
        series_id = data.get('seriesId')
        if not isinstance(series_id, int) or not (0 <= series_id < len(SERIES_NAMES)):
            return jsonify({'success': False, 'error': f'seriesId must be 0..{len(SERIES_NAMES) - 1}'}), 400

        char_dir = CUSTOM_CHARACTERS_PATH / slug
        fighter_json_path = char_dir / 'fighter.json'
        if not fighter_json_path.exists():
            return jsonify({'success': False, 'error': 'Character not found'}), 404

        with open(fighter_json_path, 'r', encoding='utf-8') as f:
            fighter_data = json.load(f)
        fighter_data['seriesID'] = series_id
        with file_retry.retry_locked(open, fighter_json_path, 'w', encoding='utf-8') as f:
            json.dump(fighter_data, f, indent=2)

        def _set_series(meta):
            meta['seriesID'] = series_id
            return meta
        _rewrite_fighter_zip(char_dir, mutate_json=_set_series)

        metadata = _read_metadata()
        entry = _find_entry(metadata, slug)
        if entry is not None:
            entry['series_id'] = series_id
            # Picking a vanilla franchise turns the custom one off (it can
            # be reactivated from the picker without rescanning)
            if entry.get('custom_series'):
                entry['custom_series']['active'] = False
            _write_metadata(metadata)

        logger.info(f"[OK] Set {slug} series to {series_id} ({SERIES_NAMES[series_id]})")
        return jsonify({
            'success': True,
            'series_id': series_id,
            'series_name': SERIES_NAMES[series_id],
            'series_icon_url': f"/api/mex/custom-characters/series-icon/{series_id}" if _series_icon_path(series_id) else None,
        })
    except Exception as e:
        logger.error(f"Set series error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# ============= Fighter assets + properties (vault editing) =============

@custom_characters_bp.route('/api/mex/custom-characters/<slug>/zip-asset/<which>', methods=['GET'])
def get_fighter_zip_asset(slug, which):
    """Serve a fixed-name asset (result banners) straight out of fighter.zip."""
    spec = FIGHTER_ASSET_SPECS.get(which)
    if spec is None:
        return jsonify({'success': False, 'error': f'Unknown asset {which}'}), 400
    entry_name = spec[0]
    zip_path = CUSTOM_CHARACTERS_PATH / slug / 'fighter.zip'
    if not zip_path.exists():
        return jsonify({'success': False, 'error': 'fighter.zip not found'}), 404
    with zipfile.ZipFile(zip_path) as zf:
        for n in zf.namelist():
            if n.split('/')[-1].lower() == entry_name:
                import io
                from flask import Response
                return Response(zf.read(n), mimetype='image/png')
    return jsonify({'success': False, 'error': f'{entry_name} not in fighter.zip'}), 404


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/replace-asset/<which>', methods=['POST'])
def replace_fighter_asset(slug, which):
    """Replace the CSS icon or a result banner with an uploaded image.
    Writes the fighter.zip entry (what installs read) and, for the icon,
    the vault display copy css_icon.png."""
    try:
        spec = FIGHTER_ASSET_SPECS.get(which)
        if spec is None:
            return jsonify({'success': False, 'error': f'Unknown asset {which}'}), 400
        entry_name, size = spec

        char_dir = CUSTOM_CHARACTERS_PATH / slug
        if not (char_dir / 'fighter.zip').exists():
            return jsonify({'success': False, 'error': 'Character not found'}), 404
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400

        raw = request.files['file'].read()
        try:
            png = normalized_png(raw, size)
        except Exception:
            return jsonify({'success': False, 'error': 'File is not a valid image'}), 400

        _rewrite_fighter_zip(char_dir, replace_entries={entry_name: png})
        if which == 'icon':
            (char_dir / 'css_icon.png').write_bytes(png)
            metadata = _read_metadata()
            entry = _find_entry(metadata, slug)
            if entry is not None:
                entry['has_css_icon'] = True
                _write_metadata(metadata)

        logger.info(f"[OK] Replaced {which} asset for {slug}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Replace fighter asset error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/set-wall-jump', methods=['POST'])
def set_wall_jump(slug):
    try:
        char_dir = CUSTOM_CHARACTERS_PATH / slug
        if not (char_dir / 'fighter.json').exists():
            return jsonify({'success': False, 'error': 'Character not found'}), 404
        data = request.get_json(silent=True) or {}
        value = bool(data.get('canWallJump'))

        def _set(meta):
            meta['canWallJump'] = value
        _update_fighter_json_everywhere(char_dir, _set)

        logger.info(f"[OK] Set {slug} canWallJump = {value}")
        return jsonify({'success': True, 'can_wall_jump': value})
    except Exception as e:
        logger.error(f"Set wall jump error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/set-team-colors', methods=['POST'])
def set_team_colors(slug):
    """Assign which bundled costume each team color uses in team battles.
    Body: {red, blue, green} — bundled costume indexes."""
    try:
        char_dir = CUSTOM_CHARACTERS_PATH / slug
        fighter_json = char_dir / 'fighter.json'
        if not fighter_json.exists():
            return jsonify({'success': False, 'error': 'Character not found'}), 404
        data = request.get_json(silent=True) or {}

        with open(fighter_json, 'r', encoding='utf-8') as f:
            costume_count = len(json.load(f).get('costumes', []))

        indexes = {}
        for team in ('red', 'blue', 'green'):
            if team not in data:
                continue
            try:
                idx = int(data[team])
            except (TypeError, ValueError):
                return jsonify({'success': False, 'error': f'{team} must be a costume index'}), 400
            if not (0 <= idx < costume_count):
                return jsonify({'success': False,
                                'error': f'{team} index {idx} out of range (0..{costume_count - 1})'}), 400
            indexes[team] = idx
        if not indexes:
            return jsonify({'success': False, 'error': 'Provide red, blue and/or green'}), 400

        def _set(meta):
            for team, idx in indexes.items():
                meta[f'{team}CostumeIndex'] = idx
        _update_fighter_json_everywhere(char_dir, _set)

        logger.info(f"[OK] Set {slug} team colors = {indexes}")
        return jsonify({'success': True, 'team_colors': indexes})
    except Exception as e:
        logger.error(f"Set team colors error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/custom-series-icon', methods=['GET'])
def get_custom_series_icon(slug):
    p = CUSTOM_CHARACTERS_PATH / slug / 'series_icon.png'
    if p.exists():
        return send_file(p, mimetype='image/png')
    return jsonify({'success': False, 'error': 'Custom series icon not found'}), 404


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/replace-series-icon', methods=['POST'])
def replace_series_icon(slug):
    """Upload a PNG as this character's franchise icon. Creates/activates a
    custom series; at install it is added to the target project."""
    try:
        char_dir = CUSTOM_CHARACTERS_PATH / slug
        if not (char_dir / 'fighter.json').exists():
            return jsonify({'success': False, 'error': 'Character not found'}), 404
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400

        uploaded = request.files['file']
        raw = uploaded.read()
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(raw))
            img.load()
        except Exception:
            return jsonify({'success': False, 'error': 'File is not a valid image'}), 400
        # The in-game asset is an 80x64 I4 texture — normalize so it encodes well
        if img.size != (80, 64):
            img = img.convert('RGBA').resize((80, 64), Image.LANCZOS)
        img.save(char_dir / 'series_icon.png')

        metadata = _read_metadata()
        entry = _find_entry(metadata, slug)
        if entry is None:
            return jsonify({'success': False, 'error': 'Character not found in metadata'}), 404

        cs = entry.get('custom_series') or {'source_id': entry.get('series_id')}
        name = (request.form.get('name') or '').strip()
        if name:
            cs['name'] = name
        elif not cs.get('name'):
            cs['name'] = f"{entry.get('name', slug)} Series"
        cs['active'] = True
        cs['has_icon'] = True
        entry['custom_series'] = cs
        _write_metadata(metadata)

        logger.info(f"[OK] Replaced franchise icon for {slug} (series '{cs['name']}')")
        return jsonify({'success': True, 'custom_series': {
            'name': cs.get('name'),
            'active': True,
            'source_id': cs.get('source_id'),
            'icon_url': f"/api/mex/custom-characters/{slug}/custom-series-icon",
        }})
    except Exception as e:
        logger.error(f"Replace series icon error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/set-series-custom', methods=['POST'])
def set_series_custom(slug):
    """Activate (or rename) the character's custom franchise."""
    try:
        metadata = _read_metadata()
        entry = _find_entry(metadata, slug)
        if entry is None:
            return jsonify({'success': False, 'error': 'Character not found'}), 404

        cs = entry.get('custom_series')
        icon_exists = (CUSTOM_CHARACTERS_PATH / slug / 'series_icon.png').exists()
        if not cs and not icon_exists:
            return jsonify({'success': False,
                            'error': 'No custom series available — upload a franchise icon first'}), 400

        cs = cs or {'source_id': entry.get('series_id')}
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        if name:
            cs['name'] = name
        elif not cs.get('name'):
            cs['name'] = f"{entry.get('name', slug)} Series"
        cs['active'] = True
        entry['custom_series'] = cs
        _write_metadata(metadata)

        logger.info(f"[OK] Activated custom series '{cs['name']}' for {slug}")
        return jsonify({'success': True, 'custom_series': {
            'name': cs.get('name'),
            'active': True,
            'source_id': cs.get('source_id'),
            'icon_url': (f"/api/mex/custom-characters/{slug}/custom-series-icon"
                         if icon_exists else None),
        }})
    except Exception as e:
        logger.error(f"Set custom series error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
