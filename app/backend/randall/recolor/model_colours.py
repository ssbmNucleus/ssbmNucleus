"""Colour that lives in no texture, edited the same way on a stage and on a costume.

The DAT reading and the byte edits are shared/rendering/dat_colours.py. This module is
what the Stage Lab (stage_colours.py) and the Skin Lab (costume_colours.py) share on top
of it; each lab keeps only what is its own (how an edit names its objects, its
evidence, the stage's lights, the costume's parts and scope gate, how its renderer
starts).

* **Edits.** `plans` validates a batch of edits (each names its objects through the
  lab's own `resolve`, plus the texture recolor's change: set_hue/set_saturation or
  hue_shift/saturation_shift, lightness_scale and an optional colour mask).
  `recolor_vertex` changes vertex colours (format, count and alpha kept; a buffer
  other objects also read is copied first, dat_colours.isolate), `recolor_animated`
  the keys of material colour animations (frame, interpolation and format kept; a
  spline tangent follows the new curve; R, G and B keyed at different frames are
  re-keyed on the most detailed channel's, `_align`). Both use the texture path's
  own maths (lab_common.adjust; keys the same formula unrounded). `restore` puts
  objects back to the file as opened, matched by structural key.
* **What else changes.** An object outside the named ones that reads one of the same
  pointer fields (dat_colours.entangled) changes with them: the result names it
  (`also_changed`). The Skin Lab refuses such an edit before it runs, until the
  user's scope choice covers it.
* **The renderer.** An edit is made on its exported DAT; `reload` then shows the edited
  bytes. A protocol-2 viewer (session.supports) takes the change in place: what changed
  (dat_colours.colour_messages: vertex colours, key streams, material and light colours)
  goes to it as setVertexColors / setAnimationColors / setLightColors, and the picture
  matches a fresh renderer on the edited file. Otherwise, or when that fails, the file
  is loaded into the running renderer (loadDat), and with an older viewer a fresh
  renderer replaces the session's, as before (camera kept; the texture list must come
  back the same or the edit is not applied). The messages sent in place are kept
  (`viewer_colours`) for the workbench's `viewer_update` (continuity), so its 3D view
  swaps them in place too.
"""
import logging
import uuid
from collections import Counter

import numpy as np

from shared.rendering import dat_colours as dc
from shared.rendering import palette
from . import lab_common

log = logging.getLogger(__name__)

MAX_EDITS = 64
MAX_IDS = 256
FIELDS = ('diffuse', 'ambient', 'specular', 'constant', 'tev0', 'tev1')
DEFAULT_FIELDS = ('diffuse', 'ambient')
COLOUR_KEYS = {'hue_shift', 'saturation_shift', 'set_hue', 'set_saturation', 'lightness_scale'}
NOTHING_CHANGED = 'Nothing changed: check the ids, masks and values.'


# --------------------------------------------------------------------------- #
# evidence helpers                                                             #
# --------------------------------------------------------------------------- #
def hexc(colour):
    return '#' + ''.join(f'{int(v):02x}' for v in colour[:3])


def hint(values):
    """One vertex-coloured object's colour: '#rrggbb', or '#dark..#light' for a gradient."""
    lo = min(values, key=lambda c: sum(c[:3]))
    hi = max(values, key=lambda c: sum(c[:3]))
    if max(abs(int(a) - int(b)) for a, b in zip(lo[:3], hi[:3])) <= dc.NEUTRAL_SPREAD:
        mean = [round(sum(c[i] for c in values) / len(values)) for i in range(3)]
        return hexc(mean)
    return f'{hexc(lo)}..{hexc(hi)}'


def colours_hint(values, limit=4):
    """The colours one object is painted with: its few dominant colours ('#a #b'), or
    hint()'s '#dark..#light' when it is shaded rather than painted in flat colours."""
    counts = Counter(tuple(int(v) for v in c[:3]) for c in values)
    total = sum(counts.values())
    major = [c for c, n in counts.most_common() if n >= 0.05 * total][:limit]
    if major and sum(counts[c] for c in major) >= 0.8 * total:
        return ' '.join(hexc(c) for c in major)
    return hint(values)


def ranges(numbers):
    numbers = sorted(numbers)
    out, start = [], None
    for i, n in enumerate(numbers):
        if start is None:
            start = n
        if i + 1 == len(numbers) or numbers[i + 1] != n + 1:
            out.append(str(start) if start == n else f'{start}-{n}')
            start = None
    return ','.join(out)


