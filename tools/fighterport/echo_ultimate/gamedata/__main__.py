"""python -m echo_ultimate.gamedata <fighter> --root <dump folder> [--out moves.json] [--move game_attack11]

Prints a summary of what was read for the fighter; --out writes everything as JSON
(game-derived data: keep it out of the repository).
"""
import argparse
import json
import os
import sys

from . import moves


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m echo_ultimate.gamedata')
    ap.add_argument('fighter', help="the game's internal fighter name, e.g. shulk, mario, lucina")
    ap.add_argument('--root', default=os.environ.get('ULTIMATE_DUMP'),
                    help='dump folder with romfs/data.arc and ArcExplorer/smash_arc.dll (or set ULTIMATE_DUMP)')
    ap.add_argument('--out', help='write the full result as JSON')
    ap.add_argument('--move', action='append', default=[], help='print this script in full (repeatable)')
    a = ap.parse_args(argv)
    if not a.root:
        ap.error('give --root or set ULTIMATE_DUMP')
    d = moves.load(a.fighter, a.root)
    mv = d['moves']
    named = [k for k in mv if not k.startswith('0x')]
    hb = sum(len(v['hitboxes']) for v in mv.values())
    att = d['attributes']
    print(f'{a.fighter}: {len(mv)} move scripts ({len(named)} named), {hb} hitboxes, '
          f'{len(att)} attributes ({sum(1 for k in att if not k.startswith("0x"))} named)')
    print('scripts registered:', d['registered_scripts'])
    for key in ('weight', 'walk_speed_max', 'dash_speed', 'run_speed_max', 'air_accel_y', 'air_speed_y_stable',
                'jump_squat_frame'):
        if key in att:
            print(f'  {key:20} {att[key]}')
    print(f'{"script":28} {"active":>9} {"damage":>14} {"angle":>12} {"cancel":>7}  hitboxes')
    for k in sorted(named):
        v = mv[k]
        if not v['hitboxes']:
            continue
        hs = v['hitboxes']
        first = min(h['first'] for h in hs)
        last = max((h['last'] or h['first']) for h in hs)
        dmg = '/'.join(str(x) for x in sorted({h['damage'] for h in hs}, key=str, reverse=True))
        ang = '/'.join(str(x) for x in sorted({h['angle'] for h in hs}, key=str))
        print(f'{k:28} {f"{first}-{last}":>9} {dmg[:14]:>14} {ang[:12]:>12} {str(v["cancel_frame_real"] or ""):>7}  {len(hs)}')
    for k in a.move:
        print(f'\n{k}:')
        print(json.dumps(mv.get(k, 'not found'), indent=1, default=str))
    if a.out:
        with open(a.out, 'w', encoding='utf-8') as f:
            json.dump(d, f, indent=1, default=str)
        print('wrote', a.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
