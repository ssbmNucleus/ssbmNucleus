# Writing a game's reader

For whoever ports a fighter from a game the recipe has not read before. A **reader** supplies the shared source
data for that game. It reads the owner's install and writes the fighter out in Ultimate's shapes (the
files `fighter_port/source_game.py` lists). From those files the port's command runs exactly as it does for any
fighter, and no stage of the route is taught the new game. This page is the order of work and what each step
has needed so far. Read it once, then copy the nearest reader below and change it one step at a time.

Compiled character mechanics still need native runtime adapters, using the shared
helpers in SPECIALS.md. A readable roster is not a roster of finished custom
movesets. The normal package notes distinguish those cases; development
calibration is optional and its results improve the reusable reader/adapter.

When a step here was not enough, say so the way the trials did: in the work folder's `GAPS.md`, with the line to add.

For developer calibration, `harness/source_games/README.md` describes optional runtime probes. Use them
when a mechanic's effective behavior is unclear, then fix the reader/shared port code and add a focused
regression test there. They are not part of the user's port workflow and are not required for every fighter.
The Fishbunjin findings in `benchmarks/2026-11-13-source-calibration.md` include actual two-character hits;
code inspection alone missed an independent shockwave surviving its owner's interruption.

## 0. The readers there are

| Game | Engine | Reader | How its files are opened | What it was |
|---|---|---|---|---|
| Smash Ultimate | Nintendo's own | `echo_ultimate` | the archive (`data.arc`) through ArcExplorer's `smash_arc.dll`; scripts are followed in the compiled module (`gamedata/acmd.py`) | the first; the route reads it in place |
| Brawl | Nintendo's own | `echo_brawl` | Wii archives (`.pac`, `.brres`, `.brsar`), parsed in Python | the second; read in place (`--game brawl`) |
| Slap City | Unity 2020.3 (Mono) | `echo_slapcity` | UnityPy, with type trees made from the game's own DLLs | the first written game: mapped in 15 minutes, first disc at 56 |
| Rivals of Aether 2 | Unreal 5 | `echo_rivals2` | CUE4Parse in a small C# tool (`uetool/`), with mappings dumped from the running game; FMOD banks through Fmod5Sharp (`fmodtool/`) | the second written game: first disc at 51 minutes |

Every new game is a **written** game: its name goes in `source_game.GAMES`. Ultimate and Brawl are read in place
only because they came first.

**No reader holds the game's code or data.** Each reads the owner's own install when it runs and writes under a
root of the port's own; the game's folder is never written. Keep it so:
- No file of the game's goes in the repo: no clip, picture, sound, table, dumped mappings or decompiled source.
- What reading the game's code taught (a constant, a frame rule, what a field means) is written in the reader's
  own words in its docstring.
- Short lists of the game's names (a move's name, a field's) are fine; the readers are full of them.
- The work folder (`app/scratch/<game>-cold`) holds what the reader wrote and is cleanable.

(`echo_tier2_shulk` is not a reader: it holds the Shulk clip-to-action recipes `oneshot` reads. Ignored local
files there, `src/native_art_pixels.h` (pixels extracted from Ultimate) and `dragdown_*.txt` (copied wiki pages),
are not ours to share.)

## 1. The order of work

1. **Know the engine and its version.** Its install says: `UnityPlayer.dll` and a `<Game>_Data` folder is Unity
   (`globalgamemanagers` gives the version); `Content/Paks/*.pak` is Unreal; a `.pck` beside the exe is Godot;
   `data.win` is GameMaker. Write the version down: the tools depend on it.
2. **Look for a tool already on the machine before asking for a download.** Check the Python folders, the NuGet
   cache (`~/.nuget/packages`), other games' installs and earlier work folders. A download needs the owner's
   OK: ask once, plainly, with what it is for. Put it in a folder of its own, found through an environment
   variable (`UNITY_PYDEPS`, `RIVALS2_USMAP`). Never record the game being played to get what its files hold.
