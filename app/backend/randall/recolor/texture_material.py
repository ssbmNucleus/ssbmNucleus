"""Generated swatches and masked material edits in Randall's own sessions.

How a material lands on a texture (`compose_material`, shared by skin_material and the
labs' `apply` batch, lab_common.apply_batch):

* **replace** (the default): the selected pixels take the material's own colours. The
  texture's alpha is never touched, so cut-outs (leaf holes, fence gaps) stay; with no
  colour mask the colour channel of the transparent pixels takes the material too, so
  the old colour cannot bleed back in at the cut-out edges when the renderer filters.
  `keep_shading` (0..1, default KEEP_SHADING) lays that much of the original's light and
  dark detail over it (1: the full lum/ref modulation, 0: the flat material).
* **mix** (the look before 2026-10-05, now an explicit option): `strength` (default 0.75)
  of the shaded material over the texture, `keep_shading` default 1. On Dream Land's
  green canopy texture that left a quarter of the green in every pixel: the owner's
  "cotton candy tinted by the green underneath".

A texture can also be tinted by what the renderer multiplies it with: the vertex colours
of the objects drawing it (Dream Land's canopy objects carry #88ff88..#ffffff). The
batch's material edit neutralises those (lab_common), unless told to keep them.
"""
import io
import uuid

import numpy as np
from PIL import Image, ImageDraw

from shared.aiengine.image_api import generate_material_sheet
from shared.rendering import compose, palette
from . import lab_common, swatch_library
from shared import mod_files

MAX_PIXELS = 4_194_304
MAX_PLANS = 32
MAX_PLAN_BYTES = 256 * 1024 * 1024
# Texels one material tile should span on the model for a motif to read, and
# the largest side detail-sizing may grow a texture to.
DETAIL_TEXELS = 128
MAX_DETAIL_SIDE = 256
# Projection samples the swatch at full detail, up to this side.
PROJECT_SWATCH_SIDE = 1024
# One projected swatch tile spans this fraction of the model's bounding-box
# diagonal. The shared default (0.55) put one tile across nearly all of Mario,
# so a motif showed as a magnified fragment; 0.2 (~4 units on Mario) was the
# clearest of a measured 10.6 / 4.0 / 2.5 comparison. The human Skin Lab keeps 0.55.
PROJECT_TILE_FRACTION = 0.2


def _plan_bytes(plans):
    """Count shared array baselines once; never silently invalidate a handle."""
    arrays = {}
    def visit(value):
        if isinstance(value, np.ndarray):
            arrays[id(value)] = value.nbytes
        elif isinstance(value, dict):
            for child in value.values():
                visit(child)
    visit(plans)
    return sum(arrays.values())
MASK_FIELDS = {'hue_min': (0, 360), 'hue_max': (0, 360),
               'sat_min': (0, 100), 'sat_max': (0, 100),
               'lum_min': (0, 100), 'lum_max': (0, 100)}
BLENDS = ('replace', 'mix')
# replace's default share of the original's light/dark detail (module doc): chosen by looking at
# Dream Land's canopy (29) and trunk (25) with candy swatches at 0, 0.25 and 0.5: 0 leaves the chocolate trunk flat,
# 0.5 lays the leaf texture's speckle over the cotton candy; 0.25 keeps a hint of bark and stays the material's colour.
KEEP_SHADING = 0.25
# The controls a material edit takes, as skin_material and the batch's material edit name them.
# None: the default for the session's kind and the blend (`resolve_controls`).
CONTROLS = ('mask', 'mask_files', 'mode', 'tile_size', 'world_scale', 'strength', 'keep_shading', 'blend',
            'minimum_size')


def default_controls(stage):
    """A new material edit's controls: a stage repeats a texture's own tile at its own size."""
    return {'mask': {}, 'mask_files': [], 'mode': 'tile' if stage else 'project', 'tile_size': 32,
            'world_scale': None, 'strength': None, 'keep_shading': None, 'blend': 'replace',
            'minimum_size': 1 if stage else 128}


