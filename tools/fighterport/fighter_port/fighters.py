"""What a port is TOLD about one fighter: the one place a new fighter is written into the code.

A fighter that is not here still ports. Everything the route can read from the game's own files it reads, and each
value below has a rule that stands in when nobody gave one; `python -m fighter_port.preflight` (the port command's
first stage) prints, for the fighter in hand, which of these were given, which were worked out and how, and which
are simply not there. So a new fighter is: run the command, read what preflight says, and write here only what the
game's files could not say.

The values (each is read through this module by the stage named):

  bindings        {slot: bone name or None}, laid over what `bindings` works out. The engine has 54 named places on
                  a body (hip, head, the hands, each finger: `compat.bone_lookup.SLOTS`) and wants a joint for each
                  it uses. WORKED OUT when not given: the game's bones carry the same names on every fighter (Hip,
                  Bust, Head, LegL, KneeL, HandR, HaveR, FingerL11 ...), and the one thing a name does not say,
                  which digit is the thumb, is measured on the rest pose (`thumb`). Give a slot here only to
                  overrule that. (The tables measured before this rule was written are in `native_port.BINDINGS`
                  and are used as they are.)                                        [prepare: `own_skeleton.lookup`]
  item_hold       the joint an item is held at, by name. NOT GIVEN: the right hold slot, then the left;
                  without either, the bound right hand, then the left. Explicit choices must exist. The hand
                  fallback is a Melee item-placement adaptation for games without hold bones. [prepare]
  taunt           the clip Melee's one taunt plays, by its name after the three-letter start (`appealsr`). NOT
                  GIVEN: the down taunt. A fighter known for another names it.              [driver: `oneshot.taunt_row`]
  code_timed_hits {move script: (frames from its hitbox being made to its hit, frames it hits for)}: hits the game's
                  CODE times and its script does not (a hitbox the script never ends). From published frame data.
                  NOT GIVEN: every hitbox is on the frames its script says.                  [driver: `own_route.shots`]
  code_timed_effects  (the effect shown while such a hit is aimed, frames one showing lasts, the effect of the hit
                  itself). NOT GIVEN: none.                                                  [driver: `own_route.shots`]
  code_shown      parts of the body the game shows and hides in its code, which no clip's tracks say:
                  {'rest': {node: drawn at rest}, 'clips': {clip: {node: (frame it changes on, drawn before, drawn
                  from it on)}}}. NOT GIVEN: the clips' own word, and a part no clip names is always drawn. Found
                  by listing the model's parts no clip names and asking of each what the game does with it.
                                                                                            [prepare: `own_faces.read`]
  article_parts   a weapon the game keeps as a second model and puts in a hand in its code, carried as parts of the
                  body: [dict(folder, node, joint, held_at)] (`own_skeleton.with_articles`). NOT GIVEN: nothing is
                  put in the hand.                                                          [prepare: `own_skeleton.body`]
  lopsided        pairs of hurtboxes (the right one's joint name) that the game's own table gives lopsided by more
                  than the capsule's own width, looked at and accepted as the game's. NOT GIVEN: such a pair stops
                  the fighter-data stage (`own_data.capsule_check` says which, with the game's numbers). [prepare]

A fighter's SPECIALS are not a value but code: a module `fighter_port/own_<fighter>.py` (found by its name, nothing
to register; `specials`), started from `own_template.py` with `SPECIALS.md` as the guide. It gives `build(ctx)` and may give `CLIPS`
({clip: the donor action left free for it}), `HIT_ACTIONS` (actions of its states in which the fighter himself
strikes), `CODE_SOUNDS` (sounds its code plays) and `NAMES` (the names of the values of its parameter file that it
reads). Without the module the port still builds, with the plain specials of `own_template.py` (each plays its
clip and strikes with its script's hits, nothing more).

What is NOT per fighter and so is not here: the donor's own tables (`own_data.DONOR`, `own_skeleton.DONOR`, the
driver's `*_DONOR` tables: one donor, Marth, has been measured; `donors`), and the room rules for pictures
(`own_skeleton.PICTURE_SIDE`, by the picture's stored format, the same for every fighter).

What is per fighter and is NOT gathered here yet: the specials of a fighter ported onto the DONOR's skeleton (Cloud,
Byleth, Ike). There the donor's own special states are kept and a fighter's moves are fitted to them by tables
beside the code that reads each (`ON_THE_DONOR` lists every one, and `written_on_the_donor` which of them name a
fighter). None has to exist for the command to run; preflight lists them on that route.
"""
from __future__ import annotations

