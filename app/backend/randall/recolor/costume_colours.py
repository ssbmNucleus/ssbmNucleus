"""Costume colours that live outside textures: the Skin Lab's side of model_colours.py.

No vanilla fighter colours a surface through vertex colours, but mods do: the Paper
Mario Game & Watch in the owner's vault colours 59 of its 116 objects, the red shirt and
blue overalls included, with RGB8 vertex colours only, and the Peach mod `plpeae`
multiplies 11 objects' textures with them. Yoshi has one vanilla colour animation (two
objects on joint 3). A texture recolor silently cannot change any of those.

* **Evidence** (`annotate`, `evidence`, `part_kinds`). Every texture row gets
  `colour_from` (texture | material | vertex | animation | mixed, dat_colours.colour_from
  over the objects that draw it; a texture's own format says whether it is greyscale),
  every known part too (its objects are the ones drawing its textures). When some
  object takes vertex colours or animated colours, `colour_sources` adds, per known part
  (else under "no known part"), the objects whose colour is not simply their texture's
  by material id (`Model:i`), which of them the fighter hides (`hidden`: the low-poly
  model and the alternate model options moves swap in, read from the fighter's model
  lookup tables, shared/rendering/lowpoly.hidden_objects), and which objects carry
  each vertex colour (`vertex_colours`).
* **Edits** (`action`): `recolor_vertex` and `recolor_animated` take `edits`, each
  naming a `part` (every object drawing that part's textures, hidden ones included,
  as a texture edit reaches them), `material_ids` or a `texture_index`, with the
  texture recolor's change and colour mask (model_colours). `reset_colors` restores
  them from the session's source file (the costume as opened, an immutable chat file
  the resume record names), so it also works after a resume.
* **Reach.** Every edit is made; what it changed beyond what it names is said in the
  result (`also_changed_parts`, `_reach`), never refused: a pointer two objects read
  (dat_colours.entangled), or, for an edit by part, an object that draws another
  part's textures too. A buffer another object also reads is not that: model_colours
  copies it so the named objects change alone.
* **The renderer**: the edit is made on its exported DAT and model_colours.reload shows
  it: in place on a protocol-2 viewer (the changed vertex colours and keys; nothing
  restarts), else the file loaded into the running renderer (loadDat) or a fresh one
  started like the session's own (skin_lab._viewer: the fighter's scene, animations
  and model tables), in the session's private folder. Nothing a reloaded renderer
  holds of a palette analysis is assumed: the next recolor sends its textures again.
  An edit put in place carries a `viewer_update` with the same colour messages
  (continuity), so the workbench swaps it in place too; else it reloads the checkpoint.
"""
from pathlib import Path

from shared.rendering import dat_colours as dc
from shared import mod_files
from . import model_colours as mc

ACTIONS = {'color_sources', 'recolor_vertex', 'recolor_animated', 'reset_colors'}
TARGETS = ('part', 'material_ids', 'texture_index')
NAMED = 'a part, material_ids or a texture_index'
# Vertex colour groups listed in the evidence (the rest are counted).
COLOUR_GROUPS = 24

NOTE = ('colour_from (each texture row, and known_parts) says which store holds a surface\'s colour, so which '
        'edit changes it: texture -> recolor; material -> set_material; vertex -> recolor_vertex (colours stored '
        'per vertex, multiplied with any texture); animation -> recolor_animated (keys that replace the material '
        'colour every frame); mixed -> several, change the one holding the colour you see. colour_sources lists the '
        'objects (material_id "Model:i") whose colour is not simply their texture\'s, by known part; "hidden" names '
        'those the fighter does not show by default (low-poly: its far-away model; alternate: a model piece some '
        'moves swap in) -- give them the same edit so every model matches; "vertex_colours" says which objects carry '
        'each colour. One object can carry several colours: a colour mask picks one of them.')


