"""Randall's bounded stage tools, using the same live renderer as Stage Creator.

The open hands the model everything it needs to start editing in ONE result, so
no model round is spent collecting it: the first rendered picture, a labelled
sheet of the stage's textures (up to three pages of 32), and one row per texture
with its size, how many triangles draw it and whether it is a greyscale slot
(lab_common: those hold lightness only; colour comes from the material). Edits
are batched: `apply` takes up to 64 edits of mixed kinds (texture recolors,
vertex colours, colour keys, lights, material colours, generated materials,
texture resets) with one render and one checkpoint (lab_common.apply_batch); the
single-kind actions (`recolor` with `edits`, `recolor_vertex`, ...) still work.
`reset_texture` returns textures (or, with none named, the whole stage including
its base material colours) to how the session opened them.

A session closed by the idle timer, by `close` or by a backend restart is
reopened from its workspace's last checkpoint on its next call (`_session`,
lab_common.live): the originals `reset_texture` returns to, the base material
colours and the scenery provenance are kept in the workspace beside it.
"""
import atexit
import io
import math
import re
import shutil
import sys
import threading
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image
from core import config
from shared.rendering import stage_editor
from shared.rendering.stage_editor import open_stage, save_copy
from shared.rendering.session import ViewerSession
from shared import mod_files
from randall.assistant.stage_scene import run_scene
from . import lab_common, stage_colours, texture_inspection
from .materials import palette_snapshot, palette_edits, ACTIONS as MATERIAL_ACTIONS

_sessions = {}
_lock = threading.RLock()

# Texture sheet pages the open returns (32 textures each); the rest by texture_sheet.
OPEN_SHEET_PAGES = 3
MAX_EDITS = 64
MISSING = 'Stage Lab session expired or closed; open it again'
# Colour edits are computed on this many threads (numpy and the PNG encoder release
# the GIL); the renderer still receives them one at a time, in the same order.
COMPUTE_THREADS = 4

# What recolor and apply take, said with every refusal of a call's shape (tools.prepare's too): while filming 0.9.0
# an MCP client's three recolor calls were refused for their shape alone, and nothing said which one it wants.
RECOLOR_SHAPE = ('recolor takes edits, a list of {texture_index, colour, optional mask}, for example '
                 '{"action": "recolor", "edits": [{"texture_index": 3, "set_hue": 270, "set_saturation": 60}, '
                 '{"texture_index": 5, "hue_shift": -40, "lightness_scale": 0.8}]}; or one texture_index with '
                 'hue_shift, saturation_shift or lightness_scale beside it; or those shifts alone for every texture. '
                 'A colour is set_hue (0..360) and/or set_saturation (0..100) exactly, or hue_shift (-180..180) and/or '
                 'saturation_shift (-100..100), with optional lightness_scale (0..2, below 1 darker).')
APPLY_SHAPE = ('apply takes edits alone, a list of {kind, ...that kind\'s fields}, for example {"action": "apply", '
               '"edits": [{"kind": "recolor", "texture_index": 3, "set_hue": 270, "set_saturation": 60}, '
               '{"kind": "set_material", "material_id": "Group 1:0", "field": "diffuse", "value": "#8040c0ff"}]}.')
SHAPES = {'recolor': RECOLOR_SHAPE, 'apply': APPLY_SHAPE}
# A recolor edit's own colour fields, which the top-level single form does not take.
_EDIT_ONLY = {'set_hue', 'set_saturation', 'mask'}


def _indices(value):
    """A list of whole numbers (texture indices), or None."""
    return value if isinstance(value, list) and value and all(type(i) is int for i in value) else None


def _json_kind(value):
    """What a refused value is, in JSON's words."""
    return {str: 'a string', dict: 'an object', list: 'a list', bool: 'true/false', int: 'a number',
            float: 'a number', type(None): 'null'}.get(type(value), type(value).__name__)


