"""A fighter of forms: two or more fighters, one at a time, switched in play by a move (PORT_CHECKLIST section 13).

What the recipe is TOLD is one entry in `fighters.FORMS` (the group: its forms in the order the switch goes round,
which special switches, the clips that end one form and begin the next, published timings). Everything else is the
same route as any fighter on its own skeleton: each form is ported by itself (its own skeleton, normals, movement,
costumes; its specials from its own module or the template), and this module adds, to every form alike:

  states    four states of the switch, the FIRST of the fighter's own (so they have the same numbers in every form,
            which is what lets one form's code put the next in its arriving state): leaving (ground, air) plays the
            clip that ends a form, and on its last frame the next form takes his place; arriving (ground, air) plays
            the clip that begins it, until the frame the game's list of motions lets him act from
  the code  `Form_Switch` hands the player over with Melee's own transformation (`Fighter_Transform`, the call
            Zelda and Sheik use): position, facing, damage, speed, ground or air, the shield, a held item and the
            stocks go with him, as they do for Sheik. Melee keeps two fighters per player (`Playerblock.gobj`); a
            third form and on is made the first time it is needed (`Fighter_Create`, its files already loaded: see
            the preload below) and the one it displaces is kept in the fighter's own variable `FORM_PARKED`, which
            is handed along at each switch. Which form is next is read in the game, from m-ex's table of fighters
            (each form's `subCharacter` is the next: the link stage writes the ring), so no form's code names another
  the disc  (`harness/forms_link.py`) every form installed into one project, the ring written, the character
            select screen showing only the first form (named for the group: `name`), and a code that loads every
            form of the ring as the match loads (`preload_code`): Melee loads a fighter and its one partner and no
            more, and making a fighter whose files were never loaded stops the game (measured in September)

What is NOT the game's here, and is said in every build's report: the trainer standing behind the stage; the
Poke Ball thrown (the clips' own shrink and the scripts' sounds play, nothing else); a KO'd form comes back as itself
(Melee's rule for Sheik), where the game sends out the next in line.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

from . import fighters

# the two donor actions the arriving clips go on: free on Marth for every fighter (own_template.FREE_ACTIONS)
ARRIVE_ACTIONS = ('SpecialLwHit', 'SpecialAirLwHit')
STATES = 4                              # leaving and arriving, on the ground and in the air
# the fighter variables the switch keeps (the last of the 52: no donor code or module of the route uses them)
PARKED, CLOCK = 'fighter_var.ft_var50', 'fighter_var.ft_var51'


def group_of(fighter):
    """(group, entry) when `fighter` is one of a group's forms, else (None, None). The group itself is not a form."""
    name, entry = fighters.group(fighter)
    if name is None or name == fighter:
        return None, None
    return name, entry


def switch_special(entry):
    """The template's row for the special that switches (`own_template.SPECIALS`, by its key)."""
    from .own_template import SPECIALS
    key = entry.get('switch') or 'down'
    found = [sp for sp in SPECIALS if sp['key'] == key]
    if not found:
        raise ValueError(f"switch {key!r}: not one of the four specials ({', '.join(sp['key'] for sp in SPECIALS)})")
    return found[0]


def clips(fighter, have=None):
    """{clip: donor action} for the switch's clips of a form (empty for any other fighter). The clips that end a
    form go on the switch special's own actions, the ones that begin the next on two actions left free. `have`: the
    form's clip names; a clip it does not have is left out (the air state then plays the ground's)."""
    _, entry = group_of(fighter)
    if entry is None:
        return {}
    sp = switch_special(entry)
    leave = tuple(entry.get('leave') or sp['clips'])
    arrive = tuple(entry.get('arrive') or ())
    out = dict(zip(leave, sp['actions']))
    out.update(zip(arrive, ARRIVE_ACTIONS))
    return {c: m for c, m in out.items() if have is None or c in have}


