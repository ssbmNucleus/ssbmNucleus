"""Canonical identity for a costume's textures, and the parts they carry.

Three index spaces describe the same texture and none of them IS the texture:

  * the FACADE index -- ``(node, texture_index)`` from ``modfile.list_textures``,
    a depth-first JOBJ/DOBJ/TOBJ walk of the DAT;
  * the VIEWER index -- HSDRawViewer's ``GetTextureList()`` ordinal, which
    de-duplicates TOBJs that share one backing image array, so 77 facade
    entries collapse to 10 viewer entries on the Goku Fox costume;
  * the DAT-walk ordinal -- the facade index flattened across roots.

``shared/rendering/part_map.py`` is authored in the VIEWER space. The facade only ever
spoke the facade space. Translating between them by position is how a recolour
lands on the gauntlets while the report calls them arms, so every texture here
gets an identity that is neither ordinal:

    texture_id = sha256(source DAT sha256 | HSD_Image offset)

The HSD_Image struct offset is the image DESCRIPTOR, and it is file-wide: one
descriptor is ONE record however many roots, meshes or palettes reach it. Two
descriptors that happen to decode to identical pixels are NOT the same texture
(Melee models carry byte-identical duplicates across LODs, and an edit aimed at
one of them can land entirely on a hidden copy). Every ordinal is an ALIAS.

What the report says about an edit, and how strong each claim is:

  * ``shared_storage`` (DEMONSTRATED, from the file) -- descriptors whose pixel
    data lives at ONE offset, or whose palette does. Editing one edits them all.
  * ``co_owned`` (DEMONSTRATED, from the part map) -- one descriptor named by
    two parts, e.g. Mario's cap emblem sits in a texture the cap also uses.
  * ``overlapping_texels`` (NOT MEASURED) -- whether two parts read the SAME
    texels of a shared image. That needs a per-mesh UV mask, and the renderer's
    ``getUVLayout`` pools triangles per image across every mesh that samples it.
    Shared storage is therefore never reported as proof of overlapping texels.
  * ``duplicate_content`` -- descriptors with their own storage but identical
    encoded bytes. The DAT writer treats them separately; the VIEWER edits them
    together (``RenderJObj.UpdateTexture`` matches TOBJs by content), so the two
    paths disagree and the report says so.

Where the evidence runs out the answer is ``unresolved``, never a guess: an
unidentified part gets ``scope='unresolved'`` and a stop, not a texture index.
"""
import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

IDENTITY_VERSION = 'part-identity/2'

#: Names a caller may use for a part the authored map spells differently. Only
#: pairs that are the same surface on a Melee fighter -- a fox's hair IS its
#: fur, which is exactly why "recolour the hair" cannot mean "the head only".
PART_SYNONYMS = {
    'hair': ('hair', 'fur', 'head fur'),
    'fur': ('fur', 'hair'),
    'coat': ('jacket', 'coat'),
    'jacket': ('jacket', 'coat'),
    'shoes': ('boots', 'shoes'),
    'boots': ('boots', 'shoes'),
    'skin': ('skin', 'fur', 'body'),
    'shirt': ('undershirt', 'shirt'),
    'trousers': ('pants', 'trousers'),
    'pants': ('pants', 'trousers'),
    'eye': ('eyes', 'eye'),
    'eyes': ('eyes', 'eye'),
    'mouth': ('mouth', 'teeth'),
}

SHARED_STOP = ('{part} and {others} read the same image. '
               'Recolor both, choose a supported narrower mask, or stop.')

UNRESOLVED_STOP = ('This costume does not say which texels are {part}: nothing in the vanilla '
                   'part map fits its texture layout. Identify the part with one highlight '
                   'before editing, or choose a scope explicitly. Do not edit a whole texture '
                   'on the strength of a guess.')

#: Why no relationship here is ever reported as "the same affected texels".
OVERLAP_UNMEASURED = ('unmeasured: the renderer pools UV triangles per image across every mesh '
                      'that samples it, so which texels belong to which part is not available')


def _sha(*parts):
    digest = hashlib.sha256()
    for part in parts:
        digest.update(str(part).encode('utf-8'))
        digest.update(b'\x1f')
    return digest.hexdigest()


# --------------------------------------------------------------------------- #
# the DAT walk                                                                #
# --------------------------------------------------------------------------- #
def _model_roots(dat):
    """Roots the facade walks: model joints, never matanim/shapeanim banks."""
    return [(name, offset) for name, offset in dat.roots
            if name.endswith('_joint') and 'matanim' not in name and 'shapeanim' not in name]


