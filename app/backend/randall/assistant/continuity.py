"""Bounded, structured working state rebuilt from server-owned receipts."""
import json
import re
import uuid
from pathlib import Path

from core import config
from shared import mod_files
from randall.recolor import lab_common, skin_lab, stage_lab


# Model-facing, on the result of an edit whose checkpoint (or resume record) could not be
# written, and on every later result until one is: both labs report it the same way.
CHECKPOINT_ERROR = ('The live edit succeeded but its recovery copy could not be saved. '
                    'Export before closing this session.')

EDIT_ACTIONS = {'recolor', 'reset_palette', 'set_material', 'reset_material', 'apply', 'reset',
                # costume_colours: a viewer_update only when the renderer took them in place
                'recolor_vertex', 'recolor_animated', 'reset_colors', 'reset_texture'}
# `apply`/`reset` are skin_material's, which also edits a Stage Lab session; `apply` is also both
# labs' batch of mixed edits (lab_common.apply_batch).
STAGE_EDIT_ACTIONS = {'replace_texture', 'recolor', 'reset_texture', 'set_material', 'reset_material',
                      'copy_objects', 'transform_scenery', 'hide_objects', 'apply', 'reset',
                      # stage_colours: a viewer_update only when the renderer took them in place
                      'recolor_vertex', 'recolor_animated', 'recolor_lights', 'reset_colors'}
# The colour edits model_colours.reload can put into the renderer in place.
COLOUR_ACTIONS = ('recolor_vertex', 'recolor_animated', 'recolor_lights', 'reset_colors')


# The workbench's 3D view (frontend randall/assistant/WorkbenchViewer.jsx) shows the
# newest checkpoint. Restarting its renderer for every edit costs 6-10 s (process, GL
# and scene start-up); when an edit changed only textures and material values, the
# view can put them into the renderer it already runs (updateTexture, setMaterialColors,
# setMaterial) instead. `viewer_update` says what: the checkpoint it applies on top of
# (`from`), each changed texture as a PNG chat file read back from the live session,
# and each changed material field with its new ABSOLUTE value (a reset in the view
# would restore the view's own file's value, not the session's original). A scenery
# or unknown change carries none, and the view reloads as before. Card-only: the
# model never sees it (compaction.UI_ONLY_ANY).
#
# A colour edit (vertex colours, colour keys, lights) the session's renderer took in
# place (model_colours.reload, protocol 2) carries `colours`: the id of the stream
# messages it sent, kept by `keep_colours` (a whole group's vertex colours can be
# hundreds of KB, so never in the transcript), the message types (a view whose
# renderer lacks one reloads) and the objects whose material colours they set (a
# material value recorded before them is older). The view fetches and sends them.
MAX_SWAP_TEXTURES = 64
MATERIAL_ACTIONS = ('set_material', 'reset_material')
KEEP_COLOURS = 256


def _colours_root():
    base = config.STORAGE_PATH.resolve()
    root = base / 'assistant' / 'viewer_updates'
    if not root.resolve().is_relative_to(base):
        raise ValueError('Viewer update storage is outside the vault.')
    root.mkdir(parents=True, exist_ok=True)
    return root


def keep_colours(messages):
    """Store an in-place colour edit's stream messages -> their id (the newest KEEP_COLOURS are kept)."""
    root = _colours_root()
    update_id = uuid.uuid4().hex
    (root / f'{update_id}.json').write_text(json.dumps(messages, separators=(',', ':')), encoding='utf-8')
    rows = sorted(root.glob('*.json'), key=lambda path: path.stat().st_mtime, reverse=True)
    for old in rows[KEEP_COLOURS:]:
        old.unlink(missing_ok=True)
    return update_id


def colours_file(update_id):
    """The stored messages' file for an id from a viewer_update, or None."""
    if not isinstance(update_id, str) or not re.fullmatch(r'[a-f0-9]{32}', update_id):
        return None
    path = _colours_root() / f'{update_id}.json'
    return path if path.is_file() else None


def _colour_update(item, previous, args, result):
    """A colour edit's viewer_update: nothing to change, its in-place messages, or None (the view reloads)."""
    colours = item.pop('viewer_colours', None)
    if not previous:
        return None
    if not (result.get('changed') or result.get('restored')):
        return {'from': previous, 'textures': []}
    if not colours:
        return None
    objects = sorted({entry['id'] for message in colours for entry in message.get('materials') or ()})
    return {'from': previous, 'textures': [],
            'colours': {'id': keep_colours(colours), 'types': sorted({message['type'] for message in colours}),
                        'objects': objects}}


