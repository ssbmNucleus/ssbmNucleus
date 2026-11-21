"""
Tests for shared/rendering/stock_gen.py — deterministic stock-icon generation.

Uses the shipped vanilla assets (utility/assets/vanilla) as ground truth:
the vanilla colorways ARE recolors of the Nr base, so generating "Gr from
Nr + the Gr DAT" must move the icon toward the real Gr icon.
"""
from tests.paths import BACKEND
import sys
import io
import numpy as np
import pytest
from pathlib import Path
from PIL import Image

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

from shared.rendering.stock_gen import (
    STYLE_RECOLOR,
    STYLE_RENDER,
    generate_stock,
    recolor_stock,
    recolor_gw_stock,
    texture_pixel_pairs,
    csp_pixel_pairs,
    csp_head_crop,
    _load_rgba,
)

VANILLA = BACKEND_DIR.parent / 'utility' / 'assets' / 'vanilla'
FOX = VANILLA / 'Fox'

pytestmark = pytest.mark.skipif(
    not (FOX / 'PlFxNr' / 'PlFxNr.dat').exists(),
    reason='vanilla assets not present')

# Most tests compare against Fox's Nr/Gr costumes, CSPs and stock icons, which
# only a full vanilla extraction has; the module guard above checks Nr alone.
FOX_REFERENCE = tuple(FOX / code / name for code in ('PlFxNr', 'PlFxGr')
                      for name in (f'{code}.dat', 'stock.png', 'csp.png'))
needs_fox = pytest.mark.skipif(not all(p.exists() for p in FOX_REFERENCE),
                               reason='vanilla Fox Nr/Gr costumes, CSPs and stock icons not extracted here')


def _mean_err(png_bytes, reference_png_path):
    a = _load_rgba(png_bytes)
    b = _load_rgba(reference_png_path)
    op = b[..., 3] > 0
    return np.abs(a[op][:, :3] - b[op][:, :3]).mean()


class TestTexturePairs:
    @needs_fox
    def test_same_model_pairs(self):
        pairs = texture_pixel_pairs(FOX / 'PlFxNr' / 'PlFxNr.dat',
                                    FOX / 'PlFxGr' / 'PlFxGr.dat')
        assert pairs is not None
        src, dst = pairs
        assert len(src) == len(dst)
        assert len(src) > 100000

    def test_different_model_rejected(self):
        # Fox vs Marth: texture lists do not line up
        marth_dat = VANILLA / 'Marth' / 'PlMsNr' / 'PlMsNr.dat'
        if not marth_dat.exists():
            pytest.skip('Marth vanilla assets missing')
        pairs = texture_pixel_pairs(FOX / 'PlFxNr' / 'PlFxNr.dat', marth_dat)
        assert pairs is None


@needs_fox
class TestRecolorStock:
    def test_identity_transfer_keeps_icon(self):
        """Vanilla DAT vs itself => the icon must come back unchanged."""
        pairs = texture_pixel_pairs(FOX / 'PlFxNr' / 'PlFxNr.dat',
                                    FOX / 'PlFxNr' / 'PlFxNr.dat')
        stock = _load_rgba(FOX / 'PlFxNr' / 'stock.png')
        result = recolor_stock(stock, pairs[0], pairs[1])
        assert np.abs(result - stock).max() < 2

    def test_alpha_preserved(self):
        pairs = texture_pixel_pairs(FOX / 'PlFxNr' / 'PlFxNr.dat',
                                    FOX / 'PlFxGr' / 'PlFxGr.dat')
        stock = _load_rgba(FOX / 'PlFxNr' / 'stock.png')
        result = recolor_stock(stock, pairs[0], pairs[1])
        assert np.array_equal(result[..., 3], stock[..., 3])


class TestGwStock:
    """Mr. Game & Watch's icon is recolored from the vanilla one by CSS slot (his
    model carries no color), so recolor_gw_stock maps the black body to
    GAMEWATCH_COLOR[index] while keeping the gray outline and the alpha. Uses a
    synthetic icon so it needs no G&W vanilla asset."""

    @staticmethod
    def _icon():
        a = np.zeros((2, 2, 4), np.uint8)
        a[0, 0] = (0, 0, 0, 255)       # body (black)
        a[0, 1] = (72, 72, 72, 255)    # outline (vanilla gray level)
        a[1, 0] = (36, 36, 36, 255)    # anti-alias halfway between
        a[1, 1] = (0, 0, 0, 0)         # transparent
        buf = io.BytesIO(); Image.fromarray(a, 'RGBA').save(buf, 'PNG')
        return buf.getvalue()

    def test_index0_is_byte_identical(self):
        b = self._icon()
        assert recolor_gw_stock(b, 0) == b       # black default: nothing to do
        assert recolor_gw_stock(b, None) == b

    def test_body_recolored_outline_and_alpha_kept(self):
        out = _load_rgba(recolor_gw_stock(self._icon(), 1))   # red = (110,0,0)
        assert tuple(out[0, 0][:3]) == (110, 0, 0)            # body -> team color
        assert tuple(out[0, 1][:3]) == (72, 72, 72)           # outline gray kept
        assert tuple(out[1, 0][:3]) == (73, 18, 18)           # AA ramps halfway
        assert np.array_equal(out[..., 3], np.array([[255, 255], [255, 0]]))

    def test_all_four_slots_distinct(self):
        icon = self._icon()
        bodies = [tuple(_load_rgba(recolor_gw_stock(icon, i))[0, 0][:3]) for i in range(4)]
        assert bodies == [(0, 0, 0), (110, 0, 0), (0, 0, 110), (0, 110, 0)]


