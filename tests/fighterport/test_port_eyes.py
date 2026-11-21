"""fighter_port.eyes: an eye's white and iris layers baked into the costume's own texture, the costume
pieces found for them, blink frames redrawn over the baked eye, and a patch over the eyes emptied."""
import os
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from fighter_port import eyes


def test_texture_coordinates_stored_a_whole_picture_away_are_put_back():
    place = np.array([[x, y] for x in np.linspace(0, 1, 6) for y in np.linspace(0, 1, 4)])
    uv = place * [0.97, -0.97] + [-0.02, 0.98]
    stored = uv.copy()
    stored[stored[:, 0] < 0, 0] += 1.0                  # -0.02 kept as 0.98, as a console's file does
    M, off = eyes.affine(place, stored, wraps=True)
    assert off < 1e-6 and np.allclose(M, [[0.97, 0], [0, -0.97], [-0.02, 0.98]], atol=1e-6)
    assert eyes.affine(place, stored)[1] > 0.3          # without knowing it repeats, one fit cannot hold


def eye(side):
    """A game eye: a square patch on one side of the head, the iris layer on a stretched second set of coordinates."""
    place = np.array([[x, y] for x in (0.0, 0.5, 1.0) for y in (0.0, 0.5, 1.0)])
    world = np.c_[side * (0.2 + 0.4 * place[:, 0]), 18.0 + 0.2 * place[:, 1], np.ones(9)]
    map1 = np.c_[place[:, 0], 1.0 - place[:, 1]]        # the game's v runs down the picture
    return {'material': 'EyeL' if side > 0 else 'EyeR', 'white': 'w', 'iris': 'bL' if side > 0 else 'bR',
            'transform': [1.0, 1.0, 0.0, 0.0], 'clamp': True, 'map1': map1, 'uvset': map1 * 2.0 - 0.5,
            'world': world, 'overlays': []}


def pictures():
    white = np.zeros((16, 16, 4), np.uint8)
    white[...] = (200, 200, 200, 255)
    white[:4] = (40, 40, 40, 255)                       # a shadow along the top of the eye
    iris = np.zeros((16, 16, 4), np.uint8)
    iris[4:12, 4:12] = (0, 80, 255, 255)                # a square iris in the middle of its own picture
    return {'w': Image.fromarray(white, 'RGBA'), 'bL': Image.fromarray(iris, 'RGBA'), 'bR': Image.fromarray(iris, 'RGBA')}


def costume_piece(game_eye, turn_over=False):
    """The costume's piece for an eye: the same patch, smaller and elsewhere, its coordinates as an exporter writes them."""
    place = eyes._unit(game_eye['world'])
    points = np.c_[game_eye['world'][:, 0] * 0.8, 15.0 + 0.16 * place[:, 1], np.ones(9)]
    uv = np.c_[place[:, 0], place[:, 1]]                # the costume's v runs up the picture: the same picture, upright
    if turn_over:
        uv[:, 1] = 1.0 - uv[:, 1]                       # an import that stored the picture upside down
    return {'dobj': 21, 'texture': 21, 'points': points, 'uv': uv, 'bone': 60, 'eye': game_eye}


def test_an_eye_is_baked_white_then_iris_in_the_costumes_own_layout():
    left = eye(+1)
    out = np.asarray(eyes.bake(costume_piece(left), pictures(), (32, 32)).convert('RGB'), int)
    assert tuple(out[2, 16]) == (40, 40, 40)            # the shadow is still along the top
    assert tuple(out[16, 16]) == (0, 80, 255)           # the iris sits in the middle of the eye
    assert tuple(out[28, 3]) == (200, 200, 200)         # and the white shows around it
    blue = (out[..., 2] > 200) & (out[..., 0] < 60)
    ys, xs = np.where(blue)
    assert 6 <= xs.max() - xs.min() <= 9                # the iris picture's square is half as wide on the eye: its coordinates are stretched by two
    # a costume that stores the same picture upside down gets it baked upside down, so it still looks right on the face
    flipped = np.asarray(eyes.bake(costume_piece(left, turn_over=True), pictures(), (32, 32)).convert('RGB'), int)
    assert tuple(flipped[29, 16]) == (40, 40, 40) and tuple(flipped[16, 16]) == (0, 80, 255)


def test_an_overlay_on_the_eye_is_baked_in_too():
    left = eye(+1)
    lash = np.zeros((16, 16, 4), np.uint8)
    lash[12:] = (0, 0, 0, 255)                          # a dark line along the bottom, see-through elsewhere
    left['overlays'] = [{'texture': 'lash', 'map1': left['map1']}]
    out = np.asarray(eyes.bake(costume_piece(left), dict(pictures(), lash=Image.fromarray(lash, 'RGBA')), (32, 32)).convert('RGB'), int)
    assert tuple(out[30, 16]) == (0, 0, 0) and tuple(out[16, 16]) == (0, 80, 255)


DAE = """<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema"><library_geometries>{}</library_geometries></COLLADA>"""
GEOMETRY = """<geometry id="Joint_0_Object_{n}-geometry"><mesh>
<source id="g{n}-POSITION"><float_array>{pos}</float_array><technique_common><accessor stride="3"/></technique_common></source>
<source id="g{n}-TEXCOORD"><float_array>{uv}</float_array><technique_common><accessor stride="2"/></technique_common></source>
<vertices id="g{n}-VERTEX"><input semantic="POSITION" source="#g{n}-POSITION"/></vertices>
<triangles><input semantic="VERTEX" source="#g{n}-VERTEX" offset="0"/><input semantic="TEXCOORD" source="#g{n}-TEXCOORD" offset="1"/>
<p>0 0 1 1 2 2 0 0 2 2 3 3</p></triangles></mesh></geometry>"""


