"""Mr. Game & Watch's portrait and stock icon for a model imported onto him.

His own model draws no image: the game paints it the slot's flat fill, so the portrait is rebuilt as a flat
silhouette with his outline and the stock icon is the vanilla one recoloured. A model imported onto him draws its
own textures (tinted by the fill, white for an import: core.gaw_colors.import_sidecar), so both are made as for any
import. No renderer runs here: the render, the probe and the icon makers are replaced.
"""
import sys

import pytest

from tests.paths import BACKEND

sys.path.insert(0, str(BACKEND.parent / 'utility' / 'tools' / 'processor'))
generate_csp = pytest.importorskip('generate_csp')

from shared.rendering import costume_assets as CA  # noqa: E402
from shared.rendering import datprobe  # noqa: E402

WHITE = {'fill': (255, 255, 255), 'outline': (255, 255, 255, 128)}


@pytest.mark.parametrize('textured, rebuilt', [(False, True), (True, False)])
def test_the_flat_outline_redraw_is_for_his_own_flat_model_only(monkeypatch, textured, rebuilt):
    calls = []
    monkeypatch.setattr(generate_csp, '_gw_body_color', lambda *a, override_rgb=None: override_rgb)
    monkeypatch.setattr(generate_csp, '_gw_apply_outline', lambda path, body, outline_rgba=None: calls.append(body))
    monkeypatch.setattr(datprobe, 'samples_textures', lambda path: textured)
    generate_csp._gw_finish('csp.png', 'Mr. Game & Watch', 'PlGwNr.dat', 0, WHITE['fill'], WHITE['outline'])
    assert calls == ([WHITE['fill']] if rebuilt else [])


def test_no_other_fighter_is_redrawn(monkeypatch):
    monkeypatch.setattr(generate_csp, '_gw_apply_outline', lambda *a, **k: pytest.fail('redrawn'))
    monkeypatch.setattr(datprobe, 'samples_textures', lambda path: pytest.fail('probed'))
    generate_csp._gw_finish('csp.png', 'Mario', 'PlMrNr.dat')


@pytest.mark.parametrize('textured', [False, True])
def test_his_stock_icon_is_recoloured_only_for_his_own_flat_model(monkeypatch, textured):
    monkeypatch.setattr(CA, '_draws_own_textures', lambda data, path=None: textured)
    monkeypatch.setattr(CA, '_vanilla_stock', lambda character, code: (b'vanilla icon', 'vanilla'))
    monkeypatch.setattr(CA, 'recolor_gw_stock_rgb', lambda data, fill: b'recoloured ' + bytes(fill))
    monkeypatch.setattr(CA, 'generate_stock', lambda *a, **k: (b'made from the model', 'csp-crop'))
    data, source, method = CA.build_stock('Mr. Game & Watch', 'PlGwNr', b'dat', gw_colors=WHITE)
    if textured:
        assert (data, source, method) == (b'made from the model', 'generated', 'csp-crop')
    else:
        assert (data, method) == (b'recoloured ' + bytes(WHITE['fill']), 'gw_recolor')


def test_an_unreadable_file_draws_no_image(tmp_path):
    bad = tmp_path / 'bad.dat'
    bad.write_bytes(b'not a dat')
    assert datprobe.samples_textures(bad) is False
    assert datprobe.samples_textures(tmp_path / 'missing.dat') is False
