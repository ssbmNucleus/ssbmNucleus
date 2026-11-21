import numpy as np
from PIL import Image
from fighter_port.material_bake import alpha_layer
from fighter_port.material_bake import layer_coordinates


def test_secondary_uv_layer_remaps_color_and_preserves_base_alpha():
    base=Image.new('RGBA',(8,8),(100,100,100,220))
    pixels=np.zeros((8,8,4),dtype=np.uint8)
    pixels[:,:4]=[200,0,0,128]
    pixels[:,4:]=[0,0,200,128]
    uv=np.array([[0,0],[1,0],[1,1],[0,1]],float)
    second=uv.copy();second[:,0]=1-second[:,0]
    result=np.array(alpha_layer(base,Image.fromarray(pixels),uv,second,[[0,1,2],[0,2,3]],8))
    assert tuple(result[2,1]) == (50,50,150,220)
    assert tuple(result[2,6]) == (150,50,50,220)


def test_transparent_layer_leaves_base_unchanged():
    base=Image.new('RGBA',(8,8),(10,20,30,255))
    layer=Image.new('RGBA',(8,8),(255,0,0,0))
    uv=np.array([[0,0],[1,0],[0,1]],float)
    assert np.array_equal(np.array(base),np.array(alpha_layer(base,layer,uv,uv,[[0,1,2]],8)))


def test_eye_repeat_tiles_retain_correspondence_and_uv_transform():
    uv=np.array([[.2,.2],[.8,.2],[.2,.8]])
    for shift in ([1,0],[0,-2]):
        base,second,tile=layer_coordinates(uv+shift,uv,base_repeat=True,transform=[2,2,.1,.1])
        assert np.allclose(base,uv) and np.allclose(tile,shift)
        assert np.allclose(second,[[.2,-.4],[1.4,-.4],[.2,.8]])


def test_outside_uv_triangles_leave_pixels_unchanged_without_blocking_visible_layer():
    base = Image.new('RGBA', (8, 8), (10, 20, 30, 220))
    layer = Image.new('RGBA', (8, 8), (255, 0, 0, 255))
    visible = np.array([[0, 0], [1, 0], [0, 1]], float)
    outside = np.concatenate([visible + offset for offset in
                              ([2, 0], [-3, 0], [0, 2], [0, -3])])
    uv = np.concatenate([outside, visible])
    triangles = np.arange(len(uv)).reshape(-1, 3)
    expected = alpha_layer(base, layer, visible, visible, [[0, 1, 2]], 8)
    actual = alpha_layer(base, layer, uv, uv, triangles, 8)
    assert np.array_equal(np.array(actual), np.array(expected))
    assert tuple(np.array(actual)[1, 1]) == (255, 0, 0, 220)
    assert tuple(np.array(actual)[7, 7]) == (10, 20, 30, 220)


def test_a_white_whole_repeats_off_its_picture_gets_its_iris_once_moved_onto_it():
    from fighter_port.material_bake import one_tile
    eye = np.array([[.235, -1.854], [.77, -1.854], [.235, -1.148]])         # Squirtle's eye white: two repeats down
    assert one_tile(eye) and one_tile([[0, 0], [1, 1]]) and not one_tile([[.5, .5], [1.5, .5]])
    base = Image.new('RGBA', (8, 8), (200, 200, 200, 255))
    iris = Image.new('RGBA', (8, 8), (90, 20, 20, 255))
    second = np.array([[0, 0], [1, 0], [0, 1]], float)
    as_is = np.array(alpha_layer(base, iris, eye, second, [[0, 1, 2]], 8))
    assert (as_is[..., 0] == 200).all()                                      # off the picture: no iris anywhere
    moved, second, _ = layer_coordinates(eye, second, base_repeat=one_tile(eye))
    laid = np.array(alpha_layer(base, iris, moved, second, [[0, 1, 2]], 8))
    assert tuple(laid[2, 3][:3]) == (90, 20, 20)