def index(object_id):
    """The number after the colon of a material id ('Group 1:7', 'Model:7' -> 7)."""
    return int(object_id.rsplit(':', 1)[1])


def vertex_colours(inventory, obj):
    return [rgba for v in obj.vertex for _, rgba in dc.vertex_values(inventory.dat, v)]


# --------------------------------------------------------------------------- #
# validation                                                                   #
# --------------------------------------------------------------------------- #
def plans(edits, resolve, animated, targets=('material_ids', 'texture_index'),
          named='material_ids or a texture_index'):
    """Validated edits -> [(objects, value, mask, fields, change)], before anything changes.

    Each edit names exactly one of `targets` (resolve(change) -> its objects, raising
    ValueError for an unknown one; `named` says them in the error) plus a colour change
    and an optional colour mask; `fields` only for an animated edit.
    """
    if not isinstance(edits, list) or not 1 <= len(edits) <= MAX_EDITS:
        raise ValueError(f'edits takes 1..{MAX_EDITS} changes.')
    allowed = set(targets) | COLOUR_KEYS | {'mask'} | ({'fields'} if animated else set())
    out = []
    for change in edits:
        if (not isinstance(change, dict) or set(change) - allowed
                or sum(key in change for key in targets) != 1):
            raise ValueError(f'Each edit names {named}, plus set_hue/set_saturation or hue_shift/saturation_shift, '
                             'optional lightness_scale and an optional colour mask'
                             + (' and fields.' if animated else '.'))
        value = lab_common.colour_change({k: v for k, v in change.items() if k in COLOUR_KEYS})
        mask = change.get('mask')
        if mask is not None:
            if not isinstance(mask, dict) or 'surrounding' in mask:
                raise ValueError('A colour mask here takes hue_min/max, sat_min/max and lum_min/max.')
            lab_common.select(np.zeros((1, 1, 4), np.uint8), mask)          # validates the bounds
        fields = change.get('fields', list(DEFAULT_FIELDS))
        if not isinstance(fields, list) or not fields or any(f not in FIELDS for f in fields):
            raise ValueError(f'fields lists some of {list(FIELDS)}.')
        out.append((resolve(change), value, mask, fields, change))
    return out


def material_ids(inventory, ids, example, pattern):
    """The objects named by material ids ('<label>:i', or '<label>' alone for all of a group's).
    `example` and `pattern` show the lab's own ids in the errors."""
    if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_IDS or any(not isinstance(i, str) for i in ids):
        raise ValueError(f'material_ids lists 1..{MAX_IDS} ids such as {example}.')
    objects, unknown = [], []
    for wanted in ids:
        found = [o for o in inventory.objects if o.id == wanted or (':' not in wanted and o.id.startswith(wanted + ':'))]
        if not found:
            unknown.append(wanted)
        objects += [o for o in found if o not in objects]
    if unknown:
        raise ValueError(f'Unknown material_ids {unknown}: use ids from colour_sources or materials ({pattern}).')
    return objects


# --------------------------------------------------------------------------- #
# colour maths                                                                 #
# --------------------------------------------------------------------------- #
def selected(rgb, mask):
    """Does a colour (0..1 floats) pass the colour mask (texture_material's rule)?"""
    pixel = np.clip(np.round(np.asarray(rgb, float) * 255), 0, 255).astype(np.uint8)
    return bool(lab_common.select(np.array([[[*pixel, 255]]], np.uint8), mask).any())


def _hsl_rgb(h, s, l):
    """palette.hsl_to_rgb without the rounding to 8 bits -> 0..1 floats."""
    h, s, l = (h % 360.0) / 360.0, np.clip(s, 0, 100) / 100.0, np.clip(l, 0, 100) / 100.0
    q = np.where(l < 0.5, l * (1 + s), l + s - l * s)
    p = 2 * l - q

    def hue(t):
        t = np.mod(t, 1.0)
        return np.select([t < 1 / 6, t < 1 / 2, t < 2 / 3], [p + (q - p) * 6 * t, q, p + (q - p) * (2 / 3 - t) * 6],
                         default=p)
    return np.stack([np.where(s == 0, l, hue(h + 1 / 3)), np.where(s == 0, l, hue(h)),
                     np.where(s == 0, l, hue(h - 1 / 3))], axis=-1)