# --------------------------------------------------------------------------- #
# evidence                                                                     #
# --------------------------------------------------------------------------- #
def _model(inventory):
    """The objects of the model the renderer draws (dat_colours names them Model:i)."""
    return [o for o in inventory.objects if o.id.startswith('Model:')]


def _textures_of(obj):
    """The live texture indices an object draws (dat_colours names a costume's as the renderer does)."""
    out = set()
    for texture in obj.textures:
        name = texture.get('name') or ''
        if name.startswith('Texture_') and name[8:].isdigit():
            out.add(int(name[8:]))
    return out


def _open_data(item):
    """The bytes the renderer shows, when they are at hand (None: export them): the bytes the last colour
    edit loaded, else the session's private copy (the source, or after a resume the checkpoint it reopened)."""
    viewer = item['viewer']
    loaded = item.get('colour_data')
    if loaded:
        return loaded[1] if loaded[0] is viewer else None
    try:
        return (Path(item['scratch'].name) / item['source']['name']).read_bytes()
    except (KeyError, AttributeError, TypeError, OSError):
        return None


def _hidden(item):
    """{object id: 'low-poly' | 'alternate'} from the fighter's model tables, read once a session ({} unknown)."""
    if 'object_visibility' not in item:
        item['object_visibility'] = None
        origin = mod_files.origin_of(item.get('source') or {})
        character, code = origin.get('character'), origin.get('costume_code') or ''
        if character:
            from core.viewer_tools import find_fighter_data_file
            from shared.rendering.lowpoly import hidden_objects
            from shared.rendering.lowpoly_promote import costume_slot_for_code
            data_file = find_fighter_data_file(character)
            table = hidden_objects(data_file, costume_slot_for_code(character, code[4:6])) if data_file else None
            if table is not None:
                item['object_visibility'] = {f'Model:{i}': kind for i, kind in table.items()}
    return item['object_visibility'] or {}


def _summary(item):
    """What the evidence says, cached per renderer."""
    viewer = item['viewer']
    cached = item.get('colour_scan')
    if cached and cached['viewer'] is viewer:
        return cached
    from . import skin_lab
    data = _open_data(item)
    inventory = dc.scan(data if data is not None else viewer.export_dat())
    objects = _model(inventory)
    kinds = {o.id: dc.colour_from(o, inventory.dat) for o in objects}
    known = skin_lab.known_parts(item)
    named = (known or {}).get('parts') or {}
    parts_of = {o.id: [name for name, indices in named.items() if _textures_of(o) & set(indices)] for o in objects}
    hidden = _hidden(item)
    textures = {}
    for obj in objects:
        for texture in obj.textures:
            if texture.get('name'):
                textures.setdefault(texture['name'], set()).add(kinds[obj.id][0])
    part_kinds = {}
    for name in named:
        found = {kinds[o.id][0] for o in objects if name in parts_of[o.id]}
        if found:
            part_kinds[name] = next(iter(found)) if len(found) == 1 else 'mixed'
    item['colour_scan'] = {
        'viewer': viewer, 'parts_of': parts_of, 'hidden': hidden, 'known': known,
        'textures': {name: next(iter(k)) if len(k) == 1 else 'mixed' for name, k in textures.items()},
        'parts': part_kinds, 'sources': _describe(inventory, objects, kinds, parts_of, hidden),
        # Only these need the new edits; a costume coloured by textures and materials alone says nothing more.
        'beyond': any({'vertex', 'animation'} & set(kinds[o.id][1]) for o in objects)}
    return item['colour_scan']