def _batch_update(item, previous, result):
    """An apply batch's viewer_update: its textures, its material values (read back after the whole batch,
    so newer than any colour message) and, when its file colours went in place, their messages; None
    (the view reloads) when those colours needed a reload."""
    colours = item.pop('viewer_colours', None)
    written = item.pop('batch_written', None)
    touched = item.pop('batch_materials', None) or []
    if not previous or not isinstance(written, list) or len(written) > MAX_SWAP_TEXTURES:
        return None
    if result.get('changed_objects') and not colours:
        return None
    viewer = item['viewer']
    update = {'from': previous, 'textures': [
        {'index': index, 'file_id': mod_files.register(viewer.get_full_texture(index),
                                                       f'Viewer texture {index}.png')['file_id']}
        for index in written]}
    if touched:
        listed = {m.get('id'): {f.get('key'): f.get('value') for f in m.get('fields', [])}
                  for m in viewer.material_command({'type': 'getMaterials'}).get('materials') or []}
        update['materials'] = [{'id': material_id, 'field': field, 'value': listed[material_id][field]}
                               for material_id, field in dict.fromkeys(touched)
                               if listed.get(material_id, {}).get(field) is not None]
    if colours:
        update['colours'] = {'id': keep_colours(colours), 'types': sorted({message['type'] for message in colours}),
                             'objects': sorted({entry['id'] for message in colours
                                                for entry in message.get('materials') or ()})}
    return update


def _swap_textures(item, name, args, result):
    """The texture indices an edit wrote, [] for none, None when it may have changed anything else."""
    action = args.get('action')
    if name == 'skin_material' and action in ('apply', 'reset'):
        return result.get('updated_textures')
    if name == 'skin_lab' and action == 'reset_texture':
        return result.get('restored')
    if action in MATERIAL_ACTIONS and name in ('skin_lab', 'stage_lab'):
        return []
    if name == 'skin_lab' and action in ('recolor', 'reset_palette'):
        # The ones it actually uploaded (a texture no changed group touches is not sent again).
        written = (item.get('palette') or {}).get('last_written')
        return written if isinstance(written, list) else result.get('updated_textures')
    if name == 'stage_lab':
        if action in ('recolor', 'replace_texture'):
            return result.get('changed')
        if action == 'reset_texture':
            return result.get('restored')
    return None


def _swap_materials(item, name, args, result):
    """[{id, field, value}] for the material fields an edit changed, [] for none, None when unknown."""
    action = args.get('action')
    if action in MATERIAL_ACTIONS:
        listed = item['viewer'].material_command({'type': 'getMaterials'}).get('materials') or []
        material = next((m for m in listed if m.get('id') == args.get('material_id')), None)
        field = next((f for f in (material or {}).get('fields', []) if f.get('key') == args.get('field')), None)
        return [{'id': material['id'], 'field': field['key'], 'value': field['value']}] if field else None
    if name == 'skin_lab' and action in ('recolor', 'reset_palette'):
        if not result.get('updated_material_colors'):
            return []
        from randall.recolor.materials import palette_edits
        analysis = item.get('palette') or {}
        fields = analysis.get('material_fields')
        return (palette_edits(analysis['originals'], fields, analysis['maps'], analysis['adjustments'])
                if fields else None)
    if name == 'stage_lab' and action == 'recolor':
        return item.get('last_material_edits') if result.get('updated_material_colors') else []
    if name == 'stage_lab' and action == 'reset_texture':
        return item.get('material_originals') if result.get('restored_material_colors') else []
    return []


def _viewer_update(item, previous, name, args, result):
    if name in ('skin_lab', 'stage_lab') and args.get('action') in COLOUR_ACTIONS:
        return _colour_update(item, previous, args, result)
    if name in ('skin_lab', 'stage_lab') and args.get('action') == 'apply':
        return _batch_update(item, previous, result)
    item.pop('viewer_colours', None)
    textures = _swap_textures(item, name, args, result)
    if not previous or not isinstance(textures, list) or len(textures) > MAX_SWAP_TEXTURES:
        return None
    materials = _swap_materials(item, name, args, result)
    if materials is None:
        return None
    viewer = item['viewer']
    update = {'from': previous, 'textures': [
        {'index': index, 'file_id': mod_files.register(viewer.get_full_texture(index),
                                                       f'Viewer texture {index}.png')['file_id']}
        for index in textures]}
    if materials:
        update['materials'] = [{'id': m['id'], 'field': m['field'], 'value': m['value']} for m in materials]
    return update