def apply(rgb, value):
    """palette.apply_adjustments' maths for one colour (0..1 floats), unrounded: keys are finer than 8 bits."""
    hue, saturation, mode, scale = value
    h, s, l = palette.rgb_to_hsl(np.clip(np.asarray(rgb, float), 0, 1).reshape(1, 3) * 255.0)
    h = np.full(h.shape, float(hue) % 360.0) if mode in ('set', 'set_hue') else (h + hue) % 360.0
    s = (np.full(s.shape, float(np.clip(saturation, 0, 100))) if mode in ('set', 'set_saturation')
         else np.clip(s + saturation, 0, 100))
    new_l = np.clip(l * scale, 0, 100)
    if mode not in ('set', 'set_saturation'):
        room_old, room_new = 1 - np.abs(2 * l / 100 - 1), 1 - np.abs(2 * new_l / 100 - 1)
        ratio = np.divide(room_old, room_new, out=np.ones_like(room_old), where=room_new > 1e-6)
        s = np.clip(s * np.minimum(1.0, ratio), 0, 100)
    return _hsl_rgb(h, s, new_l)[0]


def adjust_bytes(raw, value, mask):
    """One stored RGBA colour through the texture path's change (alpha kept) -> new bytes, or None."""
    work = np.array([[[*raw[:3], 255]]], np.uint8)
    out = lab_common.adjust(work, value, mask)
    return None if out is None else bytes(int(v) for v in out[0, 0, :3]) + bytes(raw[3:4])


# --------------------------------------------------------------------------- #
# vertex colours                                                               #
# --------------------------------------------------------------------------- #
def recolor_vertex(inventory, plans):
    """Every plan's vertex colours changed in place on inventory.dat -> the result (no files)."""
    dat = inventory.dat
    changed, skipped, also = {}, [], set()
    for objects, value, mask, _, _ in plans:
        chosen = [o for o in objects if dc.uses_vertex(o)]
        skipped += [o.id for o in objects if not dc.uses_vertex(o) and o.id not in skipped]
        attrs = [a for o in chosen for a in o.vertex if a.positions]
        if not attrs:
            continue
        tied = dc.entangled(inventory, chosen, 'vertex')
        dc.private_vertex(dat, attrs)
        where = {}                       # offset -> [format, size, owners]: a buffer two chosen objects share changes once
        for obj in chosen:
            for attr in obj.vertex:
                for off in attr.offsets():
                    where.setdefault(off, [attr.fmt, attr.size, set()])[2].add(obj.id)
        offsets = list(where)
        rgba = np.array([dc.decode_colour(where[o][0], dat.raw(o, where[o][1])) for o in offsets],
                        np.uint8).reshape(1, -1, 4)
        work = rgba.copy()
        work[..., 3] = 255               # alpha is kept, and never decides what a mask selects
        out = lab_common.adjust(work, value, mask)
        if out is None:
            continue
        moved = False
        for i, off in enumerate(offsets):
            fmt, size, owners = where[off]
            new = dc.encode_colour(fmt, out[0, i], dat.raw(off, size))
            if new != dat.raw(off, size):
                dat.put(off, new)
                moved = True
                for owner in owners:
                    changed.setdefault(owner, set()).add(off)
        if moved:
            also.update(tied)
    changed = {owner: len(offsets) for owner, offsets in changed.items()}
    result = {'changed': changed, 'vertex_colours': sum(changed.values())}
    notes = []
    if skipped:
        result['not_vertex'] = skipped
        notes.append('not_vertex objects do not take vertex colours (their render flags pick the material or the '
                     'texture): see colour_sources for the edit that changes them.')
    _also(result, notes, also - set(changed))
    if not changed:
        notes.append(NOTHING_CHANGED)
    if notes:
        result['note'] = ' '.join(notes)
    return result


def _also(result, notes, ids):
    if ids:
        result['also_changed'] = sorted(ids, key=dc._id_order)
        notes.append('also_changed objects read the same stored colours as the ones named (one pointer the file '
                     'shares between them), so they changed too.')


# --------------------------------------------------------------------------- #
# animated colours                                                             #
# --------------------------------------------------------------------------- #
def _slope(keys, frame):
    low, high = max(frame - 0.5, 0.0), frame + 0.5
    return (dc.sample(keys, high) - dc.sample(keys, low)) / (high - low)


