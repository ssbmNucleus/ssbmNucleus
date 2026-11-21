"""What the Skin Lab and the Stage Lab share.

Both labs keep private HSDRawViewer sessions (`skin_lab._sessions`,
`stage_lab._sessions`) whose textures are read and written in the renderer's
own index space. The texture tools that do not care which kind of file is open
-- `skin_material` (generated materials through a mask), the texture sheet,
usage and highlight (`texture_inspection`), and the per-texture colour edit
below -- reach a session through `session()` and work on either.

Stage specifics live here too, because the shared tools have to respect them:

* **Greyscale slots.** Many stage textures are intensity formats (I4/I8/IA4/
  IA8, or a palette with an IA8 table): the game stores only lightness there
  and the colour comes from the material. The renderer shows a colour written
  into one, but the saved DAT keeps the slot's format, so the colour is gone on
  save (measured on Pokemon Stadium: a red gradient written into texture 9 came
  back grey from the exported file). A texture that reads back with R=G=B
  everywhere is treated as such a slot; colour writes into it are refused and
  the model is pointed at the material colour instead. The rule is
  conservative: a colour texture that happens to be pure grey is treated the
  same, which only costs the model the material route.
* **No growth.** A stage texture is never enlarged (a stage file has a memory
  budget); generated detail is drawn at the slot's own size.

**Resume.** A session closes after 15 idle minutes (or when the model closes it,
or the backend restarts), and its renderer goes with it. Each session keeps a
workspace on disk (a stage's is its Stage Lab workspace, a costume's
`<storage>/assistant/skin_lab/<session id>/`) with a resume record: the last
checkpoint chat file plus what a checkpoint cannot hold (the originals a reset
returns to, the palette analysis, the material values
before the first material edit). A call naming a session that is gone reopens it
from there (`live`), under the same session id, and carries on; the model is not
told, because nothing it does changes. A record whose checkpoint reopens with a
different texture list is not resumed (the model's texture indices would be
wrong): that call gets the old "expired or closed" error.
"""
import io
import json
import math
import os
import re
import time
import uuid

import numpy as np
from PIL import Image

from shared.rendering import compose, palette

GREYSCALE_NOTE = ('greyscale textures store only lightness: the game takes their colour from the material, '
                  'and the saved file keeps their format, so a colour written into one is lost on save. '
                  'Change their colour with set_material, their lightness with recolor lightness_scale.')

IDLE_SECONDS = 900       # a session closes after 15 idle minutes (both labs)
MAX_SESSIONS = 2         # live sessions per lab


def png(pixels):
    output = io.BytesIO()
    Image.fromarray(pixels).save(output, format='PNG')
    return output.getvalue()


def pixels(raw):
    with Image.open(io.BytesIO(raw)) as image:
        return np.array(image.convert('RGBA'))


def _as_png(data):
    with Image.open(io.BytesIO(data)) as image:
        if image.width * image.height > 16000000:
            raise ValueError('Image exceeds 16 megapixels')
        result = io.BytesIO()
        image.convert('RGBA').save(result, format='PNG')
        return result.getvalue()


def image_file(data, name):
    """A rendered frame or texture (any image the renderer returns) as a PNG chat file."""
    from shared import mod_files
    return mod_files.register(_as_png(data), name)


def session(session_id, missing='Skin Lab session expired or closed; open the source again.'):
    """(kind, item, lock) for a Skin Lab ('costume') or Stage Lab ('stage') session.

    A session that has closed is reopened from its workspace (`live`). The caller
    holds `lock` while it uses the item, as each lab does for its own.
    """
    from . import skin_lab, stage_lab
    if isinstance(session_id, str):
        for kind, module in (('costume', skin_lab), ('stage', stage_lab)):
            with module._lock:
                if session_id in module._sessions or resumable(module._workspace(session_id)):
                    return kind, live(module, session_id), module._lock
    raise ValueError(missing)


# --------------------------------------------------------------------------- #
# resume: a closed session reopened from its workspace (module doc)           #
# --------------------------------------------------------------------------- #
RECORD = 'resume.json'
_ID = re.compile(r'[a-f0-9]{32}')


def workspace_id(session_id):
    """True for an id a workspace can be named after (a session's own uuid hex)."""
    return isinstance(session_id, str) and bool(_ID.fullmatch(session_id))


