"""Build a port through the normal recipe, without requiring a gameplay harness.

The own-skeleton route prepares the source body, clips, scripts, sounds and
costumes, packages portraits, builds one final disc and verifies its files. Packaging
renders portraits directly; it does not need gameplay screenshots.

`--calibrate` additionally runs the optional developer gameplay round and uses
its pictures for art. Explicit `--only round`, `--from art`, or `--tests` also
opt into those stages. They are development tools, never a user prerequisite.

`--from`, `--to` and `--only` select stages. Status preserves the results of
previous stages. PORT_CHECKLIST.md records detailed fidelity work separately:
done, difference, not applicable, or open with an explanation. An unfilled
fidelity line does not block packaging, and a successful build does not imply
that unimplemented character mechanics or gameplay checks are complete.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
HARNESS = HERE / 'harness'
CHECKLIST = HERE / 'PORT_CHECKLIST.md'
STAGES = ('preflight', 'model', 'project', 'driver', 'sounds', 'costumes', 'build', 'verify', 'round')
OWN_STAGES = ('preflight', 'project', 'prepare', 'driver', 'sounds', 'costumes', 'firstdisc', 'verify', 'round', 'art',
              'build')
# A fighter of forms (`fighters.FORMS`: `port <group> --own`): each form is ported in <work>/<form> by the stages
# above (to and with costumes), then the group's own: a fresh project, the link (every form installed, the ring, the
# preload, one disc: harness/forms_link.py), each form's portraits and stock icons cut from pictures of it on that
# disc (game_art.py, by its own number on the roster: a form off the character screen is still a fighter), the
# project and the disc again with them, and the files checked for every form and for the room they need together.
FORM_STAGES = ('forms', 'project', 'link', 'art', 'build', 'verify')
SAID_ALOUD = ('preflight',)                              # stages whose whole log is printed, not only where it is
ANSWERS = ('done', 'difference', 'not applicable')
OPEN = 'open'                                            # looked at, and still owed: it says what is owed, and counts as unanswered
DONOR_PREFIX = {'Marth': 'PlMs'}                         # the donor's file prefix, for costume file names


# ---------------------------------------------------------------------------------------- the list
def lines(path=CHECKLIST):
    """The checklist's lines, each with a number that stays put while lines are only added at a section's end:
    [{'id': '6.3', 'section': 'Each special, ...', 'text': ...}]. A line is a top-level bullet of a numbered
    section (its indented continuation lines belong to it)."""
    out, section, number, count = [], None, None, 0
    for raw in Path(path).read_text('utf-8').splitlines():
        head = re.match(r'## (\d+)\. (.+)', raw)
        if head:
            number, section, count = int(head[1]), head[2].strip(), 0
            continue
        if raw.startswith('## '):
            number = None                               # a heading without a number: not part of the list
        if number is None:
            continue
        if raw.startswith('- '):
            count += 1
            out.append({'id': f'{number}.{count}', 'section': section, 'text': raw[2:].strip()})
        elif raw.startswith('  ') and out and out[-1]['id'].startswith(f'{number}.') and raw.strip() and not raw.lstrip().startswith('|'):
            out[-1]['text'] += ' ' + raw.strip()
    return out


def answers(work):
    path = Path(work) / 'checklist.json'
    return json.loads(path.read_text('utf-8')) if path.exists() else {}


def record(work, line, answer, how):
    """Answer one line: `answer` is one of ANSWERS, `how` says how it was seen (or why not). -> the answers."""
    if answer not in ANSWERS + (OPEN,):
        raise ValueError(f'an answer is one of {ANSWERS}, or {OPEN!r} with what is still owed')
    if not str(how or '').strip():
        raise ValueError('an answer says how it is known')
    known = {row['id'] for row in lines()}
    if line not in known:
        raise ValueError(f'no line {line} in the checklist')
    got = answers(work)
    got[line] = {'answer': answer, 'how': str(how).strip()}
    path = Path(work) / 'checklist.json'
    path.write_text(json.dumps({k: got[k] for k in sorted(got, key=lambda i: [int(x) for x in i.split('.')])}, indent=1), 'utf-8')
    return got


def unanswered(work):
    """The lines a port still owes: never answered, or recorded as `open` (looked at, not finished)."""
    got = answers(work)
    return [row for row in lines() if got.get(row['id'], {}).get('answer') not in ANSWERS]


def open_lines(work):
    """The lines recorded as `open`, each with what was said is owed: looked at, and not finished. They are among
    `unanswered(work)`; this is what tells them from the lines nobody has looked at."""
    got = answers(work)
    return [{'id': row['id'], 'line': row['text'], 'how': got[row['id']]['how']}
            for row in lines() if got.get(row['id'], {}).get('answer') == OPEN]


def differences(work):
    """The list given with the port: every line answered as a difference, with what was said."""
    got = answers(work)
    return [{'id': row['id'], 'line': row['text'], 'how': got[row['id']]['how']}
            for row in lines() if got.get(row['id'], {}).get('answer') == 'difference']


# ---------------------------------------------------------------------------------------- the stages
def _env(repo):
    env = dict(os.environ, NUCLEUS_REPO=str(repo), PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8')
    env['PYTHONPATH'] = os.pathsep.join([str(Path(repo) / 'app' / 'backend'), str(HERE.parent)]
                                        + ([env['SSBH_DATA_PY']] if env.get('SSBH_DATA_PY') else [])
                                        + ([env['PYTHONPATH']] if env.get('PYTHONPATH') else []))
    return env


def calibration_requested(a):
    """Calibration is an explicit developer request, including legacy stage flags."""
    return bool(getattr(a, 'calibrate', False) or getattr(a, 'tests', None) or
                any(getattr(a, flag, None) in ('round', 'art') for flag in ('start', 'to', 'only')))


def stage_order(a, forms=False):
    order = FORM_STAGES if forms else OWN_STAGES if getattr(a, 'own', False) else STAGES
    if calibration_requested(a):
        return order
    # The preliminary disc exists for the optional gameplay round. Packaging
    # renders its own portraits, so normal users need one final disc, then checks.
    # Keep explicit firstdisc requests usable without opting into a harness.
    if getattr(a, 'own', False) and not forms and not any(
            getattr(a, flag, None) == 'firstdisc' for flag in ('start', 'to', 'only')):
        return ('preflight', 'project', 'prepare', 'driver', 'sounds', 'costumes', 'build', 'verify')
    return tuple(s for s in order if s not in ('round', 'art'))


def commands(a):
    """{stage: [argv, ...]} for one port. Every script runs from the app's backend folder."""
    work, py = Path(a.work), sys.executable
    prefix = DONOR_PREFIX.get(a.donor, 'Pl' + a.donor[:2])
    body = str(a.body or work / 'package' / 'costumes' / f'{prefix}Nr.dat')
    recolour = ([py, str(HARNESS / 'brawl_recolors.py'), str(work), a.fighter, prefix, body]
                + ([str(a.rip)] if getattr(a, 'rip', None) else []) if a.game == 'brawl' else
                [py, str(HARNESS / 'ultimate_recolors.py'), str(work), a.fighter, prefix, body])
    ready = work / 'input' / f'{a.fighter}-ready.zip'
    own_tests = (['--own'] + list(a.tests)) if getattr(a, 'tests', None) else []
    verify = [py, '-m', 'fighter_port.verify', str(work), '--json']
    large = ['--allow-large'] if getattr(a, 'allow_large', False) else []
    preflight = ([py, '-m', 'fighter_port.preflight', a.fighter, '--game', a.game, '--donor', a.donor, '--work', str(work),
                  '--root', str(a.root)] + (['--own'] if getattr(a, 'own', False) else [])
                 + (['--mextk', str(a.mextk)] if a.mextk else []) + (['--iso', str(a.iso)] if a.iso else [])
                 + (['--body', str(a.body)] if getattr(a, 'body', None) else []) + large)
    if getattr(a, 'own', False):
        costume = str(work / 'package' / 'costumes' / f'{prefix}Nr.dat')
        project = [py, str(HARNESS / 'make_project.py'), str(work), a.donor]
        disc = lambda iso: [py, str(HARNESS / 'package_build.py'), 'build', str(work), a.name, a.donor, costume] + ([str(iso)] if iso else [])  # noqa: E731
        return {
            'preflight': [preflight],
            'project': [project],
            'prepare': [[py, str(HARNESS / 'own_prepare.py'), str(work), a.fighter, a.donor, str(a.root)]],
            'driver': [[py, '-m', 'fighter_port.oneshot', a.fighter, '--donor', a.donor, '--root', str(a.root),
                        '--donor-zip', str(work / f'{a.donor}.zip'), '--own', str(work), '--work', str(work / 'port')]
                       + (['--game', a.game] if a.game != 'ultimate' else [])
                       + (['--mextk', str(a.mextk)] if a.mextk else [])],
            # (with the sounds: what says whose fighter this is outside the fight, its series emblem and its fanfare)
            'sounds': [[py, str(HARNESS / 'make_sounds.py'), str(work), a.fighter, a.name, a.donor, a.game, str(a.root)],
                       [py, str(HARNESS / 'own_identity.py'), str(work), a.fighter, str(a.root)]],
            'costumes': [[py, str(HARNESS / 'own_costumes.py'), str(work), a.fighter, a.donor, str(a.root)] + large],
            # a build needs a project that has not got the fighter yet: each disc starts from a fresh one
            'firstdisc': [project, disc(work / 'tmp' / 'first.iso')],
            # (the artwork is not due yet: it is cut from the round's pictures)
            'verify': [verify + (['--art-later'] if calibration_requested(a) else [])],
            'round': [[py, str(HARNESS / 'round.py'), str(work), str(work / 'tmp' / 'first.iso'), a.fighter] + own_tests],
            'art': [[py, str(HARNESS / 'game_art.py'), str(work), '--shots', str(work / 'round' / 'shots')]],
            'build': [project, disc(a.iso), verify],
        }
    return {
        'preflight': [preflight],
        'model': ([[py, str(HARNESS / 'brawl_model.py'), str(work), a.fighter, str(a.rip), str(ready)]]
                  if a.game == 'brawl' and getattr(a, 'rip', None) else []),
        'driver': [[py, '-m', 'fighter_port.oneshot', a.fighter, '--game', a.game, '--donor', a.donor, '--root', str(a.root),
                    '--donor-zip', str(work / f'{a.donor}.zip'), '--work', str(work / 'port')]
                   + (['--mextk', str(a.mextk)] if a.mextk else [])],
        'project': [[py, str(HARNESS / 'make_project.py'), str(work), a.donor]],
        'sounds': [[py, str(HARNESS / 'make_sounds.py'), str(work), a.fighter, a.name, a.donor, a.game, str(a.root)]],
        # (then every costume is made cheaper for the engine to skin: see the script)
        'costumes': [recolour, [py, str(HARNESS / 'lighten_costumes.py'), str(work)]],
        'build': [[py, str(HARNESS / 'package_build.py'), 'build', str(work), a.name, a.donor,
                   str(work / 'package' / 'costumes' / f'{prefix}Nr.dat')] + ([str(a.iso)] if a.iso else [])],
        # (the file checks were written against a fighter on its own skeleton: on this route they report and do
        # not stop the run)
        'verify': [verify + ['--report-only']],
        'round': ([[py, str(HARNESS / 'round.py'), str(work), str(a.iso), a.fighter, '--no-portraits'] + own_tests]
                  if a.iso else []),
    }


