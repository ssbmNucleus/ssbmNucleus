"""Copy-only costume sessions for Randall's palette and live-view tools.

A session closed by the idle timer, by `close` or by a backend restart is
reopened from its last checkpoint on its next call (`_session`,
lab_common.live), under the same session id: its workspace
(`<storage>/assistant/skin_lab/<session id>/`) keeps what a checkpoint cannot
hold -- the part scope, the palette analysis that
recolor and reset_palette work from, the material values before the first edit.

Colour that lives in no texture (vertex colours, colour animation keys) is
costume_colours.py: its evidence rides on the open, inspect and texture_usage,
its edits are the actions costume_colours.ACTIONS, which say what they reach beyond
what they name as texture edits do (`reach` below).
"""
import atexit
import hashlib
import io
import logging
import math
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import numpy as np
from PIL import Image
from core import config
from shared.rendering import palette, part_identity, part_map
from shared.rendering.session import ViewerSession
from shared import mod_files
from . import costume_colours, lab_common, texture_inspection
from .materials import palette_snapshot, palette_edits, ACTIONS as MATERIAL_ACTIONS

logger = logging.getLogger(__name__)

_sessions = {}
_lock = threading.RLock()
MISSING = 'Skin Lab session expired or closed; open the source again.'


def _file(data, name):
    return lab_common.image_file(data, name)

# --------------------------------------------------------------------------- #
# scope: what an edit reaches besides the part it is aimed at                  #
# --------------------------------------------------------------------------- #
# A measured Goku Fox run went from "one shared palette texture covering the
# whole body" to "I can isolate just the orange fur by colour", recoloured, and
# only THEN found the gi had changed with it. Colour groups are not body parts.
# So the canonical part-map adapter computes, once at open, which parts read the
# same pixels (`part_scope`), and every edit's result says what it reached beyond
# them (`reach`): `also_changed` names the parts that read the same image, and
# `unmapped_textures` the textures no part map covers (a model import, a
# restructured mod). Nothing is refused and nothing is asked of the user: the
# model checks its target from the evidence (known parts, the identify map,
# highlight), edits, reads the render and that line, and fixes it (a colour mask
# by part: analyze_palette with parts) or says in its reply what else changed.

REACH_NOTES = {
    'also_changed': ('also_changed: parts that read the same pixels as what this edit changed, so they changed too: '
                     'check the render; separate them with analyze_palette parts (a colour mask by part) and '
                     'recolor again, or say so in your reply.'),
    'unmapped_textures': ('unmapped_textures: no part map covers them (a model import, a restructured mod); check '
                          'in the render, or the identify map, that only the surface you meant changed.')}


def _scope_map(private_copy, info):
    """The file half of the part scope: the canonical map with every texture decoded.

    Needs no renderer, so skin_lab_open builds it while the renderer starts.
    -> the map, or the exception that stopped it (reported by `_scope_report`).
    """
    try:
        mapping = part_identity.build_map(private_copy, mod_files.origin_of(info))
        for record in mapping['textures']:
            part_identity.decoded_pixels(record)       # cached on the record for attach_viewer
        return mapping
    except Exception as exc:
        return exc


class _SessionReads:
    """The live viewer as part_identity.attach_viewer reads it, through the session's own reads:
    the textures from the renderer (read once, shared.rendering.session) and the UV layout the
    session caches (lab_common.uv_layout), which the open needs again for known_parts."""

    def __init__(self, item):
        self.item = item
        self.textures = item['viewer'].textures

    def get_full_texture(self, index):
        return self.item['viewer'].get_full_texture(index)

    def get_uv_layout(self):
        return lab_common.uv_layout(self.item)


def _scope_report(private_copy, info, viewer, item=None, mapping=None):
    """The canonical part map of THIS session's private copy.

    Built from the file plus the live viewer, never from whichever costume the
    user has open elsewhere. A failure here must not break editing, so it
    degrades to None and the open reply says enforcement is off. `mapping` is
    `_scope_map`'s result when the caller built it already; `item` lets the
    viewer's reads come from the session's caches.
    """
    try:
        if mapping is None:
            mapping = _scope_map(private_copy, info)
        if isinstance(mapping, Exception):
            raise mapping
        part_identity.attach_viewer(mapping, _SessionReads(item) if item is not None else viewer)
        part_identity.label_parts(mapping)
        return part_identity.describe(mapping)
    except Exception:
        logger.warning('[skin_lab] no part scope for this costume', exc_info=True)
        return None


def _scope_index(report):
    """live texture index -> the verdict for the parts that own it."""
    if not report:
        return {}
    index = {}
    for texture in report['textures']:
        live = texture['viewer_index']
        if live is None:
            continue
        owners = texture['parts']
        if owners:
            worst = max((report['parts'][name] for name in owners),
                        key=lambda entry: entry['scope'] == 'shared')
            index[live] = {
                'parts': owners, 'scope': worst['scope'],
                'co_owned_with': sorted({n for name in owners
                                         for n in report['parts'][name]['co_owned_with']}),
                'required_mask': worst['required_mask'],
                'shares_with': sorted({n for name in owners
                                       for n in report['parts'][name]['shares_texels_with']['parts']})}
        else:
            # A costume the map DID place names its hidden low-poly and blend
            # layers by omission; one it did not place says nothing about
            # anything, and a guess there is what this gate exists to stop.
            index[live] = {'parts': [], 'co_owned_with': [], 'shares_with': [],
                           'required_mask': {'required': True, 'available': False,
                                             'kind': 'identification'},
                           'scope': 'unlisted' if report['parts'] else 'unresolved'}
    return index