def _align(dat, channels):
    """Key R, G and B alike when their frames differ -> the channels re-keyed.

    A hue change moves colour between channels: red pulsing over constant green and
    blue (Pokemon Stadium's lamps: R keyed at 0/mid/end, G and B only at 0 and end) can
    only become a green pulse when G has keys where R has. The channel with the most keys
    is the template; every other channel is sampled at its frames, in its interpolation
    and formats, into a new key stream (dc.replace_track). Timing (frames and length) is
    unchanged.
    """
    frames = {c: [k['frame'] for k in t.keys] for c, t in channels.items()}
    if len({tuple(f) for f in frames.values()}) <= 1:
        return []
    template = max(channels.values(), key=lambda t: len(t.keys))
    aligned = []
    for c, track in channels.items():
        if track is template:
            continue
        keys = [{'op': k['op'], 'step': k['step'],
                 'value': dc.sample(track.keys, k['frame']) if k['value'] is not None else None,
                 'tan': _slope(track.keys, k['frame']) if k['tan'] is not None else None} for k in template.keys]
        dc.replace_track(dat, track, dc.encode_keys(keys, template.value_flag, template.tan_flag),
                         template.value_flag, template.tan_flag)
        aligned.append(c)
    return aligned


def _transform_set(channels, base, value, mask):
    """New keys for one field's R/G/B tracks in one animation -> [(track, key, value, tangent)]."""
    def colour_at(frame):
        return [dc.sample(channels[c].keys, frame) if c in channels else base[c] for c in range(3)]

    writes = []
    for c, track in channels.items():
        for key in track.keys:
            frame = float(key['frame'])
            here = colour_at(frame)
            if not selected(here, mask):
                continue
            new_value = float(np.clip(apply(here, value)[c], 0, 1)) if key['value'] is not None else None
            new_tan = None
            if key['tan'] is not None:
                # The tangent of the new curve: the change's derivative along the old one.
                low, high = max(frame - 0.5, 0.0), frame + 0.5
                new_tan = float((apply(colour_at(high), value)[c] - apply(colour_at(low), value)[c]) / (high - low))
            writes.append((track, key, new_value, new_tan))
    return writes


def track_set(dat, channels, base, value, mask):
    """Recolour one R/G/B track set in place -> (keys changed, re-keyed?)."""
    for track in channels.values():
        dc.private_track(dat, track)
    rekeyed = bool(_align(dat, channels))
    count = 0
    for track, key, new_value, new_tan in _transform_set(channels, base, value, mask):
        before = (key['value'], key['tan'])
        dc.write_key(dat, track, key, new_value, new_tan)
        count += (key['value'], key['tan']) != before
    return count, rekeyed


def sets(tracks, fields):
    out = {}
    for track in tracks:
        if track.channel[0] in fields:
            out.setdefault(track.set_key, {})[track.channel[1]] = track
    return out


def recolor_animated(inventory, plans):
    """Every plan's animated colours (keys, and the descriptor colour of an animated field) changed in
    place on inventory.dat -> the result (no files)."""
    dat = inventory.dat
    changed, without, aligned, partial, also = {}, [], [], [], set()
    for objects, value, mask, fields, _ in plans:
        done_materials = set()
        tied = dc.entangled(inventory, [o for o in objects if sets(o.tracks, fields)], 'animation', fields)
        moved = False
        for obj in objects:
            found = sets(obj.tracks, fields)
            if not found:
                if obj.id not in without:
                    without.append(obj.id)
                continue
            keys = 0
            for set_key, channels in found.items():
                field = set_key[-1]
                base = [1.0, 1.0, 1.0]
                if field in dc.MATERIAL_FIELDS and obj.material is not None:
                    base = [c / 255 for c in dat.raw(obj.material + dc.MATERIAL_FIELDS[field], 3)]
                if len(channels) < 3 and obj.id not in partial:
                    partial.append(obj.id)     # a channel without a track stays the descriptor's (no new FOBJ)
                count, rekeyed = track_set(dat, channels, base, value, mask)
                keys += count
                if rekeyed and obj.id not in aligned:
                    aligned.append(obj.id)
            # The descriptor colour of an animated field follows (the view without animation, and a channel
            # without a track of its own, show it).
            animated = {t.channel[0] for t in obj.tracks if t.channel[0] in fields}
            if obj.material is not None and animated & set(dc.MATERIAL_FIELDS):
                dc.private_material(dat, obj)
                if obj.material not in done_materials:
                    done_materials.add(obj.material)
                    for field in sorted(animated & set(dc.MATERIAL_FIELDS)):
                        at = obj.material + dc.MATERIAL_FIELDS[field]
                        new = adjust_bytes(dat.raw(at, 4), value, mask)
                        if new is not None:
                            dat.put(at, new)
            if keys:
                changed[obj.id] = changed.get(obj.id, 0) + keys
                moved = True
        if moved:
            also.update(tied)
    result = {'changed': changed, 'keys': sum(changed.values())}
    notes = []
    if aligned:
        result['rekeyed'] = aligned
        notes.append('rekeyed: their R, G and B keys had different frames, so every channel now uses the frames of '
                     'the most detailed one (same timing).')
    if partial:
        result['partial'] = partial
        notes.append('partial: a colour channel there has no animation track, so it keeps one value all along.')
    if without:
        result['not_animated'] = without
        notes.append('not_animated objects have no colour animation for the named fields: their colour is in '
                     'another store (colour_sources).')
    _also(result, notes, also - set(changed))
    if not changed:
        notes.append(NOTHING_CHANGED)
    if notes:
        result['note'] = ' '.join(notes)
    return result


