"""
Character costume import - vault storage, CSP/stock handling, Ice Climbers
pairing.
"""

import os
import re
import zipfile
import tempfile
import logging
from datetime import datetime
from pathlib import Path
import file_retry

from core.config import STORAGE_PATH
from core.costume_files import get_costume_archive_extension
from core.metadata import load_metadata, metadata_transaction
from dat_processor import validate_for_slippi
from shared.rendering.costume_assets import build_csp_and_stock

from .helpers import compute_dat_hash, extract_custom_name_from_filename, sanitize_filename

logger = logging.getLogger(__name__)

_PL_CODE_RE = re.compile(r'^(Pl[A-Za-z]{2})([A-Za-z]{2})')


def _cleanup_import_files(paths):
    for path in paths:
        try:
            file_retry.retry_locked(path.unlink, missing_ok=True)
        except OSError:
            logger.warning('Could not clean up incomplete costume import file %s', path, exc_info=True)


def _maybe_diet_fix(dat_data: bytes, dat_filename: str,
                    character: str = '') -> tuple[bytes, bool]:
    """Repair a Diet Melee-authored costume DAT (art in the hidden low-poly
    slots, stripped-texture materials that hang normal builds — see
    shared/rendering/lowpoly_promote.py). Fires only on the stripped-texture
    fingerprint, which normally-authored skins never carry. Returns the
    (possibly transformed) bytes; the original on any failure."""
    tmp_in = tmp_out = None
    try:
        from shared.rendering import lowpoly_promote as lp
        from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref

        m = _PL_CODE_RE.match(os.path.basename(dat_filename))
        if not m:
            return dat_data, False

        with tempfile.NamedTemporaryFile(suffix='.dat', delete=False) as f:
            f.write(dat_data)
            tmp_in = f.name
        if not lp.stripped_tex_materials(tmp_in):
            return dat_data, False

        van_costume = ensure_vanilla_ref(m.group(0) + '.dat')
        ftdata = ensure_vanilla_ref(m.group(1) + '.dat')
        if not van_costume or not ftdata:
            return dat_data, False

        slot = lp.costume_slot_for_code(character, m.group(2))
        plan = lp.plan_diet_fix(tmp_in, van_costume, ftdata, costume_slot=slot)
        if not plan.promote:
            logger.info(f"Diet fingerprint on {dat_filename} but no repair: {plan.reason}")
            return dat_data, False

        tmp_out = tmp_in + '.fixed'
        lp.apply_diet_fix(tmp_in, tmp_out, plan)
        with open(tmp_out, 'rb') as f:
            fixed = f.read()
        logger.info(f"Diet-authored costume repaired on import: {dat_filename} ({plan.reason})")
        return fixed, True
    except Exception as e:
        logger.warning(f"Diet repair failed for {dat_filename}: {e} — importing original")
        return dat_data, False
    finally:
        for p in (tmp_in, tmp_out):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass


def fix_ice_climbers_pairing(character_infos: list, imported_skin_ids: dict):
    """
    Fix Ice Climbers pairing and acknowledge committed reciprocal links.

    Args:
        character_infos: List of character info dicts with pairing metadata
        imported_skin_ids: Dict mapping costume_code -> actual skin_id created
    """
    try:
        # Locked read-modify-write: this pairing fixup mutates existing Ice
        # Climbers skins right after import, when concurrent imports may also be
        # writing. metadata_transaction re-reads under metadata_lock and writes
        # atomically so the pairing edits merge without a lost update.
        with metadata_transaction() as metadata:
            if metadata is None:
                return False

            if 'Ice Climbers' not in metadata.get('characters', {}):
                return False

            # Build a mapping of costume_code -> character_info for easy lookup
            info_by_code = {ci['costume_code']: ci for ci in character_infos}

            # Update each Ice Climbers skin with actual paired IDs
            updated = False
            for skin in metadata['characters']['Ice Climbers']['skins']:
                # Skip if this specific skin wasn't just imported
                # Check by skin ID, not costume code, since multiple skins can share the same costume code
                if skin['id'] not in imported_skin_ids.values():
                    continue

                costume_code = skin['costume_code']
                char_info = info_by_code.get(costume_code)
                if not char_info:
                    continue

                # Update Popo with actual Nana ID
                if char_info.get('is_popo') and char_info.get('pair_costume_code'):
                    nana_costume_code = char_info['pair_costume_code']
                    actual_nana_id = imported_skin_ids.get(nana_costume_code)
                    if actual_nana_id:
                        skin['paired_nana_id'] = actual_nana_id
                        logger.info(f"Linked Popo {skin['id']} -> Nana {actual_nana_id}")
                        updated = True

                # Update Nana with actual Popo ID
                elif char_info.get('is_nana') and char_info.get('pair_costume_code'):
                    popo_costume_code = char_info['pair_costume_code']
                    actual_popo_id = imported_skin_ids.get(popo_costume_code)
                    if actual_popo_id:
                        skin['paired_popo_id'] = actual_popo_id
                        logger.info(f"Linked Nana {skin['id']} -> Popo {actual_popo_id}")
                        updated = True

            if updated:
                logger.info("[OK] Updated Ice Climbers pairing with actual skin IDs")
            # A successful file import alone does not establish a usable pair.
            # Compute the acknowledgement here, but return it only after the
            # transaction exits successfully (including its durable write).
            by_id = {skin['id']: skin for skin in metadata['characters']['Ice Climbers']['skins']}
            pair_infos = [info for info in character_infos if info.get('is_popo') or info.get('is_nana')]
            complete = bool(pair_infos)
            for info in pair_infos:
                skin_id = imported_skin_ids.get(info['costume_code'])
                partner_id = imported_skin_ids.get(info.get('pair_costume_code'))
                key, reciprocal = ('paired_nana_id', 'paired_popo_id') if info.get('is_popo') else ('paired_popo_id', 'paired_nana_id')
                complete = complete and bool(skin_id and partner_id) and (
                    by_id.get(skin_id, {}).get(key) == partner_id and
                    by_id.get(partner_id, {}).get(reciprocal) == skin_id)
            # metadata_transaction always writes on clean exit; the pairing edits
            # (if any) are persisted atomically here.
        return complete

    except Exception as e:
        logger.error(f"Failed to fix Ice Climbers pairing: {e}", exc_info=True)
        return False