def keep(directory, record):
    """Write the workspace's resume record (atomically: a crash leaves the previous one)."""
    if directory is None:
        return
    directory.mkdir(parents=True, exist_ok=True)
    partial = directory / (RECORD + '.part')
    partial.write_text(json.dumps(record, default=_plain), encoding='utf-8')
    os.replace(partial, directory / RECORD)


def _plain(value):
    """numpy scalars and arrays (palette groups carry them) as the JSON values they are."""
    if isinstance(value, (np.generic, np.ndarray)):
        return value.tolist()
    if isinstance(value, (set, tuple)):
        return list(value)
    raise TypeError(f'{type(value).__name__} is not kept in a resume record')


def resumable(directory):
    """True when the workspace holds a resume record (cheaper than reading it)."""
    return directory is not None and (directory / RECORD).is_file()


def kept(directory):
    """The workspace's resume record, or None."""
    try:
        return json.loads((directory / RECORD).read_text(encoding='utf-8')) if directory else None
    except (OSError, ValueError):
        return None


def keep_textures(directory, raws, token):
    """The originals a reset returns to, as the renderer returned them: `originals-<token>/<index>.png`."""
    target = directory / f'originals-{token}'
    if (target / 'done').exists():
        return
    target.mkdir(parents=True, exist_ok=True)
    for index, raw in raws.items():
        (target / f'{int(index)}.png').write_bytes(raw)
    (target / 'done').write_text('')
    _drop_others(directory, 'originals-', target.name)


def kept_textures(directory, token):
    target = directory / f'originals-{token}'
    if not (target / 'done').exists():
        raise ValueError('missing originals')
    return {int(path.stem): path.read_bytes() for path in target.glob('*.png')}


def keep_arrays(directory, token, arrays):
    """Named numpy arrays (a palette analysis) as `palette-<token>.npz`, written once per token."""
    target = directory / f'palette-{token}.npz'
    if target.exists():
        return
    partial = directory / f'palette-{token}.part.npz'
    np.savez(partial, **{name: np.asarray(value) for name, value in arrays.items()})
    os.replace(partial, target)
    _drop_others(directory, 'palette-', target.name)


def kept_arrays(directory, token):
    with np.load(directory / f'palette-{token}.npz', allow_pickle=False) as data:
        return {name: data[name] for name in data.files}


def _drop_others(directory, prefix, current):
    import shutil
    for entry in directory.iterdir():
        if entry.name.startswith(prefix) and entry.name != current:
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)


def supports(viewer, message):
    """True when the session's renderer announced protocol 2 and takes `message` (session.supports)."""
    check = getattr(viewer, 'supports', None)
    return callable(check) and check(message) is True


def write_textures(viewer, updated):
    """{index: PNG bytes} into the renderer, in order: one batch when it takes updateTextures, else one
    texture at a time (session.update_textures)."""
    if not updated:
        return
    if callable(getattr(viewer, 'update_textures', None)):
        viewer.update_textures(updated)
    else:
        for index, data in updated.items():
            viewer.update_texture(index, data)


def texture_list(viewer):
    """The renderer's texture list as a resume record keeps it (and compares it)."""
    return [{key: texture.get(key) for key in ('index', 'name', 'width', 'height', 'matAnim', 'animates', 'extra')}
            for texture in viewer.textures]


def same_textures(viewer, recorded):
    return texture_list(viewer) == recorded


def token():
    return uuid.uuid4().hex


def _alive(viewer):
    alive = getattr(viewer, 'alive', None)
    return alive() if callable(alive) else True


def make_room(module):
    """A free slot in `module`'s lab (skin_lab or stage_lab; the caller holds `module._lock`). Idle sessions and
    ones whose renderer died close first; when every slot is still in use, the one used longest ago closes too.
    It is not lost: like a session that idled out, its next call reopens it from its workspace (`live`), and one
    that never kept a record says to open it again. A lab that refused instead left an AI whose earlier run kept
    sessions open (their ids gone with that run) unable ever to open one again (0.9.0 MCP filming, 11-20)."""
    for key, other in list(module._sessions.items()):
        if time.monotonic() - other['used'] >= IDLE_SECONDS or not _alive(other['viewer']):
            module._close(key)
    while len(module._sessions) >= MAX_SESSIONS:
        module._close(min(module._sessions, key=lambda key: module._sessions[key]['used']))


