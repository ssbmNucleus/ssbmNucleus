# Writing a fighter's specials

The worked examples below are fighters' own modules (`own_wolf.py`, `own_duckhunt.py`, `own_gekkouga.py`,
`own_shulk.py`, `own_zetterburn.py` and the rest). They left the tree with the other character-specific code and
are kept under the git tag `archive/fighterport-character-specific-2026-11`: read one with
`git show archive/fighterport-character-specific-2026-11:tools/fighterport/fighter_port/own_wolf.py`.
The helpers they share (`fill`, `number`, `hitbox`, `item_code`, `helpless_landing` ...) are in `own_kit.py`.


## Current implementation priority: playable adaptations

Build a good version of the fighter in Melee: complete special mechanics, useful
movement/recovery, real opponent interactions, readable presentation, and a
repeatable normal recipe. Source timing and data inform implementation; exact
frame parity, camera matching and small animation differences are later polish.
Detailed fidelity checklists remain useful backlog, not a prerequisite to make
functional progress. Developer source/native harnesses are optional calibration
tools; users do not need to run a harness to import or build a port.

`own_rivals_motion.physics` carries source-window gravity/drift and velocity
events into custom specials. Set/add/multiply are entry impulses; constants own
their axes during their windows. Positive vertical velocity transitions to air
before applying horizontal speed (native SetAirborne clears ground velocity).
The generic template now uses this movement too, with native collision/ledges.
`own_rivals_states` allocates reachable source branch clips and their hit scripts,
then executes explicit release/press, grounded/aerial and terminal transitions.
Loops require a supported exit; hidden prerequisites remain reported gaps.
The recognized forward-stick angle modifier uses native stick steering.
Custom modules keep their own collision and branch handlers.
Unhandled compiled velocity modifiers fail explicitly so the module can supply
and report a practical adaptation. `own_windows.cancel_intervals` preserves
source input intervals and rejects hidden prerequisites instead of removing them.

Ranno uses these helpers for rise, optional attack-held spin, down-B dive, dive
landing hits, ledge catching and recovery. Launch steering uses the source angle
limit with native forward-stick input; the source modifier offset is deferred.
Neutral charge persists through native shield/jump/air-dodge cancels and resets
on stock loss. Side/down now provide tongue pull and a steerable bubble with opponent capture,
poison consumption, bounded holds, escape and interruption. The spin dart fan,
wall sling and bubble-assisted self launch remain later work.


For whoever writes the specials of a fighter on its own skeleton (`--own`). Everything else in a port is
mechanical; the specials are the one part that needs judgment: read what each move does in the source game,
decide how Melee does it, and write that as C in a Python module. This page is how. It is short on purpose:
read it once, then copy `own_template.py` and work one special at a time.

