"""Local portraits for a port's own skeleton; no game or donor pose required.

Use the port's compiled idle when available, otherwise its rest pose. The
existing renderer fits that body and projects its own head joint for stocks.
Explicit artwork already in package/art remains the packager's first choice.
"""
import io
import json
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from fighter_port.compat.bone_lookup import SLOTS


def png(image):
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    return stream.getvalue()


def assets(image, head=None, stock_image=None):
    """Fit the full portrait; crop stocks using this render's head coordinates."""
    from fighter_port.harness.game_art import fitted
    from shared.rendering.stock_gen import csp_head_crop, csp_whole_body_crop

    image = image.convert('RGBA')
    if not image.getchannel('A').point(lambda v: 255 if v > 40 else 0).getbbox():
        raise ValueError('The port portrait is empty; no artwork was saved.')
    stock_image = (stock_image if stock_image is not None else image).convert('RGBA')
    rgba = np.asarray(stock_image)
    icon = None
    if head and not head.get('behindCamera', False):
        # The renderer reports its logical CSP dimensions. Scale the projected
        # point if the output uses a higher resolution.
        x = float(head['x']) * stock_image.width / head['width']
        y = float(head['y']) * stock_image.height / head['height']
        if 0 <= x < stock_image.width and 0 <= y < stock_image.height:
            icon = csp_head_crop(rgba, x, y)
    if icon is None or not np.any(icon[..., 3] > 40):
        icon = csp_whole_body_crop(rgba)
    if icon is None or not np.any(icon[..., 3] > 40):
        raise ValueError('The port stock render is empty; no artwork was saved.')
    return dict(hd=png(fitted(image, (272, 376))),
                csp=png(fitted(image, (136, 188))),
                stock=png(Image.fromarray(icon.astype(np.uint8))))


def render_assets(path, work, animation=None):
    """Render one costume using the own-rig lookup and optional compiled AJ."""
    from core.native_helper import native_run
    from shared.mod_files import dat_roots

    path, work = Path(path), Path(work)
    lookup = json.loads((work / 'rig' / 'lookup.json').read_text('utf-8'))
    head = lookup['forward'][SLOTS.index('headN')]
    roots = dat_roots(path)
    joint = next(r for r in roots if r.startswith('Ply') and r.endswith('_joint')
                 and 'matanim' not in r)
    with tempfile.TemporaryDirectory(prefix='port_art_') as temp:
        output = Path(temp) / 'portrait.png'
        args = ['--csp', path, output]
        if animation is not None:
            animation = Path(animation)
            if not animation.is_file():
                raise ValueError(f'The port animation archive is missing: {animation}')
            pose = Path(temp) / 'idle.yml'
            pose.write_text(f'frame: 0\nanimSymbol: {joint[:-6]}_ACTION_Wait1_figatree\n'
                            'settings:\n  renderBones: false\n  renderObjects: Visible\n', 'utf-8')
            args.extend([pose, animation])
        # Despite the flag's name, this frames the WHOLE body and disables the
        # debug skeleton. It works after the port's own idle is applied too.
        args.extend(['--scale', '2', '--head-shot', '--head-shot-yaw', '20'])
        if head != 255:
            args.extend(['--head-bone', str(head)])
        code, log = native_run(args)
        if code or not output.is_file():
            raise ValueError('Could not render the port portrait: ' + log[-1200:])
        with Image.open(output) as source:
            image = source.convert('RGBA')
        stock_image = image
        if animation is not None:
            # The shared head crop expects the rest silhouette. In an idle pose
            # a raised arm can cross the head and be mistaken for the face.
            output = Path(temp) / 'stock.png'
            stock_args = ['--csp', path, output, '--scale', '2', '--head-shot', '--head-shot-yaw', '20']
            if head != 255:
                stock_args.extend(['--head-bone', str(head)])
            code, log = native_run(stock_args)
            if code or not output.is_file():
                raise ValueError('Could not render the port stock: ' + log[-1200:])
            with Image.open(output) as source:
                stock_image = source.convert('RGBA')
        projected = Path(str(output) + '.head.json')
        head_point = json.loads(projected.read_text('utf-8')) if projected.is_file() else None
        return assets(image, head_point, stock_image)
