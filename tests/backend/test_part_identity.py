"""The canonical part-map adapter: identity first, ordinals only as aliases.

The app's part map is authored in the Skin Lab viewer's index space and the
facade only ever spoke its own DAT-walk space, so finding "the hair" on a
ported costume used to mean brute force -- painting candidate textures with
debug colours and diffing renders. These tests pin the translation between
them, and the facts a recolour has to know before it starts: which ordinal is
which texture, which textures are really the same storage, which look alike
but are not -- and, just as important, where the evidence runs out and the
honest answer is ``unresolved``.
"""
from tests.paths import BACKEND
import io
import json
import shutil
import struct
import sys
from pathlib import Path

import pytest

BACKEND_DIR = BACKEND
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from shared.rendering import part_identity                                  # noqa: E402

VANILLA = BACKEND_DIR.parent / 'utility' / 'assets' / 'vanilla'
VANILLA_FOX = VANILLA / 'Fox' / 'PlFxNr' / 'PlFxNr.dat'
VANILLA_MARIO = VANILLA / 'Mario' / 'PlMrBk' / 'PlMrBk.dat'

needs_fox = pytest.mark.skipif(not VANILLA_FOX.is_file(),
                               reason='vanilla Fox costume not extracted on this machine')
needs_mario = pytest.mark.skipif(not VANILLA_MARIO.is_file(),
                                 reason='vanilla Mario costume not extracted on this machine')


def _renderer():
    try:
        from core import config
        return Path(config.HSDRAW_EXE).is_file()
    except Exception:
        return False


needs_renderer = pytest.mark.skipif(not _renderer(), reason='HSDRawViewer is not built here')