def _describe(inventory, objects, kinds, parts_of, hidden):
    """colour_sources (module doc)."""
    by_owner, listed = {}, []
    for obj in objects:
        kind, parts = kinds[obj.id]
        if kind == 'texture':
            continue
        label = kind if kind != 'mixed' else '+'.join(parts)
        owner = '+'.join(parts_of[obj.id]) or 'no known part'
        by_owner.setdefault(owner, {}).setdefault(label, []).append(mc.index(obj.id))
        listed.append(obj)
    out = {}
    if by_owner:
        out['by_part'] = {owner: '; '.join(f'{label} {mc.ranges(ids)}' for label, ids in sorted(entry.items()))
                          for owner, entry in sorted(by_owner.items(), key=lambda pair: pair[0] == 'no known part')}
    shown = {}
    for obj in listed:
        if obj.id in hidden:
            shown.setdefault(hidden[obj.id], []).append(mc.index(obj.id))
    if shown:
        out['hidden'] = '; '.join(f'{kind} {mc.ranges(ids)}' for kind, ids in sorted(shown.items()))
    groups = {}
    for obj in listed:
        values = mc.vertex_colours(inventory, obj) if 'vertex' in kinds[obj.id][1] else []
        if values:
            groups.setdefault(mc.colours_hint(values), []).append(mc.index(obj.id))
    if groups:
        rows = sorted(groups.items(), key=lambda pair: min(pair[1]))
        out['vertex_colours'] = '; '.join(f'{hint} {mc.ranges(ids)}' for hint, ids in rows[:COLOUR_GROUPS]) + (
            f'; and {len(rows) - COLOUR_GROUPS} more colour sets' if len(rows) > COLOUR_GROUPS else '')
    return out


def annotate(item, rows):
    """`colour_from` on every texture row (an animation frame takes its base texture's). Rows are the
    caller's own dicts."""
    try:
        summary = _summary(item)
    except Exception:
        return rows                   # the evidence is a help: an unreadable file never fails the open
    names = {t['index']: t.get('name') for t in item['viewer'].textures}
    for row in rows:
        base = row['index']
        if row.get('matAnim') and row.get('animates', -1) not in (None, -1):
            base = row['animates']
        kind = summary['textures'].get(names.get(base))
        if kind:
            row['colour_from'] = kind
    return rows


def part_kinds(item):
    """{known part: colour_from}, or {}."""
    try:
        return dict(_summary(item)['parts'])
    except Exception:
        return {}


def evidence(item):
    """{'colour_sources', 'colour_note'} when some object takes vertex or animated colours, else {}."""
    try:
        summary = _summary(item)
    except Exception:
        return {}
    return {'colour_sources': summary['sources'], 'colour_note': NOTE} if summary['beyond'] else {}


# --------------------------------------------------------------------------- #
# edits                                                                        #
# --------------------------------------------------------------------------- #
def _targets(item, inventory, change, summary):
    """The objects one edit names: a known part, material_ids ('Model:i') or a texture."""
    objects = _model(inventory)
    if 'part' in change:
        known = (summary['known'] or {}).get('parts') or {}
        if not isinstance(change['part'], str) or change['part'] not in known:
            raise ValueError(f"Unknown part {change['part']!r}: " + (
                f'use one of known_parts ({", ".join(sorted(known))}) or material_ids.' if known else
                'this costume has no known parts; name material_ids from colour_sources.'))
        return [o for o in objects if change['part'] in summary['parts_of'].get(o.id, ())]
    if 'texture_index' in change:
        index = change['texture_index']
        textures = {t['index']: t for t in item['viewer'].textures}
        if type(index) is not int or index not in textures:
            raise ValueError('texture_index must be a live texture index from the open or inspect.')
        if textures[index].get('matAnim') and textures[index].get('animates', -1) in textures:
            index = textures[index]['animates']
        found = [o for o in objects if index in _textures_of(o)]
        if not found:
            raise ValueError(f'No object draws texture {index}.')
        return found
    return mc.material_ids(inventory, change.get('material_ids'), '"Model:0" (or "Model" for every object)',
                           '"Model:i"')


def _plans(item, inventory, edits, animated, summary):
    return mc.plans(edits, lambda change: _targets(item, inventory, change, summary), animated, TARGETS, NAMED)