def resolve_controls(controls):
    """The controls with the blend's defaults filled in (strength, keep_shading)."""
    out = dict(controls)
    replace = out.get('blend', 'replace') == 'replace'
    if out.get('strength') is None:
        out['strength'] = 1.0 if replace else 0.75
    if out.get('keep_shading') is None:
        out['keep_shading'] = KEEP_SHADING if replace else 1.0
    return out


def generate_material(prompt=None, prompts=None, style='swatch', *, _key=None):
    # `prompt` is the original single-material form; older transcripts and
    # continuations still send it.
    if prompts is None:
        prompts = [prompt] if prompt is not None else None
    elif prompt is not None:
        raise ValueError('Send prompts (a list), not both prompt and prompts.')
    pngs, metadata = generate_material_sheet(prompts, key=_key, style=style)
    materials, files = [], []
    for number, (text, png) in enumerate(zip(prompts, pngs), 1):
        file = mod_files.register(png, f'Generated material {number}.png' if len(pngs) > 1
                                  else 'Generated material.png')
        files.append(file)
        materials.append({'prompt': text, 'file_id': file['file_id']})
    swatch_library.record(materials)
    return {**metadata, 'files': files, 'materials': materials, 'reading': True,
            'note': 'Fresh material swatches, one per prompt, in the same order: put them in one skin_lab/stage_lab '
                    'apply as material edits (material_file_id), with the colour edits. Reuse these file IDs '
                    'to change placement, mask or scale without generating again. Seamless tiling is requested, '
                    'not guaranteed.'}


def _pixels(raw):
    with Image.open(io.BytesIO(raw)) as image:
        if image.width * image.height > MAX_PIXELS:
            raise ValueError('Choose images under 4 megapixels for material edits.')
        return np.array(image.convert('RGBA'))


def _file_pixels(file_id):
    path, info = mod_files.resolve(file_id)
    if info['extension'] != '.png':
        raise ValueError('Choose a PNG file ID.')
    return _pixels(path.read_bytes())


def _sheet(plan, name='Material mask preview.png', last_title='Proposed result'):
    """At most eight rows so every selected texture is legible to vision."""
    sheet = Image.new('RGB', (720, 40 + 116 * len(plan['originals'])), '#20252c')
    draw = ImageDraw.Draw(sheet)
    for x, title in ((0, 'Original'), (240, 'Mask (white = change)'), (480, last_title)):
        draw.text((x + 12, 10), title, fill='white')
    for row, (index, original) in enumerate(plan['originals'].items()):
        mask = np.uint8(plan['masks'][index] * 255)
        for col, pixels in enumerate((original, mask, plan['candidate'][index])):
            tile = Image.fromarray(pixels)
            zoom = min(208 / tile.width, 88 / tile.height)
            tile = tile.resize((max(1, round(tile.width * zoom)), max(1, round(tile.height * zoom))),
                               Image.Resampling.NEAREST)
            x, y = col * 240 + 16, 38 + row * 116
            sheet.paste(tile, (x, y), tile if tile.mode == 'RGBA' else None)
            draw.text((x, y + 90), f'Texture {index} | {pixels.shape[1]}x{pixels.shape[0]}', fill='white')
    output = io.BytesIO()
    sheet.save(output, format='PNG')
    return {**mod_files.register(output.getvalue(), name), 'preview_only': True}


def _sheets(plan, **kwargs):
    indices = list(plan['originals'])
    return [_sheet({key: {i: plan[key][i] for i in indices[start:start + 8]}
                    for key in ('originals', 'masks', 'candidate')}, **kwargs)
            for start in range(0, len(indices), 8)]