def _scope_summary(report, index):
    """What skin_lab_open hands the model: the verdict per part, in live indices."""
    if not report:
        return {'mapped': False,
                'note': 'This costume could not be mapped to parts: check your target with identify or highlight '
                        'before editing, and the render after.'}
    parts = {name: {'texture_indices': entry['viewer_indices'], 'scope': entry['scope'],
                    'co_owned_with': entry['co_owned_with'],
                    'required_mask': entry['required_mask']}
             for name, entry in report['parts'].items()}
    return {
        'mapped': True,
        'mapping_version': report['mapping_version'],
        'parts': parts,
        'unresolved_texture_indices': sorted(i for i, row in index.items()
                                             if row['scope'] == 'unresolved'),
        'unresolved_reason': report['unresolved']['reason'],
        'note': 'scope says which parts read the same pixels (colour groups, triangle counts and highlights do '
                'not): editing a `shared` part changes its co-owners too unless analyze_palette with parts '
                'separates them by colour; `unresolved` textures belong to no part map, so identify them '
                '(identify, highlight) yourself. Every edit is made; its result names what else it reached '
                '(also_changed).',
    }


def scope_verdict(item, indices):
    """Group the targeted textures by what would escape the edit."""
    index = item.get('scope_index') or {}
    shared, unresolved, parts = {}, [], []
    for live in sorted(set(indices)):
        row = index.get(live)
        if row is None:
            # The adapter could not tie this live ordinal to a descriptor (two
            # duplicate-looking textures, or pixels matching none of them). An
            # alias it could not resolve is not a texture it cleared.
            unresolved.append(live)
            continue
        for name in row['parts']:
            if name not in parts:
                parts.append(name)
        if row['scope'] == 'shared':
            for name in row['parts']:
                shared.setdefault(name, {**row, 'texture_indices': []})['texture_indices'].append(live)
        elif row['scope'] == 'unresolved':
            unresolved.append(live)
    return {'shared': shared, 'unresolved': unresolved, 'parts': parts}


def _colour_mask_covers(item, shared):
    """analyze_palette with parts is the app's supported narrower mask.

    It clusters each NAMED part on its own and hands a texture's other detail to
    the analysis as borrowed extras, so the part's own colours move and the
    neighbour's do not -- the cap red shifts, the emblem M stays. So a co-owner
    the mask exists to protect does not itself have to be named; what has to
    hold is that every named part is one the adapter says a colour mask can
    isolate, and that every shared part in range is either named or protected.
    """
    analysis = item.get('palette') or {}
    if analysis.get('mask') != 'color':
        return False
    parts = ((item.get('scope') or {}).get('parts')) or {}
    named = [name for name in (analysis.get('part_names') or ()) if name in parts]
    if not named:
        return False
    if not all(parts[name]['required_mask'].get('kind') == 'color'
               and parts[name]['required_mask'].get('available') for name in named):
        return False
    protected = {other for name in named for other in parts[name]['co_owned_with']}
    return all(name in named or name in protected for name in shared)


def reach(item, indices):
    """What an edit of these live textures changed besides the part it was aimed at (module doc).

    Never a refusal. -> {'also_changed': ["'cap emblem' (same pixels as 'cap', textures [3])"],
    'unmapped_textures': [...], 'note'} with only what applies, {} when there is nothing to say."""
    if not item.get('scope_index') or not indices:
        return {}
    verdict = scope_verdict(item, indices)
    out = {}
    if verdict['shared'] and not _colour_mask_covers(item, verdict['shared']):
        groups = {}
        for name, entry in verdict['shared'].items():
            owners = frozenset({name, *(entry['co_owned_with'] or entry['shares_with'])})
            groups.setdefault(owners, set()).update(entry['texture_indices'])
        out['also_changed'] = [
            (' and '.join(f"'{n}'" for n in sorted(owners)) if len(owners) > 1
             else f"'{next(iter(owners))}' and other geometry")
            + f' (same pixels: textures {sorted(textures)})' for owners, textures in groups.items()]
    if verdict['unresolved']:
        out['unmapped_textures'] = verdict['unresolved']
    if out:
        out['note'] = ' '.join(REACH_NOTES[key] for key in REACH_NOTES if key in out)
    return out


def _close(session_id):
    """Close the renderer and its private copy; the workspace stays for a resume."""
    item = _sessions.pop(session_id)
    if item.get('timer'):
        item['timer'].cancel()
    try:
        item['viewer'].close()
    finally:
        item['scratch'].cleanup()


def _close_all():
    with _lock:
        for session_id in list(_sessions):
            _close(session_id)


atexit.register(_close_all)


