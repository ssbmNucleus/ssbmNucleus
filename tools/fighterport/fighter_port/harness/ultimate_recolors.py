"""Make the port's costumes from Ultimate's own recolors of the same model, each with its own eyes.

Usage (cwd app/backend): python ultimate_recolors.py <work> <fighter> <donor prefix> <body.dat> [<costume folder>]
<body.dat> is the body as the importer made it (no eyes yet). Writes <work>/package/costumes/<prefix><code>.dat
and costumes.json; clears the old costumes, artwork and weapon costumes so the later steps rebuild them.

The game keeps a fighter's costumes in folders (c00, c01, ...); the ones with the same texture names wear the
same model. <costume folder> names that family (c00 unless given; a fighter with a second body has it under
c01, with its own <body.dat>, and its costumes are added after the ones already there).

The body may be any costume of its family (a ripped model is whichever one the ripper chose): which one is found
by looking, and the others are made from it. Eyes are baked per costume, because the game changes the iris too.
"""
import json
import re
import shutil
import subprocess
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
from fighter_port import eyes, recolors  # noqa: E402

work, fighter, prefix, body = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4])
ROOT = str(_where.ULTIMATE)
CODES = ('Nr', 'Re', 'Bu', 'Gr', 'Ye', 'Wh', 'Bk', 'Pi')          # file codes only; the colours are Ultimate's
BASE = sys.argv[5] if len(sys.argv) > 5 else 'c00'
pkg = work / 'package'
cos = pkg / 'costumes'
before = []
if BASE == 'c00':
    for old in ('costumes', 'costumes_w', 'art'):
        shutil.rmtree(pkg / old, ignore_errors=True)
    cos.mkdir(parents=True)
else:
    before = [r for r in json.loads((cos / 'costumes.json').read_text('utf-8')) if r.get('base', 'c00') != BASE]
    for old in ('costumes_w', 'art'):
        shutil.rmtree(pkg / old, ignore_errors=True)
    shutil.rmtree(cos / 'textures', ignore_errors=True)
    CODES = CODES[len(before):]


def run(args, output):
    code, log = native_run(args)
    if code or not Path(output).is_file():
        raise SystemExit('model tool failed: ' + log[-500:])


node = next(r for r in mod_files.dat_roots(body) if r.startswith('Ply') and r.endswith('_joint') and 'matanim' not in r)
tex = cos / 'textures'
tex.mkdir()
code, log = native_run(['--texture', 'export-all', body, node, tex])
files = sorted(tex.glob('tex_*.png'), key=lambda p: int(re.search(r'(\d+)', p.stem)[1]))
folders = recolors.costume_folders(ROOT, fighter, BASE)
print('costumes that share the model:', list(folders))
all_sources = {f: recolors.sources(ROOT, fighter, f, folders[f]) for f in folders}
# which costume the body is: the one most of its textures are
matches = {f: recolors.match(files, all_sources[f]) for f in folders}
own = max(folders, key=lambda f: (len(matches[f]), f == BASE))
base, found = all_sources[own], matches[own]
print('the body is costume', own, '(textures matched per costume:', {f: len(m) for f, m in matches.items()}, ')')
textures = {i: (name, Image.open(tex / f'tex_{i}.png').size) for i, name in found.items()}
print('costume textures matched to the game:', {i: n for i, (n, _) in textures.items()})
print('game textures the costume does not carry:', sorted(set(base) - {n for n, _ in textures.values()}))

# eyes: baked into the body once per costume whose eye pictures are not the body's own
game_eyes = eyes.game_eyes(S, ROOT, fighter, BASE)
eye_names = {n.lower() for e in game_eyes for n in (e['white'], e['iris'], *[o['texture'] for o in e['overlays']])}
bake = Path(__file__).with_name('bake_eyes.py')
if not bake.exists():
    bake = Path(__file__).parents[1] / 'cloud-oneshot' / 'bake_eyes.py'
baked = {}


def with_eyes(folder):
    """The body with the eyes of costume `folder` (the body itself when the game draws this fighter no eyes this way)."""
    if not game_eyes:
        return body
    same = next((f for f in baked if not eye_names & {n.lower() for n in recolors.changed(all_sources[f], all_sources[folder])}), None)
    if same:
        return baked[same]
    r = subprocess.run([sys.executable, str(bake), str(work), fighter, str(body), BASE, folder], capture_output=True, text=True)
    out = work / ('eyes' if (BASE, folder) == ('c00', 'c00') else f'eyes-{folder}') / 'body_eyes.dat'
    if r.returncode or not out.exists():
        raise SystemExit(f'eye bake for {folder} failed: ' + (r.stdout + r.stderr)[-800:])
    print(f'eyes of {folder}:', [line for line in r.stdout.splitlines() if 'fit the game' in line or 'eyelid' in line][:4])
    baked[folder] = out
    return out


varies = sorted({n for f in folders for n in recolors.changed(base, all_sources[f])} & {n for n, _ in textures.values()})
rows = []
for code, folder in zip(CODES, folders):
    out = cos / f'{prefix}{code}.dat'
    start = with_eyes(folder)
    if folder == own:
        out.write_bytes(Path(start).read_bytes())
        done = []
    else:
        other = all_sources[folder]
        done = recolors.recolor(run, start, node, textures, base, other, out, cos / 'work')
        missed = sorted(set(recolors.changed(base, other)) - set(done) - {n for n in base if n.lower() in eye_names})
        print(f'{folder}: replaced {done}; changed in the game but not in the costume: {missed}')
    rows.append({'code': code, 'name': f'Ultimate {folder}', 'folder': folder, 'file': out.name, 'replaced': done,
                 'base': BASE, 'tone': recolors.tone(all_sources[folder], varies)})
rows = before + rows
(cos / 'costumes.json').write_text(json.dumps(rows, indent=1), 'utf-8')
shutil.rmtree(cos / 'work', ignore_errors=True)
print('costumes:', [(r['code'], r['folder']) for r in rows])
