"""Answer what can be answered about a port from the files its build wrote, without starting the game.

    python -m fighter_port.verify <work folder> [--json] [--art-later] [--report-only]

Every line of PORT_CHECKLIST.md is marked in `checklist_marks.json` by what it takes to answer it for a new fighter:

    rule   settled in the system (code, a table, a method note): nothing is run for a fighter
    files  answered from what the build wrote (fighter data, scripts, bank, costumes, receipts): this module
    boot   needs the game, the same way for every fighter: a step of the round's one boot (harness/round.py)
    code   needs the game because it is code written for this fighter (specials, items): its own steps of that boot

("files+boot": the files answer it and the boot confirms with one reading; "look": someone must look at a picture.)
A check here is tied to a line, reads the build's receipts and the built files, and says one of:

    ok     the files say the line holds
    say    it holds with something to state (a stand-in, a list of what was left): the list given with the port
    FAULT  the files say it does not hold

A line marked for the files that has no check here yet is listed as such; it is not counted as answered. A check
is only as good as the reading of the rule behind it: when the game shows a fault the files did not, the fault
becomes a check here, and the game is not asked that question again.

A check that finds no receipt of its own in the folder gives no answer (None: the line is listed as having no
check), and never says ok for want of something to read. FAULT is kept for what the files show does not hold; where
they cannot tell a fault from a rule of the driver, the check says what it saw. Each check's own words say what it
holds against what, and what it does not look at.
"""
import json
import re
import sys
import time
import zipfile
from pathlib import Path

MARKS = Path(__file__).with_name('checklist_marks.json')

# what the engine holds (PORT_CHECKLIST 11.1, 11.11, 11.21) and what has been measured (9.13)
JOINTS, CLIP_BYTES, HURTBOXES, CHAINS, SPHERES, GROUPS, PIECES, DEPTH = 140, 0x8000, 15, 9, 11, 11, 124, 29
CLOCK_BASE, CLOCK_PER_1000, OWN_MATRICES = 0.20, 0.06, 387  # Marth beside Donkey Kong; each 1,000 matrices; Marth's own

# Room (11.26). A match's files share one heap, and it holds each file whole. Every number here was read from the
# running game (the heap's own list, Wolf's port, 2026-11-12: wolf-cold/shots/checks5/heap_*.log) and the sum they
# make was the game's own free figure to the byte in three matches; it also gives the 0.34 MB an earlier session
# read for Duck Hunt beside Peach on Pokemon Stadium.
HEAP = 0x818297E0 - 0x811DE3E0                  # 6,599,680 bytes
HEAP_FILE = 96                                  # what the heap adds for a file loaded by itself
HEAP_ROUND = 32                                 # a file takes its size rounded up to this
STAGE = {'Final Destination': (611_136, 1),     # (bytes, files that each cost HEAP_FILE): the largest and the smallest
         'Pokemon Stadium': (1_461_024 + 80_640 + 522_240 + 19_840 + 327_680, 1)}   # ... with what it loads beside itself
PEACH = (269_824 + 5_120 + 809_824, 3)          # the largest of the game's own: her data, her effects, a costume
TIGHT = 200_000                                 # A READING: less than this to spare is said (nothing measured sets it)
# A fighter of forms (13.7): every form is loaded with the match. Its clip files (each fighter's <..>AJ.dat) go whole
# into a heap of their own, read from the running game with Wolf beside Peach (2026-11-12: heap 5, 0x60CF00 to
# 0xF79700, the two clip files and nothing else). The second fighter that costs most is Zelda, who brings Sheik:
# READINGS from the vanilla disc's file sizes, not from a match (Zelda's and Sheik's data, Zelda's effects, which
# Sheik shares, a costume each; their two clip files).
CLIP_HEAP = 0xF79700 - 0x60CF00                 # 9,881,600 bytes
ZELDA = (187_304 + 166_907 + 86_954 + 350_082 + 380_176, 5)   # heap 4: (bytes, files)
ZELDA_CLIPS = 2_182_400 + 1_366_336                             # heap 5
PEACH_CLIPS = 2_102_080

# Rules of the driver that a built move differs from the game's by (`oneshot`): held against the receipts below
GRAB_LEAD = 1                                   # a grab box takes hold the frame after it is made: written one earlier
DODGES = {'EscapeN': 'escape_n', 'EscapeF': 'escape_f', 'EscapeB': 'escape_b', 'EscapeAir': 'escape_air'}


class Work:
    def __init__(self, folder):
        self.dir = Path(folder)
        self._json = {}
        # the driver's own folder: `port` from the one command, `route` in a hand-run build
        found = [n for n in ('port', 'route') if (self.dir / n / 'report.json').exists()]
        self.drv = max(found, key=lambda n: (self.dir / n / 'report.json').stat().st_mtime) if found else 'port'   # the newer, if both

    def json(self, rel):
        if rel not in self._json:
            p = self.dir / rel
            self._json[rel] = json.loads(p.read_text('utf-8')) if p.exists() else None
        return self._json[rel]

    @property
    def report(self):
        return self.json(f'{self.drv}/report.json') or {}

    @property
    def data(self):
        return self.json('data/report.json') or {}

    @property
    def game(self):
        return self.json(f'{self.drv}/game.json') or {}

    @property
    def sound(self):
        return self.json('package/sound.json') or {}

    @property
    def costumes(self):
        return self.json('package/costumes/costumes.json') or []

    def fighter_zips(self):
        """The package's fighter zips, the newest last: a zip an earlier run left under another name (the
        Trainer's Squirtle.zip beside its Pokemon Trainer.zip) comes first, so a check that reads the last zip
        holding a file reads the one this run wrote."""
        zips = [p for p in (self.dir / 'package').glob('*.zip') if p.name != 'sound.zip']
        return sorted(zips, key=lambda p: (p.stat().st_mtime, p.name))

    def entry(self):
        """The fighter's entry in the package (fighter.json in the fighter's zip)."""
        if 'entry' not in self._json:
            got = None
            for z in self.fighter_zips():
                with zipfile.ZipFile(z) as f:
                    names = [n for n in f.namelist() if n.lower().endswith('fighter.json')]
                    if names:
                        got = json.loads(f.read(names[0]))
            self._json['entry'] = got
        return self._json['entry']


CHECKS = {}


def check(*ids):
    def deco(fn):
        for i in ids:
            CHECKS[i] = fn
        return fn
    return deco


@check('1.2', '11.18')
def costumes(w):
    rows = w.costumes
    files = [w.dir / 'package' / 'costumes' / r['file'] for r in rows]
    missing = [p.name for p in files if not p.exists()]
    if not rows or missing:
        return 'FAULT', f'{len(rows)} costumes listed, missing files {missing}'
    sizes = sorted({p.stat().st_size for p in files})
    folders = {r.get('folder') for r in rows}
    if len(folders) != len(rows):
        return 'FAULT', f'{len(rows)} costumes from {len(folders)} folders: one is a copy of another'
    # (a costume that is a model of its own under the same pictures' names, Slap City's other outfits, is
    # compared with the costumes of its model: own_costumes writes which model each is made from)
    by_model = {}
    for r, p in zip(rows, files):
        by_model.setdefault(r.get('model') or 'c00', set()).add(p.stat().st_size)
    differ = {m: sorted(v) for m, v in by_model.items() if len(v) > 1}
    if differ and w.report.get('route') == 'own skeleton':
        return 'FAULT', f'costumes of one model differ in size: {differ}'
    if len(by_model) > 1:
        return 'ok', (f'{len(rows)} costumes, each from its own folder, of {len(by_model)} models (each the same size as '
                      f'the others of its model): {sizes[0]:,} to {sizes[-1]:,} bytes')
    return 'ok', f'{len(rows)} costumes, each from its own folder, {sizes[0]:,} bytes each' if len(sizes) == 1 else \
        f'{len(rows)} costumes, each from its own folder, {sizes[0]:,} to {sizes[-1]:,} bytes'