Words used below. A **state** is a row of the fighter's state table: an action to play and four calls. An
**action** is a clip and its script. The **donor** is the Melee fighter whose data the port starts from (Marth).
The **engine** is Melee's own code; its source is the Melee decompilation (where it is on this machine:
PORT_CHECKLIST.md, the end of section 6). A pointer `file:name` names a function or a value in `fighter_port/`
(C functions are inside the modules' C texts), or a file of the decompilation.

## 1. The module

A fighter's specials are `fighter_port/own_<fighter>.py`, by the game's own name for the fighter (Greninja is
`gekkouga`: `own_gekkouga.py`). It is found by its name (`fighters.py:specials`); nothing is registered. Without
one, the route builds `own_template.py`. Slap City and Rivals 2 add the shared
source execution described below; other readers get clip/hitbox placeholders.
The report distinguishes those implementations and lists unsupported mechanics. The module is built only when the code file can be: MexTK (`--mextk` or `MEXTK_DIR`), the game's
executable, and the donor's state table.

Start from `own_template.py`. It is the smallest module the route takes: four specials and their air forms, each
entering a state of its own, playing its clip, striking with its script's hitboxes and ending properly. It goes
through the same build as `own_wolf.py` and `own_duckhunt.py`. The places where a kind below goes are marked `KIND`.

### Shared source execution

Both source readers preserve shield-damage multipliers on fighter attacks and
projectiles. The common combat/item writers convert these to Melee's signed
shield-damage offset, including reductions, rounded and bounded to -128..127.
Body damage stays separate. Native Melee shield depletion, lightshield,
staling, stun and pushback remain authoritative; this is an adaptation of the
source pressure, not reproduction of the source shield engine. Native opposing
shield input confirmed reduced Jenny jab pressure and increased Loxodont down-tilt
pressure in ordinary packages.
Adapters that rewrite active hitboxes can use `own_hit_properties.SHIELD` for
the same signed conversion. BCM reapplies source shield offsets with its resource
damage multiplier, selects paid properties, and gives its paid counter the correct
shield modifier after the neutral base update. Repeated updates never compound
the modifier; changing moves restores the ordinary properties.

The shared Slap compiler preserves ordered assignments, atomic choices, finite
delays, persistent source locals and supported `PreMoveUpd` callbacks. It reads
current native controller input, converts source movement units, supports jump
height launches and uses native stage/ledge collision. Scalar input reads include
held buttons, both sticks and analog shield. Supported all-hitbox callbacks consume
native body/shield contacts and can enable source-guarded input cancels. Contact work
waits through hitlag and is discarded on interruption; it cannot revive an old move.
Unrestricted standard-input windows use ordinary native IASA; restricted windows
carry directional specials, jabs/tilts/smashes, jump, shield, dodge and grab permissions.
Aerial attacks use native selection when all aerial directions are enabled.
Source dash attacks, neutral strong attacks and individually restricted aerial
directions remain explicit limits. Input windows expire on source time.
Invincible/item contacts and selected-hitbox callbacks remain adapter work.
Unsupported predicates leave their entire branch disabled, including nested jobs,
contact registrations and article spawns.

`own_slap_states` allocates reachable hard move transitions using the exported
source move identity. Ground/air states retain that identity even when they share
one animation. The ordinary route installs each follow-up's clip and hit script.
Hard transitions preserve velocity and jump resources, stop the canceled ordered
action, clear its timers/contact/input callbacks, and execute the new entry work.
Native idle/fall/landing destinations are supported; immediate transition chains
are bounded so malformed source loops cannot hang the game.

Source input-action triggers use their live button/stick predicate, duration and
newest-first priority. Repeated registration of one source trigger site refreshes
one bounded callback. Source input-assist histories use current native input;
historical event blocking and soft cancels that retain animation/configuration
still need adapters. Jump-used and jumps-left assignments update Melee's actual
jump resource. A due source action runs before animation-end fallback can discard
it. These are shared reader/runtime behaviors, not Jenny-specific callbacks.

`own_slap_projectiles` supplies source models and launch expressions for
`SmashProjectile` and the returning-projectile family. Native item contacts
handle opponents, shields and reflection; per-instance state handles travel,
gravity, lifetime and cleanup. Slap prefab models use their source world axes,
independently of Ultimate's fighter-local article conversion. The Slap reader also
converts world-space fighter-hitbox offsets through each animated bone's inverse
transform; position updates preserve the hitbox run instead of striking repeatedly.

The common Rivals planner runs before clip conversion and again during native
generation. It reserves only reachable supported follow-up clips, installs
their source hit scripts, and fails if an allocated action is missing. Source
window loops with an understood exit stay active until that condition occurs.
Native collision can enter an actual landing attack rather than discarding it
for generic landing lag. Character-specific predicates, compiled spawn timing
and custom article behavior remain explicit adapter work.

The Rivals reader now retains each article's window graph, named hitboxes,
velocity operations and complete source declarations. It also exports explicit
skeletal article meshes from the default renderer, with its neutral material
bake. Unsupported renderer transforms or missing meshes remain named limits.
`own_rivals_articles` executes supported phase graphs, gravity, velocity,
hit windows and continuous hit memory; loops have a bounded cleanup lifetime.
Native contact, shield, clank and reflection handle opponent interactions.
`own_rivals_spawns` schedules declared window creations in the common template.
Unknown compiled classes/triggers require an explicit policy. Source statuses
require a contact adapter; they are never silently treated as ordinary damage.
Zetterburn's fireball uses this shared runtime with its existing Burn observer.

`own_rivals_grabs` connects explicit `OnGrab` paths to native capture when the
source declares a finite `ThrowData` release. The state planner reserves the
capture/recovery clips; each ground/air clip normalizes its own grab geometry.
Capture paths split at their declared throw release so the hold and the remaining
motion use separate native animation buffers. Ordinary finite phase transitions
remain executable; only cycles without a supported exit fall back to finite recovery.
Only native collision establishes ownership. The shared grab helpers attach the
opponent, apply source throw damage/converted knockback once, and safely drop a
capture on interruption. Input cancels and owner movement/landing are suspended
during the bounded hold. Melee's captured pose and the first source grab bone
replace source thrown animation/release offsets; these choices are reported.
Unknown guards, conditional pre-release capture paths and article swallowing
remain adapter work.

These paths run during the ordinary build. The optional developer match checks
do not become a user dependency. Jenny Fox's common path has native acceptance
for axe contact, returning hits, launch, live recovery input, front/rear down-special
contact, hit-only up-special/up-tilt/jump cancels and return to ordinary movement.
Matching whiffs reject the follow-up input. Fox shield, powershield and reflector
checks exercise actual opposing input. Loxodont validates the common Rivals path:
steered recovery, a damaging landing branch, aerial entry, early charge release
and side-special movement. Its neutral now uses a named boulder adaptation:
one source-model projectile at the active release window, with source launch
and gravity, removed on its first hit or stage contact. Ground/aerial side-special
now captures through native collision, holds and releases 12% damage, then returns
control; a miss recovers without capturing. Magma, boulder batting and charge
scaling remain unfinished mechanics; this adaptation
does not certify those moves. The package notes preserve these limits.

Rivals sound extraction writes a receipt and annotates references absent from both
successfully read source sound tables. Those absent entries are reported explicitly.
A missing table, bank, sample or failed decode remains an export failure; it is
never relabeled source silence to make verification pass.

### What the route reads from a module

| Name | Needed | What it is for |
|---|---|---|
| `build(ctx)` | yes | Makes everything below. Exactly one parameter, named `ctx`, or the module is passed over (`fighters.py:specials`). Returns `(dict, None)`, or `(None, why)` and the specials do nothing. Called by `own.py:build` from `own_route.py:run`. |
| `CLIPS` | no | `{clip: donor action}`: the clips of his own states, each on a donor action left free (`own.py:OWN_CLIPS`). A clip is named without its three-character start (`d00specialn.nuanmb` is `specialn`). The route stores each a frame longer than its keys (a state of his own is entered with a step). |
| `HIT_ACTIONS` | no | The actions of his own states in which he himself strikes (`own.py:SPECIAL_HITS`). The route writes their hitboxes from the game's script for the clip on each, as for an attack. Leave out an action whose hits are a thing's he makes. |
| `CODE_SOUNDS` | no | Sounds only his code plays (an item's, a state's own), in the order they matter when the bank is short of room (`own.py:code_sounds`). Each gets a place code can call: `ctx['sound_ids']`. |
| `NAMES` | no | The names of the values of his `vl.prc` that `build` reads (the file holds only hashes): table names (`param_special_n`) and value names (`own.py:names`). They come back read in `ctx['vl']`. Find them with `python -m fighter_port.prc_names <fighter> <words>`: it tries words against the file's hashes and prints a `NAMES` line (start from the words of the move's nickname and its articles: Greninja's shuriken, water, warp, vanish). |
| `CODE_EFFECTS` | no | `{action: [effect names]}` his CODE plays (made by his code, not his script): the route leaves those calls out of the action's script so they are not made twice (`own.py:code_effects`, `own_wolf.py:CODE_EFFECTS`). |

Name in `CLIPS` every clip a state of his plays, the ones the driver already put on an action included
(`specialnstart` on SpecialNStart): an action not named has its script emptied, and its sounds go silent (verify
7.1 names them).

Nothing else of the module is read by the route. `fill`, `number`, `hitbox`, `flag_frame`, `fx`, `item_code` and
`ITEM_LOST` (in `own_duckhunt.py`) and `helpless_landing`, `real_frames` and `clip_length` (in `own_wolf.py`) are
helpers to import.

### What `build(ctx)` returns

| Key | Needed | What it is |
|---|---|---|
| `source` | yes | The C, as a list of lines. It goes into the code file after `#include "../mex.h"`. |
| `rows` | yes | His states, in order: `{name, action, flags, move, anim, iasa, phys, coll}`. `action` is a number (`ctx['action'][donor action]`); `flags` and `move` are copied from the donor's row for the same input (`ctx['row']`). A call is a C name of `source`, 0, or a donor function's address (`states.py:table_text`). The first row is state `ctx['first']`. |
| `frame` | yes | Lines run every frame from `OnFrame` (`fd` and `gobj` are there): `['OwnFrame(fd, gobj);']`. |
| `provides` | yes | What it gives, in words, for the report. Say what is a stand-in and what is not built. |
| `donor_iasa` | no | `{donor motion: C wrapper name}` replaces that existing state's IASA in both routes. Build the wrapper with `states.iasa_wrapper`: run the port's current-input check, then the original IASA only if the state stayed the same. |
| `load` | no | Lines run as he is made, after the donor's own load: `['OwnLoad(fd);']`. |
| `entries` | no | The states his specials start in: the stick held the other way on their first four frames turns them round. |
| `items` | no | The things his specials make (section 2, "A thing a special makes"). |
| `numbers` | no | `{special: [{what, value, from}]}`: every number and where it came from (report.json `special_numbers`). |
| `flash` | no | `[(action, frame, frames to get there, colour from, colour to)]`: the colours his scripts lay on his body. The route plays a script's flashes only for the actions its own table writes, which his states' are not: hand them over with `oneshot.py:flash_keys`. |

(`effects_left_out`, in Duck Hunt's, is read by nothing.)

`ctx`, as `own_route.py:run` makes it:

| Key | What it is |
|---|---|
| `first` | His first state's number (373 on Marth: the donor's 32 special states come first). |
| `action` | `{donor action name: action number}`. |
| `total` | `{donor action name: frames of the clip installed on it}`. No entry: no clip there. |
| `state`, `row` | `{donor action: the donor's state for it}`, `{donor action: that state's row}` (`flags`, `move`). |
| `moves` | The game's scripts, `{'game_<clip>': entry}`. An entry has `hitboxes`, `flags` (`on_flag`/`off_flag` and the frame), `articles` and `article_frames`, `cancel_frame_real` (the frame he may act from), `time_keys`, `motion_rates`, `intangible`, `effects`, `sounds`, `flashes`, `animation`. `oneshot.py:script_for` finds a clip's. |
| `vl` | His `vl.prc`, read with `NAMES`: `{table: [rows]}`. Read a value with `own_duckhunt.py:number`. |
| `drawn` | His drawn scale. A size the game gives (a hitbox, a model, a distance) is times this; a speed is not. |
| `gravity` | His gravity. |
| `sound_ids` | `{sound name: id}` for `CODE_SOUNDS`. The place C uses is `int(id) % 10000`. |
| `effects` | The run's effects of his own (`own_duckhunt.py:fx` reads it). |
| `articles` | The scripts of his weapons and projectiles (`articles.load`): `{'articles': [{'scripts': {...}}]}`. |
| `joints` | `{name: joint index}` of his rig: `throw` (where a made thing is held), `__engine_xrot` (the joint that pitches the whole body). |
| `root`, `work` | The source game's files, and the work folder (`<work>/game.json`, `<work>/spec`). |
| `functions`, `world`, `flags`, `move` | The donor's functions; the drawn scale again; the donor's up special's flags and move numbers. |

There is no `fighter` key: a module that needs its fighter's name writes it in.

## 2. The life of a special in the engine

**A state and its four calls.** Each frame the engine moves the state's clip and script on one frame, then calls
the state's **animation** call (what the move does on this frame, and whether it is over), its **interrupt** call
(`iasa`: what a button may start), its **physics** call (his speed), and its **collision** call (what the stage does
to him). What none of them does is not done. Example: `own_wolf.py:N_Anim`, `own_wolf.py:N_Phys`,
`own_wolf.py:N_Coll`; the rows in `own_wolf.py:build`:

```python
def state(name, motion, like, **calls):
    return dict({'name': name, 'action': action[motion], 'flags': like['flags'], 'move': like['move']}, **calls)

rows = [
    state('Blaster', 'SpecialS3Hi', N, anim='N_Anim', phys='N_Phys', coll='N_Coll'),
    state('Blaster in the air', 'SpecialAirS3Hi', NA, anim='N_Anim', phys='N_Phys', coll='N_Coll'),
```

**Natural completion and input interrupts are separate.** `own_timing.move_timing` reads the source's
`end` and `cancel_frame_real` independently. The first ends an untouched move; the second enables ordinary
input checks in IASA. Missing natural completion falls back to the clip ending. Never force Wait/Fall at
the first interrupt frame. Zetterburn's side special was observed ending naturally at update 47, with
an attack accepted at 36 and rejected at 35; the template and his module now preserve those separate rules.
For helpless recovery moves, do not grant ordinary aerial cancels unless the source allows them.
MexTK declares `Fighter_IASACheck_AllGrounded` as returning an int, but its linked `ftCo_Wait_IASA` is void:
ignore that return value. When a fallback transition is needed, compare the fighter's state before and after.

**Current inputs belong in IASA.** Melee refreshes `fd->input` after the animation callback and before
the interrupt callback. Read button presses/releases, jump requests and current stick choices in a row's
`iasa` callback when they must take effect on that update. `Anim` can count time and perform scheduled
transitions; reading `input.down` or a release there uses the preceding update. Fishbunjin's charge release
and run follow-ups both exhibited this one-update delay; `own_fishbunjin.py:Lw_IASA` and `SRun_IASA` show
the corrected split. If the source intentionally calculates movement before a facing change, save that
old facing separately instead of delaying the whole input path. This is an engine-order rule, not a new
per-port harness requirement. Rivals 2 independently confirmed the same delay: holding Zetterburn's
neutral special for updates 1..10 and releasing on 11 enters Uncharged Active on source update 11;
the old port waited until 12. `own_zetterburn.py:N_IASA` applies this rule to both ground and air charge.

**How a special is entered.** The engine calls `SpecialN`, `SpecialAirN`, `SpecialS`, `SpecialAirS`, `SpecialHi`,
`SpecialAirHi`, `SpecialLw` and `SpecialAirLw` (the kit links a function to the engine by its name: MexTK's
`ftFunction.txt` lists them). Each puts him in a state of his own. Enter a state with the step, so its script
runs on its first frame (`own_wolf.py:Enter`):

```c
static void Enter(GOBJ *gobj, int state)
{
    FighterData *fd = gobj->userdata;
    ActionStateChange(0, 1, 0, gobj, state, 0, 0);
    Fighter_AdvanceScript(gobj);
    w_age[fd->ply] = 1;
}
```

The frame a state is entered on already runs its physics and collision calls: it is the state's first frame.
Count from 1 there.

**Ground and air forms, and the hand-over.** A move that can be on the ground and in the air has a state for each.
When he walks off an edge or comes down, the collision call hands over to the other form on the frame the clip is
at; `0x5000` keeps the body's colour and goes on with the script from that frame (`own_wolf.py:Hand_Over`,
`own_wolf.py:N_Coll`):

