"""
Animelee costumes (the inverted-hull outline effect): detect them with the
MexCLI geometry detector, grouped by body geometry, and file them in a folder.

Registers on `storage_costumes_bp` (vault/routes/storage_costumes/).
"""

import os
import json
import uuid
import tempfile
import logging
import mexcli.commands
from flask import jsonify, request
from core.config import STORAGE_PATH
from core.metadata import get_char_data, load_metadata, save_metadata
from . import storage_costumes_bp
from vault.catalog.costume_folders import find_folder_in_skins

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Animelee detection — find costumes with the inverted-hull outline effect via
# the MexCLI geometry detector (detect-outline), grouped by body-geometry
# fingerprint so colour variants of the same skin cluster together. Vanilla
# geometry is excluded (defensive; vanilla's small intrinsic outline is already
# below the detector's threshold). See memory animelee-detection.
# ---------------------------------------------------------------------------

_VANILLA_GEOM_HASHES = None

# Animelee verdict applied here (not in C#) so it's tunable without a rebuild.
# A real inverted-hull outline needs >=2 cull-asymmetric concentric duplicate
# pairs and a substantial largest duplicated part. Threshold 120 sits above the
# retail-vanilla ceiling (max asymDupMax across all 273 vanilla DATs = 112) and
# below genuine Animelee (e.g. Breloom-Yoshi = 137), so vanilla never trips it.
ANIMELEE_CULLASYM_MIN = 2
ANIMELEE_ASYMMAX_MIN = 120


def _load_vanilla_geom_hashes():
    """Body-geometry fingerprints of retail vanilla costumes (cached)."""
    global _VANILLA_GEOM_HASHES
    if _VANILLA_GEOM_HASHES is None:
        try:
            from core.config import BACKEND_DATA_DIR
            doc = json.loads((BACKEND_DATA_DIR / 'vanilla_geom_hashes.json').read_text(encoding='utf-8'))
            _VANILLA_GEOM_HASHES = set(doc.get('hashes', []))
        except Exception:
            _VANILLA_GEOM_HASHES = set()
    return _VANILLA_GEOM_HASHES