def _validate_mask(mask):
    from .skin_lab import _number
    if not isinstance(mask, dict) or set(mask) - MASK_FIELDS.keys() - {'surrounding'}:
        raise ValueError('Mask accepts hue_min/max, sat_min/max, lum_min/max and surrounding.')
    if 'surrounding' in mask and type(mask['surrounding']) is not bool:
        raise ValueError('surrounding must be true or false.')
    for key, value in mask.items():
        if key != 'surrounding':
            _number(value, key, *MASK_FIELDS[key])
    for kind in ('sat', 'lum'):
        if mask.get(f'{kind}_min', 0) > mask.get(f'{kind}_max', 100):
            raise ValueError(f'{kind}_min must not exceed {kind}_max.')


def _select(rgba, mask):
    """The colour mask's pixels; with surrounding, only that colour's large
    surrounding field -- the cap red AROUND Mario's emblem, not the red M
    inside it."""
    selected = compose.build_mask(rgba, **{k: v for k, v in mask.items() if k != 'surrounding'})
    return palette.surrounding(selected) if mask.get('surrounding') else selected


def _coverage(item, mask, texture_indices):
    """Find a surface's color in mixed-content textures without editing them."""
    if mask is None and texture_indices is not None:
        # A named part (known_parts) IS its textures: select them whole, exactly
        # as an omitted mask does for preview. Demanding a colour mask here cost
        # a round per part in a measured Aztec-Mario run.
        mask = {}
    elif mask is None:
        raise ValueError('Give a color mask, or texture_indices to select those textures whole.')
    _validate_mask(mask)
    if not mask and texture_indices is None:
        raise ValueError('Coverage needs explicit color mask bounds for the surface being changed.')
    viewer = item['viewer']
    textures = {t['index']: t for t in viewer.textures}
    chosen = list(textures) if texture_indices is None else texture_indices
    if (not isinstance(chosen, list) or not chosen or len(set(chosen)) != len(chosen)
            or any(type(i) is not int or i not in textures for i in chosen)):
        raise ValueError('Choose unique live texture_indices, or omit to scan the costume.')
    plan = {'originals': {}, 'masks': {}, 'candidate': {}}
    matches, skipped, scanned, pixels_total = [], [], [], 0
    for index in chosen:
        texture = textures[index]
        count = texture['width'] * texture['height']
        if len(scanned) >= 128 or pixels_total + count > MAX_PIXELS:
            skipped.append(index)
            continue
        original = _pixels(viewer.get_full_texture(index))
        pixels_total += original.shape[0] * original.shape[1]
        scanned.append(index)
        selected = _select(original, mask)
        if not selected.any():
            continue
        matches.append({'texture_index': index, 'selected_pixels': int(selected.sum()),
                        'fraction': round(float(selected.mean()), 4),
                        'animates': texture.get('animates', -1), 'matAnim': bool(texture.get('matAnim'))})
        if len(plan['originals']) < 32:
            overlay = original.copy()
            overlay[selected, :3] = [255, 0, 255]
            plan['originals'][index] = original
            plan['masks'][index] = selected.astype(float)
            plan['candidate'][index] = overlay
    item['material_coverage'] = {'mask': dict(mask), 'matches': matches}
    return {'reading': True, 'mask': mask, 'matches': matches,
            'scanned_texture_indices': scanned, 'unscanned_texture_indices': skipped,
            'shown_texture_indices': list(plan['originals']),
            'files': _sheets(plan, name='Material coverage preview.png', last_title='Selected surface (magenta)'),
            'note': 'Read-only surface coverage. An eye/ear/face texture may also contain surrounding skin. '
                    'Review each mask: keep iris, white rim, mouth and other intended details protected, '
                    'and include surrounding skin plus matching animation variants in the material preview. '
                    'Matching color alone does not prove the same material. Only the first 32 matches are pictured; '
                    'use texture_indices to inspect additional or unscanned textures. No pixels changed.'}


def _check_current(viewer, plan):
    current = {i: _pixels(viewer.get_full_texture(i)) for i in plan['originals']}
    if any(not np.array_equal(pixels, plan['expected'][i]) for i, pixels in current.items()):
        raise ValueError('These textures changed since this material preview. Create a new preview first.')
    return current


