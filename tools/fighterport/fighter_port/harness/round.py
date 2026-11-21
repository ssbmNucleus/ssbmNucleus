"""One round of checks on a built port: the game is started ONCE.

Usage (cwd app/backend): python round.py <work> <iso> <fighter> [--own PATTERN ...] [--skip NAME ...]
                                         [--no-portraits] [--ckind 0x1A] [--keep-sound] [--plan]

Everything that needs the game is done in one Dolphin, as the tests of one `look_probe.py` run:

    portraits   each costume stands for its picture, a new match for each (`match_<n>`, about six seconds: no boot)
    common      what every fighter is asked: the frame clock, the HUD, the shield, the taunt, the blink, dodges and
                rolls and how many frames each lasts, a grab, the sounds of a jump, a grab and the taunt
    own         the fighter's own tests (its specials and what they make), named by --own patterns over the probe's
                test names (`--own "dh_*" "face_*"`; remembered in <work>/round.json). Each starts in a match of its
                own, so that nothing one test leaves out (an item, a shot) is there for the next.

The game's sound is recorded through the whole boot and every sound the scripts play is looked for in it
(`audio_check.py`). What it leaves in <work>/round/: `run.log` (the probe's own lines, one test after another),
`shots/` (the pictures), `sheet-<n>.png` (the pictures thirty to a sheet, to look at), `sound.txt`, and
`report.json`: which tests ran, which did not, whether the game stopped, how long the boot took.

What a round does NOT do is judge: a test's line says what happened (states, frames, hits, distances) and a reader
holds it against what the source game does. A new boot is owed only for a new disc (after a fix) or after the game
stopped: `--from <test>` starts a second boot at that test (the round says which).

--plan prints the tests and the deadline and starts nothing.
"""
import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import game_art  # noqa: E402

COMMON = ('look_perf', 'look_hud', 'look_shield', 'look_taunt', 'look_blink', 'look_round',
          'spotdodge', 'roll_f', 'roll_b', 'shield_drop', 'airdodge', 'grab_whiff', 'dashgrab_whiff',
          'step_spotdodge', 'step_rollf', 'step_rollb', 'step_shield', 'step_airdodge', 'step_jab', 'step_grab',
          'step_dashgrab', 'step_taunt', 'step_ledge_up', 'snd_jump', 'snd_grab', 'snd_taunt', 'snd_quiet')
SECONDS_A_TEST = 4            # room over the probe's own nine seconds a test (65 tests took 669 s in one boot)
A_SHEET = 30
PEACH = 0x0C                  # the largest of the game's own fighters' files


def room(kind):
    """The three matches a fighter's files must fit in (`verify` holds their sum against the heap before any disc;
    the game is asked once, here): two of the fighter in two costumes on Final Destination, the same on Pokemon
    Stadium, and the fighter beside Peach there. Each is followed by a picture of it (`look_round`). They come LAST:
    a match that does not load ends the boot ("the bag never spawned") without costing a test."""
    out = []
    for match in (f'match_1_{kind:x}', f'match_1_{kind:x}_pokemonstadium', f'match_0_{PEACH:x}_pokemonstadium'):
        out += [match, 'look_round']
    return out


def known(probe=None):
    """The names of the tests the probe carries, in its own order."""
    text = (probe or HERE / 'look_probe.py').read_text('utf-8')
    seen, out = set(), []
    for name in re.findall(r"^    '([a-z0-9_]+)': ", text, re.M):
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def plan(names, costumes=0, own=(), skip=(), start=None, kind=None):
    """The probe's tests for one round, in order. `costumes`: how many to photograph (0: none). `own`: patterns over
    `names`. `kind`: the fighter's number on the roster, for the three matches of `room` at the end (None: none).
    -> (tests, the fighter's own tests among them, patterns that matched nothing)"""
    tests = []
    if costumes:
        tests += game_art.tests(costumes) + ['match_0']
    tests += [n for n in COMMON if n in names and n not in skip]
    mine, empty = [], []
    for pattern in own:
        got = [n for n in names if fnmatch.fnmatch(n, pattern) and n not in skip and n not in mine and n not in COMMON]
        if not got:
            empty.append(pattern)
        mine += got
    for n in mine:
        tests += ['match_0', n]                 # a match of its own: nothing an earlier test left is in it
    if kind is not None and 'look_round' in names and 'room' not in skip:
        tests += room(kind)
    if start:
        real = [t for t in tests if not t.startswith('match_')]
        if start not in real:
            raise SystemExit(f'--from {start}: not one of this round\'s tests')
        keep = set(real[real.index(start):])
        tests = [t for i, t in enumerate(tests)
                 if t in keep or (t.startswith('match_') and i + 1 < len(tests) and tests[i + 1] in keep)]
    return tests, mine, empty