@storage_costumes_bp.route('/api/mex/storage/animelee/detect', methods=['POST'])
def detect_animelee():
    """Detect Animelee (inverted-hull outline) costumes for a character.

    Runs the MexCLI geometry detector over the character's costume zips, drops
    vanilla geometry, and groups hits by geomHash (same fingerprint = same model
    in different colours). A group is 'known' when its geometry already appears
    inside an Animelee folder — propagating your existing labels to colour
    variants you haven't foldered yet.
    """
    try:
        from collections import defaultdict

        data = request.json or {}
        character = data.get('character')
        if not character:
            return jsonify({'success': False, 'error': 'Missing character parameter'}), 400

        metadata = load_metadata()
        char_data = get_char_data(metadata, character) if metadata else None
        if not char_data:
            return jsonify({'success': False, 'error': f'Character {character} not found'}), 404
        skins = char_data.get('skins', [])

        folder_names = {s['id']: s.get('name', '') for s in skins if s.get('type') == 'folder'}
        anime_fids = {fid for fid, nm in folder_names.items() if 'anim' in nm.lower()}

        char_folder = STORAGE_PATH / character
        id_to_skin = {}
        items = []
        for s in skins:
            if s.get('type') == 'folder':
                continue
            fn = s.get('filename')
            if not fn:
                continue
            zp = char_folder / fn
            if not zp.exists():
                continue
            id_to_skin[s['id']] = s
            items.append({'key': s['id'], 'path': str(zp)})

        if not items:
            return jsonify({'success': True, 'character': character, 'groups': [], 'totalNew': 0,
                            'animeFolders': [{'id': f, 'name': folder_names[f]} for f in anime_fids]})

        manifest_path = None
        try:
            with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as mf:
                json.dump({'items': items}, mf)
                manifest_path = mf.name
            out = mexcli.commands.run_json(['detect-outline', '--batch', manifest_path])
        finally:
            if manifest_path:
                try:
                    os.unlink(manifest_path)
                except OSError:
                    pass

        results = out.get('results', []) if isinstance(out, dict) else []
        res_by_id = {r.get('key'): r for r in results}
        vanilla = _load_vanilla_geom_hashes()

        # geometry fingerprints already confirmed Animelee (foldered members)
        confirmed_geom = set()
        for s in skins:
            if s.get('type') == 'folder' or s.get('folder_id') not in anime_fids:
                continue
            r = res_by_id.get(s.get('id'))
            if r and r.get('success') and r.get('geomHash'):
                confirmed_geom.add(r['geomHash'])

        groups_map = defaultdict(list)
        for r in results:
            if not r.get('success'):
                continue
            if (r.get('dupCullAsym', 0) < ANIMELEE_CULLASYM_MIN
                    or r.get('asymDupMax', 0) < ANIMELEE_ASYMMAX_MIN):
                continue
            gh = r.get('geomHash') or ''
            if gh and gh in vanilla:
                continue   # vanilla/recolor geometry, never Animelee
            s = id_to_skin.get(r.get('key'))
            if not s:
                continue
            groups_map[gh].append({
                'id': s.get('id'),
                'name': s.get('name') or s.get('id'),
                'alreadyFoldered': bool(s.get('folder_id') in anime_fids),
                'folderId': s.get('folder_id'),
                'asymMax': r.get('asymDupMax', 0),
            })

        groups = []
        for gh, members in groups_map.items():
            unfoldered = sum(1 for m in members if not m['alreadyFoldered'])
            groups.append({
                'geomHash': gh,
                'known': gh in confirmed_geom,
                'skins': members,
                'unfolderedCount': unfoldered,
            })
        groups.sort(key=lambda g: (-g['unfolderedCount'], not g['known']))

        return jsonify({
            'success': True,
            'character': character,
            'groups': groups,
            'totalNew': sum(g['unfolderedCount'] for g in groups),
            'animeFolders': [{'id': f, 'name': folder_names[f]} for f in anime_fids],
        })
    except Exception as e:
        logger.error(f"Detect animelee error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@storage_costumes_bp.route('/api/mex/storage/animelee/apply', methods=['POST'])
def apply_animelee():
    """Move the given skins into an Animelee folder (reusing one if it exists,
    else creating it). Atomic: one metadata write."""
    try:
        data = request.json or {}
        character = data.get('character')
        skin_ids = data.get('skinIds') or []
        folder_id = data.get('folderId')
        folder_name = data.get('folderName') or 'Animelee'

        if not character or not skin_ids:
            return jsonify({'success': False, 'error': 'Missing character or skinIds'}), 400

        metadata = load_metadata(default={'characters': {}})
        characters = metadata.setdefault('characters', {})
        character_data = characters.setdefault(character, {})
        skins = character_data.setdefault('skins', [])

        if folder_id:
            folder, _ = find_folder_in_skins(skins, folder_id)
            if not folder:
                return jsonify({'success': False, 'error': f'Folder {folder_id} not found'}), 404
        else:
            folder_id = f"folder_{uuid.uuid4().hex[:8]}"
            skins.append({'type': 'folder', 'id': folder_id, 'name': folder_name, 'expanded': True})

        wanted = set(skin_ids)
        moved = 0
        for s in skins:
            if s.get('type') != 'folder' and s.get('id') in wanted:
                s['folder_id'] = folder_id
                moved += 1

        save_metadata(metadata)
        logger.info(f"[OK] Animelee: moved {moved} skin(s) into {folder_id} for {character}")
        return jsonify({'success': True, 'folderId': folder_id, 'moved': moved, 'skins': skins})
    except Exception as e:
        logger.error(f"Apply animelee error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