def _write(viewer, values, before, item):
    from .skin_lab import _png
    stale_dimensions = False
    try:
        for index, pixels in values.items():
            viewer.update_texture(index, _png(pixels))
            if _pixels(viewer.get_full_texture(index)).shape != pixels.shape:
                stale_dimensions = True
                raise ValueError('The native viewer has stale texture dimensions.')
    except Exception:
        # Restore even the failed index: a lost reply can follow a successful write.
        restored = True
        for index, pixels in before.items():
            try:
                viewer.update_texture(index, _png(pixels))
            except Exception:
                restored = False
        item['palette'] = None
        if not restored:
            item['edited'] = True
            item['texture_material_plans'] = {}
            raise ValueError('Material update failed and restoration was incomplete. Inspect or reopen this working copy before saving.') from None
        note = ' Update HSDRawViewer before resizing textures; its readback reported stale dimensions.' if stale_dimensions else ''
        raise ValueError('Material update failed; the previous working textures were restored.' + note) from None
    item['edited'] = True
    forget_palette(item, values)


def forget_palette(item, indices):
    """Textures written outside the palette analysis leave it (a costume's palette recolor rewrites
    every texture it holds from its snapshot, which would undo the edit). The rest of it stays usable
    with the same group numbers: clearing it all cost a galaxy-Marth run a failed recolor plus a
    re-analysis round."""
    analysis = item.get('palette')
    if analysis:
        for index in indices:
            analysis['originals'].pop(index, None)
            analysis['maps'].pop(index, None)
            analysis.get('live', {}).pop(index, None)
        if not any(i not in analysis.get('material_fields', {}) for i in analysis['originals']) \
                and not analysis.get('material_fields'):
            item['palette'] = None


def _material_numbers(controls, number):
    if type(controls['minimum_size']) is not int or controls['minimum_size'] not in (1, 32, 64, 128, 256, 512):
        raise ValueError('minimum_size must be 1, 32, 64, 128, 256 or 512.')
    if controls['world_scale'] is not None:
        number(controls['world_scale'], 'world_scale', 0.0001, 10000)
    _validate_mask(controls['mask'])
    if controls.get('blend', 'replace') not in BLENDS:
        raise ValueError("blend must be replace (the material's own colours, the default) or mix.")
    if controls['strength'] is not None:
        number(controls['strength'], 'strength', 0, 1)
    if controls['keep_shading'] is not None:
        number(controls['keep_shading'], 'keep_shading', 0, 1)
    if controls['mode'] not in {'tile', 'project', 'fit'}:
        raise ValueError('mode must be project, fit or tile.')
    if type(controls['tile_size']) is not int or not 2 <= controls['tile_size'] <= 1024:
        raise ValueError('tile_size must be 2..1024 pixels.')