def _reach(inventory, plans, store, summary):
    """What an edit reaches beyond what it names (module doc), in plain words: never a refusal.
    -> ["Model:3 (gloves): reads the same stored vertex colours", ...]"""
    lines = []
    for objects, _, _, fields, change in plans:
        used = [o for o in objects if dc.store_fields(o, store, fields)]
        for other in dc.entangled(inventory, used, store, fields if store == 'animation' else None):
            parts = '+'.join(summary['parts_of'].get(other) or []) or 'no known part'
            line = (f'{other} ({parts}): reads the same stored '
                    f'{"vertex colours" if store == "vertex" else "colour keys"} through one pointer')
            if line not in lines:
                lines.append(line)
        part = change.get('part')
        for o in used:
            others = [p for p in summary['parts_of'].get(o.id, ()) if p != part] if part else []
            if others:
                line = f"{o.id} ({' and '.join(repr(p) for p in others)}): also draws {part!r}, so it changed whole"
                if line not in lines:
                    lines.append(line)
    return lines


def _hidden_left(before, after, plans, changed, summary):
    """Hidden objects (low-poly, alternate) the edit left alone that carry a colour it changed.

    `before` is the file scanned before the edit, `after` the edited inventory (its objects'
    attributes point at the edited bytes); a colour counts when one of its vertices changed."""
    hidden = summary['hidden']
    named = {o.id for objects, *_ in plans for o in objects}
    if not hidden or not changed:
        return []
    moved = set()
    for object_id in changed:
        old, new = before.object(object_id), after.object(object_id)
        if old is not None and new is not None:
            moved |= {tuple(a[:3]) for a, b in zip(mc.vertex_colours(before, old), mc.vertex_colours(after, new))
                      if a != b}
    return [o.id for o in _model(before) if o.id in hidden and o.id not in named and dc.uses_vertex(o)
            and moved & {tuple(c[:3]) for c in mc.vertex_colours(before, o)}]


def _finish(item, result, inventory, before, plans, summary):
    """The preview (a reload when anything changed) and the notes on what the fighter hides."""
    if result['changed']:
        item['edited'] = True
        notes = [result['note']] if result.get('note') else []
        left = _hidden_left(before, inventory, plans, result['changed'], summary)
        if left:
            result['hidden_unchanged'] = left
            notes.append('hidden_unchanged objects (the low-poly model or an alternate piece some moves swap in) '
                         'carry a colour this edit changed and were not in it: add the ones that belong to the same '
                         'surface, so every model of the fighter matches.')
        if all(i in summary['hidden'] for i in result['changed']):
            notes.append('Every object changed is one the fighter does not show by default, so this preview looks '
                         'the same.')
        if notes:
            result['note'] = ' '.join(notes)
        result['files'] = _reload(item, inventory.dat.data(), 'Recolored skin.png', before)
    else:
        result['files'] = mc.frame(item, 'Skin preview.png')
    return result


def _edit(item, edits, animated):
    viewer = item['viewer']
    summary = _summary(item)
    inventory = dc.scan(viewer.export_dat())
    plans = _plans(item, inventory, edits, animated, summary)
    reached = _reach(inventory, plans, 'animation' if animated else 'vertex', summary)
    before = dc.scan(inventory.dat.data())         # the colours as they were, for _hidden_left
    result = (mc.recolor_animated if animated else mc.recolor_vertex)(inventory, plans)
    if reached and result['changed']:
        # Said, not refused: the model sees the render and decides (separate, or tell the user).
        result['also_changed_parts'] = reached
        result['note'] = ((result.get('note') or '') + ' also_changed_parts: objects outside what the edit named '
                          'that changed with it; check the render, and separate or report them.').strip()
    return _finish(item, result, inventory, before, plans, summary)


def _source(item):
    """The costume as the session opened it: its source chat file (immutable; the resume record names it)."""
    path, _ = mod_files.resolve(item['source']['file_id'])
    return path.read_bytes()