class TestGenerateStock:
    @pytest.mark.parametrize('cc', ['PlFxGr', 'PlFxLa', 'PlFxOr'])
    def test_colorway_moves_toward_real_icon(self, cc):
        """On the pixels the OFFICIAL colorway icon repainted (vs Nr), the
        generated icon must be closer to it than the unmodified Nr icon is.
        (Restricting to repainted pixels ignores artistic liberties the
        official art takes elsewhere.)"""
        if not all(p.exists() for p in (FOX / 'PlFxNr' / 'stock.png', FOX / cc / f'{cc}.dat', FOX / cc / 'stock.png')):
            pytest.skip(f'vanilla Fox {cc} not extracted here')
        out = generate_stock(VANILLA, 'Fox', 'PlFxNr',
                             modded_dat_path=FOX / cc / f'{cc}.dat')
        assert out is not None
        png, method = out
        assert method == 'texture-diff'
        generated = _load_rgba(png)
        baseline = _load_rgba(FOX / 'PlFxNr' / 'stock.png')
        official = _load_rgba(FOX / cc / 'stock.png')
        repainted = (official[..., 3] > 0) & (
            np.abs(official[..., :3] - baseline[..., :3]).mean(-1) > 30)
        assert repainted.sum() > 10
        err_generated = np.abs(generated[repainted][:, :3]
                               - official[repainted][:, :3]).mean()
        err_baseline = np.abs(baseline[repainted][:, :3]
                              - official[repainted][:, :3]).mean()
        assert err_generated < err_baseline

    @needs_fox
    def test_csp_fallback(self):
        """With no usable DAT, the CSP pair drives the transfer."""
        with open(FOX / 'PlFxGr' / 'csp.png', 'rb') as f:
            csp_bytes = f.read()
        out = generate_stock(VANILLA, 'Fox', 'PlFxNr', modded_csp=csp_bytes)
        assert out is not None
        png, method = out
        assert method == 'csp-diff'
        Image.open(io.BytesIO(png)).verify()

    def test_missing_vanilla_returns_none(self):
        assert generate_stock(VANILLA, 'NoSuchChar', 'PlXxNr',
                              modded_csp=b'not a png') is None

    @needs_fox
    def test_custom_slot_falls_back_to_nr(self):
        """Unknown costume code (custom MEX slot) uses the Nr reference."""
        out = generate_stock(VANILLA, 'Fox', 'PlFxZz',
                             modded_dat_path=FOX / 'PlFxGr' / 'PlFxGr.dat')
        assert out is not None

    def test_no_sources_returns_none(self):
        assert generate_stock(VANILLA, 'Fox', 'PlFxNr') is None

    @needs_fox
    def test_output_is_valid_png_with_alpha(self):
        out = generate_stock(VANILLA, 'Fox', 'PlFxNr',
                             modded_dat_path=FOX / 'PlFxGr' / 'PlFxGr.dat')
        img = Image.open(io.BytesIO(out[0]))
        assert img.size == (24, 24)
        assert 'A' in img.getbands()