def recolor_args(args):
    """A recolor call one step from the shape it takes (RECOLOR_SHAPE) -> in that shape; any other call as it was.

    The colour at the top level for several textures (texture_indices, or a list in texture_index), or with an
    edit's own fields (set_hue, set_saturation, mask), is one edit per texture; an edit naming several textures
    (texture_indices) is one per texture. Run by tools.prepare after its schema repairs (tools.reshape)."""
    if not isinstance(args, dict) or args.get('action') != 'recolor':
        return args
    edits = args.get('edits')
    if isinstance(edits, list):
        split = []
        for edit in edits:
            many = None
            if isinstance(edit, dict):
                index = edit.get('texture_index')
                many = _indices(index) if isinstance(index, list) else (
                    _indices(edit.get('texture_indices')) if index is None else None)
            if many:
                rest = {k: v for k, v in edit.items() if k not in ('texture_index', 'texture_indices')}
                split += [{'texture_index': i, **rest} for i in many]
            else:
                split.append(edit)
        return {**args, 'edits': split} if len(split) <= MAX_EDITS else args
    colour = {key: args[key] for key in lab_common.CHANGE_FIELDS - {'texture_index'} if key in args}
    index, many = args.get('texture_index'), args.get('texture_indices')
    if edits is not None or not colour or 'include_materials' in args or (index is not None and many is not None):
        return args
    targets = _indices(many if many is not None else index if isinstance(index, list) else None)
    if targets is None and type(index) is int and _EDIT_ONLY & set(colour):
        targets = [index]
    if targets is None or len(targets) > MAX_EDITS:
        return args
    rest = {k: v for k, v in args.items() if k not in colour and k not in ('texture_index', 'texture_indices')}
    return {**rest, 'edits': [{'texture_index': i, **colour} for i in targets]}


def _close(session_id):
    item = _sessions.pop(session_id)
    if item.get('timer'): item['timer'].cancel()
    item['viewer'].close()


def _close_all():
    with _lock:
        for session_id in list(_sessions):
            _close(session_id)


atexit.register(_close_all)


def _expire(session_id):
    with _lock:
        item = _sessions.get(session_id)
        if not item: return
        remaining = lab_common.IDLE_SECONDS - (time.monotonic() - item['used'])
        if remaining <= 0:
            _close(session_id)
            return
        timer = threading.Timer(remaining, _expire, args=(session_id,))
        timer.daemon = True; item['timer'] = timer; timer.start()


def _workspace(session_id):
    """The session's Stage Lab workspace (stage_editor), or None for an id that names none."""
    if not lab_common.workspace_id(session_id):
        return None
    base = config.STORAGE_PATH.resolve()
    directory = base / 'stage_editor' / session_id       # stage_editor._root(), without creating it
    return directory if directory.is_dir() and directory.resolve().is_relative_to(base) else None


def keep(session_id, item):
    """Write the resume record after a checkpoint: what reopening this session needs (module doc)."""
    directory = _workspace(session_id)
    if directory is None or not item.get('checkpoint'):
        return
    if item.get('originals_token') and item.get('original_textures') is not None:
        lab_common.keep_textures(directory, item['original_textures'], item['originals_token'])
    lab_common.keep(directory, {
        'kind': 'stage', 'checkpoint': item['checkpoint'], 'revision': item.get('revision', 0),
        'textures': lab_common.texture_list(item['viewer']),
        'originals_token': item.get('originals_token'),
        'material_originals': item.get('material_originals'),
        'material_baseline': item.get('material_baseline'),
        'scene_instances': item.get('scene_instances', {}),
        'coverage': texture_inspection.coverage_record(item)})


def _resume(session_id, directory, record):
    """A Stage Lab item reopened from the workspace's last checkpoint (lab_common.live)."""
    try:
        directory, info = stage_editor.resolve(session_id)
        path, _ = mod_files.resolve(record['checkpoint']['file_id'])
        originals = lab_common.kept_textures(directory, record['originals_token'])
    except (ValueError, KeyError, TypeError, OSError):
        raise ValueError(MISSING)
    # The renderer reads its own copy, never the immutable chat file.
    copy = directory / f'resumed-{record["checkpoint"]["file_id"]}.dat'
    if not copy.exists():
        shutil.copyfile(path, copy)
    for old in directory.glob('resumed-*.dat'):
        if old != copy:
            old.unlink(missing_ok=True)
    from core.viewer_tools import find_available_port
    viewer = ViewerSession(config.HSDRAW_EXE, find_available_port(), copy,
                           logs_path=config.LOGS_PATH, subprocess_kwargs=config.get_subprocess_args())
    if not lab_common.same_textures(viewer, record.get('textures')):
        viewer.close()
        raise ValueError(MISSING)
    source = {**info, 'datFile': str(directory / 'source.dat'), 'datName': Path(info['member']).name,
              'textures': []}
    item = {'viewer': viewer, 'source': source, 'used': time.monotonic(), 'kind': 'stage',
            'home_camera': dict(viewer.camera), 'checkpoint': record['checkpoint'], 'revision': record.get('revision', 0),
            'original_textures': originals, 'originals_token': record['originals_token'],
            'material_originals': record.get('material_originals'),
            'material_baseline': record.get('material_baseline'),
            'scene_instances': record.get('scene_instances') or {}}
    _derive(item)
    texture_inspection.restore_coverage(item, record.get('coverage'))
    return item