# --------------------------------------------------------------------------- #
# a DAT built to order                                                        #
# --------------------------------------------------------------------------- #
class DatBuilder:
    """The smallest DAT the adapter's walk accepts, assembled field by field.

    Melee ships no costume where one image is drawn through two palettes, or
    where two roots read one copy of the pixels, so the cases that broke the
    first version of this module are built here instead of hunted for.
    """
    HEADER = 0x20

    def __init__(self):
        # data-section relative from here on; the first 16 bytes are reserved so
        # no real pointer is ever 0 (a 0 word with no reloc entry means NULL)
        self.data = bytearray(0x10)
        self.roots = []

    def _alloc(self, size):
        offset = len(self.data)
        pad = -offset % 16
        self.data += b'\x00' * (pad + size)
        return offset + pad

    def _put32(self, offset, value):
        struct.pack_into('>I', self.data, offset, value)

    def _put16(self, offset, value):
        struct.pack_into('>H', self.data, offset, value)

    def blob(self, payload):
        offset = self._alloc(len(payload))
        self.data[offset:offset + len(payload)] = payload
        return offset

    def image(self, pixels, width=8, height=8, fmt=9):
        """An HSD_Image. fmt 9 = CI8, so it needs a palette to decode."""
        data_offset = self.blob(pixels)
        offset = self._alloc(0x18)
        self._put32(offset + 0x00, data_offset)
        self._put16(offset + 0x04, width)
        self._put16(offset + 0x06, height)
        self._put32(offset + 0x08, fmt)
        return offset

    def tlut(self, colors, fmt=1):
        data_offset = self.blob(colors)
        offset = self._alloc(0x10)
        self._put32(offset + 0x00, data_offset)
        self._put32(offset + 0x04, fmt)
        self._put16(offset + 0x0c, len(colors) // 2)
        return offset

    def root(self, name, tobjs):
        """One root joint -> one mesh -> one material -> this list of TOBJs."""
        previous = 0
        for image_offset, tlut_offset in reversed(tobjs):
            tobj = self._alloc(0x5c)
            self._put32(tobj + 0x04, previous)
            self._put32(tobj + 0x4c, image_offset)
            self._put32(tobj + 0x50, tlut_offset or 0)
            previous = tobj
        mobj = self._alloc(0x0c)
        self._put32(mobj + 0x08, previous)
        dobj = self._alloc(0x0c)
        self._put32(dobj + 0x08, mobj)
        jobj = self._alloc(0x40)
        self._put32(jobj + 0x10, dobj)
        self.roots.append((name, jobj))
        return jobj

    def write(self, path, root_order=None):
        names = [name for name, _ in self.roots]
        order = root_order or list(range(len(self.roots)))
        body = bytes(self.data)
        strings, table = bytearray(), bytearray()
        for i in order:
            name, offset = self.roots[i]
            table += struct.pack('>II', offset, len(strings))
            strings += name.encode('ascii') + b'\x00'
        header = struct.pack('>IIIII',
                             self.HEADER + len(body) + len(table) + len(strings),
                             len(body), 0, len(order), 0) + b'\x00' * 12
        Path(path).write_bytes(header + body + bytes(table) + bytes(strings))
        return names


def _indices(value):
    """8x8 of one palette index -- valid CI8 data for a 4-colour TLUT."""
    return bytes([value]) * 64


PALETTE_A = struct.pack('>4H', 0xF800, 0x07E0, 0x001F, 0xFFFF)
PALETTE_B = struct.pack('>4H', 0x001F, 0xF800, 0xFFFF, 0x07E0)

#: The meshes of ``write_unmapped_port``; each reads the shared image once.
PORT_MESHES = ('PlyPort_Body_joint', 'PlyPort_Head_joint', 'PlyPort_Tail_joint')


def write_unmapped_port(path):
    """A restructured model port: a texture layout no vanilla part map fits.

    One 16x16 image (viewer index 0) read by every mesh, beside one 8x8 flat
    fill they also share. Analysed as a Fox costume, nothing places any part.
    """
    builder = DatBuilder()
    tlut = builder.tlut(PALETTE_A)
    atlas = builder.blob(bytes([1]) * 256)            # one 16x16 image ...
    patch = builder.blob(_indices(0))                 # ... and one 8x8 flat fill

    def image_at(data_offset, size):
        offset = builder._alloc(0x18)
        builder._put32(offset + 0x00, data_offset)
        builder._put16(offset + 0x04, size)
        builder._put16(offset + 0x06, size)
        builder._put32(offset + 0x08, 9)
        return offset

    for name in PORT_MESHES:
        builder.root(name, [(image_at(atlas, 16), tlut), (image_at(patch, 8), tlut)])
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    builder.write(path)
    return Path(path)


# --------------------------------------------------------------------------- #
# identity and its aliases                                                    #
# --------------------------------------------------------------------------- #
@needs_fox
def test_facade_indices_match_the_facade_s_own_texture_inventory():
    """The adapter's (node, texture_index) pairs ARE modfile.list_textures'."""
    from shared.mod_files import texture_inventory
    mapping = part_identity.build_map(VANILLA_FOX, {'character': 'Fox', 'costume_code': 'PlFxNr'})
    mine = sorted((f['node'], f['texture_index'])
                  for record in mapping['textures'] for f in record['facade'])
    theirs = sorted((row['node'], row['texture_index']) for row in texture_inventory(VANILLA_FOX))
    assert mine == theirs
    assert len(theirs) == 77


@needs_fox
def test_predicted_viewer_list_reproduces_the_authored_part_map_signature():
    """77 facade rows collapse to the 36 the renderer lists, without a renderer."""
    from shared.rendering import part_map
    mapping = part_identity.build_map(VANILLA_FOX, {'character': 'Fox', 'costume_code': 'PlFxNr'})
    listed = part_identity.viewer_texture_list(mapping)
    assert len(listed) == 36
    assert part_map.signature(listed) == part_map._load()['PlFxNr']['signature']
    assert part_identity.label_parts(mapping)['fur']['provenance'] == 'vanilla'


def _fake_viewer(mapping, order=None):
    """A viewer whose list is in ``order`` (a permutation of the real one)."""
    from PIL import Image
    listed = sorted((r for r in mapping['textures'] if r['viewer_index'] is not None),
                    key=lambda r: r['viewer_index'])
    if order is not None:
        listed = [listed[i] for i in order]
    textures, pixels = [], {}
    for index, record in enumerate(listed):
        buffer = io.BytesIO()
        Image.fromarray(part_identity.decoded_pixels(record), 'RGBA').save(buffer, format='PNG')
        textures.append({'index': index, 'width': record['width'], 'height': record['height'],
                         'matAnim': record['kind'] == 'matanim', 'animates': -1})
        pixels[index] = buffer.getvalue()
    return part_identity.DetachedViewer(textures, [], pixels), listed


@needs_fox
def test_reordered_viewer_indices_still_resolve_to_the_correct_facade_textures():
    """The live list's ORDER is the renderer's business, never an identity."""
    origin = {'character': 'Fox', 'costume_code': 'PlFxNr'}
    straight = part_identity.build_map(VANILLA_FOX, origin)
    viewer, listed = _fake_viewer(straight)
    part_identity.reconcile_viewer(straight, viewer.textures, viewer.get_full_texture)
    expected = {record['texture_id']: record['viewer_index'] for record in straight['textures']
                if record['viewer_index'] is not None}
    assert expected, 'nothing bound at all'

    order = list(reversed(range(len(listed))))
    shuffled = part_identity.build_map(VANILLA_FOX, origin)
    reversed_viewer, _ = _fake_viewer(shuffled, order)
    bindings = part_identity.reconcile_viewer(shuffled, reversed_viewer.textures,
                                              reversed_viewer.get_full_texture)
    assert all(binding['alias_confidence'] == 'content' for binding in bindings)

    facade = {record['texture_id']: [(f['node'], f['texture_index']) for f in record['facade']]
              for record in shuffled['textures']}
    for live, binding in enumerate(bindings):
        original = order[live]
        straight_id = next(i for i, v in expected.items() if v == original)
        assert facade[binding['texture_id']] == facade[straight_id], (
            f'live index {live} resolved to the wrong facade textures')

    # the part map reads the CANONICAL enumeration, so labels survive the reorder
    part_identity.label_parts(shuffled)
    part_identity.label_parts(straight)
    assert (sorted(straight['parts']['fur']['texture_ids'])
            == sorted(shuffled['parts']['fur']['texture_ids']))


def test_duplicate_looking_textures_are_left_unresolved_not_guessed(tmp_path):
    """Identical pixels are not an identity, and neither is "probably the first".

    Two descriptors with their own storage and identical bytes both match the
    same live entry. Content cannot separate them and the viewer transport does
    not carry the descriptor, so nothing is bound: picking the lower ordinal
    would be a coin toss recorded as a fact.
    """
    from PIL import Image
    import numpy as np
    builder = DatBuilder()
    tlut = builder.tlut(PALETTE_A)
    first = builder.image(_indices(0))
    second = builder.image(_indices(0))               # same bytes, its own storage
    builder.root('PlyTest_Share_joint', [(first, tlut), (second, tlut)])
    path = tmp_path / 'twins.dat'
    builder.write(path)

    mapping = part_identity.build_map(path)
    assert len(mapping['textures']) == 2, 'two descriptors, not one'
    assert len({r['texture_id'] for r in mapping['textures']}) == 2
    assert len({r['texel_group'] for r in mapping['textures']}) == 2, 'separate storage'
    assert len({r['content_group'] for r in mapping['textures']}) == 1, 'identical bytes'

    buffer = io.BytesIO()
    Image.fromarray(part_identity.decoded_pixels(mapping['textures'][0]), 'RGBA').save(
        buffer, format='PNG')
    png = buffer.getvalue()
    bindings = part_identity.reconcile_viewer(
        mapping, [{'index': 0, 'width': 8, 'height': 8}, {'index': 1, 'width': 8, 'height': 8}],
        lambda index: png)

    assert [b['texture_id'] for b in bindings] == [None, None]
    assert [b['alias_confidence'] for b in bindings] == ['ambiguous', 'ambiguous']
    assert len(bindings[0]['candidates']) == 2
    assert all(r['viewer_index'] is None for r in mapping['textures'])

    report = part_identity.describe(mapping)
    assert report['unresolved']['aliases'] == bindings
    assert len(report['duplicate_content']) == 1, 'and the pair is reported as such'
    assert np.asarray(part_identity.decoded_pixels(mapping['textures'][0])).shape == (8, 8, 4)


def test_contradictory_pixels_do_not_fall_back_to_a_size_match(tmp_path):
    """A wrong alias is how an edit lands on a hidden LOD copy."""
    from PIL import Image
    import numpy as np
    builder = DatBuilder()
    tlut = builder.tlut(PALETTE_A)
    builder.root('PlyTest_Share_joint', [(builder.image(_indices(0)), tlut)])
    path = tmp_path / 'one.dat'
    builder.write(path)
    mapping = part_identity.build_map(path)

    buffer = io.BytesIO()
    other = np.zeros((8, 8, 4), dtype=np.uint8)
    other[..., 3] = 255
    Image.fromarray(other, 'RGBA').save(buffer, format='PNG')
    bindings = part_identity.reconcile_viewer(
        mapping, [{'index': 0, 'width': 8, 'height': 8}], lambda index: buffer.getvalue())
    assert bindings[0]['texture_id'] is None
    assert bindings[0]['alias_confidence'] == 'unmatched'


# --------------------------------------------------------------------------- #
# scope: what an edit would really touch                                      #
# --------------------------------------------------------------------------- #
@needs_mario
def test_a_part_named_by_two_parts_is_not_exclusive():
    """Mario's cap emblem sits in a texture the cap also uses.

    Scope used to be computed only against texture ids OUTSIDE the part, so a
    descriptor two parts both name looked private to each of them and both came
    back ``exclusive`` -- an edit authorization for the whole texture.
    """
    report = part_identity.analyze(VANILLA_MARIO, {'character': 'Mario', 'costume_code': 'PlMrBk'})
    cap, emblem = report['parts']['cap'], report['parts']['cap emblem']

    shared_ids = set(cap['texture_ids']) & set(emblem['texture_ids'])
    assert shared_ids, 'the fixture only means something if they really do share a descriptor'
    assert cap['scope'] == 'shared' and emblem['scope'] == 'shared'
    assert cap['co_owned_with'] == ['cap emblem'] and emblem['co_owned_with'] == ['cap']
    assert cap['separable_by_mask'] is False and emblem['separable_by_mask'] is False

    # the mask is named: both are shared ONLY with a part the map knows, which
    # is exactly what a colour mask can separate
    for entry, other in ((cap, 'cap emblem'), (emblem, 'cap')):
        assert entry['required_mask']['required'] is True
        assert entry['required_mask']['available'] is True
        assert entry['required_mask']['kind'] == 'color'
        assert entry['required_mask']['co_owners'] == [other]
        assert entry['shares_texels_with']['storage'] == []

    # sharing an image is never reported as sharing the same texels
    assert cap['overlapping_texels'].startswith('unmeasured')
    assert 'read the same image' in cap['stop']


@needs_fox
def test_a_part_with_its_own_storage_is_exclusive_and_needs_no_mask():
    report = part_identity.analyze(VANILLA_FOX, {'character': 'Fox', 'costume_code': 'PlFxNr'},
                                   part='hair')
    fur = report['parts']['fur']
    assert fur['provenance'] == 'vanilla'
    assert fur['scope'] == 'exclusive' and fur['separable_by_mask'] is True
    assert fur['co_owned_with'] == [] and fur['required_mask'] == {'required': False}
    requested = report['requested_part']
    assert requested['resolved_as'] == 'fur' and requested['identification'] == 'mapped'
    assert requested['scope'] == 'exclusive' and 'stop' not in requested


def test_one_image_drawn_through_two_palettes_keeps_both_bindings(tmp_path):
    """A palette is a property of the TOBJ, not of the image.

    Records merge on the image descriptor, and the first version kept only the
    first TOBJ's palette -- so a second use through a different TLUT vanished,
    and with it the fact that a palette-level recolour reaches only one of them.
    """
    builder = DatBuilder()
    first, second = builder.tlut(PALETTE_A), builder.tlut(PALETTE_B)
    image = builder.image(_indices(1))
    builder.root('PlyTest_Share_joint', [(image, first), (image, second)])
    path = tmp_path / 'two-palettes.dat'
    builder.write(path)

    report = part_identity.analyze(path)
    assert len(report['textures']) == 1, 'one descriptor, reached twice'
    texture = report['textures'][0]
    assert [f['texture_index'] for f in texture['facade']] == [0, 1]
    assert len(texture['palettes']) == 2, 'both TLUT bindings survive the merge'
    assert ({p['tlut_data_offset'] for p in texture['palettes']}
            == {u['palette']['tlut_data_offset'] for u in texture['usages']})
    assert len(texture['groups']['palettes']) == 2
    assert len(report['multi_palette_images']) == 1
    assert report['shared_descriptors'][0]['meshes'] == 2
    assert report['shared_descriptors'][0]['palettes'] == 2


def test_storage_sharing_is_grouped_across_the_whole_dat_not_per_root(tmp_path):
    """Group ids used to include the root name, hiding a shared copy of the
    pixels the moment the two uses sat under different roots."""
    builder = DatBuilder()
    tlut = builder.tlut(PALETTE_A)
    pixels = builder.blob(_indices(2))

    def image_at(data_offset):
        offset = builder._alloc(0x18)
        builder._put32(offset + 0x00, data_offset)
        builder._put16(offset + 0x04, 8)
        builder._put16(offset + 0x06, 8)
        builder._put32(offset + 0x08, 9)
        return offset

    builder.root('PlyTest_Share_joint', [(image_at(pixels), tlut)])
    builder.root('PlyTestExtra_Share_joint', [(image_at(pixels), tlut)])
    path = tmp_path / 'cross-root.dat'
    builder.write(path)

    report = part_identity.analyze(path)
    assert len(report['textures']) == 2, 'two descriptors'
    assert len(report['shared_texels']) == 1, 'one copy of the pixels, across two roots'
    group = report['shared_texels'][0]
    assert group['nodes'] == ['PlyTestExtra_Share_joint', 'PlyTest_Share_joint']
    assert len(group['texture_ids']) == 2
    assert group['overlapping_texels'].startswith('unmeasured')
    assert len(report['shared_palettes']) == 1, 'and one TLUT, across two roots'


def test_a_part_no_vanilla_map_fits_is_unresolved_and_stops_rather_than_naming_a_texture(tmp_path):
    """A restructured port: nothing in the vanilla part map fits its layout.

    The adapter does not know which texels are the hair -- and says so. It
    still hands over the candidate a recolour would have to choose (one image
    read by several meshes), marked unconfirmed, so the workflow can stop and
    ask for a scope decision instead of editing a whole shared image on a
    guess. A flat 8x8 fill is never offered as that candidate, shared or not.
    """
    path = write_unmapped_port(tmp_path / 'port.dat')
    report = part_identity.analyze(path, {'character': 'Fox', 'costume_code': 'PlFxNr'},
                                   part='hair')
    requested = report['requested_part']

    assert requested['identification'] == 'unresolved'
    assert requested['scope'] == 'unresolved'
    assert requested['separable_by_mask'] is None
    assert requested['texture_ids'] == [], 'an unidentified part selects nothing'
    assert requested['required_mask']['kind'] == 'identification'
    assert 'does not say which texels are hair' in requested['stop']
    assert requested['resolved_as'] == 'fur', "the character's own word for this surface"

    widest, = requested['candidates']                 # the shared 8x8 fill is not one
    assert widest['confirmed'] is False
    assert widest['shared_storage'] is True
    assert widest['meshes'] == 3 and widest['texture_aliases'] == 3
    assert widest['overlapping_texels'].startswith('unmeasured')
    assert (widest['width'], widest['height']) == (16, 16)
    assert len(set(widest['texture_ids'])) == 3

    assert report['parts'] == {}
    assert 'No vanilla part map matches' in report['unresolved']['reason']
    assert 'fur' in report['unresolved']['vocabulary']
    assert json.loads(json.dumps(report))['mapping_version'] == part_identity.IDENTITY_VERSION


# --------------------------------------------------------------------------- #
# reserialization                                                             #
# --------------------------------------------------------------------------- #
def test_rebase_does_not_swap_predecessors_when_the_roots_are_reordered(tmp_path):
    """Content alone re-identifies the wrong texture.

    Two roots each hold one texture with identical bytes. Matching on content
    and a bare texture_index gave both records the footprint ``(0,)``, so the
    rewrite's first unused match handed each one the OTHER root's predecessor --
    a wrong provenance claim wearing a correct-looking id.
    """
    def make(path, order):
        builder = DatBuilder()
        tlut = builder.tlut(PALETTE_A)
        builder.root('PlyAlpha_Share_joint', [(builder.image(_indices(3)), tlut)])
        builder.root('PlyBeta_Share_joint', [(builder.image(_indices(3)), tlut)])
        builder.write(path, root_order=order)
        return path

    before = part_identity.analyze(make(tmp_path / 'a.dat', [0, 1]))
    after = part_identity.analyze(make(tmp_path / 'b.dat', [1, 0]), previous=before)

    assert after['source']['sha256'] != before['source']['sha256']
    old = {row['texture_id']: row['nodes'][0] for row in before['textures']}
    assert len(set(old.values())) == 2
    for row in after['textures']:
        assert row.get('previous_texture_id'), 'an unambiguous correspondence exists'
        assert old[row['previous_texture_id']] == row['nodes'][0], (
            'provenance followed the enumeration order instead of the root')
    assert after['rebased']['ambiguous'] == []
    assert after['rebased']['carried'] == 2


@needs_fox
def test_rebase_generates_new_ids_and_carries_the_old_provenance(tmp_path):
    """A rewritten DAT gets a NEW mapping; the names travel across on content."""
    before = part_identity.analyze(VANILLA_FOX, {'character': 'Fox', 'costume_code': 'PlFxNr'})
    rewritten = tmp_path / 'PlFxNr.dat'
    rewritten.write_bytes(VANILLA_FOX.read_bytes() + b'\x00' * 32)   # a different file
    after = part_identity.analyze(rewritten, {'character': 'Fox', 'costume_code': 'PlFxNr'},
                                  previous=before)

    assert after['source']['sha256'] != before['source']['sha256']
    old_ids = {row['texture_id'] for row in before['textures']}
    assert not (old_ids & {row['texture_id'] for row in after['textures']}), (
        'the source hash is part of the identity, so every id has to change')
    assert after['rebased']['carried'] == len(after['textures'])
    assert after['rebased']['ambiguous'] == [] and after['rebased']['unmatched'] == []
    assert all(row.get('previous_texture_id') in old_ids for row in after['textures'])
    assert set(after['carried_parts']) == set(before['parts'])
    assert after['carried_parts']['fur']['complete'] is True


@needs_fox
@needs_renderer
def test_rebase_survives_a_real_hsdraw_reserialization(tmp_path):
    """Not a padded copy: HSDRaw writes the file out and every offset moves."""
    from shared.rendering import lab_session
    origin = {'character': 'Fox', 'costume_code': 'PlFxNr'}
    before = part_identity.analyze(VANILLA_FOX, origin)
    rewritten = tmp_path / 'PlFxNr-rewritten.dat'
    with lab_session.open_costume(VANILLA_FOX, 'Fox') as viewer:
        rewritten.write_bytes(viewer.export_dat())

    after = part_identity.analyze(rewritten, origin, previous=before)
    assert ({row['descriptor']['image_offset'] for row in after['textures']}
            != {row['descriptor']['image_offset'] for row in before['textures']}), (
        'HSDRaw really did move the structs, so the offsets cannot be the identity')
    assert not ({row['texture_id'] for row in after['textures']}
                & {row['texture_id'] for row in before['textures']})
    assert after['rebased']['carried'] == len(after['textures'])
    assert after['rebased']['ambiguous'] == []
    assert after['parts']['fur']['provenance'] == 'vanilla'


# --------------------------------------------------------------------------- #
# the facade                                                                  #
# --------------------------------------------------------------------------- #
def test_describe_parts_reads_the_costume_without_opening_the_user_s_viewer(tmp_path, monkeypatch):
    """The facade call the recolor workflow starts from, with no renderer at all."""
    import hashlib
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    monkeypatch.setenv('NUCLEUS_API_WORKSPACE', str(workspace))
    import nucleus_api
    outside = write_unmapped_port(tmp_path / 'vault' / 'PlFxNrMod.dat')   # not in the workspace
    shutil.copyfile(outside, workspace / outside.name)

    report = nucleus_api.modfile.describe_parts(outside.name, part='hair', character='Fox',
                                               viewer=False)
    assert report['viewer'] == 'predicted'
    assert report['requested_part']['scope'] == 'unresolved'
    assert report['source']['sha256'] == hashlib.sha256(outside.read_bytes()).hexdigest()
    assert json.loads(json.dumps(report))['source']['costume_code'] == 'PlFxNr'

    with pytest.raises(nucleus_api.WorkspaceError):
        nucleus_api.modfile.describe_parts(str(outside))


@needs_fox
@needs_renderer
def test_describe_parts_with_a_backend_session_agrees_with_the_offline_map(tmp_path, monkeypatch):
    """The private session must not change the answer -- only add UV masks."""
    monkeypatch.setenv('NUCLEUS_API_WORKSPACE', str(tmp_path))
    import nucleus_api
    shutil.copyfile(VANILLA_FOX, tmp_path / 'PlFxNr.dat')

    offline = nucleus_api.modfile.describe_parts('PlFxNr.dat', character='Fox', viewer=False)
    live = nucleus_api.modfile.describe_parts('PlFxNr.dat', character='Fox', viewer=True)

    assert offline['viewer'] == 'predicted' and live['viewer'] == 'session'
    assert ({name: sorted(entry['texture_ids']) for name, entry in offline['parts'].items()}
            == {name: sorted(entry['texture_ids']) for name, entry in live['parts'].items()})
    assert all(row['alias_confidence'] in ('content', 'facade-only') for row in live['textures'])
    assert live['uv_masks'], 'a live session contributes the UV layout'
    assert all(mask['per_part'] is False for mask in live['uv_masks'])
