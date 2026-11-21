"""
Effect/model mod import - routes website-tagged effect mods through the
extras model system.
"""

import zipfile
import io
import logging
import shutil
import uuid
from pathlib import Path
from datetime import datetime

from core.config import STORAGE_PATH
from core.metadata import load_metadata, save_metadata
from core.extra_lookup import get_extra_types, get_storage_character
from vault.extras.models import extract_model_from_dat, model_extra_location
from vault.extras.derive import derive_modifications_from_dat

from .helpers import sanitize_filename, compute_dat_hash

logger = logging.getLogger(__name__)


def select_effect_payload(zf, filename, effect_type):
    """Resolve the same character, type and payload for import and duplicates."""
    character = Path(filename).stem.split('_')[0]
    character = {'Captain Falcon': 'C. Falcon', 'Donkey Kong': 'DK',
                 'Mr. Game & Watch': 'G&W', 'Mr. Game And Watch': 'G&W'}.get(character, character)
    normalize = lambda value: value.strip().lower().replace(' ', '_').replace('-', '_')
    key = normalize(effect_type)
    cfg = next((t for t in get_extra_types(character)
                if key in (t['id'], normalize(t['name']))), None)
    if not cfg:
        raise ValueError(f'Effect type "{effect_type}" not defined for {character}')
    names = [n for n in zf.namelist() if not n.endswith('/')
             and not any(p.startswith(('__MACOSX', '._')) for p in n.replace('\\', '/').split('/'))]
    dats = [n for n in names if n.lower().endswith('.dat')]
    if dats:
        target = Path(cfg.get('target_file', '')).stem.lower()
        preferred = [n for n in dats if Path(n).name.lower().startswith(target)] if target else []
        # A single renamed DAT remains supported; never guess among unrelated DATs.
        if not preferred and len(dats) != 1:
            raise ValueError(f'Archive has no unambiguous {cfg.get("target_file")} effect payload')
        member = (preferred or dats)[0]
        raw = zf.read(member)
        return character, cfg['id'], cfg, member, compute_dat_hash(raw)
    from vault.extras import effect_model as em
    images = [n for n in names if Path(n).suffix.lower() in em.IMAGE_EXTS
              and Path(n).stem.lower() not in ('preview', 'screenshot', 'thumbnail')]
    if not em.supports(cfg):
        raise ValueError('This effect requires a DAT file; image import is not supported for this type')
    if len(images) != 1:
        raise ValueError('Choose one effect image per import (preview images are not effect payloads)')
    member = images[0]
    image_cfg = em.parse_cfg(cfg)
    px, _ = em.texels_from_upload(zf.read(member), Path(member).suffix.lower(), cfg)
    return character, cfg['id'], cfg, member, compute_dat_hash(em._png_bytes(px, image_cfg['width'], image_cfg['height']))