def _session(session_id, action=None):
    """The session's item; one that has closed is reopened from its last checkpoint (lab_common.live)."""
    if action == 'close':
        return _sessions.get(session_id)       # nothing to reopen just to close it
    return lab_common.live(sys.modules[__name__], session_id)


def supported_stages():
    """The stages `stage_lab_open` opens, in the vault's order, as the panel's stage picker shows them.

    The Stage Lab's own limit is shared/rendering/stage_editor.open_stage: any stage
    code in core.stages.ALL_STAGES (the 29 versus stages: the six tournament stages
    first), and nothing else. Each row: `code`, `name`, the vault `folder`
    (<storage>/das/<folder>/<variant id>.zip), `legal` (one of the six; only those
    have an in-game stage test) and `art`, the backend path of the stage's picture
    (core.stages.catalog_entry). GET /api/assistant/status serves this as
    `recolor_stages`; the blueprint accepts a picked stage only from it.
    """
    from core.stages import ALL_STAGES, LEGAL_STAGE_CODES, catalog_entry
    return [{'code': code, 'name': stage['name'], 'folder': stage['folder'],
             'legal': code in LEGAL_STAGE_CODES, 'art': catalog_entry(code)['artUrl']}
            for code, stage in ALL_STAGES.items()]


def _inventory(item):
    """Read every texture once: the reset originals, the greyscale slots, triangle
    counts and the base material colours as the session has them now."""
    viewer = item['viewer']
    raws = {t['index']: viewer.get_full_texture(t['index']) for t in viewer.textures}
    item['original_textures'] = raws
    item['originals_token'] = lab_common.token()      # kept with the workspace on the next checkpoint
    _derive(item)
    try:
        samples, fields = palette_snapshot(viewer)
        item['material_originals'] = [
            {'id': material_id, 'field': key, 'value': '#' + ''.join(f'{int(v):02x}' for v in samples[k][0, 0, :3]) + alpha}
            for k, (material_id, key, alpha) in fields.items()]
    except Exception:
        item['material_originals'] = None
    return raws


def _derive(item):
    """What follows from the originals and the geometry: greyscale slots, triangle counts (also on a resume)."""
    raws = item['original_textures']
    item['greyscale'] = {i for i, raw in raws.items() if lab_common.greyscale(lab_common.pixels(raw))}
    item['uv_layout'] = None
    try:
        layout = lab_common.uv_layout(item)
        item['triangles'] = {entry['index']: len(entry.get('triangles') or []) for entry in layout}
    except Exception:
        item['triangles'] = None          # an older renderer: rows simply carry no count


def _rows(item):
    """One compact row per live texture: what the model needs to pick targets."""
    rows = []
    triangles = item.get('triangles')
    for texture in item['viewer'].textures:
        index = texture['index']
        row = {'index': index, 'name': texture.get('name'), 'width': texture['width'], 'height': texture['height']}
        base = index
        if texture.get('matAnim'):
            row['animates'] = base = texture.get('animates', -1)
        if texture.get('extra'):
            row['extra'] = True
        if triangles is not None:
            row['triangles'] = triangles.get(base, 0)
        if index in item.get('greyscale', ()):
            row['greyscale'] = True
        rows.append(row)
    return rows


SHEET_NOTE = ('Labels are live Stage Lab indices and size; "grey" marks a greyscale slot (' + lab_common.GREYSCALE_NOTE
              + ') An arrow names the texture an animation frame replaces. Texture names do not say which surface a '
              'texture is: the identify map shows which id draws each surface; highlight shows where given textures draw.')


def _identify(item, camera=None, points=None, shade=None):
    """The identify map (texture_inspection.identify): three views in one picture (game camera, raised
    three-quarter, zoom on the busiest small scenery), or with `camera` one view from there."""
    return texture_inspection.identify(item, stage_colours.shown_data(item), camera=camera, points=points,
                                       shade=shade, grey=item.get('greyscale', ()), name='Stage identify map.png',
                                       views='stage')


def _opening_identify(item, frame):
    """The open's identify map: a help, so a failure costs the map, never the open (unless the look left no
    renderer: texture_inspection._take_back closes one that reloaded with another texture list)."""
    try:
        return _identify(item, shade=frame)
    except Exception:
        if not item['viewer'].alive():
            raise
        import logging
        logging.getLogger(__name__).warning('Stage Lab: no identify map on the open', exc_info=True)
        return {}