TEXT = '''
// ---- a fighter of forms: the switch (forms.py) --------------------------------------------------------
// Four states, the first of his own in every form: leaving (ground, air), arriving (ground, air).
#define FORM_LEAVE @leave@
#define FORM_LEAVE_AIR @leave_air@
#define FORM_ARRIVE @arrive@
#define FORM_ARRIVE_AIR @arrive_air@
#define FORM_HAS_ARRIVE @has_arrive@            // the group has clips that begin a form
#define FORM_LEAVE_FRAMES @leave_frames@        // frames of the clip that ends a form (clip)
#define FORM_ARRIVE_END @arrive_end@            // the frame of the arriving clip he may act from (the game's list of motions)
#define FORM_WAIT @wait@                        // frames from one switch before the next may begin (published)
#define FORM_UNTOUCHABLE @untouchable@          // frames from the press in which he cannot be hit (published)
#define FORM_PARKED @parked@                    // a form of this player made and in neither of his two places (GOBJ *)
#define FORM_CLOCK @clock@                      // frames before he may switch again
#define FORM_CREATE ((GOBJ *(*)(void *))0x80068E98)     // Fighter_Create, from the engine's own allocation record
#define FORM_INPUT_ON ((void (*)(GOBJ *))0x8008688C)    // ftLib_8008688C: a fighter made after GO is given his inputs
typedef struct { int kind; u8 slot; s8 x5; u8 flags; u8 pad; } FormAlloc;   // plAllocInfo
#define FORM_ALLOC_FLAGS 0xC0                   // made for a player, as one of his forms (asleep until switched to)

// The form after this one: m-ex's table of fighters, by the number the character select screen picks, gives each
// its partner (`subCharacter`), and the link stage made the partners a ring. -1: not a fighter of forms.
static int Form_Next(int kind)
{
    FtKindDesc *desc = MEX_GetData(MXDT_FTKINDDESC);
    int n = (int)MEX_GetData(MXDT_FTEXTNUM), e;
    for (e = 0; e < n; e++)
        if (desc[e].ft_main == kind && desc[e].ft_sub >= 0 && desc[e].ft_sub != kind)
            return desc[e].ft_sub;
    return -1;
}
// The kind of a fighter, or -1 for a pointer that is not one (a variable that outlived its fighter).
static int Form_KindOf(GOBJ *g)
{
    unsigned int p = (unsigned int)g;
    FighterData *f;
    if (p < 0x80300000u || p >= 0x81800000u || (p & 3) != 0)
        return -1;
    f = g->userdata;
    p = (unsigned int)f;
    if (p < 0x80300000u || p >= 0x81800000u || (p & 3) != 0)
        return -1;
    return f->kind;
}
static void Form_Done(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    Fighter_SetAllHurtboxState(gobj, 0);
    if (fd->phys.air_state == 0)
        Fighter_EnterWait(gobj);
    else
        Fighter_EnterFall(gobj);
}
// On the form that arrives (Melee's transformation calls it once he has taken the player's place).
static void Form_Arrived(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    Playerblock *pb = Fighter_GetPlayerblock(fd->ply);
    GOBJ *from = pb->gobj[pb->isTransformed[1]];
    if (from != 0 && from != gobj)
    {
        FighterData *was = from->userdata;
        fd->FORM_PARKED = was->FORM_PARKED;     // the form kept aside goes with the player
        fd->FORM_CLOCK = was->FORM_CLOCK;
    }
    // the input block came across whole, the press of the switch with it: without this he switches again at once
    fd->input.timer_speciallw = 0xFF;
#if FORM_HAS_ARRIVE
    ActionStateChange(0, 1, 0, gobj, fd->phys.air_state == 0 ? FORM_ARRIVE : FORM_ARRIVE_AIR, 0, 0);
    Fighter_AdvanceScript(gobj);
    Fighter_SetAllHurtboxState(gobj, FORM_UNTOUCHABLE > FORM_LEAVE_FRAMES ? 2 : 0);
#else
    Form_Done(gobj);
#endif
}
// The switch itself, on the last frame of the leaving clip. -> 1 when another form took his place.
static int Form_Switch(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    Playerblock *pb = Fighter_GetPlayerblock(fd->ply);
    int want = Form_Next(fd->kind), idle = pb->isTransformed[1];
    GOBJ *other;
    FormAlloc info;
    if (want < 0 || idle > 1 || pb->gobj[pb->isTransformed[0]] != gobj)
        return 0;
    if (Form_KindOf(pb->gobj[idle]) != want)
    {
        other = (GOBJ *)fd->FORM_PARKED;
        if (Form_KindOf(other) != want)
        {
            // the first time this player needs this form: made now (its files were loaded with the match)
            info.kind = want;
            info.slot = fd->ply;
            info.x5 = -1;
            info.flags = FORM_ALLOC_FLAGS;
            info.pad = 0;
            other = FORM_CREATE(&info);
            if (other == 0)
                return 0;
            FORM_INPUT_ON(other);
        }
        fd->FORM_PARKED = (int)pb->gobj[idle];   // the one it displaces is kept aside, never unloaded
        pb->gobj[idle] = other;
    }
    Fighter_Transform(gobj, Form_Arrived);
    return 1;
}
static void Form_Begin(GOBJ *gobj, int state)
{
    FighterData *fd = gobj->userdata;
    fd->input.timer_speciallw = 0xFF;            // the press is spent, whether he switches or not
    if (fd->FORM_CLOCK > 0 || Form_Next(fd->kind) < 0)
        return;                                  // too soon after the last: nothing happens
    fd->FORM_CLOCK = FORM_WAIT;
    ActionStateChange(0, 1, 0, gobj, state, 0, 0);
    Fighter_AdvanceScript(gobj);
    Fighter_SetAllHurtboxState(gobj, FORM_UNTOUCHABLE > 0 ? 2 : 0);
}
void Special@c@(GOBJ *gobj)
{
    Form_Begin(gobj, FORM_LEAVE);
}
void SpecialAir@c@(GOBJ *gobj)
{
    Form_Begin(gobj, FORM_LEAVE_AIR);
}
void Form_Leave_Anim(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    if (fd->state.frame + 1 < FORM_UNTOUCHABLE)
        Fighter_SetAllHurtboxState(gobj, 2);
    if (FrameTimerCheck(gobj) == 0 && Form_Switch(gobj) == 0)
        Form_Done(gobj);                         // (no other form to go to: he stays)
}
void Form_Arrive_Anim(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    int frame = (int)fd->state.frame + 1;
    Fighter_SetAllHurtboxState(gobj, frame + FORM_LEAVE_FRAMES < FORM_UNTOUCHABLE ? 2 : 0);
    if (frame >= FORM_ARRIVE_END || FrameTimerCheck(gobj) == 0)
        Form_Done(gobj);
}
void Form_Phys(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    if (fd->phys.air_state == 0)
        Fighter_PhysGround_ApplyFriction(gobj);
    else
        Fighter_PhysAir_ApplyGravityFastfall(gobj);
}
static void Form_Other(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    int s = fd->state_id, to = s;
    if (s == FORM_LEAVE) to = FORM_LEAVE_AIR;
    else if (s == FORM_LEAVE_AIR) to = FORM_LEAVE;
    else if (s == FORM_ARRIVE) to = FORM_ARRIVE_AIR;
    else if (s == FORM_ARRIVE_AIR) to = FORM_ARRIVE;
    ActionStateChange(fd->state.frame, 1, 0, gobj, to, 0x5000, 0);
}
void Form_Coll(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    if (fd->phys.air_state == 0)
    {
        if (Fighter_CollGround_PassLedge(gobj) == 0)
        {
            Fighter_SetAirborne(fd);
            Form_Other(gobj);
        }
    }
    else if (Fighter_CollAir_IgnoreLedge_NoCB(gobj) != 0)
    {
        Fighter_SetGrounded2(fd);
        Form_Other(gobj);
    }
}
static void FormLoad(FighterData *fd)
{
    fd->FORM_PARKED = 0;
    fd->FORM_CLOCK = 0;
}
static void FormFrame(FighterData *fd)
{
    if (fd->FORM_CLOCK > 0)
        fd->FORM_CLOCK--;
}
'''


