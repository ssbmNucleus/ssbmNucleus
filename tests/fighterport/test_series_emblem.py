"""A series emblem's model, cut from its picture."""
from PIL import Image, ImageDraw

from fighter_port import series_emblem as E


def _ring():
    image = Image.new('RGBA', (128, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((10, 10, 118, 118), fill=(255, 255, 255, 255))
    draw.ellipse((40, 40, 88, 88), fill=(0, 0, 0, 0))               # a hole
    draw.rectangle((100, 100, 126, 126), fill=(255, 255, 255, 255))  # a second piece, joined at a corner
    return image


def test_the_model_covers_the_pictures_shape_and_leaves_its_hole():
    image = _ring()
    tris = E.triangles(image)
    inside, spill = E.covered(tris, image)
    assert inside > 0.985 and spill < 0.02
    # nothing is drawn in the middle of the hole
    assert not any(min(x for x, _ in t) < -0.2 < 0.2 < max(x for x, _ in t)
                   and min(y for _, y in t) < -0.2 < 0.2 < max(y for _, y in t)
                   and all(abs(x) < 0.9 and abs(y) < 0.9 for x, y in t) for t in tris)


def test_it_sits_in_the_games_box_and_winds_as_the_games_do():
    tris = E.triangles(_ring())
    xs = [x for t in tris for x, _ in t]
    ys = [y for t in tris for _, y in t]
    assert max(xs) - min(xs) <= E.WIDE + 1e-6 and max(ys) - min(ys) <= E.HIGH + 1e-6
    assert abs(max(xs) + min(xs)) < 0.15 and abs(max(ys) + min(ys)) < 0.15        # about the middle
    for (x1, y1), (x2, y2), (x3, y3) in tris:
        assert (x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1) < 0                   # clockwise, as the game's own


def test_the_file_is_three_corners_a_triangle(tmp_path):
    got = E.write(_ring(), tmp_path / 'emblem.obj')
    lines = (tmp_path / 'emblem.obj').read_text('utf-8').splitlines()
    assert sum(1 for line in lines if line.startswith('v ')) == 3 * got['triangles']
    assert sum(1 for line in lines if line.startswith('f ')) == got['triangles']
    assert lines[-1] == f"f {3 * got['triangles'] - 2} {3 * got['triangles'] - 1} {3 * got['triangles']}"


def test_a_picture_with_no_shape_is_refused():
    import pytest
    with pytest.raises(ValueError):
        E.triangles(Image.new('RGBA', (32, 32), (0, 0, 0, 0)))


def test_thin_lines_are_read_again_at_twice_the_size(tmp_path):
    # Xenoblade's emblem is rings of lines one or two pixels wide: traced through the pixels' middles they had no
    # width, the cut covered 97.2% and the sounds stage stopped. A picture of thin rings is cut at twice its size.
    image = Image.new('RGBA', (128, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for r in (20, 28, 36, 44, 52):
        draw.ellipse((64 - r, 64 - r, 64 + r, 64 + r), outline=(255, 255, 255, 255), width=3)
    draw.line((0, 127, 127, 0), fill=(255, 255, 255, 255), width=3)
    draw.rectangle((70, 4, 120, 30), fill=(255, 255, 255, 255))           # and a plain block, as the emblem's blade
    plain = E.covered(E.triangles(image), image)
    assert plain[0] < E.LEAST                       # the plain reading falls short
    got = E.write(image, tmp_path / 'emblem.obj')
    assert got['larger'] == 2 and got['covered'] >= E.LEAST
    # a picture the plain reading covers is cut as it was
    assert E.write(_ring(), tmp_path / 'ring.obj')['larger'] == 1