def _walk_material_tobjs(dat, root_offset):
    """Every material TOBJ under one root, in the facade's own order.

    Mirrors ``shared.mod_files.texture_inventory`` step for step -- the
    facade's ``texture_index`` IS this loop's counter, so the two cannot drift.
    Yields ``(texture_index, jobj_index, dobj_index, tobj_slot, tobj_offset)``.
    """
    steps = 0

    def pointer(offset):
        nonlocal steps
        steps += 1
        if steps > 50000 or not 0 <= offset <= dat.data_size - 4:
            raise ValueError('The DAT texture tree is invalid or too large to inspect.')
        value = dat.ptr(offset)
        if value is not None and not 0 <= value < dat.data_size:
            raise ValueError('The DAT texture tree contains an invalid pointer.')
        return value

    pending, seen, index, joint_index = [root_offset], set(), 0, -1
    while pending:
        joint = pending.pop()
        if joint is None or joint in seen:
            continue
        seen.add(joint)
        joint_index += 1
        pending.extend([pointer(joint + 0x0c), pointer(joint + 0x08)])
        if dat.u32(joint + 4) & ((1 << 14) | (1 << 5)):
            continue
        dobj = pointer(joint + 0x10)
        dobj_index, seen_dobjs = 0, set()
        while dobj is not None:
            if dobj in seen_dobjs:
                raise ValueError('The DAT has a cyclic mesh list.')
            seen_dobjs.add(dobj)
            material = pointer(dobj + 8)
            tobj = pointer(material + 8) if material is not None else None
            slot, seen_tobjs = 0, set()
            while tobj is not None:
                if tobj in seen_tobjs:
                    raise ValueError('The DAT has a cyclic texture list.')
                seen_tobjs.add(tobj)
                if pointer(tobj + 0x4c) is not None:
                    yield index, joint_index, dobj_index, slot, tobj
                    index += 1
                slot += 1
                tobj = pointer(tobj + 4)
            dobj = pointer(dobj + 4)
            dobj_index += 1


def _palette(dat, tlut_offset):
    """One TOBJ's palette binding, or ``None``. A binding of the TOBJ, never of
    the image: the same image can be drawn through two different TLUTs."""
    if not tlut_offset:
        return None
    from shared.rendering.datprobe import TLUT_FMT
    tlut = dat.tlut_at(tlut_offset)
    return {'tlut_offset': tlut.offset, 'tlut_data_offset': tlut.data_offset,
            'tlut_format': TLUT_FMT.get(tlut.format), 'tlut_colors': tlut.count,
            '_data': tlut.data, '_tlut': tlut}


def _new_record(dat, image_offset):
    from shared.rendering.datprobe import TEX_FMT
    image = dat.image_at(image_offset)
    return {
        'nodes': [], 'root_numbers': [], 'kind': None,
        'width': image.width, 'height': image.height,
        'format': TEX_FMT.get(image.format, f'unknown({image.format})'),
        'format_id': image.format,
        'descriptor': {'image_offset': image.offset, 'data_offset': image.data_offset},
        'palettes': [], 'facade': [], 'usages': [], 'viewer_index': None,
        '_image': image,
    }


def _bind(record, node, root_number, kind, palette, usage):
    if node not in record['nodes']:
        record['nodes'].append(node)
    if root_number is not None and root_number not in record['root_numbers']:
        record['root_numbers'].append(root_number)
    record['kind'] = record['kind'] or kind
    if palette is not None and not any(p['tlut_offset'] == palette['tlut_offset']
                                       for p in record['palettes']):
        record['palettes'].append(palette)
    usage['palette'] = ({'tlut_offset': palette['tlut_offset'],
                         'tlut_data_offset': palette['tlut_data_offset']}
                        if palette else None)
    record['usages'].append(usage)


# --------------------------------------------------------------------------- #
# identity map                                                                #
# --------------------------------------------------------------------------- #
def build_map(path, origin=None):
    """The canonical texture map of one costume DAT, read from the file alone.

    No viewer is started: every identity, alias and sharing relationship here is
    a property of the bytes. ``attach_viewer`` adds the live UV layout on top.
    """
    from shared.rendering.datprobe import DatFile
    path = Path(path)
    dat = DatFile(path)
    source_sha = hashlib.sha256(dat.raw).hexdigest()

    textures, by_image, order = [], {}, []

    def record_for(image_offset):
        record = by_image.get(image_offset)
        if record is None:
            record = _new_record(dat, image_offset)
            record['texture_id'] = 'tex:' + _sha(source_sha, image_offset)[:16]
            by_image[image_offset] = record
            textures.append(record)
            order.append(record)
        return record

    for root_number, (name, offset) in enumerate(_model_roots(dat)):
        for index, jobj, dobj, slot, tobj in _walk_material_tobjs(dat, offset):
            record = record_for(dat.ptr(tobj + 0x4c))
            _bind(record, name, root_number, 'material', _palette(dat, dat.ptr(tobj + 0x50)),
                  {'kind': 'material', 'node': name, 'jobj_index': jobj, 'dobj_index': dobj,
                   'tobj_slot': slot, 'texture_index': index})
            record['facade'].append({'node': name, 'texture_index': index})

    for name, offset in dat.roots:
        if not name.endswith('_joint') or 'matanim' not in name:
            continue
        for anim in dat.matanim_texanims(offset):
            for frame, image in enumerate(anim.images):
                tlut = anim.tluts[frame] if frame < len(anim.tluts) else None
                record = record_for(image.offset)
                _bind(record, name, None, 'matanim', _palette(dat, tlut.offset if tlut else None),
                      {'kind': 'matanim', 'node': name, 'joint_index': anim.joint_index,
                       'matanim_index': anim.matanim_index, 'texmap_id': anim.texmap_id,
                       'frame': frame})

    for record in textures:
        image = record['_image']
        record['data_sha256'] = hashlib.sha256(image.data or b'').hexdigest()
        palette_bytes = b''.join(sorted(p['_data'] or b'' for p in record['palettes']))
        record['content_sha256'] = hashlib.sha256((image.data or b'') + palette_bytes).hexdigest()
        # Physical storage is a property of the FILE, not of a root: an image
        # reached from two roots is one copy of the pixels either way.
        record['texel_group'] = 'texels:' + _sha(source_sha,
                                                 record['descriptor']['data_offset'])[:16]
        record['content_group'] = 'content:' + record['data_sha256'][:16]
        record['palette_groups'] = ['tlut:' + _sha(source_sha, p['tlut_data_offset'])[:16]
                                    for p in record['palettes']
                                    if p['tlut_data_offset'] is not None]
        record['dat_walk_ordinals'] = [f['texture_index'] for f in record['facade']]

    _predict_viewer_indices(textures, order)
    return {
        'mapping_version': IDENTITY_VERSION,
        'source': {'path': str(path), 'sha256': source_sha,
                   'roots': [name for name, _ in dat.roots],
                   'character': (origin or {}).get('character'),
                   'costume_code': (origin or {}).get('costume_code')},
        'textures': textures,
        'viewer': 'predicted',
        'origin': dict(origin or {}),
        'parts': {},
    }


