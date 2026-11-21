"""Stage colours that live outside textures and material descriptors: where each object's
colour comes from (evidence on the open), and the edits for vertex colours, animated
material colours and lights, with their reset. The DAT reading and byte edits are
shared/rendering/dat_colours.py; the edits, their reset and the renderer reload are
model_colours.py, which the Skin Lab uses too (costume_colours.py). This module is the
Stage Lab's side of them: how an edit names its objects, the stage's evidence, its lights.

Why it exists: many stage looks are in no texture. The VsMewtwo Final Destination's
whole background is Group 1: six objects whose render flags take VERTEX colours (lighting
off) over greyscale textures (CI8 with grey palettes, I4), so neither a texture recolor
nor a material colour reaches them; the purple there is RGB8 vertex colours stored in the
display lists. Battlefield's swirl, Pokemon Stadium's sky, Yoshi's Story's sky and ground
and Dream Land's tree are vertex colours too; Final Destination, Pokemon Stadium and
Battlefield also animate material colours (keys that replace the descriptor colour every
frame). Before this the model only learned that by testing blind.

* **Evidence** (`annotate`, `evidence`): every texture row gets `colour_from` (texture |
  material | vertex | animation | mixed, dat_colours.colour_from over the objects that
  draw it, with the live renderer's greyscale slots), and `colour_sources` lists, per
  group, the objects whose colour is not simply their texture's, by material id, and the
  lights that carry hue or animate (they tint every lit object: most of Fountain of Dreams).
* **Edits** (`action`): `recolor_vertex` and `recolor_animated` take `edits` like the
  texture recolor, each naming `material_ids` ('Group g:i', or 'Group g' for a whole
  group) or a `texture_index` (every object drawing it); model_colours does the rest.
  `recolor_lights` does the same for light colours and their keys. `reset_colors`
  restores them from the workspace's source.dat (the stage as opened), matched by
  structural key, so it also works after a resume.
* **How an edit reaches the renderer**: model_colours.reload, in the workspace folder:
  in place on a protocol-2 viewer (the changed vertex colours, keys and light colours;
  nothing restarts and the animation keeps playing), else the edited file loaded into
  the running renderer (loadDat) or a fresh plain renderer (as a scenery edit does): the
  camera is kept, earlier texture and material edits are in the export, the animation
  restarts at frame 0. An edit put in place carries a `viewer_update` with the same
  colour messages (continuity), so the workbench's 3D view swaps them in place too;
  otherwise the workbench reloads.
"""
from pathlib import Path

import numpy as np

from core import config
from shared.rendering import dat_colours as dc
from shared.rendering.session import ViewerSession
from . import lab_common, model_colours as mc

ACTIONS = {'color_sources', 'recolor_vertex', 'recolor_animated', 'recolor_lights', 'reset_colors'}
# Colour hints listed per group in the evidence (the rest are named, not described).
HINTS_PER_GROUP = 12

NOTE = ('colour_from says which store holds a surface\'s colour, so which edit changes it: texture -> recolor; '
        'material -> set_material (or recolor); vertex -> recolor_vertex (per-vertex colours multiplied with the '
        'texture, usually a greyscale one); animation -> recolor_animated (keys that replace the material colour every '
        'frame); mixed -> several, change the one holding the colour you see. colour_sources names, per group, the '
        'objects (material_id "Group g:i") whose colour is not simply their texture\'s, with each vertex-coloured '
        'object\'s colour (#dark..#light for a gradient); some only show during a stage animation. "lights" names '
        'coloured or animated lights, which tint lit surfaces: recolor_lights.')


# --------------------------------------------------------------------------- #
# evidence                                                                     #
# --------------------------------------------------------------------------- #
def _grey(item):
    """Names of the textures the live renderer shows as greyscale slots."""
    names = {t['index']: t.get('name') for t in item['viewer'].textures}
    return {names[i] for i in item.get('greyscale') or () if names.get(i)}


