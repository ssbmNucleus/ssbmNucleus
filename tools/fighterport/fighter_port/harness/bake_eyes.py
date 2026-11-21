"""Give a ported costume its eyes: irises baked into each eye's own texture, and no opaque patch over them.

Usage (cwd app/backend): python bake_eyes.py <work> <fighter> [<body.dat> [<model folder> [<pictures folder>]]]
Reads <work>/body/2-swap/4-export/<donor>.dat (or the file given), writes <work>/eyes/body_eyes.dat and
<work>/eyes/eyes.png (each eye's new picture, enlarged, to look at). <model folder> is the game costume whose
model the body is (c00; a second body is c01); <pictures folder> the costume whose eye pictures are baked
(the game changes the iris between costumes of one model). The output folder is <work>/eyes for c00's
own pictures, else <work>/eyes-<pictures folder>.
"""
import io
import json
import re
import sys
import _where  # noqa: E402
from pathlib import Path

sys.path.insert(0, str(_where.BACKEND))
sys.path.insert(0, str(_where.PORT_REPO))
sys.path.insert(0, str(_where.SSBH))
import ssbh_data_py as S  # noqa: E402
from PIL import Image  # noqa: E402
from core.native_helper import native_run  # noqa: E402
from shared import mod_files  # noqa: E402
from vault.echo.subactions import Dat  # noqa: E402
from fighter_port import eyes  # noqa: E402

work, fighter = Path(sys.argv[1]), sys.argv[2]
ROOT = str(_where.ULTIMATE)
body = Path(sys.argv[3]) if len(sys.argv) > 3 else next((work / 'body' / '2-swap' / '4-export').glob('*.dat'))
FOLDER = sys.argv[4] if len(sys.argv) > 4 else 'c00'
PICTURES = sys.argv[5] if len(sys.argv) > 5 else FOLDER
out = work / ('eyes' if (FOLDER, PICTURES) == ('c00', 'c00') else f'eyes-{PICTURES}')
if out.exists():
    import shutil
    shutil.rmtree(out)                                  # nothing kept from an earlier body
out.mkdir()
node = next(r for r in mod_files.dat_roots(body) if r.startswith('Ply') and r.endswith('_joint') and 'matanim' not in r)


def run(args, output=None):
    code, log = native_run(args)
    if code or (output is not None and not Path(output).is_file()):
        raise SystemExit('model tool failed: ' + log[-500:])
    return log


tex = out / 'tex'
if not tex.exists():
    tex.mkdir()
    run(['--texture', 'export-all', body, node, tex])
dae = out / 'body.dae'
if not dae.exists():
    run(['--model', 'export', body, node, dae], dae)
info = json.loads(re.search(r'\[\{.*\}\]', run(['--dobj-info', body, node]), re.S)[0])
textures = {int(re.search(r'(\d+)', p.stem)[1]): Image.open(p).convert('RGBA') for p in tex.glob('tex_*.png')}

game = eyes.game_eyes(S, ROOT, fighter, FOLDER)
print('the game draws', len(game), 'eyes in two layers:', [(e['material'], e['white'], e['iris'], e['transform'],
                                                         [o['texture'] for o in e['overlays']]) for e in game])
images = eyes.pictures(ROOT, fighter, [n for e in game for n in (e['white'], e['iris'], *[o['texture'] for o in e['overlays']])], PICTURES)
found, root = eyes.pieces(dae, info, textures, game, images)
d = Dat(body.read_bytes())
offsets = eyes.piece_offsets(d, next(off for name, off in d.roots if name == node))
current, sheet, baked = body, [], {}
for p in sorted(found, key=lambda p: p['dobj']):
    size = textures[p['texture']].size
    if eyes.picture_size(d, offsets[p['dobj']]) != size:
        raise SystemExit(f"piece {p['dobj']}: the file's own list of pieces is not in the model tool's order")
    M, off = eyes.coordinates(p)
    image = eyes.bake(p, images, size)
    png = out / f"eye_{p['dobj']}.png"
    image.save(png)
    baked[p['dobj']] = image
    step = out / f"step_{p['dobj']}.dat"
    run(['--texture', 'import', current, node, p['texture'], png, step], step)
    current = step
    print(f"piece {p['dobj']} (texture {p['texture']}, {size[0]}x{size[1]}) is the game's {p['eye']['material']}: "
          f"its coordinates fit the game's to within {off:.3f}")
    sheet.append(image.resize((size[0] * 4, size[1] * 4), Image.NEAREST))
data = Path(current).read_bytes()
from shared.rendering import datprobe  # noqa: E402
lid, face = eyes.lid_colour(root, info, textures, found)
print('eyelid colour, from the skin around the eyes on piece', face, ':', None if lid is None else [round(v) for v in lid])
data, frames = eyes.blink(data, baked, info, datprobe.DatFile, datprobe.decode_image, out, lid)
print('blink frames redrawn over the baked eye (piece: frames):', frames)
patches = eyes.cover(root, info, textures, found) if any(e['overlays'] for e in game) else []
if patches:
    data = eyes.empty(data, node, patches, Dat)
    print('pieces drawn as an opaque patch over the eyes, now drawing nothing (their picture is baked into the eyes):', patches)
final = out / 'body_eyes.dat'
final.write_bytes(data)
both = Image.new('RGB', (sum(s.width for s in sheet) + 8 * len(sheet), max(s.height for s in sheet)), (40, 40, 40))
x = 0
for s in sheet:
    both.paste(s.convert('RGB'), (x, 0))
    x += s.width + 8
both.save(out / 'eyes.png')
print('costume with eyes:', final, final.stat().st_size)