def _reset(item, material_ids):
    """Vertex colours, colour keys and animated fields' descriptor colours back to the costume as opened."""
    source = dc.scan(_source(item))
    exported = item['viewer'].export_dat()
    inventory = dc.scan(exported)
    objects = _model(inventory) if material_ids is None else mc.material_ids(
        inventory, material_ids, '"Model:0" (or "Model" for every object)', '"Model:i"')
    restored, unmatched = mc.restore(inventory, source, objects)
    result = {'restored': restored}
    if unmatched:
        result['unmatched'] = unmatched
        result['note'] = 'unmatched objects no longer have the opened costume\'s layout.'
    result['files'] = (_reload(item, inventory.dat.data(), 'Reset skin.png', exported) if restored
                       else mc.frame(item, 'Skin preview.png'))
    return result


def _reload(item, data, name, previous=None):
    """`data` shown by the session's renderer (model_colours.reload): in place when it can take it, else
    loaded into it (loadDat) or a fresh renderer started as skin_lab starts one. `previous`: the export
    (bytes or scan) the edit was made on."""
    from . import skin_lab
    files = mc.reload(item, data, name, lambda path: skin_lab._viewer(path, item['source']), Path(item['scratch'].name),
                      previous)
    analysis = item.get('palette')
    if analysis is not None and not item.get('viewer_colours'):
        # A reloaded renderer holds the exported textures: send them again. Put in place,
        # it still holds exactly what it was sent.
        analysis['live'] = {}
    return files


# --------------------------------------------------------------------------- #
# the labs' apply batch (lab_common.apply_batch): edits on one export, one reload  #
# --------------------------------------------------------------------------- #
def batch_context(item, inventory):
    """What every edit of one batch shares: the evidence, the colours before it (for hidden_unchanged)."""
    return {'summary': _summary(item), 'before': dc.scan(inventory.dat.data()), 'plans': []}


def batch_targets(item, inventory, change, context):
    """The objects an edit names (a part, material_ids or a texture_index), as recolor_vertex resolves them."""
    return _targets(item, inventory, change, context['summary'])


def batch_edit(item, inventory, kind, change, context):
    """One recolor_vertex / recolor_animated edit made on inventory.dat -> its result (no files), with
    `also_changed_parts` as the single action says them."""
    if kind == 'recolor_lights':
        raise ValueError('A costume has no lights to recolor (recolor_lights is the Stage Lab\'s).')
    animated = kind == 'recolor_animated'
    plans = _plans(item, inventory, [change], animated, context['summary'])
    reached = _reach(inventory, plans, 'animation' if animated else 'vertex', context['summary'])
    result = (mc.recolor_animated if animated else mc.recolor_vertex)(inventory, plans)
    if result['changed']:
        context['plans'] += plans
        if reached:
            result['also_changed_parts'] = reached
    return result


def batch_finish(item, inventory, context, result):
    """After the batch's colour edits: the hidden objects (low-poly, alternate) left with a colour it changed."""
    changed = result.get('changed_objects') or []
    if changed:
        item['edited'] = True
        left = _hidden_left(context['before'], inventory, context['plans'], changed, context['summary'])
        if left:
            result['hidden_unchanged'] = left


def batch_reload(item, data, previous):
    return _reload(item, data, 'Edited skin.png', previous)


def action(item, action, edits=None, material_ids=None):
    """One Skin Lab colour action (ACTIONS) on a live session item; the caller holds the lab's lock."""
    if action == 'color_sources':
        summary = _summary(item)
        return {'colour_sources': summary['sources'], 'parts': summary['parts'], 'note': NOTE}
    if action == 'reset_colors':
        if edits is not None:
            raise ValueError('reset_colors takes material_ids (or nothing, for every object), not edits.')
        return _reset(item, material_ids)
    if material_ids is not None:
        raise ValueError('Send edits alone: each edit carries its own part, material_ids or texture_index.')
    return _edit(item, edits, animated=action == 'recolor_animated')