def compose_material(item, stage, originals, material, controls):
    """A material laid over textures (module doc), nothing written -> the plan's arrays and facts.

    `originals` {index: RGBA array} are the textures as they are now; `controls` the edit's
    (default_controls, with what it supplied). -> {'candidate', 'masks', 'controls' (resolved),
    'unprojected', 'enlarged_for_detail', 'world'}. Raises ValueError for a bad control or a mask
    that selects nothing.
    """
    from . import skin_lab as lab
    viewer = item['viewer']
    _material_numbers(controls, lab._number)
    resolved = resolve_controls(controls)
    layouts = {}
    world = controls['world_scale']
    if controls['mode'] == 'project':
        layouts = {entry['index']: entry for entry in lab_common.uv_layout(item)}
        for texture in viewer.textures:
            if texture.get('matAnim') and texture['index'] not in layouts and texture.get('animates') in layouts:
                layouts[texture['index']] = layouts[texture['animates']]
        # A texture with no UV layout (Mario's unmapped button texture) cannot be
        # projected. Tile just that one instead of refusing the whole preview --
        # the model's only move after that refusal was to retry in tile mode.
        unprojected = sorted(i for i in originals if i not in layouts or not layouts[i].get('triangles'))
        world = world or compose.layout_world_scale(list(layouts.values()), fraction=PROJECT_TILE_FRACTION)
    else:
        unprojected = []
    base, detail, axes = {}, {}, {}
    for index, original in originals.items():
        h, w = original.shape[:2]
        factor = 1
        while max(h, w) * factor < controls['minimum_size']:
            factor *= 2
        base[index] = (factor, factor)
        fx = fy = factor
        # Size by DETAIL along EACH axis: keep doubling an axis until one
        # material tile spans DETAIL_TEXELS texels along it. A flat minimum
        # left Mario's 8x8 cap panel at 15 texels per tile, and averaging
        # both axes left Samus's one-way strips starved along the other.
        if index in layouts and index not in unprojected:
            axes[index] = compose.texels_per_tile_axes(layouts[index]['triangles'], w, h, world)
            if axes[index]:
                along_u, along_v = axes[index]
                while along_u * fx < DETAIL_TEXELS and w * fx * 2 <= MAX_DETAIL_SIDE:
                    fx *= 2
                while along_v * fy < DETAIL_TEXELS and h * fy * 2 <= MAX_DETAIL_SIDE:
                    fy *= 2
        detail[index] = (fx, fy)
    # Detail growth is a bonus, never a new way to fail: over the pixel
    # budget, fall back to the plain minimum_size sizing.
    area = lambda factors: sum(p.shape[0] * p.shape[1] * factors[i][0] * factors[i][1]  # noqa: E731
                               for i, p in originals.items())
    factors = detail if area(detail) <= MAX_PIXELS else base
    if stage:
        # Never larger than the slot: a stage file's textures share one memory budget.
        factors = base = {index: (1, 1) for index in originals}
    enlarged_for_detail = {str(i): [originals[i].shape[1] * f[0], originals[i].shape[0] * f[1]]
                           for i, f in factors.items() if f != base[i]}
    working = {}
    for index, original in originals.items():
        h, w = original.shape[:2]
        fx, fy = factors[index]
        # Nearest preserves each protected pixel and alpha exactly over its
        # enlarged footprint; only selected areas receive generated detail.
        working[index] = np.array(Image.fromarray(original).resize((w * fx, h * fy), Image.Resampling.NEAREST))
    if sum(p.shape[0] * p.shape[1] for p in working.values()) > MAX_PIXELS:
        raise ValueError('Select fewer textures or a smaller minimum_size (4 megapixels per edit).')
    files = controls['mask_files']
    if not isinstance(files, list) or len(files) > len(originals):
        raise ValueError('mask_files must list at most one PNG mask per selected texture.')
    spatial = {}
    for entry in files:
        if (not isinstance(entry, dict) or set(entry) != {'texture_index', 'file_id'}
                or type(entry['texture_index']) is not int or entry['texture_index'] not in originals
                or entry['texture_index'] in spatial):
            raise ValueError('Mask files need unique selected texture_index and PNG file_id.')
        pixels = _file_pixels(entry['file_id'])
        if pixels.shape != originals[entry['texture_index']].shape:
            raise ValueError('PNG masks must have the exact target texture dimensions.')
        spatial[entry['texture_index']] = (pixels[..., :3].mean(axis=2) / 255) * (pixels[..., 3] / 255)
        index = entry['texture_index']
        h, w = working[index].shape[:2]
        spatial[index] = np.array(Image.fromarray(spatial[index].astype(np.float32)).resize((w, h), Image.Resampling.NEAREST))
    masks = {}
    for index, original in working.items():
        weights = _select(original, controls['mask']).astype(float)
        masks[index] = weights * spatial.get(index, 1)
    if not any(m.any() for m in masks.values()):
        raise ValueError('The mask selects no pixels. Adjust it before applying.')
    # tile_size is the repeat in PIXELS, a tile-mode idea. Projection spans one
    # swatch per world_scale units, so shrinking the swatch to tile_size first
    # (default 32 px) averaged a whole Aztec motif into one salmon blur before
    # it ever reached the model -- the reason project mode looked broken and
    # GLM kept switching to tile mode, seams and all.
    size = controls['tile_size'] if controls['mode'] == 'tile' else min(max(material.shape[:2]), PROJECT_SWATCH_SIDE)
    if controls['mode'] == 'fit':
        # fit lays the image across each texture ONCE, so it keeps its own
        # aspect and full detail: a banknote stays a banknote. Squaring it
        # to a swatch first is what tile and project need, not this.
        swatch = np.array(Image.fromarray(material).convert('RGB'))
    else:
        swatch = np.array(Image.fromarray(material).convert('RGB').resize((size, size), Image.Resampling.LANCZOS))
    # With no colour mask a replace takes the WHOLE colour channel (alpha untouched): the RGB under a
    # cut-out is what filtering blends into its edge, so the old colour would ring every leaf hole.
    whole = resolved['blend'] == 'replace' and not controls['mask'] and not spatial
    candidate = {}
    ref = sum(compose.masked_lightness(working[i], m > 0) * np.count_nonzero(m)
              for i, m in masks.items()) / sum(np.count_nonzero(m) for m in masks.values())
    kwargs = {'lum_lo': 0.3, 'lum_hi': 1.6, 'shade_amount': resolved['keep_shading']}
    for index, original in working.items():
        selected = masks[index] > 0
        projected = controls['mode'] == 'project' and index not in unprojected
        if projected:
            result = compose.composite_project(original, swatch, selected, layouts[index], world,
                                               shade_ref=ref, **kwargs)
        else:
            result = compose.composite(original, swatch, selected,
                                       mode='fit' if controls['mode'] == 'fit' else 'tile', **kwargs)
        if selected.any() and result is None:
            raise ValueError(f'Could not map the selected pixels for texture {index}. Choose tile mode explicitly.')
        out = original.copy()
        if result is not None:
            alpha = (masks[index] * resolved['strength'])[..., None]
            out[..., :3] = np.rint(original[..., :3] * (1 - alpha) + result[..., :3] * alpha).astype(np.uint8)
        if whole:
            clear = ~selected
            if clear.any():
                if projected:
                    flat = compose.composite_project(original, swatch, clear, layouts[index], world, shade_amount=0)
                    flat = original if flat is None else flat
                else:
                    cover = compose.fit_to if controls['mode'] == 'fit' else compose.tile_to
                    flat = original.copy()
                    flat[..., :3] = np.clip(cover(swatch.astype(np.float64), original.shape), 0, 255).astype(np.uint8)
                out[..., :3][clear] = flat[..., :3][clear]
        candidate[index] = out
    return {'candidate': candidate, 'masks': masks, 'controls': resolved, 'unprojected': unprojected,
            'enlarged_for_detail': enlarged_for_detail, 'world': world}