def _predict_viewer_indices(textures, order):
    """Reproduce ``RenderJObj.GetTextureList()``'s de-duplication offline.

    The viewer keeps a ``HashSet<byte[]>`` of the image arrays it has listed and
    HSDRaw hands back ONE array per pixel-data offset, so material TOBJs collapse
    by data offset in walk order. MatAnim frames whose encoded bytes already
    appear are skipped and the rest appended; extra (non-rendered) roots come
    last. Predicted only -- ``reconcile_viewer`` confirms it against a live list.
    """
    index, seen_texels, seen_data = 0, set(), set()
    for record in order:
        if 0 not in record['root_numbers'] or record['texel_group'] in seen_texels:
            continue
        seen_texels.add(record['texel_group'])
        seen_data.add(record['data_sha256'])
        record['viewer_index'] = index
        index += 1
    for record in textures:
        if record['kind'] != 'matanim' or record['data_sha256'] in seen_data:
            continue
        seen_data.add(record['data_sha256'])
        record['viewer_index'] = index
        index += 1
    for record in order:                          # extra (non-rendered) roots
        if record['viewer_index'] is not None or record['data_sha256'] in seen_data:
            continue
        seen_data.add(record['data_sha256'])
        record['viewer_index'] = index
        index += 1
    for record in textures:
        # The part map is authored against THIS enumeration, so it is kept for
        # good: a live session's ordering is one more alias, never the key.
        record['predicted_viewer_index'] = record['viewer_index']
        record.setdefault('alias_confidence', 'predicted')


#: Two decoders of the same GX texture disagree by a bit: this module expands
#: 5-bit channels as ``v * 255 // 31`` and the renderer as ``v << 3 | v >> 2``,
#: which is off by one on most colours. Content identity has to survive that
#: and nothing more -- a real recolour moves channels by far more than 2.
DECODE_TOLERANCE = 2


def decoded_pixels(record):
    """The texture's own decoded RGBA pixels, or ``None`` when undecodable."""
    if '_decoded' in record:
        return record['_decoded']
    import numpy as np

    from shared.rendering.datprobe import decode_image
    tlut = record['palettes'][0]['_tlut'] if record['palettes'] else None
    try:
        pixels = np.asarray(decode_image(record['_image'], tlut), dtype=np.uint8)
    except Exception as exc:                        # naming a texture is never the edit
        logger.debug('[part_identity] cannot decode %s: %s', record['texture_id'], exc)
        pixels = None
    record['_decoded'] = pixels
    return pixels


def same_picture(live, record):
    """Do a viewer's pixels and a descriptor's own pixels show one image?

    Channel order is a transport detail -- the renderer decodes to BGRA and the
    PNG travels through two libraries -- so a red/blue swap still counts as the
    same texture, while a different texture does not. An undecodable descriptor
    answers ``None``: unknown, which is not a match.
    """
    import numpy as np
    mine = decoded_pixels(record)
    if mine is None or live is None or mine.shape != live.shape:
        return None
    for candidate in (mine, mine[..., [2, 1, 0, 3]]):
        if int(np.abs(candidate.astype(np.int16) - live.astype(np.int16)).max()) <= DECODE_TOLERANCE:
            return True
    return False


def _viewer_pixels(png_bytes):
    from io import BytesIO

    import numpy as np
    from PIL import Image as PILImage
    with PILImage.open(BytesIO(png_bytes)) as image:
        rgba = image.convert('RGBA')
        return np.asarray(rgba, dtype=np.uint8), (image.width, image.height)