def record_skin_result(name, args, result):
    """Checkpoint successful edits before a session can expire or the app exits."""
    sid = result.get('session_id') or args.get('session_id')
    if not sid:
        return result
    result.update(session_id=sid, action=args.get('action', 'open'))
    with skin_lab._lock:
        item = skin_lab._sessions.get(sid)
        if not item:
            return result
        result['source_file_id'] = item['source']['file_id']
        # What the workbench shows now: the last checkpoint, or the source before the first edit.
        shown = None if item.get('checkpoint_error') else (item.get('checkpoint') or item['source']).get('file_id')
        update = None
        if args.get('action') in EDIT_ACTIONS:
            try:
                info = item['source']
                item['checkpoint'] = mod_files.register(item['viewer'].export_dat(), info['name'],
                                                        origin=info.get('origin'), edited=True)
                item['checkpoint_textures'] = lab_common.texture_list(item['viewer'])
                skin_lab.keep(sid, item)            # what a resume reopens (recolor/skin_lab.py)
                item.pop('checkpoint_error', None)
                try:
                    update = _viewer_update(item, shown, name, args, result)
                except Exception:
                    update = None           # the view reloads instead
            except Exception:
                item['checkpoint_error'] = CHECKPOINT_ERROR
        if args.get('action') == 'export' and result.get('files'):
            # The export is the last checkpoint's content: nothing for the view to change.
            update = {'from': shown, 'textures': []} if shown and item.get('checkpoint') else None
            item['checkpoint'] = result['files'][0]
            item['checkpoint_textures'] = lab_common.texture_list(item['viewer'])
            try:
                skin_lab.keep(sid, item)
                item.pop('checkpoint_error', None)
            except Exception:
                item['checkpoint_error'] = CHECKPOINT_ERROR
        if update:
            result['viewer_update'] = update
        if item.get('checkpoint_error'):
            result['checkpoint_error'] = item['checkpoint_error']
        # Which costume this session belongs to. A live editor showing the same
        # costume follows its checkpoints; matching on a file name or a
        # character alone would adopt the wrong one. Sent from the open onward,
        # so Randall's workbench can show the costume before the first edit.
        origin = mod_files.origin_of(item['source'])     # a plain label (a model import's) names none
        target = {key: origin[key] for key in ('character', 'skin_id', 'costume_code') if origin.get(key)}
        if target:
            result['skin_target'] = target
        if item.get('checkpoint'):
            result['checkpoint_file'] = item['checkpoint']
            item['revision'] = item.get('revision', 0) + 1
            result['revision'] = item['revision']
    return result


def record_stage_result(name, args, result):
    """Checkpoint stage edits like skin edits, so the workbench can load each one.

    A stage edit only returned a screenshot; the DAT existed nowhere until an
    export. The open registers the untouched source, each edit the live copy, and
    each checkpoint updates the workspace's resume record (recolor/stage_lab.py).
    A checkpoint that cannot be written is reported as the Skin Lab reports it
    (`checkpoint_error`, until the next one is). `checkpoint_file`, `revision` and
    `stage_target` are the workbench's: the model never sees them
    (compaction.STAGE_UI_ONLY)."""
    sid = result.get('session_id') or args.get('session_id')
    if not sid:
        return result
    with stage_lab._lock:
        item = stage_lab._sessions.get(sid)
        if not item:
            return result
        source = item['source']
        origin = {'stage_workspace': sid, 'stage_code': source['stage_code']}
        # The checkpoint the workbench shows; unknown after a failed one (that edit never reached it).
        shown = None if item.get('viewer_stale') else (item.get('checkpoint') or {}).get('file_id')
        try:
            checkpointed = True
            if name == 'stage_lab_open':
                item['checkpoint'] = mod_files.register(Path(source['datFile']).read_bytes(), source['datName'],
                                                        origin=origin)
            elif args.get('action') in STAGE_EDIT_ACTIONS:
                try:
                    stage_lab.track(item, name, args, result)    # what it changed: the coverage line's input
                except Exception:
                    pass                                         # a help: never the checkpoint's failure
                item['checkpoint'] = mod_files.register(item['viewer'].export_dat(), source['datName'],
                                                        origin=origin, edited=True)
                item.pop('viewer_stale', None)
                try:
                    update = _viewer_update(item, shown, name, args, result)
                except Exception:
                    update = None           # the view reloads instead
                if update:
                    result['viewer_update'] = update
            else:
                checkpointed = False
            if checkpointed:
                stage_lab.keep(sid, item)
                item.pop('checkpoint_error', None)
        except Exception:
            # The edit itself succeeded; the live preview misses this step and a resume
            # would reopen an earlier checkpoint.
            item['viewer_stale'] = True
            item['checkpoint_error'] = CHECKPOINT_ERROR
            result['checkpoint_error'] = CHECKPOINT_ERROR
            return result
        if item.get('checkpoint_error'):
            result['checkpoint_error'] = item['checkpoint_error']
        if item.get('checkpoint'):
            item['revision'] = item.get('revision', 0) + 1
            # `action` as the Skin Lab's results carry it: the vision layer keeps the latest render by it.
            result.update(session_id=sid, action=args.get('action', 'open'), checkpoint_file=item['checkpoint'],
                          revision=item['revision'],
                          stage_target={'stage_code': source['stage_code'], 'name': source.get('name')})
    return result