@check('1.4', '11.21')
def face_groups(w):
    f, t = w.report.get('faces') or {}, w.data.get('model_tables') or {}
    groups, pieces = f.get('groups') or t.get('groups_now'), t.get('pieces_named_now')
    if groups is None:
        return 'say', 'no face parts are switched (no receipt of any)'
    if groups > GROUPS or (pieces or 0) > PIECES:
        return 'FAULT', f'{groups} groups (the engine holds {GROUPS}), {pieces} pieces (it holds {PIECES})'
    return 'ok', f'{groups} groups of {GROUPS}, {pieces} pieces of {PIECES}, {f.get("commands")} switch commands in {f.get("actions")} actions'


@check('11.23')
def face_scripts(w):
    f = w.report.get('faces') or {}
    if not f:
        return 'say', 'no face parts are switched'
    if f.get('not_placed'):
        return 'FAULT', f'switches with no place in a script: {f["not_placed"]}'
    left = f.get('left') or {}
    return ('say' if left else 'ok'), (f'{f.get("commands")} commands written, {f.get("donor_commands_removed")} of the donor\'s removed'
                                        + (f'; {len(left)} actions leave a group to the resting clip' if left else ''))


@check('1.13', '9.13', '11.16')
def frame_cost(w):
    from . import skin_cost
    rows = w.costumes
    if not rows:
        return 'FAULT', 'no costumes'
    worst, name = 0, None
    for r in rows:
        c = skin_cost.cost((w.dir / 'package' / 'costumes' / r['file']).read_bytes())
        m = c.get('matrices', c.get('total', 0)) if isinstance(c, dict) else c
        if m > worst:
            worst, name = m, r['file']
    clock = CLOCK_BASE + CLOCK_PER_1000 * max(0, worst - OWN_MATRICES) / 1000
    verdict = 'ok' if clock < 0.5 else 'FAULT'
    return verdict, (f'{worst:,} matrices in the heaviest costume ({name}) with every part counted: at most {clock:.2f} of a '
                     f'frame beside one other fighter by the measured rule (frames drop past 1.0 for the two together)')


@check('2.1', '11.10')
def clips(w):
    c, held, ok = w.report.get('clips') or {}, w.report.get('held') or {}, (w.report.get('check') or {})
    if c.get('error') or not ok.get('ok', False):
        return 'FAULT', f'clip errors {c.get("error")}, check problems {ok.get("problems")}'
    return ('say' if held else 'ok'), (f'{c.get("compiled")} clips compiled, {ok.get("actions")} actions'
                                       + (f'; {len(held)} actions hold a pose: {", ".join(sorted(held))}' if held else ''))


@check('2.6', '11.9')
def travel(w):
    t = w.report.get('travel')
    if not t:
        return None
    return 'ok', (f'{len(t.get("kept") or {})} actions keep the clip\'s travel, {len(t.get("taken_off") or {})} have it taken '
                  f'off for the state\'s own physics (the distance itself is the boot\'s to log)')


@check('11.1')
def limits(w):
    own, ok = w.report.get('own') or {}, w.report.get('check') or {}
    facts = ((w.data.get('verify') or {}).get('facts')) or {}
    big = (ok.get('largest_clip') or {}).get('bytes', 0)
    bad = []
    if own.get('joints', 0) > JOINTS:
        bad.append(f'{own["joints"]} joints (limit {JOINTS})')
    if big > CLIP_BYTES:
        bad.append(f'a clip of {big} bytes (limit {CLIP_BYTES})')
    if facts.get('hurtbox_count', 0) > HURTBOXES:
        bad.append(f'{facts["hurtbox_count"]} hurtboxes (limit {HURTBOXES})')
    rigs = sorted((w.dir / 'rig').glob('rig-*.json')) if (w.dir / 'rig').is_dir() else []
    depth = ((json.loads(rigs[0].read_text('utf-8')).get('provenance') or {}).get('depth')) if rigs else None
    if isinstance(depth, int) and depth > DEPTH:
        bad.append(f'joints {depth} deep (limit {DEPTH})')
    if bad:
        return 'FAULT', '; '.join(bad)
    if not own.get('joints') or not big:
        return None                 # no receipt of the joints or of the clips: nothing was counted
    boxes = facts.get('hurtbox_count')
    return 'ok', (f'{own.get("joints")} joints of {JOINTS}, largest clip {big:,} of {CLIP_BYTES:,} bytes, '
                  + (f'{boxes} hurtboxes of {HURTBOXES}, ' if boxes is not None else 'hurtboxes not in the data\'s receipt, ')
                  + (f'joints {depth} deep of {DEPTH}' if isinstance(depth, int) else 'joint depth not in the rig\'s receipt'))


@check('11.5')
def joint_tables(w):
    v = w.data.get('verify') or {}
    if not v:
        return None
    if not v.get('ok') or v.get('out_of_range') or v.get('round_trip_problems'):
        return 'FAULT', f'problems {v.get("problems")}, out of range {v.get("out_of_range")}, round trip {v.get("round_trip_problems")}'
    return 'ok', f'{v.get("joint_indices")} joint numbers rewritten in {len(w.data.get("plain") or [])} tables and the scripts, none out of range, highest {v.get("highest")} of {v.get("limit")}'


@check('11.6')
def hurtboxes(w):
    h, e = w.data.get('hurtboxes') or {}, w.data.get('ecb') or {}
    if not h:
        return None
    src = str(h.get('source', ''))
    return ('ok' if 'source' in src else 'FAULT'), f'hurtboxes from {src} ({h.get("written")}); the collision joints from {str(e.get("source"))[:60]}'


@check('11.8')
def clip_sizes(w):
    c, ok = w.report.get('clips') or {}, w.report.get('check') or {}
    big = (ok.get('largest_clip') or {})
    if big.get('bytes', 0) > ok.get('capacity', CLIP_BYTES):
        return 'FAULT', f'{big}'
    n = c.get('loosened') or 0
    return ('say' if n else 'ok'), f'{n} clips thinned to fit; the largest is {big.get("motion")} at {big.get("bytes"):,} of {ok.get("capacity", CLIP_BYTES):,} bytes'


@check('11.11')
def swing(w):
    s = w.report.get('swing')
    if not s:
        return 'say', 'nothing swings'
    chains, spheres = len(s.get('chains') or []), s.get('spheres') or 0
    if chains > CHAINS or spheres > SPHERES:
        return 'FAULT', f'{chains} chains (limit {CHAINS}), {spheres} spheres (limit {SPHERES})'
    return 'ok', f'{chains} chains of {CHAINS}, {spheres} spheres of {SPHERES}'


@check('11.14')
def drawn_size(w):
    s = w.data.get('scale')
    if not s:
        return None
    return 'ok', f'drawn at {s.get("written"):.4f}: {str(s.get("chosen_by"))[:110]}'