def live(module, session_id):
    """THE session lookup of either lab: its live item, or the session reopened from its workspace.

    `module` is skin_lab or stage_lab; the caller holds `module._lock`. A session
    whose renderer died is closed first. Reopening takes a free slot (`make_room`)
    and goes through the lab's own `_resume(session_id, directory,
    record)`, which raises ValueError when the record cannot be used.
    """
    item = module._sessions.get(session_id)
    if item is not None and _alive(item['viewer']):
        return item
    if item is not None:
        module._close(session_id)
    directory = module._workspace(session_id)
    record = kept(directory)
    if not record:
        raise ValueError(module.MISSING)
    make_room(module)
    item = module._resume(session_id, directory, record)
    item['used'] = time.monotonic()
    item['resumed'] = True
    module._sessions[session_id] = item
    module._expire(session_id)
    return item


# --------------------------------------------------------------------------- #
# material edits: the values a reset returns to survive a resume              #
# --------------------------------------------------------------------------- #
def material_baseline(item):
    """Every material field's value before the session's first material edit, read once.

    The renderer keeps each field's pre-edit value itself (reset_material), but a
    resumed renderer starts from the checkpoint, so its "original" is the edited
    value. This is the true one, kept with the workspace.
    """
    if item.get('material_baseline') is None:
        listed = item['viewer'].material_command({'type': 'getMaterials'}).get('materials') or []
        item['material_baseline'] = {f"{material['id']}\n{field['key']}": field['value']
                                     for material in listed for field in material.get('fields', [])
                                     if 'key' in field and 'value' in field}
    return item['material_baseline']


def material(item, action, material_id=None, field=None, value=None, enabled=None):
    """materials.material_action for a lab session: on a resumed one, reset_material sets the true original."""
    from .materials import material_action
    if action in ('set_material', 'reset_material'):
        baseline = material_baseline(item)
        original = baseline.get(f'{material_id}\n{field}')
        if action == 'reset_material' and item.get('resumed') and original is not None:
            return material_action(item['viewer'], 'set_material', material_id, field, original, enabled)
    return material_action(item['viewer'], action, material_id, field, value, enabled)


def uv_layout(item):
    """The session's UV layout (getUVLayout, 0.3-0.7 s a call), fetched once.

    It maps texture space to geometry in the session's pose: a texture edit or a
    resize does not change it. The Stage Lab drops it when the pose changes
    (`animation`) or the geometry does (scenery).
    """
    if not item.get('uv_layout'):            # an empty answer (no geometry) is asked again, as before
        item['uv_layout'] = item['viewer'].get_uv_layout()
    return item['uv_layout']


def is_stage(session_id):
    """True for a Stage Lab session, live or resumable."""
    from . import stage_lab
    with stage_lab._lock:
        return isinstance(session_id, str) and (session_id in stage_lab._sessions
                                                or resumable(stage_lab._workspace(session_id)))


def greyscale(rgba):
    """True when every pixel has R=G=B: an intensity slot, as far as the renderer shows."""
    return bool(np.array_equal(rgba[..., 0], rgba[..., 1]) and np.array_equal(rgba[..., 1], rgba[..., 2]))


def refuse_greyscale(item, indices, what='a colour'):
    """Refuse writing colour into greyscale stage slots (module doc). Costume sessions never refuse."""
    grey = sorted(set(indices) & set(item.get('greyscale') or ()))
    if grey:
        raise ValueError(f'Textures {grey} are greyscale slots, so {what} written into them is lost when the stage '
                         f'is saved: {GREYSCALE_NOTE} Leave them out of this edit.')


