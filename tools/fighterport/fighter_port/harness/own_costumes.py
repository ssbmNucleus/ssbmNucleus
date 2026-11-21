"""Every costume of a fighter on its own skeleton: the game's own model and pictures of each costume folder, built
the way the first was (`own_skeleton.body`, then the texture animations), into the package's costumes folder.

Usage (cwd app/backend): python own_costumes.py <work> <fighter> <donor> <game root> [--allow-large]
Reads <work>/rig and <work>/data (the `prepare` stage). Writes <work>/package/costumes/<prefix><code>.dat and
costumes.json, and clears the artwork so that it is made again. The pieces, joints and per-frame cost of every
costume must be the first's: a costume that differs stops the stage. Only a costume whose folder holds a model of
its own (`recolors.own_model`: a game written out by its reader, whose outfits differ under the same pictures'
names) may cost otherwise; its pieces and joints must still be the first's.

Each costume's bytes are printed by kind (pictures by stored format, display lists, the rest), and a costume over
`skin_cost.COSTUME_MOST` bytes stops the stage at the first one, before the others are made: every file of a match
shares one heap of 6.6 MB, a costume is held whole once a colour, and two of 2.9 MB did not load (the game hangs
after stage select: pick the fighter against itself in another colour). --allow-large builds them all the same
(to look at one alone, or after the heap has been read in the game with the pictures looked at).
"""
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from fighter_port import compat  # noqa: E402

compat.install()
from fighter_port import fighters, own_skeleton, recolors, skin_cost  # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith('--')]
allow_large = '--allow-large' in sys.argv[1:]
work, fighter, donor, root = Path(args[0]), args[1], args[2], Path(args[3])
if fighters.donor_problem(donor):
    raise SystemExit(fighters.donor_problem(donor))
names = own_skeleton.DONOR[donor]
prefix = names['costume'][:-len('Nr.dat')]
CODES = ('Nr', 'Re', 'Bu', 'Gr', 'Ye', 'Wh', 'Bk', 'Pi')          # file codes only; the colours are the game's
frozen = json.loads((work / 'rig' / f'rig-{fighter}.json').read_text('utf-8'))
folders = recolors.costume_folders(root, fighter, 'c00')
print('costumes that share the model:', list(folders))
if len(folders) > len(CODES):
    print(f'  the game has {len(folders)}; the first {len(CODES)} are made (a fighter here has {len(CODES)} file codes)')
sources = {f: recolors.sources(root, fighter, f, folders[f]) for f in folders}
varies = sorted({n for f in folders for n in recolors.changed(sources['c00'], sources[f])})
print('pictures that change between costumes:', varies)
rows, first, sizes = [], None, {}
for code, folder in zip(CODES, folders):
    began = time.time()
    plain, receipt = own_skeleton.body(fighter, root, work, frozen, donor, work / 'project' / 'files',
                                       log=lambda *a: None, costume=folder)
    costume, _ = own_skeleton.materials(plain, work / 'data' / names['data'], donor, plain.with_name(f'{fighter}_static.dat'))
    from fighter_port import own_opacity
    own_opacity.costume(costume, root, fighter, receipt, names['joint'])
    got = skin_cost.cost(costume.read_bytes())
    same = (receipt['pieces'], got['joints'], got['matrices'])
    if first is None:
        first = same
    elif same[:2] != first[:2] or (same[2] != first[2] and not recolors.own_model(root, fighter, folder)):
        raise SystemExit(f'{folder}: its pieces, joints or cost are not the first costume\'s: {same} against {first}')
    elif same[2] != first[2]:
        # a costume that is another model under the same pictures' names (Slap City's other outfits): the pieces
        # and joints the fighter's data names are the first's, its cost is its own (each costume is its own file)
        print(f'   {folder} is a model of its own: {same[2]} matrices against the first\'s {first[2]}')
    kinds, lines, stop = skin_cost.costume_room(f'{prefix}{code}.dat ({folder})', costume.read_bytes(), allow_large)
    sizes[f'{prefix}{code}.dat'] = kinds
    print('\n'.join(lines))
    print(f'   {got["matrices"]} matrices, {time.time() - began:.0f} s', flush=True)
    if stop:
        raise SystemExit(stop + ' STOPPED before the other costumes are made.')
    rows.append({'code': code, 'name': f'Ultimate {folder}', 'folder': folder, 'file': f'{prefix}{code}.dat', 'base': 'c00',
                 # the model it is made from: the first's, or one of its own (`recolors.own_model`)
                 'model': folder if recolors.own_model(root, fighter, folder) else 'c00',
                 'tone': recolors.tone(sources[folder], varies), 'made': str(costume)})
pkg = work / 'package'
for old in ('costumes', 'art', 'costumes_w'):
    shutil.rmtree(pkg / old, ignore_errors=True)
(pkg / 'costumes').mkdir(parents=True)
for r in rows:
    shutil.copyfile(r.pop('made'), pkg / 'costumes' / r['file'])
(pkg / 'costumes' / 'costumes.json').write_text(json.dumps(rows, indent=1), 'utf-8')
(work / 'tmp').mkdir(exist_ok=True)
(work / 'tmp' / 'costume-bytes.json').write_text(json.dumps(sizes, indent=1), 'utf-8')
largest = max(sizes, key=lambda n: sizes[n]['bytes'])
print(f"costumes: {[(r['code'], r['folder']) for r in rows]}; the largest is {largest}, {sizes[largest]['bytes']:,} bytes "
      f"(the stage stops over {skin_cost.COSTUME_MOST:,}" + ('; --allow-large was given)' if allow_large else ')'))
