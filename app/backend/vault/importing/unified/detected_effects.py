"""
Importing the effect mods detected in an upload: one stored extra per detected
effect, the duplicate check, and effect pictures (image shines).
"""

import os
import zipfile
import tempfile
from pathlib import Path
from core.metadata import load_metadata
from core.extra_lookup import get_extra_type, get_storage_character
from vault.importing.unified.detection import _read_member
from vault.importing.unified.helpers import check_duplicate_effect, sanitize_filename
from vault.importing.unified.effects import _import_effect_mod, select_effect_payload
from vault.importing.unified.dialogs import _choice_dialog
from vault.importing.unified.menu_import import _archive_images


# ── effects (extras) ─────────────────────────────────────────────────────────

def _effect_zip_name(filename, character):
    """The effect importer reads the character off the archive name
    ('Fox_<title>.zip'); synthesize that from an explicit character hint."""
    if character:
        return f"{character}_{Path(filename).stem}.zip"
    return filename


def _effect_located(message, storage_char):
    return f'{message} — Characters › {storage_char} › Extras' if storage_char else message


def _effect_duplicate_response(temp_zip_path, zip_name, effect_type, duplicate_action):
    """The duplicate gate for effects: None to proceed, else a (payload,
    status) that skips or asks."""
    if duplicate_action == 'import_anyway':
        return None
    try:
        with zipfile.ZipFile(temp_zip_path, 'r') as zf:
            character, effect_type_key, _, _, file_hash = select_effect_payload(zf, zip_name, effect_type)
    except (zipfile.BadZipFile, KeyError, ValueError):
        return None
    if not file_hash:
        return None
    storage_char = get_storage_character(character, effect_type_key)
    metadata = load_metadata(default={'characters': {}})
    existing = check_duplicate_effect(storage_char, effect_type_key, file_hash, metadata)
    if not existing:
        return None
    screenshot_url = (f"/storage/{storage_char}/{existing['screenshot']}"
                      if existing.get('screenshot') else None)
    duplicate_detail = {
        'character': storage_char,
        'color': existing['name'],
        'existing_skin': {'id': existing['id'], 'name': existing['name'], 'csp_url': screenshot_url},
    }
    if duplicate_action == 'skip':
        return {
            'success': True,
            'type': 'effect',
            'imported_count': 0,
            'skipped_count': 1,
            'skipped_duplicates': [duplicate_detail],
            'message': f"Skipped effect (already owned): {existing['name']}"
        }, 200
    return {
        'success': False,
        'type': 'duplicate_dialog',
        'mod_type': 'effect',
        'duplicate_skins': [duplicate_detail],
        'message': 'You already have this effect!'
    }, 200