def import_character_costume(zip_path: str, char_info: dict, original_filename: str, auto_fix: bool = False, custom_name: str = None, allow_stock_gen: bool = True) -> dict:
    """
    Import a character costume to storage.

    Args:
        zip_path: Path to the uploaded ZIP file
        char_info: Character detection info
        original_filename: Original filename of the upload
        auto_fix: If True, apply slippi fixes to the DAT file
        custom_name: Optional custom name to use instead of extracting from filename
        allow_stock_gen: If False, skip the recolor stock generator and fall back
            to the vanilla icon when no stock came in with the costume. The
            ISO-scan bulk import passes False to keep a 90-skin import fast.
    """
    staged_zip = None
    published_files = []
    committed = False
    try:
        # Load metadata
        metadata = load_metadata(default={'characters': {}, 'stages': {}})

        # Ensure 'stages' section exists
        if 'stages' not in metadata:
            metadata['stages'] = {}

        character = char_info['character']

        # Create character folder
        char_folder = STORAGE_PATH / character
        char_folder.mkdir(parents=True, exist_ok=True)

        logger.info(f"[DEBUG import_character_costume] custom_name parameter: '{custom_name}' (type: {type(custom_name).__name__})")
        logger.info(f"[DEBUG import_character_costume] original_filename: '{original_filename}'")

        # Use provided custom name, or extract from filename
        if not custom_name:
            logger.info(f"[DEBUG] custom_name is falsy, extracting from filename")
            custom_name = extract_custom_name_from_filename(original_filename, character)
            logger.info(f"[DEBUG] Extracted custom_name from filename: '{custom_name}'")

        # Extract descriptive name from DAT filename (remove .dat extension and clean up)
        dat_basename = os.path.splitext(os.path.basename(char_info['dat_file']))[0]
        # Clean and sanitize: lowercase, replace spaces/special chars with hyphens
        dat_name_clean = re.sub(r'[^\w\s-]', '', dat_basename)  # Remove special chars except space and hyphen
        dat_name_clean = re.sub(r'[\s_]+', '-', dat_name_clean)  # Replace spaces/underscores with hyphens
        dat_name_clean = dat_name_clean.lower().strip('-')  # Lowercase and remove leading/trailing hyphens

        # Generate base ID: use custom name if found, otherwise use DAT filename.
        # The base ID becomes a filename on disk, so strip characters Windows
        # forbids (e.g. a '|' in a post title like "Akaneia Pichu | Animelee"
        # previously produced an illegal path -> OSError [Errno 22], silently
        # failing the import). The pretty custom_name is kept for display below.
        if custom_name:
            base_id = f"{sanitize_filename(custom_name)}-{dat_name_clean}"
            logger.info(f"Using custom name from filename: '{custom_name}' -> '{base_id}'")
        else:
            base_id = dat_name_clean
            logger.info(f"Using DAT filename as name: '{base_id}'")

        # Rendering can take minutes. Keep its output private until the locked
        # commit can choose an identity from LIVE metadata; concurrent imports
        # previously chose the same id here and overwrote each other's files.
        fd, staged_name = tempfile.mkstemp(prefix='.costume-import-', suffix='.tmp', dir=char_folder)
        os.close(fd)
        staged_zip = Path(staged_name)

        # Copy files from uploaded ZIP to final ZIP with correct structure
        csp_source = 'imported'
        archive_ext = get_costume_archive_extension(char_info['dat_file'])

        # SLIPPI VALIDATION: Validate DAT before importing
        slippi_validation = None
        dat_hash = None
        with zipfile.ZipFile(zip_path, 'r') as source_zip:
            # Extract DAT for validation
            dat_data = source_zip.read(char_info['dat_file'])

            # Compute hash of original DAT for duplicate detection
            dat_hash = compute_dat_hash(dat_data)
            logger.info(f"Computed DAT hash: {dat_hash}")

            with tempfile.NamedTemporaryFile(suffix='.dat', delete=False) as tmp_dat:
                tmp_dat.write(dat_data)
                tmp_dat_path = tmp_dat.name

            try:
                slippi_validation = validate_for_slippi(tmp_dat_path, auto_fix=auto_fix)
                logger.info(f"Slippi validation: slippi_safe={slippi_validation['slippi_safe']}, auto_fix={auto_fix}, output={slippi_validation.get('output', '')[:200]}")

                # If auto_fix was applied, read the fixed DAT
                if auto_fix and slippi_validation.get('fix_applied'):
                    with open(tmp_dat_path, 'rb') as f:
                        dat_data = f.read()
                    logger.info("Using slippi-fixed DAT file")
            finally:
                os.unlink(tmp_dat_path)

        # Diet Melee-authored skins (stripped-texture fingerprint) get their
        # low-poly art promoted + blink indices shimmed, or they'd display as
        # near-vanilla and hang normal builds at match load.
        dat_data, _ = _maybe_diet_fix(dat_data, char_info['dat_file'],
                                      character=character)

        # G&W color mods carry a gaw.json sidecar ({"fill": "#AARRGGBB",
        # "outline": "#AARRGGBB"}) declaring the slot's engine-side colors --
        # preserve it through re-import (exported/shared mods) and use it to
        # color the regenerated CSP/stock.
        gaw_sidecar = None
        gw_colors = None
        with zipfile.ZipFile(zip_path, 'r') as source_zip:
            sidecar_name = next((n for n in source_zip.namelist()
                                 if os.path.basename(n).lower() == 'gaw.json'), None)
            if sidecar_name:
                try:
                    import json as _json
                    from core.gaw_colors import gw_colors_from_hex
                    parsed = _json.loads(source_zip.read(sidecar_name))
                    gaw_sidecar = {'fill': parsed.get('fill'), 'outline': parsed.get('outline')}
                    gw_colors = gw_colors_from_hex(parsed.get('fill'), parsed.get('outline'))
                    logger.info(f"Found gaw.json sidecar: {gaw_sidecar}")
                except Exception as e:
                    logger.warning(f"Unreadable gaw.json sidecar ignored: {e}")
                    gaw_sidecar = None

        with zipfile.ZipFile(zip_path, 'r') as source_zip:
            with zipfile.ZipFile(staged_zip, 'w') as dest_zip:
                # Copy the costume archive (potentially fixed version), preserving .usd when present.
                dest_zip.writestr(f"{char_info['costume_code']}Mod{archive_ext}", dat_data)

                if gaw_sidecar:
                    import json as _json
                    dest_zip.writestr('gaw.json', _json.dumps(gaw_sidecar, indent=2))

                # Build the costume's portrait assets through the ONE canonical
                # path (render via generate_csp with proper anim+camera, recolor
                # via generate_stock) so import, skin-lab, and the duel generator
                # all produce identical CSP/stock. See shared.rendering.costume_assets.
                existing_csp = source_zip.read(char_info['csp_file']) if char_info['csp_file'] else None
                existing_stock = source_zip.read(char_info['stock_file']) if char_info['stock_file'] else None

                paired_dat_data = None
                if char_info.get('is_popo') and char_info.get('pair_dat_file'):
                    paired_dat_data = source_zip.read(char_info['pair_dat_file'])
                    paired_dat_data, _ = _maybe_diet_fix(
                        paired_dat_data, char_info['pair_dat_file'],
                        character=character)

                # Ice Climbers: Nana copies Popo's composite CSP + stock (Popo is
                # imported first), looked up from storage by paired color.
                popo_csp = popo_stock = None
                if char_info.get('is_nana') and char_info.get('pair_color'):
                    popo_id = f"{character.lower().replace(' ', '-')}-{char_info['pair_color'].lower()}"
                    for skin in metadata.get('characters', {}).get(character, {}).get('skins', []):
                        if skin['id'] == popo_id:
                            pcsp = STORAGE_PATH / character / f"{popo_id}_csp.png"
                            pstk = STORAGE_PATH / character / f"{popo_id}_stc.png"
                            popo_csp = pcsp.read_bytes() if pcsp.exists() else None
                            popo_stock = pstk.read_bytes() if pstk.exists() else None
                            break

                assets = build_csp_and_stock(
                    character, char_info['costume_code'], dat_data,
                    existing_csp=existing_csp, existing_stock=existing_stock,
                    paired_dat_data=paired_dat_data,
                    is_nana=bool(char_info.get('is_nana')),
                    popo_csp=popo_csp, popo_stock=popo_stock,
                    allow_stock_gen=allow_stock_gen, gw_colors=gw_colors,
                    log=logger)
                csp_data, csp_source = assets['csp'], assets['csp_source']
                stock_data, stock_source = assets['stock'], assets['stock_source']

                # Sidecars are published with the completed archive below.
                if csp_data:
                    dest_zip.writestr('csp.png', csp_data)

                # (csp_data / stock_data and their sources were resolved above by
                # build_csp_and_stock; just persist them.)

                # Save stock if we have one
                if stock_data:
                    dest_zip.writestr('stc.png', stock_data)

        # Determine display name: use custom_name if provided, otherwise use DAT filename
        display_name = custom_name if custom_name else dat_name_clean
        logger.info(f"[DEBUG] Final display_name: '{display_name}' (custom_name: '{custom_name}', dat_name_clean: '{dat_name_clean}')")

        # Build the COMPLETE skin entry up front. Every field (id, color,
        # has_csp, date_added, dat_hash, slippi_safe, ...) is set here in one
        # dict so the entry is only ever committed whole -- a half-populated
        # entry (e.g. dat_hash + slippi_safe but no color/has_csp/date_added)
        # is the fingerprint of an interrupted/raced two-phase write and must
        # never reach metadata.json. See metadata_transaction below.
        skin_entry = {
            'color': display_name,  # Display name shown in UI
            'costume_code': char_info['costume_code'],
            'has_csp': csp_data is not None,
            'has_stock': stock_data is not None,
            'csp_source': csp_source,
            'stock_source': stock_source if stock_data else None,
            'date_added': datetime.now().isoformat(),
            # DAT hash for duplicate detection
            'dat_hash': dat_hash,
            # Slippi safety metadata
            'slippi_safe': slippi_validation['slippi_safe'] if slippi_validation else False,
            'slippi_tested': True,
            'slippi_test_date': datetime.now().isoformat(),
            'slippi_manual_override': None
        }

        # G&W color mod: keep the colors on the entry (identity + UI editing)
        if gaw_sidecar and gaw_sidecar.get('fill'):
            skin_entry['gaw_colors'] = gaw_sidecar

        # Ice Climbers pairing metadata
        # Note: paired_nana_id/paired_popo_id will be set by fix_ice_climbers_pairing()
        # after both costumes are imported, using actual skin IDs
        if char_info.get('is_popo'):
            skin_entry['is_popo'] = True
            skin_entry['visible'] = True
            # Placeholder - will be updated with actual Nana ID after import
            skin_entry['paired_nana_id'] = None

        elif char_info.get('is_nana'):
            skin_entry['is_nana'] = True
            skin_entry['visible'] = False  # Hidden in UI
            # Placeholder - will be updated with actual Popo ID after import
            skin_entry['paired_popo_id'] = None

        # Commit the complete entry in ONE locked read-modify-write. The earlier
        # `metadata` snapshot (loaded at the top, before the slow CSP render) is
        # discarded here: metadata_transaction re-reads under metadata_lock so a
        # concurrent import that landed during the render is preserved instead of
        # being clobbered by a stale-snapshot save. This closes the lost-update /
        # partial-entry race (the costume-import twin of the custom-character
        # 24-thread fix; that path was converted to the DAL transaction, this one
        # had been left on a bare load/save).
        with metadata_transaction(default={'characters': {}, 'stages': {}}) as live:
            live.setdefault('characters', {})
            if character not in live['characters']:
                live['characters'][character] = {'skins': []}
            skins = live['characters'][character].setdefault('skins', [])
            existing_ids = {skin['id'] for skin in skins}
            skin_id = base_id
            counter = 1
            while skin_id in existing_ids or any(
                (char_folder / f'{skin_id}{suffix}').exists()
                for suffix in ('.zip', '_csp.png', '_csp_hd.png', '_stc.png')
            ):
                skin_id = f'{base_id}{counter:02d}'
                counter += 1
            skin_entry.update(id=skin_id, filename=f'{skin_id}.zip')
            final_zip = char_folder / skin_entry['filename']
            # No long-running work while holding the catalog lock. Publication
            # and deletion use the same lock so a reimport cannot be deleted by
            # an older request between its files and metadata becoming visible.
            try:
                file_retry.retry_locked(staged_zip.rename, final_zip)
                published_files.append(final_zip)
                for suffix, content in (('_csp.png', csp_data), ('_stc.png', stock_data)):
                    if content:
                        path = char_folder / f'{skin_id}{suffix}'
                        published_files.append(path)
                        file_retry.retry_locked(path.write_bytes, content)
                skins.append(skin_entry)
            except Exception:
                _cleanup_import_files(published_files)
                raise
        committed = True

        logger.info(f"[OK] Saved character costume: {final_zip}")

        return {
            'success': True,
            'type': 'character',
            'character': character,
            'color': dat_name_clean,  # Use descriptive name
            'skin_id': skin_id,  # Return the actual skin ID for pairing
            'csp_source': csp_source,
            'camera_sound': csp_source == 'generated',
            'slippi_fixed': bool(slippi_validation and slippi_validation.get('fix_applied')),
            'message': f"Imported {character} - {dat_name_clean} costume"
        }

    except Exception as e:
        logger.error(f"Character import error: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }
    finally:
        if staged_zip is not None:
            _cleanup_import_files([staged_zip])
        if not committed:
            _cleanup_import_files(published_files)
