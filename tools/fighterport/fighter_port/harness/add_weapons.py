"""Build the held weapons and put them in each costume.

Usage (cwd app/backend): python add_weapons.py <work> <fighter> <donor prefix e.g. PlMs>
Reads <work>/port/weapons.json (written by fighter_port.oneshot) and the costumes in
<work>/package/costumes; writes <work>/package/costumes_w/. A weapon that bends
(the whip) becomes joints of the costume itself, and the port's data files that
go with those joints are written to <work>/port/final_w/.
"""
import json
import sys
import _where  # noqa: E402
from pathlib import Path

sys.path.insert(0, str(_where.BACKEND))
sys.path.insert(0, str(_where.PORT_REPO))
sys.path.insert(0, str(_where.SSBH))
import ssbh_data_py as S  # noqa: E402
from core.config import HSDRAW_EXE  # noqa: E402
from vault.echo import datroot  # noqa: E402
from vault.echo.subactions import Dat  # noqa: E402
from fighter_port import chain_weapon, weapons  # noqa: E402

work, fighter, prefix = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
ROOT = str(_where.ULTIMATE)
port = work / 'port'
info = json.loads((port / 'weapons.json').read_text('utf-8'))
order, chains = info['order'], info.get('chains', {})
if not order and not chains:
    raise SystemExit('no held weapons for this fighter')

to_joint = weapons.to_joint(port / 'clips', next(port.glob('*.joints.json')), info['attach']['target'], info['hold'])
out = work / 'package' / 'weapons'
tex_dirs = [work / 'input' / 'src' / 'Byleth' / 'textures']
attach = int(info['attach']['target'].split('_')[1])

# rigid weapons: one add-on model each
source_bones = json.loads((next(p for p in sorted((port / 'clips').iterdir()) if (p / 'transfer.json').exists())
                            / 'decoded' / 'source.joints.json').read_text('utf-8'))['order']
models = weapons.hold_models(S, ROOT, fighter) if order else {}
addons = {}
for name in order:
    # each weapon in the axes of the body bone it hangs on
    root = models[name]['root']
    its_joint = weapons.to_joint(port / 'clips', next(port.glob('*.joints.json')), info['attach']['target'],
                                 root if root in source_bones else info['hold'])
    smd, missing = weapons.write_smd(models, name, its_joint, out, tex_dirs)
    addon, log = weapons.build_addon(HSDRAW_EXE, smd, attach, out)
    addons[name] = addon.read_bytes()
    print(f'{name}: {models[name]["triangles"]} triangles, textures missing {missing}, add-on {addon.stat().st_size} bytes;',
          log.strip().splitlines()[-1][-60:])

# bending weapons: joints and skinned mesh, to be hung on the costume's own skeleton
grafts = {}
for name in chains:
    chain = chain_weapon.read(S, ROOT, fighter, name, chain_weapon.stems_of(chains[name]['clips']))
    smd, missing = chain_weapon.write_smd(chain, to_joint, out, tex_dirs)
    addon, log = weapons.build_addon(HSDRAW_EXE, smd, 0, out)
    grafts[name] = addon.read_bytes()
    print(f'{name} (bends): {len(chain["bones"])} joints, {chain["triangles"]} triangles, textures missing {missing}, '
          f'{addon.stat().st_size} bytes;', log.strip().splitlines()[-1][-60:])

dst = work / 'package' / 'costumes_w'
dst.mkdir(exist_ok=True)
grafted = {}
for f in sorted((work / 'package' / 'costumes').glob(f'{prefix}??.dat')):
    data, reps = f.read_bytes(), []
    for name, blob in grafts.items():
        data, rep = chain_weapon.graft(data, blob, datroot, Dat)
        if grafted.setdefault(name, rep) != rep:
            raise SystemExit(f'{f.name}: the {name} lands on other joint or mesh numbers than in the first costume')
        reps.append({k: (v if k != 'rest' else '...') for k, v in rep.items()} | {'meshes': len(rep['meshes'])})
    for name in order:
        data, rep = weapons.add_to_costume(data, addons[name], info['variants'][name], datroot, Dat)
        reps.append(rep)
    (dst / f.name).write_bytes(data)
    print(f.name, f.stat().st_size, '->', len(data), reps)

if chains:
    report = chain_weapon.finish(S, ROOT, fighter, port, port / 'final_w', grafted, HSDRAW_EXE, datroot, Dat)
    joints = max(r['joints'] for r in report.values())
    (work / 'package' / 'chain.json').write_text(json.dumps({'joints': joints}), 'utf-8')
    print('port data with the bending weapon:', port / 'final_w', {k: (v['part_tables'], len(v['clips'])) for k, v in report.items()},
          'joints', joints)
