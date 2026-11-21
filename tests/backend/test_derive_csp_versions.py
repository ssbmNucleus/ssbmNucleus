"""
derive_csp_versions: every portrait lands in the CSP's 136:188 frame. Off-ratio
uploads are center-cropped (never stretched or letterboxed), SD is always
exactly 136x188, HD is 544x752 only when the source is big enough.
"""
from tests.paths import BACKEND
import io
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(BACKEND))

import vault.routes.storage_costumes as sc  # noqa: E402
import shared.rendering.csp_frame as csp_frame  # noqa: E402


def _png(w, h, color=(10, 200, 30, 255)):
    img = Image.new('RGBA', (w, h), color)
    # a distinct left/right/top/bottom band so cropping is observable
    px = img.load()
    for y in range(h):
        px[0, y] = (255, 0, 0, 255)          # left edge red
        px[w - 1, y] = (0, 0, 255, 255)      # right edge blue
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def _size(data):
    with Image.open(io.BytesIO(data)) as im:
        return im.size


def test_exact_size_passes_through_and_has_no_hd():
    sd, hd = csp_frame.derive_csp_versions(_png(136, 188))
    assert _size(sd) == (136, 188)
    assert hd is None


def test_wide_source_is_center_cropped_not_stretched():
    sd, hd = csp_frame.derive_csp_versions(_png(1000, 752))   # much wider than 136:188
    assert _size(sd) == (136, 188)
    assert _size(hd) == (544, 752)
    with Image.open(io.BytesIO(hd)) as im:
        # the red/blue side bands were cropped away, the centre colour remains
        assert im.getpixel((0, 376))[:3] == (10, 200, 30)
        assert im.getpixel((543, 376))[:3] == (10, 200, 30)


def test_tall_source_is_center_cropped():
    sd, hd = csp_frame.derive_csp_versions(_png(544, 2000))
    assert _size(sd) == (136, 188)
    assert _size(hd) == (544, 752)


def test_small_source_becomes_sd_only():
    sd, hd = csp_frame.derive_csp_versions(_png(100, 100))
    assert _size(sd) == (136, 188)
    assert hd is None


def test_mid_size_source_keeps_native_hd_between_2x_and_4x():
    sd, hd = csp_frame.derive_csp_versions(_png(272, 376))   # exactly 2x
    assert _size(sd) == (136, 188)
    assert _size(hd) == (272, 376)


def test_crop_helper_is_a_no_op_on_ratio():
    img = Image.new('RGBA', (272, 376))
    assert csp_frame.crop_to_csp_aspect(img) is img