class DetachedViewer:
    """A finished session's lists, in the shape ``attach_viewer`` reads.

    Lets a caller reconcile against a viewer that has already been closed -- and
    lets a test present a deliberately REORDERED list without a renderer.
    """

    def __init__(self, textures, uv_layout=None, pixels=None):
        self.textures = list(textures)
        self._layout = list(uv_layout or [])
        self._pixels = dict(pixels or {})

    @property
    def has_pixels(self):
        return bool(self._pixels)

    def get_uv_layout(self):
        return self._layout

    def get_full_texture(self, index):
        if index not in self._pixels:
            raise KeyError(f'no pixels captured for viewer texture {index}')
        return self._pixels[index]


# --------------------------------------------------------------------------- #
# viewer reconciliation                                                       #
# --------------------------------------------------------------------------- #
def reconcile_viewer(mapping, viewer_textures, get_full_texture=None):
    """Bind the live viewer's ordinals to canonical ids, by CONTENT.

    The viewer's list order is an implementation detail of whichever build
    answered, so a deliberately reordered list must still land on the right
    facade textures. Each live entry is matched to the candidate whose decoded
    pixels and dimensions agree.

    An association is made only when it is UNIQUE. Two duplicate-looking
    descriptors both match, and content cannot tell them apart, so neither is
    bound: the entry comes back ``ambiguous`` with its candidates listed. The
    same holds when the pixels contradict every candidate (``unmatched``) --
    there is no fall back to "same size, close enough", because a wrong alias is
    how an edit lands on a hidden LOD copy.

    The real repair is upstream: the ``textureList`` message should carry the
    TOBJ's HSD_Image offset, and then no content guessing is needed at all.
    Until the renderer exposes it, ambiguity stays ambiguity.

    Returns the bindings and rewrites each record's ``viewer_index`` in place.
    """
    predicted = {r['texture_id']: r['predicted_viewer_index'] for r in mapping['textures']}
    candidates = [r for r in mapping['textures'] if predicted[r['texture_id']] is not None]
    for record in mapping['textures']:
        record['viewer_index'] = None
        record['alias_confidence'] = 'facade-only'

    bindings, taken = [], set()
    for entry in viewer_textures:
        live = entry['index']
        size = (entry.get('width'), entry.get('height'))
        pixels = None
        if get_full_texture is not None:
            try:
                pixels, size = _viewer_pixels(get_full_texture(live))
            except Exception as exc:
                logger.warning('[part_identity] viewer texture %s unreadable: %s', live, exc)
        free = [r for r in candidates if r['texture_id'] not in taken
                and (r['width'], r['height']) == size]
        if pixels is None:
            fits, confidence = free, 'size'
        else:
            fits = [r for r in free if same_picture(pixels, r)]
            confidence = 'content' if fits else 'unmatched'
        if len(fits) != 1:
            bindings.append({'viewer_index': live, 'texture_id': None,
                             'alias_confidence': 'ambiguous' if fits else confidence,
                             'candidates': [r['texture_id'] for r in fits],
                             'reason': ('several descriptors decode to this image and the viewer '
                                        'transport does not carry which one it listed'
                                        if fits else
                                        'no descriptor in this DAT decodes to what the viewer '
                                        'returned for this index')})
            continue
        chosen = fits[0]
        taken.add(chosen['texture_id'])
        chosen['viewer_index'] = live
        chosen['alias_confidence'] = confidence
        bindings.append({'viewer_index': live, 'texture_id': chosen['texture_id'],
                         'alias_confidence': confidence, 'candidates': [], 'reason': None})
    mapping['viewer_bindings'] = bindings
    mapping['viewer'] = 'session'
    return bindings


def attach_viewer(mapping, viewer):
    """Reconcile against a live ``ViewerSession`` and collect its UV masks."""
    getter = viewer.get_full_texture if getattr(viewer, 'has_pixels', True) else None
    reconcile_viewer(mapping, viewer.textures, getter)
    by_viewer = {r['viewer_index']: r for r in mapping['textures']
                 if r['viewer_index'] is not None}
    try:
        layout = viewer.get_uv_layout()
    except Exception as exc:
        logger.warning('[part_identity] no UV layout: %s', exc)
        layout = []
    for entry in layout:
        record = by_viewer.get(entry.get('index'))
        if record is None:
            continue
        triangles = entry.get('triangles') or []
        record['uv_mask'] = {
            'available': bool(triangles), 'triangles': len(triangles),
            'wrap_s': entry.get('wrapS'), 'wrap_t': entry.get('wrapT'),
            'scope': 'whole-image',
            'per_part': False,
            'note': 'UV triangles for the whole image, pooled across every mesh that samples '
                    'it. This cannot say which texels belong to which part, so it cannot '
                    'split a shared image.'}
    mapping['geometry'] = {r['predicted_viewer_index']:
                           {'mapped_triangles': r['uv_mask']['triangles'], 'bounds': None}
                           for r in mapping['textures']
                           if r.get('uv_mask') and r.get('predicted_viewer_index') is not None}
    return mapping


