"""A thing a special makes that the game shows in one pose at a time (Duck Hunt's gunmen): its poses read from its
model's meshes' names, one flat picture each in one model, and the item's code showing one of them."""
import numpy as np
import pytest

from fighter_port import own_items, weapons

# the gunman model's meshes, as the game names them
GUNMAN_MESHES = ['Hige_A_VIS_O_OBJShape', 'Hige_B_VIS_O_OBJShape', 'Hige_C_VIS_O_OBJShape', 'Noppo_A_VIS_O_OBJShape',
                 'Noppo_B_VIS_O_OBJShape', 'Noppo_C_VIS_O_OBJShape', 'Noppo_D_VIS_O_OBJShape', 'Kurohuku_A_VIS_O_OBJShape',
                 'Kurohuku_B_VIS_O_OBJShape', 'Kurohuku_C_VIS_O_OBJShape', 'Kurohuku_D_VIS_O_OBJShape',
                 'Sombrelo_A_VIS_O_OBJShape', 'Sombrelo_B_VIS_O_OBJShape', 'Sombrelo_C_VIS_O_OBJShape', 'Boss_A_VIS_O_OBJShape',
                 'Boss_B_VIS_O_OBJShape', 'Boss_C_VIS_O_OBJShape']


def test_a_models_figures_in_poses_are_read_from_its_meshes_names():
    got = own_items.pose_meshes(GUNMAN_MESHES)
    assert got == {'Hige': ['A', 'B', 'C'], 'Noppo': ['A', 'B', 'C', 'D'], 'Kurohuku': ['A', 'B', 'C', 'D'],
                   'Sombrelo': ['A', 'B', 'C'], 'Boss': ['A', 'B', 'C']}
    # a mesh of one piece, a left and a right, and a lone A are no figure in poses; the names may lack the tail
    assert own_items.pose_meshes(['Gamemodel_VIS_O_OBJShape', 'Hand_L_VIS_O_OBJShape', 'Hand_R_VIS_O_OBJShape',
                                  'Lid_A_VIS_O_OBJShape', 'Can_A', 'Can_B']) == {'Can': ['A', 'B']}


def picture(width, height, colour):
    from PIL import Image
    return Image.new('RGBA', (width, height), colour)


def test_the_poses_are_one_model_a_mesh_each_in_the_order_given(tmp_path):
    from PIL import Image
    pictures = [(picture(4, 8, (255, 0, 0, 255)), (-1.0, 1.0, 0.0, 4.0), 'man_a'),
                (picture(6, 8, (0, 0, 255, 255)), (-1.0, 2.0, 0.0, 4.2), 'man_b')]
    model = own_items.cutouts(pictures, tmp_path, grow=4)
    assert [p['texture'] for p in model['parts']] == ['man_a', 'man_b'] and model['triangles'] == 8
    # each stands on its own extent (the figure's feet are where they are in the game's model), the model's size is all of them
    assert np.allclose(model['parts'][1]['positions'][:, 2].max(), 2.0) and np.allclose(model['max'][1:], [4.2, 2.0])
    assert Image.open(tmp_path / 'tex' / 'man_b.png').size == (24, 32)
    # two poses of one picture name would be drawn as one mesh, and the item would count its poses wrong
    with pytest.raises(ValueError):
        own_items.cutouts(pictures[:1] * 2, tmp_path)


def test_a_tall_figure_is_drawn_with_smaller_squares_never_shrunk(tmp_path):
    # (the boss is 69 squares tall facing the camera and 71 turned: at four pixels a square his pictures would pass 256
    # and be shrunk and blurred, and stored at four times the bytes; one size of square for both, so they look alike)
    from PIL import Image
    pictures = [(picture(29, 69, (255, 0, 0, 255)), (-1.0, 1.0, 0.0, 4.0), 'boss_a'),
                (picture(35, 71, (0, 0, 255, 255)), (-1.0, 1.0, 0.0, 4.0), 'boss_b')]
    own_items.cutouts(pictures, tmp_path)
    assert [Image.open(tmp_path / 'tex' / f'boss_{p}.png').size for p in 'ab'] == [(87, 207), (105, 213)]
    assert max(Image.open(tmp_path / 'tex' / 'boss_b.png').size) <= own_items.PICTURE_MOST
    import inspect
    assert inspect.signature(weapons.write_smd).parameters['max_texture'].default == own_items.PICTURE_MOST
    # a figure that fits keeps its four pixels a square
    own_items.cutouts([(picture(32, 64, (0, 0, 0, 255)), (-1.0, 1.0, 0.0, 4.0), 'hige_a')], tmp_path)
    assert Image.open(tmp_path / 'tex' / 'hige_a.png').size == (128, 256)


def test_the_meshes_keep_the_poses_order_in_the_file_the_model_tool_reads(tmp_path):
    # (the model tool makes a mesh for each material in the order they first come: built and read 2026-11-13, poses
    # given C, A, B came out C, A, B; the item's code shows a pose by that place)
    pictures = [(picture(2, 2, (0, 0, 0, 255)), (0.0, 1.0, 0.0, 1.0), name) for name in ('man_c', 'man_a', 'man_b')]
    model = own_items.cutouts(pictures, tmp_path)
    smd, missing = weapons.write_smd({'man': model}, 'man', own_items.TO_ITEM, tmp_path, [tmp_path / 'tex'])
    lines = smd.read_text('ascii').splitlines()
    materials = [line for line in lines if line.startswith('man_')]
    assert not missing and list(dict.fromkeys(materials)) == ['man_man_c', 'man_man_a', 'man_man_b']


def test_the_item_shows_one_pose_and_hides_the_rest():
    text = own_items.SHOW_POSE
    assert 'static void Show_Pose(GOBJ *item, int pose)' in text and '@' not in text
    # its meshes, in order, on the one joint of its model
    assert 'DOBJ *mesh = ((JOBJ *)item->hsd_object)->dobj;' in text and 'mesh = mesh->next' in text
    assert 'if (k == pose)\n            DOBJ_ClearFlags(mesh, DOBJ_HIDDEN);' in text
    assert 'else\n            DOBJ_SetFlags(mesh, DOBJ_HIDDEN);' in text