def _cancel(work, clip):
    """The frame the game's list of motions lets him act from in a clip (by its name after the three-letter
    start), or 0."""
    try:
        motions = json.loads((Path(work) / 'game.json').read_text('utf-8')).get('motions') or {}
    except (OSError, ValueError, TypeError):
        return 0
    row = next((v for k, v in motions.items() if k[3:] == clip), None) or {}
    return int(row.get('cancel_frame') or 0)


def build(fighter, specials_of, ctx, inner):
    """The code of a form's own states: the switch's four (first), then its specials from `inner(specials_of,
    ctx)` (the template or its own module), told to leave the switch out (`ctx['switch']`) and to number its states
    after the switch's. -> (what the code file needs, or None; why not). For a fighter that is not a form, `inner`
    as it is."""
    from .own_kit import fill
    group, entry = group_of(fighter)
    if entry is None:
        return inner(specials_of, ctx)
    sp = switch_special(entry)
    action, total, row = ctx['action'], ctx['total'], ctx['row']
    first = int(ctx['first'])
    placed = clips(fighter)
    on = {m: c for c, m in placed.items()}
    leave_g, leave_a = sp['actions']
    arrive_g, arrive_a = ARRIVE_ACTIONS
    if leave_g not in action or not total.get(leave_g):
        return None, (f"the form's clip that ends it ({on.get(leave_g)}) is not on {leave_g}: the switch cannot be "
                      'built (fighters.FORMS: leave)')
    if leave_a not in action or not total.get(leave_a):
        leave_a = leave_g
    has_arrive = arrive_g in action and bool(total.get(arrive_g))
    if not has_arrive:
        arrive_g = arrive_a = leave_g
    elif arrive_a not in action or not total.get(arrive_a):
        arrive_a = arrive_g
    like_g, like_a = row[sp['like'][0]], row[sp['like'][1]]

    def state(name, motion, like, anim):
        return {'name': name, 'action': action[motion], 'flags': like['flags'], 'move': like['move'],
                'anim': anim, 'phys': 'Form_Phys', 'coll': 'Form_Coll'}

    rows = [state('the switch: leaving', leave_g, like_g, 'Form_Leave_Anim'),
            state('the switch: leaving, in the air', leave_a, like_a, 'Form_Leave_Anim'),
            state('the switch: arriving', arrive_g, like_g, 'Form_Arrive_Anim'),
            state('the switch: arriving, in the air', arrive_a, like_a, 'Form_Arrive_Anim')]
    arrive_clip = on.get(ARRIVE_ACTIONS[0])
    arrive_end = _cancel(ctx.get('work') or '', arrive_clip) if has_arrive and arrive_clip else 0
    numbers = [{'what': 'the switch: frames of the clip that ends a form', 'value': int(total[leave_g]), 'from': 'clip'},
               {'what': 'the switch: the frame he may act from as he arrives',
                'value': arrive_end or "the clip's end",
                'from': "the game's list of motions" if arrive_end else 'clip (the list names no such frame)'},
               {'what': 'the switch: frames before the next may begin', 'value': int(entry.get('wait') or 0),
                'from': 'fighters.FORMS (published frame data)'},
               {'what': 'the switch: frames from the press he cannot be hit', 'value': int(entry.get('untouchable') or 0),
                'from': 'fighters.FORMS (published frame data)'}]
    values = dict(leave=first, leave_air=first + 1, arrive=first + 2, arrive_air=first + 3,
                  has_arrive=int(has_arrive), leave_frames=int(total[leave_g]), arrive_end=arrive_end or 30000,
                  wait=int(entry.get('wait') or 0), untouchable=int(entry.get('untouchable') or 0),
                  parked=PARKED, clock=CLOCK, c=sp['c'])
    mine, why = inner(specials_of, dict(ctx, first=first + STATES, switch=sp['key']))
    if mine is None:
        mine, why = {'source': [], 'rows': [], 'load': [], 'frame': [], 'entries': [], 'numbers': {}, 'flash': [],
                     'provides': []}, why
    out = dict(mine)
    out['source'] = fill(TEXT, values).strip('\n').split('\n') + [''] + list(mine.get('source') or [])
    out['rows'] = rows + list(mine.get('rows') or [])
    out['load'] = ['FormLoad(fd);'] + list(mine.get('load') or [])
    out['frame'] = ['FormFrame(fd);'] + list(mine.get('frame') or [])
    out['numbers'] = dict(mine.get('numbers') or {}, switch=numbers)
    out['provides'] = ([f"the switch ({sp['key']} special): {group}'s next form takes his place, with Melee's own "
                        'transformation (damage, stocks, place, facing, speed, ground or air, a held item go with him); '
                        f"leaving plays {on.get(sp['actions'][0])}, arriving {arrive_clip or 'nothing'}"]
                       + list(mine.get('provides') or [])
                       + ['NOT the game\'s: no trainer behind the stage, no Poke Ball thrown; a KO\'d form comes back as '
                          'itself (Melee\'s rule for Sheik), where the game sends out the next'])
    out['forms'] = {'group': group, 'states': [first, first + STATES - 1], 'leave': on.get(sp['actions'][0]),
                    'arrive': arrive_clip, 'inner': None if why is None else why}
    return out, None