# --------------------------------------------------------------------------- #
# parts                                                                       #
# --------------------------------------------------------------------------- #
def vocabulary(character):
    """Every part name the authored map uses for this character, unplaced."""
    from shared.rendering import part_map
    names = []
    for entry in part_map._load().values():
        if character and entry.get('character') != character:
            continue
        for name in list(entry.get('groups') or {}) + list(entry.get('masked') or {}):
            if name not in names:
                names.append(name)
    return names


def viewer_texture_list(mapping):
    """The canonical viewer list, in the shape ``part_map.describe`` reads it.

    Always the PREDICTED enumeration -- ``vanilla_parts.json`` was authored
    against it, and a live session that lists the same textures in another
    order must not change which one is the scarf.
    """
    rows = [r for r in mapping['textures'] if r.get('predicted_viewer_index') is not None]
    rows.sort(key=lambda r: r['predicted_viewer_index'])
    return [{'index': r['predicted_viewer_index'], 'width': r['width'], 'height': r['height'],
             'matAnim': r['kind'] == 'matanim', 'animates': -1} for r in rows]


def label_parts(mapping, geometry=None):
    """Named parts from ``shared.rendering.part_map``, translated into canonical ids."""
    from shared.rendering import part_map
    known = part_map.describe(viewer_texture_list(mapping), mapping.get('origin'),
                              geometry if geometry is not None else mapping.get('geometry'))
    mapping['vocabulary'] = vocabulary((mapping.get('origin') or {}).get('character'))
    if not known:
        mapping['parts'] = {}
        mapping['unresolved_reason'] = (
            'No vanilla part map matches this costume: its texture layout is not that of any '
            'vanilla slot of this character (a restructured model port rather than a retexture).')
        return mapping['parts']
    by_viewer = {r['predicted_viewer_index']: r for r in mapping['textures']
                 if r.get('predicted_viewer_index') is not None}
    by_texels = {}
    for record in mapping['textures']:
        by_texels.setdefault(record['texel_group'], []).append(record)

    def resolve(indices):
        """A viewer index addresses ONE copy of the pixels, so it names every
        descriptor that reads it -- all 17 of the Goku atlas, not the first."""
        ids = []
        for index in indices:
            record = by_viewer.get(index)
            if record is None:
                continue
            for sibling in by_texels[record['texel_group']]:
                if sibling['texture_id'] not in ids:
                    ids.append(sibling['texture_id'])
        return ids

    provenance = 'vanilla' if known.get('source') == 'vanilla' else 'likely'
    parts = {}
    for name, indices in (known.get('parts') or {}).items():
        ids = resolve(indices)
        if ids:
            parts[name] = {'texture_ids': ids, 'provenance': provenance, 'masked': False}
    for name, indices in (known.get('masked_parts') or {}).items():
        ids = resolve(indices)
        if not ids:
            continue
        entry = parts.setdefault(name, {'texture_ids': [], 'provenance': provenance,
                                        'masked': False})
        entry['masked'] = True
        entry['masked_texture_ids'] = ids
    mapping['parts'] = parts
    mapping['unresolved_reason'] = None if parts else 'The part map named nothing on this costume.'
    return parts


def _groups(mapping, key, many=False):
    """Records by group id. ``many``: the field is already a list of group ids."""
    buckets = {}
    for record in mapping['textures']:
        value = record.get(key)
        for group in (value or []) if many else ([value] if value else []):
            buckets.setdefault(group, []).append(record)
    return buckets


