"""Assemble a model-based Echo with five costumes and freshly rendered artwork.

The donor's gameplay files remain byte-for-byte intact. Work happens in a private
directory; callers publish only after every costume and image has succeeded.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile

from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import package

COSTUMES = (('Nr', 'Original', None), ('Re', 'Red', 0),
            ('Bu', 'Blue', 220), ('Gr', 'Green', 125), ('Ye', 'Gold', 45))


def png_bytes(image):
    out = io.BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()


def checked_image(data, size=None, *, allow_empty=False):
    with Image.open(io.BytesIO(data)) as source:
        if source.format != 'PNG' or source.width * source.height > 16_777_216:
            raise ValueError('Clone artwork must be a PNG up to 16 megapixels.')
        image = source.convert('RGBA')
    if not allow_empty and not image.getchannel('A').getbbox():
        raise ValueError('Clone artwork rendered empty; no character was saved.')
    return ImageOps.contain(image, size, Image.Resampling.LANCZOS) if size else image


def banner(text, size):
    """Fit the whole name, including descenders, inside the game's fixed banner."""
    image = Image.new('RGBA', size)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=24)
    for height in range(size[1] - 4, 5, -1):
        font = ImageFont.load_default(size=height)
        bounds = draw.textbbox((0, 0), text, font=font, stroke_width=1)
        if bounds[2] - bounds[0] <= size[0] - 4:
            break
    x = (size[0] - (bounds[2] - bounds[0])) / 2 - bounds[0]
    y = (size[1] - (bounds[3] - bounds[1])) / 2 - bounds[1]
    draw.text((x, y), text, font=font, fill='white', stroke_width=1, stroke_fill='black')
    return png_bytes(image)


