"""Watch Lite next to the real game: one command from a replay folder to
labelled side-by-side PNG pairs and a brief for a fresh-context reviewer.

    app/venv/Scripts/python.exe -B tools/liteaudit/sidebyside/run.py --replays <replay folder> --types shine,stages,items --n 30

Steps (each script also runs on its own; see its docstring):
  pick     index.mjs (header index of the replay folder, cached) + pick.mjs -> targets.json
  prep     prep.mjs -> targets-ext.json (the replay's own truth at each frame)
  capture  capture.py -> shots/ (playback Dolphin, frame-exact; holds the Dolphin lock)
  compose  build.mjs (paint modules from the live source) + compose.py -> pairs/, REVIEW_BRIEF.md
--from STEP reruns from that step in an existing --out run folder; --from compose
after a Watch Lite fix redraws the pairs without capturing again.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SCRATCH = REPO / 'app' / 'scratch' / 'liteaudit' / 'sidebyside'
STEPS = ('pick', 'prep', 'capture', 'compose')

import capture                                                        # noqa: E402
import compose                                                        # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--replays', help='Slippi replay folder (its .slp files and their direct subfolders); needed to pick')
    ap.add_argument('--types', default='all',
                    help='comma list of shine, stages, items, throws, effects, shields, fighters, swords, ko, respawn, starko, screenko, flash, dust (default all)')
    ap.add_argument('--n', type=int, help='how many frames to pick (default 30, or one per --only id)')
    ap.add_argument('--only', default='', help='pick these target ids (see pick.mjs) instead of whole types')
    ap.add_argument('--exclude', default='', help="earlier runs' targets.json, comma separated: their replays are not reused")
    ap.add_argument('--out', help='run folder (default app/scratch/liteaudit/sidebyside/<date>-<time>)')
    ap.add_argument('--from', dest='start', choices=STEPS, default='pick', help='first step to run (needs --out after pick)')
    ap.add_argument('--wait', type=float, default=1800, help='seconds to queue for the Dolphin lock')
    ap.add_argument('--iso', help='vanilla NTSC 1.02 ISO (default: the one the app recorded)')
    ap.add_argument('--chrome', help='Chrome or Edge executable (default: found automatically)')
    ap.add_argument('--src', help='frontend src tree to bundle instead of app/frontend/src (e.g. an older worktree)')
    ap.add_argument('--cache', default=str(SCRATCH / 'cache'), help='replay index, animation packs, paint bundle')
    a = ap.parse_args()
    steps = STEPS[STEPS.index(a.start):]
    if a.start != 'pick' and not a.out:
        ap.error('--from needs --out <existing run folder>')
    if 'pick' in steps and not a.replays:
        ap.error('--replays is needed to pick frames')
    run = Path(a.out).resolve() if a.out else SCRATCH / time.strftime('%Y%m%d-%H%M%S')
    cache = Path(a.cache).resolve()
    run.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    logf = (run / 'run.log').open('a', encoding='utf-8')

    def log(m):
        line = f"[{time.strftime('%H:%M:%S')}] {m}"
        print(line, flush=True)
        logf.write(line + '\n')
        logf.flush()

    def node(script, *args):
        p = subprocess.Popen(['node', str(HERE / script), *map(str, args)], cwd=str(HERE), stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
        for line in p.stdout:
            log(f'  {line.rstrip()}')
        if p.wait():
            raise SystemExit(f'{script} failed (exit {p.returncode}); see the lines above')

    t0 = time.time()
    log(f"run folder {run}; steps {', '.join(steps)}")
    if 'pick' in steps:
        slug = re.sub(r'[^A-Za-z0-9]+', '_', str(Path(a.replays).resolve())).strip('_')
        index = cache / f'index-{slug}.json'
        node('index.mjs', '--root', a.replays, '--out', index)
        args = ['--index', index, '--out', run / 'targets.json', '--types', a.types]
        args += ['--n', a.n] if a.n else []
        args += ['--only', a.only] if a.only else []
        args += ['--exclude', a.exclude] if a.exclude else []
        node('pick.mjs', *args)
    if 'prep' in steps:
        node('prep.mjs', run / 'targets.json', run / 'targets-ext.json')
    targets = json.loads((run / 'targets-ext.json').read_text())
    if not targets:
        raise SystemExit('no targets were picked')
    if 'capture' in steps:
        log(f'capturing {len(targets)} frames in playback Dolphin, about 11-15 s each')
        metas = capture.capture_all(targets, run / 'shots', a.iso, a.wait, log)
        bad = [m['id'] for m in metas if not m.get('ok')]
        log(f'captured {len(metas) - len(bad)}/{len(metas)}' + (f"; failed: {', '.join(bad)}" if bad else ''))
    if 'compose' in steps:
        lib = cache / 'paintlib.js'
        node('build.mjs', '--out', lib, *(['--src', a.src] if a.src else []))
        rows = compose.compose_all(targets, run / 'shots', run / 'pairs', lib, cache, a.chrome, None, log)
        listing = '\n'.join(f"- `{r['png']}`: {r['shows']}" + ('' if r['frame_exact'] else ' (FRAME CHECK FAILED)')
                            for r in rows)
        brief = ((HERE / 'review_brief.md').read_text(encoding='utf-8')
                 .replace('{count}', str(len(rows))).replace('{pairs_dir}', str(run / 'pairs')).replace('{pair_list}', listing))
        (run / 'REVIEW_BRIEF.md').write_text(brief, encoding='utf-8')
        inexact = [r['id'] for r in rows if not r['frame_exact']]
        log(f"{len(rows)}/{len(targets)} pairs in {run / 'pairs'}; frame-exact {len(rows) - len(inexact)}"
            + (f" (check failed: {', '.join(inexact)})" if inexact else ''))
        log(f"reviewer brief: {run / 'REVIEW_BRIEF.md'}")
    log(f'done in {time.time() - t0:.0f} s')
    return 0


if __name__ == '__main__':
    sys.exit(main())