def quad(n, x0, x1, y0=15.0, y1=15.2):
    pos = [x0, y0, 1, x1, y0, 1, x1, y1, 1, x0, y1, 1]
    return GEOMETRY.format(n=n, pos=' '.join(map(str, pos)), uv='0 0 1 0 1 1 0 1')


def test_costume_pieces_are_paired_with_the_games_eyes_by_side(tmp_path):
    dae = tmp_path / 'body.dae'
    dae.write_text(DAE.format(quad(21, 0.2, 0.5) + quad(25, -0.5, -0.2) + quad(46, -0.5, 0.5) + quad(27, -3, 3, 0, 16) + quad(29, -0.5, 0.5)), 'utf-8')
    white, flat, black = pictures()['w'], Image.new('RGBA', (8, 8), (10, 90, 10, 255)), Image.new('RGBA', (8, 8), (0, 0, 0, 255))
    info = [{'dobj': 21, 'owner': 0, 'verts': 4, 'bones': [60], 'textures': [21]}, {'dobj': 25, 'owner': 0, 'verts': 4, 'bones': [60], 'textures': [25]},
            {'dobj': 27, 'owner': 0, 'verts': 4, 'bones': [60], 'textures': [27]}, {'dobj': 29, 'owner': 0, 'verts': 4, 'bones': [60], 'textures': [29]},
            {'dobj': 46, 'owner': 0, 'verts': 4, 'bones': [60], 'textures': [46]}, {'dobj': 30, 'owner': 0, 'verts': 0, 'bones': [], 'textures': [0]}]
    textures = {21: white.resize((8, 8)), 25: white.resize((8, 8)), 46: white.resize((8, 8)), 27: flat, 29: black}
    game = [eye(+1), eye(-1)]
    found, root = eyes.pieces(dae, info, textures, game, pictures())
    by = {p['dobj']: p for p in found}
    assert set(by) == {21, 25, 46}                                               # not the hair, not the patch
    assert by[21]['eye']['material'] == 'EyeL' and by[25]['eye']['material'] == 'EyeR'
    assert by[46].get('both') and by[46]['eye']['material'] == 'EyeL' and by[46]['points'][:, 0].min() > 0   # the far copy: one eye's picture
    # the opaque flat piece lying exactly over both eyes is the patch; the hair, bigger, is not
    assert eyes.cover(root, info, textures, [by[21], by[25]]) == [29]
    with pytest.raises(ValueError):
        eyes.pieces(dae, info, textures, game[:1], pictures())


def test_a_flat_picture_is_matched_by_its_colour_and_a_drawn_one_by_looking():
    grey = Image.new('RGBA', (64, 64), (186, 186, 186, 255))
    assert eyes.looks_like(Image.new('RGBA', (64, 32), (189, 186, 189, 255)), grey)       # Byleth's eye white, cropped by the import
    assert not eyes.looks_like(Image.new('RGBA', (64, 32), (0, 0, 0, 255)), grey)
    drawn = pictures()['w']
    assert eyes.looks_like(drawn.resize((32, 16), Image.LANCZOS), drawn) and not eyes.looks_like(grey, drawn)


def test_blink_pictures_are_written_in_the_consoles_order():
    indices = np.arange(16 * 8, dtype=np.uint8).reshape(8, 16)
    data = eyes._index_bytes(indices)
    assert data[:8] == bytes(range(0, 8)) and data[8:16] == bytes(range(16, 24))          # a tile: 8 across, 4 down
    assert data[32:40] == bytes(range(8, 16))                                             # then the tile to its right
    with pytest.raises(ValueError):
        eyes._index_bytes(np.zeros((6, 16), np.uint8))
    table = eyes._palette_bytes([(255, 0, 0), (0, 255, 0), (8, 8, 8)], 2, 4)
    assert struct.unpack('>4H', table) == (0x8000 | 31 << 10, 0x8000 | 31 << 5, 0x8000 | 1 << 10 | 1 << 5 | 1, 0)
    assert struct.unpack('>2H', eyes._palette_bytes([(255, 0, 0), (0, 0, 255)], 1, 2)) == (31 << 11, 31)
    idx, colours = eyes._paletted(pictures()['w'], 256)
    assert idx.shape == (16, 16) and set(map(tuple, np.array(colours)[np.unique(idx)])) == {(200, 200, 200), (40, 40, 40)}


def test_the_games_own_eyes_read_as_two_layers():
    dump = os.environ.get('ULTIMATE_DUMP')
    if not dump or not (Path(dump) / 'gamedata/fighter/master/model/body/c00/model.numatb').exists():
        pytest.skip('needs ULTIMATE_DUMP with Byleth fetched')
    sys.path.insert(0, str(Path(dump) / 'pydeps' / 'ssbh_data_py-0.9.1'))
    import ssbh_data_py
    found = {e['material']: e for e in eyes.game_eyes(ssbh_data_py, dump, 'master')}
    assert set(found) == {'EyeL', 'EyeR'}
    left = found['EyeL']
    assert (left['white'], left['iris']) == ('eye_master_w_col', 'eye_master_b_L_col') and left['clamp']
    assert [o['texture'] for o in left['overlays']] == ['alp_master_002_col']             # the lash shadow over the eye
    assert left['world'][:, 0].mean() > 0 > found['EyeR']['world'][:, 0].mean()           # one on each side of the head
    second, off = eyes.affine(left['map1'], left['uvset'])
    assert off < 0.05 and second[0, 0] > 1.5                                              # the iris layer is stretched over the eye