@needs_fox
class TestHeadCrop:
    # Fox Nr head-bone projection from the renderer sidecar
    HEAD = {'x': 98.6, 'y': 78.3}

    def test_crop_produces_icon(self):
        csp = _load_rgba(FOX / 'PlFxNr' / 'csp.png')
        icon = csp_head_crop(csp, self.HEAD['x'], self.HEAD['y'])
        assert icon is not None
        assert icon.shape == (24, 24, 4)
        opaque = icon[..., 3] > 0
        assert opaque.sum() > 100          # mostly filled
        # quantized: limited palette on the opaque pixels
        colors = {tuple(px[:3].astype(int)) for px in icon[opaque]}
        assert len(colors) <= 17           # 15 quantized + outline (+rounding)

    def test_model_import_routes_to_crop(self):
        """A DAT whose textures don't align (different model) with a head-shot
        provider must use csp-crop, not color transfer."""
        marth_dat = VANILLA / 'Marth' / 'PlMsNr' / 'PlMsNr.dat'
        if not marth_dat.exists():
            pytest.skip('Marth vanilla assets missing')
        with open(FOX / 'PlFxNr' / 'csp.png', 'rb') as f:
            csp_bytes = f.read()
        calls = []

        def provider():
            calls.append(1)
            return csp_bytes, self.HEAD

        out = generate_stock(VANILLA, 'Fox', 'PlFxNr',
                             modded_dat_path=marth_dat,
                             head_shot_provider=provider)
        assert out is not None
        assert out[1] == 'csp-crop'
        assert calls == [1]

    def test_provider_not_called_for_recolors(self):
        """texture-diff succeeding must not trigger the head-shot render."""
        calls = []

        def provider():
            calls.append(1)
            return None, None

        out = generate_stock(VANILLA, 'Fox', 'PlFxNr',
                             modded_dat_path=FOX / 'PlFxGr' / 'PlFxGr.dat',
                             head_shot_provider=provider)
        assert out is not None
        assert out[1] == 'texture-diff'
        assert calls == []

    def test_no_head_falls_back_to_csp_diff(self):
        marth_dat = VANILLA / 'Marth' / 'PlMsNr' / 'PlMsNr.dat'
        if not marth_dat.exists():
            pytest.skip('Marth vanilla assets missing')
        with open(FOX / 'PlFxGr' / 'csp.png', 'rb') as f:
            csp_bytes = f.read()
        out = generate_stock(VANILLA, 'Fox', 'PlFxNr',
                             modded_dat_path=marth_dat, modded_csp=csp_bytes)
        assert out is not None
        assert out[1] == 'csp-diff'


@needs_fox
class TestForcedStyle:
    """The vault offers the two looks as BUTTONS, so a forced style must win
    over the automatic choice and must never quietly produce the other one."""

    HEAD = {'x': 98.6, 'y': 78.3}

    def _provider(self, calls):
        with open(FOX / 'PlFxNr' / 'csp.png', 'rb') as f:
            csp_bytes = f.read()

        def provider():
            calls.append(1)
            return csp_bytes, self.HEAD
        return provider

    def test_render_style_overrides_a_working_recolor(self):
        """Fox Gr recolors fine automatically; asking for the render must
        still render."""
        calls = []
        out = generate_stock(VANILLA, 'Fox', 'PlFxNr',
                             modded_dat_path=FOX / 'PlFxGr' / 'PlFxGr.dat',
                             head_shot_provider=self._provider(calls),
                             style=STYLE_RENDER)
        assert out is not None
        assert out[1] == 'csp-crop'
        assert calls == [1]

    def test_recolor_style_never_renders(self):
        """A different model auto-routes to the crop; asking for the recolor
        must fail instead, without paying for the render."""
        marth_dat = VANILLA / 'Marth' / 'PlMsNr' / 'PlMsNr.dat'
        if not marth_dat.exists():
            pytest.skip('Marth vanilla assets missing')
        calls = []
        out = generate_stock(VANILLA, 'Fox', 'PlFxNr',
                             modded_dat_path=marth_dat,
                             head_shot_provider=self._provider(calls),
                             style=STYLE_RECOLOR)
        assert out is None
        assert calls == []

    def test_recolor_style_still_uses_csp_diff(self):
        """csp-diff IS a recolor, so it stays available under that style."""
        marth_dat = VANILLA / 'Marth' / 'PlMsNr' / 'PlMsNr.dat'
        if not marth_dat.exists():
            pytest.skip('Marth vanilla assets missing')
        with open(FOX / 'PlFxGr' / 'csp.png', 'rb') as f:
            csp_bytes = f.read()
        out = generate_stock(VANILLA, 'Fox', 'PlFxNr',
                             modded_dat_path=marth_dat, modded_csp=csp_bytes,
                             style=STYLE_RECOLOR)
        assert out is not None
        assert out[1] == 'csp-diff'

    def test_render_style_ignores_the_csp_diff_fallback(self):
        """No provider + render style = nothing, NOT a surprise recolor."""
        with open(FOX / 'PlFxGr' / 'csp.png', 'rb') as f:
            csp_bytes = f.read()
        out = generate_stock(VANILLA, 'Fox', 'PlFxNr',
                             modded_dat_path=FOX / 'PlFxGr' / 'PlFxGr.dat',
                             modded_csp=csp_bytes, style=STYLE_RENDER)
        assert out is None

    def test_auto_is_unchanged(self):
        out = generate_stock(VANILLA, 'Fox', 'PlFxNr',
                             modded_dat_path=FOX / 'PlFxGr' / 'PlFxGr.dat')
        assert out is not None
        assert out[1] == 'texture-diff'