# ---------------------------------------------------------------------------------------------------- the preload
# A C2 code at 0x80031D14, the end of Player_80031CB0 (lbDvd's preload asks it, once for each player, to load the
# fighter picked: it loads that fighter and its partner and returns). Here r31 is the picked fighter's number times
# three, r30 the colour, and the frame's own registers are restored after it, so it may use them. For a fighter of a
# ring it loads every OTHER form of the ring the same way (ftData_800855C8: data, costume, effects, clips), which is
# what lets a third form be made mid-match. The rings are a table in the code (`rings`: internal numbers, written by
# the link stage). Assembled with devkitPPC (powerpc-eabi-as -mregnames) from the text beside each word.
PRELOAD_AT = 0x80031D14
_HEAD = (0x9421FFE0,    # stwu  r1,-0x20(r1)
         0xBF410008)    # stmw  r26,0x8(r1)
#                         bl    over the table (made by `preload_code`: its length is the table's)
_BODY = (0x7FA802A6,    # mflr  r29                   the table: [members, internal ids ...]*, 0
         0x81820008,    # lwz   r12,8(r2)             m-ex's table of fighters by the number picked (3 bytes each),
         0x7F8CF8AE,    # lbzx  r28,r12,r31           read as m-ex's own patch at 0x80031CCC reads it: the picked one
         0x7F9C0774,    # extsb r28,r28
         0x8B7D0000,    # ring: lbz r27,0(r29)
         0x2C1B0000,    # cmpwi r27,0
         0x4182007C,    # beq   done
         0x3B400000,    # li    r26,0
         0x387D0001,    # find: addi r3,r29,1
         0x7C03D0AE,    # lbzx  r0,r3,r26
         0x7C00E000,    # cmpw  r0,r28
         0x4182001C,    # beq   hit
         0x3B5A0001,    # addi  r26,r26,1
         0x7C1AD800,    # cmpw  r26,r27
         0x4180FFE8,    # blt   find
         0x7FBDDA14,    # add   r29,r29,r27
         0x3BBD0001,    # addi  r29,r29,1
         0x4BFFFFCC,    # b     ring
         0x3B400000,    # hit: li r26,0
         0x387D0001,    # each: addi r3,r29,1
         0x7C63D0AE,    # lbzx  r3,r3,r26
         0x7C03E000,    # cmpw  r3,r28                the picked one is loaded already
         0x41820030,    # beq   skip
         0x81820008,    # lwz   r12,8(r2)
         0x7D8CFA14,    # add   r12,r12,r31
         0x880C0001,    # lbz   r0,1(r12)             ... and so is its partner
         0x7C000774,    # extsb r0,r0
         0x7C030000,    # cmpw  r3,r0
         0x41820018,    # beq   skip
         0x7FC4F378,    # mr    r4,r30
         0x3D808008,    # lis   r12,0x8008
         0x618C55C8,    # ori   r12,r12,0x55c8        ftData_800855C8(internal number, colour)
         0x7D8903A6,    # mtctr r12
         0x4E800421,    # bctrl
         0x3B5A0001,    # skip: addi r26,r26,1
         0x7C1AD800,    # cmpw  r26,r27
         0x4180FFBC,    # blt   each
         0xBB410008,    # done: lmw r26,0x8(r1)
         0x38210020,    # addi  r1,r1,0x20
         0x8001001C)    # lwz   r0,0x1c(r1)           the instruction the hook stands in place of