# --------------------------------------------------------------------------- #
# reset                                                                        #
# --------------------------------------------------------------------------- #
def restore_tracks(dat, source, tracks, originals):
    """Key values and tangents back to the opened file's (`originals`, matched by key) -> keys restored."""
    originals = {t.key: t for t in originals}
    count = 0
    for track in tracks:
        old = originals.get(track.key)
        if old is None:
            continue
        if ((old.value_flag, old.tan_flag) != (track.value_flag, track.tan_flag)
                or [(k['op'], k['frame']) for k in old.keys] != [(k['op'], k['frame']) for k in track.keys]):
            # Re-keyed by an edit (_align): the opened stream comes back whole.
            dc.replace_track(dat, track, source.raw(old.buffer, old.length), old.value_flag, old.tan_flag)
            count += len(old.keys)
            continue
        todo = []
        for key, was in zip(track.keys, old.keys):
            for slot, flag in (('value_at', track.value_flag), ('tan_at', track.tan_flag)):
                if slot in key:
                    size = len(dc.encode_number(0.0, flag))
                    then = source.raw(old.buffer + was[slot], size)
                    if dat.raw(track.buffer + key[slot], size) != then:
                        todo.append((key[slot], then))
        if todo:
            dc.private_track(dat, track)
            for at, then in todo:
                dat.put(track.buffer + at, then)
            count += len(todo)
    return count


def restore(inventory, source, objects):
    """Vertex colours, animation keys and animated fields' descriptor colours of `objects` back to `source`
    (the file as opened, scanned), matched by object id and structural key -> (restored {id: n}, unmatched)."""
    dat = inventory.dat
    restored, unmatched = {}, []
    for obj in objects:
        original = source.object(obj.id)
        if original is None:
            unmatched.append(obj.id)
            continue
        count = 0
        pairs = list(zip(obj.vertex, original.vertex))
        if len(obj.vertex) != len(original.vertex) or any(
                a.key != b.key or a.fmt != b.fmt or len(a.positions) != len(b.positions) for a, b in pairs):
            unmatched.append(obj.id)
            pairs = []
        differing = [a for a, b in pairs if any(dat.raw(x, a.size) != source.dat.raw(y, b.size)
                                                for x, y in zip(a.offsets(), b.offsets()))]
        if differing:
            dc.private_vertex(dat, differing)
            for a, b in pairs:
                for x, y in zip(a.offsets(), b.offsets()):
                    if dat.raw(x, a.size) != source.dat.raw(y, b.size):
                        dat.put(x, source.dat.raw(y, b.size))
                        count += 1
        count += restore_tracks(dat, source.dat, obj.tracks, original.tracks)
        animated = {t.channel[0] for t in obj.tracks} & set(dc.MATERIAL_FIELDS)
        if animated and obj.material is not None and original.material is not None:
            for field in animated:
                at, was = obj.material + dc.MATERIAL_FIELDS[field], original.material + dc.MATERIAL_FIELDS[field]
                if dat.raw(at, 4) != source.dat.raw(was, 4):
                    dc.private_material(dat, obj)
                    dat.put(obj.material + dc.MATERIAL_FIELDS[field], source.dat.raw(was, 4))
                    count += 1
        if count:
            restored[obj.id] = count
    return restored, unmatched


# --------------------------------------------------------------------------- #
# the renderer                                                                 #
# --------------------------------------------------------------------------- #
def frame(item, name):
    return [lab_common.image_file(item['viewer'].grab_frame(), name)]