import importlib
import importlib.util

FIGHTERS = {
    # Duck Hunt (2026-11): the first fighter on a skeleton of its own.
    'duckhunt': dict(
        # the game's own item-idle clip (a00waititem against a00wait1, first frames) leaves both front paws planted
        # and moves only `Have`, the joint in front of its mouth: the dog carries things in its mouth
        item_hold='Have',
        taunt='appealsr',                               # the dog's laugh is the side taunt
        # each smash is three shots of an aiming reticle. PUBLISHED FRAME DATA (ultimateframedata.com, read
        # 2026-11-12: forward smash hits on 17-18, 23-24 and 29-30, up and down smash on 12-13, 20-21 and 28-29),
        # and it agrees with the game's own sound script, which plays each shot five frames after its hitbox is made
        code_timed_hits={'game_attacks4': (5, 2), 'game_attackhi4': (5, 2), 'game_attacklw4': (5, 2)},
        # READING: the aim is shown from the frame the script makes the shot's hitbox, again each time one showing
        # has run out, and the flash on the frame it hits
        code_timed_effects=('duckhunt_target', 4, 'duckhunt_target_flash'),
    ),
    # Wolf (2026-11-12, the cold trial: a session that had only this repository).
    'wolf': dict(
        taunt='appealhir',                              # his howl is the up taunt
        # the gun at his hip is a part of his body, and the game's code hides it while the same gun, a second
        # model the game makes as the neutral special starts, is in his hand (script: game_specialn deals with
        # its articles on frames 2, the gun is made, and 16, it fires)
        code_shown={'rest': {'wolf_blaster': True, 'blaster_hand': False},
                    'clips': {stem: {'wolf_blaster': (1, True, False), 'blaster_hand': (1, False, True)}
                              for stem in ('d00specialn', 'd00specialairn')}},
        article_parts=[dict(folder='blaster', node='blaster_hand', joint='HaveR', held_at='Have')],
    ),
    # Ittle Dew (Slap City, 2026-11-13: the first fighter of a Unity game, read by echo_slapcity).
    'ittledew': dict(
        # Slap City has no items, so no hold bone: an item is held at the right fist (`r_fist`), the hand she
        # holds her stick in
        item_hold='HandR',
    ),
    # Fishbunjin 3000 (Slap City, 2026-11-13: the second fighter of the game, a cold trial).
    'fishbunjin': dict(
        # no hold bone (as Ittle Dew). His right hand is two parts the clips switch by size: `r_fist` (HandR by the
        # reader's names, made nothing by his standing clip) and the open hand `r_hand`, drawn at rest; a held
        # item goes in the open hand
        item_hold='r_hand',
    ),
}

# what each value is called when preflight speaks of it, and what stands in when it is not given
VALUES = {
    'bindings': ("which joint is which for the engine", 'by bone name, the thumb measured'),
    'item_hold': ('the joint an item is held at', 'a hold slot, else a bound hand'
                 ),
    'taunt': ("the clip Melee's one taunt plays", 'the down taunt'),
    'code_timed_hits': ("hits the game's code times", 'none: every hitbox on the frames its script says'),
    'code_timed_effects': ('what such a hit is seen by', 'none'),
    'code_shown': ("parts the game's code shows and hides", "none: the clips' own word"),
    'article_parts': ('a weapon that is a second model, carried in the hand', 'none: nothing is put in the hand'),
    'lopsided': ("hurtbox pairs the game's table gives lopsided, accepted", 'none'),
}
MODULE_NAMES = ('build', 'CLIPS', 'HIT_ACTIONS', 'CODE_SOUNDS', 'NAMES')

