"""
ISO Scan blueprint - rip new costumes from a list of vanilla / modded ISOs.

Pipeline lives in `iso_scanner.py`. This blueprint exposes:

- POST   /api/mex/iso-scan/start              kick off a scan thread
- GET    /api/mex/iso-scan/<job_id>/csp/<key> serve a candidate's CSP png
- POST   /api/mex/iso-scan/<job_id>/import    import selected keys into vault
- POST   /api/mex/iso-scan/cleanup            prune inactive work dirs
- DELETE /api/mex/iso-scan/<job_id>           drop completed candidate files
- GET    /api/mex/iso-scan/preflight          report extraction capabilities
"""

from __future__ import annotations

import logging
import os
import tempfile
import zipfile
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from core import jobs
from vault.importing.iso_scanner import (
    SCAN_KIND, start_scan, scan_candidates, delete_scan_files, cleanup_stale_jobs,
)

logger = logging.getLogger(__name__)

iso_scan_bp = Blueprint('iso_scan', __name__)


@iso_scan_bp.route('/api/mex/iso-scan/preflight', methods=['GET'])
def preflight():
    return jsonify({
        'native_available': True,
    })


@iso_scan_bp.route('/api/mex/iso-scan/start', methods=['POST'])
def start():
    data = request.get_json(silent=True) or {}
    iso_paths = data.get('iso_paths') or []
    if not isinstance(iso_paths, list) or not iso_paths:
        return jsonify({'success': False, 'error': 'iso_paths required'}), 400

    # Validate existence + .iso/.gcm extension. NKit images advertise as .iso but
    # cannot be opened by this pipeline, so skip them instead of failing a mixed
    # batch.
    cleaned = []
    skipped = []
    for p in iso_paths:
        path = Path(p)
        if not path.exists() or not path.is_file():
            return jsonify({'success': False, 'error': f'File not found: {p}'}), 400
        if path.suffix.lower() not in ('.iso', '.gcm'):
            return jsonify({'success': False, 'error': f'Not an ISO: {path.name}'}), 400
        if '.nkit' in path.name.lower():
            skipped.append({'path': str(path), 'reason': 'NKit ISO is not supported'})
            continue
        cleaned.append(str(path))
    if not cleaned:
        return jsonify({
            'success': False,
            'error': 'No compatible ISO/GCM files to scan',
            'skipped': skipped,
        }), 400

    job_id = start_scan(cleaned)
    logger.info(f"Started ISO scan {job_id} for {len(cleaned)} ISO(s)")
    return jsonify({'success': True, 'job_id': job_id, 'skipped': skipped})


@iso_scan_bp.route('/api/mex/iso-scan/<job_id>/csp/<key>/csp', methods=['GET'])
def get_csp(job_id, key):
    job = jobs.get(job_id)
    if not job or job['kind'] != SCAN_KIND:
        return jsonify({'success': False, 'error': 'Job not found'}), 404
    for s in scan_candidates(job):
        if s.key == key:
            if not s.csp_path or not os.path.exists(s.csp_path):
                return jsonify({'success': False, 'error': 'No CSP'}), 404
            return send_file(s.csp_path, mimetype='image/png')
    return jsonify({'success': False, 'error': 'Skin not found'}), 404


@iso_scan_bp.route('/api/mex/iso-scan/cleanup', methods=['POST'])
def cleanup():
    data = request.get_json(silent=True) or {}
    max_age_seconds = data.get('maxAgeSeconds')
    if max_age_seconds is not None:
        try:
            max_age_seconds = int(max_age_seconds)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'maxAgeSeconds must be an integer'}), 400
    result = cleanup_stale_jobs(max_age_seconds=max_age_seconds)
    return jsonify({'success': True, **result})


@iso_scan_bp.route('/api/mex/iso-scan/<job_id>', methods=['DELETE'])
def delete(job_id):
    if delete_scan_files(job_id):
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Job not found'}), 404