def describe(mapping, part=None):
    """Turn a canonical map into the report ``modfile.describe_parts`` returns."""
    parts = mapping.get('parts') or {}
    texels = _groups(mapping, 'texel_group')
    palettes = _groups(mapping, 'palette_groups', many=True)
    contents = _groups(mapping, 'content_group')
    owner = {}
    for name, entry in parts.items():
        for texture_id in entry['texture_ids'] + entry.get('masked_texture_ids', []):
            owner.setdefault(texture_id, []).append(name)

    def facade_of(records):
        return [f for record in records for f in record['facade']]

    def sort_key(record):
        first = record['facade'][0] if record['facade'] else None
        return (0, first['node'], first['texture_index']) if first else (1, record['nodes'][0], 0)

    textures = []
    for record in sorted(mapping['textures'], key=sort_key):
        group = texels[record['texel_group']]
        same_content = contents[record['content_group']]
        palette_partners = []
        for palette_group in record['palette_groups']:
            for other in palettes[palette_group]:
                if other['texture_id'] != record['texture_id'] \
                        and other['texture_id'] not in palette_partners:
                    palette_partners.append(other['texture_id'])
        textures.append({
            'texture_id': record['texture_id'],
            'facade': list(record['facade']),
            'nodes': list(record['nodes']),
            'viewer_index': record['viewer_index'],
            'predicted_viewer_index': record.get('predicted_viewer_index'),
            'dat_walk_ordinals': record['dat_walk_ordinals'],
            'alias_confidence': record.get('alias_confidence', 'predicted'),
            'kind': record['kind'],
            'width': record['width'], 'height': record['height'], 'format': record['format'],
            'descriptor': dict(record['descriptor']),
            'palettes': [{k: v for k, v in p.items() if not k.startswith('_')}
                         for p in record['palettes']],
            'content_sha256': record['content_sha256'],
            'groups': {'texels': record['texel_group'], 'content': record['content_group'],
                       'palettes': list(record['palette_groups'])},
            'usages': list(record['usages']),
            'shares_texels_with': [r['texture_id'] for r in group
                                   if r['texture_id'] != record['texture_id']],
            'shares_palette_with': palette_partners,
            'duplicate_content_of': [r['texture_id'] for r in same_content
                                     if r['texture_id'] != record['texture_id']
                                     and r['texel_group'] != record['texel_group']],
            'parts': owner.get(record['texture_id'], []),
            'uv_mask': record.get('uv_mask'),
            **({'previous_texture_id': record['previous_texture_id']}
               if record.get('previous_texture_id') else {}),
        })

    by_id = {t['texture_id']: t for t in textures}
    named = {name: _part_scope(name, entry, by_id, owner) for name, entry in parts.items()}

    report = {
        'mapping_version': mapping['mapping_version'],
        'source': dict(mapping['source']),
        'viewer': mapping.get('viewer', 'predicted'),
        'textures': textures,
        'parts': named,
        'shared_texels': [
            {'group': group, 'texture_ids': [r['texture_id'] for r in records],
             'facade_indices': facade_of(records),
             'nodes': sorted({n for r in records for n in r['nodes']}),
             'viewer_indices': sorted({r['viewer_index'] for r in records
                                       if r['viewer_index'] is not None}),
             'meshes': sum(len(r['usages']) for r in records),
             'parts': sorted({n for r in records for n in owner.get(r['texture_id'], [])}),
             'overlapping_texels': OVERLAP_UNMEASURED}
            for group, records in texels.items() if len(records) > 1],
        'shared_palettes': [
            {'group': group, 'texture_ids': [r['texture_id'] for r in records],
             'facade_indices': facade_of(records),
             'nodes': sorted({n for r in records for n in r['nodes']}),
             'parts': sorted({n for r in records for n in owner.get(r['texture_id'], [])}),
             'usages': sum(1 for r in records for u in r['usages']
                           if (u.get('palette') or {}).get('tlut_data_offset') is not None)}
            for group, records in palettes.items() if len(records) > 1],
        'shared_descriptors': [
            {'texture_id': r['texture_id'], 'facade_indices': list(r['facade']),
             'nodes': list(r['nodes']), 'meshes': len(r['usages']),
             'palettes': len(r['palettes']),
             'parts': owner.get(r['texture_id'], [])}
            for r in mapping['textures'] if len(r['usages']) > 1],
        'multi_palette_images': [
            {'texture_id': r['texture_id'], 'facade_indices': list(r['facade']),
             'palettes': [{k: v for k, v in p.items() if not k.startswith('_')}
                          for p in r['palettes']],
             'note': 'One image drawn through more than one palette: a palette-level recolour '
                     'changes only the uses bound to that TLUT.'}
            for r in mapping['textures'] if len(r['palettes']) > 1],
        'duplicate_content': [
            {'group': group, 'texture_ids': [r['texture_id'] for r in records],
             'facade_indices': facade_of(records),
             'note': 'Separate storage, identical encoded bytes: the DAT writer edits these one '
                     'at a time, the viewer edits them together.'}
            for group, records in contents.items()
            if len({r['texel_group'] for r in records}) > 1],
        'uv_masks': [{'texture_id': t['texture_id'], **t['uv_mask']}
                     for t in textures if t['uv_mask']],
        'unresolved': {
            'texture_ids': [t['texture_id'] for t in textures if not t['parts']],
            'reason': mapping.get('unresolved_reason'),
            'vocabulary': mapping.get('vocabulary') or [],
            'aliases': [b for b in (mapping.get('viewer_bindings') or [])
                        if b['texture_id'] is None],
        },
        'note': ('texture_id is the identity; facade indices and viewer_index are aliases of it. '
                 'shared_texels and shared_palettes are DEMONSTRATED shared storage -- an edit to '
                 'one member reaches every member. Whether two parts read the same TEXELS of a '
                 'shared image is NOT measured: ' + OVERLAP_UNMEASURED + '.'),
    }
    if mapping.get('viewer_bindings') is not None:
        report['viewer_bindings'] = mapping['viewer_bindings']
    if mapping.get('rebased'):
        report['rebased'] = mapping['rebased']
    if part is not None:
        report['requested_part'] = resolve_part(report, mapping, part)
    return report