def working_context(receipts):
    sources, swatches, sessions, previews = {}, {}, {}, {}
    for receipt in receipts:
        result = receipt.get('result') or {}
        if result.get('error'):
            continue
        args = receipt.get('arguments') or {}
        for file in result.get('files', []):
            if file.get('extension') in {'.dat', '.usd', '.zip', *mod_files.MODEL_SUFFIXES}:
                sources[file['file_id']] = file
            if receipt.get('name') == 'generate_material':
                # One call can return several swatches; each keeps its OWN prompt.
                own = next((m['prompt'] for m in result.get('materials') or []
                            if m.get('file_id') == file['file_id']), args.get('prompt'))
                # No cost: this state is in the model's context, and users never see dollar amounts.
                swatches[file['file_id']] = {**file, 'prompt': own}
        sid = result.get('session_id') or args.get('session_id')
        # Stage Lab checkpoints are for the workbench preview; they cannot be
        # reopened with skin_lab_open, so they are not skin sessions here.
        # (`stage_target` marks a skin_material call that edited a Stage Lab session.)
        if sid and not str(receipt.get('name') or '').startswith('stage_lab') and not result.get('stage_target'):
            state = sessions.setdefault(sid, {'session_id': sid})
            for key in ('source_file_id', 'checkpoint_file', 'checkpoint_error'):
                if result.get(key):
                    state[key] = result[key]
            if result.get('checkpoint_file') and not result.get('checkpoint_error'):
                state.pop('checkpoint_error', None)
            if receipt.get('name') == 'skin_lab_open' and args.get('file_id'):
                state['source_file_id'] = args['file_id']
        if result.get('preview_id'):
            previews.setdefault(result['preview_id'], {}).update({key: result[key] for key in
                ('preview_id', 'session_id', 'material_file_id', 'texture_indices', 'controls', 'dimensions', 'action') if key in result})
    with skin_lab._lock:
        for sid, state in sessions.items():
            item = skin_lab._sessions.get(sid)
            # A closed session with a resume record reopens on its next call (recolor/skin_lab.py):
            # to the model it is as usable as a live one.
            usable = (item and item['viewer'].alive()) or lab_common.resumable(skin_lab._workspace(sid))
            state['status'] = 'active' if usable else 'unavailable'
            if item:
                state['source_file_id'] = item['source']['file_id']
                if item.get('checkpoint'):
                    state['checkpoint_file'] = item['checkpoint']
                if item.get('checkpoint_error'):
                    state['checkpoint_error'] = item['checkpoint_error']
            state['reopen_file_id'] = (state.get('checkpoint_file') or {}).get('file_id') or state.get('source_file_id')
        for pid, preview in previews.items():
            # A material preview can belong to a Stage Lab session too (skin_material on a stage).
            item = (skin_lab._sessions.get(preview.get('session_id'))
                    or stage_lab._sessions.get(preview.get('session_id')))
            preview['status'] = 'active' if item and pid in item.get('texture_material_plans', {}) else 'unavailable'
    return {'sources': list(sources.values())[-24:],
            'material_swatches': list(swatches.values())[-16:],
            'skin_sessions': list(sessions.values())[-16:], 'material_previews': list(previews.values())[-8:],
            'note': 'Use these exact handles, not IDs recalled from prose. Unavailable sessions can be reopened with '
                    'skin_lab_open(reopen_file_id); that creates a new session and requires new material previews. '
                    'Checkpoints preserve completed edits. Generated swatches persist independently of sessions. '
                    'Earlier image descriptions may be mistaken: inspect the attached evidence or fetch the exact file again.'}