def chosen(order, start=None, to=None, only=None):
    """The stages one run does, in order: all of them; from `start` on; up to and with `to`; `only` that one.
    A stage that is not one of this route's is refused by name (it used to mean "from the first", so `--from
    prepare` without `--own` quietly ran everything)."""
    for flag, stage in (('--from', start), ('--to', to), ('--only', only)):
        if stage is not None and stage not in order:
            raise SystemExit(f"{flag} {stage}: not a stage of this route (its stages: {', '.join(order)})")
    if only is not None:
        if start is not None or to is not None:
            raise SystemExit('--only names the one stage to run: it goes with neither --from nor --to')
        return [only]
    first = order.index(start) if start is not None else 0
    last = order.index(to) if to is not None else len(order) - 1
    if last < first:
        raise SystemExit(f'--to {to} comes before --from {start}')
    return list(order[first:last + 1])



def stage_current(stages, name):
    row=stages.get(name) or {}
    return bool(row.get('ok') and not row.get('stale') and not row.get('running'))


def begin_stage(stages, name, out):
    """Keep previous logs as history, but never call an old artifact current after its inputs change."""
    artifacts=('firstdisc','link','round','art','build','verify')
    changed={
        'project':artifacts,
        'model':('driver','sounds','costumes')+artifacts,
        'prepare':('driver','sounds','costumes')+artifacts,
        'driver':('sounds',)+artifacts,
        'sounds':artifacts,
        'costumes':artifacts,
        'forms':('project','link','art','build','verify'),
        'firstdisc':('round','art','build','verify'),
        'link':('art','build','verify'),
        'round':('art','build'),
        'art':('build','verify'),
        'build':('verify',),
    }
    for target in changed.get(name, ()):
        if target in stages:
            stages[target]=dict(stages[target],stale=True,invalidated_by=name)
    stages[name]={'ok':False,'running':True,'log':str(out)}