def _number(value, label, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{label} must be a number in {low}..{high}.')
    return value


CHANGE_FIELDS = {'texture_index', 'hue_shift', 'saturation_shift', 'set_hue', 'set_saturation',
                 'lightness_scale', 'mask'}


def colour_change(change):
    """A validated per-texture change -> palette.apply_adjustments value (hue, sat, mode, scale), mode
    'set' | 'shift' | 'set_hue' | 'set_saturation'.

    `set_hue`/`set_saturation` colourize outright (the only way to colour white or
    grey); shifts rotate what is there; `lightness_scale` multiplies lightness
    (below 1 darker) and keeps relative shading. Hue is a circle, so a 242 degree
    shift is read as -118, as the Skin Lab does. An exact value of one with a shift
    of the other is one change too: `set_hue` with `saturation_shift` makes every
    pixel that hue and moves the saturation it has ("purple, a bit less vivid"; every
    MCP test run of 2026-11-18 asked that once and was refused), `hue_shift` with
    `set_saturation` the reverse. The same field both set and shifted is refused.
    """
    shift = change.get('hue_shift')
    if type(shift) in (int, float) and math.isfinite(shift):
        shift = (shift + 180) % 360 - 180
    for field in ('hue', 'saturation'):
        if f'set_{field}' in change and f'{field}_shift' in change:
            raise ValueError(f'Use either {field}_shift or set_{field} in one change, not both.')
    scale = _number(change.get('lightness_scale', 1), 'lightness_scale', 0, 2)
    set_hue, set_saturation = 'set_hue' in change, 'set_saturation' in change
    if set_hue and 'saturation_shift' in change:
        return (_number(change['set_hue'], 'set_hue', 0, 360),
                _number(change['saturation_shift'], 'saturation_shift', -100, 100), 'set_hue', scale)
    if set_saturation and 'hue_shift' in change:
        return (_number(shift, 'hue_shift', -180, 180),
                _number(change['set_saturation'], 'set_saturation', 0, 100), 'set_saturation', scale)
    if set_hue or set_saturation:
        return (_number(change.get('set_hue', 0), 'set_hue', 0, 360),
                _number(change.get('set_saturation', 60), 'set_saturation', 0, 100), 'set', scale)
    return (_number(shift if shift is not None else 0, 'hue_shift', -180, 180),
            _number(change.get('saturation_shift', 0), 'saturation_shift', -100, 100), 'shift', scale)


def adds_colour(value):
    """True when a change would put colour where there is none (refused on greyscale slots)."""
    return value[1] > 0


def select(rgba, mask):
    """The pixels a colour mask selects (texture_material's own rule); opaque pixels without bounds."""
    from .texture_material import _select, _validate_mask
    mask = mask or {}
    _validate_mask(mask)
    return _select(rgba, mask)


def adjust(rgba, value, mask=None):
    """One texture's colour edit from its CURRENT pixels. -> new array, or None when nothing changes."""
    selected = select(rgba, mask)
    if not selected.any():
        return None
    pixel_map = np.where(selected.ravel(), 0, 255).astype(np.uint8)
    out = palette.apply_adjustments(rgba, pixel_map, {0: value})
    if out is None or np.array_equal(out, rgba):
        return None
    return out


def shift(rgba, hue, saturation):
    """The Stage Lab's original whole-texture rotation (compose.hue_shift), or None when nothing changes."""
    out = compose.hue_shift(rgba, compose.build_mask(rgba), hue, saturation)
    if out is None or np.array_equal(out, rgba):
        return None
    return out


# --------------------------------------------------------------------------- #
# reset_texture originals of a costume session                                 #
# --------------------------------------------------------------------------- #
def keep_originals(item, indices):
    """A costume's textures as they were before their first direct write (a material, an apply batch),
    for skin_lab reset_texture. A stage session has the originals of its open already
    (stage_lab._inventory). Kept with the workspace by skin_lab.keep, under a new token when they grow."""
    if item.get('kind') == 'stage':
        return
    kept = item.setdefault('texture_originals', {})
    fresh = [i for i in indices if i not in kept]
    for index in fresh:
        kept[index] = item['viewer'].get_full_texture(index)
    if fresh:
        item['texture_originals_token'] = token()


def originals_of(item):
    """{index: PNG bytes} a reset_texture returns to: a stage's as opened, a costume's before its first write."""
    return item.get('original_textures') if item.get('kind') == 'stage' else item.get('texture_originals') or {}


# --------------------------------------------------------------------------- #
# apply: one batch of mixed edits, one render, one checkpoint                  #
# --------------------------------------------------------------------------- #
# Each edit names its kind: one of the single actions it stands for (or a short alias) and that
# action's own fields. Texture pixels, material colours and the colours stored in the file
# (vertex colours, colour keys, lights) are separate stores, so the batch changes each in the
# order its edits are given: every texture edit on the pixels as they are at that point (one
# upload), then the material colours (one listing, one setMaterialColors), then the file's
# colours on one export (one reload, in place on a protocol-2 renderer). An edit that fails is
# reported with its reason and the rest still apply; a batch where none applies is an error.
MAX_BATCH = 64
BATCH_KINDS = ('recolor', 'recolor_vertex', 'recolor_animated', 'recolor_lights', 'set_material', 'material',
               'reset_texture')
KIND_ALIASES = {'texture': 'recolor', 'texture_recolor': 'recolor', 'vertex': 'recolor_vertex',
                'vertex_colours': 'recolor_vertex', 'vertex_colors': 'recolor_vertex',
                'animated': 'recolor_animated', 'animation': 'recolor_animated', 'lights': 'recolor_lights',
                'light': 'recolor_lights', 'material_colour': 'set_material', 'material_color': 'set_material',
                'generated_material': 'material', 'swatch': 'material', 'reset': 'reset_texture'}
FILE_KINDS = ('recolor_vertex', 'recolor_animated', 'recolor_lights')
STORE = 'colour_store'       # an object colour edit without a kind: recolor_vertex or recolor_animated by its objects
COLOUR_FIELDS = {'hue_shift', 'saturation_shift', 'set_hue', 'set_saturation', 'lightness_scale'}
SWATCH_KEYS = ('material_file_id', 'swatch', 'swatch_id', 'file_id')
NOTHING = 'changed nothing: the mask matched no pixels, or the values are what is there already.'


def batch_kind(edit, stage):
    """An edit's kind (`kind`, an alias, or what its fields say when it has none) -> one of BATCH_KINDS."""
    kind = edit.get('kind')
    if kind is None:
        if any(key in edit for key in SWATCH_KEYS):
            kind = 'material'
        elif 'field' in edit and 'value' in edit:
            kind = 'set_material'
        elif 'lights' in edit:
            kind = 'recolor_lights'
        elif 'fields' in edit:
            kind = 'recolor_animated'
        elif 'texture_index' in edit and set(edit) & COLOUR_FIELDS and not {'material_ids', 'part'} & set(edit):
            kind = 'recolor'
        elif {'material_ids', 'part'} & set(edit) and set(edit) & COLOUR_FIELDS:
            return STORE            # vertex colours or colour keys: the objects' own store says (apply_batch)
        else:
            raise ValueError('say its kind: one of ' + ', '.join(_kinds(stage)) + '.')
    kind = KIND_ALIASES.get(kind, kind) if isinstance(kind, str) else kind
    if kind not in _kinds(stage):
        raise ValueError(f'unknown kind {edit.get("kind")!r}: use one of ' + ', '.join(_kinds(stage)) + '.')
    return kind


def single_kind(action, edits):
    """A single action's edits may carry `kind` (the batch's item schema has it): their own kind is dropped,
    another one is refused with the way to send it."""
    if not isinstance(edits, list) or not any(isinstance(e, dict) and 'kind' in e for e in edits):
        return edits
    out = []
    for edit in edits:
        if isinstance(edit, dict) and 'kind' in edit:
            kind = KIND_ALIASES.get(edit['kind'], edit['kind']) if isinstance(edit['kind'], str) else edit['kind']
            if kind != action:
                raise ValueError(f'An edit of kind {edit["kind"]!r} in {action}: send edits of several kinds with '
                                 'action=apply.')
            edit = {k: v for k, v in edit.items() if k != 'kind'}
        out.append(edit)
    return out


def _kinds(stage):
    return BATCH_KINDS if stage else tuple(k for k in BATCH_KINDS if k != 'recolor_lights')


def _only(edit, allowed, kind):
    extra = sorted(set(edit) - set(allowed) - {'kind'})
    if extra:
        raise ValueError(f'{kind} takes ' + ', '.join(sorted(allowed)) + f'; not {", ".join(extra)}.')


def _live_index(viewer, index, label='texture_index'):
    if type(index) is not int or not any(t['index'] == index for t in viewer.textures):
        raise ValueError(f'{label} {index!r} is not a live texture index (from the open, identify or inspect).')
    return index


def _texture_list(viewer, edit, most=32):
    indices = edit.get('texture_indices', [edit['texture_index']] if 'texture_index' in edit else None)
    if not isinstance(indices, list) or not 1 <= len(indices) <= most or len(set(map(str, indices))) != len(indices):
        raise ValueError(f'name texture_indices (1..{most} unique live indices) or one texture_index.')
    return [_live_index(viewer, i, 'texture_indices entry') for i in indices]


def _swatch(edit, cache):
    from . import texture_material
    found = [edit[key] for key in SWATCH_KEYS if key in edit]
    if len(found) != 1 or not isinstance(found[0], str):
        raise ValueError('a material edit names one swatch: material_file_id from generate_material or the '
                         'saved swatches.')
    if found[0] not in cache:
        cache[found[0]] = texture_material._file_pixels(found[0])
    return found[0], cache[found[0]]


def _refuse_texture_edit(item, indices, what, stage):
    if stage:
        refuse_greyscale(item, indices, what)
    else:
        from .skin_lab import refuse_hidden_only
        refuse_hidden_only(item, indices)


def _material_colours(item, edits):
    """The batch's set_material edits, checked against one listing -> ({position: reason}, applied
    [(position, [{id, field, value}])]). Colours go in one setMaterialColors; opacity and shininess one
    setMaterial each (materials.material_action, the single action's own command)."""
    from .materials import material_action, rgba_hex, COLOUR_SHAPE
    viewer = item['viewer']
    listed = {m['id']: {f['key']: f for f in m.get('fields', []) if 'key' in f}
              for m in viewer.material_command({'type': 'getMaterials'}).get('materials') or []}
    failed, colours, numbers, done = {}, [], [], []
    for position, edit in edits:
        try:
            _only(edit, ('material_id', 'material_ids', 'field', 'value'), 'set_material')
            ids = edit.get('material_ids', [edit.get('material_id')])
            if 'material_id' in edit and 'material_ids' in edit:
                raise ValueError('name material_id or material_ids, not both.')
            if not isinstance(ids, list) or not ids or any(i not in listed for i in ids):
                raise ValueError('material_id(s) must come from materials (each row\'s ids).')
            field, value = edit.get('field'), edit.get('value')
            rows = []
            for material_id in ids:
                target = listed[material_id].get(field)
                if target is None:
                    raise ValueError(f'{material_id} has no field {field!r} (see materials).')
                own = value
                if target.get('kind') == 'color':
                    own = rgba_hex(value, target.get('value'))      # each material keeps its own alpha
                    if own is None:
                        raise ValueError(f'a colour value is {COLOUR_SHAPE}.')
                elif type(value) not in (int, float) or not math.isfinite(value) or not \
                        0 <= value <= (1 if field == 'alpha' else 128):
                    raise ValueError('opacity takes 0..1 and shininess 0..128.')
                rows.append({'id': material_id, 'field': field, 'value': own, 'colour': target.get('kind') == 'color'})
            done.append((position, rows))
        except ValueError as exc:
            failed[position] = str(exc)
    if done:
        material_baseline(item)           # the values a reset_material returns to, before the first edit
        colours = [{k: r[k] for k in ('id', 'field', 'value')} for _, rows in done for r in rows if r['colour']]
        numbers = [r for _, rows in done for r in rows if not r['colour']]
        if colours:
            viewer.material_command({'type': 'setMaterialColors', 'edits': colours})
        for row in numbers:
            material_action(viewer, 'set_material', row['id'], row['field'], row['value'])
    return failed, done


def _vertex_tinted(item, inv, lab, context, indices, named):
    """Objects drawing these textures whose vertex colours carry a hue (the renderer multiplies the texture
    by them), minus those another edit of the batch names."""
    from shared.rendering import dat_colours as dc
    found = []
    for index in indices:
        try:
            objects = lab.batch_targets(item, inv, {'texture_index': index}, context)
        except ValueError:
            continue
        for obj in objects:
            if obj.id in named or obj in found or not dc.uses_vertex(obj):
                continue
            try:
                parts = dc.colour_from(obj, inv.dat)[1]
            except Exception:
                continue
            if 'vertex' in parts:
                found.append(obj)
    return found


def apply_batch(item, edits, stage):
    """The labs' `apply` action (module section above) -> the result, its render in `files`.

    `stage`: a Stage Lab session (else a Skin Lab one). Every edit goes through the single action's own
    code: lab_common.adjust (recolor), texture_material.compose_material (material), the session's
    originals (reset_texture), materials (set_material), and model_colours through the lab's colour
    module (recolor_vertex / recolor_animated / recolor_lights)."""
    from . import texture_material
    from .model_colours import recolor_vertex
    if not isinstance(edits, list) or not 1 <= len(edits) <= MAX_BATCH:
        raise ValueError(f'apply takes edits: a list of 1..{MAX_BATCH} changes, each {{kind, ...that kind\'s fields}}, '
                         'for example [{"kind": "recolor", "texture_index": 3, "set_hue": 270, "set_saturation": 60}].')
    viewer = item['viewer']
    if stage:
        from . import stage_colours as lab
    else:
        from . import costume_colours as lab
    failed, applied, notes = {}, {}, []
    working, before = {}, {}
    swatches, materials, file_edits, neutral = {}, [], [], []

    def current(index):
        if index not in working:
            before[index] = viewer.get_full_texture(index)
            working[index] = pixels(before[index])
        return working[index]

    for position, edit in enumerate(edits):
        try:
            if not isinstance(edit, dict):
                raise ValueError('an edit is an object: {kind, ...that kind\'s fields}.')
            kind = batch_kind(edit, stage)
            if kind == 'recolor':
                _only(edit, {'texture_index', 'mask'} | COLOUR_FIELDS, kind)
                index = _live_index(viewer, edit.get('texture_index'))
                value = colour_change(edit)
                if adds_colour(value) or not stage:         # a greyscale slot still takes lightness
                    _refuse_texture_edit(item, [index], 'a colour', stage)
                out = adjust(current(index), value, edit.get('mask'))
                if out is None:
                    raise ValueError(NOTHING)
                working[index] = out
                applied[position] = (kind, {'textures': [index]})
            elif kind == 'material':
                _only(edit, {'texture_index', 'texture_indices', 'keep_vertex_colours', *SWATCH_KEYS,
                             *texture_material.CONTROLS}, kind)
                indices = _texture_list(viewer, edit)
                _refuse_texture_edit(item, indices, 'a material', stage)
                keep = edit.get('keep_vertex_colours', False)
                if type(keep) is not bool:
                    raise ValueError('keep_vertex_colours is true or false.')
                swatch, material = _swatch(edit, swatches)
                controls = texture_material.default_controls(stage)
                controls.update({key: edit[key] for key in texture_material.CONTROLS if key in edit})
                composed = texture_material.compose_material(item, stage, {i: current(i) for i in indices},
                                                             material, controls)
                working.update(composed['candidate'])
                if not keep:
                    neutral.append((position, indices))
                applied[position] = (kind, {'textures': indices, 'material_file_id': swatch})
            elif kind == 'reset_texture':
                _only(edit, {'texture_index', 'texture_indices'}, kind)
                indices = _texture_list(viewer, edit, 512)
                kept = originals_of(item)
                missing = [i for i in indices if i not in kept]
                if missing:
                    raise ValueError(f'textures {missing} have not been changed in this session (nothing to reset to).')
                for index in indices:
                    current(index)
                    working[index] = pixels(kept[index])
                applied[position] = (kind, {'restored': indices})
            elif kind == 'set_material':
                materials.append((position, edit))
            else:
                file_edits.append((position, kind, edit))
        except ValueError as exc:
            failed[position] = str(exc)

    # 1. texture pixels: one upload of every texture that ends up different
    written = {index: png(px) for index, px in working.items() if not np.array_equal(px, pixels(before[index]))}
    if written:
        keep_originals(item, list(written))
        write_textures(viewer, written)
        if not stage:
            texture_material.forget_palette(item, written)
            item['edited'] = True
    # 2. material colours
    item['batch_materials'] = []
    if materials:
        bad, done = _material_colours(item, materials)
        failed.update(bad)
        for position, rows in done:
            applied[position] = ('set_material', {'materials': [r['id'] for r in rows]})
            item['batch_materials'] += [(r['id'], r['field']) for r in rows]
        if done and not stage:
            item['edited'] = True
    # 3. colours stored in the file, on one export
    result = {}
    files = None
    if file_edits or neutral:
        from shared.rendering import dat_colours as dc
        exported = viewer.export_dat()
        inv = dc.scan(exported)
        context = lab.batch_context(item, inv)
        named = set()
        for n, (position, kind, edit) in enumerate(file_edits):
            if kind not in ('recolor_vertex', STORE):
                continue
            try:
                objects = lab.batch_targets(item, inv, {k: v for k, v in edit.items() if k != 'kind'}, context)
            except Exception:
                continue                               # said by the edit itself below
            if kind == STORE:                          # no kind given: the store its objects colour through
                kind = ('recolor_vertex' if any(dc.uses_vertex(o) for o in objects) else
                        'recolor_animated' if any(o.tracks for o in objects) else STORE)
                file_edits[n] = (position, kind, edit)
            if kind == 'recolor_vertex':               # what the batch's own vertex edits name: never neutralised
                named |= {o.id for o in objects}
        changed, also, parts = {}, set(), []
        tinted = []
        for position, indices in neutral:
            objects = _vertex_tinted(item, inv, lab, context, indices, named)
            if objects:
                done = recolor_vertex(inv, [(objects, (0.0, 0.0, 'set', 1.0), None, [], {})])
                for key, count in done['changed'].items():
                    changed[key] = changed.get(key, 0) + count
                    if key not in tinted:
                        tinted.append(key)
                named |= {o.id for o in objects}
        for position, kind, edit in file_edits:
            try:
                if kind == STORE:
                    raise ValueError('say its kind: these objects take neither vertex colours nor colour keys '
                                     '(colour_sources; a material colour is set_material).')
                one = lab.batch_edit(item, inv, kind, {k: v for k, v in edit.items() if k != 'kind'}, context)
            except ValueError as exc:
                failed[position] = str(exc)
                continue
            if not one.get('changed'):
                failed[position] = 'changed nothing: ' + (one.get('note') or NOTHING)
                continue
            for key, count in one['changed'].items():
                changed[key] = changed.get(key, 0) + count
            also.update(one.get('also_changed') or ())
            parts += [line for line in one.get('also_changed_parts') or () if line not in parts]
            applied[position] = (kind, {'objects': list(one['changed'])})
            extra = {k: one[k] for k in ('not_vertex', 'not_animated', 'rekeyed', 'partial') if one.get(k)}
            if extra:
                notes.append({'index': position, **extra})
        if changed:
            result['changed_objects'] = list(changed)
            if tinted:
                result['vertex_neutralised'] = tinted
            if also - set(changed):
                result['also_changed'] = sorted(also - set(changed), key=dc._id_order)
            if parts:
                result['also_changed_parts'] = parts
            lab.batch_finish(item, inv, context, result)
            files = lab.batch_reload(item, inv.dat.data(), exported)
    if not applied:
        raise ValueError('No edit applied. ' + ' '.join(f'Edit {i}: {reason}' for i, reason in sorted(failed.items())))
    if files is None:
        files = [image_file(viewer.grab_frame(), 'Edited stage.png' if stage else 'Edited skin.png')]
    textures = sorted({i for kind, info in applied.values() for i in info.get('textures', ())} & set(written))
    restored = sorted({i for kind, info in applied.values() for i in info.get('restored', ())})
    result = {'applied': len(applied), 'failed': [{'index': i, 'kind': _named_kind(edits[i], stage), 'reason': failed[i]}
                                                  for i in sorted(failed)],
              **({'changed_textures': textures} if textures else {}),
              **({'restored_textures': restored} if restored else {}),
              **({'material_colours': len(item['batch_materials'])} if item['batch_materials'] else {}),
              **result, **({'notes': notes} if notes else {}), 'files': files}
    if not stage and textures:
        from .skin_lab import reach
        reached = reach(item, textures)          # parts reading the same pixels, as a texture edit says them
        if reached.get('also_changed'):
            result['also_changed'] = list(result.get('also_changed') or ()) + reached['also_changed']
        if reached.get('unmapped_textures'):
            result['unmapped_textures'] = reached['unmapped_textures']
    result['note'] = BATCH_NOTE + (' vertex_neutralised: the material\'s textures were multiplied by these objects\' '
                                   'vertex colours, now grey with their lightness kept, so the material shows its own '
                                   'colours (keep_vertex_colours keeps them).' if result.get('vertex_neutralised') else '')
    item['batch_written'] = sorted(written)
    return result


BATCH_NOTE = ('One render for the whole batch: check it. failed lists the edits that did not apply and why; '
              'fix them in another apply.')


def _named_kind(edit, stage):
    """The kind a failed edit was read as (its own word when it named no known one)."""
    try:
        kind = batch_kind(edit, stage)
        return None if kind == STORE else kind
    except (ValueError, AttributeError, TypeError):
        return edit.get('kind') if isinstance(edit, dict) else None