def _expire(session_id):
    with _lock:
        item = _sessions.get(session_id)
        if not item:
            return
        remaining = lab_common.IDLE_SECONDS - (time.monotonic() - item['used'])
        if remaining <= 0:
            _close(session_id)
            return
        timer = threading.Timer(remaining, _expire, args=(session_id,))
        timer.daemon = True
        item['timer'] = timer
        timer.start()


def _root(create=False):
    base = config.STORAGE_PATH.resolve()
    root = base / 'assistant' / 'skin_lab'
    if not root.resolve().is_relative_to(base):
        raise ValueError('Invalid Skin Lab workspace location')
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def _workspace(session_id, create=False):
    """The session's workspace (module doc), or None for an id that names none."""
    if not lab_common.workspace_id(session_id):
        return None
    directory = _root(create) / session_id
    if create:
        directory.mkdir(exist_ok=True)
    return directory if directory.is_dir() else None


def keep(session_id, item):
    """Write the resume record: what reopening this session from its last checkpoint needs."""
    directory = _workspace(session_id)
    if directory is None:
        return
    analysis = item.get('palette')
    kept_palette = None
    if analysis is not None:
        if not analysis.get('token'):
            analysis['token'] = lab_common.token()
        arrays = {**{f'o:{key}': value for key, value in analysis['originals'].items()},
                  **{f'm:{key}': value for key, value in analysis['maps'].items()}}
        lab_common.keep_arrays(directory, analysis['token'], arrays)
        # The arrays are written once per analysis; entries can leave it later (a material
        # applied over a texture, texture_material._write), so the record names those still in it.
        kept_palette = {'token': analysis['token'], 'groups': analysis['groups'],
                        'originals': [str(key) for key in analysis['originals']],
                        'maps': [str(key) for key in analysis['maps']],
                        'adjustments': [[index, list(value)] for index, value in analysis['adjustments'].items()],
                        'material_fields': {key: list(value) for key, value in analysis.get('material_fields', {}).items()},
                        **{key: analysis[key] for key in ('mask', 'part_names') if key in analysis}}
    originals = item.get('texture_originals')
    if originals and item.get('texture_originals_token'):
        lab_common.keep_textures(directory, originals, item['texture_originals_token'])
    lab_common.keep(directory, {
        'texture_originals_token': item.get('texture_originals_token') if originals else None,
        'kind': 'costume', 'source_file_id': item['source']['file_id'],
        'checkpoint': item.get('checkpoint'), 'revision': item.get('revision', 0),
        # The texture list the checkpoint reopens with (continuity sets it with each checkpoint).
        'textures': item.get('checkpoint_textures') or lab_common.texture_list(item['viewer']),
        'edited': bool(item.get('edited')), 'hidden_textures': item.get('hidden_textures'),
        'scope': item.get('scope'),
        'source_sha256': item.get('source_sha256'), 'palette': kept_palette,
        'material_baseline': item.get('material_baseline')})


def _resume(session_id, directory, record):
    """A Skin Lab item reopened from the workspace's last checkpoint (lab_common.live)."""
    try:
        _, source_info = mod_files.resolve(record['source_file_id'])
        reopened = (record.get('checkpoint') or {}).get('file_id') or record['source_file_id']
        path, info = mod_files.resolve(reopened)
        analysis = None
        if record.get('palette'):
            kept_palette = record['palette']
            arrays = lab_common.kept_arrays(directory, kept_palette['token'])
            key = lambda text: int(text) if text.isdigit() else text
            analysis = {'originals': {key(name): arrays['o:' + name] for name in kept_palette['originals']},
                        'maps': {key(name): arrays['m:' + name] for name in kept_palette['maps']},
                        'groups': kept_palette['groups'],
                        'adjustments': {int(index): tuple(value) for index, value in kept_palette['adjustments']},
                        'material_fields': {name: tuple(value) for name, value in kept_palette['material_fields'].items()},
                        # Nothing the reopened renderer holds is known yet: the next recolor sends every texture.
                        'live': {}, 'token': kept_palette['token'],
                        **{name: kept_palette[name] for name in ('mask', 'part_names') if name in kept_palette}}
    except (ValueError, KeyError, TypeError, OSError):
        raise ValueError(MISSING)
    scratch = tempfile.TemporaryDirectory(prefix='skin-lab-', dir=mod_files.root())
    viewer = None
    try:
        copy = Path(scratch.name) / source_info['name']
        copy.write_bytes(path.read_bytes())
        viewer = _viewer(copy, source_info)
        if not lab_common.same_textures(viewer, record.get('textures')):
            raise ValueError(MISSING)
    except Exception:
        if viewer:
            viewer.close()
        scratch.cleanup()
        raise
    report = record.get('scope')
    originals, kept_token = {}, record.get('texture_originals_token')
    if kept_token:
        try:
            originals = lab_common.kept_textures(directory, kept_token)
        except (ValueError, OSError):
            kept_token = None          # reset_texture then has nothing to return to; the session still reopens
    return {'texture_originals': originals, 'texture_originals_token': kept_token if originals else None,
            'viewer': viewer, 'scratch': scratch, 'source': source_info, 'used': time.monotonic(),
            'palette': analysis, 'edited': bool(record.get('edited')),
            'hidden_textures': record.get('hidden_textures'),
            'scope': report, 'scope_index': _scope_index(report),
            'source_sha256': record.get('source_sha256'), 'material_baseline': record.get('material_baseline'),
            'checkpoint_textures': record.get('textures'),
            'checkpoint': record.get('checkpoint'), 'revision': record.get('revision', 0)}