def run(a, log=print):
    """Run the stages asked for (`chosen`: --from, --to, --only). -> the status written to <work>/port/status.json;
    its 'ran' are the stages of this run."""
    repo = Path(a.repo or os.environ.get('NUCLEUS_REPO') or '')
    if not (repo / 'app' / 'backend').is_dir():
        raise SystemExit('NUCLEUS_REPO (or --repo) must name the app checkout')
    from . import fighters
    if a.fighter in fighters.FORMS:
        return run_forms(a, repo, log)
    order = stage_order(a)
    todo = chosen(order, getattr(a, 'start', None), getattr(a, 'to', None), getattr(a, 'only', None))
    work = Path(a.work)
    (work / 'tmp').mkdir(parents=True, exist_ok=True)
    (work / 'port').mkdir(parents=True, exist_ok=True)
    status_path = work / 'port' / 'status.json'
    status = json.loads(status_path.read_text('utf-8')) if status_path.exists() else {}
    status.update(fighter=a.fighter, game=a.game, donor=a.donor, name=a.name, ran=[],
                  calibration_requested=calibration_requested(a), checklist_scope='optional fidelity backlog')
    status.pop('implementation', None)  # Recomputed after this run; never preserve an old current-driver claim.
    stages = status.setdefault('stages', {})
    plan = commands(a)
    for stage in todo:
        began = time.time()
        out = work / 'tmp' / f'port-{stage}.log'
        begin_stage(stages,stage,out)
        status.setdefault('owed', {})['stages'] = [s for s in order if not stage_current(stages,s)]
        status_path.write_text(json.dumps(status, indent=1), 'utf-8')
        if any(Path(argv[1]).name == 'make_project.py' for argv in plan[stage]):
            import shutil
            shutil.rmtree(work / 'project', ignore_errors=True)   # the fighter goes into a project that has not got it
            if stage in ('firstdisc', 'build'):
                target = Path(next(argv for argv in plan[stage] if Path(argv[1]).name == 'package_build.py')[-1])
                if target.suffix == '.iso' and target.exists():
                    target.unlink()                               # the disc tool will not write over a disc
        ok = True
        with open(out, 'w', encoding='utf-8') as f:
            for argv in plan[stage]:
                cwd = HERE.parent if argv[1] == '-m' else repo / 'app' / 'backend'
                r = subprocess.run(argv, cwd=str(cwd), env=_env(repo), stdout=f, stderr=subprocess.STDOUT)
                ok = ok and r.returncode == 0
                if not ok:
                    break
        stages[stage] = {'ok': ok, 'seconds': round(time.time() - began), 'log': str(out)}
        if ok and stage == 'build' and any(argv[1:3] == ['-m','fighter_port.verify'] for argv in plan[stage]):
            stages['verify']={'ok':True,'log':str(out),'performed_by':'build'}
        status['ran'].append(stage)
        if stage in SAID_ALOUD:                         # (what it found is the point of it: said here, not only filed)
            log(out.read_text('utf-8', errors='replace').rstrip())
        log(f"{stage}: {'done' if ok else 'FAILED'} in {stages[stage]['seconds']} s ({out})")
        status_path.write_text(json.dumps(status, indent=1), 'utf-8')
        if not ok:
            break
    left, looked = unanswered(work), open_lines(work)
    status['owed'] = {'stages': [s for s in order if not stage_current(stages,s)],
                      'checklist lines unanswered': len(left), 'first': [f"{r['id']} {r['text'][:90]}" for r in left[:5]],
                      # (among the unanswered: the ones looked at and not finished, each with what is owed)
                      'checklist lines open': len(looked), 'open': [f"{r['id']} {r['how']}" for r in looked]}
    status_path.write_text(json.dumps(status, indent=1), 'utf-8')
    log(f"build stages remaining: {status['owed']['stages'] or 'none'}")
    status.pop('implementation', None)
    report_path = work / 'port' / 'report.json'
    if report_path.exists():
        from .port_receipt import summarize
        status['implementation'] = summarize(json.loads(report_path.read_text('utf-8')))
        current = stage_current(stages,'driver')
        status['implementation']['current_driver'] = current
        log('special runtime: ' + (status['implementation']['runtime'] if current else 'awaiting a successful driver rebuild'))
        if current and status['implementation']['limitations']:
            log(f"known implementation limits: {len(status['implementation']['limitations'])} (port/report.json; package/PORT_NOTES.txt)")
    if calibration_requested(a):
        log(f'fidelity backlog: {len(left)} lines unanswered; {len(looked)} recorded open')
    status_path.write_text(json.dumps(status, indent=1), 'utf-8')
    return status