# ------------------------------------------------------------------------------------------------- fighters of forms
# A fighter that is two or more fighters, one at a time, switched in play by a move (Pokemon Trainer: Squirtle,
# Ivysaur, Charizard; Zelda and Sheik in Brawl). Each FORM is ported as a fighter of its own, on its own skeleton,
# with its own normals and movement (an entry above if it needs one, a module own_<form>.py for its specials); the
# group is what is picked: `python -m fighter_port.port <group> --own ...` ports every form and builds them onto one
# disc as linked fighters (`forms.py` says how). The values of a group:
#
#   name      what the player picks on the character select screen (the first form's slot carries it)
#   forms     ((the form's name in the game's files, its name in Melee), ...) in the order the switch goes round;
#             the first is the one a match starts as
#   switch    which special switches ('down': the down special); the forms' own specials leave it out
#   leave     the clips that end a form (ground, air): it is switched on the last frame of one. NOT GIVEN: the
#             switch special's own clips (`<special>`, `<special air>`)
#   arrive    the clips that begin the next (ground, air), the frame he may act from read from the game's list of
#             motions. NOT GIVEN: none (he stands, or falls, as he arrives)
#   wait      frames from one switch before the next may start. NOT GIVEN: 0
#   untouchable  frames from the press in which he cannot be hit. NOT GIVEN: 0
#   call      the announcer's call for the group, by its name in the game's bank of names. NOT GIVEN: the group's
#             name in the game's files
#
# Each value is the GAME'S where the game's files say it, and published frame data where only the game's code knows
# (said beside it).
FORMS = {
    'ptrainer': dict(
        name='Pokemon Trainer',
        forms=(('pzenigame', 'Squirtle'), ('pfushigisou', 'Ivysaur'), ('plizardon', 'Charizard')),
        switch='down',
        # the game's clips of Pokemon Change: the Pokemon is called back (11 frames) and the next is sent out (39)
        leave=('speciallwin', 'specialairlwin'), arrive=('speciallwout', 'specialairlwout'),
        # PUBLISHED (SmashWiki "Pokemon Trainer (SSBU)", ultimateframedata.com, read 2026-11-13): intangible on
        # frames 1-25 of the switch; about 140 frames from one switch before the next may begin
        wait=140, untouchable=25,
        call='poketrainer',             # vc_narration_characall_poketrainer, in the bank of names every fighter shares
    ),
}
FORM_VALUES = {
    'name': ('what the player picks', "the group's name in the game's files"),
    'forms': ('the forms, in the order the switch goes round', 'none: it is not a fighter of forms'),
    'switch': ('the special that switches', 'the down special'),
    'leave': ('the clips that end a form', "the switch special's own clips"),
    'arrive': ('the clips that begin the next', 'none'),
    'wait': ('frames before the next switch may begin', '0'),
    'untouchable': ('frames of the switch in which he cannot be hit', '0'),
    'call': ("the announcer's call", "the group's name in the game's files"),
}


def group(fighter):
    """(the group's name, its entry) for a group or for one of its forms, or (None, None) for a fighter of one form."""
    if fighter in FORMS:
        return fighter, FORMS[fighter]
    for name, entry in FORMS.items():
        if fighter in [f for f, _ in entry['forms']]:
            return name, entry
    return None, None

# The per-fighter tables of the route on the DONOR's skeleton, each beside the code that reads it: (module, name,
# what it holds). All are optional: a fighter in none of them gets the donor's own special states with whichever
# of its clips fit them (`oneshot.special_rows`). `tests/test_fighters.py` holds this list against the code, so a
# table added there and not here fails a test.
ON_THE_DONOR = (
    ('oneshot', 'CHARGE_CUT', 'a start clip that holds both a draw and its charge: where to cut it'),
    ('oneshot', 'SHOT_GAME', "where the game keeps a fighter's shots (the weapon script, its model, its numbers)"),
    ('oneshot', 'SECOND_COLOUR', 'the script whose trail colour the second versions of its specials are drawn in'),
    ('oneshot', 'ARMOUR_GAME', 'a special that cannot be knocked out of its swing: its script and first frame'),
    ('oneshot', 'CHARGE_GAME', "a charged special's numbers in the game's own table"),
    ('oneshot', 'COUNTER_GAME', "a counter's numbers in the game's own table"),
    ('oneshot', 'BEAM_COLOUR', 'the colour of a shot drawn as a beam of light'),
    ('oneshot', 'STOMP_GAME', "which of the game's versions of an up special's kick is written"),
    ('own', 'CLIPS', 'the clips of states of its own, on donor actions the port does not otherwise use'),
    ('own', 'CHAIN_NEEDS_HIT', 'a chained side special that goes on only once its first swing has hit'),
    ('own', 'BUILD', 'the code of states of its own (a function in own.py, or its module own_<fighter>.py)'),
)