# What each edit changed, for the coverage line (texture_inspection.mark_edited / coverage).
def track(item, name, args, result):
    """Called with every checkpointed stage edit (continuity.record_stage_result)."""
    if not isinstance(result, dict) or result.get('error'):
        return
    action = args.get('action')
    mark = lambda **kw: texture_inspection.mark_edited(item, **kw)     # noqa: E731
    if name == 'skin_material':
        if action == 'apply':
            mark(textures=result.get('updated_textures') or ())
        elif action == 'reset':
            mark(clear=result.get('updated_textures') or ())
    elif action in ('recolor', 'replace_texture'):
        whole = action == 'recolor' and args.get('edits') is None and args.get('texture_index') is None
        mark(textures=result.get('changed') or (), every=whole)
    elif action == 'reset_texture':
        mark(clear=True if args.get('texture_indices') is None else result.get('restored') or ())
    elif action in ('recolor_vertex', 'recolor_animated'):
        mark(objects=list(result.get('changed') or ()) + list(result.get('also_changed') or ()))
    elif action == 'apply':                   # the batch (lab_common.apply_batch)
        mark(clear=result.get('restored_textures') or ())
        mark(textures=result.get('changed_textures') or (),
             objects=list(result.get('changed_objects') or ()) + list(result.get('also_changed') or ())
             + [material_id for material_id, _ in item.get('batch_materials') or ()])
    elif action == 'set_material':
        mark(objects=[args.get('material_id')])
    elif action == 'reset_colors':
        mark(clear=list(result.get('restored') or ()) if args.get('material_ids') is not None else
             [k for k in (item.get('edited_ids') or ()) if isinstance(k, str)])
    elif action in ('copy_objects', 'transform_scenery', 'hide_objects'):
        item['identify'] = None               # new geometry: the next identify map says it again


def coverage(session_id):
    """The coverage line for a live Stage Lab session (texture_inspection.coverage), or None."""
    with _lock:
        item = _sessions.get(session_id)
        return texture_inspection.coverage(item) if item else None


# A request that names a surface stays on it; anything else ("a lava retexture", "make it purple",
# "night version") restyles the whole stage (the stage card), and its edits carry the coverage line.
_SURFACES = re.compile(
    r'\b(platforms?|tree|trees|trunks?|leaves|leaf|canopy|bush|bushes|foliage|grass|ground|floor|dirt|soil|'
    r'underside|sky|skies|background|clouds?|water|pond|lake|sea|river|waterfall|fence|fences|flowers?|'
    r'rainbow|walls?|buildings?|pillars?|ledges?|stands|screen|logo)\b', re.I)
_WHOLE = re.compile(r'\b(whole|entire|everything|all of it|all over|theme|themed|version)\b', re.I)


def whole_stage_request(text):
    """True when the request restyles the whole stage rather than a surface it names."""
    text = text or ''
    return bool(_WHOLE.search(text)) or not _SURFACES.search(text)


def _sheets(item, pages):
    viewer, raws = item['viewer'], item.get('original_textures') or {}
    marks = {i: 'grey' for i in item.get('greyscale', ())}
    files = []
    for page in pages:
        sheet = texture_inspection.texture_sheet(viewer, page, marks=marks,
                                                 read=lambda i: raws.get(i) or viewer.get_full_texture(i))
        files.extend(sheet['files'])
    return files


def stage_lab_open(stage_code, variant_id=None):
    with _lock:
        lab_common.make_room(sys.modules[__name__])
        source = open_stage(stage_code, variant_id)
        from core.viewer_tools import find_available_port
        viewer = ViewerSession(config.HSDRAW_EXE, find_available_port(), source['datFile'],
                               logs_path=config.LOGS_PATH, subprocess_kwargs=config.get_subprocess_args())
        item = {'viewer': viewer, 'source': source, 'used': time.monotonic(), 'kind': 'stage',
                'home_camera': dict(viewer.camera)}
        try:
            _inventory(item)
            pages = math.ceil(len(viewer.textures) / 32) or 1
            frame = viewer.grab_frame()
            identified = _opening_identify(item, frame)
            files = [lab_common.image_file(frame, 'Stage preview.png'), *identified.get('files', []),
                     *_sheets(item, range(min(pages, OPEN_SHEET_PAGES)))]
        except Exception:
            viewer.close()
            raise
        _sessions[source['id']] = item
        _expire(source['id'])
        table = {key: identified[key] for key in ('views', 'surfaces', 'major', 'too_small', 'not_visible')
                 if key in identified}
        return {'session_id': source['id'], 'stage': stage_code, 'textures': stage_colours.annotate(item, _rows(item)),
                'files': files, 'sheet_pages': pages, **stage_colours.evidence(item),
                **({'identify': table} if table else {}),
                'note': 'Private stage working copy: the first file is the stage as it renders now, '
                        + ('then the identify map (' + identified.get('note', '') + ' Its table is `identify`.), '
                           if table else '') + 'then labelled texture sheets'
                        + (f' (pages 0-{OPEN_SHEET_PAGES - 1} of {pages}; texture_sheet page=N for the rest)'
                           if pages > OPEN_SHEET_PAGES else '') +
                        '. ' + SHEET_NOTE + ' The human editor uses its own working copy; exported PNGs can be applied there.'}