def run_forms(a, repo, log=print):
    """A fighter of forms: every form ported by itself in <work>/<form> (`run`, to and with costumes; `--forms-from`
    starts each form's run at a stage), then the group's stages (FORM_STAGES). -> the group's status, as `run`'s."""
    import argparse as _argparse
    import shutil
    from . import fighters, forms, verify
    if not getattr(a, 'own', False):
        raise SystemExit('a fighter of forms is ported on the own-skeleton route: give --own')
    entry = fighters.FORMS[a.fighter]
    work = Path(a.work)
    order = stage_order(a, forms=True)
    todo = chosen(order, getattr(a, 'start', None), getattr(a, 'to', None), getattr(a, 'only', None))
    (work / 'tmp').mkdir(parents=True, exist_ok=True)
    (work / 'port').mkdir(parents=True, exist_ok=True)
    status_path = work / 'port' / 'status.json'
    status = json.loads(status_path.read_text('utf-8')) if status_path.exists() else {}
    status.update(fighter=a.fighter, game=a.game, donor=a.donor, name=a.name, forms=[f for f, _ in entry['forms']], ran=[])
    stages = status.setdefault('stages', {})
    py = sys.executable
    for stage in todo:
        began, ok = time.time(), True
        out = work / 'tmp' / f'port-{stage}.log'
        begin_stage(stages,stage,out)
        status.setdefault('owed', {})['stages'] = [s for s in order if not stage_current(stages,s)]
        status_path.write_text(json.dumps(status, indent=1), 'utf-8')
        if stage == 'forms':
            lines = []

            def one(form, name, start):
                sub = _argparse.Namespace(**dict(vars(a), fighter=form, name=name, work=str(work / form), iso=None,
                                                 start=start, to='costumes', only=None))
                (work / form).mkdir(parents=True, exist_ok=True)
                donor_zip = work / f'{a.donor}.zip'
                if donor_zip.exists() and not (work / form / donor_zip.name).exists():
                    shutil.copyfile(donor_zip, work / form / donor_zip.name)
                got = run(sub, log=lambda *m: lines.append(' '.join(str(x) for x in m)))
                said = f'== {form}: ' + ', '.join(f"{s} {'ok' if got['stages'][s]['ok'] else 'FAILED'}" for s in got['ran'])
                lines.append(said)
                log(said)
                return all(got['stages'][s]['ok'] for s in got['ran'])
            for form, name in entry['forms']:
                ok = one(form, name, getattr(a, 'forms_from', None))
                if not ok:
                    break
            # room (13.7): every form's costume is loaded for each player; while a match of the room does not fit the
            # files' heap, the form with the largest costume is made again with smaller pictures
            works = [work / form for form, _ in entry['forms']]
            for _ in range(2 * len(works) if ok else 0):
                short = forms.heap_short(works)
                pick = forms.shrink_side(works) if short else None
                if pick is None:
                    if short:
                        log(f"room: {'; '.join(short)} does not fit and no form's pictures can be smaller")
                    break
                form_dir, side = pick
                (form_dir / 'forms-side.json').write_text(json.dumps({'side': side, 'why': short}), 'utf-8')
                log(f"room: {'; '.join(short)} does not fit: {form_dir.name}'s pictures made again at {side} a side")
                ok = one(form_dir.name, dict(entry['forms'])[form_dir.name], 'prepare')
                if not ok:
                    break
            out.write_text('\n'.join(lines), 'utf-8')
        elif stage in ('project', 'link', 'build'):
            iso = Path(a.iso) if a.iso else work / f'{a.fighter}.iso'
            make = [[py, str(HARNESS / 'make_project.py'), str(work), a.donor]]
            link = [[py, str(HARNESS / 'forms_link.py'), str(work), a.fighter, a.donor, str(iso)]
                    + [str(work / form) for form, _ in entry['forms']]]
            with open(out, 'w', encoding='utf-8') as f:
                for cmd in {'project': make, 'link': link, 'build': make + link}[stage]:
                    if cmd is make[0]:
                        shutil.rmtree(work / 'project', ignore_errors=True)
                    ok = ok and subprocess.run(cmd, cwd=str(repo / 'app' / 'backend'), env=_env(repo), stdout=f,
                                               stderr=subprocess.STDOUT).returncode == 0
        elif stage == 'art':
            # each form photographed on the linked disc by its own number on the roster (link.json), a match for each
            # costume in one boot; its package takes the pictures at the next build
            iso = Path(a.iso) if a.iso else work / f'{a.fighter}.iso'
            linked = json.loads((work / 'link.json').read_text('utf-8'))
            with open(out, 'w', encoding='utf-8') as f:
                stale = forms.stale_disc(iso, [one['work'] for one in linked['forms']])
                if stale:
                    print(f"the disc is older than the costumes of {', '.join(stale)}: its pictures would be of the "
                          "costumes before. Run from 'link' (or 'project')", file=f, flush=True)
                    ok = False
                for one in (linked['forms'] if not stale else []):
                    print(f"== {Path(one['work']).name} ({one['external']:#x})", file=f, flush=True)
                    try:
                        done = subprocess.run([py, str(HARNESS / 'game_art.py'), one['work'], str(iso),
                                               '--ckind', f"{one['external']:#x}"], cwd=str(repo / 'app' / 'backend'),
                                              env=_env(repo), stdout=f, stderr=subprocess.STDOUT, timeout=900).returncode
                    except subprocess.TimeoutExpired:
                        done = 'past its deadline'
                    ok = ok and done == 0
                    if done != 0:
                        print(f'game_art: {done}', file=f, flush=True)
                        break
        elif stage == 'verify':
            art = not calibration_requested(a) or (stage_current(stages,'art') and stage_current(stages,'build'))
            got = {form: verify.run(work / form, art_later=not art) for form, _ in entry['forms']}
            together = verify.forms_room([work / form for form, _ in entry['forms']])
            (work / 'verify.json').write_text(json.dumps({'forms': {k: v['answers'] for k, v in got.items()},
                                                          'together': together}, indent=1), 'utf-8')
            said = ([f'{form} {line:>6} {row["verdict"]:5} {row["how"]}' for form, v in got.items()
                     for line, row in v['answers'].items()]
                    + [f'together {k:>6} {v["verdict"]:5} {v["how"]}' for k, v in together.items()])
            out.write_text('\n'.join(said), 'utf-8')
            faults = [s for s in said if ' FAULT ' in s]
            ok = not faults
            for fault in faults:
                log('  ' + fault)
        stages[stage] = {'ok': ok, 'seconds': round(time.time() - began), 'log': str(out)}
        status['ran'].append(stage)
        log(f"{stage}: {'done' if ok else 'FAILED'} in {stages[stage]['seconds']} s ({out})")
        status_path.write_text(json.dumps(status, indent=1), 'utf-8')
        if not ok:
            break
    status['owed'] = {'stages': [s for s in order if not stage_current(stages,s)]}
    status_path.write_text(json.dumps(status, indent=1), 'utf-8')
    log(f"owed: stages {status['owed']['stages'] or 'none'}")
    return status