```c
void N_Coll(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    if (fd->phys.air_state == 0)
    {
        if (Fighter_CollGround_PassLedge(gobj) == 0)
        {
            Fighter_SetAirborne(fd);
            Hand_Over(gobj, ST_N_AIR);
        }
    }
    else if (Fighter_CollAir_IgnoreLedge_NoCB(gobj) != 0)
    {
        Fighter_SetGrounded2(fd);
        Hand_Over(gobj, ST_N);
    }
}
```

**What the collision call decides.** One call each frame, chosen for what the stage may do to him:

| Call | On | What it does |
|---|---|---|
| `Fighter_CollGround_PassLedge(gobj)` | ground | Walks off an edge: returns 0 when he has left the ground (`own_wolf.py:N_Coll`). |
| `Fighter_CollGround_StopLedge_EnterFall(gobj)` | ground | Stops at an edge; falls if the floor goes (`own_wolf.py:HiLanding_Coll`). |
| `Fighter_CollAir_IgnoreLedge_NoCB(gobj)` | air | Passes ledges: returns non-zero when he lands (`own_wolf.py:N_Coll`). |
| `Fighter_CollAir_IgnoreLedge(gobj, cb)` | air | Passes ledges; calls `cb` when he lands (`own_wolf.py:Dash_Coll`). |
| `Fighter_CollAir_GrabFacingLedgeWalljump(gobj, 0, cb)` | air | Catches a ledge he faces (a recovery); `cb` on landing (`own_wolf.py:SEnd_Coll`). |

**How it ends.** Standing (`Fighter_EnterWait`), an ordinary fall (`Fighter_EnterFall`), or the helpless fall
with the frames of landing it ends in (`own_wolf.py:Leave`):

```c
static void Leave(GOBJ *gobj, float landing)
{
    FighterData *fd = gobj->userdata;
    if (fd->phys.air_state == 0)
        Fighter_EnterWait(gobj);
    else if (w_helpless[fd->ply])
        Fighter_EnterSpecialFall(gobj, 1, 0, 1, 1.0f, landing);
    else
        Fighter_EnterFall(gobj);
}
```