def written_on_the_donor(fighter):
    """Which of the donor-skeleton route's tables name a fighter: [(module, name, what it holds)]."""
    out = []
    for module, name, what in ON_THE_DONOR:
        table = getattr(importlib.import_module(f'{__package__}.{module}'), name)
        if fighter in table:
            out.append((module, name, what))
    return out


def get(fighter, value, default=None):
    """One value of one fighter, or `default` when nobody gave it."""
    return FIGHTERS.get(fighter, {}).get(value, default)


def column(value):
    """{fighter: its value} for every fighter that has one: the shape the stages' own tables had before they were
    gathered here (`oneshot.TAUNT`, `own_route.SHOTS` ...), which they still read by those names."""
    return {name: row[value] for name, row in FIGHTERS.items() if value in row}


# ---------------------------------------------------------------------------------------------- the specials' module
def specials_name(fighter):
    """The name of the module a fighter's own special states are written in, whether or not it is there."""
    return f'own_{fighter}'


def specials_start(fighter):
    """What to tell a porter whose fighter has no module yet: where one is started from. (The template, when the
    package has one: it is the smallest module the route takes; else the two fighters done.)"""
    from pathlib import Path
    here = Path(__file__).parent
    name = specials_name(fighter)
    if (here / 'own_template.py').is_file():
        return (f'copy fighter_port/own_template.py to fighter_port/{name}.py and put the fighter\'s clip names in it'
                + (' (SPECIALS.md beside it is the guide)' if (here / 'SPECIALS.md').is_file() else '')
                + ': it is found by its name, nothing is registered')
    return (f'write fighter_port/{name}.py (it gives build(ctx) and may give '
            f"{', '.join(MODULE_NAMES[1:])}): it is found by its name, nothing is registered")


def specials(fighter):
    """The module of a fighter's own special states (`fighter_port/own_<fighter>.py`), or None when there is none.
    A module counts only if it has a `build(ctx)`, the one thing the route hands such a module: the route's own
    modules of the same spelling (own_data, own_bank ...) have a `build` of other things and are not fighters."""
    import inspect
    name = f'{__package__}.{specials_name(fighter)}'
    try:
        if importlib.util.find_spec(name) is None:
            return None
    except (ImportError, ValueError):
        return None
    module = importlib.import_module(name)
    build = getattr(module, 'build', None)
    return module if callable(build) and list(inspect.signature(build).parameters) == ['ctx'] else None


# ------------------------------------------------------------------------------------------------------ the bindings
# The engine's places that carry the same bone name on every fighter of the source game (Ultimate). A place whose
# bone a fighter does not have stays empty. `{s}` is L or R.
_ROOT_NAMES = dict(top='__engine_Top', trans='Trans', xRot='__engine_XRot', yRot='__engine_YRot', hip='Hip',
                   waist='Waist', extra='__engine_ExtraMotion')
_BODY_NAMES = dict(bust='Bust', neckN='Neck', headN='Head', throw='Throw')
_SIDE_NAMES = dict(Leg='Leg{s}', Knee='Knee{s}', Foot='Foot{s}', Clavicle='Clavicle{s}', Shoulder='Shoulder{s}',
                   Arm='Arm{s}', Hand='Hand{s}', Have='Have{s}')
_FINGERS = ('Index', 'Middle', 'Ring', 'Pinky')
THUMB_APART = 20.0      # degrees a digit must stand off every other to be called the thumb (below it: a mitten)


def digits(order, parent, world, hand):
    """{digit number: where the digit's root is from the wrist, a unit direction in the hand's own space} for one
    hand of a rig at rest. A digit's joints are `Finger<side><digit><joint>` (FingerL11, FingerL12 ...); joint 0 is
    a palm bone some fighters hang the digits from (Wolf: FingerL10 to FingerL40; Charizard: one for all three),
    not a digit, so a digit's root is its joint 1 wherever it hangs. `world`: {joint: 4x4}."""
    import numpy as np
    side = hand[-1]
    inverse = np.linalg.inv(np.asarray(world[hand], float))
    out = {}
    for j in order:
        if not (j.startswith('Finger' + side) and len(j) == len('FingerL11') and j[-2:].isdigit() and j[-1] == '1'):
            continue
        up = j
        while up is not None and up != hand:            # (a digit of this hand: the hand is above it)
            up = parent.get(up)
        if up != hand:
            continue
        v = (inverse @ np.asarray(world[j], float))[:3, 3]
        length = float(np.linalg.norm(v))
        if length > 1e-6:
            out[int(j[-2])] = v / length
    return out


