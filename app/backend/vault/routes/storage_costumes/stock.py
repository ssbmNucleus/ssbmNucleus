"""
A costume's stock icon: upload a replacement or generate one from the costume.

Registers on `storage_costumes_bp` (vault/routes/storage_costumes/).
"""

import zipfile
import logging
import file_retry
from pathlib import Path
from flask import jsonify, request
from core.config import STORAGE_PATH
from core.costume_files import find_costume_archive_name
from core.metadata import get_char_data, load_metadata, save_metadata
from core.atomic_archive import rewrite_zip_atomic
from . import storage_costumes_bp

logger = logging.getLogger(__name__)


@storage_costumes_bp.route('/api/mex/storage/costumes/update-stock', methods=['POST'])
def update_costume_stock():
    """Update stock icon for a character costume"""
    try:
        character = request.form.get('character')
        skin_id = request.form.get('skinId')

        if not character or not skin_id:
            return jsonify({'success': False, 'error': 'Missing character or skinId parameter'}), 400

        if 'stock' not in request.files:
            return jsonify({'success': False, 'error': 'No stock file provided'}), 400

        stock_file = request.files['stock']
        if stock_file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        if not stock_file.content_type.startswith('image/'):
            return jsonify({'success': False, 'error': 'File must be an image'}), 400

        stock_data = stock_file.read()
        char_folder = STORAGE_PATH / character
        zip_path = char_folder / f"{skin_id}.zip"
        standalone_stock = char_folder / f"{skin_id}_stc.png"

        if not zip_path.exists():
            return jsonify({'success': False, 'error': f'Costume zip not found: {skin_id}'}), 404

        with file_retry.retry_locked(open, standalone_stock, 'wb') as f:
            f.write(stock_data)

        def replace_stock(source_zip, dest_zip):
            for item in source_zip.infolist():
                if item.filename.lower() not in ['stc.png', 'stock.png', 'stock']:
                    dest_zip.writestr(item, source_zip.read(item.filename))
            dest_zip.writestr('stc.png', stock_data)
        rewrite_zip_atomic(zip_path, replace_stock)

        metadata = load_metadata()
        if metadata is not None:
            char_data = get_char_data(metadata, character)
            if char_data is not None:
                for skin in char_data.get('skins', []):
                    if skin['id'] == skin_id:
                        skin['has_stock'] = True
                        skin['stock_source'] = 'custom'
                        break

                save_metadata(metadata)

        logger.info(f"[OK] Updated stock icon for {character} - {skin_id}")
        return jsonify({'success': True, 'message': 'Stock icon updated successfully'})
    except Exception as e:
        logger.error(f"Update stock error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@storage_costumes_bp.route('/api/mex/storage/costumes/generate-stock', methods=['POST'])
def generate_costume_stock():
    """Derive a stock icon for a vault costume from its DAT's color movement
    vs the vanilla costume (shared.rendering.stock_gen).

    Two-step flow so nothing is replaced without the user's say-so:
      {character, skinId}                      -> preview: {dataUri, method},
                                                  nothing written
      {character, skinId, apply, imageData}    -> writes the previewed icon to
                                                  the zip/standalone/metadata

    `style` picks which of the two looks to build -- 'recolor' (palette-swap
    the vanilla pixel-art icon) or 'render' (crop a head out of a bind-pose
    render). Omitted = auto, which is what intake uses.
    """
    try:
        import base64

        data = request.json
        character = data.get('character')
        skin_id = data.get('skinId')

        if not character or not skin_id:
            return jsonify({'success': False, 'error': 'Missing character or skinId parameter'}), 400

        char_folder = STORAGE_PATH / character
        zip_path = char_folder / f"{skin_id}.zip"
        if not zip_path.exists():
            return jsonify({'success': False, 'error': f'Costume zip not found: {skin_id}'}), 404

        metadata = load_metadata()
        skin_meta = None
        if metadata is not None:
            char_data = get_char_data(metadata, character)
            if char_data is not None:
                skin_meta = next((s for s in char_data.get('skins', [])
                                  if s['id'] == skin_id), None)

        if data.get('apply'):
            image_data = data.get('imageData') or ''
            if ',' in image_data:
                image_data = image_data.split(',', 1)[1]
            try:
                stock_data = base64.b64decode(image_data)
            except Exception:
                stock_data = b''
            if not stock_data:
                return jsonify({'success': False, 'error': 'No previewed icon to apply'}), 400

            file_retry.retry_locked((char_folder / f"{skin_id}_stc.png").write_bytes, stock_data)
            def replace_stock(source_zip, dest_zip):
                for item in source_zip.infolist():
                    if item.filename.lower() not in ['stc.png', 'stock.png', 'stock']:
                        dest_zip.writestr(item, source_zip.read(item.filename))
                dest_zip.writestr('stc.png', stock_data)
            rewrite_zip_atomic(zip_path, replace_stock)

            if metadata is not None and skin_meta is not None:
                skin_meta['has_stock'] = True
                skin_meta['stock_source'] = 'generated'
                save_metadata(metadata)

            logger.info(f"[OK] Applied generated stock icon for {character} - {skin_id}")
            return jsonify({'success': True,
                            'stockUrl': f"/storage/{character}/{skin_id}_stc.png"})

        # preview: generate (generated-only, no vanilla fallback) via the shared
        # canonical builder; nothing is written here.
        from shared.rendering.costume_assets import build_stock
        from shared.rendering.stock_gen import STYLE_RECOLOR, STYLE_RENDER

        style = data.get('style') or None
        if style is not None and style not in (STYLE_RECOLOR, STYLE_RENDER):
            return jsonify({'success': False,
                            'error': f'Unknown stock icon style: {style}'}), 400

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            dat_filename = find_costume_archive_name(zip_ref.namelist())
            if not dat_filename:
                return jsonify({'success': False, 'error': 'No costume archive found in costume ZIP'}), 400
            dat_data = zip_ref.read(dat_filename)

        # Import names the archive '<costume_code>Mod.<ext>'
        stem = Path(dat_filename).stem
        costume_code = stem[:-3] if stem.endswith('Mod') else stem

        # only our own stored render (vanilla pose) may feed the csp-diff path
        csp_bytes = None
        if skin_meta and skin_meta.get('csp_source') == 'generated':
            csp_path = char_folder / f"{skin_id}_csp.png"
            if csp_path.exists():
                csp_bytes = csp_path.read_bytes()

        stock_data, _source, method = build_stock(
            character, costume_code, dat_data,
            aligned_csp=csp_bytes, vanilla_fallback=False, style=style)

        if stock_data is None:
            # A forced style never falls back to the other one, so say which
            # one failed and point at the button that might still work.
            if style == STYLE_RECOLOR:
                error = ("Could not recolor the vanilla icon for this skin (its "
                         "textures don't line up with the vanilla costume). Try "
                         "the 3D head style.")
            elif style == STYLE_RENDER:
                error = ("Could not render a head for this skin. Try the recolor "
                         "style.")
            else:
                error = ('Could not derive a stock icon for this skin (no vanilla '
                         'reference lines up with its DAT or CSP)')
            return jsonify({'success': False, 'error': error}), 422

        logger.info(f"[OK] Previewed generated stock ({style or 'auto'}) for "
                    f"{character} - {skin_id} via {method}")
        return jsonify({'success': True, 'method': method,
                        'dataUri': 'data:image/png;base64,'
                                   + base64.b64encode(stock_data).decode('ascii')})
    except Exception as e:
        logger.error(f"Generate stock error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