def _texture_ids(viewer, indices, label='texture_indices'):
    live = {t['index'] for t in viewer.textures}
    if not isinstance(indices, list) or not indices or any(type(i) is not int or i not in live for i in indices):
        raise ValueError(f'{label} must list live texture indices from the open or inspect.')
    return indices


def _parallel(compute, keys):
    """compute(key) for every key on COMPUTE_THREADS threads, in the keys' order."""
    keys = list(keys)
    if len(keys) < 2:
        return [compute(key) for key in keys]
    with ThreadPoolExecutor(min(COMPUTE_THREADS, len(keys))) as pool:
        return list(pool.map(compute, keys))


def _write(item, updated, name):
    """Send {index: PNG bytes} to the renderer, in order (one batch on a protocol-2 viewer:
    session.update_textures), and grab the result."""
    viewer = item['viewer']
    lab_common.write_textures(viewer, updated)
    return [lab_common.image_file(viewer.grab_frame(), name)]


def _recolor_edits(item, edits):
    """Several textures in one call, each change applied in order to the texture's current pixels."""
    viewer = item['viewer']
    if not isinstance(edits, list) or not 1 <= len(edits) <= MAX_EDITS:
        got = f'{len(edits)} changes' if isinstance(edits, list) else _json_kind(edits)
        raise ValueError(f'edits takes a list of 1..{MAX_EDITS} changes, not {got}. ' + RECOLOR_SHAPE)
    plans = []
    for position, change in enumerate(edits):
        extra = sorted(set(change) - lab_common.CHANGE_FIELDS) if isinstance(change, dict) else ()
        if not isinstance(change, dict) or extra or 'texture_index' not in change:
            wrong = (f'is {_json_kind(change)}, not an object' if not isinstance(change, dict) else
                     f'has {", ".join(extra)}, which a recolor edit does not take' if extra else 'has no texture_index')
            raise ValueError(f'Edit {position} {wrong}. ' + RECOLOR_SHAPE)
        index = _texture_ids(viewer, [change['texture_index']], 'texture_index')[0]
        value = lab_common.colour_change(change)
        if lab_common.adds_colour(value):
            lab_common.refuse_greyscale(item, [index])
        plans.append((index, value, change.get('mask')))
    indexes = list(dict.fromkeys(index for index, _, _ in plans))
    raws = {index: viewer.get_full_texture(index) for index in indexes}
    current = dict(zip(indexes, _parallel(lambda index: lab_common.pixels(raws[index]), indexes)))
    for index, value, mask in plans:     # validate every mask before computing anything
        lab_common.select(current[index], mask)
    # A texture's own changes apply in the order given; textures are independent of each other.
    changes = {index: [(value, mask) for own, value, mask in plans if own == index] for index in indexes}

    def compute(index):
        pixels = current[index]
        for value, mask in changes[index]:
            out = lab_common.adjust(pixels, value, mask)
            if out is not None:
                pixels = out
        return None if np.array_equal(pixels, current[index]) else lab_common.png(pixels)
    encoded = dict(zip(indexes, _parallel(compute, indexes)))
    updated = {index: data for index, data in encoded.items() if data is not None}
    files = _write(item, updated, 'Recolored stage.png') if updated else [lab_common.image_file(viewer.grab_frame(), 'Recolored stage.png')]
    return {'changed': list(updated), 'unchanged': [i for i in indexes if i not in updated], 'files': files,
            **({'note': 'Some edits matched no pixels or changed nothing; check their masks and values.'}
               if len(updated) < len(indexes) else {})}