def _part_scope(name, entry, by_id, owner):
    """Can this part be recoloured on its own, and what would an edit also hit?

    Three demonstrated ways an edit escapes the part, each recorded separately:
    another part NAMING the same descriptor (Mario's cap emblem lives in a
    texture the cap also uses), another descriptor reading the same pixel
    storage, and another descriptor reading the same palette.
    """
    ids = entry['texture_ids'] + entry.get('masked_texture_ids', [])
    mine = set(ids)
    co_owners, storage, palette, content, meshes, aliases = [], [], [], [], 0, 0
    for texture_id in ids:
        row = by_id[texture_id]
        meshes += len(row['usages'])
        aliases += len(row['facade'])
        for other_name in owner.get(texture_id, []):
            if other_name != name and other_name not in co_owners:
                co_owners.append(other_name)
        for bucket, key in ((storage, 'shares_texels_with'), (palette, 'shares_palette_with'),
                            (content, 'duplicate_content_of')):
            for other in row[key]:
                if other not in mine and other not in bucket:
                    bucket.append(other)
    external = storage + palette + content
    partners = list(co_owners)
    for other in external:
        for other_name in owner.get(other, []):
            if other_name != name and other_name not in partners:
                partners.append(other_name)
    shared = bool(co_owners) or bool(external)
    scope = {
        'texture_ids': ids,
        'facade_indices': [f for i in ids for f in by_id[i]['facade']],
        'viewer_indices': sorted({by_id[i]['viewer_index'] for i in ids
                                  if by_id[i]['viewer_index'] is not None}),
        'provenance': entry['provenance'],
        'scope': 'shared' if shared else 'exclusive',
        'co_owned_with': co_owners,
        'shares_texels_with': {'parts': partners, 'meshes': meshes, 'texture_aliases': aliases,
                               'co_owned_texture_ids': [i for i in ids
                                                        if len(owner.get(i, [])) > 1],
                               'storage': storage, 'palette': palette, 'content': content,
                               'texture_ids': external},
        'overlapping_texels': OVERLAP_UNMEASURED if shared else None,
        'separable_by_mask': not shared,
        'masked': entry.get('masked', False),
    }
    scope['required_mask'] = _required_mask(co_owners, external, shared)
    if shared:
        scope['stop'] = SHARED_STOP.format(
            part=name.capitalize(),
            others=(' and '.join(partners) if partners else
                    f'{len(external)} unnamed textures on the same storage'))
    return scope


def _required_mask(co_owners, external, shared):
    """What would have to narrow an edit to this part, and is it available?

    One supported narrower mask exists, and it is a COLOUR mask: the part map
    knows both parts by name, so ``analyze_palette with parts`` can cluster each
    on its own and keep the other's detail out (the cap red around Mario's
    emblem M). It applies only when every escape route is a named part. As soon
    as the pixels are shared with something unnamed -- raw storage, a palette,
    a content duplicate -- separating them would need a per-part UV mask, and
    there is none.
    """
    if not shared:
        return {'required': False}
    if co_owners and not external:
        return {'required': True, 'available': True, 'kind': 'color',
                'co_owners': list(co_owners),
                'how': "analyze_palette with parts (naming this part), or skin_material with a "
                       "colour mask and mask.surrounding=true, recolours only this part's "
                       'colours inside the texture it shares.'}
    return {'required': True, 'available': False, 'kind': 'uv',
            'reason': 'The pixels are shared with something the part map does not name, so no '
                      'colour mask separates them, and no per-part UV mask exists: '
                      + OVERLAP_UNMEASURED + '.'}


def resolve_part(report, mapping, part):
    """Answer "which textures is <part>, and can it be edited on its own?"."""
    wanted = str(part).strip().lower()
    names = {name.lower(): name for name in report['parts']}
    for candidate in PART_SYNONYMS.get(wanted, (wanted,)):
        if candidate in names:
            name = names[candidate]
            entry = report['parts'][name]
            return {'name': part, 'resolved_as': name, 'identification': 'mapped',
                    'resolution': 'mapped',
                    'provenance': entry['provenance'],
                    'texture_ids': entry['texture_ids'],
                    'facade_indices': entry['facade_indices'],
                    'viewer_indices': entry['viewer_indices'],
                    'scope': entry['scope'],
                    'co_owned_with': entry['co_owned_with'],
                    'overlapping_texels': entry['overlapping_texels'],
                    'separable_by_mask': entry['separable_by_mask'],
                    'required_mask': entry['required_mask'],
                    'shares_texels_with': entry['shares_texels_with'],
                    **({'stop': entry['stop']} if 'stop' in entry else {})}

    # Nothing placed this part, so nothing about it is demonstrated -- not which
    # textures it uses, and therefore not that it shares texels with anything.
    # An unresolved part gets candidates and a stop, never a scope verdict: the
    # whole point of this module is that a guess must not authorize an edge-to-
    # edge edit of a texture 17 meshes read.
    known = {name.lower(): name for name in (mapping.get('vocabulary') or [])}
    resolved_as = next((known[c] for c in PART_SYNONYMS.get(wanted, (wanted,)) if c in known), None)
    candidates = []
    for group in sorted(report['shared_texels'], key=lambda g: -g['meshes']):
        members = [t for t in report['textures']
                   if t['groups']['texels'] == group['group'] and t['kind'] == 'material'
                   and t['width'] * t['height'] >= FLAT_PATCH_TEXELS]
        if not members:
            continue
        candidates.append({
            'texture_ids': [t['texture_id'] for t in members],
            'facade_indices': [f for t in members for f in t['facade']],
            'viewer_indices': sorted({t['viewer_index'] for t in members
                                      if t['viewer_index'] is not None}),
            'predicted_viewer_indices': sorted({t['predicted_viewer_index'] for t in members
                                                if t['predicted_viewer_index'] is not None}),
            'width': members[0]['width'], 'height': members[0]['height'],
            'confirmed': False,
            'shared_storage': True,
            'meshes': group['meshes'], 'texture_aliases': len(group['facade_indices']),
            'overlapping_texels': OVERLAP_UNMEASURED,
            'why': 'a surface image this costume reads from several meshes; NOT confirmed to '
                   'carry this part',
        })
    return {
        'name': part,
        'resolved_as': resolved_as,
        'identification': 'unresolved',
        'resolution': 'unresolved',
        'provenance': 'unresolved',
        'scope': 'unresolved',
        'texture_ids': [],
        'facade_indices': [],
        'viewer_indices': [],
        'separable_by_mask': None,
        'overlapping_texels': OVERLAP_UNMEASURED,
        'required_mask': {'required': True, 'available': False, 'kind': 'identification',
                          'reason': 'the part itself has not been identified on this costume'},
        'candidates': candidates,
        'stop': UNRESOLVED_STOP.format(part=part),
        'next': ('Highlight a candidate in a Skin Lab session to confirm which geometry it '
                 'covers, then ask again. The identification cannot be inferred from texture '
                 'sizes or mesh counts.'),
    }


