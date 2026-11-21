"""Material controls shared by Randall's private costume and stage sessions."""
import json
import math
import re

ACTIONS = {'materials', 'set_material', 'reset_material', 'preview_base_colors'}
COLOUR_SHAPE = ("eight-digit RGBA, such as #ff0000ff (#ff0000 or [255, 0, 0] keep the field's own alpha, "
                "[255, 0, 0, 255] sets it)")


def rgba_hex(value, current=None):
    """A material colour as the renderer takes it, '#rrggbbaa', from that or the forms a caller sends for it:
    '#rrggbb' or [r, g, b] (the field's `current` alpha kept, as a palette recolor keeps it) or [r, g, b, a], in
    whole numbers 0..255. -> the string, or None when `value` is none of them."""
    alpha = current[7:9] if isinstance(current, str) and re.fullmatch(r'#[0-9a-fA-F]{8}', current) else 'ff'
    if isinstance(value, str) and re.fullmatch(r'#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?', value):
        return value if len(value) == 9 else value + alpha
    if isinstance(value, list) and len(value) in (3, 4) and all(type(v) is int and 0 <= v <= 255 for v in value):
        return '#' + ''.join(f'{v:02x}' for v in value) + (alpha if len(value) == 3 else '')
    return None


def palette_snapshot(viewer):
    import numpy as np
    originals, fields = {}, {}
    for material in viewer.material_command({'type': 'getMaterials'})['materials']:
        for field in material['fields']:
            if field['kind'] != 'color': continue
            if len(fields) >= 4096: raise ValueError('Too many material colors for one palette')
            key = f'material:{len(fields)}'
            rgb = [int(field['value'][i:i+2], 16) for i in (1, 3, 5)]
            # Same minimum weight as the UI; alpha does not gate material RGB.
            originals[key] = np.tile(np.array([*rgb, 255], dtype=np.uint8), (1, 100, 1))
            fields[key] = (material['id'], field['key'], field['value'][7:])
    return originals, fields


def palette_edits(originals, fields, maps, adjustments):
    from shared.rendering.palette import apply_adjustments
    edits = []
    for key, (material_id, field, alpha) in fields.items():
        pixels = apply_adjustments(originals[key], maps[key], adjustments)
        if pixels is None: pixels = originals[key]
        rgb = ''.join(f'{int(v):02x}' for v in pixels[0, 0, :3])
        edits.append({'id': material_id, 'field': field, 'value': f'#{rgb}{alpha}'})
    return edits


def material_action(viewer, action, material_id=None, field=None, value=None, enabled=None):
    if action == 'materials':
        command = {'type': 'getMaterials'}
    elif action == 'preview_base_colors':
        if type(enabled) is not bool:
            raise ValueError('enabled must be a boolean')
        command = {'type': 'previewBaseColors', 'enabled': enabled}
    else:
        inventory = viewer.material_command({'type': 'getMaterials'})
        material = next((m for m in inventory['materials'] if m['id'] == material_id), None)
        target = next((f for f in material['fields'] if f['key'] == field), None) if material else None
        if not target:
            raise ValueError('Choose a material ID and field from materials inspection')
        command = {'type': 'setMaterial', 'id': material_id, 'field': field}
        if action == 'reset_material':
            command['reset'] = True
        elif target['kind'] == 'color':
            colour = rgba_hex(value, target.get('value'))
            if colour is None:
                raise ValueError(f'Use an {COLOUR_SHAPE}')
            command['value'] = colour
        else:
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= (1 if field == 'alpha' else 128):
                raise ValueError('Opacity must be 0..1; shininess must be 0..128')
            command['value'] = value
    result = viewer.material_command(command)
    result.pop('requestId', None)
    note = 'Base descriptor colors. Animation and render flags may override them. Preview base colors is view-only; saved animations remain unchanged.'
    listed = result.pop('materials', None)
    if isinstance(listed, list):
        if action in {'set_material', 'reset_material'}:
            # Only the material that changed; the model already has the rest.
            result['material'] = next(iter(compact([m for m in listed if m.get('id') == material_id])), None)
        else:
            result['materials'] = compact(listed)
            result['material_count'] = len(listed)
            note += (' Materials with identical values are one row: `ids` lists every material in it, '
                     'and set_material changes one id at a time.')
    result['note'] = note
    return result


def compact(materials):
    """The material inventory as rows of identical materials, `key: value` only.

    The viewer's own listing repeats every field with its label and kind for
    every mesh: Samus's 95 materials came to ~19k tokens, re-read by every
    later round, and set_material returned all of it again. Ids and field keys
    are unchanged, so every edit reads exactly as before.
    """
    rows = {}
    for material in materials:
        fields = {f['key']: f['value'] for f in material.get('fields', []) if 'key' in f}
        flags = {k: material[k] for k in ('animated', 'renderFlags') if material.get(k)}
        signature = json.dumps([fields, flags], sort_keys=True)
        row = rows.setdefault(signature, {'ids': [], **flags, 'fields': fields})
        row['ids'].append(material.get('id'))
    return list(rows.values())
