"""Own-rig packaging must never apply a donor's skeleton pose or head lookup."""
import io
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from fighter_port.compat.bone_lookup import SLOTS
from fighter_port.harness import port_art


def body(color):
    image = Image.new('RGBA', (272, 376))
    draw = ImageDraw.Draw(image)
    draw.ellipse((95, 20, 175, 100), fill=color)
    draw.rectangle((70, 100, 200, 350), fill=color)
    return image


def test_idle_uses_own_archive_but_stocks_use_unobstructed_rest_pose(tmp_path, monkeypatch):
    from core import native_helper
    from shared import mod_files
    (tmp_path / 'rig').mkdir()
    lookup = [255] * len(SLOTS)
    lookup[SLOTS.index('headN')] = 13
    (tmp_path / 'rig/lookup.json').write_text(json.dumps(dict(forward=lookup)))
    animation = tmp_path / 'OwnAJ.dat'
    animation.write_bytes(b'own animation archive')
    monkeypatch.setattr(mod_files, 'dat_roots', lambda _path: ['PlyOwn_joint'])
    calls = []

    def render(args):
        calls.append(args)
        output = Path(args[2])
        if len(calls) == 1:
            assert args[4] == animation
            assert 'PlyOwn_ACTION_Wait1_figatree' in Path(args[3]).read_text()
            body('blue').save(output)
        else:
            assert animation not in args
            body('lime').save(output)
        assert args[args.index('--head-bone') + 1] == '13'
        Path(str(output) + '.head.json').write_text(json.dumps(
            dict(x=135, y=60, width=272, height=376, behindCamera=False)))
        return 0, ''

    monkeypatch.setattr(native_helper, 'native_run', render)
    result = port_art.render_assets(tmp_path / 'body.dat', tmp_path, animation)
    assert len(calls) == 2
    for kind, size in [('hd', (272, 376)), ('csp', (136, 188)), ('stock', (24, 24))]:
        image = Image.open(io.BytesIO(result[kind]))
        assert image.size == size and image.getchannel('A').getbbox()
    stock = np.asarray(Image.open(io.BytesIO(result['stock'])))
    assert np.any(stock[..., 1] > 200) and not np.any(stock[..., 2] > 200)


def test_absent_head_uses_a_visible_whole_body_stock():
    result = port_art.assets(body('orange'))
    stock = Image.open(io.BytesIO(result['stock']))
    assert stock.getchannel('A').getbbox()


def test_empty_portrait_cannot_be_packaged():
    with pytest.raises(ValueError, match='portrait is empty'):
        port_art.assets(Image.new('RGBA', (272, 376)))


def test_empty_stock_cannot_be_packaged():
    with pytest.raises(ValueError, match='stock render is empty'):
        port_art.assets(body('orange'), stock_image=Image.new('RGBA', (272, 376)))