def _in_place(item, data, previous):
    """The edit's colours put into the running renderer (protocol 2) -> True, or False when it cannot.

    `previous` is the export the edit was made on (bytes or a scan). The messages are
    what changed between it and `data` (dat_colours.colour_messages); a failure part way
    leaves the renderer half edited, which the reload that follows replaces anyway.
    """
    viewer = item['viewer']
    if previous is None or not lab_common.supports(viewer, 'setVertexColors'):
        return False
    try:
        before = previous if isinstance(previous, dc.Inventory) else dc.scan(previous)
        messages = dc.colour_messages(before, dc.scan(data))
        if not messages or not all(lab_common.supports(viewer, message['type']) for message in messages):
            return False
        viewer.apply_colour_messages(messages)
    except Exception as exc:
        log.warning('In-place colour update failed, reloading the renderer instead: %s', exc)
        return False
    item['viewer_colours'] = messages            # what the workbench view replays (continuity)
    return True


def _swap_in(viewer, path):
    """`path` loaded into the running renderer (loadDat, camera and companions kept) -> True, or False."""
    if not lab_common.supports(viewer, 'loadDat'):
        return False
    try:
        viewer.reopen(path)
        return True
    except Exception as exc:
        log.warning('loadDat failed, restarting the renderer instead: %s', exc)
        return False


def reload(item, data, name, start, directory, previous=None):
    """Show `data` (the edited DAT) in the session's renderer -> [preview file].

    In order, each falling back to the next: its colours put in place (protocol 2:
    setVertexColors / setAnimationColors / setLightColors, about 0.1 s); the file loaded
    into the running renderer (loadDat); a fresh renderer that replaces the session's
    (the only way with an older viewer, about 5 s). `previous` is the export the edit was
    made on (bytes or a scan; without it only the last two). `start(path)` opens the
    lab's renderer on a file; `directory` is the session's own working folder (a file
    is written there, and the previous one removed). Either way the camera is kept and
    the texture list must come back the same, or the edit is not applied.
    """
    viewer = item['viewer']
    lab_common.material_baseline(item)       # the true material values, before a reload forgets them
    item.pop('viewer_colours', None)
    if _in_place(item, data, previous):
        # Nothing reloaded; resets go to the session's baseline as after a reload, so the two agree.
        item['resumed'] = True
        item['colour_scan'] = None
        item['colour_data'] = (viewer, data)
        return [lab_common.image_file(viewer.grab_frame(), name)]
    path = directory / f'colours-{uuid.uuid4().hex[:12]}.dat'
    path.write_bytes(data)
    expected = lab_common.texture_list(viewer)
    if _swap_in(viewer, path):
        if lab_common.same_textures(viewer, expected):
            candidate, shot = viewer, viewer.grab_frame()
        else:
            # Back to the file before the edit, which the renderer showed.
            try:
                if previous is None:
                    raise ValueError('no previous file')
                back = directory / f'colours-{uuid.uuid4().hex[:12]}.dat'
                back.write_bytes(previous.dat.data() if isinstance(previous, dc.Inventory) else previous)
                viewer.reopen(back)
            except Exception:
                viewer.close()               # the session reopens from its checkpoint on its next call
            path.unlink(missing_ok=True)
            raise ValueError('The edited copy reloaded with a different texture list, so the edit was not applied.')
    else:
        candidate = None
        try:
            candidate = start(path)
            if not lab_common.same_textures(candidate, expected):
                raise ValueError('The edited copy reloaded with a different texture list, so the edit was not applied.')
            camera = viewer.camera
            candidate.set_camera(rot_x=camera['rotX'], rot_y=camera['rotY'], scale=camera['scale'], x=camera['x'],
                                 y=camera['y'])
            shot = candidate.grab_frame()
        except Exception:
            if candidate:
                candidate.close()
            path.unlink(missing_ok=True)
            raise
    item['viewer'] = candidate
    # The renderer's own "original" material values are this file's now: lab_common.material resets
    # to the session's baseline instead, as after a resume. A loaded file plays from frame 0, so a pose
    # the Stage Lab set (`animation`) is not set again by a later look (texture_inspection._take_back).
    item['resumed'] = True
    item.pop('animation', None)
    item['colour_scan'] = None
    item['colour_data'] = (candidate, data)      # the evidence, when asked again, reads these bytes
    if candidate is not viewer:
        viewer.close()
    for old in directory.glob('colours-*.dat'):
        if old != path:
            old.unlink(missing_ok=True)
    return [lab_common.image_file(shot, name)]