@check('11.42')
def shield_joint(w):
    """The shield's joint is scaled to the shield's size every frame: a joint with anything under it takes the body
    (or that part of it) with it. Holds the data report's `shield` against that; the picture is still the round's."""
    s = w.data.get('shield')
    if not s:
        return None
    if s.get('under'):
        return 'FAULT', (f'the shield hangs from {s["name"]} (joint {s["joint"]}), which has {len(s["under"])} joints under it '
                         f'({", ".join(s["under"][:4])}{"..." if len(s["under"]) > 4 else ""}): they grow with the shield; give the rig a leaf for it (a Throw bone)')
    return 'ok', f'the shield hangs from {s["name"]} (joint {s["joint"]}), with nothing under it'


def _rows(w):
    """The route's own table of the ordinary moves (jab to ledge attack), each as built beside the game's: read back
    from the built fighter data by the driver, against the game's script for the action's clip."""
    return [r for r in w.report.get('moves') or [] if r.get('clip') and r.get('action')]


def _grab(row):
    return any('(grab)' in str(b) for b in (row.get('boxes') or []) + (row.get('game_boxes') or []))


@check('2.8')
def facing_copies(w):
    """Facing left as well as right is a list of clip names: the clips the game keeps a second copy of for the
    other facing, against the clips the port carries. What is compared: the names in the game's list of motions
    (`game.json`) with the clips in the driver's own list (`spec/moveset.json`). Not seen from here: what code
    places when he faces left (a picture each way of the specials)."""
    motions, spec = w.game.get('motions'), w.json(f'{w.drv}/spec/moveset.json')
    if not motions or not spec or not spec.get('clips'):
        return None
    names = set(motions)
    carried = {Path(str(c.get('source') or '')).stem for c in spec['clips']}
    twins = sorted(n for n in names if n.endswith('l') and n[:-1] in names)                 # <clip> and <clip>l
    pairs = sorted(n[:-1] for n in names if n.endswith('l') and n[:-1] + 'r' in names and n[:-1] not in names)
    lone = [n for n in twins if n[:-1] in carried and n not in carried]
    halves = [f'{p}{"l" if p + "l" in carried else "r"}' for p in pairs if (p + 'l' in carried) != (p + 'r' in carried)]
    if twins:
        said = f'the game keeps a second copy for facing left of {len(twins)} clips ({", ".join(twins)})'
        said += (f'; the port carries the right-facing one and not {", ".join(lone)}: facing left he plays that one turned round '
                 f'(his back to the screen): a clip to carry or a stand-in to name' if lone else '; each is carried, or its move is not')
    else:
        said = 'the game keeps no clip of this fighter\'s in a second copy named for facing left'
    if halves:      # (told, not judged: whether an l and r pair is for the facing or for which foot leads is the script's word)
        said += (f'. Of {len(pairs)} clips kept as one ending l and one ending r the port carries one of {len(halves)} '
                 f'({", ".join(halves)}): which of the two the game plays when is not read here')
    return ('say' if lone else 'ok'), said


@check('2.2', '9.2')
def free_frames(w):
    """The frame the fighter may act on in each ordinary move. What is compared: the built script's own "may act"
    command, read back by the driver, with the game's script's cancel frame. An action whose clip ends on or one
    frame before the game's frame is given no command and ends with its clip: the same frame. Not in the table:
    dodges, landings and the other actions that are not attacks (their frames are written from the game's tables),
    and any state of the port's own (those are counted in the game)."""
    rows = _rows(w)
    if not rows:
        return None
    same, with_clip, off, unsaid = 0, [], [], []
    for r in rows:
        built, game, frames = r.get('acts'), r.get('game_acts'), r.get('frames')
        if game is None:
            unsaid.append(r['action'])
        elif built == game:
            same += 1
        elif frames is not None and 0 <= game - frames <= 1 and built in (None, frames):
            with_clip.append(r['action'])
        else:
            off.append(f'{r["action"]} frees him on {built} for the game\'s {game} (its clip is {frames} frames)')
    said = (f'the frame he may act on in {len(rows)} ordinary moves, read back from the built scripts against the game\'s: '
            f'{same} the same' + (f', {len(with_clip)} end with their clip on the game\'s frame ({", ".join(with_clip)})' if with_clip else ''))
    if unsaid:
        said += f'; the game\'s script names no frame for {", ".join(unsaid)}'
    if off:
        return 'FAULT', said + '. NOT THE GAME\'S: ' + '; '.join(off)
    return 'ok', said + ' (dodges, landings and the port\'s own states are not in this table)'


@check('3.1')
def untouchable(w):
    """Frames nothing can touch him on. What is compared: the frames the driver wrote for each shared action (its
    receipt) with the game's own dodge table for the four dodges (a first frame and a count). The rest (getups,
    techs, ledge actions) are written from the game's list of motions through each clip's time keys, and only
    counted here."""
    u = (w.report.get('shared') or {}).get('untouchable')
    if u is None:
        return None
    if not u:
        why = (w.game or {}).get('no_dodge_frames')
        if why:                         # the reader says the source game keeps them in no file (checklist 3.10)
            return 'say', f'untouchable frames were written for no action: every dodge, tech and getup keeps the donor\'s ({why})'
        return 'FAULT', 'untouchable frames were written for no action: every dodge, tech and getup keeps the donor\'s'
    params, num = w.game.get('motion_params') or {}, lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    held, off = [], []
    for action, key in DODGES.items():
        first, count = params.get(f'{key}_hit_xlu_frame'), params.get(f'{key}_hit_normal_frame')
        if action in u and num(first) and num(count):
            want = [int(first), int(first + count) - 1]
            (held if list(u[action]) == want else off).append(f'{action} {u[action][0]} to {u[action][1]}' + ('' if list(u[action]) == want else f' for the table\'s {want[0]} to {want[1]}'))
    said = f'untouchable frames written for {len(u)} actions from the game\'s tables'
    if held:
        said += f'; the dodges are the game\'s own table: {", ".join(held)}'
    if off:     # (a clip whose script changes its speed moves these frames: the files here cannot tell that from a fault)
        return 'say', said + '. NOT the dodge table\'s as written (a speed change in the clip moves them; else a fault: count it): ' + '; '.join(off)
    return 'ok', said + (f'; the other {len(u) - len(held)} are counted, not compared' if len(u) > len(held) else '')