def deadline(tests):
    """(PROBE_EXTRA to give the probe, the seconds the probe allows itself with it): `look_probe.py`'s own sum."""
    extra = 60 + SECONDS_A_TEST * len(tests)
    return extra, 100 + 9 * len(tests) + 20 * sum(1 for t in tests if t.startswith('match_')) + extra


def read(log_text, tests):
    """What the probe's log says of each test. -> {'ran', 'not_run', 'stopped', 'matches'}"""
    real = [t for t in tests if not t.startswith('match_')]
    began = set(re.findall(r'^([a-z0-9_]+): states ', log_text, re.M))
    for name in ('look_portrait',):                    # (a picture-only test logs no states line: its pictures say)
        if name in real and re.search(rf'^{name}', log_text, re.M):
            began.add(name)
    # a test whose stepping stuck is void (the game was alive: it is asked again), and nothing is believed of a
    # test the game stopped in
    void = set(re.findall(r'THE STEPPING STUCK, NOT THE GAME, in ([a-z0-9_]+)', log_text))
    dead = re.findall(r'THE GAME STOPPED in ([a-z0-9_]+)', log_text)
    began -= void | set(dead)
    stopped = ('PROBE DEADLINE PASSED' in log_text or bool(dead)
               or bool(re.search(r'^(Traceback|.*never got back.*|.*did not land.*|.*never started.*|.*never spawned.*)', log_text, re.M)))
    why = re.findall(r'^(?:PROBE DEADLINE.*|THE GAME STOPPED.*|.*never .*|.*did not land.*|.*died.*)$', log_text, re.M)
    slow = len(re.findall(r'a step took more than a second', log_text))
    # the matches of `room` (a second fighter named): loaded, or not (and then the boot ended there)
    fit = {m: 'loaded' for m in re.findall(r'^(match_\d+_[0-9a-f]+(?:_[a-z]+)?): a new match in the same boot', log_text, re.M)}
    fit.update({m: 'DID NOT LOAD' for m in re.findall(r'^(match_\d+_[0-9a-f]+(?:_[a-z]+)?): the bag never spawned', log_text, re.M)})
    return {'room': fit, 'ran': [t for t in dict.fromkeys(real) if t in began], 'not_run': [t for t in dict.fromkeys(real) if t not in began],
            'void': sorted(void), 'dead': dead, 'stopped': stopped, 'why': why[:5], 'slow_steps': slow,
            'retried_matches': len(re.findall(r'the quit to the character screen did not take', log_text)),
            'matches': len(re.findall(r': a new match in the same boot', log_text))}


def driver_folder(work):
    """The driver's own folder in a work folder: `port` from the one command, `route` in a hand-run build (the newer)."""
    found = [n for n in ('port', 'route') if (Path(work) / n / 'game.json').exists()]
    return max(found, key=lambda n: (Path(work) / n / 'game.json').stat().st_mtime) if found else 'port'


