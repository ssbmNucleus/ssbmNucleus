"""The four specials at their plainest: the module a new fighter's own is started from.

A fighter can override the shared source runtime with a module of its own (`fighter_port/own_<fighter>.py`, found
by its name: `fighters.specials`). This is the smallest such module the route accepts, and it is real: it goes
through the same build as any fighter's own module. Copy it to `own_<fighter>.py` (the game's own name
for the fighter: Greninja is `gekkouga`), put the fighter's clip names in `SPECIALS`, build, and then turn one
special at a time into what the source game's move is. `SPECIALS.md` beside this file is the guide: what the route
reads from a module, the life of a special in the engine, and one worked example for each kind of special.

What each special does here (the PLAIN form), on the ground and in the air:
  it is entered     the engine calls `SpecialN` / `SpecialAirN` (and S, Hi, Lw); each puts him in a state of his own
  it plays its clip the state's action is the donor action the clip was put on (`CLIPS`)
  it strikes        with the hitboxes the game's own script for that clip makes (`HIT_ACTIONS`); the route also
                    writes that script's sounds and effects, and this module hands over its body flashes
  it ends           on the natural source end (or clip end): standing on the ground, an ordinary fall in the
                    air, the helpless fall after the up special. The earlier cancel frame enables inputs
                    without truncating untouched recovery; helpless up-special air recovery stays locked.
  between           on the ground he slows by his own friction; in the air he falls and drifts as in any attack in
                    the air; he walks off an edge or comes down in the same move, on the frame the clip is at
  turned round      the stick held the other way in its first frames turns it (`entries`)

Generic Slap builds additionally use own_slap_motion and own_slap_projectiles;
generic Rivals builds use own_rivals_motion and own_rivals_states. Their supported
movement, branches and articles are generated from reader data, with explicit
limits in the package report. Custom modules keep the PLAIN scaffold unchanged.

What the PLAIN scaffold alone does NOT do: nothing is made (no shot, no item), nothing moves him but the
engine's own friction, gravity and drift, nothing is held, charged, reflected or countered. Each of those is a KIND
with a section in `SPECIALS.md`; the places they go are marked `KIND` in the C below. A build made with a plain
special says so in `report.json` (`special_numbers`, `code`), so nobody takes it for the move.

Where each number is from is said beside it, in the words the other modules use: script (the fighter's own move
scripts, `game.json`), clip, and the game's list of motions.

The C texts are filled by `own_kit.fill`: @name@ is a value of the build (a float is written as a C float).
"""
from __future__ import annotations

from .own_kit import fill               # (and, for a module that needs them: number, hitbox, flag_frame, ITEM_LOST,
                                        #  item_code, fx, real_frames)
from .own_timing import NEVER, move_timing, interrupt_callback
from .own_kit import helpless_landing

# ---- what the route reads from this module (all but `build` may be left out: SPECIALS.md, "What the route reads") ----