def thumb(directions):
    """Which digit is the thumb, MEASURED, never taken from its number: the digit whose root stands furthest off
    its nearest neighbour's, seen from the wrist (fingers sit side by side along the palm's edge and a thumb sits
    off to one side). The Pokemon Trainer campaign's measure (its `digits.py`): Charizard's thumb is digit 5 (34
    degrees off, the others 30), Squirtle's is digit 1 (49 against 40), and here Wolf's is 5 (50 against 13), as
    Cloud's and Byleth's are. (How the digits POINT says the same on a hand of five, 33 degrees against half a
    degree on Wolf, and nothing on Squirtle, whose three point the same way: so it is not the measure.)
    -> (digit number or None, how far off in degrees or None). None for a hand of one digit or none, and for a
    mitten (no digit stands `THUMB_APART` off the others)."""
    import numpy as np
    if len(directions) < 2:
        return None, None
    apart = {d: min(float(np.degrees(np.arccos(np.clip(v @ w, -1.0, 1.0)))) for o, w in directions.items() if o != d)
             for d, v in directions.items()}
    best = max(apart, key=lambda d: (apart[d], d))
    return (best, apart[best]) if apart[best] >= THUMB_APART else (None, apart[best])


def bindings_by_name(order, parent, world):
    """The engine's 54 places bound to a rig's joints by the source game's bone names, the thumb measured.
    -> ({slot: joint name or None}, [what was decided and how, in words])"""
    from .compat.bone_lookup import SLOTS
    have = set(order)
    bound = {slot: None for slot in SLOTS}
    notes = []
    for slot, name in dict(_ROOT_NAMES, **_BODY_NAMES).items():
        if name in have:
            bound[slot] = name
    for side, s in (('l', 'L'), ('r', 'R')):
        for part, pattern in _SIDE_NAMES.items():
            name = pattern.format(s=s)
            if name in have:
                bound[side + part] = name
        hand = f'Hand{s}'
        if hand not in have:
            continue
        found = digits(order, parent, world, hand)
        which, apart = thumb(found)
        if len(found) == 1:
            # nothing to measure against: the number is the only evidence (Ivysaur's one digit is `Finger?51`)
            only = next(iter(found))
            which = only if only == 5 else None
            notes.append(f'{hand}: one digit ({only}); ' + ('bound as the thumb by its number alone (READING)'
                                                          if which else 'bound as the first finger'))
        elif found:
            notes.append(f'{hand}: digits {sorted(found)}; ' + (
                f'digit {which} is the thumb (its root stands {apart:.1f} degrees off its nearest neighbour, seen from '
                'the wrist)' if which
                else f'no thumb (no digit stands {THUMB_APART:g} degrees off the others: the most is {apart:.1f})'))
        if which is not None:
            for k in (1, 2):
                if f'Finger{s}{which}{k}' in have:
                    bound[f'{side}Thumb{k}'] = f'Finger{s}{which}{k}'
        for finger, digit in zip(_FINGERS, sorted(d for d in found if d != which)):
            for k in (1, 2):
                if f'Finger{s}{digit}{k}' in have and f'{side}{finger}{k}' in bound:
                    bound[f'{side}{finger}{k}'] = f'Finger{s}{digit}{k}'
    if bound['lHave'] is None and bound['rHave'] is None and 'Have' in have:
        bound['rHave'] = 'Have'                         # one hold bone, not a pair: Melee holds in the right hand
        notes.append('one hold bone (`Have`): it takes the right hold slot')
    return bound, notes