def _session(session_id, action=None):
    """The session's item; one that has closed is reopened from its last checkpoint (lab_common.live)."""
    if action == 'close':
        return _sessions.get(session_id)       # nothing to reopen just to close it
    return lab_common.live(sys.modules[__name__], session_id)


def _viewer(path, info):
    """A renderer on the private copy, with the fighter's scene, animations and data when known."""
    from core.viewer_tools import find_available_port, find_scene_file, find_aj_file, find_fighter_data_file
    character = mod_files.origin_of(info).get('character')
    return ViewerSession(config.HSDRAW_EXE, find_available_port(), path,
                         logs_path=config.LOGS_PATH,
                         scene_file=find_scene_file(character) if character else None,
                         aj_file=find_aj_file(character) if character else None,
                         data_file=find_fighter_data_file(character) if character else None,
                         subprocess_kwargs=config.get_subprocess_args())


def _keep_quietly(session_id, item):
    """keep(), for a step that is not a checkpoint: a failed write never fails the edit."""
    try:
        keep(session_id, item)
    except Exception:
        logger.warning('[skin_lab] resume record not written', exc_info=True)


def _preview(item, name='Skin preview.png'):
    return _file(item['viewer'].grab_frame(), name)


def skin_lab_open(file_id):
    """Only opaque registered DATs; never accept model-supplied paths."""
    path, info = mod_files.resolve(file_id)
    if info['extension'] not in {'.dat', '.usd'}:
        raise ValueError('Open a costume DAT from open_vault_file or unpack_mod_file first.')
    roots = mod_files.dat_roots(path)
    if not any(root.startswith('Ply') and root.endswith('_joint') for root in roots):
        raise ValueError('Choose a fighter costume DAT. Use Stage Lab for stages.')
    with _lock:
        lab_common.make_room(sys.modules[__name__])
        scratch = tempfile.TemporaryDirectory(prefix='skin-lab-', dir=mod_files.root())
        viewer = None
        try:
            source = Path(scratch.name) / info['name']
            source.write_bytes(path.read_bytes())
            # The file half of the part scope needs no renderer: built while it starts.
            mapping = {}
            builder = threading.Thread(target=lambda: mapping.update(result=_scope_map(source, info)),
                                       name='skin-lab-scope', daemon=True)
            builder.start()
            try:
                viewer = _viewer(source, info)
            finally:
                builder.join()
            item = {'viewer': viewer, 'scratch': scratch, 'source': info,
                    'used': time.monotonic(), 'palette': None, 'edited': False,
                    'checkpoint_textures': lab_common.texture_list(viewer),
                    'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
            report = _scope_report(source, info, viewer, item, mapping.get('result'))
            item.update(hidden_textures=_hidden_textures(source, info, viewer),
                        scope=report, scope_index=_scope_index(report))
            preview = _preview(item)
        except Exception:
            if viewer:
                viewer.close()
            scratch.cleanup()
            raise
        session_id = uuid.uuid4().hex
        _sessions[session_id] = item
        _expire(session_id)
        try:
            _workspace(session_id, create=True)
            keep(session_id, item)
            from shared.rendering.stage_editor import prune_workspaces
            prune_workspaces(protect=(session_id,), root=_root())
        except Exception:                  # a resume is a convenience, never the open itself
            logger.warning('[skin_lab] no resume record for this session', exc_info=True)
        scope = _scope_summary(item['scope'], item['scope_index'])
        known = known_parts(item)
        if known is not None:
            # One object: a part's texture_indices and its isolation verdict were
            # never separable, and reading them from two places is how a run ends
            # up recolouring the gi with the fur.
            known = {**known, 'scope': scope.get('parts', {}),
                     'unresolved_texture_indices': scope.get('unresolved_texture_indices', []),
                     'colour_from': costume_colours.part_kinds(item)}
        hidden = item['hidden_textures']
        return {'session_id': session_id,
                # Where each texture's colour lives (costume_colours): the rows are copies, not the renderer's list.
                'textures': costume_colours.annotate(item, [dict(t) for t in viewer.textures]),
                'camera': viewer.camera, 'source_file_id': file_id, 'files': [preview],
                **({'hidden_textures': hidden, 'hidden_note': texture_inspection.HIDDEN_NOTE}
                   if hidden and (hidden['lowpoly'] or hidden['alternate']) else {}),
                # Handed over unasked: the exploration rounds this replaces used
                # to happen before the model could name a single part.
                **({'known_parts': known} if known else {}),
                **costume_colours.evidence(item),
                'part_scope': scope,
                'note': 'Private costume copy. ' + (
                    'The parts listed in known_parts are already identified for this costume: '
                    'use those texture_indices directly instead of exploring for them. Explore '
                    'only for something they do not name. '
                    if known and known['source'] == 'vanilla' else
                    'Before targeting a part, check where it is with identify (every surface numbered '
                    'with its texture), texture_sheet or highlight, in live indices. ') +
                        'part_scope says which parts share pixels; an edit reaching beyond its part '
                        'still runs and its result names what else changed (also_changed). ' +
                        'Inspect the rendered result before export. The human editor is separate.'}


def known_parts(item):
    """part_map.describe for this session (its live textures, origin and geometry), or None.

    Looked up once per renderer and texture layout: the open, texture_usage, a palette
    analysis by parts and the colour evidence (costume_colours) all read it."""
    viewer = item['viewer']
    layout = part_map.signature(viewer.textures)
    cached = item.get('known_parts')
    if cached and cached[0] is viewer and cached[1] == layout:
        return cached[2]
    known = part_map.describe(viewer.textures, mod_files.origin_of(item.get('source') or {}), _geometry(viewer, item))
    item['known_parts'] = (viewer, layout, known)
    return known


def _geometry(viewer, item=None):
    """{index: {mapped_triangles, bounds}} for part_map. Which triangles a
    texture covers survives an upscale or a retexture; its size does not, so
    the session's UV layout is read once (lab_common.uv_layout)."""
    try:
        layout = lab_common.uv_layout(item) if item is not None else None
        rows = texture_inspection.texture_usage(viewer, layout=layout)['textures']
    except Exception:   # naming parts is a convenience, never the edit itself
        return None
    return {row['index']: {'mapped_triangles': row.get('mapped_triangles'), 'bounds': row.get('bounds')}
            for row in rows}


def _hidden_textures(source, info, viewer):
    """Low-poly and alternate-model texture indices, read from the fighter's
    Pl<XX>.dat model tables (see shared.rendering.lowpoly); None when unknown."""
    origin = mod_files.origin_of(info)
    character, code = origin.get('character'), origin.get('costume_code') or ''
    if not character:
        return None
    from core.viewer_tools import find_fighter_data_file
    from shared.rendering.lowpoly import hidden_textures
    from shared.rendering.lowpoly_promote import costume_slot_for_code
    data_file = find_fighter_data_file(character)
    if not data_file:
        return None
    return hidden_textures(source, data_file, costume_slot_for_code(character, code[4:6]), viewer.textures)


def refuse_hidden_only(item, indices):
    """An edit aimed ONLY at textures the fighter never shows changes nothing
    visible: say so and name the way out, instead of letting the model conclude
    the render is stale (Ganondorf's low-poly face; Burger King Falco)."""
    hidden = item.get('hidden_textures') or {}
    kinds = {i: k for k in ('lowpoly', 'alternate') for i in hidden.get(k, [])}
    chosen = list(indices or [])
    if chosen and all(i in kinds for i in chosen):
        raise ValueError(f'Textures {sorted(chosen)} are never drawn on the fighter by default '
                         f'({", ".join(sorted(set(kinds[i] for i in chosen)))}): editing them alone changes '
                         'nothing visible. Target the visible part; texture_usage marks hidden textures.')


def _number(value, label, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{label} must be a number in {low}..{high}.')
    return value


def _numeric(value):
    """A numeric string as its number; anything else unchanged."""
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    return value


def _png(pixels):
    output = io.BytesIO()
    Image.fromarray(pixels).save(output, format='PNG')
    return output.getvalue()


def _reset_textures(item, texture_indices):
    """Textures a material or an apply batch wrote back to how they were before its first write
    (lab_common.keep_originals): the named ones, or with none every one of them."""
    from .texture_material import forget_palette
    viewer = item['viewer']
    kept = item.get('texture_originals') or {}
    chosen = list(kept) if texture_indices is None else texture_indices
    live = {t['index'] for t in viewer.textures}
    if not isinstance(chosen, list) or any(type(i) is not int or i not in live for i in chosen):
        raise ValueError('texture_indices must list live texture indices.')
    missing = [i for i in chosen if i not in kept]
    if missing:
        raise ValueError(f'Textures {missing} were not changed by a material or apply in this session '
                         '(a palette recolor is undone by reset_palette).')
    restored = [i for i in chosen if viewer.get_full_texture(i) != kept[i]
                and not np.array_equal(lab_common.pixels(viewer.get_full_texture(i)), lab_common.pixels(kept[i]))]
    lab_common.write_textures(viewer, {i: kept[i] for i in restored})
    if restored:
        forget_palette(item, restored)
        item['edited'] = True
    return {'restored': restored, 'files': [_preview(item, 'Reset skin.png')]}


def skin_lab(session_id, action, max_groups=8, texture_indices=None,
             adjustments=None, texture_index=None, camera=None, material_id=None, field=None, value=None, enabled=None, include_materials=None, page=0,
             parts=None, edits=None, material_ids=None, points=None, name=None):
    """One Skin Lab action. `name` names the result the retexture auto-save keeps when the turn ends
    (randall/recolor/autosave.py reads it from the call's receipt); the action itself ignores it."""
    with _lock:
        item = _session(session_id, action)
        if item is None:
            return {'closed': True}           # already closed
        item['used'] = time.monotonic()
        viewer = item['viewer']
        if action in {'texture_usage', 'texture_sheet', 'highlight', 'identify'}:
            from . import texture_inspection
            if action == 'identify':
                # The reverse lookup, through the Stage Lab's own code: what is drawn where (texture_inspection).
                # Without a camera: front, back (seen in game) and a zoom on the head, in one picture.
                return texture_inspection.identify(item, costume_colours._open_data(item), camera=camera,
                                                   points=points, name='Skin identify map.png', views='costume')
            if action == 'texture_usage':
                # (Only usage repeats the part names; the sheet and highlight never used them.)
                known = known_parts(item)
                usage = texture_inspection.texture_usage(viewer, item.get('hidden_textures'),
                                                         layout=lab_common.uv_layout(item))
                # Repeat the names here too: a session reopened from a checkpoint
                # reaches this without ever seeing skin_lab_open's reply. So is where
                # each colour lives: this is one of the two results the recolor
                # workflow's prepare stage leaves whole for the main model (workflows.py).
                costume_colours.annotate(item, usage['textures'])
                return {**usage, **({'known_parts': {**known, 'colour_from': costume_colours.part_kinds(item)}}
                                    if known else {}),
                        **costume_colours.evidence(item)}
            if action == 'texture_sheet':
                return texture_inspection.texture_sheet(viewer, page, item.get('hidden_textures'))
            return texture_inspection.highlight(item, texture_indices)
        if action in MATERIAL_ACTIONS:
            result = lab_common.material(item, action, material_id, field, value, enabled)
            if action in {'set_material', 'reset_material'}: item['edited'] = True
            if action != 'materials': result['files'] = [_preview(item)]
            return result
        if action in costume_colours.ACTIONS:   # vertex colours and colour keys (costume_colours.py)
            if action in ('recolor_vertex', 'recolor_animated'):
                edits = lab_common.single_kind(action, edits)
            return costume_colours.action(item, action, edits=edits, material_ids=material_ids)
        if action == 'apply':                   # one batch of mixed edits (lab_common.apply_batch)
            if any(v is not None for v in (texture_index, texture_indices, material_ids, adjustments, material_id,
                                           field, value, parts)):
                raise ValueError('apply takes edits alone: each edit carries its own kind, targets and values.')
            return lab_common.apply_batch(item, edits, stage=False)
        if action == 'reset_texture':
            return _reset_textures(item, texture_indices)
        if edits is not None or material_ids is not None:
            raise ValueError('edits and material_ids belong to recolor_vertex, recolor_animated, reset_colors '
                             '.')
        if action == 'close':
            _close(session_id)
            return {'closed': True}
        if action == 'inspect':
            return {'session_id': session_id, 'camera': viewer.camera,
                    'textures': costume_colours.annotate(item, [dict(t) for t in viewer.textures]),
                    'groups': item['palette']['groups'] if item['palette'] else []}
        if action == 'frame' and not camera:
            return {'files': [_preview(item)]}
        # frame with a camera turns it first: ignoring the camera returned the
        # same front view twice in a galaxy-Marth run, which the model then
        # reported as a renderer fault.
        if action in {'camera', 'frame'}:
            if not isinstance(camera, dict) or not camera or set(camera) - {'rot_x', 'rot_y', 'scale', 'x', 'y'}:
                raise ValueError('Use rot_x, rot_y (degrees), scale (zoom), x and y (pan).')
            # Numeric strings ("180") are read as numbers: a galaxy-Marth run
            # sent one twice, and each rejection cost a round.
            camera = {key: _number(_numeric(value), key, 0.1 if key == 'scale' else -1000, 1000)
                      for key, value in camera.items()}
            viewer.set_camera(**camera)
            return {'camera': viewer.camera, 'files': [_preview(item)]}
        indices = {texture['index'] for texture in viewer.textures}
        if action == 'texture':
            if type(texture_index) is not int or texture_index not in indices:
                raise ValueError('Choose a texture index returned by inspection.')
            # Read, not presented. The model still needs the image (vision reads
            # `files`), but a texture pulled to look at is working material, so
            # the UI folds it into the tool row instead of posting a card.
            return {'reading': True, 'texture_index': texture_index, 'session_id': session_id,
                    'files': [_file(viewer.get_full_texture(texture_index), f'Skin texture {texture_index}.png')]}
        if action == 'analyze_palette' and parts is not None:
            if type(max_groups) is not int or not 1 <= max_groups <= 16:
                raise ValueError('Choose 1..16 color groups.')
            if (not isinstance(parts, dict) or not 1 <= len(parts) <= 16 or any(
                    not isinstance(name, str) or not isinstance(chosen, list) or not chosen
                    or any(type(i) is not int or i not in indices for i in chosen)
                    for name, chosen in parts.items())):
                raise ValueError('parts maps 1..16 part names to non-empty lists of live texture indices.')
            pixels_total = 0
            def snapshot(index):
                nonlocal pixels_total
                with Image.open(io.BytesIO(viewer.get_full_texture(index))) as image:
                    pixels_total += image.width * image.height
                    if pixels_total > 16_777_216:
                        raise ValueError('Analyze fewer textures at a time (16 megapixel limit).')
                    return np.array(image.convert('RGBA'))
            # A named part also takes its colour from textures it shares with
            # other detail (Mario's emblem holds the cap red around the M): only
            # its own hues, in their surrounding field, so the M stays as it is.
            # That holds even when the model lists the shared texture under the
            # part itself -- it did, and the whole emblem M went with the cap.
            # Recolouring the M too means naming the emblem as its own part.
            shared = (known_parts(item) or {}).get('masked_parts') or {}
            parts = {name: [i for i in chosen if i not in shared.get(name, [])] or chosen
                     for name, chosen in parts.items()}
            for chosen in parts.values():
                refuse_hidden_only(item, chosen)
            snapshots = {name: {i: snapshot(i) for i in dict.fromkeys(chosen)} for name, chosen in parts.items()}
            named = {i for chosen in parts.values() for i in chosen}
            extras = {name: {i: snapshot(i) for i in shared.get(name, []) if i not in named} for name in parts}
            groups, maps = palette.analyze_parts(snapshots, max_groups, extras=extras)
            originals = {i: px for part in snapshots.values() for i, px in part.items()}
            borrowed = {}
            for name, textures in extras.items():
                for index, px in textures.items():
                    if index in maps and index not in originals:
                        originals[index] = px
                        borrowed.setdefault(name, []).append(index)
            item['palette'] = {'originals': originals, 'maps': maps, 'groups': groups,
                               'adjustments': {}, 'material_fields': {}, 'live': dict(originals),
                               # the supported narrower mask: each part clustered
                               # on its own, a shared texture's other detail kept
                               # out of it: reach() does not report the parts it protects.
                               'mask': 'color', 'part_names': sorted(parts)}
            _keep_quietly(session_id, item)
            return {'groups': groups, 'parts': {n: sorted(s) for n, s in snapshots.items()},
                    **({'borrowed_textures': borrowed} if borrowed else {}),
                    'note': 'One analysis, clustered per part: every group names its part, and a '
                            'single recolor can adjust groups from all parts at once. Adjustments '
                            'are absolute from this snapshot.'}
        if action == 'analyze_palette':
            if type(max_groups) is not int or not 1 <= max_groups <= 16:
                raise ValueError('Choose 1..16 color groups.')
            if include_materials is not None and type(include_materials) is not bool:
                raise ValueError('include_materials must be boolean')
            use_materials = (texture_indices is None) if include_materials is None else include_materials
            chosen = sorted(indices) if texture_indices is None else texture_indices
            if texture_indices is not None:
                refuse_hidden_only(item, texture_indices)
            if not isinstance(chosen, list) or (not chosen and not use_materials) or len(chosen) > 512 or any(type(i) is not int or i not in indices for i in chosen):
                raise ValueError('Choose up to 512 texture indices from inspection, or omit for all.')
            # Full-resolution snapshots first, including animation frames. Later
            # adjustments always use these originals, never the shifted pixels.
            originals = {}
            pixels_total = 0
            for index in dict.fromkeys(chosen):
                with Image.open(io.BytesIO(viewer.get_full_texture(index))) as image:
                    pixels_total += image.width * image.height
                    if pixels_total > 16_777_216:
                        raise ValueError('Analyze fewer textures at a time (16 megapixel limit).')
                    originals[index] = np.array(image.convert('RGBA'))
            fields = {}
            if use_materials:
                samples, fields = palette_snapshot(viewer)
                originals.update(samples)
            groups, maps = palette.analyze(originals, max_groups)
            item['palette'] = {'originals': originals, 'maps': maps, 'groups': groups, 'adjustments': {}, 'material_fields': fields,
                               'live': dict(originals)}
            _keep_quietly(session_id, item)
            return {'groups': groups, 'texture_indices': chosen, 'material_colors': len(fields),
                    'note': 'Group indices apply to this analysis. Adjustments are absolute from this snapshot. '
                            'Lightness is preserved unless lightness_scale is supplied; hue alone cannot turn pale pink into dark brown.'}
        if action in {'recolor', 'reset_palette'}:
            analysis = item['palette']
            if analysis is None:
                raise ValueError('Analyze the palette first.')
            values = dict(analysis['adjustments']) if action == 'recolor' else {}
            if action == 'recolor':
                # A first pass over a whole costume can touch more than 16 groups
                # across its parts; each group can still be named only once.
                if not isinstance(adjustments, list) or not 1 <= len(adjustments) <= 64:
                    raise ValueError('Provide 1..64 group adjustments.')
                # An adjustment without an index means "all of it": every group,
                # or every group present in texture_indices when those are given.
                # A cyberpunk-Samus run sent that three times and was refused.
                if any(isinstance(c, dict) and 'index' not in c for c in adjustments):
                    if len(adjustments) != 1:
                        raise ValueError('Give every adjustment an index, or send ONE adjustment without '
                                         'an index to apply it to every group.')
                    if texture_indices is not None:
                        if not isinstance(texture_indices, list) or any(i not in analysis['maps'] for i in texture_indices):
                            raise ValueError('texture_indices must come from the latest palette analysis.')
                        present = {int(g) for i in texture_indices for g in np.unique(analysis['maps'][i]) if g != 255}
                    else:
                        present = set(range(len(analysis['groups'])))
                    if not present:
                        raise ValueError('Those textures hold no analysed colour groups.')
                    adjustments = [{**adjustments[0], 'index': g} for g in sorted(present)]
                seen = set()
                for change in adjustments:
                    if isinstance(change, dict):
                        # A zero shift changes nothing, so it cannot conflict with a set.
                        change = {k: v for k, v in change.items()
                                  if not (k in ('hue_shift', 'saturation_shift') and v == 0)}
                        # Hue is a circle: a 242 degree shift IS -118 (sent by a
                        # cyberpunk-Samus run and refused).
                        shift = change.get('hue_shift')
                        if type(shift) in (int, float) and math.isfinite(shift):
                            change['hue_shift'] = (shift + 180) % 360 - 180
                    if not isinstance(change, dict) or set(change) - {'index', 'hue_shift', 'saturation_shift',
                                                                      'set_hue', 'set_saturation', 'lightness_scale'}:
                        raise ValueError('Use index with hue_shift/saturation_shift, or set_hue/set_saturation.')
                    index = change.get('index')
                    if type(index) is not int or not 0 <= index < len(analysis['groups']) or index in seen:
                        raise ValueError('Choose unique group indices from the latest palette analysis.')
                    seen.add(index)
                    setting = 'set_hue' in change or 'set_saturation' in change
                    if setting and ('hue_shift' in change or 'saturation_shift' in change):
                        # "This hue, a bit more saturated" has one reading: the
                        # group's own average plus the shift. Rejecting it cost
                        # a round in two of three galaxy-Marth runs.
                        group = analysis['groups'][index]
                        change = dict(change)
                        if 'set_hue' in change and 'saturation_shift' in change and 'set_saturation' not in change:
                            change['set_saturation'] = min(100, max(0, group['avgSaturation'] + _number(
                                change.pop('saturation_shift'), 'Saturation', -100, 100)))
                        if ('set_saturation' in change and 'hue_shift' in change and 'set_hue' not in change
                                and group.get('centerHue') is not None):
                            change['set_hue'] = (group['centerHue'] + _number(
                                change.pop('hue_shift'), 'Hue', -180, 180)) % 360
                        if 'hue_shift' in change or 'saturation_shift' in change:
                            raise ValueError('Use either shifts or set_hue/set_saturation for a group, not both.')
                    if setting:
                        # Colorize outright: a rotation cannot move white or grey,
                        # so this is the only way to recolor unsaturated parts.
                        values[index] = (_number(change.get('set_hue', 0), 'Hue', 0, 360),
                                         _number(change.get('set_saturation', 60), 'Saturation', 0, 100),
                                         'set')
                    else:
                        values[index] = (_number(change.get('hue_shift', 0), 'Hue', -180, 180),
                                         _number(change.get('saturation_shift', 0), 'Saturation', -100, 100))
                    scale = _number(change.get('lightness_scale', 1), 'Lightness scale', 0, 2)
                    values[index] = (*values[index][:2], 'set' if setting else 'shift', scale)
            # Compute everything before writing. Restore all baseline textures too,
            # so setting a group to zero actually undoes its previous adjustment.
            # A texture whose pixels come out as the renderer already holds them (no
            # group it contains changed) is not sent again: a one-group change used to
            # re-encode and re-upload every analysed texture (36 on Fox, about 1 s).
            updated, writes = {}, {}
            live = analysis.setdefault('live', {})
            for index, original in analysis['originals'].items():
                if index in analysis.get('material_fields', {}): continue
                pixels = palette.apply_adjustments(original, analysis['maps'][index], values)
                pixels = original if pixels is None else pixels
                updated[index] = pixels
                if index not in live or not np.array_equal(live[index], pixels):
                    writes[index] = _png(pixels)
            fields = analysis.get('material_fields', {})
            if fields:
                lab_common.material_baseline(item)
                viewer.material_command({'type': 'setMaterialColors', 'edits': palette_edits(analysis['originals'], fields, analysis['maps'], values)})
            lab_common.write_textures(viewer, writes)      # one batch on a protocol-2 renderer
            for index in writes:
                live[index] = updated[index]
            analysis['last_written'] = list(writes)      # what the workbench view needs (continuity)
            analysis['adjustments'] = values
            item['edited'] = True
            # What the edit reached beyond its part: said, never refused (reach, the scope block above).
            reached = reach(item, [i for i, px in updated.items()
                                   if not np.array_equal(px, analysis['originals'][i])]) if action == 'recolor' else {}
            return {'updated_textures': list(updated), 'updated_material_colors': len(fields), 'files': [_preview(item, 'Recolored skin.png')],
                    **{k: v for k, v in reached.items() if k != 'note'},
                    'note': 'Preview the result from other angles before saving. This is not a Slippi test.'
                            + (' ' + reached['note'] if reached else '')}
        if action == 'export':
            if not item['edited']:
                raise ValueError('Make a skin edit before exporting a new copy.')
            info = item['source']
            result = mod_files.register(viewer.export_dat(), info['name'], origin=info.get('origin'), edited=True)
            return {'files': [result], 'note': 'New immutable DAT copy. Use save_mod_copy when asked to add it to the vault; paired climbers must be saved together in Texture Lab.'}
        raise ValueError('Unknown Skin Lab action.')