def css_icon(csp):
    image = checked_image(csp)
    left, top, right, bottom = image.getchannel('A').getbbox()
    # Upper-body crop keeps the imported character recognizable at CSS size.
    image = image.crop((left, top, right, top + max(1, round((bottom - top) * .55))))
    image = ImageOps.contain(image, (64, 56), Image.Resampling.LANCZOS)
    result = Image.new('RGBA', (64, 56))
    result.alpha_composite(image, ((64 - image.width) // 2, (56 - image.height) // 2))
    return png_bytes(result)


def tint_texture(rgba, hue, mode):
    """Basic colorways preserve shading/alpha; neutral mode keeps colored accents."""
    import numpy as np
    from shared.rendering.palette import rgb_to_hsl, hsl_to_rgb
    _, saturation, lightness = rgb_to_hsl(rgba[..., :3].astype(float))
    # Feather selection rather than leaving a hard edge through silver armor's
    # compression/shading. Colored markings remain unchanged in neutral mode.
    weight = np.clip((60 - saturation) / 40, 0, 1) if mode == 'neutral' else np.ones_like(lightness)
    weight = weight * weight * (3 - 2 * weight)
    shadow = np.clip((lightness - 4) / 10, 0, 1)
    weight *= shadow * shadow * (3 - 2 * shadow)
    weight *= rgba[..., 3] >= 128
    target = hsl_to_rgb(np.full_like(lightness, hue), np.full_like(lightness, 58), lightness * .9)
    result = rgba.copy()
    result[..., :3] = np.rint(rgba[..., :3] * (1 - weight[..., None]) + target * weight[..., None]).astype(np.uint8)
    return result


def recolor(base, directory, prefix, mode, progress):
    import numpy as np
    from shared.mod_files import dat_roots
    from core.native_helper import native_run as _native_run

    def run(args, output):
        code, log = _native_run(args)
        if code or not output.is_file():
            raise ValueError('Clone texture generation failed: ' + log[-500:])

    node = next(r for r in dat_roots(base) if r.startswith('Ply') and r.endswith('_joint') and 'matanim' not in r)
    texture_dir = directory / 'textures'
    texture_dir.mkdir()
    code, log = _native_run(['--texture', 'export-all', base, node, texture_dir])
    textures = sorted(texture_dir.glob('tex_*.png'), key=lambda p: int(re.search(r'(\d+)', p.stem)[1]))
    if code or not textures or len(textures) > 128:
        raise ValueError('Automatic recolors need 1–128 model textures. Supply four prepared costume files instead.')
    originals = []
    for png in textures:
        index = int(re.search(r'(\d+)', png.stem)[1])
        originals.append((index, np.array(checked_image(png.read_bytes(), allow_empty=True))))
    paths = [base]
    for code, name, hue in COSTUMES[1:]:
        progress(f'Making {name.lower()} costume')
        current = base
        changed = 0
        for i, (texture_index, pixels) in enumerate(originals):
            tinted = tint_texture(pixels, hue, mode)
            if np.array_equal(tinted, pixels):
                continue
            png = directory / f'{code}-{i}.png'
            Image.fromarray(tinted).save(png)
            output = directory / f'{code}-step-{i}.dat'
            run(['--texture', 'import', current, node, texture_index, png, output], output)
            current, changed = output, changed + 1
        if not changed:
            raise ValueError(f'No pixels changed for the {name.lower()} costume. Choose another recolor mode or supply prepared files.')
        final = directory / f'{prefix}{code}.dat'
        final.write_bytes(current.read_bytes())
        paths.append(final)
    if len({hashlib.sha256(p.read_bytes()).digest() for p in paths}) != 5:
        raise ValueError('Recolor output contains duplicate costumes; no character was saved.')
    return paths


def render_assets(path, donor):
    from shared.rendering.portrait import render_portrait
    from shared.rendering.costume_assets import build_stock
    from shared.rendering.stock_gen import STYLE_RENDER
    rendered = render_portrait(path, donor, scale=2)
    if not rendered.path or not Path(rendered.path).is_file():
        raise ValueError('Could not render the clone portrait; no character was saved.')
    hd = Path(rendered.path).read_bytes()
    image = checked_image(hd)
    csp = png_bytes(image.resize((136, 188), Image.Resampling.LANCZOS))
    stock, source, _ = build_stock(donor, path.stem, path.read_bytes(),
        dat_path=str(path), aligned_csp=csp, vanilla_fallback=False, style=STYLE_RENDER)
    if source != 'generated' or not stock:
        raise ValueError('Could not render the clone stock icon; no character was saved.')
    checked_image(stock)
    return {'csp': csp, 'hd': hd, 'stock': stock}


def assemble(donor_zip, echo, paths, artwork, roots):
    """Return the complete fighter package, metadata and loose vault assets."""
    if len(paths) != 5 or len(artwork) != 5 or len(roots) != 5:
        raise ValueError('A clone needs the original and four complete recolors.')
    materialized, _ = package.materialize(donor_zip, echo)
    with zipfile.ZipFile(io.BytesIO(materialized)) as donor:
        fighter = json.loads(donor.read('fighter.json'))
        old_costumes = {Path((c.get('file') or {}).get('fileName', '')).stem + '.zip'
                        for c in fighter.get('costumes', [])}
        members = {n: donor.read(n) for n in donor.namelist()
                   if n not in old_costumes and n != 'fighter.json'}
    fighter['assets'] = {'cssIcon': 'css\\icon', 'resultBannerBig': 'rst\\big_banner',
                         'resultSmallBig': 'rst\\small_banner'}
    fighter.update(redCostumeIndex=1, blueCostumeIndex=2, greenCostumeIndex=3)
    template = copy.deepcopy(fighter['costumes'][0])
    fighter['costumes'] = []
    loose = {'css_icon.png': css_icon(artwork[0]['csp'])}
    members['icon.png'] = loose['css_icon.png']
    members['big_banner.png'] = banner(echo['name'].upper(), (256, 28))
    members['small_banner.png'] = banner(echo['short_name'].upper(), (120, 24))
    for i, ((code, name, _), path, art, symbols) in enumerate(zip(COSTUMES, paths, artwork, roots)):
        stem = echo['donor_prefix'] + code
        costume = copy.deepcopy(template)
        costume.update(name=name, icon=None, csp=None, colorSmashGroup=-200 - i)
        costume['file'] = dict(fileName=stem + '.dat', visibilityIndex=0,
                               jointSymbol=symbols['joint'], materialSymbol=symbols.get('material', ''))
        fighter['costumes'].append(costume)
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr(stem + '.dat', path.read_bytes())
            z.writestr('csp.png', art['csp'])
            z.writestr('stc.png', art['stock'])
        members[stem + '.zip'] = inner.getvalue()
        loose[f'csp_{i}.png'], loose[f'stock_{i}.png'] = art['csp'], art['stock']
        loose[f'costumes/{stem}_csp_hd.png'] = art['hd']
    members['fighter.json'] = json.dumps(fighter, indent=2).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return output.getvalue(), fighter, loose


def contact_sheet(name, artwork):
    sheet = Image.new('RGB', (5 * 204, 340), '#17202b')
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=17)
    draw.text((14, 10), name + ' - costume assets', font=font, fill='white')
    for i, ((_, label, _), art) in enumerate(zip(COSTUMES, artwork)):
        portrait = checked_image(art['hd'], (184, 245))
        x = i * 204
        sheet.paste(portrait, (x + (204 - portrait.width) // 2, 42), portrait)
        stock = checked_image(art['stock']).resize((36, 36), Image.Resampling.NEAREST)
        sheet.paste(stock, (x + 14, 294), stock)
        draw.text((x + 61, 304), label, font=font, fill='white')
    return png_bytes(sheet)