def sheets(shots, out):
    """The round's pictures, thirty to a sheet, each under its name. -> the sheets written"""
    from PIL import Image, ImageDraw
    files = sorted(Path(shots).glob('*.png'))
    made = []
    for k in range(0, len(files), A_SHEET):
        part = files[k:k + A_SHEET]
        w, h, across = 320, 240, 6
        sheet = Image.new('RGB', (w * across, (h + 14) * -(-len(part) // across)), (0, 0, 0))
        draw = ImageDraw.Draw(sheet)
        for i, f in enumerate(part):
            x, y = (i % across) * w, (i // across) * (h + 14)
            sheet.paste(Image.open(f).convert('RGB').resize((w, h)), (x, y + 14))
            draw.text((x + 2, y + 1), f.stem[:52], fill=(255, 255, 0))
        path = Path(out) / f'sheet-{k // A_SHEET + 1}.png'
        sheet.save(path)
        made.append(str(path))
    return made


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('work')
    p.add_argument('iso')
    p.add_argument('fighter')
    p.add_argument('--own', nargs='*', help="patterns over the probe's test names for the fighter's own tests")
    p.add_argument('--skip', nargs='*', default=[])
    p.add_argument('--from', dest='start', help='start AT this test (a second boot, after a stop)')
    p.add_argument('--no-portraits', action='store_true')
    p.add_argument('--ckind', default='0x1A', help="the fighter's number on the roster (the first added fighter is 0x1A)")
    p.add_argument('--keep-sound', action='store_true', help='keep the recording (tens of megabytes)')
    p.add_argument('--plan', action='store_true')
    a = p.parse_args(argv)
    work = Path(a.work)
    out = work / 'round'
    shots = out / 'shots'
    notes = work / 'round.json'
    kept = json.loads(notes.read_text('utf-8')) if notes.exists() else {}
    own = a.own if a.own is not None else kept.get('own', [])
    if a.own is not None:
        notes.write_text(json.dumps(dict(kept, own=own), indent=1), 'utf-8')
    rows = json.loads((work / 'package' / 'costumes' / 'costumes.json').read_text('utf-8'))
    own_route = (work / 'data' / 'report.json').exists()              # (a fighter on its own skeleton: art from the game)
    costumes = len(rows) if own_route and not a.no_portraits and not a.start else 0
    tests, mine, empty = plan(known(), costumes, own, a.skip, a.start, kind=int(a.ckind, 16))
    extra, allowed = deadline(tests)
    real = [t for t in tests if not t.startswith('match_')]
    print(f'{len(real)} tests in one boot ({costumes} costumes photographed, {len(mine)} of the fighter\'s own, '
          f'{len(tests) - len(real)} new matches); the probe allows itself {allowed} s', flush=True)
    if not own:
        print('no tests of the fighter\'s own were named (--own): its specials are not in this round', flush=True)
    for pattern in empty:
        print(f'--own {pattern}: the probe has no test of that name', flush=True)
    if a.plan:
        print(' '.join(tests))
        return 0
    shots.mkdir(parents=True, exist_ok=True)
    if not a.start:
        # a round that takes no portraits keeps the ones already here: the `art` stage cuts from them (Greninja's
        # three rounds of his own tests wiped round 1's, and `--from art` stopped)
        for old in list(shots.glob('*.png')) + list(out.glob('sheet-*.png')):
            if costumes or not old.name.startswith('look_portrait'):
                old.unlink()
    wav = out / 'round.wav'
    env = dict(os.environ, LOOK_OUT=str(shots), PROBE_CKIND=a.ckind, PROBE_AUDIO=str(wav), PROBE_EXTRA=str(extra))
    if costumes:
        env['PROBE_PORTRAIT_CAM'] = game_art.camera(work)
    log = out / ('run.log' if not a.start else f'run-from-{a.start}.log')
    began = time.time()
    try:
        with open(log, 'w', encoding='utf-8') as f:
            code = subprocess.run([sys.executable, str(HERE / 'look_probe.py'), str(a.iso)] + tests, env=env,
                                  stdout=f, stderr=subprocess.STDOUT, timeout=allowed + 90).returncode
    except subprocess.TimeoutExpired:
        code = -1
    seconds = round(time.time() - began)
    text = log.read_text('utf-8', errors='replace')
    got = read(text, tests)
    got['stopped'] = got['stopped'] or code != 0
    sound = None
    if wav.exists():
        sound = out / ('sound.txt' if not a.start else f'sound-from-{a.start}.txt')     # (one for each boot of the round)
        with open(sound, 'w', encoding='utf-8') as f:
            subprocess.run([sys.executable, str(HERE / 'audio_check.py'), str(work), a.fighter, str(wav), str(log)],
                           env=dict(os.environ, PORT_DIR=os.environ.get('PORT_DIR') or driver_folder(work)), stdout=f, stderr=subprocess.STDOUT)
        if not a.keep_sound:
            wav.unlink()
    made = sheets(shots, out)
    report = dict(got, boots=1, seconds=seconds, tests=len(real), all=list(dict.fromkeys(real)), own=mine, costumes=costumes,
                  exit=code, pictures=len(list(shots.glob('*.png'))), sheets=made, logs=[str(log)],
                  sound=str(sound) if sound else None)
    before = out / 'report.json'
    if a.start and before.exists():
        # a second boot of the same round: what the boots ran between them is the round's
        was = json.loads(before.read_text('utf-8'))
        ran = list(dict.fromkeys(was.get('ran', []) + got['ran']))
        every = was.get('all') or list(dict.fromkeys(was.get('ran', []) + was.get('not_run', [])))
        report.update(boots=was.get('boots', 1) + 1, seconds=was.get('seconds', 0) + seconds, all=every, tests=len(every),
                      ran=ran, not_run=[t for t in every if t not in ran], costumes=was.get('costumes', 0),
                      dead=was.get('dead', []) + got['dead'], logs=was.get('logs', []) + [str(log)],
                      matches=was.get('matches', 0) + got['matches'])
        got = dict(got, ran=report['ran'], not_run=report['not_run'], matches=report['matches'])
        real = every
    (out / 'report.json').write_text(json.dumps(report, indent=1), 'utf-8')
    print(f"{'one boot' if report['boots'] == 1 else str(report['boots']) + ' boots'}, {report['seconds']} s: {len(got['ran'])} of {len(real)} tests ran, {got['matches']} new matches, "
          f"{report['pictures']} pictures on {len(made)} sheets" + (f"; NOT RUN: {' '.join(got['not_run'])}" if got['not_run'] else '')
          + (f"; stepping stuck (the game alive) in: {' '.join(got['void'])}" if got['void'] else '')
          + (f"; {got['slow_steps']} steps took over a second (a busy machine)" if got['slow_steps'] else '')
          + (f"; THE GAME OR THE PROBE STOPPED: {got['why']}" if got['stopped'] else ''), flush=True)
    if got['room']:
        print('room: ' + '; '.join(f'{m} {v}' for m, v in got['room'].items()), flush=True)
    if any(v != 'loaded' for v in got['room'].values()):
        # (the boot ends at a match that does not load, and the room's matches are the last tests: nothing is owed
        # but smaller files, which `verify`'s room line measures)
        print('A MATCH DID NOT LOAD: the files are too large for it (verify: line 11.26). No second boot is owed '
              'for the rest: make the costumes or the fighter data smaller, then build again.', flush=True)
    elif got['stopped'] and got['not_run']:
        # A game that stopped INSIDE a test: that test is a fault, and a second boot starts at the one after it. A
        # stop between tests (a match that would not change, the deadline): the second boot starts at the first test
        # that did not run.
        rest = [t for t in got['not_run'] if t not in got['dead']]
        print((f"THE GAME STOPPED IN {' '.join(got['dead'])}: a fault. " if got['dead'] else 'it stopped between tests. ')
              + (f"A second boot for the rest: --from {rest[0]}. " if rest else 'Nothing is left to run. ')
              # (checklist 9.17: a stop is run again, on the same disc, before anything is changed for it; Greninja's
              # one stop never came back in three runs)
              + (f"Run {' '.join(got['dead'])} again on this same disc before changing anything (checklist 9.17)"
                 if got['dead'] else ''), flush=True)
    return 1 if got['stopped'] or got['not_run'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