def skin_material(session_id, action, texture_indices=None, material_file_id=None,
                  mask=None, mask_files=None, mode=None, tile_size=None,
                  world_scale=None, strength=None, shading=None, preview_id=None, minimum_size=None,
                  blend=None, keep_shading=None):
    """Preview snapshots are absolute edit baselines, never cumulative overlays. `shading` is the
    older name of keep_shading."""
    if shading is not None:
        if keep_shading is not None and keep_shading != shading:
            raise ValueError('Send keep_shading (shading is its older name), not both.')
        keep_shading = shading
    controls = (texture_indices, material_file_id, mask, mask_files, mode, tile_size,
                world_scale, strength, keep_shading, minimum_size, blend)
    if action == 'apply' and any(v is not None for v in controls) and (
            preview_id is not None or material_file_id is not None):
        # Apply carrying the material's arguments applies it in one step: the
        # reply's render is the look, and reset (or reset_texture) undoes it. With
        # a preview_id it refines that preview first. A preview is optional.
        def draft(pid):
            return skin_material(session_id, 'preview', texture_indices, material_file_id, mask,
                                 mask_files, mode, tile_size, world_scale, strength, None,
                                 preview_id=pid, minimum_size=minimum_size, blend=blend,
                                 keep_shading=keep_shading)
        try:
            preview = draft(preview_id)
        except ValueError as exc:
            # A new target or swatch cannot refine the old plan, and a replaced
            # plan is gone; with a full set of arguments, draw a fresh one.
            if preview_id is None or material_file_id is None or not any(
                    s in str(exc) for s in ('omit preview_id', 'Choose a preview_id')):
                raise
            preview = draft(None)
        applied = skin_material(session_id, 'apply', preview_id=preview['preview_id'])
        return {**{k: v for k, v in preview.items() if k not in {'files', 'action', 'reading', 'note'}}, **applied}
    from . import skin_lab as lab
    # A Stage Lab session works too (lab_common): there textures keep their own size
    # (a stage file has a memory budget), mode defaults to tile (stage textures repeat
    # across many faces), and greyscale slots, which cannot hold colour, are refused.
    kind, item, lock = lab_common.session(session_id)
    stage = kind == 'stage'
    with lock:
        import time
        item['used'] = time.monotonic()
        viewer = item['viewer']
        if action == 'coverage':
            # Coverage only reads mask and texture_indices. Preview settings
            # (swatch, mode, strength...) are tolerated and ignored: coverage and
            # preview share this tool and models send them by habit. Rejecting
            # them cost a round in an Aztec-Mario run and in two galaxy-Marth runs.
            if isinstance(texture_indices, list):
                lab.refuse_hidden_only(item, texture_indices)
            return _coverage(item, mask, texture_indices)
        plans = item.setdefault('texture_material_plans', {})
        if action in {'apply', 'reset'}:
            if any(v is not None for v in controls):
                raise ValueError('Apply with a preview_id takes only session_id, action and preview_id; '
                                 'or send apply with texture_indices and material_file_id to apply in one step.')
            plan = plans.get(preview_id) if isinstance(preview_id, str) else None
            if plan is None:
                raise ValueError('Choose a preview_id from this session, or send apply with texture_indices and '
                                 'material_file_id to apply in one step.')
            before = _check_current(viewer, plan)
            values = plan['candidate'] if action == 'apply' else plan['originals']
            if action == 'apply':
                lab_common.keep_originals(item, list(values))      # what reset_texture returns to
            _write(viewer, values, before, item)
            # Compare subsequent edits with the viewer's actual working pixels.
            # Its display cache can retain more precision than the saved DAT.
            plan['expected'] = {i: _pixels(viewer.get_full_texture(i)) for i in values}
            # What the apply reached beyond its part, as recolor says it: a mask drawn over a shared
            # texture still writes the whole texture (skin_lab.reach; never a refusal).
            reached = lab.reach(item, list(values)) if action == 'apply' and kind == 'costume' else {}
            return {'preview_id': preview_id, 'action': action, 'updated_textures': list(values),
                    **{k: v for k, v in reached.items() if k != 'note'},
                    'files': [{**lab._preview(item, 'Material edit preview.png'), 'preview_only': True}],
                    'note': 'This render is the result: check it. The saved DAT uses its native color precision '
                            'and may differ slightly. Only the listed texture indices changed; animation variants '
                            'may need their own edit.' + (' ' + reached['note'] if reached else '')}
        if action == 'preview' and isinstance(texture_indices, list):
            lab.refuse_hidden_only(item, texture_indices)
            if stage:
                lab_common.refuse_greyscale(item, [i for i in texture_indices if type(i) is int], 'a material')
        if action != 'preview':
            raise ValueError('Use coverage, preview, apply or reset.')
        if preview_id is not None:
            prior = plans.get(preview_id) if isinstance(preview_id, str) else None
            if prior is None:
                raise ValueError('Choose a preview_id from this session.')
            _check_current(viewer, prior)
            if ((texture_indices is not None and texture_indices != list(prior['originals']))
                    or (material_file_id is not None and material_file_id != prior['material_file_id'])):
                raise ValueError('For a new target or swatch, omit preview_id and create a new preview.')
            material_file_id = prior['material_file_id']
            originals = prior['originals']
            material = prior['material']
            expected = prior['expected']
            # Omitted controls retain their previous values when refining.
            controls = dict(prior['controls'])
        else:
            indices = {t['index'] for t in viewer.textures}
            if (not isinstance(texture_indices, list) or not 1 <= len(texture_indices) <= 32
                    or any(type(i) is not int or i not in indices for i in texture_indices)
                    or len(set(texture_indices)) != len(texture_indices)):
                raise ValueError('Choose 1..32 unique texture indices from Skin Lab inspection.')
            material = _file_pixels(material_file_id)
            originals, total = {}, 0
            for index in texture_indices:
                pixels = _pixels(viewer.get_full_texture(index))
                total += pixels.shape[0] * pixels.shape[1]
                if total > MAX_PIXELS:
                    raise ValueError('Select fewer textures (4 megapixels per edit).')
                originals[index] = pixels
            expected = originals
            controls = default_controls(stage)
        supplied = dict(mask=mask, mask_files=mask_files, mode=mode, tile_size=tile_size, world_scale=world_scale,
                        strength=strength, keep_shading=keep_shading, minimum_size=minimum_size, blend=blend)
        controls.update({k: v for k, v in supplied.items() if v is not None})
        composed = compose_material(item, stage, originals, material, controls)
        candidate, masks = composed['candidate'], composed['masks']
        plan = {'originals': originals, 'material': material, 'masks': masks,
                'candidate': candidate, 'expected': expected, 'controls': controls, 'material_file_id': material_file_id}
        token = uuid.uuid4().hex
        retained = {key: value for key, value in plans.items() if key != preview_id}
        retained[token] = plan
        if len(retained) > MAX_PLANS or _plan_bytes(retained) > MAX_PLAN_BYTES:
            raise ValueError('Material preview storage is full. Refine an existing preview_id instead of creating another. Existing previews are unchanged.')
        overlaps = [{'preview_id': key, 'texture_indices': sorted(set(value['originals']) & set(originals))}
                    for key, value in plans.items() if key != preview_id and set(value['originals']) & set(originals)]
        sheet_files = _sheets(plan)
        if preview_id is not None:
            plans.pop(preview_id)
        plans[token] = plan
        coverage = item.get('material_coverage', {})
        outside = ([row for row in coverage.get('matches', []) if row['texture_index'] not in originals]
                   if coverage.get('mask') == controls['mask'] else [])
        variants = [t['index'] for t in viewer.textures
                    if t.get('matAnim') and t.get('animates') in originals and t['index'] not in originals]
        return {'preview_id': token, 'session_id': session_id, 'material_file_id': material_file_id,
                'texture_indices': list(originals), 'reading': True, 'files': sheet_files,
                'controls': composed['controls'],
                'overlapping_previews': overlaps,
                'unselected_mask_matches': outside, 'unselected_animation_variants': variants,
                'dimensions': {str(i): {'original': [p.shape[1], p.shape[0]],
                                      'proposed': [candidate[i].shape[1], candidate[i].shape[0]]} for i, p in originals.items()},
                'tiled_without_uv_layout': composed['unprojected'], 'enlarged_for_detail': composed['enlarged_for_detail'],
                'world_scale': composed['world'], 'selected_pixels': {str(i): int(np.count_nonzero(m)) for i, m in masks.items()},
                'note': 'Optional preview: original, mask and proposed result; nothing changed yet. Apply this preview_id, '
                        'or refine it with preview_id plus changed controls (same baseline and swatch). '
                        'Overlapping previews share textures: applying one makes the others stale. '
                        'Tiny canvases are enlarged for material detail; reset restores original dimensions. '
                        'Alpha and protected pixels are preserved. '
                        'Review unselected mask matches and animation variants before claiming the whole surface is covered. '
                        'Color masks do not understand logos or stitching; protect them with PNG masks.'}