def _summary(item, data=None):
    """{texture name: colour_from}, {group: evidence string}: cached per renderer."""
    viewer = item['viewer']
    cached = item.get('colour_scan')
    if cached and cached['viewer'] is viewer:
        return cached
    inv = dc.scan(data if data is not None else viewer.export_dat())
    grey = _grey(item)
    textures, groups = {}, {}
    for obj in inv.objects:
        kind, parts = dc.colour_from(obj, inv.dat, grey)
        for texture in obj.textures:
            if texture.get('name'):
                textures.setdefault(texture['name'], set()).add(kind)
        if kind == 'texture':
            continue
        label = kind if kind != 'mixed' else '+'.join(parts)
        groups.setdefault(obj.group, {}).setdefault(label, []).append(obj)
    # A joint's hidden flag says nothing reliable about what shows (a stage animation, or the
    # renderer's branch rule, shows it anyway), so the evidence does not claim visibility.
    by_texture = {name: next(iter(kinds)) if len(kinds) == 1 else 'mixed' for name, kinds in textures.items()}
    described = {}
    for group, entry in sorted(groups.items()):
        pieces, hinted = [], 0
        for label, objects in sorted(entry.items()):
            text = f'{label} {mc.ranges(mc.index(o.id) for o in objects)}'
            hints = []
            for obj in objects:
                values = mc.vertex_colours(inv, obj)
                if 'vertex' in label and values and hinted < HINTS_PER_GROUP:
                    hints.append(f'{mc.index(obj.id)} {mc.hint(values)}')
                    hinted += 1
            pieces.append(text + (f' ({", ".join(hints)})' if hints else ''))
        described[f'Group {group}'] = '; '.join(pieces)
    # Lights tint every lit object (render flag DIFFUSE): listed when one carries hue or is animated.
    lit = sum(1 for obj in inv.objects if obj.render_flags & dc.RENDER_LIGHTING)
    seen, lights = set(), []
    for light in inv.lights:
        if light['offset'] in seen or not (dc._hue(light['rgba']) or light['tracks']):
            continue
        seen.add(light['offset'])
        lights.append(f"{light['where']} #{bytes(light['rgba'][:3]).hex()}" + (' animated' if light['tracks'] else ''))
    if lit and lights:
        described['lights'] = f'{lit} lit objects; ' + ', '.join(lights) + ' (recolor_lights)'
    item['colour_scan'] = {'viewer': viewer, 'textures': by_texture, 'groups': described}
    return item['colour_scan']


def annotate(item, rows):
    """`colour_from` on every texture row (an animation frame takes its base texture's)."""
    try:
        summary = _summary(item, _open_data(item))
    except Exception:
        return rows                   # the evidence is a help: an unreadable file never fails the open
    names = {t['index']: t.get('name') for t in item['viewer'].textures}
    for row in rows:
        index = row.get('animates', row['index'])
        name = names.get(row['index'] if index in (None, -1) else index)
        if name in summary['textures']:
            row['colour_from'] = summary['textures'][name]
    return rows


def evidence(item):
    """{'colour_sources', 'colour_note'} for the open's result (empty when the file cannot be read)."""
    try:
        summary = _summary(item, _open_data(item))
    except Exception:
        return {}
    return {'colour_sources': summary['groups'], 'colour_note': NOTE}


def _open_data(item):
    """The bytes the renderer shows when they are at hand (None: export them): the bytes the last colour
    edit loaded, or the workspace source while nothing has replaced the renderer's file."""
    if (item.get('colour_scan') or {}).get('viewer') is item['viewer']:
        return None                              # cached
    return shown_data(item)


def shown_data(item):
    """_open_data without the cache: the bytes the renderer shows when they are at hand, else None."""
    viewer = item['viewer']
    loaded = item.get('colour_data')
    if loaded and loaded[0] is viewer:
        return loaded[1]
    if not item.get('resumed') and not item.get('scene_instances') and not loaded:
        try:
            return Path(item['source']['datFile']).read_bytes()
        except (KeyError, OSError):
            return None
    return None