# The four specials. For each:
#   c        the letters of its C names. The engine calls `Special<c>` on the ground and `SpecialAir<c>` in the air
#            (the kit links a function to the engine by its name, from the list in MexTK's ftFunction.txt: these
#            eight for the specials; OnLoad, OnFrame and move_logic are the code file's own).
#   clips    the fighter's own clips for the ground and the air, by name after the three-character start of the
#            file (`d00specialn.nuanmb` is `specialn`). The game's script for a clip is `game_<clip>`.
#            CHANGE THESE to the clips the fighter has: a special in three clips (start, loop, end) plays its
#            first here until it is given states for the rest.
#   actions  the donor action each clip is put on. A state plays an ACTION (a clip and its script).
#   like     the donor's own state for the same input: a state of the fighter's keeps that row's flags and the
#            number the engine knows the move by (stale moves, what a hit is counted as).
#   helpless he falls helpless after it (an up special).
SPECIALS = (
    dict(key='neutral', c='N', clips=('specialn', 'specialairn'), actions=('SpecialS3Hi', 'SpecialAirS3Hi'),
         like=('SpecialNStart', 'SpecialAirNStart'), helpless=False),
    dict(key='side', c='S', clips=('specials', 'specialairs'), actions=('SpecialS1', 'SpecialAirS1'),
         like=('SpecialS1', 'SpecialAirS1'), helpless=False),
    dict(key='up', c='Hi', clips=('specialhi', 'specialairhi'), actions=('SpecialHi', 'SpecialAirHi'),
         like=('SpecialHi', 'SpecialAirHi'), helpless=True),
    dict(key='down', c='Lw', clips=('speciallw', 'specialairlw'), actions=('SpecialLw', 'SpecialAirLw'),
         like=('SpecialLw', 'SpecialAirLw'), helpless=False),
)
# The donor's (Marth's) special actions that the driver's own rule (`oneshot.special_rows`) leaves alone for most
# fighters: the places for the clips of more states (a start, a loop, an end, a landing). The driver's rule fills
# SpecialNStart, SpecialNLoop and SpecialNEnd with a clip named `specialn` CUT IN THREE (which is why the neutral
# special above plays on SpecialS3Hi, where the clip is whole), SpecialS1 with `specials`, SpecialHi with
# `specialhi`, SpecialLw with `speciallw`, and the same in the air. It also fills SpecialS2Hi to SpecialS4Lw when the
# fighter has side special clips numbered `specials1`, `specials2` ... (a chain), and an action whose name a clip
# has (`speciallwhit` goes on SpecialLwHit). A clip of another name sent to an action the driver has filled does
# not get it, and nothing but `<work>/spec/skipped.json` says so: `build` below reads that file and stops.
FREE_ACTIONS = ('SpecialS2Hi', 'SpecialS2Lw', 'SpecialS3Hi', 'SpecialS3S', 'SpecialS3Lw', 'SpecialS4Hi', 'SpecialS4S',
                'SpecialS4Lw', 'SpecialAirS2Hi', 'SpecialAirS2Lw', 'SpecialAirS3Hi', 'SpecialAirS3S', 'SpecialAirS3Lw',
                'SpecialAirS4Hi', 'SpecialAirS4S', 'SpecialAirS4Lw', 'SpecialLwHit', 'SpecialAirLwHit')

# {clip: donor action}: the clips of his own states. The route puts each on its action, stored one frame longer
# than its keys (a state of his own is entered with a step: see `Enter`). A clip the fighter does not have is
# passed over, and the special that wanted it is left out by `build`.
CLIPS = {clip: motion for sp in SPECIALS for clip, motion in zip(sp['clips'], sp['actions'])}
# The actions of his own states in which the fighter HIMSELF strikes: the route writes their hitboxes from the
# game's script for the clip on each, as it does an attack's. An action named here whose script makes no hitbox
# costs nothing. Leave an action out when its script's hitboxes are not his (a script that is really an article's).
HIT_ACTIONS = tuple(motion for sp in SPECIALS for motion in sp['actions'])
# The sounds of his that only his CODE plays (an item's, a state's own: no script the port writes names them), in
# the order they matter when the bank is short of room. Each gets a place in his bank that code can call
# (`ctx['sound_ids']`). The plain specials play none: their sounds are their scripts'.
CODE_SOUNDS = ()
# The names of the values of the fighter's parameter file (`vl.prc`, which holds only a hash of each name) that
# `build` reads from `ctx['vl']`: the table names (`param_special_n` ...) and the values in them. None here.
NAMES = ()


