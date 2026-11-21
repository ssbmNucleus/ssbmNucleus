"""Make the port's costumes from Brawl's own recolours of the same model.

Usage (cwd app/backend): python brawl_recolors.py <work> <fighter> <donor prefix> <body.dat> [<rip.zip>]
<rip.zip>: the rip as it came (before brawl_model.py), when the importer made the eyes blink but had no lid to draw:
the lids of the blink are drawn from the game's own blinking faces, which the rip still holds.
<work> holds the extracted disc (the fighter's FitXxx00.pac, 01, ... under it). <body.dat> is the body as the
importer made it. Writes <work>/package/costumes/<prefix><code>.dat and costumes.json; clears the old costumes
and artwork so the later steps rebuild them.

A Brawl fighter's costumes are files of the same model with other pictures under the same names. The body may
be any one of them (a ripped model is whichever the ripper chose): which one is found by looking, and the others
are made from it by putting their pictures in.
"""
import json
import re
import shutil
import sys
import _where  # noqa: E402
from pathlib import Path

sys.path.insert(0, str(_where.BACKEND))
sys.path.insert(0, str(_where.PORT_REPO))
from PIL import Image  # noqa: E402
from core.native_helper import native_run  # noqa: E402
from shared import mod_files  # noqa: E402
from fighter_port import recolors  # noqa: E402
from echo_brawl import textures  # noqa: E402

work, fighter, prefix, body = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4])
CODES = ('Nr', 'Re', 'Bu', 'Gr', 'Ye', 'Wh', 'Bk', 'Pi')          # file codes only; the colours are the game's
pkg = work / 'package'
cos = pkg / 'costumes'
keep = work / 'body-as-imported.dat'                                # the body may be one of the files about to be cleared
if body.resolve() != keep.resolve():
    shutil.copyfile(body, keep)
body = keep
for old in ('costumes', 'costumes_w', 'art'):
    shutil.rmtree(pkg / old, ignore_errors=True)
cos.mkdir(parents=True)


def run(args, output):
    code, log = native_run(args)
    if code or not Path(output).is_file():
        raise SystemExit('model tool failed: ' + log[-500:])


node = next(r for r in mod_files.dat_roots(body) if r.startswith('Ply') and r.endswith('_joint') and 'matanim' not in r)
tex = cos / 'textures'
tex.mkdir()
code, log = native_run(['--texture', 'export-all', body, node, tex])
files = sorted(tex.glob('tex_*.png'), key=lambda p: int(re.search(r'(\d+)', p.stem)[1]))
every = textures.costumes(work, fighter)
if not every:
    raise SystemExit(f'no costume files of {fighter} under {work}')
print('costumes on the disc:', sorted(every), '; pictures in the body:', len(files))
# which costume the body is: the one most of its pictures are
matches = {n: recolors.match(files, every[n]) for n in every}
own = max(every, key=lambda n: (len(matches[n]), -n))
base, found = every[own], matches[own]
print('the body is costume', own, '(pictures matched per costume:', {n: len(m) for n, m in matches.items()}, ')')
pictures = {i: (name, Image.open(tex / f'tex_{i}.png').size) for i, name in found.items()}
print('body pictures matched to the game:', {i: n for i, (n, _) in pictures.items()})
print('game pictures the body does not carry:', sorted(set(base) - {n for n, _ in pictures.values()}))
# the body's pictures are repeated or clamped as the game's materials draw them (an eye's iris is laid on once)
import numpy as np  # noqa: E402
from vault.echo.subactions import Dat  # noqa: E402
from fighter_port import eyes  # noqa: E402
named = dict(found)
for path in files:                                      # the small ones the matcher passes over: the same size, the same picture
    index = int(re.search(r'(\d+)', path.stem)[1])
    if index not in named:
        mine = Image.open(path).convert('RGBA')
        for name, picture in base.items():
            if picture.size == mine.size and np.abs(np.asarray(picture.convert('RGBA'), int) - np.asarray(mine, int)).mean() < 8:
                named[index] = name
                break
modes = textures.wraps(work, fighter)
rows_ = json.loads(re.search(r'\[\{.*\}\]', native_run(['--dobj-info', body, node])[1], re.S)[0])
fix = {r['dobj']: modes[named[t]] for r in rows_ for t in r['textures'][:1]
       if t in named and named[t] in modes and tuple(modes[named[t]]) != (1, 1)}
if fix:
    wrapped = work / 'body-wrapped.dat'
    wrapped.write_bytes(eyes.wrap(body.read_bytes(), node, fix, Dat))
    body = wrapped
    print('pictures laid on once, as the game does (piece: picture):', {n: named[r['textures'][0]] for r in rows_ for n in [r['dobj']] if n in fix})
# the lids of the blink, from the game's own blinking faces (the importer says where the eye's picture was cut from)
rip = Path(sys.argv[5]) if len(sys.argv) > 5 else None
made = Path(sys.argv[4]).resolve().parent.parent / '3-build' / 'eyes.json'
if rip and made.is_file():
    import io
    import zipfile
    from shared.rendering import datprobe
    from echo_brawl import model
    from fighter_port.oneshot import EYES_DONOR
    from fighter_port.port import DONOR_PREFIX
    said = json.loads(made.read_text('utf-8'))
    donor = next((d for d, pre in DONOR_PREFIX.items() if pre == prefix), None)
    if said.get('crop') and said.get('eye_texture_size') and donor in EYES_DONOR:
        with zipfile.ZipFile(rip) as z:
            dae_name = next(n for n in z.namelist() if n.lower().endswith('.dae'))
            drawn = {n.rsplit('/', 1)[-1]: Image.open(io.BytesIO(z.read(n))) for n in z.namelist() if n.lower().endswith('.png')}
            lids = model.lids(z.read(dae_name).decode('utf-8'), drawn, model.parts(work, fighter), tuple(said['eye_texture_size']))
        x, y, w, h = said['crop']
        over = {EYES_DONOR[donor][state]: lid.crop((x, y, x + w, y + h)) for state, lid in lids.items() if state in EYES_DONOR[donor]}
        if over:
            data, done = eyes.frames(body.read_bytes(), over, datprobe.DatFile, datprobe.decode_image, work / 'lids')
            lidded = work / 'body-lids.dat'
            lidded.write_bytes(data)
            body = lidded
            print("blink frames drawn from the game's own blinking faces (piece: frames):", done)
varies = sorted({n for k in every for n in recolors.changed(base, every[k])} & {n for n, _ in pictures.values()})
rows = []
for code, number in zip(CODES, sorted(every)):
    out = cos / f'{prefix}{code}.dat'
    if number == own:
        out.write_bytes(body.read_bytes())
        done = []
    else:
        done = recolors.recolor(run, body, node, pictures, base, every[number], out, cos / 'work')
        missed = sorted(set(recolors.changed(base, every[number])) - set(done))
        print(f'costume {number}: replaced {done}; changed in the game but not in the body: {missed}')
    rows.append({'code': code, 'name': f'Brawl costume {number}', 'folder': f'{number:02d}', 'file': out.name, 'replaced': done,
                 'tone': recolors.tone_of_changes(every, number, varies),
                 'team': recolors.team_shares(every, number, varies)})
(cos / 'costumes.json').write_text(json.dumps(rows, indent=1), 'utf-8')
shutil.rmtree(cos / 'work', ignore_errors=True)
print('costumes:', [(r['code'], r['folder'], r['team']) for r in rows])