def _import_effect_mod(zip_path, zip_filename, effect_type, custom_title=None):
    """Import an effect/model mod using website-provided type info.

    Routes through the existing extras model system so the effect
    shows up in the Extras/Effects tab.

    Args:
        zip_path: Path to the uploaded ZIP file
        zip_filename: Original filename of the uploaded ZIP
        effect_type: Effect type ID from website tags (e.g. 'gun', 'laser')
        custom_title: Optional display name

    Returns:
        dict with success/error info, or None for an invalid ZIP
    """
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            character, effect_type, type_config, selected, _ = select_effect_payload(zf, zip_filename, effect_type)
            if not selected.lower().endswith('.dat'):
                from werkzeug.datastructures import FileStorage
                from vault.extras import effect_model as em
                mod = em.import_image_mod(FileStorage(stream=io.BytesIO(zf.read(selected)), filename=selected),
                                          character, effect_type, type_config,
                                          sanitize_filename(custom_title or Path(zip_filename).stem))
                return {'success': True, 'type': 'effect', 'imported_count': 1,
                        'character': get_storage_character(character, effect_type),
                        'effect_type': effect_type, 'id': mod['id'], 'message': f"Imported {mod['name']}"}
            image_exts = {'.png', '.jpg', '.jpeg', '.gif'}
            image_files = [n for n in zf.namelist()
                           if Path(n).suffix.lower() in image_exts
                           and not n.startswith('__MACOSX')]

            dat_name = selected

            dat_data = zf.read(dat_name)

            from vault.extras import sideb_model
            if sideb_model.supports(type_config):
                sideb_model.read_model(dat_data)

            # Reject malformed/wrong-bank archives and replacement geometry before storage.
            from vault.extras import effect_model as em
            if em.supports(type_config):
                kind, detail = em.classify_model(dat_data, type_config)
                if kind == em.CLASSIFY_MODEL:
                    raise ValueError('This DAT replaces effect geometry; replacement 3D effect models are not supported yet')

            storage_char = get_storage_character(character, effect_type)
            mod_id = f"{effect_type}_{uuid.uuid4().hex[:8]}"
            effect_name = custom_title or Path(zip_filename).stem
            effect_name = sanitize_filename(effect_name)

            modifications = {}
            if type_config.get('type') == 'model':
                # Model-type effect (e.g. gun) - extract .dae from .dat, into
                # a folder of its own (the export writes its textures beside
                # the .dae under fixed names)
                jobj_path = type_config.get('model_path')
                if not jobj_path:
                    return {
                        'success': False,
                        'error': f'Model path not configured for {effect_type}'
                    }
                models_dir, model_file = model_extra_location(STORAGE_PATH / storage_char, mod_id)
                models_dir.mkdir(parents=True, exist_ok=True)
                temp_dat = models_dir / f"{mod_id}_temp.dat"
                temp_dat.write_bytes(dat_data)
                try:
                    dae_path = models_dir / f"{mod_id}.dae"
                    extract_model_from_dat(temp_dat, jobj_path, dae_path)
                    logger.info(f"Extracted model from .dat to {dae_path}")
                except Exception:
                    shutil.rmtree(models_dir, ignore_errors=True)
                    raise
                finally:
                    temp_dat.unlink(missing_ok=True)
            else:
                # Non-model effect (color patches etc.) - store the .dat directly
                models_dir = STORAGE_PATH / storage_char / 'models'
                models_dir.mkdir(parents=True, exist_ok=True)
                dat_path = models_dir / f"{mod_id}.dat"
                dat_path.write_bytes(dat_data)
                model_file = f"models/{mod_id}.dat"

                # Color-format extras install from a 'modifications' dict, not
                # the stored DAT -- remake the downloaded mod through our
                # offset system (read its colors) or it installs as a no-op.
                modifications = derive_modifications_from_dat(
                    dat_path, effect_type, type_config)
                if 'image' in modifications:
                    # An image effect (image shines): derive marks it instead
                    # of returning colors it cannot read, and install rebuilds
                    # the effect model from the stored DAT's own texture
                    # (vault/routes/extras/effect_model.py).
                    logger.info(f"[Import] {effect_type} in {dat_name} is an "
                                f"image effect: {modifications['image']}")
                elif modifications:
                    logger.info(f"[Import] Derived {effect_type} modifications "
                                f"from {dat_name}: {modifications}")
                elif type_config.get('format') != 'texture_region':
                    dat_path.unlink(missing_ok=True)
                    raise ValueError(f'Could not read applicable {effect_type} colors from {dat_name}')

            # Save screenshot if present
            screenshot_file = None
            if image_files:
                screenshots_dir = STORAGE_PATH / storage_char / 'models'
                screenshots_dir.mkdir(parents=True, exist_ok=True)
                screenshot_path = screenshots_dir / f"{mod_id}_preview.png"
                screenshot_path.write_bytes(zf.read(image_files[0]))
                screenshot_file = f"models/{mod_id}_preview.png"
            elif type_config.get('format') == 'texture_region':
                # No screenshot in the zip: render the mod's actual texture
                # region as the preview (decoded from the imported DAT).
                try:
                    from vault.extras import texture_region as tr
                    cfg = tr.parse_cfg(type_config)
                    off = tr.locate_region(dat_data, cfg)
                    png = tr.region_to_png_bytes(
                        dat_data[off:off + cfg['size']], type_config)
                    screenshots_dir = STORAGE_PATH / storage_char / 'models'
                    screenshots_dir.mkdir(parents=True, exist_ok=True)
                    (screenshots_dir / f"{mod_id}_preview.png").write_bytes(png)
                    screenshot_file = f"models/{mod_id}_preview.png"
                except Exception as e:
                    logger.warning(f"texture_region preview render failed: {e}")
            elif 'image' in modifications:
                # No screenshot in the zip: decode the effect's own texture as
                # the preview, so an image shine's card shows the picture.
                try:
                    from vault.extras import effect_model as em
                    png = em.png_from_dat(dat_data, type_config)
                    screenshots_dir = STORAGE_PATH / storage_char / 'models'
                    screenshots_dir.mkdir(parents=True, exist_ok=True)
                    (screenshots_dir / f"{mod_id}_preview.png").write_bytes(png)
                    screenshot_file = f"models/{mod_id}_preview.png"
                except Exception as e:
                    logger.warning(f"image effect preview render failed: {e}")

            # Update metadata
            metadata = load_metadata(default={'characters': {}})
            metadata.setdefault('characters', {})

            if storage_char not in metadata.get('characters', {}):
                metadata['characters'][storage_char] = {'skins': [], 'extras': {}}

            char_data = metadata['characters'][storage_char]
            if 'extras' not in char_data:
                char_data['extras'] = {}
            if effect_type not in char_data['extras']:
                char_data['extras'][effect_type] = []

            new_mod = {
                'id': mod_id,
                'name': effect_name,
                'type': type_config.get('type', 'model'),
                'date_added': datetime.now().isoformat(),
                'source': 'nucleus',
                'model_file': model_file,
                'file_hash': compute_dat_hash(dat_data)
            }
            if screenshot_file:
                new_mod['screenshot'] = screenshot_file
            if modifications:
                new_mod['modifications'] = modifications
            if 'image' in modifications:
                # tag it so install/apply and the editor recognize it without
                # re-reading the DAT (vault/routes/extras/effect_model.py)
                new_mod['format'] = 'effect_model'
            elif sideb_model.is_model_mod(new_mod):
                new_mod['format'] = 'sideb_model'

            char_data['extras'][effect_type].append(new_mod)

            save_metadata(metadata)

            logger.info(f"[OK] Imported effect '{effect_name}' ({effect_type}) for {storage_char}")

            return {
                'success': True,
                'type': 'effect',
                'imported_count': 1,
                'character': storage_char,
                'effect_type': effect_type,
                'id': mod_id,
                'message': f"Imported {effect_name} ({effect_type} for {storage_char})"
            }

    except zipfile.BadZipFile:
        return None  # Not a valid zip
    except Exception as e:
        logger.error(f"Effect import error: {e}", exc_info=True)
        return {
            'success': False,
            'error': f'Effect import error: {str(e)}'
        }