HEAD = '''
// ---- his own states: each special at its plainest -----------------------------------------------
#define B_BUTTON 0x200                  // the special button, in fd->input.held (down now) and fd->input.down (pressed this frame)
#define ST_FIRST_OWN @first@            // the first state of his own (the donor's own come before it in the table)
#define NEVER @never@                   // a frame no clip reaches
static u16 t_frame[6];                  // by player: the frame of the state of his own he is in (1 on the frame it is entered)

// Into a state of his own. `ActionStateChange` puts him in it at the start of its clip; `Fighter_AdvanceScript`
// then runs the clip's and the script's first frame at once, as the game's own code does for a special. Without
// it the script starts a frame late. (The frame a state is entered on already runs the state's movement and its
// collision: it is the state's first.)
static void Enter(GOBJ *gobj, int state)
{
    FighterData *fd = gobj->userdata;
    ActionStateChange(0, 1, 0, gobj, state, 0, 0);
    Fighter_AdvanceScript(gobj);
    t_frame[fd->ply] = 1;
}
// The same move's other form (ground for air, air for ground), on the frame its clip is at: 0x5000 keeps the
// body's colour and has the script go on from that frame, not from its start. (Hitboxes that were out are taken
// down by it, and nothing before that frame is played again. So hand over on a frame BEFORE the one the script
// makes its boxes on, never on it: those are taken down at once and never come out.)
static void Hand_Over(GOBJ *gobj, int state)
{
    FighterData *fd = gobj->userdata;
    ActionStateChange(fd->state.frame, 1, 0, gobj, state, 0x5000, 0);
}
// The frame of the move this is. Called once, first thing, by a state's animation call: 2 the first time (the
// frame the state was entered on was its first), so it is the frame the script has just run.
static int Tick(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    if (t_frame[fd->ply] < NEVER)
        t_frame[fd->ply]++;
    return t_frame[fd->ply];
}
// Out of a special: standing on the ground; in the air an ordinary fall, or the helpless fall with the frames of
// landing it ends in.
static void Leave(GOBJ *gobj, int helpless, float landing)
{
    FighterData *fd = gobj->userdata;
    if (fd->phys.air_state == 0)
        Fighter_EnterWait(gobj);
    else if (helpless)
        Fighter_EnterSpecialFall(gobj, 1, 0, 1, 1.0f, landing);
    else
        Fighter_EnterFall(gobj);
}
// The same move's other form: the air state for a ground one, the ground state for an air one. Written at the end
// of this file by `build`, from its list `forms` (a state you add that hands over to another form goes in it too).
static int Other_Form(int state);
// PHYSICS, each frame after the animation call. What a state does not do here is not done: on the ground this
// slows him by his own friction and hands on the speed he has (a clip that travels along the ground is given to
// him as speed by the route's own per-frame code where it can be: report.json `travel`); in the air the engine
// moves him by `self_vel`, and this gives him gravity (with fast fall) and drift, as an attack in the air has:
// `Fighter_PhysAir_ApplyGravityFastfall` does all three (the game's ft_80084DB0 calls the drift itself, so a
// second call of `Fighter_PhysAir_ApplyAerialDrift` after it adds nothing).
// KIND: a dash, a rise, a hang in the air: a physics call of the state's own (SPECIALS.md "A dash that hits",
// "A recovery that rises").
void Plain_Phys(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    if (fd->phys.air_state == 0)
        Fighter_PhysGround_ApplyFriction(gobj);
    else
        Fighter_PhysAir_ApplyGravityFastfall(gobj);
}
// COLLISION, each frame after he has moved: what the stage may do to him. Here the move goes on where it was:
// off an edge he is in the air form, come down he is in the ground form, on the same frame of the clip.
// KIND: stop at an edge, land with lag, catch a ledge: another call (SPECIALS.md "What the collision call decides").
void Plain_Coll(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    if (fd->phys.air_state == 0)
    {
        if (Fighter_CollGround_PassLedge(gobj) == 0)
        {
            Fighter_SetAirborne(fd);
            Hand_Over(gobj, Other_Form(fd->state_id));
        }
    }
    else if (Fighter_CollAir_IgnoreLedge_NoCB(gobj) != 0)
    {
        Fighter_SetGrounded2(fd);
        Hand_Over(gobj, Other_Form(fd->state_id));
    }
}
'''

NEUTRAL = '''
// ---- the neutral special: PLAIN (its clip, its script's hits, its end) ---------------------------
#define ST_N @n@                        // its state on the ground,
#define ST_N_AIR @n_air@                //   and in the air
#define N_END @n_end@                   // the natural end, on the ground (NEVER: at the clip's end),
#define N_END_AIR @n_end_air@           //   and in the air
void SpecialN(GOBJ *gobj)
{
    Enter(gobj, ST_N);
}
void SpecialAirN(GOBJ *gobj)
{
    Enter(gobj, ST_N_AIR);
}
// ANIMATION, each frame after the clip and the script have moved on: what the move does on this frame, and
// whether it is over.
void N_Anim(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    int frame = Tick(gobj);
    // KIND: a shot fired, a thing placed or thrown, a helper that appears: made here on the frame the game's
    // script lets it go (SPECIALS.md "A shot fired"):      if (frame == N_FIRE) Shoot(gobj);
    // KIND: a charge: a state that loops while B_BUTTON is held and counts its frames (SPECIALS.md "A charge").
    if (frame >= (fd->phys.air_state == 0 ? N_END : N_END_AIR) || FrameTimerCheck(gobj) == 0)
        Leave(gobj, 0, 0);
}
'''