def _import_detected_effects(temp_zip_path, filename, detail, custom_title, duplicate_action):
    """Import every extra the detector found DIFFERING from vanilla, one mod
    per MOVE: a DAT recoloring laser + shine yields two mods, while flight
    puffs + charge flames + Up-B colors fold into ONE Up-B mod carrying those
    parts (core.extra_types.UNIT_PARTS). Undecidable files (no vanilla
    reference) ask; all-vanilla files are refused."""
    from core.extra_lookup import part_owner
    from .effects import create_effect_unit_mod, attach_effect_part
    from vault.extras.derive import derive_modifications_from_dat

    dats = detail.get('dats', [])
    differing = [(d, c) for d in dats for c in d['candidates'] if c['differs']]
    undecided = [(d, c) for d in dats for c in d['candidates'] if c['differs'] is None]
    errors = []
    if not differing and undecided:
        d = undecided[0][0]
        options = [{
            'key': f"effect:{c['character']}:{c['extra_type']}",
            'label': f"{c['name']} ({c['character']})",
            'description': f"Import {dd['dat']} as this effect.",
            'hints': {'mod_type': 'effect', 'effect_type': c['extra_type'],
                      'character': c['character']},
        } for dd, c in undecided]
        return _choice_dialog(
            filename,
            f"{d['dat']} is an effect file, but no vanilla ISO is recorded to tell "
            'which effect it changes. Import it as:',
            options, default=options[0]['key'])
    for d in dats:
        if not any(c['differs'] for c in d['candidates']):
            if d['candidates']:
                errors.append(f"{d['dat']}: every editable effect layer matches vanilla, nothing to import")
            else:
                errors.append(f"{d['dat']}: no effect layer Nucleus can read")
    if not differing:
        return {'success': False, 'type': 'effect', 'error': '; '.join(errors) or 'No effect imported'}, 400

    # One group per (character, unit): the unit's own layers plus its parts.
    groups = {}
    for d, c in differing:
        primary = part_owner(c['extra_type']) or c['extra_type']
        group = groups.setdefault((c['character'], primary), {'primary': None, 'parts': []})
        if c['extra_type'] == primary:
            group['primary'] = (d, c)
        else:
            group['parts'].append((d, c))

    base_title = custom_title or Path(filename).stem
    multi = len(groups) > 1
    results = []

    def _derive_part(d, c):
        cfg = get_extra_type(c['character'], c['extra_type'])
        data = _read_member(temp_zip_path, d.get('member') or d['dat'])
        if not cfg or not data:
            return None
        with tempfile.NamedTemporaryFile(suffix='.dat', delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        try:
            mods = derive_modifications_from_dat(tmp_path, c['extra_type'], cfg)
        finally:
            os.unlink(tmp_path)
        return mods if mods and 'image' not in mods else None

    for (character, primary), group in groups.items():
        primary_cfg = get_extra_type(character, primary) or {}
        unit_name = primary_cfg.get('name', primary)
        title = f"{base_title} ({unit_name})" if multi else base_title
        zip_name = _effect_zip_name(filename, character)
        if group['primary'] is not None:
            dup = _effect_duplicate_response(temp_zip_path, zip_name, primary, duplicate_action)
            if dup is not None:
                payload, status = dup
                if payload.get('type') == 'duplicate_dialog':
                    return dup
                results.append(payload)   # skipped duplicate summary
                continue
            result = _import_effect_mod(temp_zip_path, zip_name, primary, title)
            if not result or not result.get('success'):
                errors.append(f"{group['primary'][0]['dat']} as {unit_name}: "
                              f"{(result or {}).get('error', 'import failed')}")
                continue
        else:
            # Only parts differ (a charge-flames EfCoData, a fireball-aura
            # PlMr): a unit mod whose primary layers stay vanilla.
            d, c = group['parts'][0]
            data = _read_member(temp_zip_path, d.get('member') or d['dat']) or b''
            created = create_effect_unit_mod(character, primary, title, data, d['dat'])
            result = {
                'success': True, 'type': 'effect', 'imported_count': 1,
                'character': created['character'], 'effect_type': primary, 'id': created['id'],
                'message': f"Imported {sanitize_filename(title)} ({unit_name} for {created['character']})",
            }
        attached = []
        for d, c in group['parts']:
            part_mods = _derive_part(d, c)
            if part_mods and attach_effect_part(result['character'], primary, result['id'],
                                                c['extra_type'], part_mods):
                attached.append(c['name'])
            else:
                errors.append(f"{d['dat']}: could not read {c['name']} into the {unit_name} mod")
        if attached:
            result['message'] += ' with ' + ', '.join(attached)
        results.append(result)

    imported = [r for r in results if r.get('imported_count', 1)]
    skipped = [s for r in results for s in r.get('skipped_duplicates', [])]
    if not imported and not skipped:
        return {'success': False, 'type': 'effect', 'error': '; '.join(errors) or 'No effect imported'}, 400
    chars = sorted({r.get('character') for r in imported if r.get('character')})
    def _summary(r):
        m = r.get('message', '')
        return m[len('Imported '):] if m.startswith('Imported ') else m
    message = f"Imported {len(imported)} effect(s): " + ', '.join(_summary(r) for r in imported)
    if skipped:
        message += f'; skipped {len(skipped)} already owned'
    if errors:
        message += '; ' + '; '.join(errors)
    if len(chars) == 1:
        message = _effect_located(message, chars[0])
    return {
        'success': True,
        'type': 'effect',
        'imported_count': len(imported),
        'skipped_count': len(skipped),
        'skipped_duplicates': skipped,
        'effects': imported,
        'message': message,
    }, 200


def _import_effect_image(temp_zip_path, character, effect_type, custom_title):
    """A lone picture into an image-capable extra: shine images (effect
    model) or the shield bubble texture (texture region)."""
    cfg = get_extra_type(character, effect_type)
    if not cfg:
        return {'success': False, 'error': f'Effect type "{effect_type}" not defined for {character}'}, 400
    try:
        images = _archive_images(temp_zip_path)
    except zipfile.BadZipFile:
        return {'success': False, 'error': 'Invalid or corrupt zip file'}, 400
    if len(images) != 1:
        return {'success': False, 'error': 'Choose one picture per effect import'}, 400
    member, raw = images[0]
    name = sanitize_filename(custom_title or Path(member).stem)
    try:
        if cfg.get('format') == 'texture_region':
            from vault.extras.texture_region import import_texture_region_bytes
            mod = import_texture_region_bytes(raw, Path(member).suffix.lower(),
                                              character, effect_type, cfg, name)
        else:
            import io
            from werkzeug.datastructures import FileStorage
            from vault.extras import effect_model as em
            if not em.supports(cfg):
                return {'success': False,
                        'error': f'{cfg.get("name", effect_type)} does not take a picture'}, 400
            mod = em.import_image_mod(FileStorage(stream=io.BytesIO(raw), filename=member),
                                      character, effect_type, cfg, name)
    except Exception as e:
        return {'success': False, 'error': f'Effect image import failed: {e}'}, 400
    storage_char = get_storage_character(character, effect_type)
    return {
        'success': True,
        'type': 'effect',
        'imported_count': 1,
        'character': storage_char,
        'effect_type': effect_type,
        'id': mod['id'],
        'message': _effect_located(f"Imported {mod['name']} as {cfg.get('name', effect_type)}", storage_char),
    }, 200