def create_effect_unit_mod(character, primary, name, dat_bytes, dat_name):
    """A unit mod whose primary layers stay vanilla and which exists to
    carry nested parts (a website "charge flames" EfCoData becomes an Up-B
    mod with just that part). Stores the source DAT for provenance and
    duplicate detection. Returns {'id', 'character'}."""
    from core.extra_lookup import get_extra_type
    type_config = get_extra_type(character, primary) or {}
    storage_char = get_storage_character(character, primary)
    mod_id = f"{primary}_{uuid.uuid4().hex[:8]}"
    models_dir = STORAGE_PATH / storage_char / 'models'
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / f"{mod_id}.dat").write_bytes(dat_bytes)

    metadata = load_metadata(default={'characters': {}})
    char_data = metadata.setdefault('characters', {}).setdefault(storage_char, {'skins': [], 'extras': {}})
    mods = char_data.setdefault('extras', {}).setdefault(primary, [])
    mods.append({
        'id': mod_id,
        'name': sanitize_filename(name),
        'type': type_config.get('type', 'model'),
        'date_added': datetime.now().isoformat(),
        'source': 'nucleus',
        'model_file': f"models/{mod_id}.dat",
        'source_dat': dat_name,
        'file_hash': compute_dat_hash(dat_bytes),
        'modifications': {'parts': {}},
    })
    save_metadata(metadata)
    logger.info(f"[OK] Created unit mod '{name}' ({primary}) for {storage_char} to carry parts")
    return {'id': mod_id, 'character': storage_char}


def attach_effect_part(storage_char, primary, mod_id, part_id, part_mods):
    """Set one nested part recipe on a unit mod. Returns True when found."""
    from vault.extras.unit_parts import attach_part
    metadata = load_metadata(default={'characters': {}})
    mod = attach_part(metadata, storage_char, primary, mod_id, part_id, part_mods)
    if mod is None:
        return False
    save_metadata(metadata)
    logger.info(f"[OK] Attached part {part_id} to {primary} mod {mod_id}: {part_mods}")
    return True