@check('4.1', '9.4')
def hitboxes(w):
    """The ordinary moves' hits. What is compared: the first frame a hitbox is out and the damages, read back from
    each built script by the driver, with the game's script (a grab is written a frame early: it takes hold the
    frame after; damage is the game's to the nearest whole number, halves up, at least 1). Not compared: how many
    balls (a drawn-out hitbox is a row of them), the joint, the place, the size, the angle and the knockback."""
    s, rows = w.report.get('scripts') or {}, _rows(w)
    if not s and not rows:
        return None
    if s.get('failed') or s.get('no_hitboxes'):
        return 'FAULT', f'scripts that failed {s.get("failed")}, attacks with no hitbox {s.get("no_hitboxes")}'
    off, held, four = [], 0, []
    # the driver's own rule: more than four hitboxes out at once keeps the strongest four (Melee holds four), and
    # says so in its notes; a damage gone that way is said, not a fault
    cut = {str(n).split(':')[0] for n in s.get('notes') or [] if 'Melee holds 4, kept the strongest' in str(n)}
    for r in rows:
        if 'game_first' not in r:
            continue
        want = r['game_first'] - (GRAB_LEAD if _grab(r) else 0)
        if r.get('first') != want:
            off.append(f'{r["action"]} first hits on {r.get("first")} for the game\'s {r["game_first"]}'
                       + (f' (a grab is written {GRAB_LEAD} early: {want} was wanted)' if _grab(r) else ''))
            continue
        damage = sorted({max(1, int(float(d) + 0.5)) for d in r.get('game_damage') or []})
        if not _grab(r) and sorted(r.get('damage') or []) != damage:
            script = 'game_' + re.sub(r'^c\d\d', '', str(r.get('clip')))
            if script in cut and set(r.get('damage') or []) < set(damage):
                four.append(f'{r["action"]} does {r.get("damage")} of the game\'s {r.get("game_damage")}')
                held += 1
                continue
            off.append(f'{r["action"]} does {r.get("damage")} for the game\'s {r.get("game_damage")}')
            continue
        held += 1
    empty = sorted({r['action'] for r in rows if not r.get('boxes')})
    said = (f'{s.get("written")} attack scripts written, none failed, none without a hitbox; first hit frame and damage of '
            f'{held} ordinary moves are the game\'s (joint, place, size, angle and knockback are not compared here)')
    if four:
        said += ('. More than four hitboxes out at once in the game, the strongest four kept (Melee holds four): '
                 + '; '.join(four))
    if off:
        return 'FAULT', said + '. NOT THE GAME\'S: ' + '; '.join(off)
    return ('say' if empty or four else 'ok'), said + (f'; no hitbox of their own: {", ".join(empty)}' if empty else '')


@check('4.6')
def angles(w):
    notes = [n for n in ((w.report.get('scripts') or {}).get('notes') or []) if 'angle' in n]
    return ('say' if notes else 'ok'), (f'{len(notes)} hits use an angle Melee does not have: ' + '; '.join(notes) if notes else 'no angle had to be written another way')


@check('4.8')
def grabs(w):
    """Grabs and throws. What is compared: the frames the driver wrote each grab on (its receipt) with the game's
    script's first grabbing frame, and each throw's damage and angle, read back from the built script, with the
    game's (damage to the nearest whole number). Not compared: the boxes' reach, the release frame, growth and base,
    which way a throw turns; and nothing here sees the victim hang from the right joint."""
    g = (w.report.get('shared') or {}).get('grabs')
    if g is None:
        return None
    bad = [k for k, v in g.items() if not v.get('boxes')]
    said = 'grab boxes: ' + ', '.join(f'{k} frames {v.get("first")} to {v.get("end")}, {v.get("boxes")} boxes' for k, v in g.items())
    if bad or not g:
        return 'FAULT', said + f'; no box written for {bad or "any grab"}'
    rows = {r['action']: r for r in _rows(w)}
    off, notes, held = [], [], 0
    for action, v in g.items():
        game = (rows.get(action) or {}).get('game_first')
        if game is not None:
            if v.get('first') != game:
                off.append(f'{action} grabs from {v.get("first")} for the game\'s {game}')
            else:
                held += 1
    def amount(text):
        m = re.fullmatch(r'(-?[\d.]+)% at (-?[\d.]+)', str(text))
        return tuple(float(x) for x in m.groups()) if m else None

    throws = 0
    for r in rows.values():
        built, game = r.get('throw'), r.get('game_throw')
        if not built and not game:
            continue
        if not built or not game:
            off.append(f'{r["action"]}: the throw is {built or "not written"} for the game\'s {game or "none"}')
            continue
        if amount(built) is None or amount(game) is None:
            notes.append(f'{r["action"]}: a throw of {built} beside the game\'s {game} could not be read, and is not compared')
            continue
        (d, a), (gd, ga) = amount(built), amount(game)
        if a != ga or abs(d - gd) > 0.5:
            off.append(f'{r["action"]} throws for {built}, the game\'s is {game}')
        else:
            throws += 1
            if d != gd:
                notes.append(f'{r["action"]} {game} is written {built}')
    said += (f'; {held} grabs start on the game\'s frame' if held else '') + (f'; {throws} throws have the game\'s damage and angle' if throws else '')
    if off:
        return 'FAULT', said + '. NOT THE GAME\'S: ' + '; '.join(off)
    return ('say' if notes else 'ok'), said + (f' ({"; ".join(notes)})' if notes else '') + ' (reach, release frame and knockback are not compared here)'


@check('4.9')
def code_hits(w):
    c = w.report.get('code_timed_hits')
    if c is None:
        return None
    return ('say' if c else 'ok'), (f'{len(c)} moves have a hit the game\'s code turns on, timed from published frame data: {", ".join(c)}' if c else 'no hit is turned on by code')


@check('5.5')
def numbers(w):
    """The fighter's block of numbers. The driver's receipt holds how many it set and its notes: neither the values
    nor which were left as the donor's. So nothing is compared with the game's here, and this never says ok."""
    a = w.report.get('attributes') or {}
    if not a:
        return None
    if not a.get('set'):
        return 'FAULT', 'none of the fighter\'s numbers was set: every one is the donor\'s'
    return 'say', (f'{a.get("set")} of the fighter\'s numbers were set from the game\'s' + (f'; notes: {a["notes"]}' if a.get('notes') else '')
                   + '. The receipt gives the count only: which were left as the donor\'s, and why, is for the list given with the port, '
                     'and the values themselves are read once in the game')


@check('5.9', '12.6')
def roster_facts(w):
    e = w.entry()
    if not e:
        return 'FAULT', 'no fighter entry in the package'
    wall = (w.game.get('attributes') or {}).get('wall_jump_type')
    if wall is not None and bool(wall) != bool(e.get('canWallJump')):
        return 'FAULT', f'the source says wall jump {wall}, the entry says {e.get("canWallJump")}'
    n = len(w.costumes)
    team = {c: e.get(f'{c}CostumeIndex') for c in ('red', 'blue', 'green')}
    out = [c for c, i in team.items() if i is None or i >= n]
    if out:
        return 'FAULT', f'team costumes out of range: {team} of {n}'
    same = len(set(team.values())) < 3
    return ('say' if same else 'ok'), f'wall jump {e.get("canWallJump")}; team costumes {team}' + (' (two teams wear the same costume: say why)' if same else '')


@check('6.15')
def same_name(w):
    s = w.game.get('same_name_scripts')
    if s is None:
        return None
    return 'ok', (f'{len(s)} move names carry two scripts (a weapon\'s and the fighter\'s), told apart by the reader: {", ".join(s)}' if s else 'no move name carries two scripts')


@check('6.16')
def item_boxes(w):
    items = w.report.get('own_items')
    if items is None:
        return None
    small = [i['name'] for i in items
             if abs(i['box']['top'] - i['box']['bottom']) < 3 or abs(i['box']['right'] - i['box']['left']) < 3]
    missing = [i['name'] for i in items if i.get('textures_missing')]
    if missing:
        return 'FAULT', f'items with pictures missing: {missing}'
    if small:       # not a fault: the engine itself treats a box under 3 as 3 (mpcoll.c), so these stop a little off the floor
        return 'say', f'{len(items)} items of the port\'s own; the engine stops {", ".join(small)} with a box of 3, larger than drawn (what each does is the game\'s to show)'
    return 'ok', f'{len(items)} items of the port\'s own, every stage box at least 3 tall and wide, no picture missing (what each does is the game\'s to show)'