# --------------------------------------------------------------------------- #
# edits                                                                        #
# --------------------------------------------------------------------------- #
def _targets(item, inv, change):
    """The objects one edit names: material_ids ('Group g:i', or 'Group g' for a whole group) or a texture."""
    if 'texture_index' in change:
        index = change['texture_index']
        textures = {t['index']: t for t in item['viewer'].textures}
        if type(index) is not int or index not in textures:
            raise ValueError('texture_index must be a live texture index from the open or inspect.')
        texture = textures[index]
        if texture.get('matAnim') and texture.get('animates', -1) in textures:
            texture = textures[texture['animates']]
        objects = [o for o in inv.objects if any(t.get('name') == texture.get('name') for t in o.textures)]
        if not objects:
            raise ValueError(f'No object draws texture {index}.')
        return objects
    return mc.material_ids(inv, change.get('material_ids'), '"Group 1:0" (or "Group 1" for a whole group)',
                           '"Group g:i"')


def _plans(item, inv, edits, animated):
    return mc.plans(edits, lambda change: _targets(item, inv, change), animated)


def _recolor_vertex(item, edits):
    exported = item['viewer'].export_dat()
    inv = dc.scan(exported)
    result = mc.recolor_vertex(inv, _plans(item, inv, edits, animated=False))
    result['files'] = (_reload(item, inv.dat.data(), 'Recolored stage.png', exported) if result['changed']
                       else _frame(item))
    return result


def _recolor_animated(item, edits):
    exported = item['viewer'].export_dat()
    inv = dc.scan(exported)
    result = mc.recolor_animated(inv, _plans(item, inv, edits, animated=True))
    result['files'] = (_reload(item, inv.dat.data(), 'Recolored stage.png', exported) if result['changed']
                       else _frame(item))
    return result


def _lights(inv, names):
    """The lights an edit names (`Group g light i`, as colour_sources lists them), or every light."""
    if names is None:
        return inv.lights
    if not isinstance(names, list) or not names or any(not isinstance(n, str) for n in names):
        raise ValueError('lights lists light names from colour_sources, such as "Group 1 light 1".')
    known = {light['where']: light for light in inv.lights}
    unknown = [n for n in names if n not in known]
    if unknown:
        raise ValueError(f'Unknown lights {unknown}: use names from colour_sources.')
    return [known[n] for n in names]


def _recolor_lights(item, edits):
    """Light colours (LOBJ) and their colour animation keys: what lit surfaces are tinted by."""
    exported = item['viewer'].export_dat()
    inv = dc.scan(exported)
    result = _lights_edit(inv, edits)
    result['files'] = _reload(item, inv.dat.data(), 'Recolored stage.png', exported) if result['changed'] else _frame(item)
    return result


def _lights_edit(inv, edits):
    """The light edits made on inv.dat in place -> {'changed': {light: count}, 'note'?} (no files)."""
    dat = inv.dat
    if not isinstance(edits, list) or not 1 <= len(edits) <= mc.MAX_EDITS:
        raise ValueError(f'edits takes 1..{mc.MAX_EDITS} changes.')
    plans = []
    for change in edits:
        if not isinstance(change, dict) or set(change) - (mc.COLOUR_KEYS | {'lights', 'mask'}):
            raise ValueError('Each light edit takes optional lights, plus set_hue/set_saturation or '
                             'hue_shift/saturation_shift, optional lightness_scale and an optional colour mask.')
        value = lab_common.colour_change({k: v for k, v in change.items() if k in mc.COLOUR_KEYS})
        if change.get('mask') is not None:
            lab_common.select(np.zeros((1, 1, 4), np.uint8), change['mask'])
        plans.append((_lights(inv, change.get('lights')), value, change.get('mask')))
    changed = {}
    for lights, value, mask in plans:
        done = set()
        for light in lights:
            count = 0
            # A LOBJ two light entries share changes once (it holds pointers, so it is never copied).
            if light['offset'] not in done:
                done.add(light['offset'])
                base = [c / 255 for c in dat.raw(light['offset'], 3)]
                new = mc.adjust_bytes(dat.raw(light['offset'], 4), value, mask)
                if new is not None and new != dat.raw(light['offset'], 4):
                    dat.put(light['offset'], new)
                    count += 1
                for channels in mc.sets(light['tracks'], ('light',)).values():
                    count += mc.track_set(dat, channels, base, value, mask)[0]
            if count:
                changed[light['where']] = count
    result = {'changed': changed}
    if not changed:
        result['note'] = 'Nothing changed: check the light names, masks and values (a white light only darkens).'
    return result