def preload_code(rings):
    """The Gecko lines of the preload (a C2 code): `rings` is [[internal numbers of one fighter's forms], ...]."""
    table = bytearray()
    for ring in rings:
        ring = [int(k) for k in ring]
        if not 2 <= len(ring) < 128 or any(not 0 <= k < 0x80 for k in ring):
            raise ValueError(f'a ring of forms is 2 or more fighter numbers under 128: {ring}')
        table += bytes([len(ring)] + ring)
    table += b'\0'
    while len(table) % 4:
        table += b'\0'
    words = list(_HEAD) + [0x48000001 | (4 + len(table))] + list(struct.unpack(f'>{len(table) // 4}I', bytes(table))) \
        + list(_BODY)
    words += [0x60000000, 0] if len(words) % 2 == 0 else [0]
    lines = [f'C2{PRELOAD_AT & 0x01FFFFFF:06X} {len(words) // 2:08X}']
    lines += [f'{words[i]:08X} {words[i + 1]:08X}' for i in range(0, len(words), 2)]
    return lines


# ---------------------------------------------------------------------------------------------------- the link
def link_project(data_dir, kinds, behaviour=1):
    """Write the ring into a project's fighters: each form's partner (`subCharacter`) is the next, the last's the
    first, as Melee's own Zelda and Sheik are each other's (`subCharacterBehavior` 1). `kinds`: the forms' internal
    numbers in the order the switch goes round. -> {internal number: partner}"""
    data_dir = Path(data_dir)
    ring = {k: kinds[(i + 1) % len(kinds)] for i, k in enumerate(kinds)}
    for k, partner in ring.items():
        path = data_dir / 'fighters' / f'{k:03d}.json'
        entry = json.loads(path.read_text('utf-8'))
        entry['subCharacter'], entry['subCharacterBehavior'] = partner, behaviour
        path.write_text(json.dumps(entry, indent=2), 'utf-8')
    return ring