@iso_scan_bp.route('/api/mex/iso-scan/<job_id>/import', methods=['POST'])
def import_selected(job_id):
    """Import the user-selected keys into the vault.

    Reuses the standard import pipeline: we wrap each DAT in a synthetic ZIP
    and run it through `detect_character_from_zip` + `import_character_costume`
    so that CSP generation, slippi-fix, Ice Climbers pairing, and metadata
    bookkeeping all match what `Import File` does.
    """
    job = jobs.get(job_id)
    if not job or job['kind'] != SCAN_KIND:
        return jsonify({'success': False, 'error': 'Job not found'}), 404
    if job['status'] != 'done':
        return jsonify({'success': False, 'error': f"Job not complete (status={job['status']})"}), 400

    body = request.get_json(silent=True) or {}
    keys = body.get('keys') or []
    auto_fix = bool(body.get('auto_fix', True))
    if not isinstance(keys, list) or not keys:
        return jsonify({'success': False, 'error': 'keys required'}), 400

    # Lookup skins
    selected = []
    for s in scan_candidates(job):
        if s.key in keys:
            selected.append(s)
    if not selected:
        return jsonify({'success': False, 'error': 'No matching skins'}), 400

    # Lazy import to avoid circular deps at module load
    from vault.importing.character_detector import detect_character_from_zip
    from vault.importing.unified.characters import import_character_costume, fix_ice_climbers_pairing

    def _ensure_dat_ext(name: str) -> str:
        """Normalize a costume archive filename to .dat for the importer.

        MEX-built ISOs use extra-slot extensions (PlMrNr.lat, PlFxBu.rat, etc.)
        as a slot marker, but the file format is identical to .dat. The
        import path's costume-archive helper only recognises .dat / .usd
        though, so we rename on the way into the temp zip — same bytes,
        the importer just sees `PlMrNr.dat`.
        """
        if not name:
            return 'costume.dat'
        lower = name.lower()
        if lower.endswith(('.dat', '.usd')):
            return name
        # Replace any other extension with .dat (don't append on top of it).
        stem, _ = os.path.splitext(name)
        return stem + '.dat'

    imported = 0
    errors = []
    for s in selected:
        try:
            with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
                tmp_zip = tmp.name
            inner_name = _ensure_dat_ext(s.costume_code)
            with zipfile.ZipFile(tmp_zip, 'w') as zf:
                with open(s.dat_path, 'rb') as f:
                    zf.writestr(inner_name, f.read())
                # Pack the paired DAT (Ice Climbers) alongside so the importer
                # can detect both halves in one pass and run the IC pairing
                # post-process.
                if s.paired_dat_path and os.path.exists(s.paired_dat_path):
                    paired_name = _ensure_dat_ext(s.paired_costume_code or 'pair.dat')
                    with open(s.paired_dat_path, 'rb') as f:
                        zf.writestr(paired_name, f.read())
                # Reuse the preview CSP we already rendered in Phase 4 of the
                # scan. detect_character_from_zip / import_character_costume
                # will pick this up via the standard image-matching pass and
                # skip the second generate_csp call — so the thumbnail the user
                # selected is what ends up stored in the vault.
                if s.csp_path and os.path.exists(s.csp_path):
                    csp_inner_name = f"{os.path.splitext(inner_name)[0]}_csp.png"
                    with open(s.csp_path, 'rb') as f:
                        zf.writestr(csp_inner_name, f.read())
                # Prefer the actual stock icon extracted from the source ISO's
                # IfAll stock table. The unified detector matches this by the
                # costume stem, so import_character_costume stores it instead
                # of deriving/reusing a vanilla icon.
                if s.stock_path and os.path.exists(s.stock_path):
                    stock_inner_name = f"{os.path.splitext(inner_name)[0]}_stock.png"
                    with open(s.stock_path, 'rb') as f:
                        zf.writestr(stock_inner_name, f.read())

            try:
                char_infos = detect_character_from_zip(tmp_zip)
                if not char_infos:
                    errors.append({'key': s.key, 'error': 'detection failed'})
                    continue
                # Multiple entries for Ice Climbers (Popo + Nana).
                # Track the actual skin_id created for each costume_code so the
                # post-process can backfill paired_nana_id / paired_popo_id —
                # without this fixup, mod_export.py skips the Nana DAT during
                # install and the game falls back to vanilla Nana, so only the
                # modded Popo gets used. (Mirrors the post-process the regular
                # import flow runs at import_unified.py:1080.)
                imported_skin_ids: dict[str, str] = {}
                for ci in char_infos:
                    result = import_character_costume(
                        tmp_zip, ci, inner_name,
                        auto_fix=auto_fix, custom_name=None,
                        # Skip the recolor stock generator for bulk scan
                        # imports -- it is the slow per-skin step. Stocks the
                        # scan already pulled from the ISO's IfAll table are
                        # still packed (existing_stock wins); everything else
                        # gets the vanilla icon instead of a generated one.
                        allow_stock_gen=False,
                    )
                    if result.get('success'):
                        imported += 1
                        if result.get('skin_id'):
                            imported_skin_ids[ci['costume_code']] = result['skin_id']
                    else:
                        errors.append({'key': s.key, 'error': result.get('error') or 'import failed'})

                # Run the IC pairing post-process when both halves landed.
                if any(ci.get('is_popo') or ci.get('is_nana') for ci in char_infos):
                    fix_ice_climbers_pairing(char_infos, imported_skin_ids)
            finally:
                try:
                    os.unlink(tmp_zip)
                except OSError:
                    pass
        except Exception as e:
            logger.exception(f"Import failed for {s.key}")
            errors.append({'key': s.key, 'error': str(e)})

    return jsonify({
        'success': True,
        'imported': imported,
        'total_selected': len(selected),
        'errors': errors,
    })