def _reset(item, material_ids):
    """Vertex colours, animation keys and animated fields' descriptor colours (and, for the whole stage, light
    colours) back to the stage as opened."""
    source = dc.scan(Path(item['source']['datFile']).read_bytes())
    exported = item['viewer'].export_dat()
    inv = dc.scan(exported)
    dat = inv.dat
    objects = inv.objects if material_ids is None else _targets(item, inv, {'material_ids': material_ids})
    restored, unmatched = mc.restore(inv, source, objects)
    if material_ids is None:
        sources = {light['where']: light for light in source.lights}
        for light in inv.lights:
            original = sources.get(light['where'])
            if original is None:
                continue
            count = mc.restore_tracks(dat, source.dat, light['tracks'], original['tracks'])
            if dat.raw(light['offset'], 4) != source.dat.raw(original['offset'], 4):
                dat.put(light['offset'], source.dat.raw(original['offset'], 4))
                count += 1
            if count:
                restored[light['where']] = count
    result = {'restored': restored}
    if unmatched:
        result['unmatched'] = unmatched
        result['note'] = 'unmatched objects no longer have the opened stage\'s layout (scenery changed them).'
    result['files'] = _reload(item, dat.data(), 'Reset stage.png', exported) if restored else _frame(item)
    return result


# --------------------------------------------------------------------------- #
# the renderer                                                                 #
# --------------------------------------------------------------------------- #
def _frame(item):
    return mc.frame(item, 'Stage preview.png')


def _start(path):
    from core.viewer_tools import find_available_port
    return ViewerSession(config.HSDRAW_EXE, find_available_port(), path, logs_path=config.LOGS_PATH,
                         subprocess_kwargs=config.get_subprocess_args())


def _reload(item, data, name, previous=None):
    """Show `data` in the session's renderer, in the stage's workspace (model_colours.reload): in place
    when the renderer can take it, else reloaded. `previous`: the export the edit was made on."""
    return mc.reload(item, data, name, _start, Path(item['source']['datFile']).parent, previous)


# --------------------------------------------------------------------------- #
# the labs' apply batch (lab_common.apply_batch): edits on one export, one reload  #
# --------------------------------------------------------------------------- #
def batch_context(item, inv):
    return {}


def batch_targets(item, inv, change, context):
    """The objects an edit names (material_ids or a texture_index), as recolor_vertex resolves them."""
    return _targets(item, inv, change)


def batch_edit(item, inv, kind, change, context):
    """One recolor_vertex / recolor_animated / recolor_lights edit made on inv.dat -> its result (no files)."""
    if kind == 'recolor_lights':
        return _lights_edit(inv, [change])
    animated = kind == 'recolor_animated'
    plans = _plans(item, inv, [change], animated)
    return (mc.recolor_animated if animated else mc.recolor_vertex)(inv, plans)


def batch_finish(item, inv, context, result):
    """Nothing to add for a stage (a costume names the hidden objects it left)."""


def batch_reload(item, data, previous):
    return _reload(item, data, 'Edited stage.png', previous)


def action(item, action, edits=None, material_ids=None):
    """One Stage Lab colour action (ACTIONS) on a live session item; the caller holds the lab's lock."""
    if action == 'color_sources':
        summary = _summary(item, _open_data(item))
        return {'colour_sources': summary['groups'], 'note': NOTE}
    if action == 'reset_colors':
        if edits is not None:
            raise ValueError('reset_colors takes material_ids (or nothing, for the whole stage), not edits.')
        return _reset(item, material_ids)
    if material_ids is not None:
        raise ValueError('Send edits alone: each edit carries its own material_ids or texture_index.')
    run = {'recolor_vertex': _recolor_vertex, 'recolor_animated': _recolor_animated, 'recolor_lights': _recolor_lights}
    return run[action](item, edits)