A move that comes down onto a floor ends in its landing: `Fighter_EnterSpecialLanding(gobj, 0, frames)`
(`own_wolf.py:S_Landed`). The frames of landing after a helpless fall: the special's own table if it names them
(`fire_landing_frame`), else the game's list of motions (`own_wolf.py:helpless_landing`). The engine's helpless
fall still lets him jump if he had a jump left: take it away until he stands (`own_wolf.py:Helpless_Frame`,
under "A recovery that rises"). `Fighter_EnterSpecialFall`'s second argument says whether those frames of landing
are kept however he lands: with 0 (as above) the engine plays them only when he falls faster than a set speed
(`ftCo_FallSpecial.c:ftCo_80096D28`), and a slow landing has none. A move that leaves him helpless near the floor,
or that hangs before the fall, passes 1 (`own_ittledew.py:Hi_Anim`: Ittle Dew's hop landed with no lag on 0).

**Its script and its hitboxes.** The route empties every donor special's script, then for each action in `CLIPS`
writes the game's script for the clip on it: its sounds and effects always, its hitboxes when the action is in
`HIT_ACTIONS`. The script's flags are not written. Where the game's code acts on a flag (a thing let go, a way
out opened), read the flag's frame in Python (`own_duckhunt.py:flag_frame`, `article_frames`) and act on that
frame in C. The script's body colours come back to the route through `flash`.

**A sound from code.** Name it in `CODE_SOUNDS`; `build` takes its place, `int(ctx['sound_ids'][name]) % 10000`,
and C plays `5000 + place`. From his own code, a sound the engine ends when his state changes
(`own_duckhunt.py:Fall_Frame`):

```c
#define PLAY_STATE_SOUND ((void (*)(FighterData *, int, int, int))0x80088510)   // ft_80088510: a sound the engine ends as his state changes
```

```c
if (falls && !fall_was[p] && SOUND_FALL)
    PLAY_STATE_SOUND(fd, 5000 + SOUND_FALL, 127, 64);
```

From an item: `Item_PlayOnDestroySFXAgain(id, 5000 + place, 127, 64)` (`own_wolf.py:Laser_Anim`). A sound an item
must end (a whistle in flight) is played and ended with the item's own pair, `PLAY_KEPT` and `END_KEPT`
(`own_duckhunt.py:Can_Anim`). A sound his code plays that must NOT end with his state (a status on another fighter
starting or ending while he attacks): `Fighter_PlaySFX(fd, 5000 + place, 127, 64)` (ft_PlaySFX; m-ex turns the
5000s into his bank in ft_80087D0C, which every fighter sound call goes through: `own_zetterburn.py:Burn_Sound`).

**An effect from code.** An effect of his own is a list of generators (`own_duckhunt.py:fx` makes it from the
effect's name), played at a point with the engine's `SPAWN_EFFECT` (`own_duckhunt.py:Fx_At`):

```c
static void Fx_At(GOBJ *gobj, const OwnFx *fx, int count, int age, Vec3 *at)
{
    FighterData *fd = gobj->userdata;
    Vec3 off, none = {0, 0, 0};
    int i;
    off.X = 0;
    off.Y = at->Y - fd->phys.pos.Y;
    off.Z = (at->X - fd->phys.pos.X) * fd->facing_direction;
    for (i = 0; i < count; i++)
        if (fx[i].delay == age)
            SPAWN_EFFECT(gobj, fx[i].gfx, 0, 0, 0, &off, &none, 0.0f);
}
```

**A thing a special makes (an item).** Its data is a spec in `items` (`own_items.py:install`): `name`, `model`
(`{'folder', 'meshes', 'lit'}` for the game's own model, or `{'cutout': fn}` for a flat picture), `numbers` (floats
its code may read), `states` (for each state, a list of `(frame, hitbox)`: `own_duckhunt.py:hitbox` makes a
hitbox from the game's), and `code` (its C, made with `own_duckhunt.py:item_code`). Its place in the list is its
number. Its code is a file of its own: the item and the fighter cannot call each other.

- Made by the fighter's code (`own_wolf.py:Make_Item`). It does nothing until it is given a state:

```c
static GOBJ *Make_Item(GOBJ *gobj, int which, Vec3 *at)
{
    FighterData *fd = gobj->userdata;
    SpawnItem spawn;
    GOBJ *item;
    spawn.parent_gobj = gobj;
    spawn.parent_gobj2 = gobj;
    spawn.it_kind = MEX_GetFtItemID(gobj, which);
    spawn.pos = *at;
    spawn.pos.Z = 0;
    spawn.pos2 = spawn.pos;
    spawn.vel.X = 0;
    spawn.vel.Y = 0;
    spawn.vel.Z = 0;
    spawn.facing_direction = fd->facing_direction;
    spawn.damage = 0;
    spawn.unk6 = 0;
    spawn.is_raycast_below = 1;
    item = Item_CreateItem1(&spawn);
    if (item)
    {
        ItemStateChange(item, 0, 2);                    // (an item does nothing until it is given a state)
        Item_CopyDevelopState(item, gobj);
    }
    return item;
}
```

- m-ex is told each item's number as the fighter is made (`own_wolf.py:OwnLoad`):

```c
static void OwnLoad(FighterData *fd)
{
    ItemDesc **items = fd->ftData->items;
    int i;
    w_helpless[fd->ply] = 0;
    hi_pitched[fd->ply] = 0;
    for (i = 0; items && i < @item_count@; i++)
        if (items[i])
            MEX_IndexFighterItem(fd->kind, items[i], i);
}
```

- It talks to the fighter through its variables. The fighter writes an ask into `item_var.var1`; the item reads
  it and clears it on its next frame (`own_wolf.py:Shoot`, `own_wolf.py:Laser_Anim`). The other way, the item
  sets a variable and the fighter's frame code answers (`own_duckhunt.py:Gun_Frame`).
- It is removed when its animation call returns 1. It never outlives its use: every item's code starts with
  `Lost()` (`own_duckhunt.py:ITEM_LOST`, put in by `own_duckhunt.py:item_code`):

```c
static int Lost(GOBJ *item)
{
    ItemData *id = item->userdata;
    GOBJ *owner = id->fighter_gobj;
    if (!owner || ((FighterData *)owner->userdata)->state_id < ASID_REBIRTH)
        return 1;
    return id->pos.X < stc_stage->blastzoneLeft || id->pos.X > stc_stage->blastzoneRight
           || id->pos.Y < stc_stage->blastzoneBottom || id->pos.Y > stc_stage->blastzoneTop;
}
```

  and its animation call ends it on that, on its own time running out, and two frames after it was made if it
  was never let go.
- A thing the game shows in one pose at a time (its model holds a mesh for each pose, `<Name>_A`, `<Name>_B` ...,
  that the article's state code shows and hides) carries a picture of every pose it shows in the port, and its code
  shows the right one on the frame the game's code switches to it. Its clips show none of this (the gunman's have
  no animation files): read the switching in the state code. `own_items.py:pose_meshes` lists the poses,
  `own_items.py:cutouts` makes one model of the pictures (a mesh each, in order, each within 256 pixels so none is
  shrunk, blurred and stored at four times the bytes) and `own_items.py:SHOW_POSE` shows
  one by its place (`own_duckhunt.py:Gun_Anim`, its frames in `own_duckhunt.py:GUN_POSES`). A pose that only a
  behaviour the port leaves out would show (a gunman struck) is said to be left out.
- A flat picture taken from the game's particle effect (`own_gekkouga.py:flat_picture`, Wolf's laser) can be a plain
  MASK the game colours with keys the reader does not apply: Greninja's water came out a white square. Look at it in
  the game before keeping it; else a soft blob in the effect's colour (a stand-in, said so).
- A thing that strikes again and again (the full Water Shuriken's five 1% hits) holds its target only if it keeps up
  with the push of its own hit: one that stops where it first struck lands once. Step the round of hits in a test and
  read the target's damage after each (`own_gekkouga.py:NMax_Anim`: it creeps on at about the push's speed).

## 3. Each kind of special

Each is the smallest working example in the two modules. Read the whole function a pointer names before copying.

### A shot fired (Wolf's Blaster)

The fighter makes the shot on the frame the script lets it go, and asks it to fly (`own_wolf.py:Shoot`):

```c
static void Shoot(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    Vec3 at;
    GOBJ *shot;
    at.X = fd->phys.pos.X + MUZZLE_X * fd->facing_direction;
    at.Y = fd->phys.pos.Y + MUZZLE_Y;
    at.Z = 0;
    shot = Make_Item(gobj, LASER, &at);
    if (shot)
        ((ItemData *)shot->userdata)->item_var.var1 = 1;        // its own code sends it on its way
}
```

The shot's own code: given its speed and life on the ask, flies in a state of its own until its life is out or it
meets a wall (`own_wolf.py:Laser_Anim`):

```c
int Laser_Anim(GOBJ *item)
{
    ItemData *id = item->userdata;
    JOBJ *model = item->hsd_object;
    int ask = id->item_var.var1;
    id->item_var.var1 = 0;
    if (Lost(item))
        return 1;
    if (id->state == 0)
    {
        if (ask)
        {
            id->self_vel.X = SPEED * id->facing_direction;
            id->self_vel.Y = 0;
            id->item_var.var2 = LIFE;
            Item_SetAirborne(id);
            Item_ResetAllHitPlayers(id);
            ItemStateChange(item, 1, 2);
            if (SOUND_FLY)
                Item_PlayOnDestroySFXAgain(id, 5000 + SOUND_FLY, 127, 64);
            // (its picture is made flying right: turned about when it flies left)
            model->rot.Y = id->facing_direction < 0 ? 3.14159265f : 0;
            JOBJ_SetMtxDirtySub(model);
        }
        else if (++id->item_var.var4 > 2)
            return 1;                                   // never let go: gone
        return 0;
    }
    return --id->item_var.var2 <= 0;
}
void Laser_Phys(GOBJ *item) {}
int Laser_Coll(GOBJ *item)
{
    ItemData *id = item->userdata;
    if (id->state == 0)
        return 0;
    return (Item_CollAir_NoCB(item) & ~1) != 0;         // a wall or a ceiling ends it; it passes along a floor
}

__attribute__((used))
static struct ItemState item_state_table[] = {
    {.state = 0, .animCallback = Laser_Anim, .physCallback = Laser_Phys, .collCallback = Laser_Coll},
    {.state = 1, .animCallback = Laser_Anim, .physCallback = Laser_Phys, .collCallback = Laser_Coll},
};
```

Its spec: a picture, one number, two states (new: no hit; flying: the game's own hits on their frames):

```python
laser_item = {
    'name': 'laser', 'model': {'cutout': lambda out: laser_picture(ctx, out)}, 'numbers': [0.0],
    # new; flying: the game's own stretches of its flight, each from the frame it begins on
    'states': [[(0, None)], [(max(0, h['first'] - 1), hitbox(h, drawn)) for h in fly]],
    'code': item_code(LASER, values)}
```

A shot whose hit depends on something (a level of charge, which gunman fired) has one state per hit and is given
the state on the ask: `ItemStateChange(item, ask, 2)` (`own_duckhunt.py:Bullet_Anim`).

### A thing placed or thrown that lives on (Duck Hunt's can and clay)

Made only if none is out; a second press acts on the one that is out (`own_duckhunt.py:N_Begin`,
`own_duckhunt.py:Own_Item`):

```c
static GOBJ *Own_Item(GOBJ *gobj, int which, int ended)
{
    int kind = MEX_GetFtItemID(gobj, which);
    GOBJ *g;
    for (g = (*stc_gobj_lookup)[MATCHPLINK_ITEM]; g; g = g->next)
    {
        ItemData *id = g->userdata;
        if (id->kind == kind && id->state < ended && (id->fighter_gobj == gobj || id->MEX.fighter_orig == gobj))
            return g;
    }
    return 0;
}
```

```c
static void N_Begin(GOBJ *gobj, int state)
{
    FighterData *fd = gobj->userdata;
    int p = fd->ply;
    Enter(gobj, state);
    n_age[p] = 0;
    n_kicks[p] = 0;
    if (!Own_Item(gobj, CAN, CAN_ENDS))
    {
        Vec3 at;
        Throw_Place(fd, &at);
        if (Make_Item(gobj, CAN, &at))
            n_kicks[p] = 1;
    }
}
```

Until it is let go it rides the throw joint (`ctx['joints']['throw']`; `own_duckhunt.py:N_Phys`). Its own code
then has states of its own (flying, standing, shot, going off), each with its hits in its spec, and ends itself
(`own_duckhunt.py:Can_Anim`, `own_duckhunt.py:Clay_Anim`). A press that asks something of a thing that is out is
an interrupt call (`own_duckhunt.py:N_IASA`, `own_duckhunt.py:S_IASA`).

### A dash that hits (Wolf Flash)

Three states: he gathers himself, the dash, the arrival. The dash leaves the ground, is given its speed once,
and keeps it (an empty physics call: in the air the engine moves him by `self_vel`). He is helpless after it.
The hits are the scripts' (`HIT_ACTIONS`). From `own_wolf.py:Dash_Begin` on:

```c
static void Dash_Begin(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    float sy = fd->input.lstick.Y, tilt = 0, c, s;
    if (fd->phys.air_state == 0)
        Fighter_SetAirborne(fd);
    Enter(gobj, ST_S_DASH);
    // (READING: past min_stick_y the dash is turned by the whole of max_rush_degree)
    if (sy >= S_STICK)
        tilt = S_TILT;
    else if (sy <= -S_STICK)
        tilt = -S_TILT;
    c = cos(tilt);
    s = sin(tilt);
    fd->phys.self_vel.X = (S_DASH_X * c - S_DASH_Y * s) * fd->facing_direction;
    fd->phys.self_vel.Y = S_DASH_X * s + S_DASH_Y * c;
    w_helpless[fd->ply] = 1;
}
```

```c
void Dash_Anim(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    int p = fd->ply;
    w_age[p]++;
    if (w_age[p] > S_DASH_FRAMES)
        End_Begin(gobj);
}
void Dash_Phys(GOBJ *gobj)
{
}
static void S_Landed(GOBJ *gobj)
{
    Fighter_EnterSpecialLanding(gobj, 0, S_LANDING);
}
// (the dash passes ledges; a floor it meets is landed on, a wall stops it)
void Dash_Coll(GOBJ *gobj)
{
    Fighter_CollAir_IgnoreLedge(gobj, S_Landed);
}
```

The speed is the clip's own travel over its frames (`own_wolf.py:clip_length`). Left to ordinary friction a dash
on the ground goes about twice as far as the source's: brake it yourself.

The clip on the disc already plays at the speeds its script sets: the driver timed it by the script's time keys
(the clip's `time_keys` in `<work>/spec/moveset.json`). Turn a frame of the source clip into a frame of the state by
those keys (`oneshot.frame_at(keys, clip frame) + 1`, as `own_gaogaen.py:_played` does), never by the script's
`motion_rates` again, and never set the clip's rate in the engine: a rate is frames of play to one of the clip, so
0.9 plays it faster. (Incineroar's Cross Chop divided by the 0.9: the rise was to end on frame 30 of a 27-frame clip,
and he turned over short of it.)

### A recovery that rises (Duck Jump, Fire Wolf)

He leaves the ground, is given his speed as the rise begins, keeps a physics call of his own, and catches a
ledge he faces (`own_duckhunt.py:Fly_Begin`, `own_duckhunt.py:Fly_Coll`):

```c
static void Fly_Begin(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    int p = fd->ply;
    if (fd->phys.air_state == 0)
        Fighter_SetAirborne(fd);
    Enter(gobj, ST_HI_FLY);
    fd->phys.self_vel.X = FLY_X0 * fd->facing_direction;
    fd->phys.self_vel.Y = FLY_Y0;
    // (the frame it begins on is the flight's first: the engine runs the new state's movement on it already)
    flaps[p] = FLAP_TIMES;
    flap_wait[p] = FLAP_INTERVAL - 1;
    flap_now[p] = 0;
    fly_age[p] = 1;
    hi_spent[p] = 1;
}
```

```c
static void Fly_Landed(GOBJ *gobj)
{
    Fighter_EnterSpecialLanding(gobj, 0, HI_LANDING);
}
// a ledge he faces is caught on the way (the engine's own rule for an up special); a floor is landed on
void Fly_Coll(GOBJ *gobj)
{
    Fighter_CollAir_GrabFacingLedgeWalljump(gobj, 0, Fly_Landed);
}
```

Along the ground a state hands on its ground speed itself, or he stays where he is (`own_wolf.py:Rush_Phys`):

```c
void Rush_Phys(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    if (fd->phys.air_state == 0)
    {
        fd->phys.self_vel_ground.X = HI_SPEED * fd->facing_direction;
        Fighter_PhysGround_ApplyVelocity(gobj);
    }
}
```

A rise that follows its clip, up and back down (Shulk's Air Slash: up 48 by frame 25, then down 28), takes the
clip's root a frame at a time, never a span: `own_gaogaen._span` gives the NET travel between the first and last
moving frames, which for an arc is what is left of the rise (Air Slash rose 3.9 in round 1). `own_shulk.py:per_frame`
turns the root's keys into a speed for each frame of the state (timed by `_played`; two clip frames on one state
frame add up), and `own_shulk.py:Hi_Move` gives it, a mode's height laid only on the rising frames.

Aimed by the stick, and the body pitched to the flight: `own_wolf.py:Rush_Begin`, `own_wolf.py:Pitch`. An attack
or an air dodge that may end the rise: an interrupt call from the frame the script opens the way
(`own_duckhunt.py:Fly_IASA`), with the engine's own attack wrapped so he is helpless after it
(`own_duckhunt.py:HiAttack_Anim`). Until he stands, no jump (`own_wolf.py:Helpless_Frame`):

```c
static void Helpless_Frame(FighterData *fd, GOBJ *gobj)
{
    int p = fd->ply, s = fd->state_id;
    if (hi_pitched[p] && s != ST_HI_RUSH)
        Pitch(fd, 0);
    if (!w_helpless[p])
        return;
    if (fd->phys.air_state == 0)
        w_helpless[p] = 0;
    else if (s >= ST_FIRST_OWN || (s >= ASID_FALLSPECIAL && s <= ASID_FALLSPECIALB))
        fd->jump.jumps_used = fd->attr.max_jumps;
    else
        w_helpless[p] = 0;
}
```

**A move's own gravity.** A source move may set its own gravity (and fall speed) before it asks for a jump height:
Slap City's teleport sets gravity 10 and fall speed 5 on its frame 1, then jumpheight 3 (the reader keeps what a move
sets itself plainly as the move's `sets`). The hop rises under the move's gravity, not the fighter's: turn the height
into a speed with the move's (`own_ittledew.py:build`, HI_RISE = sqrt(2 x HI_GRAV x height), HI_GRAV the move's 10
in Melee's units), and give that gravity in the state's own physics call (`own_ittledew.py:Hi_Phys`). Under her own
gravity of 50 the same height is reached 2.2 times as fast and in under half the time (both go as the root of the
gravity).

### A reflector (Wolf's Reflector)

The engine's reflect bubble, `Fighter_CreateReflect`. Any change of state takes it down, so it is put up again on
every frame it should stand (`own_wolf.py:Bubble_Up`, `own_wolf.py:LwLoop_Anim`):

```c
static const ReflectDesc lw_bubble = {0, LW_LIMIT, {0, LW_HEIGHT, 0}, LW_RADIUS, LW_DAMAGE, LW_SPEED, 0};

static void Lw_Reflected(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    lw_sent[fd->ply] = 1;
}
```

```c
static void Bubble_Up(GOBJ *gobj)
{
    Fighter_CreateReflect(gobj, (ReflectDesc *)&lw_bubble, @lw_cb@);
}
```

(`@lw_cb@` is a blank `build` fills, `values['lw_cb'] = 'Lw_Reflected'`, as every `@name@` in the C texts is
filled: `own_duckhunt.py:fill`.)

Wolf's loop handles reflection in Anim and current-button release in `LwLoop_IASA`, wired to both
ground and air loop rows. Its directional up-special launch is likewise chosen in IASA. Ittle's charge
and aimed bomb throw, and Shulk's up-special follow-up use the same rule. `test_own_input_phase.py`
executes these C callbacks across an explicit Anim -> input refresh -> IASA sequence, checking release,
minimum/full holds, launch/throw aim and follow-up boundaries. Cloud and Ike charge/release, Greninja's
neutral/side release, two jet aims and counter direction now follow the same rule. Cloud's dive request
and Byleth's bow/axe cancels wrap the donor IASA through `donor_iasa`; the original donor callback runs
only if the custom check did not change state. m-ex `OnFrame` is at 0x8006AA28 in `Fighter_8006A360`,
before Anim and input refresh, so its input decisions also require this split. Meter and presentation
updates remain per frame. Byleth's flick lunge intentionally uses the input from move entry.
Fishbunjin and Zetterburn also have in-game calibration evidence; the newer callback cases still need
native integration acceptance.

Its states each have an air form, so its collision call hands over by a switch of pairs and puts the bubble back
up (`own_wolf.py:Lw_Coll`). The engine's absorber is `Fighter_CreateAbsorb` (no example yet).

### A helper that appears and acts (Duck Hunt's Wild Gunman)

The fighter makes the helper on the script's frame (`own_duckhunt.py:Lw_Anim`). The helper runs its own time and
says when it acts by a variable (`own_duckhunt.py:Gun_Anim`):

```c
if (age == 1 && SOUND_APPEAR)
    Item_PlayOnDestroySFXAgain(id, 5000 + SOUND_APPEAR, 127, 64);
// (he asks for the bullet a frame early: the fighter's code makes it on the next frame, and its hit is out the
// frame after that, which is the published one. His flash is made and his shot's sound played FLASH_LEAD frames
// before, as the game's code does; the flash's pieces wait their own frames, so it shows as the bullet leaves)
if (age == FIRE_WAIT - 1)
    id->item_var.var3 = 1;
```

An effect's pieces can wait frames of their own after it is made (the muzzle flash's wait 5 to 7): make it when the
game's code makes it, not when it should show, or it shows that many frames late.

and the fighter's frame code makes what it fires (`own_duckhunt.py:Gun_Frame`):

```c
static void Gun_Frame(FighterData *fd, GOBJ *gobj)
{
    GOBJ *g = Own_Gunman(gobj);
    if (g)
    {
        ItemData *id = g->userdata;
        if (id->item_var.var3 == 1)
        {
            Vec3 at = id->pos;
            GOBJ *shot;
            id->item_var.var3 = 0;
            at.X += (float)id->item_var.var5 * 0.01f * id->facing_direction;
            at.Y += (float)id->item_var.var6 * 0.01f;
            shot = Make_Item(gobj, BULLET, &at);
            if (shot)
            {
                ItemData *sd = shot->userdata;
                sd->facing_direction = id->facing_direction;
                sd->item_var.var1 = id->item_var.var7 + 1;
            }
        }
    }
}
```

### A counter (Greninja's Substitute)

A state of his own catches a hit with the engine's own counter ball, the one Marth's code puts up
(`own_gekkouga.py:Lw_Catch`). MexTK has the ball's description (`ShieldDesc`) but no function that takes it: call
the engine by its address.

```c
#define CATCH ((void (*)(GOBJ *, ShieldDesc *, void *))0x8007B1B8)    // ftColl_8007B1B8: the engine's counter ball (Marth's)
static const ShieldDesc lw_ball = {LW_JOINT, 0, {0, LW_HEIGHT, 0}, LW_RADIUS, 0, 0, 0};
```

```c
static void Lw_Catch(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    CATCH(gobj, (ShieldDesc *)&lw_ball, Lw_Caught);
    fd->flags.shield_always_refract = 1;    // (Marth's code sets this beside it)
}
```

- Put it up on the window's frames from the animation call (`Lw_Anim`), and down after (`fd->flags.shield_enable = 0`).
  A change of state takes it down: put it back up after a hand-over.
- Each physics frame clear `fd->shield_bubble.is_checked` (Marth's `ftColl_8007AEE0`): the ball then follows its joint.
- The callback is called as the hit is taken (`Lw_Caught`): `fd->shield.dmg_source` is who struck (a fighter's or an
  item's GOBJ). Change state there, then clear `fd->cb.EnterHitlag` and `fd->cb.ExitHitlag` as Marth's code does.
- Melee's catch is a BALL round one joint (`lbColl_80007BCC`: the joint's place plus the offset, radius the size). A
  newer game's counter catches a hit anywhere on the body, so its own numbers are not a ball's: Greninja's offset 6.5
  and size 8 on joint 0 held only his legs, and a jab to his chest struck him through it. Ride a middle joint (the hip)
  and size it to hold the whole body (a third bigger there); check with a high hit and a low one.
- A counter that strikes from somewhere else (behind the one who struck) is placed by hand, and then the collision is
  told where he is, as Warp Star and Barrel do (`mpColl_80043680`, MexTK `Coll_CopyPosToECBs`; written out:
  `coll_data.topN_Curr`, `topN_CurrCorrect` and `topN_Prev` set to `phys.pos`, `flags |= 0x20`). Without it the next
  collision sweeps from where he stood to the new place and stops him partway: Greninja's came out 8 short, on the
  near side of the attacker (`own_gekkouga.py:Lw_Strike`).
- The strike each way the stick is held: the game's script holds all of them, the code picks one (next).

**A script that holds alternatives.** A script with more than one hitbox of the same id over the same frames (or with
a hitbox's last frame before its first) holds versions the game's code chooses between (Substitute's five strikes, one
for each way). The driver keeps one, the last, and says so in its notes ("alternatives"); carry the others in the
module and put the chosen one on the live hitboxes on the frame they come out (`own_gekkouga.py:Lw_Ways`).

### A move that vanishes and reappears (Shadow Sneak, Substitute)

`fd->flags.invisible = 1` hides him and `Fighter_SetScriptHurtStatus(gobj, 2)` makes him impossible to hit
(`own_gekkouga.py:Hide`, as the engine does for Sheik's Vanish: decompilation `ftSk_SpecialHi.c:inlineA0`); he is
moved by `self_vel` or by setting `fd->phys.pos` while unseen. Undo both as he reappears, AND in the frame code
whenever he is found in a state that is not his own (`own_gekkouga.py:Own_Frame`, by a per-player flag): a state
left by a hit, a ledge or the blast zone never runs the code that shows him again.

### A mode that changes his numbers (Shulk's Monado Arts)

A special that puts him in a MODE for a time: his speeds, his jump, his falling, the damage and knockback of his hits
and the damage he takes are the mode's until it ends, then it cools down (`own_shulk.py`, NEUTRAL). The pressing is
an ordinary state (the mode's clip); the mode itself lives in variables kept by player and in four places, because no
one state can hold it:

| What it changes | Where | Why there |
|---|---|---|
| walk, dash, run, friction, jump, air speed, fall | `fd->attr` (his copy of his numbers): kept as the mode starts, the mode's laid over them, put back as it ends (`own_shulk.py:Art_On`, `own_shulk.py:Art_Off`) | the engine's own states read `fd->attr` every frame; nothing else needs changing |
| damage he takes | the engine's damage-taken multiplier, a FLOAT at `fd->dmg` + 0x182c (MexTK calls it `int behavior`: write `*(float *)&fd->dmg.behavior`; the decompilation's `dmg.x182c_behavior`, read by `ftColl_800765F0` for every hit he takes) | every change of state puts it back to 1 (`fighter.c`): set it every frame, and again in the call below |
| damage and knockback of his hits | each hitbox of his as it comes out: `Fighter_UpdateHitboxDamage` for the damage, `kb_growth` and `kb` (base) for the knockback (both times the multiplier: knockback is linear in them), worked out from the hitbox's OWN numbers kept when it was first seen, never from what is there now (`own_shulk.py:Arts_Hits`) | a hitbox is made by the script (the animation step) and struck with at the hit step: it must be changed between the two, in every state he can be in |
| his throws | `fd->throw_hitbox[0]` and `[1]` (the decompilation's `fp->xDF4`): the throw command sets them (`ftColl_8007ABD0` for the damage, `kb_growth` at 0x24, `kb` at 0x2C) and the release reads them (`ftCo_800DDDE4`); laid on from their OWN numbers like a hitbox's (`own_shulk.py:Arts_Throw`) | a throw's hit is no hitbox of the script: a mode that changes only `fd->hitbox` leaves every throw at its plain numbers |
| knockback he takes | `fd->dmg.hit_log.force_applied` (0x1850) times the mode's number, in `fd->cb.OnTakeDamage2` (0x21F0, the decompilation's `take_dmg_2_cb`; `own_shulk.py:Arts_Blown`) | the engine works the knockback out, calls that hook, then uses it (`fighter.c`); every change of state clears the hook, so the call below sets it again each frame the mode is on |
| that call | `fd->cb.Accessory_Persist` (0x21b4, the decompilation's `accessory4_cb`, run in `fighter.c:Fighter_8006C80C`): the engine runs it each frame after physics AND collision (`Fighter_procMap`) and before hits are looked at, and keeps it through every change of state; a KO clears it, so the frame code puts it back when it is not his (`own_shulk.py:OwnFrame`). One hook makes every change to his hits (`own_shulk.py:Own_Hits`). Melee's own users are Link's and Samus's hookshot items only | wrapping the state's physics call (Incineroar's Revenge) misses the frame a state is changed in the animation step, and a state entered on LANDING (from the collision call) makes its hits after its physics has run: Back Slash's landing strike struck with both its sides until its side was chosen here |

- The mode's numbers are the game's by NAME in `vl.prc` (`prc_names`): Ultimate's words are `spd` (speed),
  `blow` (knockback dealt: `buster_blow_mul`), `attack_power_mul` (damage dealt), `damage_mul` (damage TAKEN),
  `height_mul` (a jump's height: the jump's speed is times its square root), `air_speed_x` (most speed sideways in
  the air), `air_speed_y` (falling), `ground_brake` (friction), and times `active_time_<mode>` and
  `unavailable_time_<mode>` in SECONDS, and `blown_mul` (knockback TAKEN: Shulk's `shield_blown_mul` 0.6,
  `smash_blown_mul` 1.2). A value the game does not name for a mode is 1, and said. Where the move's words run out,
  try the fighter's own vocabulary (the words of its motion names and of its code's status names), and weigh a find
  by `prc_names.chance`: three words after the mode's name, out of a thousand, find something by chance (Shulk:
  `jump_sqrt_yield_string`), two do not.
- What a hitbox's numbers become must not be laid on twice: a code of his that sets a hitbox's damage itself
  (a counter's strike) is left out of the mode's call, or its knockback grows every frame.
- How it is shown is the game's own effects, from his effect file (`own_shulk.py:ART_SHOW`, `art_shown`): the
  mode's symbol where it starts (at a point, given off once), its sign on the sword, and its aura on the joints the
  mode's own script names (`EFFECT_FOLLOW ... sys_equip_end`: feet, waist, sword, hands). An effect the game keeps
  on while the mode lasts is a steady emitter given a life of `ART_EVERY` frames (`Plan.use(lasting=)`) and given
  again by the code every `ART_EVERY` frames: Melee's code cannot end a held effect it did not make itself. Only the
  sets' flat emitters are used (`Plan.use(only=)`); a 3D shape among them is left to the set's own row. No tint of the
  whole body: that is not what the game shows. What the game recolours by its effects' own colours (the Monado's
  blade, an effect whose colour is in its generator commands) cannot be changed at run time: a glow in the mode's
  colour at that part stands in, named (`glow`, on `haver`).
- End the mode at a KO (`fd->state_id < ASID_WAIT`) and put his numbers back; clear every variable in `OwnLoad`.
- Check it in one boot: the probe's `attrs` step prints his numbers as the game holds them (`sk_arts_numbers`), and a
  hit on the bag in the mode against the same hit without it (`sk_fsmash`, `sk_buster_fsmash`); a throw in two modes
  (`sk_buster_throw`, `sk_smash_throw`); pictures of the shown mode as it starts, while it is on and in a swing
  (`sk_arts_show`); and the mode's voice line in the sound check (each test's scripts in `audio_check.SCRIPTS`).

A module that changes its own state's hits after the script made them (one side of two, a strike's power) finds
them by their NUMBERS, never by place or size: the driver joins a script's like balls into fewer (Melee holds four)
and writes an Ultimate hit of `part 1` with a hit group of its own, so both groups strike the same fighter. Shulk's
Back Slash writes front (angle 361) and back (140) hits at once: `own_shulk.py:back_sides` tells them by angle, and
`S_Hits` puts out the side not wanted, chosen ONCE an action as the hits first come out (a fighter struck turns to
face him, and the other group would strike him again the next frame).

## 4. Kinds with no example on this route yet

Say so in the module and in `provides`. Each has code on the donor-skeleton route to read, or engine code that
does it; none of it is tried on a skeleton of the fighter's own.

- **A counter** has an example now (section 3, Greninja's Substitute). The other way, keeping the donor's own
  counter states (Marth's `SpecialLw` waits, `SpecialLwHit` strikes: `ctx['state']`), needs the script's flag 1
  raised by the module (`fd->ftcmd_var.flag1 = 1` on the window's frames: the script is emptied), and the ball rides
  a joint by the donor's numbering (its special numbers at 0x64). The strike's damage as a multiple of the hit taken
  is done on the donor route (`oneshot.py:COUNTER_DONOR`, the counter part of `code.py:source`).
- **A charge with levels.** Greninja's Water Shuriken (`own_gekkouga.py:NHold_Anim`, a level per item state). A state
  that loops while `B_BUTTON` is held and counts frames: also Ike's (`own.py:QdHold_Anim`) and Cloud's
  (`own.py:ChargeLoop_Anim`) on the donor route. The donor's own charge
  (Marth's neutral special) counts loops and sets the release's damage (`oneshot.py:CHARGE_DONOR`). A hit's damage
  can be set from code: `Fighter_UpdateHitboxDamage(&fd->hitbox[i], damage, gobj)` (in `code.py:source`). A
  charged shot: one item state per level (`own_duckhunt.py:Bullet_Anim`). A stored charge's glow: `oneshot.py:OWN_GLOW`.
- **A meter or gauge.** No example here. Cloud's limit gauge on the donor route: a value kept by player, filled in
  the frame code from damage taken and dealt, drawn on the damage display (`own.py:Gauge_Make`,
  `own.py:Gauge_Draw`), lit on his body (`own.py:Limit_Light`). The engine has no gauge of its own.
- **A tether.** No example here. Byleth's on the donor route: `fd->cb.OnGiveDamage` notes what the whip caught
  (`own.py:Whip_Hit`) and a state draws him to it (`own.py:Latch_Phys`). A tether to a ledge: the donor's air up
  special catches a ledge when its script flags say so (`oneshot.py:TETHER_DONOR`), and the ledge box is widened
  while the whip is out (the tether part of `code.py:source`: `fd->coll_data.cliffgrab_width`).
Greninja, as kinds (`own_gekkouga.py`): Water Shuriken is a charge with levels and a shot (one item state per
level); Shadow Sneak is a dash (Wolf Flash) that vanishes; Hydro Pump is a recovery that rises (Fire Wolf, aimed by
the stick); Substitute is a counter that vanishes and strikes from elsewhere. List a fighter's clips before naming
any (`oneshot.py:clip_names`).

## 5. How to decide

Ask of each source special, before writing it:

1. Does it move him? Which way, how fast, for how long, and who brakes it? A physics call of its own.
2. Does it make a thing? A shot (flies and is gone), a thing that stays (stands, can be struck), a helper (acts by
   itself). An item, and its spec.
3. Can it be held or charged? What does holding add, and what lets it go?
4. What ends it: its frames, the button let go, a hit, a landing, a ledge? What may cut it short (a jump, a
   shield, an attack in the air)?
5. What happens in the air: the same move, a form of its own, a fall? Is he helpless after it?
6. Does he strike with his body (`HIT_ACTIONS`), or only with the thing?
7. Where does each number come from: the script, `vl.prc`, the clip, published frame data? Note each.
8. What does Melee already have that is close: the donor's own states, the engine's calls (reflect, absorb, the
   helpless fall, the ledge catch), another vanilla fighter's code in the decompilation?

Liberties are fine where Melee has no form for something (a bubble drawn with 3D rings, a figure of a thousand
squares, a bounce off the floor). Make a sensible stand-in and say it is one: in the module's docstring, in
`numbers` (`'STAND-IN: ...'`) and in `provides`. Never leave a special out for want of exactness; never let a
stand-in pass as the move.

## 6. Checking a special without many boots

Add tests for his specials to `MOVES` in `harness/look_probe.py`, each written out by name, beside Wolf's. One of
Wolf's, as a pattern:

```python
'w_laser': [(0.0, 'bag 60 0'), (0.5, 'freeze'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'steplog 80'), (0.5, 'unfreeze'), (1.0, 'end')],
```

Each step is `(seconds from the test's start, step)`. `freeze` and `steplog n` step the game a frame at a time and
log every frame where something changed; `bag dx dy` puts the second fighter that far in front; `stick x y`, `B+`,
`B-`, `X+` (a jump) work the pad. The probe's docstring lists every step.

Then one boot for all of them, each test in a match of its own:

```text
python round.py <work> <iso> <fighter> --own "gk_*" --plan     (lists the tests and starts nothing)
python round.py <work> <iso> <fighter> --own "gk_*"
```

(`harness/round.py`, run as its docstring says.) What in a test's line says the special worked:

- `states (number, seconds in)` and `frames in each state, in order`: his own states (373 on) for the frames
  expected, ending in 14 (standing), 29 (a fall), 35 then 43 (the helpless fall and its landing), 252 (a ledge).
  Wolf's Blaster: `frames in each state, in order: 14x1 373x52 14x29`.
- `bag took X% in hits (seconds, %)`, and in the stepped lines the bag's state (75 on: hit) and its damage: the hit
  landed, on which frame.
- `track (...)` with `PROBE_TRACK=1`: the first item's place and state each frame (the thing was made, flew, ended).
- `rose` and `went`, and `highest` in the stepped summary: how far the move took him.

Use these optional developer checks to verify playable movement, interactions and recovery.
Exact source frame matching is later calibration work, not a requirement for building a port.

## 7. Traps

- `build` with any parameter but one named `ctx` is not a module: preflight says so, and the route builds no special.
- A clip sent to a donor action the driver's own rule fills is lost; only `<work>/spec/skipped.json` says so (`own_template.py:spec_of` reads it).
- A chain of side special clips (`specials1`, `specials2` ...) takes SpecialS2Hi to SpecialS4Lw; a clip named like a donor action may take that action (Wolf's `speciallwhit` went on SpecialLwHit).
- Without `Fighter_AdvanceScript` after `ActionStateChange`, the script starts a frame late.
- The frame a state is entered on is its first: its physics and collision run on it.
- A physics call that does nothing on the ground leaves him where he is; in the air the engine still moves him by `self_vel`.
- `Fighter_PhysAir_ApplyGravityFastfall` already drifts him (decompilation `ft_081B.c:ft_80084DB0`): a second drift call adds nothing.
- Telling a ground state from its air form by arithmetic on state numbers breaks once a move has an odd number of states: list the pairs (`own_template.py:other_forms`).
- Don't write state numbers into C by hand: they start at `ctx['first']` and move when the donor or the rows change.
- A reflect bubble goes down at every change of state, a hand-over included: put it back up.
- The helpless fall keeps a jump he had: take it away until he stands.
- The donor's special scripts are emptied: a flag the donor's code waits for is never raised unless the module raises it.
- A script's body flashes are not played on his states unless `build` hands them over (`flash`).
- A sound a script names that his bank does not hold is dropped without a word: listen for it.
- A sound code plays is right only on a bank built by the same run: the places change with each build.
- An item does nothing until it is given a state.
- An item the fighter made must end: on `Lost()`, on its own time, and two frames after it was made if never let go.
- An item's code and the fighter's cannot call each other: they talk through `item_var`.
- Every item's number is told to m-ex in `OwnLoad`; the loop's count is the number of items.
- A hitbox an item takes from the template item keeps its "hit again after" frames: set `again`.
- A model is hidden with `JOBJ_SetFlagsAll(model, JOBJ_HIDDEN)`; the kit's own "set hidden" call shows it.
- Two of his own items must not meet as hits unless that is meant: see it a frame ahead (`own_duckhunt.py:Knock_Frame`).
- Every variable kept by player is cleared in `OwnLoad`: a rematch starts with what the last match left in it.
- `ctx` has no fighter name: `own_wolf.py:clip_length` writes `wolf` into its path; change that when you copy it.
- The code file already has `OnLoad`, `OnFrame`, `move_logic`, `ReverseInput`, `TravelFrame`, `FlashFrame`, `Flash_Anim`, `flash_keys`, `FacesLoad`, `FacesFrame` and `GetTrailData`: name nothing so.
- The route's flash code swaps `fd->cb.Anim` while an action with a colour plays; a module that swaps it too (`own_duckhunt.py:HiAttack_Anim`) must not lose the other's.
- In the probe, `neutral` lets every button go: keep a button held with `stick 0.5 0.5`.
- `pads 1 0` gives the pad to the second fighter and takes it from his.
- A target pinned in the air stands on the floor for the engine: test an air hit on a target that stands or jumped.
- Tests in one boot share damage and items; `round.py --own` gives each its own match, `look_probe.py` alone does not.
- `round.py` finds only tests written out as `    'name': [` (`harness/round.py:known`): a name made in a loop is not found.
- A form of a fighter of forms (`fighters.FORMS`): its first four states of its own are the switch's (`forms.py`), so a module's `build` takes `ctx['first']` as it is given (already after them) and leaves out the special named by `ctx['switch']` (the template does both); it must not use `forms.PARKED` or `forms.CLOCK`, or name a function `Form_*`, `FormLoad` or `FormFrame`.
- Hand a move over (ground to air, `Hand_Over`) on a frame BEFORE the one its script makes its boxes on, never on that frame: the boxes made then are taken down by the hand-over and the new state's script goes on after them (Fishbunjin's Bell Ringer struck nothing until handed over on frame 8, its boxes made on 9).
- A hitbox made in code uses the Grab_Box pattern (`own_gaogaen.py`) with its damage and angle set. Fishbunjin's shockwave is now an independent item (`own_fishbunjin_wave.py:item_specs`), so it survives interruption of its owner. Armour a module gives is its own value (`OWN_ARMOUR` 4322.0f there): the route's frame code clears its own (4321.0f) wherever its spans end.


## Bounded article capture as a Melee adaptation

`own_capture.SOURCE` supplies `Hold_Begin(target, item, duration, body_offset)`,
`Hold_Uses` and `Hold_Release`. A native collision must supply the target; do not
infer contact from distance or damage changes. Call Begin with a currently live
item after native damage processing. The item needs a unique generation token
in `item_var.var6`. The helper validates target membership and item identity,
pins a native fall state to the article, and allows fresh-button/stick escape.
It yields when another hit/grab/KO takes the callbacks and releases on timeout or
item removal. It does not resume its hold over a new native action. This is an
explicit adaptation, not Melee's native grab ownership protocol.

Ranno's bubble and tongue use this helper. Their 1% contact hit is deliberate:
Melee's item damage callbacks select a fighter only for positive dealt damage
(`ftcoll.c`, `xC34_damageDealt` / `xCF4_fighterGObjUnk`). The shared raw-contact
observer also queues captures: a staled 1% hit can truncate to zero in the item
callback despite actual damage. Both paths defer hold/state changes to the next
fighter update. Shields/reflectors
pop the article. Bubble duration, steering and procedural visual are reported as
adaptations; poison stacks increase the hold and are consumed on capture.

`own_template.build_plain(ctx, ())` returns just the shared state scaffold when
a module implements all four specials itself. A nonempty request whose clips
are missing still fails; this is not a fallback to donor specials.


## Source-driven aimed recovery

BCM’s `own_bcman_recovery` reads launch speed from the retained custom component,
converts source world units with the reader’s scale, and reads its hop, launch,
hit income and exit phases from the source program. Current stick input drives
aiming in IASA; Z makes fine adjustments. Native movement/collision supplies
landing, ledges and helpless fall. `own_bcman_specials.counter_gate` is shared
across down, up and helpless entry points and keeps each source input predicate.

This is a playable adaptation: a short native special landing replaces the
source crash knockdown and angle-dependent landing penalties. Exact animation
and timing parity are deferred. Tests cover movement, reverse aiming, cash/input
guards, native callback preservation, landing and interruption cleanup.


## Ordinary builds use one disc

Without `--calibrate`, `fighter_port.port --own` runs through costumes, builds
the final disc with packager-generated portraits, then verifies the package.
It does not build a preliminary test disc or boot a game. Explicit `firstdisc`
stage requests still work; `--calibrate` retains the developer round/art path.
An old status file's missing `firstdisc` no longer counts as unfinished normal
build work. Optional fidelity notes remain separate from functional coverage.


## Native command grabs

`own_command_grab` supplies native grab boxes, owner/victim initialization,
reciprocal ownership validation, thrown damage and safe drop cleanup. An adapter
provides its own bounded hold animation/state, anchor joint and release time.
Only actual Melee collision establishes a grab; distance is not treated as a hit.
Native release applies percent, knockback, stale-move handling and damage state.
Cleanup does not overwrite another fighter's damage state.

BCM's side special uses these helpers for its lunge and reversible spit. Ground
and aerial entries can capture; an aerial entry grants a hop only once until
landing. The source capture clip plays on a separate state. Both entries use
the source ground-grab geometry directly, adapting the source aerial setup hit.
Victims remain visible in Melee's captured pose. These choices are reported in
the ordinary build receipt; source-specific victim hiding and pose fidelity are
deferred polish.


Stage status keeps earlier logs as history, but marks dependent artifacts stale
when an input stage runs again, including failed or interrupted attempts. A new
driver requires new sounds and a new disc/check; it does not discard unchanged
costumes. Rebuilding the prepared rig also invalidates those costumes. Read-only
preflight/verification do not silently make a stale disc current. A successful
own build's embedded verifier counts as completed file verification. None of
this requires gameplay calibration or turns the fidelity backlog into a gate.


Normal own-skeleton preflight requires MexTK, because its compiled code supplies
specials and movement. Missing MexTK is a setup error with the `--mextk` /
`MEXTK_DIR` remedy, not a successful gameplay build with inert specials. The
low-level data-only driver remains available for development. Gameplay harnesses
and exact source timing are not prerequisites.


Every normal package includes `PORT_NOTES.txt` and `port-implementation.json`,
also saved beside the zip. They summarize the actual driver report: custom
runtime versus placeholder/missing slots, included behavior, declared adaptations
and unfinished mechanics. Generated-file readback is separate from gameplay
evidence; no module is labeled complete merely because it compiles. The ordinary
CLI shows build stages and runtime status. Detailed fidelity counts remain in
status.json and are printed only when calibration was explicitly requested.

## Declaring mechanic coverage

Four populated special slots are not a mechanic inventory. `port_mechanics`
combines reviewed character requirements with reader-detected compiled branch
entries, article creation, and character-specific conditions. An adapter returns
`mechanics` claims naming an actual generated C handler, its behavior, and any
source obligations it covers. Unknown obligations remain `unfinished` in the
normal package's JSON and readable notes. Missing handlers, duplicate claims,
and claims for absent source obligations stop generation. These declarations
describe implementation; gameplay evidence remains a separate record.

`own_rivals_states.plan` accepts attack-scoped custom predicates and an explicit
free-action list. Its exact plan must feed both clip allocation and generation.
`own_action_slots` gives explicitly assigned source phases priority over automatic
donor placeholders and rejects two explicit owners of one action.

Reusable native pieces include `own_resources` for bounded resource transactions,
`own_batted_item` for real hurtbox-damage-driven redirection, and
`own_article_motion` for projectile fans and swept segment/circle contact.
Character adapters still decide when resources are earned/spent and which
compiled source behavior needs a Melee adaptation. A working reader supplies
data, not the omitted compiled gameplay logic.

For batted items, registering geometry is insufficient: register the hurtbox
count and root joint too. GALE01 reads the count at item offset `0xAC8` as a
byte, despite MexTK's `int hurt_num` declaration. `Port_EnableBatHurtbox` uses a
byte alias; an integer store silently produces zero on big-endian PowerPC.
Validate this path with an actual opponent hit, not only a host-side C stub.

Loxodont uses the common state/movement/grab runtime with a resource adapter for
charged boulders, native batting, lava pickup/extinguishing, powered down-special
choices and strong aftershocks. Ranno adds numbered source spin pulses, native
stage sling, tongue-to-bubble launch, rapid-jab release recovery and travelling
poison palm. Geometric effect pictures and adapted trigger/launch rules are
declared in their package notes. Ordinary users do not run calibration harnesses.