# The places the route cannot do without: the root chain the engine itself turns (`native_port.ENGINE_WRITTEN`,
# `own_skeleton.ROOT_CHAIN`) and the hip. Any other place may be empty: the fighter data then goes to the nearest
# place above it that is bound (`own_data.joint_map`), which is right for a body without that part (Duck Hunt has
# no fingers) and worth a look for one that has it under another name (`unbound_worth_a_look`).
NEEDED = ('top', 'trans', 'xRot', 'yRot', 'hip')
WORTH_A_LOOK = ('bust', 'headN', 'lHand', 'rHand', 'lFoot', 'rFoot', 'lKnee', 'rKnee', 'lArm', 'rArm')


def unbound_worth_a_look(bound):
    """The places a fighter's bindings leave empty that most bodies have (head, hands, feet): a fighter whose bones
    go by other names is bound here by hand (`bindings` in its entry)."""
    return [slot for slot in WORTH_A_LOOK if not bound.get(slot)]


def item_hold(fighter, bound, joints):
    """The joint an item is held at, by name, and who said so: (name or None, 'fighters.py' | 'the right hold slot'
    | 'the left hold slot' | a reported hand fallback | None). Explicit choices never fall back on error."""
    told = get(fighter, 'item_hold')
    if told:
        return (told if told in joints else None), 'fighters.py'
    for slot, who in (('rHave', 'the right hold slot'), ('lHave', 'the left hold slot')):
        if bound.get(slot):
            return bound[slot], who
    # Engines without dedicated item-hold bones still have semantic hand bindings. This is a
    # Melee item-placement adaptation, reported explicitly, not a claim about a source-held prop.
    for slot, who in (('rHand', 'right-hand fallback (no hold bone)'), ('lHand', 'left-hand fallback (no hold bone)')):
        name = bound.get(slot)
        if name and name in joints:
            return name, who
    return None, None


def bindings(fighter, order, parent, world):
    """The bindings a port of `fighter` uses, and where each came from. -> (bound, source, notes)
    source: 'measured before' (`native_port.BINDINGS`), 'by bone name', or either with ', overruled in
    fighters.py' when `FIGHTERS[fighter]['bindings']` names slots."""
    from . import native_port
    if fighter in native_port.BINDINGS:
        bound, source, notes = dict(native_port.BINDINGS[fighter]), 'measured before (native_port.BINDINGS)', []
    else:
        bound, notes = bindings_by_name(order, parent, world)
        source = 'by bone name'
    given = get(fighter, 'bindings') or {}
    unknown = sorted(set(given) - set(bound))
    if unknown:
        raise ValueError(f"fighters.py: {fighter}'s bindings name places the engine does not have: {unknown}")
    if given:
        bound.update(given)
        source += ', overruled in fighters.py for ' + ', '.join(sorted(given))
    return bound, source, notes


# ---------------------------------------------------------------------------------------------------------- the donor
# The donor is the Melee fighter whose states, tables and files the port is built on. It is not chosen per fighter
# yet: one donor has been measured. Each of these needs a row measured on a second donor's own files before that
# donor can be named on the command line.
DONOR_TABLES = ('own_data.DONOR (its joint lookup, joint tree, weapon joints, attribute-block joints, rest height)',
                'own_skeleton.DONOR (its file and root names)', 'port.DONOR_PREFIX (its costume file prefix)',
                "the driver's *_DONOR tables in oneshot.py (its special states' numbers: SHOT, ARMOUR, CHARGE, "
                'COUNTER, TETHER, RISE, FRICTION_ONLY, PLAYS_WHOLE, EYES; and special_rows, which is written for '
                "Marth's specials)", 'voice.DONOR (its sound bank)')


def donors():
    """The donors the own-skeleton route can build on: the ones every per-donor table has a row for."""
    from . import own_data, own_skeleton
    return sorted(set(own_data.DONOR) & set(own_skeleton.DONOR))


def donor_problem(donor):
    """Why a port cannot be built on this donor, with what a second donor would take, or None when it can.
    (Asked first by `preflight` and by the stages that read a donor's row, so that the answer is this and not a
    KeyError a minute in.)"""
    known = donors()
    if donor in known:
        return None
    return (f"the donor is {donor!r}, and the route knows {' and '.join(known) or 'none'}: there is no choice of donor "
            'yet. A second donor is work, not a flag: each of these needs a row measured on its own files: '
            + '; '.join(DONOR_TABLES) + f". Until then give --donor {known[0] if known else '?'}, and say with the "
            'port which Melee fighter would have been closest and what its states would have saved.')