@check('6.21')
def bank_fresh(w):
    bank, rep = w.dir / 'package' / 'sound.zip', w.dir / w.drv / 'report.json'
    if not bank.exists() or not rep.exists():
        return 'FAULT', 'no bank or no receipt'
    late = bank.stat().st_mtime - rep.stat().st_mtime
    return ('ok' if late >= 0 else 'FAULT'), f'the bank was built {abs(late) / 60:.0f} minutes {"after" if late >= 0 else "BEFORE"} the driver\'s last run'


def _sounds(w):
    """The fighter's own sounds as the built files give them, or None when a receipt is missing.

    named     {sound: [(script, frame)]}: every one a script of the game's plays (`game.json`; the taunt's script and
              the port's own code are in it too, marked `port_plays` and `code_plays` by the driver)
    playable  the sounds the bank holds on a place a script or code can call (the driver's `own_sounds`)
    held      {sound: donor sample}: every sample of the bank file, callable or not (`package/sound.json`)
    plays     the sounds the port's own scripts and code were given (`dressed`, the grabs' sounds, the code's list)
    written   the scripts of the game's that the port writes a script from: one that hits, a special's, the taunt's,
              the code's list; never the final smash's (the bank chooser's own rule, `voice.choose`)"""
    from . import voice
    moves, own, fighter = w.game.get('moves'), w.report.get('own_sounds'), w.game.get('fighter') or w.report.get('fighter')
    if not moves or own is None or not fighter:
        return None
    mine = (f'se_{fighter}_', f'vc_{fighter}_')
    named, written, code, source_silent, source_absent = {}, set(), [], {}, {}
    for script, m in moves.items():
        m = m or {}
        if 'final' not in script and (m.get('hitboxes') or 'special' in script or m.get('port_plays') or m.get('code_plays')):
            written.add(script)
        for e in m.get('sounds') or []:
            n = str(e.get('name') or '').lower()
            if n.startswith(mine) and str(e.get('cmd') or '').startswith('PLAY'):
                source_sound = e.get('source_sound') or {}
                if (w.game.get('game') == 'slapcity' and source_sound.get('bank') == 'fighter'
                        and source_sound.get('exists') is False):
                    source_silent.setdefault(n, []).append((script, e.get('real')))
                    continue
                if (w.game.get('game') == 'rivals2' and source_sound.get('bank') == 'rivals2_sound_tables'
                        and source_sound.get('exists') is False and source_sound.get('reason')):
                    source_absent[n] = source_sound['reason']
                    continue
                named.setdefault(n, []).append((script, e.get('real')))
                if m.get('code_plays'):
                    code.append(n)
    plays = set(code)
    for rows in (w.report.get('dressed') or {}).values():
        plays |= {m.lower() for row in rows for m in re.findall(r'\(its own: ([^)]+)\)', str(row))}
    for names in ((w.report.get('shared') or {}).get('grab_sounds') or {}).values():
        plays |= {str(n).lower() for n in names}
    held = {str(r.get('sound') or '').lower(): str(r.get('sample') or '')
            for r in (w.sound.get('swapped') or []) + (w.sound.get('added') or []) if r.get('sound') != voice.SILENCE}
    # a donor voice sample is played by the engine or a kept script on its own occasion (a jump, a hit taken, a
    # ledge), unless the donor's table says nothing plays it on this route
    idle = set((voice.DONOR.get(str(w.report.get('donor'))) or {}).get('unplayed', {}).get(w.report.get('route'), ()))
    occasion = lambda sample: sample.startswith(('v_', 'se_call_')) and sample not in idle
    return {'fighter': fighter, 'named': named, 'playable': {str(n).lower() for n in own}, 'held': held, 'plays': plays,
            'written': written, 'code': list(dict.fromkeys(code)), 'occasion': occasion, 'left_out': voice.SKIPPED_WORDS,
            'source_silent': source_silent, 'source_absent': source_absent}


def _missing(s):
    """The sounds a script of the game's plays that the bank cannot, in three piles: (the port writes that script
    and nothing leaves the sound out by rule, the rest, the final smash's alone)."""
    silent, others, final = {}, {}, {}
    for n, at in sorted(s['named'].items()):
        if n in s['playable']:
            continue
        if all('final' in script for script, _ in at):
            final[n] = at
        elif any(script in s['written'] for script, _ in at) and not any(word in n for word in s['left_out']):
            silent[n] = [x for x in at if x[0] in s['written']]
        else:
            others[n] = at
    return silent, others, final


def _where(at, most=2):
    return ', '.join(f'{script} frame {frame}' for script, frame in at[:most]) + (f' and {len(at) - most} more' if len(at) > most else '')


@check('6.22', '6.28')
def code_sounds(w):
    """Every sound the fighter's module says its code plays has a place in the bank that code can call. What is
    compared: the module's list (the driver writes it into `game.json`) with the driver's list of callable sounds."""
    s = _sounds(w)
    if s is None:
        return None
    if not s['code']:
        if not w.report.get('own_states'):
            return None                 # no states of its own: nothing here plays a sound from code
        return 'say', 'the fighter\'s module names no sound that its code plays: a sound of its states or items that no script plays is not heard'
    lost = [n for n in s['code'] if n not in s['playable']]
    if lost:
        held = s['held']
        on = ', '.join(f'{n} is on {held[n]}' for n in lost if n in held) or 'not in the bank at all'
        return 'FAULT', f'its code plays {", ".join(lost)}, which the bank holds on no place code can call ({on})'
    return 'ok', f'what its code plays ({", ".join(s["code"])}) is each on a place of the bank that code can call'


@check('7.12')
def bank(w):
    s = w.sound
    if not s:
        return 'FAULT', 'no sound receipt'
    left = s.get('left') or []
    return ('say' if left else 'ok'), (f'{len(s.get("swapped") or [])} donor samples replaced, {len(s.get("added") or [])} added, bank {s.get("bank_bytes"):,} bytes'
                                        + (f'; left: {"; ".join(str(x)[:90] for x in left)}' if left else '; the receipt lists nothing left for want of room'))


@check('7.1', '9.11')
def sounds_two_lists(w):
    """Sounds are two lists. What a script the port writes (or its code) plays must be something the bank can play;
    and a sample nothing plays is a sound the fighter should be making somewhere. What is compared: the game's
    scripts (`game.json`) with the driver's list of callable sounds, the bank's own list of samples
    (`package/sound.json`) and what the port's scripts were given (`dressed`). Not seen from here: the sounds of
    clips with no move script (they are in no receipt), and whether a sound is heard (a recording's)."""
    if not w.sound:
        return 'FAULT', 'no sound receipt: the port has no bank of its own'
    s = _sounds(w)
    if s is None:
        return None
    silent, others, final = _missing(s)
    left = ' '.join(str(x) for x in w.sound.get('left') or []).lower()
    owed = {n: at for n, at in silent.items() if n not in left}
    nothing = sorted(n for n, sample in s['held'].items() if n not in s['plays'] and not s['occasion'](sample))
    where = lambda n: (f'in the bank on {s["held"][n]}, a place no script can call' if n in s['held'] else 'not in the bank')
    said = f'{len(s["named"])} sounds of its own in the game\'s scripts, {len(s["playable"])} the bank can play'
    if s['source_silent']:
        said += '. Silent in the source game (no fighter-bank id): ' + ', '.join(sorted(s['source_silent']))
    if s['source_absent']:
        said += '. Source references without a playable sound entry: ' + '; '.join(
            f'{n} ({reason})' for n, reason in sorted(s['source_absent'].items()))
    if owed:
        said += (f'. SILENT: {len(owed)} that a script the port writes plays and the bank cannot, and no receipt says so: '
                 + '; '.join(f'{n} ({_where(at)}; {where(n)})' for n, at in owed.items()))
    if len(silent) > len(owed):
        said += f'. Left for want of room, by the bank\'s own receipt: {", ".join(n for n in silent if n not in owed)}'
    if others:
        said += f'. {len(others)} more in scripts the port does not write, or left to the engine by rule (the line on clips with no move script lists them)'
    if final:
        said += f'. {len(final)} of the final smash, which is not ported'
    if nothing:
        said += '. In the bank and played by no script or code of the port: ' + ', '.join(f'{n} (on {s["held"][n]})' for n in nothing)
    return ('FAULT' if owed else 'say' if silent or others or nothing or s['source_silent'] or s['source_absent'] else 'ok'), said


