"""The animation the game itself plays for each (fighter, action state), where
Watch Lite's slippilab-derived choice differs or finds nothing.

The game: action state N -> its submotion in the decomp's motion tables
(ft/ftmotionstates.c for common states, ft/chara/ftXx/*.c for specials) -> the
submotion's value (ftCo_SM_* enum in ftCommon/forward.h; per-fighter ftXx_SM_*
enums continue from ftCo_SM_Count) -> that entry of the fighter's own action
table in Pl<XX>.dat -> its figatree symbol, whose motion part is the name the
slippilab archives use. Submotion NAMES are not used: some differ from the
file (Peach's turnip is the file's SpecialN, her Toad SpecialLw).

Watch Lite's choice is meleeRender.pose(): charmaps animationMap || specialsMap
|| action, then the action name for common states, then data/motionNames.js,
then meleeRender's stand-ins. Where the game's animation is in the archive and
that choice is another animation (or none), it is recorded; pose() and
animCandidates() try it first.

    python tools/liteaudit/game_motions.py [--decomp PATH] [--anim-zips PATH] [--iso PATH]

Writes app/frontend/src/tracker/replays/data/gameMotions.js:
    export default { "<internal cid>": { "<state>": "AnimName" } }
"""
import argparse
import json
import os
import re
import sys
import zipfile
from pathlib import Path

from extract_anims import ZIP_NAMES

REPO = Path(__file__).resolve().parents[2]
REPLAYS = REPO / 'app/frontend/src/tracker/replays'
sys.path.insert(0, str(REPO / 'app' / 'backend'))
DIRS = ['ftMario', 'ftFox', 'ftCaptain', 'ftDonkey', 'ftKirby', 'ftKoopa', 'ftLink', 'ftSeak', 'ftNess', 'ftPeach',
        'ftPopo', 'ftNana', 'ftPikachu', 'ftSamus', 'ftYoshi', 'ftPurin', 'ftMewtwo', 'ftLuigi', 'ftMars', 'ftZelda',
        'ftCLink', 'ftDrMario', 'ftFalco', 'ftPichu', 'ftGameWatch', 'ftGanon', 'ftEmblem']
CODES = ['Mr', 'Fx', 'Ca', 'Dk', 'Kb', 'Kp', 'Lk', 'Sk', 'Ns', 'Pe', 'Pp', 'Nn', 'Pk', 'Ss', 'Ys', 'Pr', 'Mt', 'Lg',
         'Ms', 'Zd', 'Cl', 'Dr', 'Fc', 'Pc', 'Gw', 'Gn', 'Fe']
# meleeRender: states the game hides, and the animation-less states whose last pose it keeps
HIDDEN = {289, 293, 331, 340}
# thrown / carried: the game plays the THROWER's victim animation (ftCo_800DE3FC
# loads it from the thrower's action table), not an entry of the victim's own
THROWN = set(range(239, 244)) | set(range(266, 275))
KEEP_POSE = {30, 31, 174, 177, 237, 278, 280, 283, 285, 294, 295, 301, 302, 314, 315, 316, 317, 318, 319, 320, 321,
             322, 324, 325, 327, 328, 329, 330, 333, 334, 336, 337, 338, 339}
GAME_ANIM = {'FlyReflectCeil': 'StopCeil', 'DownReflect': 'WallDamage', 'DamageBind': 'FuraFura',
             'DamageSong': 'FuraSleepStart', 'DamageSongWait': 'FuraSleepLoop', 'DamageSongRv': 'FuraSleepEnd',
             'BuryJump': 'JumpF', 'LiftWalk1': 'HeavyWalk1', 'LiftWalk2': 'HeavyWalk2'}


def stand_ins(name):                       # meleeRender.standIns
    if name.startswith('Shouldered'):
        return ['CaptureWaitHi']
    if name == 'ShieldBreakFly':
        return ['DamageFlyHi']
    if name.startswith('ItemParasol'):
        return ['Fall']
    if name == 'HeavyGet':
        return ['LightGet']
    if name.startswith('LiftWalk') or name.startswith('HeavyWalk'):
        return ['WalkSlow']
    if name == 'LiftTurn':
        return ['Turn']
    m = re.match(r'^Heavy(Throw[A-Za-z]+?)4?$', name)
    if m:
        return ['Light' + m.group(1), 'LightThrowF']
    m = re.match(r'^(?:Bat|Parasol|Lip[Ss]tick|StarRod|Harisen)Swing(\d)', name)
    if m:
        return ['Swing' + m.group(1), 'Swing1']
    return []


def fallback_for(name):                    # meleeRender.fallbackFor
    if not name:
        return []
    if name == 'SquatWait':
        return ['SquatWait1']
    if name in ('Guard', 'GuardDamage'):
        return ['GuardOn']
    if name.startswith('Thrown'):
        return ['DamageFlyN']
    if name.startswith('Capture') or name == 'YoshiEgg':
        return ['CaptureWaitHi']
    if name in GAME_ANIM:
        return [GAME_ANIM[name]] + stand_ins(GAME_ANIM[name])
    return stand_ins(name)