def main(argv=None):
    from fighter_port import source_game
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('fighter', help="the fighter's name in the source game's files (ike, cloud, master)")
    p.add_argument('--game', default='ultimate', choices=('ultimate', 'brawl') + source_game.GAMES)
    p.add_argument('--donor', default='Marth',
                   help="the Melee fighter whose states, tables and files the port is built on. Marth is the one "
                        "donor measured so far, so there is nothing to choose yet: a second donor needs a row in "
                        "each per-donor table (`fighters.DONOR_TABLES` lists them; preflight says so by name)")
    p.add_argument('--name', required=True, help="the port's name in the game (Ike)")
    p.add_argument('--work', required=True, help='the folder the port is made in (holds <donor>.zip)')
    p.add_argument('--root', required=True, help="source files: an Ultimate dump, extracted Brawl disc, or Slap City/Rivals reader output")
    p.add_argument('--body', help='the body as the model importer made it (needed by the costumes stage the first time)')
    p.add_argument('--rip', help='(Brawl) the ripped model as it came: a zip of a COLLADA file and its pictures')
    p.add_argument('--iso', help='optional final disc path; omit for a fighter zip only')
    p.add_argument('--mextk', help='the MexTK folder (for the code file)')
    p.add_argument('--repo', help='the app checkout (default: NUCLEUS_REPO)')
    p.add_argument('--own', action='store_true', help='the fighter keeps its own skeleton (checklist section 11)')
    p.add_argument('--calibrate', action='store_true', help='run optional developer gameplay calibration and captured artwork')
    p.add_argument('--tests', nargs='*', help="the fighter's own tests for the round, as patterns over the probe's "
                                               "test names (\"dh_*\" \"face_*\"); remembered in <work>/round.json")
    every = sorted(set(STAGES) | set(OWN_STAGES) | set(FORM_STAGES))
    p.add_argument('--forms-from', default=None, choices=sorted(OWN_STAGES),
                   help="(a fighter of forms) the stage each form's own run starts from")
    p.add_argument('--from', dest='start', default=None, choices=every,
                   help='the stage to start from (the first when not given)')
    p.add_argument('--to', default=None, choices=every, help='the last stage to run (the last when not given)')
    p.add_argument('--only', default=None, choices=every,
                   help='run this one stage and no other (--only preflight asks everything and builds nothing)')
    p.add_argument('--allow-large', action='store_true',
                   help='build costumes larger than a match is known to hold (the costumes stage stops on one otherwise)')
    status = run(p.parse_args(argv))
    # (the stages this run was asked for: with --to or --only the ones after them are owed and not a failure)
    return 0 if all(status['stages'][s]['ok'] for s in status['ran']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
