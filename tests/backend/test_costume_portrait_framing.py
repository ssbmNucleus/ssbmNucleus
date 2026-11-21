"""A portrait has to show the costume, not a patch of its surface.

`shared.rendering.costume_assets` renders a costume with the FIGHTER's curated CSP scene,
which frames the fighter. A fitted model can be a different shape and size from
the body it was fitted to, and then that camera sits inside it: the render comes
back as a slab with no outline, which in the CSS reads as a blank rectangle.
These tests pin the measurement that catches it and the fallback that replaces
it, without going near a renderer.
"""
import io
import logging

import numpy as np
import pytest
from PIL import Image

from shared.rendering import costume_assets as CA

QUIET = logging.getLogger('test-portrait-framing')
QUIET.addHandler(logging.NullHandler())
QUIET.propagate = False


def _portrait(margin, size=(136, 188)):
    """A PNG whose opaque silhouette leaves `margin` transparent pixels all round."""
    image = Image.new('RGBA', size, (0, 0, 0, 0))
    if margin < min(size) // 2:
        body = Image.new('RGBA', (size[0] - 2 * margin, size[1] - 2 * margin), (200, 200, 255, 255))
        image.paste(body, (margin, margin))
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


def test_a_portrait_with_any_background_round_it_shows_the_costume():
    assert CA._edge_cover(_portrait(margin=4)) == 0.
    assert CA._shows_the_costume(_portrait(margin=4), QUIET)
    assert CA._shows_the_costume(_portrait(margin=1), QUIET)


def test_a_costume_that_runs_off_every_side_of_the_frame_does_not():
    filled = _portrait(margin=0)
    assert CA._edge_cover(filled) == pytest.approx(1.)
    assert not CA._shows_the_costume(filled, QUIET)


def test_one_edge_of_outline_is_enough_to_recognise_a_character_by():
    # The bar is on the LEAST covered edge, so a costume that overflows three
    # sides but still shows a profile against the fourth is left alone: that is
    # what most of Melee's own portraits look like.
    image = Image.new('RGBA', (136, 188), (200, 200, 255, 255))
    image.paste(Image.new('RGBA', (30, 188), (0, 0, 0, 0)), (0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    assert CA._shows_the_costume(buffer.getvalue(), QUIET)


def test_the_bar_sits_between_every_portrait_measured_and_the_one_that_was_blank():
    # 120 vanilla portraits: least-covered edge never above 0.103.
    # 36 fitted costumes: never above 0.338. The one a verifier called a blank
    # white rectangle: 0.856.
    assert 0.338 < CA.FRAME_ESCAPES < 0.856


def test_a_render_that_cannot_be_read_never_blocks_a_portrait():
    assert CA._edge_cover(b'not a png') is None
    assert CA._shows_the_costume(b'not a png', QUIET)
    assert CA._shows_the_costume(None, QUIET)


def test_the_fallback_is_used_only_when_it_is_actually_better_framed(monkeypatch, tmp_path):
    """`_fitted_portrait` keeps the fighter's own scene when its own render is no better."""
    shot = tmp_path / 'shot.png'

    def render(dat_path):
        return str(shot), None

    monkeypatch.setitem(__import__('sys').modules, 'generate_csp',
                        type('m', (), {'generate_head_shot': staticmethod(render)}))
    shot.write_bytes(_portrait(margin=0))                   # overflows too: no gain
    assert CA._fitted_portrait('ignored.dat', (136, 188), QUIET) is None

    shot.write_bytes(_portrait(margin=6, size=(272, 376)))  # framed, and resized to the portrait
    framed = CA._fitted_portrait('ignored.dat', (136, 188), QUIET)
    assert framed and Image.open(io.BytesIO(framed)).size == (136, 188)
    assert CA._shows_the_costume(framed, QUIET)


def test_a_fallback_render_that_fails_leaves_the_curated_portrait_alone(monkeypatch):
    def broken(dat_path):
        raise RuntimeError('no renderer here')

    monkeypatch.setitem(__import__('sys').modules, 'generate_csp',
                        type('m', (), {'generate_head_shot': staticmethod(broken)}))
    assert CA._fitted_portrait('ignored.dat', (136, 188), QUIET) is None


def test_the_measure_reads_alpha_and_not_colour():
    # A white costume on a transparent background is the case this exists for;
    # a portrait may not be called blank because its pixels happen to be pale.
    white = Image.new('RGBA', (136, 188), (255, 255, 255, 0))
    white.paste(Image.new('RGBA', (60, 90), (255, 255, 255, 255)), (38, 49))
    buffer = io.BytesIO()
    white.save(buffer, format='PNG')
    assert np.isclose(CA._edge_cover(buffer.getvalue()), 0.)
    assert CA._shows_the_costume(buffer.getvalue(), QUIET)