@check('7.13')
def sounds_not_written(w):
    """The fighter's own sounds in scripts the port does not write (an entrance, a dodge, a dash's stop), and the
    steps and landings the driver leaves out of the scripts it does write. They are listed: what stands in for
    each, or that the occasion is silent, is for the list given with the port. The files do not say what is heard."""
    s = _sounds(w)
    if s is None:
        return None
    _silent, others, final = _missing(s)
    if not others:
        return 'ok', 'every sound of its own that a script of the game\'s plays is one the bank can play' + (f' (bar {len(final)} of the final smash, which is not ported)' if final else '')
    return 'say', (f'{len(others)} sounds of its own that the game plays and the port does not (none is in the bank; what is heard in '
                   f'its place is not in the files): ' + '; '.join(f'{n} ({_where(at)})' for n, at in others.items()))


@check('7.5')
def art(w):
    folder = w.dir / 'package' / 'art'
    need = [f'{n}_{k}.png' for n in range(len(w.costumes)) for k in ('csp', 'hd', 'stock')]
    missing = [n for n in need if not (folder / n).exists() or (folder / n).stat().st_size == 0]
    return ('FAULT' if missing else 'ok'), (f'missing art: {missing}' if missing else f'portrait, large portrait and stock icon for each of {len(w.costumes)} costumes')


@check('7.10')
def particles(w):
    """The fighter's own particles, converted. What is read: the effect file's receipt: how many generators, the
    effects with emitters not carried, and (a receipt from before shapes were flattened says nothing of them) the
    emitters drawn on 3D shapes, counted apart: carried as flattened STAND-INS, or refused and why; and what each
    emitter drawn with more than one picture got (its pictures combined, a stand-in picture, or left out); and how
    many pictures were made smaller so the texture bank fits (`own_effects.Plan.fit`)."""
    e = w.report.get('effect_file')
    if not e:
        return 'say', 'no effect file of the port\'s own'
    if e.get('warnings'):
        return 'FAULT', f'{e["warnings"]}'
    left = e.get('not_carried') or {}
    said = f'{e.get("generators")} generators converted, {e.get("bytes"):,} bytes'
    shapes = e.get('shapes')
    if shapes is not None:
        why = '; '.join(f'{n} {k}' for k, n in sorted((shapes.get('why') or {}).items(), key=lambda kv: -kv[1]))
        said += (f'; 3D shapes: {shapes.get("carried", 0)} carried as flattened STAND-INS, {shapes.get("refused", 0)} '
                 'refused' + (f' ({why})' if why else ''))
    if e.get('pictures'):
        said += '; emitters of several pictures: ' + ', '.join(f'{n} {k}' for k, n in sorted(e['pictures'].items()))
    if e.get('fitted'):
        said += f'; {len(e["fitted"])} pictures made smaller to fit the texture bank'
    return ('say' if left else 'ok'), said + (f'; not carried in {len(left)} effects: {", ".join(list(left)[:8])}' if left else '')


@check('7.17')
def following_effects(w):
    """An effect the game's script makes follow a bone (EFFECT_FOLLOW...) is held by its joint in the port. What is
    read: the effect file's receipt (each use of an effect: its action, frame and generators, and whether its call
    follows; a receipt from before that was written says nothing of it, and then a call follows when the game's
    scripts only ever call that effect with EFFECT_FOLLOW...), and the behaviour of each of those generators in the
    built effect file in the package (m-ex's table: 5, 6 and 7 are held by the joint; 3 is given off once where the
    call was made and stays there). Not seen from here: whether what is held covers the fighter (the move's pictures)."""
    from . import own_effects
    e = w.report.get('effect_file')
    if not e or not e.get('uses'):
        return None
    calls = {}
    for move in (w.game.get('moves') or {}).values():
        for c in (move or {}).get('effects') or []:
            if c.get('name') and 'OFF' not in str(c.get('cmd')):          # (switching one off places nothing)
                calls.setdefault(c['name'], set()).add('FOLLOW' in str(c.get('cmd')))
    behaviours, source = None, 'the receipt'
    for z in w.fighter_zips():
        with zipfile.ZipFile(z) as f:
            if e.get('file') in f.namelist():
                behaviours = own_effects.read_effect_file(f.read(e['file']))['behaviours']
                source = f'{z.name}/{e["file"]}'
    follow, faults, by_code = 0, [], 0
    for name, rows in e['uses'].items():
        for row in rows:
            follows = row['follow'] if 'follow' in row else calls.get(name) == {True}
            if not follows:
                continue
            follow += 1
            by_code += bool(row.get('by_code'))
            given = [(n, behaviours[n] if behaviours is not None and n < len(behaviours) else b)
                     for _d, n, b in row.get('generators') or []]
            once = [n for n, b in given if b not in own_effects.ATTACHED]
            if once:
                faults.append(f"{name} ({row.get('action')} frame {row.get('frame')} on {row.get('bone')}: "
                              f'{len(once)} of {len(given)} generators given off once, {once[:4]})')
    if not follow:
        return 'ok', 'no effect of its own that the game makes follow a bone'
    if faults:
        return 'FAULT', (f'{len(faults)} of {follow} calls that follow a bone are given off once where the move began '
                         f'(read from {source}): ' + '; '.join(faults[:8]))
    return 'ok', (f'{follow} calls that follow a bone, every generator held by its joint (read from {source})'
                  + (f'; {by_code} of them played by the fighter\'s own code' if by_code else ''))


@check('6.34')
def special_hits(w):
    """A state of the port's own in which the fighter himself strikes. What is read: the driver's receipt of the
    special actions it wrote hitboxes on, and its notes of scripts whose hitboxes it kept and wrote nowhere. The
    hits themselves (frames, damage) are not in a receipt: they are landed in the game."""
    h = w.report.get('special_hits')
    kept = [n for n in (w.report.get('scripts') or {}).get('notes') or [] if 'not written (nothing is built for a special)' in str(n)]
    if h is None and not kept:
        return None
    if h and h.get('failed'):
        return 'FAULT', f'the hitboxes of a special\'s own state could not be written: {h["failed"]}'
    if kept:
        return 'say', f'{len(kept)} scripts of specials have hitboxes that were written on no action: ' + '; '.join(str(n)[:110] for n in kept)
    return 'ok', f'{len(h.get("written") or [])} actions of the fighter\'s own states carry the hitboxes of the game\'s scripts for their clips: {", ".join(h.get("written") or [])}'