3. **Find the fighter in the engine's store** (section 2). List the roster with each fighter's input table before
   picking one: a story-only form is not a versus fighter (Slap City's Ruination).
   For Slap City: `python -m echo_slapcity <Game_Data> --list` writes JSON with each fighter's input table,
   move count and references to missing moves, without exporting assets. An input table is evidence to inspect,
   not proof that a prefab is selectable in versus.
4. **Write the body and skeleton, and look at them** (section 3). Render the fighter standing before anything else:
   the axes are wrong more often than not on the first try.
5. **Write the clips** (section 4).
6. **Read the moves into `game.json`** (section 5). Fix the frame rule before trusting any frame.
7. **The fighter's numbers** (section 6), **sounds** (section 7), **emblem and fanfare** (section 8).
8. **Check what was written** (section 9), then run the port's command as for any fighter.

## 2. Finding the fighter in an engine's store

**Unity.**
- The list of what can be loaded by name is the Resources container in `globalgamemanagers`. Slap City's fighters
  are prefabs there (`smash/characters/<name>/<name>`).
- A prefab's root holds the game's fighter component. Beside it are the moveset, attack numbers, skins and
  sounds (`echo_slapcity/fighter.py`).
- A player build carries no type trees for the game's own classes (MonoBehaviours). UnityPy's
  TypeTreeGenerator makes them from `<Game>_Data/Managed/*.dll`. It got two things wrong for Slap City, both
  mended in `echo_slapcity/unity.py`: `m_Enabled` needs the align flag, and a `string[]` came out typed
  `string`. When a read goes wrong, read field by field until it does.
- What a field means, and the game's rules (the frame a hitbox comes out on, the knockback formula), are in
  `Managed/Assembly-CSharp.dll`'s IL. Read it with any IL reader already on the machine.
- An IL2CPP build (`GameAssembly.dll`, no `Managed/` DLLs) needs its DLLs made first (Il2CppDumper). Not met yet:
  ask before downloading.

**Unreal.**
- The paks are read with CUE4Parse (`echo_rivals2/uetool`, a .NET console app). Rivals 2's pak is
  Oodle-compressed: CUE4Parse needs an `oo2core_9_win64.dll`, and another game on the machine had one. Its index
  is not encrypted (a zero AES key).
- A game cooked with unversioned properties shows nothing but file names without a `.usmap` (mappings). Dump
  them from the running game with Dumper-7. That is a download and an injection into the game: both need the
  owner's OK.
  - Rivals 2's engine needed one fix in Dumper-7 (its FFieldClass has one more pointer in front).
  - Start the game's exe directly, with `SteamAppId` in its environment.
  - A game update can make the mappings stale: dump them again.
  - How it was done is written up in `app/scratch/rivals2/NOTES.md`.
- A fighter's data is in blueprints' class defaults: `uetool props <package>` gives them as JSON. Rivals 2 keeps a
  fighter in a few places:
  - `CD_<Fighter>`: the character's numbers;
  - `ATT_<short>_<Move>`: each move;
  - `SK_*`: the skeletal mesh;
  - `AN_<short>_*`: the clips;
  - the physics asset: the hurtboxes.
- Export the mesh and clips as ActorX (`psk`/`psa`; CUE4Parse never writes clips as glTF). A non-root bone's
  quaternion in a psa is stored conjugated.

**Engines not met yet** (Godot, GameMaker, a studio's own): the same steps. Find the container format's reader,
find the list of loadable things, find the fighter's root object and what hangs from it. Write the reader's head
docstring the way the two above are written: where the game keeps each thing, and what the reader does with it.

## 3. The body and the skeleton

- **What to write:** `model/body/c00/` with `model.nusktb`, `.numshb`, `.numdlb`, `.numatb` and the pictures
  (`.nutexb`); each other costume as `c01`, `c02` ... (pictures only, or a body of its own).
  - `ssbh_data_py` writes all of them.
  - The writers in `echo_slapcity/transcode.py` and `echo_rivals2/transcode.py` are the ones to copy.
- **The axes.** Ultimate's fighter stands Y up, faces +Z, his left at +X. Write the one matrix from the game's axes,
  and say whether it is a turn or a mirror.
  - Unity is left-handed, with the fighter Y up facing +Z.
  - Unreal's fighter stands Z up facing +X, his left at +Y: a turn, (x, y, z) to (y, z, x).
  - Check it on a rendered picture of the fighter standing, not on numbers.
- **The size.** The reader's `unit` takes the game's lengths to the port's. Hold the height against a published
  one, or against a fighter in both games.
  - Slap City's armature is scaled by about 45.6 in the prefab.
  - Rivals 2 is in centimetres, and no fighter is in both games: `MELEE_PER_CM` is the one number that says
    how big he is.
- **Joint names.** Rename the joints the route finds by name, and keep the game's own names for the rest:
  - `Trans` (the root the clips move him by);
  - `Rot`, `Hip`, `Head`;
  - `HandL`/`HandR`, `FootL`/`FootR`;
  - `Throw`.

  The readers' `NAMES` tables show how. A game without a `Throw` joint gets one: a held fighter AND Melee's
  shield hang from it (checklist 11.42; `echo_slapcity` adds it).
  A second fighter may call its hands something else: Business Casual Man has `r_hand`, not Ittle Dew's
  `r_fist`; Jenny Fox's hand reference names `r_axe`. Resolve missing landmarks through the game's bone
  references (`echo_slapcity.transcode.landmark_names`), and use that same mapping for model, clips and boxes.
  Keep an existing mapping when it is present: Fishbunjin has both hand and fist joints.
  A fighter may have no hands or separate pelvis (Ruby). Bind the source's body as `Hip` and attach the
  synthetic `Throw` to its explicit `grabPoint` during grab/throw clips. Slap's source `sizeBones` provide
  collision points; do not manufacture missing feet/head references. A handless body's Melee item attachment
  is a reported `Have` joint at its source grab point; the source game itself has no item system.
- **Single-influence skins.** Unity can store only one bone index per vertex and no weight channel. The
  weight is implicitly 1, as [Unity documents](https://docs.unity.com/en-us/engine/6000.7/script-reference/unityengine/skinweights/onebone).
  `skin_influences` handles that layout (Tetron), and rejects missing weights for multiple influences.
- **What a move calls a bone may not be a bone.** Slap City's moveset names SHORTCUTS: `l_foot` is the bone
  `l_foot_end`. Resolve them in the reader, or every box sits on the wrong joint.
- **Costumes may not be pictures.** Rivals 2's are palettes a shader applies; `echo_rivals2/palettes.py` bakes them
  into pictures. Discover the palettes available for that fighter: Ranno has no Gold palette. Keep default
  and team colours first, then fill from real available palettes; explicit requested palettes remain strict.

## 4. The clips

- One `motion/body/c00/<stem>.nuanmb` for each of Ultimate's stems the fighter has. The readers' `STEMS` (shared
  actions) and `MOVES` (attacks) tables map the game's clips onto the stems. A clip with no stem is written as
  `z00<name>`.
- One clip frame for each game frame. A game that plays a stretch of a clip faster or slower (Rivals 2's windows)
  has its clips made, not copied: the move's own frames are then the clip's.
- A move may share one clip on the ground and in the air. Write it under both required stems when the move
  starts that clip unconditionally (Slap City's Business Casual Man side/up specials). Preserve separately
  named air clips; a conditional start needs its branches read, not a guessed duplicate. A zero-weight
  parallel clip is dormant, so it does not compete with the active entry clip (Tetron's side special).
- Follow source attack-button transitions to assign jab slots: Ittle's `jab0 -> jab1 -> jab2` and Tetron's
  `jab -> jab2` have different naming schemes. Loops and branching follow-ups still need custom behavior.
- **Root travel.** Melee moves a fighter through his rolls, getup and tech rolls, ledge roll and climb by the
  clip's own root (`Trans`, along +Z). A game that moves these in code leaves the clip in place, and he would
  roll on the spot. Give the clip the travel from the game's speeds (`echo_rivals2/transcode.py: TRAVEL`).
- Say which clips could not be read. Rivals ACL bone clips use the owned decoder when CUE4Parse lacks its native DLL; a refusal remains explicit.

## 5. The moves: `game.json`

`game.json` is the driver's `game`: the shape `echo_ultimate.gamedata.moves.load` gives for Ultimate. Copy a written
reader's builder: `echo_slapcity/gamedata.py: move_entry`, or `echo_rivals2/gamedata.py: entry_of`.

| Field | What it is |
|---|---|
| `fighter`, `game` | the folder's name; the game as named in `source_game.GAMES` |
| `moves` | `{'game_' + stem[3:]: move}`: the driver finds a move by its clip's stem |
| `melee_attributes` | `[{'op': 'set_attribute', 'name', 'value'}]`, names from the app's `vault/echo/attributes.py` (section 6) |
| `source_tables` | `{'hurt': [{bone, a, b, radius, height, part}], 'ecb': [{bone, offset}]}`: hurtboxes and collision joints |
| `motions` | `{stem: {game, cancel_frame, intangible}}`: by clip, the frame he may act on and the untouchable frames (the getups' and ledge actions' are written from here) |
| `unit`, `drawn`, `bones`, `kb` | the length unit, the drawn scale, the skeleton's names, how knockback was carried |
| `own_params`, `projectiles`, `articles`, `specials` | the game's own numbers, kept for the specials' module |

A move:

| Field | What it is |
|---|---|
| `animation` | `<stem>.nuanmb`, a clip the reader wrote |
| `time_keys` | `[[move frame, clip frame], ...]`, stopping on the frame BEFORE `cancel_frame_real`. The driver plays the clip on past it and frees the move there; keys to the clip's end free every move at its clip's end |
| `cancel_frame_real` | the frame he may act on (None: the clip's end) |
| `hitboxes` | `[{id, bone, first, last, size, x, y, z, damage, angle, kbg, bkb, fkb, effect, shield_damage, hitlag, targets, flags, grab}]`. `last` None: out to the clip's end. `last` before `first`: made and made again on one frame, a choice the game's code makes (the driver keeps the one that stays). `bone` 'top': placed from his origin |
| `intangible`, `armour`, `landing_lag`, `charge`, `momentum` | when they apply (None, or frames) |
| `sounds`, `effects`, `flashes` | `[{cmd, real, name}]` on their frames; a sound is found by its `name` in the sound folder |
| `articles`, `article_frames`, `other` | things the move makes (a shot), grabs (`CATCH`) |

- **The frame rule.** Write down how the game counts frames, in the reader's docstring, and hold one move against
  published frame data before trusting any frame.
  - Slap City: a timeline entry at `af` is out on frame af + 1, found in the game's IL; nothing was published to
    check it against.
  - Rivals 2: a window's frame 0 is the move's frame start + 1.
  - Brawl counts waits from 1.
- **A move given as windows** (Rivals 2) is cut into parts, one Melee action each: checklist section 10 has how.
  Preserve all cancel destinations, including ones absent from the initial fighter's explicit move mapping.
  The Rivals reader writes stable `d04branch_*` clips for uncovered paths, with `conditional_only: true`.
  Each move retains `window_cancels` (window, first/last frame and the complete source condition) and
  `path_end` (including a loop or engine-owned exit). `source_attacks` retains the original attack properties.
  A cancel at the window's exit boundary remains reachable; it must not become an empty interval.
  Exporting a predicate does not execute it. The custom module binds supported predicates to its native
  states; unknown resource/character conditions remain explicit data. Never splice them onto the ordinary
  path unconditionally. Conditional clips preserve full recovery separately from their input window.
  A branch after a throw release contains ordinary hitboxes; it must not repeat the throw's absolute damage
  and release commands. The ordinary throw part alone owns its matched release window.
  Zetterburn's consuming strong/forward-throw paths use this data; Ranno independently exports rapid-jab,
  projectile-release, recovery and up-special choices. Ranno still needs the corresponding custom behavior.
- **Which move is a special** is the game's own input table (Slap City's `standardSCinputTrigger`), not a move's
  name: a moveset keeps leftovers nothing starts. What a special does beyond its script is the specials' module
  (SPECIALS.md).
- **Several controls may share one source move.** Keep every control slot when grouping by source move:
  Asha's four specials share `spn`; Goddess's jab and neutral air share `explosions`. A single `move -> stem`
  dictionary silently drops earlier assignments. Expand all aliases in both the scripts and the clips,
  preserving separately defined air/follow-on states. The Slap City reader's roster regression checks this
  directly against installed input tables; this is developer coverage, not another step in a user's port.
- **Knockback.** Carry the game's formula as Melee's numbers and mark it STAND-IN where the formula is compiled
  code (Rivals 2) or its units differ (Slap City).
- **The game's data has slips** (Rivals 2's up air names the forward air's sound). Carry them as they are, and say so.
- **Write for every fighter, not the first.** A reader written for one fighter takes that fighter's names: Slap
  City's took Ittle Dew's move names, clip names, armature name and unit. It also reads only the kinds of thing her
  moves had, and the second fighter (Fishbunjin) met 13 gaps of the reader's. Read each fighter by the game's own
  tables, and read every kind a move can have:
  - moves a special goes on to, and air forms;
  - the lists a custom call references;
  - armour;
  - a throw that hits by a hitbox;
  - a box with no end (it ends with its move).

  `tests/fighterport/test_own_fishbunjin.py` holds one test for each.

## 6. The fighter's numbers

`melee_attributes` sets Melee's own fighter numbers, by the names in the app's `vault/echo/attributes.py`
(`ATTRIBUTES`, or a word in `ALIASES`). **A name the app does not know is dropped without a word**: the Rivals 2
trial's first try had one (`max_jump_horizontal_velocity`).
- Speeds are Melee's units a frame. Convert the game's (a second or a frame, in its own lengths) with the reader's
  unit, and hold one against a speed known from play.
- Jumps: Melee wants a starting speed; a game may give a height, or a time to the top.
- Melee has numbers some games do not (two air accelerations to Rivals 2's one). Carry the nearest, and say how.

## 7. Sounds

- `sound/<name>.wav` (16-bit PCM) and `sound/sounds.json`: `{name: {'file', 'also': [other names]}}`. Names are
  Ultimate's words: `se_<fighter>_...` for sounds, `vc_<fighter>_...` for the voice.
- An `also` name is Ultimate's whole name WITH its number (`vc_<fighter>_attack01`): the donor's table
  (`voice.DONOR`) takes the attack, win and taunt lines in number order and never finds a plain word.
- Sounds in a middleware bank:
  - FMOD: `.bank` files. Fmod5Sharp was already in the NuGet cache (`echo_rivals2/fmodtool`). In Unity, UnityPy's
    own FMOD decoding took no clip once the bodies had been read: Slap City's reader writes the sounds first, with
    its own decoder (`echo_slapcity/unity.py: audio`).
  - Wwise: not met yet.
  - Write each sample by its own name. When the bank's event table is not read, events are matched to samples by
    name: say so.
- A move plays a sound by its name, so name each sound in `game.json` as it is in the sound folder.

## 8. The series emblem and the victory fanfare

`identity/series_icon.png`, `identity/victory.wav` and `identity/identity.json` (what each was taken from). Look in
the game's UI pictures and its music. Without them the donor's emblem and fanfare stay, and the sounds stage says
so (`harness/own_identity.py`).

## 9. Before the port

1. Name the game in `source_game.GAMES`.
2. Run the reader: `python -m echo_<game> <the game's folder> <fighter> <root>`.
   - Paths come from arguments and environment variables, never this machine's folders. A missing one is said
     by name, with what it is (`echo_rivals2/pak.py: NEEDED`).
   - Keep what was read from the game under the root (Rivals 2's `rivals2-cache`), so that a second run reads
     nothing from the game again.
   - After any change to the reader, run it again before the driver: the driver builds from the `game.json` on disk.
3. Check what it wrote: `python -m fighter_port.reader_check <root> <fighter>`. Preflight runs the same check for
   every written game. It catches what the trials found only later, in a port or in the game:
   - a number under a name the app does not know;
   - a roll that leaves him where he started;
   - time keys run on past the cancel frame;
   - an `also` name with no number;
   - no `Throw` joint;
   - a body lying down or facing away;
   - a box or hurtbox on a joint the skeleton has not;
   - a move whose clip was not written.
4. Then the port: PORT_CHECKLIST.md, as for any fighter. Section 10 is where each game's differences were written.


## Runtime calibration requirements learned across games

- Preserve input identity separately from script identity. The Slap City roster pass restored seven
  omitted slots where several controls shared one source script; regression fixtures cover all 11 prefabs.
- Keep input history and update numbering explicit. Rivals 2 uses current and previous SnapNet input;
  setting a visible attack state bypasses precisely the charge/cancel rules a reader needs to understand.
  On the Melee side, current-button decisions belong in IASA (SPECIALS.md), independently of source game.
- Distinguish an earliest interrupt frame from natural completion. Zetterburn's source side special
  returns idle on update 47 with no further input. The shared runtime now preserves that natural end
  separately from `cancel_frame_real=36`; rebuilt-disc checks accept attack at 36 and reject it at 35.
  A custom state must explicitly decide when input interrupts versus when untouched recovery ends.
- A successful projectile hit validates neither its full lifetime nor its status effect. Record target
  reaction and follow-up damage separately. Zetterburn's isolated source observations now supply Burn's
  five-tick lifetime and stun/hitlag pauses; consuming strong/throw follow-ups have separate native states.
  Those accepted cases do not establish equivalence for every status interaction.
- Calibration is development work. Preserve accepted cases and confidence per field, fix the normal
  reader/shared implementation, and keep regressions there; users never need to run these tools.


Slap City's flattened move list is accompanied by lossless `source_programs` and
`source_attack_properties`. Use these for loops, recurring hooks, meter expressions and conditional
transitions. Flattened hits/articles retain the complete `when` conjunction, including nested else
branches. `entry_clips` records conditional and zero-weight parallel clips. Asha's omnidirectional
special changes animation weights in recurring source hooks; Orka's up-special clip depends on
`spu_fall`. These need their actual runtime selection logic, not an arbitrary clip alias. Reader
validation reports this distinction while retaining the missing-animation failure until implemented.


Slap City ordinary jab chains also carry jab_followup_windows: registration and removal of a source
attack-press listener, with an exclusive end. The shared combat compiler maps both ends to the installed
clip clock; `own_jab` evaluates them in current-input IASA. A resource-dependent, held-button or branching listener is retained
in source_programs; it is not treated as an ordinary jab press.


Explicit Slap City and Rivals jab listener intervals are executed by `own_jab` in current-input IASA
on both native routes. The old Melee enable-jab opcode cannot close a gate. Listener end frames are
exclusive and may extend beyond general IASA into natural recovery. Slap readers must be refreshed to
include the neutral-stick predicate. Raw source predicates remain available; right-stick configuration
and source pre-window input buffering are not claimed equivalent by this adapter.


Slap `source_terms` preserves ordered float assignments, custom calls and guarded hitbox mutations,
including full scalar expressions and raw predicates. A conditional property replacement, clear, count
change or repeat-hit reset cannot mutate the ordinary hitbox path unconditionally. A guarded replacement
of an existing hitbox keeps its separate geometry and does not shorten/re-hit the base box. This finite
view does not replace `source_programs` for registered callbacks, nested execution phases or loops.

The BCM resource adapter exercises `own_slap_expr` and the shared `own_contacts` observer. The latter
samples native pending contacts after collision and before damage application, including trades and
secondary fighters; it does not invent events from later percent changes. Melee aggregates contacts per
defender, so it is not a full source-game hitbox event stream. The BCM module reports its remaining custom
specials, meter visuals, input adaptation and other resource branches explicitly. See
`benchmarks/2026-11-14-slap-resource-contacts.md` for the native evidence and limits.

Sound receipts distinguish an absent source bank id from a missing export. Slap's SAPlaySFX calls only
the fighter's bank; an unknown id is a silent no-op in SmashSFXBank.PlaySFX. The reader records the
case-sensitive source lookup on each event. Verification reports that source silence; an existing source
id whose WAV is absent or failed to decode remains an export fault.

### Native resource display

An adapter can use `own_meter.source(reader, label)` for a number above each player's
native percent. The reader returns the current integer value and color mode (0 ordinary,
1 buy, 2 sell). Call `Meter_Load(fd)` on load and `Meter_Frame(fd,gobj)` in OnFrame;
the text's own process refreshes after contacts, including during hitlag. Native scene
destruction clears its registration and frees the text. Labels are restricted to characters
handled by Melee's ASCII-to-SIS converter; unsupported punctuation can swallow a following digit.
This display is a port UI adaptation, not evidence that the source's particles/material effects
have been carried. See `benchmarks/2026-11-14-native-resource-hud.md` for the live BCM check.


### Rivals renderer curves

The normal game-data read now retains `source_visuals`: every source clip's float curves,
timing, interpolation and tangents, plus the default skin's renderer Blueprint inheritance,
material groups and complete function bytecode. ACL 2.1 float1f curves use the owned scalar
decoder (constant, quantized and raw tracks, including wrap samples); an unknown layout or
partially decoded Blueprint fails explicitly. These reads have separate caches from `props`.

`visuals.tick_bindings` resolves the supported straight-line ReceiveTick event through its
actual entry point and local arrays. A branch or unknown instruction leaves the event unresolved;
child overrides do not inherit a parent's uncalled tick. Ranno resolves SashVisible -> Visible
on SashGroup/Sash. Zetterburn's different event remains unresolved, with its source retained.
These are floating material parameters, not Boolean mesh visibility. The calibrated Sash material lineage
now uses `material_opacity`: numeric curves on each raw/split/resampled clip's clock. `own_opacity` carries
them through native animation job maps, enables material alpha before shader creation, and updates each
fighter after animation/input/collision. An interrupt restores the default; demo actions use their own table.
Unknown bindings and curves remain explicit unresolved entries rather than inferred shader semantics.

Opacity-only meshes receive independent model groups, including their low-detail copies: Melee's shadow
pass can bypass materials, so zero alpha also hides the group. Group allocation respects the engine limit;
combining existing discrete visibility with opacity on one mesh is not yet supported. The native adaptation
uses alpha blending instead of source screen-door dithering, disables translucent depth writes, and retains
a full shadow at partial opacity. Hidden-motion compression is not enabled. Every normal prepare/costumes
run applies the material setup; users never need to run a harness. Evidence:
`benchmarks/2026-11-14-rivals-curves.md` and `benchmarks/2026-11-14-rivals-material-opacity.md`.


### Slap held specials and guarded counters

`own_slap_expr.condition` uses Slap's actual Less/EOLess comparison names. An optional
input resolver compiles a retained CTI only when its buffer, event-blocking and button
semantics are supported by the calling adapter; unsupported inputs still fail by default.
BCM checks the complete cash/contact/current-press predicate before ordered payment and clamp.

BCM's down-special uses an independent update clock across clip rewinds and ground/air
handover. Melee's ordinary x2220_b3 no-reaction flag supplies unlimited armor with damage
and hitlag; the boss-only no_reaction_always flag must not be used for normal fighters.
Armor is reapplied after same-move transitions and removed on recovery; source cancellation
also clears the damage-to-cash multiplier. Registered hit listeners are scoped to the move.
Source SADeleteAction removes listeners, not ordinary input recovery.

The paid counter has separate native ground/air states sharing the validated neutral geometry,
with source entry velocity, reduced gravity, intangible range, angle and full recovery. Same-move
handover preserves hitboxes and contact logs instead of deleting an active attack. Native stun
and shield multipliers, source effects, the up/side specials and further resource branches remain
open in the normal report. See `benchmarks/2026-11-14-bcm-down-counter.md` for evidence and limits.


### Rivals aerial attacks and compiled article triggers

An explicit air attack asset owns its windows, cancels and articles. The reader discovers
NspecialAir/FspecialAir/UspecialAir/DspecialAir before considering shared-attack aliases.
Shared attacks use their declared AerialAnimation for both the main path and conditional
branches; hit geometry is recomputed on that clip. A missing declared animation is an error.
Ranno exposed seven extra aerial recovery frames being copied from the ground version.

An article declaration without CreationWindowStringTableKey is retained as `trigger: compiled`
with `real: null`, rather than an invented frame-one spawn on every branch. Its complete source
row is retained. `compiled_rules` holds separately observed emission rules with build/evidence
provenance; these are consumed during normal port generation without running a harness.
See `benchmarks/2026-11-14-ranno-neutral.md`. Native Ranno poison and wider move coverage remain open.

### Long native victory clips

`own_demo_segments` can preserve a whole nonlooping victory that exceeds the retail demo buffer
by using otherwise unentered results rows. It first tries the whole clip and only responds to
the bank's explicit capacity refusal. Every segment retains its source boundaries, is read back,
and must satisfy the sampled game-frame error bound; interpolation error remains reported.
Identical source poses alone do not permit sharing tails: embedded visibility, numeric material
curves, swing state and emitted sound scripts must agree. Faces/materials/sounds follow the
actual segment job. A demo-only native process advances segments before draw and preserves
residual time; the final clip holds normally. Insufficient rows or unsupported jobs fail explicitly.
Runtime continuation is observed for Ranno's complete389-frame victory; camera framing remains
an independent open presentation defect. See `benchmarks/2026-11-14-ranno-neutral.md`.


## Cooked Rivals material defaults and packed masks

The reader now resolves material-instance overrides through the cooked master material's typed
parameter tables, including vectors, scalars, textures and static switches. A child switch only
overrides its parent when its override flag is set. Cycles, invalid table lengths and unsupported
layer associations fail explicitly. The complete resolved source and bake adaptation are retained
under `rivals2.json.material_bakes`.

Elemental custom colors receive an explicitly approximate static linear-color ramp bake. This does
not recreate the source shader's curve remapping, matcap, Fresnel, time variation or displacement.
The ordinary bake still approximates lighting with flat color and ambient occlusion. Packed RGB
masks and ORMS are resized as independent channels: an unused zero alpha must not erase RGB through
premultiplication. Missing mask slots retain their original color indices.

Ranno's normal body/game export and prepare-through-verifier build pass. The owned native match
shows the formerly gray/black sash in green (`ranno-rgb-mask-fixed-native.png`); this is color-path
acceptance, not exact shader parity. Zetterburn's five neutral materials independently pass the
same resolver without a fighter-specific override. Material regressions cover inheritance,
override semantics, bad tables, ramp interpolation and packed masks with zero alpha. The full
working-tree suite passes 727 tests with 6 skipped, including the separate in-progress camera work.
Native camera framing remains unaccepted and is not part of this material change.


### Armor windows across readers

The own route accepts legacy `[first, end-exclusive]` armor and Rivals dictionaries
with inclusive `first`/`last` and numeric `armour`. Rivals negative WindowArmor
preserves armor within the exported path; zero clears it. Positive source values
are retained in the report and currently adapt to native superarmor. They are
not interpreted as numerically equivalent Melee knockback reduction. This fixes
the dictionary unpacking failure exposed by Kragg's armored side special while
preserving the existing Slap/Brawl representation.


### Compiled-only Rivals move branches

Some attacks enter windows directly from compiled character code. These include
capture, consume, sling and resource-hit paths with no incoming `WindowCancel`.
The reader now retains every remaining positive-length path component as a
separate conditional branch, including disconnected loops. It preserves the
main path and records `entry_trigger: compiled`; retaining a clip does not invent
an input condition or make the branch execute automatically. Ranno and
Zetterburn ordinary exports exercise this shared path.


### Slap special entries reached through callbacks

The reader retains otherwise-unmapped programs whose entry animation is a
special, plus their scripted successors. BCM's `spf2` capture is one such path:
no `SACTM` in its input move points at it. Existing control slots keep priority;
partial programs and ordinary unused poses stay out. This preserves data for
runtime adapters and does not invent automatic transitions. The normal BCM
export now includes `specialforward2` and passes reader validation.

Conditional alternatives can have deliberately disabled intervals in the flat
ordinary-move view. An adapter executing that branch must use its retained
program's lifetime. BCM's command grab reads its clear timer from `spf`, not the
flat alternative's `catch_end`. The regression includes the empty flat interval.


Conditional-only branch states retain their whole recovery animation even when
input becomes available earlier. Reader preflight validates their key ordering
but does not apply the ordinary attack key truncation rule: the custom state
adapter handles interrupts and natural completion separately. This includes
Rivals consuming strong/throw branches and ground-air follow-ups. Truncating
those clips to satisfy ordinary-attack validation would discard real recovery.

The normal build now turns Rivals compiled branch entries, compiled article
creation and character-specific window conditions into mechanic obligations.
Keep their stable attack/window/article identities even when a reader cannot
execute them. `port_mechanics.requirements` consumes these fields without
inventing triggers, and custom adapters claim only the obligations they handle.
Newly discovered source behavior therefore appears as unfinished package work
instead of disappearing behind four successfully compiled special slots.

Reader calibration is developer work. Normal users import the resulting package;
they do not need the source-game harness. Exact frame parity is separate from
recognizable moves, resource choices, real opponent contact, interruption cleanup,
and returning control to the player.