SIDE = '''
// ---- the side special: PLAIN ------------------------------------------------------------------------
#define ST_S @s@
#define ST_S_AIR @s_air@
#define S_END @s_end@                   // the natural end, on the ground,
#define S_END_AIR @s_end_air@           //   and in the air
void SpecialS(GOBJ *gobj)
{
    Enter(gobj, ST_S);
}
void SpecialAirS(GOBJ *gobj)
{
    Enter(gobj, ST_S_AIR);
}
void S_Anim(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    int frame = Tick(gobj);
    // KIND: a dash that hits: three states (he gathers himself, the dash, the arrival), each begun here by the
    // one before as its frames run out (SPECIALS.md "A dash that hits").
    // KIND: a move that vanishes and reappears: no example yet (SPECIALS.md "Kinds with no example").
    if (frame >= (fd->phys.air_state == 0 ? S_END : S_END_AIR) || FrameTimerCheck(gobj) == 0)
        Leave(gobj, 0, 0);
}
'''

UP = '''
// ---- the up special: PLAIN (he does not rise: he is helpless after it in the air) -------------------
#define ST_HI @hi@
#define ST_HI_AIR @hi_air@
#define HI_END @hi_end@                 // the natural end, on the ground,
#define HI_END_AIR @hi_end_air@         //   and in the air
#define HI_LANDING @hi_landing@         // frames of landing after the helpless fall (the game's list of motions)
void SpecialHi(GOBJ *gobj)
{
    Enter(gobj, ST_HI);
}
void SpecialAirHi(GOBJ *gobj)
{
    Enter(gobj, ST_HI_AIR);
}
void Hi_Anim(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    int frame = Tick(gobj);
    // KIND: a recovery that rises: he leaves the ground (Fighter_SetAirborne) and is given his speed as the
    // rise begins, with a physics call that keeps it and a collision call that catches a ledge
    // (SPECIALS.md "A recovery that rises").
    if (frame >= (fd->phys.air_state == 0 ? HI_END : HI_END_AIR) || FrameTimerCheck(gobj) == 0)
        Leave(gobj, 1, HI_LANDING);
}
'''

DOWN = '''
// ---- the down special: PLAIN ------------------------------------------------------------------------
#define ST_LW @lw@
#define ST_LW_AIR @lw_air@
#define LW_END @lw_end@                 // the natural end, on the ground,
#define LW_END_AIR @lw_end_air@         //   and in the air
void SpecialLw(GOBJ *gobj)
{
    Enter(gobj, ST_LW);
}
void SpecialAirLw(GOBJ *gobj)
{
    Enter(gobj, ST_LW_AIR);
}
void Lw_Anim(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    int frame = Tick(gobj);
    // KIND: a reflector: a bubble put up again on every frame it should stand (SPECIALS.md "A reflector").
    // KIND: a counter: no example on this route yet (SPECIALS.md "Kinds with no example").
    // KIND: a helper that appears and acts: an item made here (SPECIALS.md "A helper that appears and acts").
    if (frame >= (fd->phys.air_state == 0 ? LW_END : LW_END_AIR) || FrameTimerCheck(gobj) == 0)
        Leave(gobj, 0, 0);
}
'''

FRAME = '''
// ---- once as he is made, and once a frame -----------------------------------------------------------
// As the fighter is made (the route calls the donor's own load first). Every variable kept by player is cleared
// here: a rematch starts with what the last match left in them otherwise.
// KIND: a module that makes things tells m-ex each item's number here (SPECIALS.md "A thing a special makes"):
//     ItemDesc **items = fd->ftData->items;
//     for (i = 0; items && i < ITEM_COUNT; i++) if (items[i]) MEX_IndexFighterItem(fd->kind, items[i], i);
static void OwnLoad(FighterData *fd)
{
    t_frame[fd->ply] = 0;
}
// Every frame, whatever state he is in, before the frame's clip moves on. For what no one state can see: a thing
// he made asking him for something, a meter, a rule that outlasts the special (no jump until he stands).
static void OwnFrame(FighterData *fd, GOBJ *gobj)
{
}
'''

FORMS = '''
// ---- the other form of each state that has one (from `forms` in `build`) ------------------------------
static int Other_Form(int state)
{
    switch (state)
    {
@cases@
    }
    return state;                       // (a state not listed: a mistake; it stays the state it is)
}
'''

TEXT = {'neutral': NEUTRAL, 'side': SIDE, 'up': UP, 'down': DOWN}


def other_forms(forms):
    """The `case` lines of `Other_Form`: each (ground state, air state) pair, by their C names, both ways round."""
    return '\n'.join(f'    case {g}: return {a};\n    case {a}: return {g};' for g, a in forms)