def enum_values(text, prefix, start):
    """{name: value} for every enumerator of the enums containing `prefix` (C rules)."""
    out = {}
    for body in re.findall(r'enum[^{]*\{(.*?)\}', text, re.S):
        if prefix not in body:
            continue
        n = None
        for item in body.split(','):
            item = re.sub(r'//.*|/\*.*?\*/', '', item, flags=re.S).strip()
            m = re.match(r'(\w+)\s*(?:=\s*(.+))?$', item)
            if not m:
                continue
            name, val = m.group(1), (m.group(2) or '').strip()
            if val:
                if re.fullmatch(r'-?\d+', val):
                    n = int(val)
                elif val == 'ftCo_SM_Count':
                    n = start
                elif val in out:
                    n = out[val]
                else:
                    mm = re.fullmatch(r'(\w+)\s*\+\s*(\d+)', val)
                    n = (out.get(mm.group(1), start) + int(mm.group(2))) if mm else (n + 1 if n is not None else 0)
            else:
                n = 0 if n is None else n + 1
            out[name] = n
    return out


def common_submotions(decomp):
    src = (decomp / 'src/melee/ft/chara/ftCommon/forward.h').read_text(encoding='utf-8', errors='ignore')
    m = re.search(r'enum\s+ftCommon_Submotion\s*\{(.*?)\}', src, re.S) or \
        re.search(r'typedef enum[^{]*\{([^}]*ftCo_SM_ThrownF[^}]*)\}', src, re.S)
    out, n = {}, -1
    for line in m.group(1).split(','):
        line = re.sub(r'//.*', '', line).strip()
        mm = re.match(r'(ftCo_SM_\w+)\s*(?:=\s*(-?\w+))?', line)
        if not mm:
            continue
        n = int(mm.group(2), 0) if mm.group(2) and re.fullmatch(r'-?\d+', mm.group(2)) else n + 1
        out[mm.group(1)] = n
    return out


def motion_table(text):
    return {int(n): sm for _, n, sm in
            re.findall(r'//\s*(ft\w+?_MS_\w+)\s*=\s*(\d+)\s*\n\s*(ft\w+_SM_\w+|ftCo_SM_\w+)\s*,', text)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--decomp', type=Path, default=Path(os.environ.get('MELEE_DECOMP') or Path.home() / 'projects' / 'melee'))
    ap.add_argument('--anim-zips', type=Path,
                    default=Path(os.environ.get('LOCALAPPDATA', '')) / 'SSBM Nucleus/storage/nucleome/anim_zips')
    ap.add_argument('--iso', type=Path, default=None)
    args = ap.parse_args()
    from stage_bake import FighterDisc
    from vault.echo.subactions import FighterDat
    if args.iso is None:
        from shared.vanilla_extract.vanilla_refs import known_vanilla_iso
        args.iso = Path(known_vanilla_iso())
    disc = FighterDisc(args.iso)
    co = common_submotions(args.decomp)
    common = motion_table((args.decomp / 'src/melee/ft/ftmotionstates.c').read_text(encoding='utf-8', errors='ignore'))
    charmaps = json.loads((REPO / 'app/backend/tracker/tools/charmaps.json').read_text(encoding='utf-8'))
    mn_src = (REPLAYS / 'data/motionNames.js').read_text(encoding='utf-8')
    motion_names = json.loads(mn_src[mn_src.index('{'):mn_src.rindex('}') + 1])
    out, counts = {}, {}
    for cid, folder in enumerate(DIRS):
        ch = charmaps['chars'].get(str(cid))
        if not ch:
            continue
        z = zipfile.ZipFile(args.anim_zips / f'{ZIP_NAMES[cid]}.zip')
        names = {n[:-5]: n for n in z.namelist() if n.endswith('.json')}

        def present(n):
            if not n or n not in names:
                return False
            data = json.loads(z.read(names[n]))
            return bool(data)
        fdir = args.decomp / 'src/melee/ft/chara' / folder
        text = ''.join(p.read_text(encoding='utf-8', errors='ignore') for p in sorted(fdir.glob('*.[ch]')))
        own = enum_values(text, '_SM_', start=co['ftCo_SM_Count'])
        table = dict(common)
        table.update({k: v for k, v in motion_table(text).items() if k >= 341})
        actions = FighterDat(disc.file(f'Pl{CODES[cid]}.dat')).actions
        for state, sm in sorted(table.items()):
            if state <= 11 or state in HIDDEN or state in THROWN or (sm == 'ftCo_SM_None' and state in KEEP_POSE):
                continue
            smv = co.get(sm, own.get(sm))
            game = actions[smv].motion if smv is not None and 0 <= smv < len(actions) else None
            if not game or not present(game):
                continue
            action = charmaps['actionNameById'][state] if state < len(charmaps['actionNameById']) else None
            name = (ch['animationMap'].get(action) if action else None) or ch['specialsMap'].get(str(state)) or action
            wl = None
            for n in (name, action if state < 341 else None, motion_names.get(str(cid), {}).get(str(state))):
                if present(n):
                    wl = n
                    break
            if wl is None:
                for n in fallback_for(name) or fallback_for(action or ''):
                    if present(n):
                        wl = n
                        break
            if wl == game:
                continue
            out.setdefault(str(cid), {})[str(state)] = game
            kind = 'missed' if wl is None else 'wrong'
            counts[kind] = counts.get(kind, 0) + 1
    path = REPLAYS / 'data/gameMotions.js'
    path.write_text("// Generated by tools/liteaudit/game_motions.py from the melee decomp's motion\n"
                    "// tables, the fighters' own action tables (vanilla Pl*.dat) and the animation\n"
                    "// zips. Do not edit by hand.\n"
                    'export default ' + json.dumps(out, separators=(',', ':'), sort_keys=True) + '\n', encoding='utf-8')
    print(f'gameMotions.js: {sum(len(v) for v in out.values())} states over {len(out)} characters', counts)


if __name__ == '__main__':
    main()
