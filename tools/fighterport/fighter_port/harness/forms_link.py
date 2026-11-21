"""The disc of a fighter of forms: every form in one project, linked as one fighter (fighter_port/forms.py).

Usage (cwd app/backend, absolute paths):
  python forms_link.py <group work> <group> <donor> <out.iso> <form work> [<form work> ...]

Each form's work folder holds a finished port of that form (the stages up to and with costumes). In order:
  1. each form's package is made and installed into the group's project (<group work>/project, made fresh by the
     group's `project` stage), the first form under the group's name (it is the one the screen shows)
  2. the ring: each form's partner is the next (forms.link_project), and the character select screen keeps the first
     form's slot alone (forms.one_on_the_screen)
  3. the code that loads every form of the ring with the match (forms.preload_code), added to the project's codes
  4. the disc, and its padding made safe as every test disc's is
and <group work>/link.json says what was done: each form's numbers, the ring, the slots taken off the screen.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import _where  # noqa: E402

sys.path.insert(0, str(_where.BACKEND))
sys.path.insert(0, str(_where.PORT_REPO))
from core.config import MEXCLI_PATH, PROJECT_ROOT, get_subprocess_args  # noqa: E402
import mexcli.commands  # noqa: E402
from fighter_port import fighters, forms  # noqa: E402
from shared.rendering.hitbox_elements import CHAR_PREFIXES  # noqa: E402

group_work, group, donor, iso_out = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4])
form_works = [Path(p) for p in sys.argv[5:]]
entry = fighters.FORMS[group]
names = [n for _, n in entry['forms']]
if len(form_works) != len(names):
    raise SystemExit(f'{group} has {len(names)} forms; {len(form_works)} work folders were given')
proj = group_work / 'project' / 'project.mexproj'
if not proj.exists():
    raise SystemExit(f'no project at {proj}: the group\'s project stage makes it')
prefix = CHAR_PREFIXES[donor]
shown = [entry.get('name') or group] + names[1:]           # the first form carries the group's name

# ---- 1. every form installed
for work, name in zip(form_works, shown):
    env = dict(os.environ, PORT_PROJECT=str(proj), PORT_NO_EXPORT='1')
    costume = work / 'package' / 'costumes' / f'{prefix}Nr.dat'
    argv = [sys.executable, str(_where.HERE / 'package_build.py'), 'build', str(work), name, donor, str(costume), str(iso_out)]
    print(f'== {name} ({work.name})', flush=True)
    r = subprocess.run(argv, cwd=str(_where.BACKEND), env=env, capture_output=True, text=True)
    print((r.stdout or '')[-1500:], (r.stderr or '')[-1500:], flush=True)
    if r.returncode:
        raise SystemExit(f'{name}: the package did not install (exit {r.returncode})')

listing = mexcli.commands.run_json(['list-fighters', proj])
by_name = {f['name']: f for f in listing.get('fighters') or []}
missing = [n for n in shown if n not in by_name]
if missing:
    raise SystemExit(f'not in the project after installing: {missing}')
kinds = [int(by_name[n]['internalId']) for n in shown]
externals = [int(by_name[n]['externalId']) for n in shown]
print('forms:', dict(zip(shown, zip(kinds, externals))))

# ---- 3. the preload (added before the files are edited by hand: MexCLI saves the project as it holds it)
code = '\n'.join(forms.preload_code([kinds]))
gct = proj.parent / 'files' / 'codes.gct'
before = gct.stat().st_size if gct.exists() else 0
r = subprocess.run([str(MEXCLI_PATH), 'add-code', str(proj), f'{entry.get("name") or group}: load every form', code],
                   capture_output=True, text=True, cwd=str(PROJECT_ROOT), **get_subprocess_args())
print('add-code rc', r.returncode, (r.stdout or '')[-300:], (r.stderr or '')[-300:])
after = gct.stat().st_size if gct.exists() else 0
words = sum(len(line.split()) for line in code.split('\n')) * 4
if r.returncode or after < before + words:
    raise SystemExit(f'the preload code did not go in (codes.gct {before:,} -> {after:,} bytes, the code is {words} bytes)')

# ---- 2. the ring and the one slot on the screen
data = proj.parent / 'data'
ring = forms.link_project(data, kinds)
css_path = data / 'css.json'
css, gone = forms.one_on_the_screen(json.loads(css_path.read_text('utf-8')), externals)
css_path.write_text(json.dumps(css, indent=2), 'utf-8')
print('ring:', ring, '; taken off the screen:', gone)

# ---- 4. the disc
from mexcli.project import MexManager  # noqa: E402
from core import iso_reads  # noqa: E402
if iso_out.exists():
    iso_out.unlink()                                        # (a disc of this group's from an earlier run)
iso_out.parent.mkdir(parents=True, exist_ok=True)
res = MexManager(str(MEXCLI_PATH), str(proj)).export_iso(str(iso_out), progress_callback=lambda p, m: None)
print('export:', {k: res[k] for k in list(res)[:6]} if isinstance(res, dict) else res)
if not iso_out.exists():
    raise SystemExit('no disc was made')
iso_reads.ensure_padding(iso_out)
link = {'group': group, 'forms': [{'name': n, 'work': str(w), 'internal': k, 'external': e}
                                  for n, w, k, e in zip(shown, form_works, kinds, externals)],
        'ring': {str(k): v for k, v in ring.items()}, 'off_the_screen': gone,
        'preload': {'address': hex(forms.PRELOAD_AT), 'lines': code.split('\n'), 'codes_gct': [before, after]},
        'iso': str(iso_out), 'iso_bytes': iso_out.stat().st_size}
(group_work / 'link.json').write_text(json.dumps(link, indent=1), 'utf-8')
print('iso:', iso_out, iso_out.stat().st_size)