def spec_of(ctx):
    """What the driver did with the clips, this run: ({donor action: the clip on it, by its file's name without the
    ending}, {(clip name, donor action): the clip that took the action first}), from the spec it wrote
    (`<work>/spec`). Both empty when there is no work folder to read (a test)."""
    import json
    from pathlib import Path
    if not ctx.get('work'):
        return {}, {}
    spec = Path(ctx['work']) / 'spec'
    try:
        clips = json.loads((spec / 'moveset.json').read_text('utf-8'))['clips']
        skipped = json.loads((spec / 'skipped.json').read_text('utf-8'))
    except (OSError, ValueError, KeyError):
        return {}, {}
    on = {c['target_motion']: c['source'].rsplit('/', 1)[1][:-len('.nuanmb')] for c in clips}
    taken = 'already filled by '
    lost = {(stem[3:], motion): why[len(taken):] for stem, motion, why in skipped
            if str(why).startswith(taken) and why[len(taken):] != stem}
    return on, lost


def build(ctx):
    return build_plain(ctx, SPECIALS)


def build_plain(ctx, specials):
    """-> (what the code file needs for the fighter's own states, or None; why not). `ctx` as `own_route.run` makes
    it (its keys are listed in SPECIALS.md). A special whose clip is not on its action is left out, and said: the
    donor's own state then answers that input and does nothing, as it does for a fighter with no module.
    An explicitly empty specials tuple returns the shared scaffold for a fully custom module."""
    from .oneshot import flash_keys, script_for
    action, total, moves, row = ctx['action'], ctx['total'], ctx['moves'], ctx['row']
    first = int(ctx['first'])
    on, lost = spec_of(ctx)
    numbers = {}

    def note(special, what, value, source):
        numbers.setdefault(special, []).append({'what': what, 'value': value, 'from': source})
        return value

    def state(name, motion, like, **calls):
        # (a row of the state table: the action it plays, the donor row it is like, its calls by their C names)
        return dict({'name': name, 'action': action[motion], 'flags': like['flags'], 'move': like['move']}, **calls)

    def script_of(clip, motion):
        # the game's script for the clip on an action (by the file the driver put there, when the spec says)
        return moves.get(script_for(on.get(motion) or 'xxx' + clip, moves)) or {}

    def timing(special, form, move):
        end, interrupt = move_timing(move)
        note(special, f'natural end, {form}', end if end != NEVER else "the clip's end",
             "source end in real updates; independent of the first input-interrupt frame")
        note(special, f'frame he may act from, {form}', interrupt if interrupt != NEVER else 'no early interrupt',
             "cancel_frame_real enables current-input checks; it does not force idle")
        return end, interrupt

    landing = float(helpless_landing(ctx))
    values, rows, texts, entries, flash, provides, left_out = {'first': first, 'never': NEVER}, [], [], [], [], [], []
    motion_bindings = []
    rivals_bindings = []
    common_items, common_load, common_frame = [], [], []
    # (ground state, air state) by their C names: every state that hands over to its other form (`Other_Form`).
    # A special turned into a kind with more states adds a pair for each of them that has an air form.
    forms = []
    for sp in specials:
        key, c = sp['key'], sp['c'].lower()
        if key == ctx.get('switch'):
            # a fighter of forms: this special switches to the next form, and `forms.py` builds it
            note(key, 'the switch to the next form', 'forms.py', 'fighters.FORMS')
            continue
        for clip, motion in zip(sp['clips'], sp['actions']):
            if (clip, motion) in lost:
                return None, (f"the {key} special's clip {clip} was to go on the donor action {motion}, and "
                              f"{lost[clip, motion]} had it first (the driver's own rule fills that action): put the "
                              f'clip on an action left free ({", ".join(FREE_ACTIONS)})')
        (clip, clip_air), (ground, air) = sp['clips'], sp['actions']
        if ground not in action or not total.get(ground) or any(m not in row for m in sp['like']):
            left_out.append(f'{key} (no clip named {clip} on {ground})')
            note(key, 'NOT BUILT', f'no clip named {clip} on {ground}', "the fighter's clips: name the one it has in SPECIALS")
            continue
        if air not in action or not total.get(air):
            note(key, 'in the air it plays the clip of the ground', ground, f'the fighter has no clip named {clip_air}')
            air, clip_air = ground, clip
        for form, name, motion in (('on the ground', clip, ground), ('in the air', clip_air, air)):
            have = on.get(motion)
            if have is not None and have[3:] != name:
                note(key, f'{form} it plays the clip', have[3:], f'what the spec has on {motion} (the fighter has no clip named {name})')
        n = first + len(rows)
        rows += [state(f'the {key} special (plain)', ground, row[sp['like'][0]],
                       anim=f"{sp['c']}_Anim", iasa=f"{sp['c']}_IASA", phys='Plain_Phys', coll='Plain_Coll'),
                 state(f'the {key} special in the air (plain)', air, row[sp['like'][1]],
                       anim=f"{sp['c']}_Anim", iasa=f"{sp['c']}_IASA", phys='Plain_Phys', coll='Plain_Coll')]
        move, move_air = script_of(clip, ground), script_of(clip_air, air)
        motion_bindings += [(n, move.get('slapcity_move'), sp['helpless']),
                            (n + 1, move_air.get('slapcity_move'), sp['helpless'])]
        rivals_bindings += [(n, action[ground], move, sp['helpless']),
                            (n+1, action[air], move_air, sp['helpless'])]
        end, interrupt = timing(key, 'on the ground', move)
        end_air, interrupt_air = timing(key, 'in the air', move_air)
        values.update({c: n, c + '_air': n + 1, c + '_end': end, c + '_end_air': end_air})
        if sp['helpless']:
            values[c + '_landing'] = note(key, 'frames of landing after the helpless fall', landing,
                                          "the game's list of motions: the frame a helpless landing is free on, less one")
        note(key, 'PLAIN', 'its clip, the hits of its script, its end: nothing made, nothing moved, nothing held',
             'own_template.py: the move itself is not written yet')
        texts.append(fill(TEXT[key], values))
        texts.append(interrupt_callback(f"{sp['c']}_IASA", interrupt, None if sp['helpless'] else interrupt_air))
        forms.append((f"ST_{sp['c'].upper()}", f"ST_{sp['c'].upper()}_AIR"))
        # the stick held the other way in its first frames turns it round (`code.source`'s `reverse`)
        entries += [n, n + 1]
        # the colour its scripts lay over the body: the route plays a script's flashes only for the actions its own
        # table installs, which a special's are not, so they are handed over here
        for motion, got in dict(((ground, move), (air, move_air))).items():
            flash += [(action[motion], *k) for k in flash_keys(got.get('flashes') or [], 0)]
        provides.append(f'the {key} special, plain: its clip and the hits of its script'
                        + (', helpless after it in the air' if sp['helpless'] else ''))
    if not rows and specials:
        return None, 'none of the four specials has its clip on its action: ' + '; '.join(left_out)
    if left_out:
        provides.append('NOT BUILT (the donor\'s own state answers, and does nothing): ' + '; '.join(left_out))
    values['cases'] = other_forms(forms)
    source = fill(HEAD, values) + ''.join(texts) + fill(FRAME, values) + fill(FORMS, values)
    game = ctx.get('source_game') or {}
    if ctx.get('generic_specials') and game.get('game') == 'slapcity' and motion_bindings:
        from . import own_slap_motion, own_slap_projectiles, own_slap_states
        source, destinations, transitions = own_slap_states.apply(ctx, source, rows, motion_bindings, flash, landing)
        numbers['transitions'] = transitions
        articles = own_slap_projectiles.Builder(ctx)
        if any(not name for _, name, _ in motion_bindings):
            return None, 'generic Slap specials require the reader source move identities'
        movement, receipt = own_slap_motion.build(motion_bindings, game,
            float(game['unit']) * float(ctx.get('drawn', 1.0)), landing, articles, values, destinations)
        common_items, common_load = articles.items, articles.load()
        numbers['projectiles'] = articles.receipt
        source = source.replace('static void Enter(GOBJ *gobj, int state)',
            'static void PM_Enter(GOBJ *gobj);\nstatic void PM_Load(FighterData *fd);\n'
            'static void Enter(GOBJ *gobj, int state)', 1)
        source = source.replace('    t_frame[fd->ply] = 1;', '    t_frame[fd->ply] = 1;\n    PM_Enter(gobj);', 1)
        source = source.replace('    t_frame[fd->ply] = 0;', '    t_frame[fd->ply] = 0;\n    PM_Load(fd);', 1)
        source += movement
        wrappers = set()
        for native_row in rows:
            native_row.update(phys='PM_Phys', coll='PM_Coll')
            callback = native_row['iasa']
            if callback not in wrappers:
                source += f'\nvoid PM_{callback}(GOBJ *gobj) {{ if(!PM_InputCancel(gobj)) {callback}(gobj); }}\n'
                wrappers.add(callback)
            native_row['iasa'] = f'PM_{callback}'
        if receipt['contact_hooks']:
            from . import own_contacts
            source += '\n' + '\n'.join(own_contacts.source('PM_OnHit', 'PM_NoHurt'))
            common_load.append('Contact_Load(fd,gobj);')
        numbers['movement'] = receipt
        if common_items:
            provides.append(f'source projectiles: {len(common_items)} source models with launch, movement, native contact and cleanup')
        provides.append('common Slap movement: ordered source assignments, atomic choices, delayed actions, '
                        'jump-height launches, gravity/drift, live input and contact callbacks, move transitions, jump resources and native ledges')
        for key in numbers:
            if isinstance(numbers[key], list):
                for note_row in numbers[key]:
                    if note_row.get('what') == 'PLAIN':
                        note_row['what'] = 'COMMON'
                        note_row['value'] = 'clip, hitboxes and supported source program; see movement limits for remaining mechanics'

    if ctx.get('generic_specials') and game.get('game') == 'rivals2':
        from . import own_rivals_motion, own_rivals_states, own_rivals_spawns, own_rivals_grabs
        source, transitions = own_rivals_states.apply(ctx, source, rows, rivals_bindings, flash, landing)
        numbers['transitions'] = transitions
        movement, receipt = own_rivals_motion.generic(rivals_bindings, game, float(ctx.get('drawn',1)), landing,
                                                     branches=True, article_adapter=True)
        source += movement
        article_builder=ctx.get('rivals_article_builder',own_rivals_spawns.build)
        article_source, common_items, article_load, article_receipt = article_builder(ctx,rivals_bindings)
        numbers['projectiles'] = article_receipt
        if common_items:
            source = 'static unsigned rp_fired[6];\n' + source
            source = source.replace('    t_frame[fd->ply] = 1;',
                '    t_frame[fd->ply] = 1;\n    rp_fired[fd->ply] = 0;', 1)
            source += article_source
            common_load += article_load
            provides.append('source articles: shared phase physics, hit memory, model, native contact and bounded cleanup')
        for native_row in rows:
            native_row.update(phys='RP_Phys' if common_items else 'RV_Phys',coll='RV_Coll')
        grab_source, grab_receipt = own_rivals_grabs.build(ctx, rows, rivals_bindings,
                                                         'RP_Phys' if common_items else 'RV_Phys')
        numbers['grabs'] = grab_receipt
        if grab_source:
            source = 'static void RG_Enter(GOBJ *gobj);\nstatic int RG_IsHolding(GOBJ *gobj);\n' + source
            source = source.replace('    t_frame[fd->ply] = 1;',
                '    t_frame[fd->ply] = 1;\n    RG_Enter(gobj);', 1)
            source = source.replace('ActionStateChange(frame-1,1,0,gobj,state,0,0);',
                'ActionStateChange(frame-1,1,0,gobj,state,RG_IsHolding(gobj) ? 0x4000 : 0,0);', 1)
            source += grab_source
            common_load.append('RG_Load(fd);')
            common_frame.append('RG_Frame(fd,gobj);')
            for native_row in rows:
                native_row.update(anim='RG_Anim', iasa='RG_IASA', phys='RG_Phys', coll='RG_Coll')
            provides.append('declared special grabs: native capture, source hold/release and interruption cleanup')
        numbers['movement'] = receipt
        provides.append('common Rivals movement and states: source window physics, native ledges, input/grounding branches and reachable follow-up clips')
        for key in numbers:
            if isinstance(numbers[key],list):
                for note_row in numbers[key]:
                    if note_row.get('what') == 'PLAIN':
                        note_row['what']='COMMON'
                        note_row['value']='clip, hitboxes and supported window movement; see movement limits for remaining mechanics'

    return {'source': source.strip('\n').split('\n'), 'rows': rows, 'items': common_items, 'load': ['OwnLoad(fd);'] + common_load, 'frame': ['OwnFrame(fd, gobj);'] + common_frame,
            'entries': entries, 'numbers': numbers, 'flash': flash, 'provides': provides}, None