def _recolor(item, texture_index, hue_shift, saturation_shift, lightness_scale, include_materials):
    """The original form: one texture, or (no texture_index) every texture plus the base material colours."""
    viewer = item['viewer']
    hue = float(hue_shift or 0); saturation = float(saturation_shift or 0)
    if not math.isfinite(hue) or not -180 <= hue <= 180 or not math.isfinite(saturation) or not -100 <= saturation <= 100:
        raise ValueError('Hue must be -180..180 and saturation -100..100')
    scale = lab_common._number(1 if lightness_scale is None else lightness_scale, 'lightness_scale', 0, 2)
    if include_materials is not None and type(include_materials) is not bool:
        raise ValueError('include_materials must be boolean')
    value = (hue, saturation, 'shift', scale)
    if texture_index is not None and lab_common.adds_colour(value):
        lab_common.refuse_greyscale(item, [texture_index])
    use_materials = (texture_index is None) if include_materials is None else include_materials
    samples, fields = palette_snapshot(viewer) if use_materials else ({}, {})
    indexes = [texture_index] if texture_index is not None else [t['index'] for t in viewer.textures]
    grey = item.get('greyscale', set())
    # Snapshot first: source textures that alias each other must not accumulate shifts.
    raws = {index: viewer.get_full_texture(index) for index in indexes}

    def compute(index):
        # A greyscale slot keeps only lightness on save: hue/saturation there would show in the
        # preview and vanish from the file, so it takes the lightness part alone.
        own = (0, 0, 'shift', scale) if index in grey else value
        out = lab_common.adjust(lab_common.pixels(raws[index]), own) if (own[0] or own[1] or own[3] != 1) else None
        return None if out is None else lab_common.png(out)
    updated, skipped = {}, []
    for index, data in zip(indexes, _parallel(compute, indexes)):
        if data is not None:
            updated[index] = data
        elif index in grey and texture_index is None:
            skipped.append(index)
    if fields:
        from shared.rendering import palette
        groups, maps = palette.analyze(samples, 16)
        edits = palette_edits(samples, fields, maps, {i: value for i in range(len(groups))})
        lab_common.material_baseline(item)
        viewer.material_command({'type': 'setMaterialColors', 'edits': edits})
        item['last_material_edits'] = edits      # the workbench view replays them (continuity)
    files = _write(item, updated, 'Recolored stage.png')
    return {'changed': list(updated), 'updated_material_colors': len(fields),
            **({'greyscale_kept': skipped} if skipped else {}), 'files': files}


def _reset(item, texture_indices):
    """Back to how the session opened: the named textures, or everything (textures and material colours)."""
    viewer = item['viewer']
    originals = item.get('original_textures') or {}
    chosen = _texture_ids(viewer, texture_indices) if texture_indices is not None else list(originals)
    restored = []
    for index in chosen:
        if index not in originals:
            raise ValueError(f'Texture {index} has no recorded original in this session.')
        if not np.array_equal(lab_common.pixels(viewer.get_full_texture(index)), lab_common.pixels(originals[index])):
            restored.append(index)
    # A texture's readback is its own last write, so reading them all first changes nothing.
    lab_common.write_textures(viewer, {index: originals[index] for index in restored})
    materials = 0
    if texture_indices is None and item.get('material_originals'):
        lab_common.material_baseline(item)
        viewer.material_command({'type': 'setMaterialColors', 'edits': item['material_originals']})
        materials = len(item['material_originals'])
    return {'restored': restored, 'restored_material_colors': materials,
            'files': [lab_common.image_file(viewer.grab_frame(), 'Reset stage.png')]}


def _scenery_viewer(viewer, path):
    """The renderer showing a scenery edit's file: the session's own with the file loaded into it
    (loadDat, camera kept) when it can, else a fresh one with the camera copied."""
    if lab_common.supports(viewer, 'loadDat'):
        try:
            viewer.load_dat(path)
            return viewer
        except Exception:
            pass          # the renderer may show nothing now: a fresh one replaces it
    from core.viewer_tools import find_available_port
    candidate = None
    try:
        candidate = ViewerSession(config.HSDRAW_EXE, find_available_port(), path, logs_path=config.LOGS_PATH,
                                  subprocess_kwargs=config.get_subprocess_args())
        camera = viewer.camera
        candidate.set_camera(rot_x=camera['rotX'], rot_y=camera['rotY'], scale=camera['scale'], x=camera['x'],
                             y=camera['y'])
        return candidate
    except Exception:
        if candidate:
            candidate.close()
        raise


def _vault_picture(item):
    """The saved variant's vault picture: the whole stage from the camera the session opened with (the game
    camera), never wherever the AI last turned or zoomed it (an underside, one fence). The session's own view comes
    back after, so the next edit sees what it saw."""
    viewer, home = item['viewer'], item.get('home_camera')
    here = dict(viewer.camera) if home else None
    moved = bool(home) and here != home
    if moved:
        _set_camera(viewer, home)
    try:
        return viewer.grab_frame()
    finally:
        if moved:
            _set_camera(viewer, here)


def _set_camera(viewer, camera):
    viewer.set_camera(rot_x=camera['rotX'], rot_y=camera['rotY'], scale=camera['scale'], x=camera['x'], y=camera['y'])