#: Below this an image is a flat fill (Melee pads materials with 8x8 patches),
#: never the artwork a named body part is painted on. Used only to keep those
#: patches out of the CANDIDATE list; it never confirms anything.
FLAT_PATCH_TEXELS = 256


# --------------------------------------------------------------------------- #
# reserialization                                                             #
# --------------------------------------------------------------------------- #
def rebase(previous, current):
    """Carry provenance from a previous report onto the report of a rewritten DAT.

    Every id changes when a DAT is reserialized -- the file hash changes and so
    does every struct offset -- so a NEW mapping is generated rather than
    patched. A texture is re-identified only through an UNAMBIGUOUS
    correspondence: the same root symbols, the same facade footprint
    (``(node, texture_index)`` pairs, which the DAT walk fixes) and the same
    encoded content. Content alone is not enough -- two identical textures under
    reordered roots would swap predecessors, which is a wrong provenance claim
    dressed as a correct one -- so anything that matches more than one candidate
    is left unresolved and counted.

    Returns ``current`` with ``previous_texture_id``, ``carried_parts`` and a
    ``rebased`` summary added.
    """
    def footprint(record):
        """Where this texture SITS, plus what it holds. Structural coordinates
        the DAT walk fixes (root symbol, joint, mesh, material slot; and for a
        swap bank its joint/matanim/texmap/frame) -- not an enumeration ordinal,
        and never content on its own."""
        usages = []
        for usage in record.get('usages', []):
            if usage['kind'] == 'material':
                usages.append(('material', usage['node'], usage['jobj_index'],
                               usage['dobj_index'], usage['tobj_slot']))
            else:
                usages.append(('matanim', usage['node'], usage['joint_index'],
                               usage['matanim_index'], usage['texmap_id'], usage['frame']))
        return (tuple(sorted(record.get('nodes') or ())),
                tuple(sorted((f['node'], f['texture_index'])
                             for f in record.get('facade', []))),
                tuple(sorted(usages)),
                record['content_sha256'])

    pools = {}
    for record in previous['textures']:
        pools.setdefault(footprint(record), []).append(record)

    carried, ambiguous, unmatched = 0, [], []
    for record in current['textures']:
        pool = pools.get(footprint(record), [])
        if len(pool) != 1:
            (ambiguous if pool else unmatched).append(record['texture_id'])
            continue
        record['previous_texture_id'] = pool[0]['texture_id']
        carried += 1

    forward = {r['previous_texture_id']: r['texture_id'] for r in current['textures']
               if r.get('previous_texture_id')}
    current['carried_parts'] = {
        name: {'texture_ids': [forward[i] for i in entry['texture_ids'] if i in forward],
               'provenance': entry.get('provenance'),
               'complete': all(i in forward for i in entry['texture_ids']),
               'carried_from': previous['source']['sha256']}
        for name, entry in (previous.get('parts') or {}).items()
        if any(i in forward for i in entry['texture_ids'])}
    current['rebased'] = {'from': previous['source']['sha256'],
                          'to': current['source']['sha256'],
                          'carried': carried, 'of': len(current['textures']),
                          'ambiguous': ambiguous, 'unmatched': unmatched}
    return current


# --------------------------------------------------------------------------- #
# one call                                                                    #
# --------------------------------------------------------------------------- #
def analyze(path, origin=None, viewer=None, part=None, previous=None):
    """Build the map, label it, and return the report. ``viewer`` is optional."""
    mapping = build_map(path, origin)
    if viewer is not None:
        attach_viewer(mapping, viewer)
    label_parts(mapping)
    report = describe(mapping, part=part)
    if previous:
        rebase(previous, report)
    return report