@check('7.6')
def flashes(w):
    """The colour a move lays over the body. What is compared: how many of the game's scripts set a colour (the
    reader's `flashes`, `game.json`) with how many actions the port plays one on (the driver's table and the
    fighter's module). The reader lists a flash only where it reads one, so a game file with none says nothing: it
    may be from a reader that did not read them."""
    moves = w.game.get('moves')
    if not moves:
        return None
    lit = sorted(k for k, m in moves.items() if (m or {}).get('flashes') and 'final' not in k)
    table, module = w.report.get('flashes') or [], w.report.get('own_flashes') or []
    if not lit and not table and not module:
        return None
    said = (f'{len(lit)} of the game\'s scripts set a colour over the body' + (f' ({", ".join(lit)})' if lit else '')
            + f'; the port plays one on {len(table) + len(module)} actions ({len(table)} from the driver\'s table, {len(module)} through the fighter\'s module)')
    if lit and not table and not module:
        return 'FAULT', said + ': none of them is carried'
    if len(table) + len(module) < len(lit):
        return 'say', said + ': fewer actions than scripts: say which script\'s flash is not played'
    return 'ok', said


@check('12.14')
def win_sounds(w):
    """The win poses' own sounds. What is read: the driver's receipt of the results screen's scripts, which names
    the poses it gave a sound. What the game's win poses play is in no receipt (they have no move script)."""
    scripts = (w.report.get('demo') or {}).get('scripts')
    if not isinstance(scripts, dict) or 'voiced' not in scripts:
        return None
    voiced = scripts.get('voiced') or {}
    if not voiced:
        return 'say', ('no win pose was given a sound of the fighter\'s own (the receipt names none): if the game\'s win poses make a '
                       'sound, it is not in the bank or not played: hold the game\'s win clips\' sounds against the bank')
    return 'ok', f'{len(voiced)} win poses play sounds of the fighter\'s own on the results screen ({", ".join(str(v) for v in voiced.values())}); heard only by recording that screen'


@check('9.6')
def unread(w):
    u = (w.report.get('shared') or {}).get('unread')
    if u is None:
        return None
    return ('say' if u else 'ok'), (f'not read: {u}' if u else 'the reader reports nothing it did not read in the shared tables (script commands it skips are not listed in the receipt)')


@check('11.26')
def room(w):
    """Room is a sum of file sizes: what is always loaded with the fighter (its data, its effect file), a costume for
    each colour in the match, the stage and the other fighter, against the heap. Three matches are held, the worst
    there are. What is compared: sizes on disk (rounded as the heap rounds) and sizes read once from the game."""
    sizes = [p.stat().st_size for p in (w.dir / 'package' / 'costumes' / r['file'] for r in w.costumes) if p.exists()]
    if not sizes:
        return None
    named = (w.entry() or {}).get('files') or {}
    final = w.dir / w.drv / 'final'
    always = [final / str(named.get('fighterDataPath') or '-'),
              final / str(named.get('effectFile') or (w.report.get('effect_file') or {}).get('file') or '-')]
    found = [p for p in always if p.is_file()]
    held = lambda n: (n + HEAP_ROUND - 1) // HEAP_ROUND * HEAP_ROUND
    costume, fixed = held(max(sizes)), sum(held(p.stat().st_size) for p in found)
    fd, ps = STAGE['Final Destination'], STAGE['Pokemon Stadium']
    cases = (('two of the fighter in two costumes on Final Destination', fixed + 2 * costume + fd[0], len(found) + 2 + fd[1]),
             ('the same on Pokemon Stadium', fixed + 2 * costume + ps[0], len(found) + 2 + ps[1]),
             ('beside Peach on Pokemon Stadium', fixed + costume + PEACH[0] + ps[0], len(found) + 1 + PEACH[1] + ps[1]))
    left = [(label, HEAP - bytes_ - HEAP_FILE * files) for label, bytes_, files in cases]
    said = (f'a costume of {costume:,} bytes and {fixed:,} always loaded ({", ".join(p.name for p in found) or "nothing found"}) '
            f'in a heap of {HEAP:,}: ' + '; '.join(f'{label} {v / 1e6:+.2f} MB' for label, v in left))
    short = [label for label, v in left if v < 0]
    if short:               # (true even where a file was not found: what was found already does not fit)
        return 'FAULT', said + f'. DOES NOT FIT: {"; ".join(short)}: that match does not load'
    if len(found) < len(always):
        return None         # the fighter's data or effect file is not where the build puts it: the sum cannot be made
    worst = min(v for _, v in left)
    if worst < TIGHT:
        return 'say', said + f'. All three fit, the tightest with {worst / 1e6:.2f} MB to spare: asked of the game once, on the last disc, with the picture looked at'
    return 'ok', said + '. All three fit (sizes on disk; the stages\' and Peach\'s were read once from the game)'


@check('12.1')
def emblem(w):
    obj, s = w.dir / 'package' / 'series_emblem.obj', w.json('package/series.json')
    if not obj.exists() or not s:
        return 'say', 'no series of its own: the donor\'s emblem shows'
    faces = sum(1 for line in obj.read_text('utf-8').splitlines() if line.startswith('f '))
    return ('ok' if faces else 'FAULT'), f'series "{s.get("name")}", emblem model of {faces} triangles'


@check('12.2')
def fanfare(w):
    hps, v = w.dir / 'package' / 'victory_theme.hps', w.json('package/victory.json')
    if not hps.exists() or not v:
        return 'say', 'no fanfare of its own: the donor\'s plays'
    return ('ok' if hps.stat().st_size else 'FAULT'), f'fanfare "{v.get("name")}", {hps.stat().st_size:,} bytes (test runs play no music: only an ear confirms it)'


@check('12.3', '12.4')
def outside_files(w):
    d, extra = w.report.get('demo') or {}, w.json(f'{w.drv}/final/extra.json') or {}
    final = w.dir / w.drv / 'final'
    files = list((d.get('files') or {})) + list(extra.get('files') or [])
    named = extra.get('fighter_files') or {}
    wanted = set(files) | {n if n.lower().endswith('.dat') else n + '.dat' for n in named.values()}     # the engine asks for <root>.dat
    missing = [f for f in wanted if not (final / Path(f).name).exists()]
    if missing or not d:
        return 'FAULT', f'clips outside the fight: missing {missing}' if d else 'no receipt of the clips outside the fight'
    held = d.get('held') or {}
    return ('say' if held else 'ok'), (f'results, intro and ending clips in files of the port\'s own ({", ".join(sorted(set(Path(f).name for f in files)))})'
                                        + (f'; held poses: {", ".join(held)}' if held else ''))


@check('12.5')
def name(w):
    e = w.entry()
    if not e:
        return 'FAULT', 'no fighter entry'
    call = (w.dir / 'package' / 'announcer.wav').exists()
    return ('ok' if e.get('name') and call else 'FAULT'), f'name "{e.get("name")}", announcer call {"present" if call else "MISSING"}'


@check('12.12')
def one_player(w):
    verdict, said = outside_files(w)      # the versus card's pose and the trophy fall are asked for by name from these files
    if verdict == 'FAULT':
        return verdict, said
    return 'say', f'{said}; the mode itself is started once in the game (classic_probe.py: its character screen, the versus card, the first fight)'


@check('12.13')
def kirby(w):
    e = w.entry()
    if not e:
        return 'FAULT', 'no fighter entry'
    live = {k: v for k, v in (e.get('functions') or {}).items() if k.lower().startswith('kirby') and v}
    if live:
        return 'FAULT', f'the entry still carries the donor\'s Kirby code ({", ".join(live)}): the game stops when Kirby copies the fighter'
    return 'say', 'every Kirby entry is none: Kirby gets nothing from the fighter and keeps his own special'