def one_on_the_screen(css, externals):
    """The character select screen's list with only the first form's slot: `externals` are the forms' numbers on
    that screen, first form first. -> (the list, [the slots taken off])"""
    gone = set(int(e) for e in externals[1:])
    icons = css.get('fighterIcons') or []
    kept = [i for i in icons if int(i.get('fighter', -1)) not in gone]
    return dict(css, fighterIcons=kept), sorted(gone & {int(i.get('fighter', -1)) for i in icons})


# ---------------------------------------------------------------------------------------------------- the room
# Every form is loaded with the match (13.7). A form's clip file goes whole into the clip heap beside the other
# forms' and the second fighter's, so each form is given an equal share of what is left there beside the costliest
# second fighter (Zelda, who brings Sheik), less the margin the room check asks for: its clip bank is made at a
# looser tolerance until it fits its share (`own_bank.BUDGETS`, a step of which is a factor of 1.41).
LOOSEST = 8                             # steps: the tolerance at most 16 times the first
STEP_SHRINKS = 0.95                      # a bank's size after one step looser, of its size before
SMALLEST_SIDE = 64                       # a form's pictures are never made smaller than this a side


def clip_share(fighter):
    """The bytes a form's clip file may have, or None for a fighter that is not a form."""
    from . import verify
    group, entry = group_of(fighter)
    if entry is None:
        return None
    return (verify.CLIP_HEAP - verify.ZELDA_CLIPS - verify.TIGHT) // len(entry['forms'])


def looser(size, share, now):
    """The next step of the bank's tolerance for a bank of `size` bytes over its `share`. Measured (Squirtle, 183
    clips): a step makes the bank about 5% smaller (2,420,192 -> 2,194,240 in two, 1,962,912 in four more), far
    less than the keys alone would say (much of a clip is headers and joints that do not move)."""
    import math
    return min(LOOSEST, now + max(1, math.ceil(math.log(size / share) / -math.log(STEP_SHRINKS))))


def bank(own_bank, start, make):
    """`make()` (an own_bank.build) with the bank's tolerances begun `start` steps looser (the cache keys carry the
    tolerances, so each step's clips are kept apart)."""
    kept = own_bank.BUDGETS
    try:
        own_bank.BUDGETS = kept[start:]
        return make()
    finally:
        own_bank.BUDGETS = kept


def heap_short(works):
    """The matches of the room (`verify.forms_heap`) the forms in these work folders do not fit in the files' heap."""
    from . import verify
    return [label for label, left in verify.forms_heap(works)['left'] if left < 0]


def shrink_side(works):
    """When the files' heap is short: the form whose pictures are made smaller (the one with the largest costume
    whose side can still halve) and its new side. -> (its work folder, side) or None. A form's work folder is named
    for it (`port.run_forms`)."""
    from pathlib import Path
    from . import own_skeleton, verify
    sizes = verify.forms_heap(works)['costumes']
    for work in sorted((Path(w) for w in works), key=lambda w: -sizes.get(w.name, 0)):
        side = own_skeleton.picture_side_for(work.name, work)
        if side // 2 >= SMALLEST_SIDE:
            return work, side // 2
    return None


def stale_disc(iso, works):
    """The forms whose costumes are newer than the group's disc: photographed there, they would be pictures of the
    costumes before (the art stage runs on the linked disc, and a run started after the link reuses the last one;
    the pictures it takes are then newer than the costumes and are kept). -> [form folder names]"""
    from pathlib import Path
    iso = Path(iso)
    made = iso.stat().st_mtime if iso.exists() else 0.0
    return [Path(w).name for w in works
            if any(p.stat().st_mtime > made for p in (Path(w) / 'package' / 'costumes').glob('*.dat'))]
