"""
The unified /api/mex/import/file endpoint - accepts ZIP/7z/RAR/DAT/USD uploads,
auto-detects mod type (character, stage, xdelta patch, CSS icon grid), and
dispatches to the matching import pipeline.

Container zips (archives that themselves contain .zip/.7z/.rar archives — the
classic "one giant zip of my whole skin folder") are recursed into: each inner
archive runs through the same detection cascade, with Slippi issues auto-fixed
and owned duplicates auto-skipped, and the response aggregates what happened
to every inner file instead of silently importing only the loose dats.
"""

import os
import zipfile
import tempfile
import logging
from pathlib import Path
from flask import request, jsonify

from core.rar_tools import rar_available

from . import import_bp
from vault.importing.unified.detection import IMAGE_EXTS
from vault.importing.unified.archive import _client_error

logger = logging.getLogger(__name__)


_UPLOAD_EXTS = {'.zip', '.7z', '.rar', '.dat', '.usd', '.xdelta', '.ssbm'} | IMAGE_EXTS


def _supported_upload(filename):
    return Path(filename or '').suffix.lower() in _UPLOAD_EXTS


def _upload_origin(source_url, files):
    """Where an upload came from, for the record kept with any fighter C in it (projects/install/fighter_source.py):
    the URL the window downloaded it from (a nucleus://import link; the frontend sends `source_url`), else a
    file from this computer. Informational only: fighter C from a package is untrusted either way."""
    url = (source_url or '').strip()
    if url.lower().startswith(('https://', 'http://')):
        return f'a download from {url[:300]}'
    names = ', '.join(Path(f.filename).name for f in files[:3])
    return f'the file {names}, imported from this computer'


def _batch_upload_name(files):
    """A name for the temp archive that packs several loose uploads: their
    common stem ('digit' for digit0..digit9) or the first file's stem."""
    stems = [Path(f.filename).stem for f in files]
    prefix = os.path.commonprefix(stems).rstrip(' _-()[]0123456789.')
    return (prefix if len(prefix) >= 2 else stems[0]) + '.zip'


@import_bp.route('/api/mex/import/file', methods=['POST'])
def import_file():
    """
    Unified import endpoint for both character costumes and stage mods.

    Accepts ZIP file upload, auto-detects type, and processes accordingly.
    Includes slippi safety validation with user choice to fix or import as-is.

    Several files may be sent under the same `file` field: loose files picked
    together (the ten PNGs of a digit pack, a Popo + Nana pair) are packed
    into ONE temp archive so detection sees them as a unit.
    """
    try:
        files = [f for f in request.files.getlist('file') if f is not None]
        if not files:
            return jsonify({
                'success': False,
                'error': 'No file uploaded'
            }), 400
        files = [f for f in files if f.filename]
        if not files:
            return jsonify({
                'success': False,
                'error': 'No file selected'
            }), 400

        unsupported = [f.filename for f in files if not _supported_upload(f.filename)]
        if unsupported:
            return jsonify({
                'success': False,
                'error': ('Only ZIP, 7z, RAR, DAT, USD, XDELTA, SSBM, and image (PNG / JPG / WebP) '
                          'files are supported'
                          + (f": {', '.join(unsupported[:3])}" if len(files) > 1 else ''))
            }), 400

        file = files[0]
        fname_lower = file.filename.lower()
        is_zip = fname_lower.endswith('.zip')
        is_7z = fname_lower.endswith('.7z')
        is_rar = fname_lower.endswith('.rar')
        is_ssbm = fname_lower.endswith('.ssbm')

        # Say so up front rather than letting the archive fall through to a
        # baffling "could not detect any mods in this file".
        if is_rar and not rar_available():
            return jsonify({
                'success': False,
                'error': ('This build cannot open .rar archives — the bundled UnRAR tool '
                          'is missing. Extract the archive and import its contents.')
            }), 400

        # Bare .ssbm bundle — store it directly, nothing to detect
        if len(files) == 1 and is_ssbm:
            from vault.catalog.bundles import import_bundle_file
            with tempfile.NamedTemporaryFile(suffix='.ssbm', delete=False) as tmp:
                file.save(tmp.name)
                ssbm_tmp = tmp.name
            try:
                result = import_bundle_file(ssbm_tmp, Path(file.filename).stem)
                return jsonify({
                    'success': True,
                    'type': 'bundle',
                    'bundle_id': result['bundle_id'],
                    'name': result['name'],
                    'message': f"Imported bundle: {result['name']}"
                })
            except ValueError as e:
                return jsonify({'success': False, 'error': str(e)}), 400
            finally:
                try:
                    os.unlink(ssbm_tmp)
                except OSError:
                    pass

        # Get slippi_action parameter (can be "fix", "import_as_is", or None)
        slippi_action = request.form.get('slippi_action')

        # Get duplicate_action parameter ("skip", "import_anyway", or None)
        duplicate_action = request.form.get('duplicate_action')

        # Get custom_title parameter if provided (for nucleus:// imports)
        custom_title = request.form.get('custom_title')
        logger.info(f"[DEBUG] custom_title from form: '{custom_title}' (type: {type(custom_title).__name__})")

        # Get mod type hints from nucleus:// protocol (set by website tags)
        # or from the app's choice dialog answering an ambiguous detection.
        mod_type = request.form.get('mod_type')  # 'effect', 'css_doors', ... or None
        effect_type = request.form.get('effect_type')  # e.g. 'gun', 'laser', 'sword'
        character = request.form.get('character')  # effect hint: whose extras
        logger.info(f"[DEBUG] mod_type: {mod_type}, effect_type: {effect_type}, character: {character}")

        # Save what was uploaded; import_handoff's shared normalizer decides
        # what it actually is (by magic bytes) and wraps or converts it. The
        # chat download path goes through the very same call.
        upload_name = file.filename
        source_filename = file.filename
        if len(files) > 1:
            with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
                temp_zip_path = tmp.name
            with zipfile.ZipFile(temp_zip_path, 'w') as zf:
                for f in files:
                    zf.writestr(Path(f.filename).name, f.read())
            upload_name = _batch_upload_name(files)
            source_filename = None
        else:
            with tempfile.NamedTemporaryFile(suffix=Path(file.filename).suffix or '.bin',
                                             delete=False) as tmp:
                file.save(tmp.name)
                temp_zip_path = tmp.name

        try:
            from vault.importing.unified.protocol import import_handoff
            payload, status = import_handoff(
                temp_zip_path, upload_name,
                source_filename=source_filename,
                slippi_action=slippi_action,
                duplicate_action=duplicate_action,
                custom_title=custom_title,
                mod_type=mod_type,
                effect_type=effect_type,
                character=character,
                origin=_upload_origin(request.form.get('source_url'), files))
            return jsonify(payload), status
        except ValueError as e:
            return jsonify({'success': False, 'error': _client_error(e)}), 400
        finally:
            # Clean up temp file
            try:
                os.unlink(temp_zip_path)
            except:
                pass

    except Exception as e:
        logger.error(f"Import error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'Import error: {_client_error(e)}'
        }), 500