@check('10.14')
def reader_output(w):
    """A written game's reader output, held against what the stages read (reader_check, run by preflight). Only a
    written game's port has the line; the answer is preflight's record (preflight.json) of that check."""
    from . import source_game
    pre = w.json('preflight.json')
    if not pre or not source_game.written(pre.get('game')):
        return None
    head = "the reader's "
    rows = [r for r in pre.get('lines') or [] if str(r.get('what', '')).startswith(head)]
    said = 'preflight held the reader\'s output against what the stages read'
    bad = [f"{r['what'][len(head):]}: {r['text']}" for r in rows if r.get('level') == 'PROBLEM']
    if bad:
        return 'FAULT', f'{said}: {"; ".join(bad)}'
    if not rows:
        return 'say', 'preflight ran before it held the reader\'s output (reader_check): run preflight again to answer it'
    notes = [r['what'][len(head):] for r in rows if r.get('level') == 'note']
    return 'ok', f'{said}: nothing wrong' + (f'; notes: {"; ".join(notes)}' if notes else '')


def forms_heap(works):
    """The sums of `forms_room`: -> {'fixed', 'costume', 'costumes' {work folder name: its largest costume}, 'files',
    'clips', 'missing', 'left' [(match, bytes to spare in the files' heap)], 'clip_left' [(match, in the clip heap)]}"""
    held = lambda n: (n + HEAP_ROUND - 1) // HEAP_ROUND * HEAP_ROUND
    fixed = costume = clips = files = 0
    missing, costumes = [], {}
    for work in works:
        w = Work(work)
        named = (w.entry() or {}).get('files') or {}
        final = w.dir / w.drv / 'final'
        sizes = [p.stat().st_size for p in (w.dir / 'package' / 'costumes' / r['file'] for r in w.costumes) if p.exists()]
        always = [final / str(named.get('fighterDataPath') or '-'),
                  final / str(named.get('effectFile') or (w.report.get('effect_file') or {}).get('file') or '-')]
        clip = final / str(named.get('animFile') or '-')
        missing += [f'{w.dir.name}: {p.name}' for p in always + [clip] if not p.is_file()] + ([] if sizes else [f'{w.dir.name}: costumes'])
        fixed += sum(held(p.stat().st_size) for p in always if p.is_file())
        files += sum(1 for p in always if p.is_file())
        costume += held(max(sizes)) if sizes else 0
        costumes[w.dir.name] = max(sizes) if sizes else 0
        clips += clip.stat().st_size if clip.is_file() else 0
    n = len(works)
    fd, ps = STAGE['Final Destination'], STAGE['Pokemon Stadium']
    cases = (('two of it on Final Destination', fixed + 2 * costume + fd[0], files + 2 * n + fd[1]),
             ('two of it on Pokemon Stadium', fixed + 2 * costume + ps[0], files + 2 * n + ps[1]),
             ('beside Peach on Pokemon Stadium', fixed + costume + PEACH[0] + ps[0], files + n + PEACH[1] + ps[1]),
             ('beside Zelda (and Sheik) on Pokemon Stadium', fixed + costume + ZELDA[0] + ps[0], files + n + ZELDA[1] + ps[1]))
    left = [(label, HEAP - b - HEAP_FILE * f) for label, b, f in cases]
    clip_cases = (('alone, or two of it', clips), ('beside Peach', clips + PEACH_CLIPS), ('beside Zelda (and Sheik)', clips + ZELDA_CLIPS))
    clip_left = [(label, CLIP_HEAP - b) for label, b in clip_cases]
    return dict(fixed=fixed, costume=costume, costumes=costumes, files=files, clips=clips, missing=missing,
                left=left, clip_left=clip_left)


def forms_room(works):
    """Room for a fighter of forms (13.7), where every form is loaded with the match: in the files' heap each form's
    data, effects and a costume for each player, beside the stage and a second fighter; in the clip heap every form's
    clip file beside the second fighter's. `works`: the forms' work folders. -> {line: {'verdict', 'how'}}"""
    got = forms_heap(works)
    if got['missing']:
        return {'13.7': {'verdict': 'FAULT', 'how': f"the files the sum is made of are not all there: {got['missing']}"}}
    n, fixed, costume, clips = len(works), got['fixed'], got['costume'], got['clips']
    left, clip_left = got['left'], got['clip_left']
    said = (f'{n} forms: {fixed:,} bytes always loaded and {costume:,} a player in the files\' heap of {HEAP:,}: '
            + '; '.join(f'{label} {v / 1e6:+.2f} MB' for label, v in left)
            + f'. Clip files {clips:,} bytes in the clip heap of {CLIP_HEAP:,}: '
            + '; '.join(f'{label} {v / 1e6:+.2f} MB' for label, v in clip_left))
    short = [label for label, v in left if v < 0] + [f'clips {label}' for label, v in clip_left if v < 0]
    if short:
        return {'13.7': {'verdict': 'FAULT', 'how': said + f'. DOES NOT FIT: {"; ".join(short)}: that match does not load'}}
    worst = min(v for _, v in left + clip_left)
    if worst < TIGHT:
        return {'13.7': {'verdict': 'say', 'how': said + f'. All fit, the tightest with {worst / 1e6:.2f} MB to spare: asked of the game once'}}
    return {'13.7': {'verdict': 'ok', 'how': said + '. All fit (sizes on disk; READINGS for Zelda and Sheik)'}}


def marks():
    """{line id: {'mark', 'look', 'how'}} for every line of the checklist."""
    return json.loads(MARKS.read_text('utf-8'))


ART = ('7.5',)             # the lines that are about the artwork, which a fighter on its own skeleton gets from the round


def run(work, art_later=False):
    """-> {'answers': {line: {'verdict', 'how'}}, 'seconds', 'no_check': [lines marked for the files with no check]}
    `art_later`: the artwork is not due yet (it is cut from the round's pictures), so its lines are left unanswered."""
    w = Work(work)
    start = time.time()
    out = {}
    for line, fn in sorted(CHECKS.items(), key=lambda kv: [int(x) for x in kv[0].split('.')]):
        if art_later and line in ART:
            continue
        try:
            got = fn(w)
        except Exception as error:          # a check that cannot read its receipt is not an answer
            got = ('FAULT', f'the check could not run: {type(error).__name__}: {error}')
        if got is not None:
            out[line] = {'verdict': got[0], 'how': got[1]}
    meant = [i for i, r in marks().items() if r['mark'].startswith('files')]
    return {'answers': out, 'seconds': round(time.time() - start, 2), 'no_check': [i for i in meant if i not in out]}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        raise SystemExit(__doc__)
    got = run(argv[0], art_later='--art-later' in argv)
    out = got['answers']
    for line, row in out.items():
        print(f'{line:>6} {row["verdict"]:5} {row["how"]}')
    by = {}
    for row in out.values():
        by[row['verdict']] = by.get(row['verdict'], 0) + 1
    print(f"\n{len(out)} lines answered from the files in {got['seconds']} s: {by}")
    print(f"marked for the files but with no check yet ({len(got['no_check'])}): " + ', '.join(got['no_check']))
    if '--json' in argv:
        (Path(argv[0]) / 'verify.json').write_text(json.dumps(got, indent=1), 'utf-8')
    return 1 if by.get('FAULT') and '--report-only' not in argv else 0


if __name__ == '__main__':
    raise SystemExit(main())