def stage_lab(session_id, action, texture_index=None, file_id=None, name=None,
              hue_shift=None, saturation_shift=None, camera=None, frame=None, playing=None,
              material_id=None, field=None, value=None, enabled=None, include_materials=None, source_session_id=None, object_ids=None, target_group=None, instance_id=None, transform=None, animation_index=None,
              edits=None, lightness_scale=None, texture_indices=None, page=None, material_ids=None, points=None,
              chat_id=None):
    """One Stage Lab action. `name` is save's variant name; with apply (or any edit) it names the result the
    retexture auto-save keeps (randall/recolor/autosave.py), and the call ignores it. `chat_id` is the engine's
    (never in the model's schema): a save records it on the new variant."""
    with _lock:
        item = _session(session_id, action)
        if item is None:
            return {'closed': True}           # already closed
        viewer = item['viewer']; item['used'] = time.monotonic()
        scene_actions = {'scene': 'stage_scene', 'preview_objects': 'preview_stage_objects',
                         'copy_objects': 'copy_stage_objects', 'transform_scenery': 'transform_stage_scenery', 'hide_objects': 'hide_stage_objects'}
        if action in scene_actions or action == 'export':
            origin = {'stage_workspace': session_id, 'stage_code': item['source']['stage_code'], 'scene_instances': item.get('scene_instances', {})}
            source_file = mod_files.register(viewer.export_dat(), item['source']['datName'], origin=origin, edited=True)
            if action == 'export': return {'files': [source_file]}
            donor_file = None
            if action == 'copy_objects':
                try:
                    donor = _session(source_session_id)      # a closed donor reopens too
                except ValueError:
                    donor = None
                if not donor: raise ValueError('Open the source stage in a second Stage Lab session first')
                donor['used'] = time.monotonic()
                donor_file = mod_files.register(donor['viewer'].export_dat(), donor['source']['datName'])['file_id']
            result = run_scene(scene_actions[action],source_file['file_id'],donor_file_id=donor_file,
                               object_ids=object_ids,target_group=target_group,instance_id=instance_id,transform=transform,animation_index=animation_index)
            if action in {'scene', 'preview_objects'}: return result
            path, info = mod_files.resolve(result['files'][0]['file_id'])
            candidate = _scenery_viewer(viewer, path)
            try:
                preview = lab_common.image_file(candidate.grab_frame(), 'Stage scenery preview.png')
            except Exception:
                if candidate is not viewer:
                    candidate.close()
                raise
            item['viewer'] = candidate
            item.pop('animation', None)           # a loaded file plays from frame 0: nothing to set again
            item['scene_instances'] = info['origin']['scene_instances']
            if candidate is not viewer:
                viewer.close()
            # The colour evidence and the bytes it was read from are the old file's (a renderer
            # loaded in place is the same object, so its caches would still look current).
            item['colour_scan'] = None
            item.pop('colour_data', None)
            # New geometry can renumber textures: the reset originals, greyscale slots,
            # counts and material values are this edited copy's from here on.
            item['material_baseline'] = None
            _inventory(item)
            result['files'].insert(0,preview)
            result['textures'] = _rows(item)
            return result
        if action in MATERIAL_ACTIONS:
            result = lab_common.material(item, action, material_id, field, value, enabled)
            if action != 'materials': result['files'] = [lab_common.image_file(viewer.grab_frame(), 'Stage material preview.png')]
            return result
        if action in ('recolor', 'recolor_vertex', 'recolor_animated', 'recolor_lights'):
            edits = lab_common.single_kind(action, edits)
        if action in stage_colours.ACTIONS:     # vertex colours and animated colours (stage_colours.py)
            return stage_colours.action(item, action, edits=edits, material_ids=material_ids)
        if action == 'apply':                   # one batch of mixed edits (lab_common.apply_batch)
            if any(v is not None for v in (texture_index, texture_indices, material_ids, hue_shift, saturation_shift,
                                           lightness_scale, material_id, field, value)):
                raise ValueError('apply takes edits alone: each edit carries its own kind, targets and values. '
                                 + APPLY_SHAPE)
            return lab_common.apply_batch(item, edits, stage=True)
        if action == 'close':
            _close(session_id)
            return {'closed': True}
        if action not in ('inspect', 'frame', 'texture', 'replace_texture', 'recolor', 'camera', 'animation', 'save',
                          'texture_usage', 'texture_sheet', 'highlight', 'identify', 'reset_texture'):
            raise ValueError('Unknown stage operation')
        if action == 'identify':
            return _identify(item, camera=camera, points=points)
        if texture_index is not None and (type(texture_index) is not int or not any(t['index'] == texture_index for t in viewer.textures)):
            raise ValueError('Choose a texture index from inspection' + (
                f': texture_index is one whole number. {RECOLOR_SHAPE}'
                if action == 'recolor' and type(texture_index) is not int else ''))
        if action == 'inspect':
            return {'session_id': session_id, 'textures': stage_colours.annotate(item, _rows(item))}
        if action == 'texture_sheet':
            pages = math.ceil(len(viewer.textures) / 32) or 1
            page = 0 if page is None else page
            if type(page) is not int or not 0 <= page < pages:
                raise ValueError(f'Choose a texture sheet page from 0 to {pages - 1}.')
            marks = {i: 'grey' for i in item.get('greyscale', ())}
            sheet = texture_inspection.texture_sheet(viewer, page, marks=marks)
            return {**sheet, 'note': SHEET_NOTE}
        if action == 'texture_usage':
            usage = texture_inspection.texture_usage(viewer, layout=lab_common.uv_layout(item))
            for row in usage['textures']:
                if row['index'] in item.get('greyscale', ()):
                    row['greyscale'] = True
            return {**usage, 'note': 'Live Stage Lab indices: mapped_triangles and bounds (stage world units) say how '
                                     'much geometry draws a texture and where. Use highlight to see it on the stage.'}
        if action == 'highlight':
            return texture_inspection.highlight(item, texture_indices)
        if action == 'reset_texture':
            return _reset(item, texture_indices)
        if action == 'frame':
            return {'files': [lab_common.image_file(viewer.grab_frame(), 'Stage preview.png')]}
        if action == 'texture':
            if texture_index is None:
                raise ValueError('Select a texture index')
            return {'files': [lab_common.image_file(viewer.get_full_texture(texture_index), f'Stage texture {texture_index}.png')]}
        if action == 'replace_texture':
            if texture_index is None:
                raise ValueError('Select a texture index')
            lab_common.refuse_greyscale(item, [texture_index], 'a picture')
            path, info = mod_files.resolve(file_id)
            if info['extension'] != '.png':
                raise ValueError('Choose a PNG file')
            texture = next(t for t in viewer.textures if t['index'] == texture_index)
            with Image.open(path) as image:
                out = io.BytesIO()
                image.convert('RGBA').resize((texture['width'], texture['height'])).save(out, format='PNG')
            viewer.update_texture(texture_index, out.getvalue())
            return {'changed': [texture_index], 'files': [lab_common.image_file(viewer.grab_frame(), 'Edited stage.png')]}
        if action == 'recolor':
            if edits is not None:
                if any(v is not None for v in (texture_index, texture_indices, hue_shift, saturation_shift,
                                               lightness_scale, include_materials)):
                    raise ValueError('Send edits alone: each edit carries its own texture_index and values. '
                                     + RECOLOR_SHAPE)
                return _recolor_edits(item, edits)
            if texture_indices is not None:
                # Not a whole-stage recolor that leaves them out (include_materials goes with that form only).
                raise ValueError('recolor names several textures in edits, one per texture. ' + RECOLOR_SHAPE)
            return _recolor(item, texture_index, hue_shift, saturation_shift, lightness_scale, include_materials)
        if action == 'camera':
            if not isinstance(camera, dict) or set(camera) - {'rot_x', 'rot_y', 'scale', 'x', 'y'}:
                raise ValueError('Use rot_x, rot_y, scale, x and y camera values')
            if any(not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > 10000 for v in camera.values()):
                raise ValueError('Invalid camera value')
            viewer.set_camera(**camera)
            return {'files': [lab_common.image_file(viewer.grab_frame(), 'Stage view.png')]}
        if action == 'animation':
            item['uv_layout'] = None      # positions follow the pose
            if frame is not None:
                if not isinstance(frame, (int, float)) or not math.isfinite(frame) or not 0 <= frame <= 1000000:
                    raise ValueError('Invalid animation frame')
                viewer.set_anim_frame(frame)
                item.setdefault('animation', {})['frame'] = frame     # set again after a look's reload
            if playing is not None:
                if type(playing) is not bool: raise ValueError('playing must be a boolean')
                viewer.set_anim_playing(playing)
                item.setdefault('animation', {})['playing'] = playing
            return {'files': [lab_common.image_file(viewer.grab_frame(), 'Stage animation.png')]}
        screenshot = _vault_picture(item)
        preview = lab_common.image_file(screenshot, 'Added to vault.png')
        result = save_copy(session_id, viewer.export_dat(), name or '', screenshot, chat_id=chat_id)
        result['files'] = [preview]
        return result
