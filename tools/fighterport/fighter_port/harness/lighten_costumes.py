"""Make a port's costumes cheaper for the engine to skin, after they are imported and recoloured.

Usage (cwd app/backend): python lighten_costumes.py <work> [<most joints> <steps>]

Every costume in <work>/package/costumes, and in <work>/package/costumes_w when the port has costumes with held
weapons added (those are the ones a disc is built from), is rewritten in place (`skin_cost.regroup` with weightings made simpler:
a vertex's three heaviest joints, their shares in tenths; each weighting named by as few polygon groups as can
be; pieces that shared their lists go on sharing; pieces no joint names any more are dropped). The file as it
was imported is kept once in a folder beside it (costumes-as-imported, costumes_w-as-imported). The engine blends one matrix for every
weighting a group names, every frame, twice (the fighter and its shadow): a costume imported with the weightings
it came with costs two to five times what the game's own do (measured with the game's own frame clock,
`look_perf`: Byleth 0.73 of a frame beside one other fighter, 0.31 after).

A second run changes nothing: a costume already lightened is told by its cost not going down by more than a
few matrices in a hundred.
"""
import json
import shutil
import sys
from pathlib import Path

import _where  # noqa: E402

sys.path.insert(0, str(_where.BACKEND))
sys.path.insert(0, str(_where.PORT_REPO))
from fighter_port import compat  # noqa: E402

compat.install()
from fighter_port import skin_cost  # noqa: E402

work = Path(sys.argv[1])
weights = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (3, 10)
report = {}
for folder in (work / 'package' / 'costumes', work / 'package' / 'costumes_w'):
    if not folder.is_dir():
        continue
    kept = folder.with_name(folder.name + '-as-imported')
    kept.mkdir(parents=True, exist_ok=True)
    for path in sorted(folder.glob('*.dat')):
        label = f'{folder.name}/{path.name}'
        data = path.read_bytes()
        before = skin_cost.cost(data)
        try:
            made, said = skin_cost.regroup(data, weights=weights)
        except Exception as exc:                        # a costume this cannot take apart stays as it is
            print(f'{label}: left as it is ({type(exc).__name__}: {str(exc)[:120]})')
            report[label] = dict(left=str(exc)[:200])
            continue
        after = said['after']
        if after['matrices'] > before['matrices'] * 0.97:       # (a second pass may shuffle a few either way)
            print(f"{label}: already as light as this makes it ({before['matrices']} matrices)")
            report[label] = dict(matrices=before['matrices'], unchanged=True)
            continue
        if not (kept / path.name).exists():
            shutil.copyfile(path, kept / path.name)
        path.write_bytes(made)
        report[label] = dict(matrices=[before['matrices'], after['matrices']], groups=[before['groups'], after['groups']],
                             bytes=[len(data), len(made)], weights=list(weights))
        print(f"{label}: {before['matrices']} matrices in {before['groups']} groups -> {after['matrices']} in "
              f"{after['groups']}; {len(data):,} -> {len(made):,} bytes")
(work / 'package' / 'lightened.json').write_text(json.dumps(report, indent=1), 'utf-8')
