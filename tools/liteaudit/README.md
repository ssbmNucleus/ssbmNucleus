# Watch Lite audit

A repeatable, offline audit of the real Watch Lite bundle and paint paths.
**Checks are highlighters, never build gates.** Inspect the flags; a process exit
of zero does not mean the replay, renderer, or audit infrastructure is correct.
The runner records unavailable producers and setup failures instead of failing
a build. It never fixes production code or downloads assets.

These checks can pass while the picture is plainly wrong (0.8.13: shine
mis-oriented, stages drawn as slabs, items as dots). Whether Watch Lite looks
like the game is judged with the side-by-side check at the end of this file:
the same replay frame captured in playback Dolphin, beside Watch Lite's render,
judged by a fresh-context reviewer.

From the repository root, with Node 20.6+ (`module.register`) and the existing
Python environment containing `peppi_py`:

```powershell
node tools/liteaudit/run.mjs --producer python
node tools/liteaudit/run.mjs --producer js
# Equivalent PowerShell entry point; all arguments pass through unchanged:
.\tools\liteaudit\run.ps1 --producer python
```

The default replay root is `~/OneDrive/Documents/Slippi`. The default Python is
`app/venv/Scripts/python.exe`. Animation zips are read from
`%LOCALAPPDATA%/SSBM Nucleus/storage/nucleome/anim_zips`; charmaps come from
`app/backend/tracker/tools/charmaps.json`. Override with `--root`, `--python`,
and `--anim-zips`. Nothing is installed. Original replay and animation files
are read-only. All generated files stay beneath
`app/scratch/liteaudit/harness/`, including a custom `--out` subdirectory.
Python runs with bytecode writes disabled.

## Running and sharding

```powershell
# All header/raw-eligible games, not just the golden selection:
node tools/liteaudit/run.mjs --producer js --full

# Make manifests once, then use separate terminals/processes:
app/venv/Scripts/python.exe -B tools/liteaudit/corpus.py
node tools/liteaudit/run.mjs --producer python --skip-corpus --shard 1/2
node tools/liteaudit/run.mjs --producer python --skip-corpus --shard 2/2

# Faster debugging; keep draw evidence for two sampled frames of each replay:
node tools/liteaudit/run.mjs --producer js --skip-corpus --limit 3 --traces 2
```

Shards are **1-based** and partition stable manifest order before eligibility
filtering. `--limit` is applied after sharding. The same selection feeds truth,
animations, data and render checks. Each producer/corpus/shard has a separate
report directory. Truth files use atomic replacement; animation packs are
separated by shard. Run a given shard only once at a time. Different limited
or custom-manifest runs with the same shard label should use separate `--out`
subdirectories. Root `report.json` / `report.md` are latest-run convenience
copies; concurrent runs can replace those copies without losing shard reports.

`--every 30` is the default render stride. Every producer row containing an
item **or whose true frame has a raw-truth item** is always rendered, regardless
of the stride, and so is every row where a fighter is a grab/throw victim or in
a Fox/Falco reflector state (events a stride would skip). The last row is also sampled. Python rollback rows are included
in render sampling because that is what its player currently consumes. Data
checks cover every canonical frame. `--refresh` rebuilds corpus and truth;
otherwise source size/mtime, extractor/backend hashes and peppi version govern
caching. Stable golden ordering does not depend on filesystem enumeration order.

The pipeline can also be run in stages:

```powershell
app/venv/Scripts/python.exe -B tools/liteaudit/corpus.py
app/venv/Scripts/python.exe -B tools/liteaudit/dump_truth.py
app/venv/Scripts/python.exe -B tools/liteaudit/extract_anims.py
node tools/liteaudit/check_data.mjs --producer python
node tools/liteaudit/check_render.mjs --producer python
```

Python stages accept `--manifest PATH`, `--out`, `--shard i/N` and `--limit N`
(corpus instead accepts `--root`, `--size`, `--refresh`). Node standalone checks
accept `--manifest`, `--full`, `--out`, `--shard`, `--limit` and `--producer`;
render also accepts `--every`. Use the orchestrator to get combined reports and
infrastructure errors as flags.

## What is compared

| Component / check | Meaning |
|---|---|
| `corpus.py` | Uses dependency-free `slp_meta.parse_slp`, then a light raw event walk for 2–4-port files. Records paths, players, stage, external/internal chars, netplay, rows, unique frames, backward jumps, rewind depth, laser event count and follower presence. The full manifest retains exclusions and header errors. A repository replay root is refused to prevent a repository tree walk. |
| Golden selection | Six worst games by extra rollback rows; every stage present, plus explicit coverage accounting for FoD 2, Stadium 3, Yoshi's Story 8, Poké Floats 23 and Dream Land 28; ICs including a follower game; actual Zelda/Sheik transforms; laser-heavy Fox/Falco; Peach, Samus, Link/Young Link, G&W, four ports and netplay. Longest qualifying games break coverage choices, relative paths break ties, relative-path hashes fill to 40. Coverage wins if it needs more than `--size`. Peppi acceptance is deliberately not a selection prerequisite. |
| `dump_truth.py` | Calls the **real** `_parse` and `build_viz_bundle`. Saves the unmodified Python producer and a projection of its output onto the sorted last occurrence of every true frame. Projects fighter/follower/form arrays, item samples and stage events; does not reimplement bundle derivation. Stores row IDs and kept row indices so the projection is inspectable. |
| `raw.py` | Independent event walk for truth items with spawn, type, owner, position, state, facing, `vx/vy`, stage events, row IDs and latest-finalized metadata. Last **closed** FrameStart/Bookend block wins, including empty item sets. An unclosed tail is flagged and excluded from item truth. Older recordings use last item emission per spawn/frame. Stage events dedupe by frame/platform. Recycled spawn IDs split after gaps/type changes. |
| `rollback_rows`, `timeline_row_count`, `not_finalized` | Original producer row count versus unique raw frames, and whether the bundle promises finalized rows. Python intentionally demonstrates these flags on netplay. |
| `finalized_frame_basis` | If `meta.finalized`, independently verifies `meta.start_frame + idx` against actual sorted raw/Python true frame IDs. |
| `fighter_field`, `fighter_shape`, `follower_shape` | All Python bundle fighter fields, form strings, and Nana arrays. Floats tolerate ±0.05; integer/state/category/input/lightshield values and strings match exactly. Python comparison uses last rows even when the producer itself retains rollbacks. Field-specific delta counts are under `metrics`. |
| `python_item_*`, `item_track_parity` | Track boundaries and per-frame multisets against projected Python output. Bundles omit spawn IDs, so matching maximizes compatible type/owner/position/state/facing pairs, then pairs leftovers by position to report deltas. Duplicate co-located items are not collapsed. |
| `raw_item_*` | Same comparison against independently finalized raw items. This can expose Python ghosts even when Python-versus-Python parity is clean. |
| `item_velocity_unavailable`, `item_velocity_delta` | Velocity availability and ±0.00001 component agreement with the raw stream. Python has no velocity fields, so its unavailable flags are expected. |
| `python_stage_timing`, `raw_stage_timing` | FoD/Stadium event counts, true frames and values, separately against projected Python and raw events. FoD heights tolerate ±0.05. |
| `render_item_missing`, `render_item_ghost` | Each raw live item is paired once with a producer item and must submit an actual nontransparent fill/stroke/image command in the real paint pass. Includes producer omissions on rollback rows. A prop held by its fighter (blaster, bow, cape, bat, Game & Watch tool..., by the game item name in `data/items`) is deliberately not drawn and is exempt, and so is kind 160, the stage's yaku item (`grMaterial` -> `it_802E6AEC`), whose ItCo.dat article has no model, except as a hazard (next row). Data checks separately verify the item's position/state. |
| `render_exploded_item_drawn` (`exploded_item_checks` metric) | A bomb in the state it blows up in (`itemArt.EXPLOSIONS`: Bob-omb 11, Link's and Young Link's bombs 5, Samus's bomb 3). The game hides the bomb (`JOBJ_HIDDEN`, itlinkbomb.c / itbombhei.c) and keeps the item alive about 80 frames. Watch Lite draws its own burst for `explosionLength` frames (the blast's hitbox frames, then smoke); after that nothing may be drawn for the item. The bomb's old look lingered there as a dot in 0.8.14. `render_item_missing` exempts every item in a state where the game no longer draws its model (`itemArt.modelHidden`, from the item code: these explosions and Samus's exploded missile). |
| `render_item_invisible_drawn` | Kind 160 (a stage part's hit/hurt volume, no model in game) must submit no paint command, except where it carries a hazard the game shows that has no collision of its own, in a state whose ALDYakuAll script has a hitbox: Peach's Castle 3/4 (Banzai Bill, its blast), Onett 2-5 (cars), Mute City 2 (cars), Jungle Japes 2 (Klaptrap). There it must be drawn. |
| `render_item_dot` (and `item_generic_dots` metric) | A vanilla item kind (<= 236, It_Kind_Kyasarin_Egg; higher kinds are m-ex fighters' own items) painted as a dot: one filled circle and nothing else, in any colour. Every vanilla kind has a look of its own, so this is a failure, except the kinds the game itself shows as a plain round ball (`DOT_OK` in check_render.mjs: Samus's bomb, Thunder Jolt, Shadow Ball, PK Flash and Kirby's copies). The 0.8.14 bomb, boomerang and thrown-egg balls were dots of their own colour, not the owner's, which the old owner-colour metric missed. `item_generic_dots` / `item_generic_dot_kind_<kind>` still count the owner-coloured generic dot. |
| `laser_no_segment`, `laser_angle` | Types 54/55 must stroke a segment. Its world-space orientation must agree with raw `atan2(vy,vx)` within 3°, modulo 180° because a segment has no arrowhead. Zero/nonfinite velocities are counted as indeterminate. Horizontal paint or the legacy Python horizontal fallback is expected to flag. |
| `fighter_dot_fallback`, `fighter_no_draw` | Wraps real `createRenderer().draw`, observes real SVG Path2D fill calls versus actual radius-7 fallback circles, and counts `(internal cid, state)`. Includes leaders and Nana; metrics separately count living fighters (state > 10). Custom characters and missing archives are explicitly reported. |
| `fighter_hidden_wrong` (`hidden_fighters` metric) | The renderer returns `hidden` (nothing drawn) only in the states where the game itself sets `fp->invisible`: Barrel/BarrelWait, CaptureWaitKirby, CaptureKirbyYoshi, and Sheik's/Zelda's/Mewtwo's up-B travel (decomp tables kept in the check, not read from paint). |
| `fighter_egg_not_drawn` (`eggs` metric) | A fighter in Yoshi's egg (YoshiEgg 277, KirbyYoshiEgg 332) is hidden in game but the egg is drawn on it as an accessory, with no item record: the renderer must fill an egg in its place. |
| `fighter_shell_not_drawn` (`koopa_shells` metric) | Bowser in Whirling Fortress (SpecialHi 359 from action frame 6, SpecialAirHi 360 from 7, to 50): the game swaps in the shell-only model part, so the renderer draws our own shell in the box the game's shell fills (`koopaShell` in data/itemMetrics.js) instead of the pack's full body; it must fill something. |
| `fighter_frame_reference_drawn`, `fighter_empty_pose_drawn` (`empty_poses` metric) | Most animation zips pad each animation to 201 entries and store a repeated pose as `frameN` (entry N of the same animation). Such an entry handed to Path2D as path data draws nothing, so it must never reach a fill. A pose whose geometry is empty (Mewtwo mid air dodge) is drawn as nothing, with no dot. |
| `stage_fill_missing`, `stage_fill_outside_collision` | What the stage LOOKS like, not only which floors exist. Using the geometry the paint pass drew (`stageGeometryAt`) and the recorded stage fill (canvas nonzero rule): (1) every floor on a closed clockwise run of collision (following each line's stored direction back to its start; the solid side is always on a line's right) must have fill 0.3 units under it; (2) every group of solid lines that has walls and floors must have fill under at least one of its floors (an open landmass such as Fountain of Dreams' still has a body); (3) no fill may lie 0.3 units under an underside ceiling, unless a floor lies on that ceiling (stacked bodies). Lines under one unit wide or steeper than 45° are not judged. A wing, bridge or deck with a free end (Venom's wing tips, Brinstar's middle bridge, Rainbow Cruise's decks) is not required to have a body. Catches a missing body fill (simulator stages lost it in 0.8.13), a slab filled below the real underside (the flat-underside silhouette) and a hull left open. |
| `stage_authored_frames`, `stage_partial_frames` metrics | Sampled frames whose stage geometry (`stageGeometryAt`) came from the authored fallback shapes (`source` `legacy*`: no collision dump and no simulator result), and frames whose geometry is marked partial (a simulator that placed only some pieces, Stadium mid-transformation); `sampled_frames` is the denominator. An authored outline is open (Great Bay's turtle arcs), so the fill rule cannot judge it; this count shows how often a stage is drawn from that fallback. |
| `stray_stroke_under_captured` | A grabbed or thrown fighter (action name `Capture*`/`Thrown*`, not the bundle's `cat`) with a grounded flag set, which is the grabber's: no opaque stage stroke that is not a collision line may be centred on its feet. Catches the ground-trail bar drawn under throw victims on partial stages. |
| `blaster_length_wrong` | A Fox/Falco blaster shot (54, 55, Kirby's 136, 137) must have its white core from the head (item position) back 11.152 x s along the travel line, s = min(3, (frames since it appeared or last turned + 1) x speed / 11.25), and nothing on the frame it is reflected (PlFx/PlFc item 0 model, itfoxlaser.c, verified in RAM). |
| `buried_floor_drawn` | A collision floor whose space just above lies inside the stage body (nonzero fill of the active lines) is drawn. The game shows nothing there: FoD's side platforms at the bottom of their travel, Randall passing under Yoshi's Story. Such floors are also exempt from `collision_floor_not_drawn` (metric `collision_floors_buried`). |
| `stage_fill_self_crossing` (`fill_polygons_checked` metric) | A traced stage body outline crosses itself where the camera can see (abs(x) < 300, -250 < y < 300). A self-crossing outline cancels part of itself out of the nonzero fill and leaves a hole in the ground (Stadium mid-transformation before round 8). Each polygon is checked once. |
| `stage_interior_stroke` (`stroke_seam_checks` metric) | A stroked wall or ceiling has stage body on both sides: a seam inside the landmass the game does not show (Stadium's base walls under a terrain). Floors are judged by `buried_floor_drawn`. |
| `reflector_not_drawn` | Fox (1) / Falco (22) in a reflector state (360-362, 364-367, 369; ftFx_SpecialLw.c) must have the game's reflector effect filled near the hips: a hexagon or half hexagon (EfFxData.dat effFoxDataTable models 0/1/2). Held (361/364/366/369): a hexagon of corner radius 8.2686 x 0.422 / 0.751 / 1.0199 x model scale (0.96 / 1.10), centred on HipN as read in RAM: (-1.27, 5.62) grounded, (-0.13, 7.3) aerial, model units along facing. The reflect flash (362/367) is due on action frames 1-11 only. Slippi records no effects; this is the only one drawn. |
| `reflector_turned` | That shape is drawn but not upright: every corner must sit at 30 + 60k degrees around its centre (one corner straight up), as in all three effect models; the effect is a billboard that follows HipN by position only, so facing never turns it. |
| `hit_spark_missing` (`hit_spark_checks` metric) | A fighter (leader) whose percent rises in hitlag (a hit; a throw's release and off-screen damage spawn no spark) must have a spark fill, the draw `hitSparks.drawHitSparks` submits (the loader labels it), within 20 units of its middle on that frame and the next two. Rows after a hit are always rendered. Custom fighters, followers (Nana) and hits on a shield are not judged. |
| `sword_trail_missing` (`sword_trail_checks` metric) | Link, Marth, Young Link or Roy (leaders) while the game's ring holds two or more samples of a trail (ftafterimage.c: a start command opens it, a stop command or any motion change ends it, a frame whose action frame stands still in hitlag pushes nothing) must have a trail fill, the draw `swordTrails.drawSwordTrails` submits (the loader labels it), within 1.5 units of the blade's tip at the newest sample (joint + axis x outer from `data/hits/<cid>.json` `trail`). The first frame each trail is drawn is always rendered. |
| `platform_out_of_frame`, `fighter_out_of_frame` | Framing through the hosts' own camera (`stepCamera`/`viewFromCam`, stepped every row like playback) at three host shapes: 960x540 (desktop clip/modal, 16:9), 615x250 (a wide card) and 390x338 (the phone player in portrait). When every living fighter stands on one level (y spread < 10), each platform over their stretch of stage (x range +- 30) and up to 56 units above them must be on screen; every living fighter must be inside the view the camera aims for (it eases toward that target, like Melee's, so a fast launch may briefly lead the eased view; that is not judged). Catches a camera that never shows Dream Land's or Battlefield's top platform, or crops a short or narrow canvas. |
| `randall_frame_basis`, `movers_frame_basis`, `*_geometry`, `*_call_missing` | Loader wrappers observe the actual stage-function arguments. Compare them with the raw/Python row's true frame, then compare recorded segments with the real geometry function at that true frame. `paintFrame` calls movers itself; the harness calls `drawRandall` with the host's `meta.start_frame + idx` contract. Missing calls are flagged, and checked segment counts are metrics. |
| `producer_unavailable`, `python_truth_unavailable`, `js_only_playable` | Distinguishes inability to run a producer from JS accepting a peppi-rejected file. JS-only games still receive independent raw-item/stage/render checks; Python fighter parity is unavailable. |
| `raw_warning`, `producer_warning`, `pipeline_error`, `render_error`, `sources_changed_during_run` | Incomplete evidence or audit infrastructure problems. Review these before treating an absent flag as evidence of agreement. |

The Python producer is **not** the projected truth bundle. It is the real
unmodified bundle, so the audit can reproduce rollback playback and moving-stage
drift. The JS producer imports only the public
`liteDeriver/index.js` `deriveFromSlp` entry point; it can be absent while Python
development proceeds.

`loader.mjs` uses `module.register` to stub only the Vite config/API imports,
resolve extensionless replay modules and adapt replay geometry JSON imports.
Calling the API stub throws. Stage wrappers forward to the original functions
and record their arguments. The shim records `moveTo`, `lineTo`, `arc`, `fill`,
`stroke`, `drawImage`, `setTransform`, transforms and paint boundaries. It stores
the original SVG path strings in `Path2D` objects but does **not** rasterize them.
Read-only item-array proxies label item draw commands without modifying their
values or the production paint source. Animation zip members are decoded in
Python and written as scratch JSON.gz packs, never extracted to arbitrary paths.
Each selected character gets its complete archive: the renderer may choose
fallback poses absent from charmaps, and trimming those would create false dots
and inconsistent shard counts. Packs are cached by source path, size and mtime.

## Reports and interpretation

Artifacts under `app/scratch/liteaudit/harness/`:

```text
corpus.json, golden.json               inventory, selection reasons and gaps
truth/<id>.json.gz                     canonical Python + raw stream + provenance
python/<id>.json.gz                    unmodified real Python producer
anims/<shard>/<cid>.json.gz             full local archive for each selected cid
animations-<shard>.json                archive source, counts and missing assets
reports/<producer>-<golden|full>-<shard>/
  report.json, report.md               combined summary and per-file records
  flags.jsonl                         one aggregate record per file/check
  traces/<id>.json                     optional sampled draw-command evidence
report.json, report.md                 latest run copies
```

Counts are **occurrences**, not severity or independent defects. Each per-game
flag keeps up to eight examples with true frame, producer row, expected/actual
values as applicable. `summary.checks` totals occurrences and affected files;
`summary.metrics` records coverage/denominators; `summary.fallbacks` counts
cid/state pairs; `worst_files` helps choose moments for human review. Reports
include source hashes before/after the run to expose another worker changing
the implementation during an audit. Shard JSON/JSONL files can be concatenated
or their counts summed; latest copies are not a merged report.

Start with unavailable/error flags and missing corpus coverage. Then distinguish
Python parity from raw truth: an item absent from JS but present only in Python
can be a Python ghost, not a JS omission. Lightshield depends on history, so
rollback-deduped trigger history may differ from projecting Python's already
computed lightshield. These are review findings, not automatically accepted
differences. Paint flags are independent of data parity: correct JS velocity
only fixes the angle when the paint implementation actually uses it.

This harness does **not** check Dolphin pixels, browser rasterization, visual
accuracy of silhouette mappings, mobile/React host wiring, public shares, R2,
or a third-party slippi-js parser. Randall's cloud is not judged; its platform
line and frame input are observed. Geometry comparisons
check timing against the shared geometry implementation, not independent game
collision truth. No Poké Floats replay means real-corpus mover coverage is absent,
even though synthetic timing probes can exercise that code.

## Adding a check

1. Choose the independent evidence: projected Python, raw stream, or recorded
   draw commands. Do not derive expected values from the producer field being
   checked.
2. Add it to `checkData` or `checkRender`. Use `flags.metric` for coverage and
   `flags.flag('descriptive_name', {frame, idx, expected, actual})` for findings.
   Return the flag; never throw/assert on replay differences or set an exit code.
3. Keep examples bounded and count every occurrence. Describe units, tolerance,
   sampled/full coverage and known limitations in this README.
4. Run both golden producers. Deliberately corrupt an in-memory bundle or draw
   result and confirm the new flag appears; leave application code untouched.
   Real replay/animation data and generated reports must remain in scratch.

The source is intended to be committed; replays, geometry packs and reports are
not. This worker does not stage or commit files in the shared checkout.

## Stages

`stage_bake.py` rebuilds Watch Lite collision geometry from the read-only
`app/scratch/liteaudit/stagedump/stage-<id>-early.npz` files when present,
otherwise `stage-<id>.npz`. It covers all 29 vanilla
VS IDs; 21 is unused and 26 is Adventure Icetop. It never launches Dolphin,
modifies the dumps, or accesses a service. Run from the repository root:

```powershell
app/venv/Scripts/python.exe -B tools/liteaudit/stage_bake.py --validate-js
node --test --experimental-test-isolation=none app/frontend/src/tracker/replays/stageCollision.test.js
```

The first command writes the compact runtime file
`app/frontend/src/tracker/replays/data/stageCollision.json`, 20 random-stage
porting notes, classification/error/coverage reports and six-frame composite
PNGs per stage under `app/scratch/liteaudit/stagework/`. `--dumps`, `--out`,
`--data`, `--decomp` and `--tolerance` override defaults. The default decomp is
`$MELEE_DECOMP/src/melee/gr` (`MELEE_DECOMP` defaults to `~/projects/melee`). Python uses the existing NumPy and
Pillow installation; Node uses the existing offline `loader.mjs`. No install
is needed. Without `--validate-js`, only the bake, source notes and basic PNGs
are rebuilt; existing runtime/replay reports must be treated as stale until
the full validation is rerun.

The calibrated frame key is **Slippi frame = match_frame**: the row contains
state AFTER that replay frame. C16 independently compared RAM boundary seeds
with raw replay pre-frame seeds at `match_frame + 1`; FoD events and grounded
platform heights agree. The earlier Randall standing-height check could not
distinguish adjacent frames. During countdown, recover frames by row index:
the last zero-counter row is Slippi **0**, immediately before counter 1.
Every countdown row in all five early captures matches the replay pre seed at
`s + 1` with this mapping; mapping the last zero row to -1 fails changing seeds.
Only duplicate gameplay rows use their last occurrence. Enabled, non-hidden, non-empty lines are
selected using runtime CollLine and CollJoint flags. The current low-nibble
line kind is retained; drop-through classification also reads MapLine's
static `lo_flags`, because initialization does not copy that bit into every
runtime line. The proximity-only CollJoint TooFar flag is not a visibility
toggle. Line IDs always mean original MapLine indices, not array positions.

The generator separates independently static joints, scripted animated
joints, neutral fallback poses and unresolved groups. Source policy is
joint-specific: a solo recording with no broken blocks does not make those
blocks static in a real match. Translation, affine or vertex-shape keyframes
are adaptively reduced in world-coordinate space, interpolated linearly, and
share identical tracks. Visibility/kind events use step sampling. The default
endpoint tolerance is 0.02 units; Randall uses 0.002. Only a full repeated
vertex/flag sequence with at least two cycles receives a loop period.
Verified periods are Randall 1200, Rainbow Cruise's scripted joints 7200,
Venom terrain 9999, and Kongo Jungle N64 499 frames. Mute City has a 6012-frame
suffix loop from Slippi 9541; its startup prefix is preserved. Poké Floats
remains bounded because its 25,200-row capture does not pass the full repeat
test. `loopStart` marks the first frame of a verified repeating suffix.

`meleeStages.collisionGeometry` evaluates the bake;
`liteStageInference.stageGeometryAt` selects the same geometry for paint and
validation. Paint fills each body from the ACTIVE solid collision lines
(`liteStageInference.solidFills`, also under simulators), so the fill follows
the real underside. The baked `main` polygon (a closed, noncrossing silhouette
with a flat underside, largest landmass only) is now only a fallback for a
frame with no solid lines. **Only collision floor kinds define walkable
surfaces**; an underside is never inferred to be a floor. The current kind
can change as a stage rotates. Walls and ceilings are drawn as separate
strokes. A simulator selects active layouts before the legacy fallback;
high floor-fit scores alone do not validate visibility.

Bounded animations disappear outside their captured range and use the
existing grounded-trail fallback. They are not frozen or falsely looped.
The existing full DAT Poké Floats path remains available beyond the short
live capture and is labeled a legacy fallback. FoD/Stadium events, Corneria's
anchor and Great Bay's neutral pose remain available. No random animation
schedule was copied from a single recording.

`stageSim/index.js` exports `simFor(stageId)` (registrations are in `all.js`)
and `registerStageSim`. A simulator receives `(bundle, idx)`, including leader
position/state/seed histories, and returns active floor/platform/wall lines
and line toggles. The documented contract specifies stable line IDs,
replacement/merge behavior, completeness, missing-seed behavior and seeking.
Simulators run before the ground-trail fallback. A result replaces authored
inferred surfaces with the dump's known static base before merging, so old
platforms cannot survive a simulator's toggle. Seeds are shared game RNG
state, not an independent stage stream; ports must resolve call order and any
contact, damage, item and DAT parameter dependencies. Recorded stage events
remain authoritative. `random-<id>.md` identifies collision-affecting source
functions, state/timers and every dump joint's vertex/line ranges. Explicitly
unconfirmed actor associations remain porting work.

With `--validate-js`, independent compressed fixtures are copied from the
NPZ, then the actual JS evaluator checks every unique dumped frame for line
presence, flags and endpoint error. The audit also measures true floor
endpoints/midpoints against the actual paint geometry, compares the original
authored baseline when `stagework/baseline-stages.json` is available, and runs
`deriveFromSlp` on every eligible vanilla nonlegal file in the corpus.
`replays.json` reports all `air==0` samples and a separate count excluding
dead/respawn samples. Ground trails are excluded from fit measurements so a
fighter cannot validate its own inferred platform. Empty samples and missing
surfaces are reported, not counted as passes.

`report.md` contains the per-stage class, exact coverage, JS max/mean error,
floor fit and payload size; JSON reports retain counts and baseline metrics.
`stage-<id>.png` overlays the bake on live collision;
`stage-<id>-runtime.png` shows actual paint geometry/fill;
`runtime-overview.png` is the contact sheet. Red-only lines expose unresolved
collision. These are offline geometry rasterizations, not browser screenshots.

Current measurements, independent dump counts, strict numeric equality,
0.05-unit endpoint matches, missing replay tails and unsupported simulator
rows are recorded separately in `app/scratch/liteaudit/c16/REPORT.md` and
`validation.json`. FoD 25/25 and Stadium 20/20 event games remain independent
checks with recorded events removed. The comments in `stageSim/all.js` document remaining gaps.
The five early captures have 25,200 rows each; seedA and wander captures are
validation inputs, never baked as random schedules. No browser/phone pixel
comparison is implied by offline geometry validation.

Heavy collision/mover tables remain lazy loaded in `data/stages/{10,11,22,23}.json`.
Mute City's simulator shares its collision table instead of retaining an old
separately calibrated capture. Run the baker twice into separate scratch data
directories and compare every generated JSON byte to verify reproducibility.
Exact raw/gzip and mobile replay bundle sizes are recorded in the C16 report.

### Captures, simulators and fighter/item data (2026-10-18)

`stage_dump.py` records live collision (and the RNG seed) per frame from a solo
Dolphin match. One Dolphin at a time. Useful options:

- `--early` starts at the countdown; `--seed` overwrites the RNG seed.
- `--wander` drives scripted movement/attacks; `--specials` adds B moves.
- `--place x,y` teleports after the entry animation; with `--air-place` the fighter
  jumps first, so it lands on the target instead of snapping back to its old ground line.
- `--script "jump@3,place@0,fsmash_r@40x20,wait@3000"` runs scripted inputs once.
  Actions: wait, left, right, jump, jab, nb, sb_l, sb_r, db, fsmash_l/r, dsmash,
  usmash, aerial_l/r, place. Syntax: `action[@frames][xRepeat]`.
- `--watch name=ADDR[>OFF...]:LEN` stores extra RAM per frame as `watch_<name>`.
  Corneria used `cam=0x80452C68:0x39C` (game_camera) to certify its camera reconstruction.

Every animated vanilla stage has a default simulator in `stageSim/all.js`.

Registration rule: every frame a simulator emits must pass the gate on every capture
(exact line IDs, flags and visibility, endpoints within 0.05 units). Otherwise it
returns null, meaning "unsupported here", and the viewer keeps the baked rendering.

Attack-, weight-, ECB- and item-driven stages (4, 6, 11, 13, 16, 17, 19) read
lazily loaded tables, `data/fighters/<cid>.json` and `data/items/<kind>.json`.

- `stage_bake.py --fighters` extracts these tables from the ISO.
- They load only for replays on those stages (`stageData.FIGHTER_STAGE_IDS`).
- Share artifacts embed only the clip's own fighters.
- Paint never waits for those tables. `node tools/liteaudit/item_sizes.mjs` derives
  the small, always-loaded `data/itemSizes.json` (family, hitbox radius x item scale,
  per-state radius where a charge changes it, body radius, held-prop flag) from
  `data/items/*.json`; re-run it after re-baking items.
- `python tools/liteaudit/compact_tails.py` compacts the documented
  `data/rngInputTails.json` (every action, nulls for unproven entries, provenance)
  into `data/rngInputTails.runtime.json`, the non-zero fixed counts
  `stageSim/rng.js` imports; re-run it after editing the full table.
- Items that are not fighter projectiles (common items, Pokemon, each stage's
  own objects) are drawn from the hand-checked table in `itemLooks.js`: name,
  ECB box (ItemAttr +0x40) and model scale (+0x60) read from the vanilla ISO
  (ItCo.dat, each stage DAT's `itemdata`), a colour and a plain shape. Kind 160
  is drawn only as the hazards above.
- `python tools/liteaudit/motion_names.py` writes `data/motionNames.js`: for
  each fighter-specific action state whose slippilab charmaps name is missing
  from that fighter's animation zip, the animation the decomp's motion table
  says the game plays (plus Kirby's copies of Pichu/Dr. Mario/Roy standing in
  with his Pikachu/Mario/Marth copies). `meleeRender.fallbackFor` holds the
  common-state equivalents (ft/ftmotionstates.c) and the stand-ins.
- `python tools/liteaudit/shield_table/build.py [--iso PATH]` writes
  `data/shieldTable.js` from the vanilla ISO: per fighter, the shield bubble's
  radius and the centre of its shield bone posed by forward kinematics through
  the guard pose (ftCo_Guard.c), untilted, at full tilt every 5 degrees and by
  GuardDamage frame (`meleeRender.shieldAt`). `shieldlib.py` holds the posing.
- `python tools/liteaudit/item_shapes/build.py [--iso PATH] [--decomp PATH]`
  writes `data/itemMetrics.js` from the vanilla ISO: the numbers behind Watch
  Lite's own drawings (`itemArt.js`) of the Onett cars, Ice Climbers' ice,
  Samus' missile, Peach's turnip (and where it sits while held), Yoshi's egg,
  Mario's/Luigi's fireballs, the Fire Fox / Fire Bird charge flame and travel
  plume (with its HipN anchor), Ness' PK Thunder tail, Pikachu's Thunder bolt,
  Yoshi's Story Shy Guys and Randall, the revival platform (and the
  per-fighter scale), Falco's blaster shells and Bowser's Whirling Fortress
  shell. The game's models are posed and measured, but only numbers are
  written: sizes and extents, colours, positions and how they change frame by
  frame. No outline, texture or sprite of the game's ships; Watch Lite draws
  these things itself. Every value is derived from the ISO; none is set by
  hand. `--decomp` is only read for `config/GALE01/symbols.txt` (fighter action
  states).
- `python tools/liteaudit/held_items/build.py [--iso PATH] [--decomp PATH]`
  writes a `hold` key into every `data/hits/<cid>.json`: where the fighter's
  item-hold part is (ft_data->x8->x10), posed through each action's animation
  (`item_shapes/fighterbones.py`), fighter-local, every 2 action frames, for the
  states fighters hold items in (standing, moving, jumping, falling, landing,
  shielding, rolling, being hit, picking up and throwing; Link's, Young Link's,
  Peach's and Yoshi's specials too). A held item's own position is not updated
  by the game, so the replay records where it was pulled or picked up for as
  long as it is held; Watch Lite draws it at this hand instead
  (`litePaint.heldAt`). `hit_tables.mjs` carries the key over.
- Hit sparks (`hitSparks.js`) come from what the game spawns when a hit lands
  (`tools/liteaudit/hit_effects/`): which effect, where and how big is the game's
  rule (ftcoll.c `ftColl_8007A06C`, `ftColl_80078538`; efasync.c), the effects are
  the game's own particles. HSD particles run a command list each, so they are read
  from RAM rather than re-simulated:
  - `node tools/liteaudit/hit_effects/pick.mjs --index <replay index> --out <targets.json>`
    picks hit frames by kind (normal, strong, slash, fire, electric, dark, ice,
    shield, throw, projectile; or `--kinds tech,techroll,walltech,walljumptech,ceiltech`
    for techs) from the side-by-side tool's replay index, only in
    replays the vanilla ISO can play (vanilla characters, stage id <= 32: m-ex
    stages leave playback black). Keep it to a pilot (~20-30 hits across kinds).
  - `python tools/liteaudit/hit_effects/record.py --targets <targets.json> --out <dir>`
    plays each in Slippi playback Dolphin and steps through the hit, reading every
    particle (lists at `hsd_804D0908`: texture group/pose, colours eased toward their
    targets, size, rotation, position, velocity, app SRT), every effect GObj, the
    victim's own contact point (Fighter +0x1854), hurtboxes, hitboxes and hitlag
    shake, plus a screenshot per frame. One Dolphin at a time (harness lock). A
    capture takes ~10 s; a target on a custom stage is skipped, and one that shows
    no match frame within 25 s (does not play on this ISO) is closed and failed.
  - `python tools/liteaudit/hit_effects/build.py --rec <record.py out for samples.json>`
    writes `data/hitEffects.js`: per kind the particles frame by frame around the
    contact point (the hits in `hit_effects/samples.json`) with the id (group, pose)
    of the texture each draws, and for the hit effects that texture from
    EfCoData.dat (`ptcltex.py`) reduced to an alpha and a light map, each a radial
    glow profile plus nested outlines fitted to the pixels they cover (never pixels);
    the slash model's crescents, traced; shield stun's torn bubble (model 13: strips,
    how many shift and by how much, the scribble's frames); a tech's effect (model 15,
    sample `tech`: its rays as particles, its glow's size, colours and fade, and its
    two rings' plane axes from RAM, lobes and colours) and PlCo.dat's hitlag shake.
    Shield hits, shield stun and techs are drawn with shapes of Watch Lite's own
    (`sparkArt.js`, `techEffects.js`); `hitSparks.js` paints the traced ones, cutting
    the faint tails of their glows, which read as large halos on Watch Lite's dark
    background.
  - `node tools/liteaudit/hit_tables.mjs` derives the small per-fighter hitbox tables
    the sparks read on every stage (`data/hits/<cid>.json`, ~7 KB; hosts load them
    through `stageData.ensureReplayHitData`) and the item elements
    (`data/hitElements.json`) from `data/fighters` and `data/items`.
  The contact point is on the victim's hurtbox, which Watch Lite does not have: the
  spark goes from the attacker's hitbox (or a projectile's path over the frame) half
  its radius toward the victim's middle. Against the game's own contact point (84
  recorded hits) that is a median 1.8 units off (2.8 for the hitbox centre). Slippi
  records Fox's and Falco's blasters but not their shots: a laser hit goes to the
  victim's side facing the shooter.
- `python tools/liteaudit/sword_trails/build.py [--iso PATH]` adds the sword trails
  (`swordTrails.js`) to the hit tables of Link, Marth, Young Link and Roy, the only
  vanilla fighters whose own scripts start one (`data/hits/<cid>.json` `trail`;
  `hit_tables.mjs` carries it over). The rule is ftafterimage.c: subaction command
  0x31 starts (0) or stops (-1) a trail, every frame not in hitlag pushes the sword
  joint's position and X axis into a ring of three, and the strip runs from inner to
  outer along the blade, newest to oldest sample, turned in 5 degree steps, fading by
  the tip's travel as the game measures it (it keeps the first step's difference, so
  the middle sample's fade depends on where the fighter stands). The colours, alpha,
  taper, joint and blade are SwordAttrs in the special attributes (Link and Young
  Link +0x64, Marth and Roy +0x78). Per action state, the windows the trail is on
  and the joint posed through the state's own animation at every action frame in
  them, fighter-local. A held Beam Sword (every fighter's Swing
  states, the command's item bit) is a `beam` key in every fighter's table: the sword
  item's bone 5 (on the hand) and its Y axis, the blade out to 10.03 x its live length
  (the swing's own 0x2D commands), the item's colours (pink to white) and no taper.
- `python tools/liteaudit/hit_flash/build.py [--iso PATH]` writes `data/hitFlash.js`,
  the victim's body flash (`hitFlash.js`): the colour animations a hit starts (PlCo.dat
  `ftLoadCommonData` [6], by element and knockback class, ftCo_Damage.c), stepped by
  the game's interpreter rule (lb_00F9.c `lb_80014258`) into one colour per step. The
  silhouette's fill is blended to it by its alpha, as the material is (ftmaterial.c).
  The darkness scripts also light the fighter with the overlay's light (`lights`);
  measured on game frames, that halves the body's brightness, so the fill is dimmed.
  `record.py` reads the fighters' overlays (Fighter +0x408 / +0x488), which is how the
  timing was checked: one step on the hit frame (two on a throw's release), then one a
  frame and one more per change of state (not into shield or grab states).
- `python tools/liteaudit/impact_effects/build.py --rec <record.py out>` writes
  `data/impactEffects.js`: numbers only, which `impactEffects.js` draws with its own
  shapes (spikes, puffs, rays, sparks, zigzags), no game art. The missed-tech bounce:
  EfCoData model 4's two rings of spikes (spike counts from the texture; per frame how
  far out and how high they show, measured on the meshes posed from RAM; the KONST
  alpha) and generator 60's dust (births, speed, friction, rise, growth, fade), from the
  recording `missedtech-u`. The shield break (recording `shieldbreak-falco`): the action
  frames its three electric bursts start on (the fighter's ShieldBreakFly script: 1, 3,
  7) and, by age, each part's size, alpha, count, spread and colour (the 1011 flare,
  the bursts' glow, star, sparkle, sparks and bolts, 1051's orb, glint and specks), and
  which of its texture's pictures the star and the flare show each frame (`pose`), so
  Watch Lite draws its own version of that picture (a flash, a jagged ring, rays,
  scattered rays; an eight-point flare, then an X). Each burst's random offset (+-7
  units on every axis, ftCo_8009F834) comes from the frame's recorded RNG seed, as the
  game draws it (`impactEffects.js` burstOffset); bursts behind the stage plane are
  painted before the fighters, or not at all when their heart is inside the stage body.
- `python tools/liteaudit/ko_effects/build.py --rec <record.py out for ko_effects/samples.json>`
  writes `data/koEffects.js`: the KO blast (`koBlast.js`), star and screen KOs
  (`koFlight.js`) and the invincibility timers (`invincible.js`). Only numbers read
  from the game ship (timing, size, colour, place, motion, which shape a particle is);
  Watch Lite draws every shape itself, no game textures or models
  (`hit_effects/record.py --targets tools/liteaudit/ko_effects/samples.json --pre 2 --post 180
  --shots 0` records the two samples):
  - KO blast: a fighter past the left, right or bottom blast zone spawns effect 1067
    (ft_0D31.c, efasync.c 0x42B), EfCoData model 25, where it is (a side KO's height and
    a bottom KO's x kept inside the blast zones), turned so it points into the stage,
    scaled by ftCommonData +0x4F4. Its five meshes become the box each fills in its joint's
    space and their colours, placed per frame as RAM had their joints on the sample KO
    (scale, translation, shown; the green flame's track does not evaluate right offline)
    with the KONST alpha track, and drawn as Watch Lite's own shapes; the first takes the
    player's colours (TEV0 / KONST from PlCo ftLoadCommonData [18] / [19], by port, team,
    or grey for a CPU: gm_80160854). Its particle track's generators (212-217, 222-224)
    are read from RAM like the hit sparks, in the effect's own space, each texture kept
    only as the kind of shape Watch Lite draws for it (streak, spikes, sparkle, star,
    smoke, starburst). RAM checks: the
    effect is first drawn at its animation frame 1 on the frame the fighter is first dead,
    at the fighter's position; the colours and turn per KO side are the game's.
  - Blast zones: each stage's general points 0x97 / 0x98 times its scale (grGroundParam +0).
  - Star KO (DeadUpStar): a straight line into the background (ftCommonData +0x504: z -350
    over 130 frames, playing DamageFall), then the twinkle (generator 289, from RAM). Screen
    KO (DeadUpFall): the model in camera space (ftdrawcommon.c), on the path of +0x520
    (come at the camera, hold, fall). RAM agrees with both on every frame. Depth is drawn
    through a camera with the game's 30 degree field of view that sees Watch Lite's view at
    z = 0, pitched and turned by the game's rule (camera.c Camera_80029CF8; the stage's tilt
    factors grGroundParam +0x14/+0x18/+0x1C, its centre point 0x94 and the camera constants
    at 0x803BCCA0 in main.dol). The hit-the-camera animation is not in the packs: the last
    tumble pose is held.
  - Invincibility: a fighter is intangible or invincible for a set time (ftColl_8007B760 /
    8007B7A4) after CliffWait 30, a throw (the thrower) 8, a wall tech 14, FlyReflect /
    DownReflect 15, BuryJump 18, leaving Yoshi's egg 14 (PlYs, PlKb attributes) and leaving
    the respawn platform 120 (RebirthWait, or Rebirth itself: an input held as Rebirth ends
    drops the fighter in the frame RebirthWait begins, so the replay never shows it), and
    throughout Rebirth and RebirthWait. The game flickers the model
    white meanwhile (colour animations 9 and 10; RAM agreed with those timers on 673 of 673
    frames). On Watch Lite's flat silhouettes a flicker was hard to see, so Watch Lite draws a
    steady outline (`invincible.js` OUTLINE) around the fighter for as long as it lasts and
    keeps its fill the player's colour (owner's call). A move's own intangibility (colour
    animations 1-3) is not drawn.
- Movement dust (`movementDust.js`) comes from the fighters' own action scripts
  (`tools/liteaudit/dust/`): effect commands 0x28 and 0x37 (ftaction.c) with the
  dust ids 0x3FF dash (EfCoData model 5 + generator 9), 0x401 / 0x400 run turn and
  brake, 0x402 jump, 0x403 double jump, 0x404 landing (model 24 + generator 10),
  0x407 aerial and special-fall landing, 0x3FE steps (efasync.c), in every state of
  every vanilla fighter that has them (so rolls, getup rolls and ledge options
  bring theirs too):
  - `node tools/liteaudit/dust/pick.mjs --index <replay index> --out <targets.json>`
    picks one clean frame per kind (the state entered, the other fighter far away).
  - `python tools/liteaudit/hit_effects/record.py --targets tools/liteaudit/dust/samples.json --out <dir> --pre 3 --post 50 --shots 40`
    records them (the hit effects' recorder).
  - `python tools/liteaudit/dust/build.py --rec <dir>` writes `data/movementDust.js`:
    per fighter and state the commands' action-frame times (a shared table plus
    each fighter's differences), and per kind and frame the shapes Watch Lite
    draws, in its own style (no game art in the data): each recorded particle
    (through its app SRT) and each part of the two models (posed from RAM, TEV or
    colour-map blend, alpha by the texture's blend track evaluated as
    HSD_FObjInterpretAnim does) measured into a soft ellipse with the same alpha
    mass, centre and spread and colour, or a ring where it is hollow (the double
    jump's). A command runs on the first frame of a
    state's run whose Slippi action frame has reached its time; a run restarts when
    the state changes or the action frame goes back (a dash dance, a run's loop).
    The dust stays where it spawned and is mirrored by facing. Floors whose material swaps landing dust for a stage effect
    (a few on Fountain of Dreams, Pokemon Stadium, Icicle Mountain;
    mpLib_80056AC4) still get the dust.
- Both round and serialize as JavaScript does (`Math.round`, `JSON.stringify`),
  so a rerun on the same ISO rewrites the data file byte for byte.

Per-worker results and the remaining fail-closed histories are in
`app/scratch/liteaudit/c2{0..9}/REPORT.md` and `c30/REPORT.md`.

## Side by side with the game (`sidebyside/`)

The checks above measure numbers; they cannot say the picture looks like
Melee. For anything Watch Lite draws, the evidence is the same replay frame
captured in Slippi's playback Dolphin, placed beside Watch Lite's render with
the camera matched to the game's, and judged by a fresh-context reviewer.
Pilot about 30 pairs before any larger wave.

### Prerequisites

- Windows. The capture reads Dolphin's memory and grabs its window through Win32.
  Run from the repository root with `app/venv` (Pillow and the backend's
  dependencies), Node 20+ and `app/frontend/node_modules` installed (esbuild
  bundles the paint modules).
- Slippi's playback Dolphin, as Slippi Launcher installs it
  (`tracker.replays.dolphin_config.playback_dolphin_path()`, normally
  `%APPDATA%/Slippi Launcher/playback/Slippi Dolphin.exe`).
- The vanilla NTSC 1.02 ISO the app recorded (`vanilla_refs.known_vanilla_iso()`),
  or `--iso PATH`. Playback runs that ISO, so only vanilla fighters and stages can
  be captured. The picker takes only two-player games with vanilla characters.
- A replay folder, `--replays`. The index
  reads the `.slp` files in it and in its direct subfolders (Slippi's monthly
  folders), never deeper. Slippi 3.18+ replays are tried first (they carry stage
  events and item owners), then older 3.x.
- The animation zips the app downloads (`%LOCALAPPDATA%/SSBM Nucleus/storage/nucleome/anim_zips`),
  and Chrome or Edge for the headless render (`--chrome EXE` to choose).

### One command

```powershell
app/venv/Scripts/python.exe -B tools/liteaudit/sidebyside/run.py --replays <replay folder> --types shine,stages,items --n 30
```

It picks the frames, captures each in playback Dolphin with the frame check,
and composes the labelled pairs. `--types` takes any of:

| Type | Frames |
|---|---|
| `shine` | Fox's and Falco's reflector: held (grounded, both facings, airborne), first frames, turning, the reflect flash |
| `stages` | Battlefield, Dream Land, Fountain of Dreams platforms (moving, highest, sunk), Stadium transformations and its four forms, Yoshi's Story Shy Guys and Randall, Corneria and Venom with and without Arwing lasers, Onett cars |
| `items` | Blaster shots (fresh, angled, reflected, last frame), fireballs, missile, charge shot, turnip (thrown and held), Thunder, arrows, needles, the Ice Climbers' ice, PK Thunder |
| `throws` | Forward and back throws, Marth's, Sheik's and Fox's throws, Donkey Kong's cargo carry, Yoshi's egg |
| `effects` | Fire Fox and Fire Bird (charge and travel), the revival platform, Bowser's Whirling Fortress shell, Falcon Punch |
| `shields` | Tilted up, sideways and down, worn down, light shield, Yoshi's shield |
| `fighters` | Bodies of Game & Watch, Marth, Roy and Ganondorf idle, running, falling, in the air |
| `swords` | Sword trails: Marth's aerials, smashes, tilts and Dancing Blade (both facings), Roy's, Link's and Young Link's swings, a few frames into the trail |
| `ko` | KO blasts off the left, right and bottom blast zones: the first flash, the flame after it, its end, a player on port 3 or 4 |
| `respawn` | The respawn: coming down on the platform, waiting on it, invincible after it (on, 4 and 8 frames off, a second in) and its end |
| `starko` | Star KOs flying into the background, and the twinkle |
| `screenko` | Screen KOs coming at the camera, on it, falling away |
| `flash` | Invincibility on ledge grabs (CliffWait +2, +9, +13, over), throws and wall bounces |
| `dust` | Movement dust: dash starts (just spawned, a few frames on, fading), run turns and brakes, jumps, double jumps, landings, aerial and wavedash landings, run steps, rolls, ledge options; the close-up centred on the puff |

The choice is mechanical: newest replay first, each replay used once, never
picked by looking. Types take turns, so every requested type is represented;
once every definition of a type has a frame, the next round finds each in
another game (ids `-2`, `-3`...). `--only fox-shine-air,onett-edge` picks named
targets; `--exclude <old run>/targets.json` keeps earlier runs' games out, for a
new wave. The definitions are the `DEFS` table in `pick.mjs`; add new ones there.

Each run gets a folder, `app/scratch/liteaudit/sidebyside/<date>-<time>/` (or `--out`):

```text
targets.json, targets-ext.json  the picked frames, and the replay's own truth around each
shots/<id>.png, <id>.json       the game frame, and what RAM held at it (frame check,
                                camera, items, collision, Fox/Falco effect objects,
                                sword-trail rings)
pairs/NN-<id>.png, index.json   the labelled pairs (frame_exact per pair)
wl-pairs/                       Watch Lite's renders (full view, then the close-up)
REVIEW_BRIEF.md                 the reviewer brief, filled in for this run
run.log
```

`app/scratch/liteaudit/sidebyside/cache/` keeps the replay index (only new
replays are read on a rerun), the animation packs, the browser profile and
`paintlib.js`, which is rebuilt from the live source on every compose.

The renders load the hit sparks' hitbox tables (`data/hits`) as the app does,
and on Yoshi's Story draw Randall as the app does (Watch Lite's own cloud).

After a Watch Lite fix, redraw the same frames without Dolphin:

```powershell
app/venv/Scripts/python.exe -B tools/liteaudit/sidebyside/run.py --out app/scratch/liteaudit/sidebyside/<run> --from compose
```

`--src <worktree>/app/frontend/src` bundles another tree instead, such as an
older commit, for a before and after. Each step also runs alone (`index.mjs`,
`pick.mjs`, `prep.mjs`, `capture.py`, `build.mjs`, `compose.py`; usage is at
the top of each). `node seq.mjs <run>` prints the shine targets' effect objects
frame by frame around the shot.

### How a pair is made

- **Frame check.** Playback starts about 150 frames early and runs until it is
  5 to 45 frames short. Then the game is frozen (`shared/ingame/framestep.py`)
  and stepped one logic frame at a time to the target. The capture fails if the
  match frame counter lands anywhere else. The live fighters (x, y, action
  state, action frame) are then matched against the replay's own values from
  60 frames before to 30 after. The best match must be the target frame; in
  practice its cost is 0.0. The pair's header prints both. A mismatch prints
  FRAME CHECK FAILED in red and is marked in `index.json` and in the brief.
- **Camera.** The game camera (view matrix, field of view, aspect) is read from
  RAM. The shot is shown at the game's 73:60 aspect, so one world unit is as
  wide as it is tall, as in Watch Lite. Watch Lite is painted by its real paint
  modules (`litePaint.js` and the rest, bundled unchanged) with a fixed camera on
  the same world point at the same scale. Objects off the stage plane do not
  line up exactly, because the game uses perspective. A small subject (shine,
  items, a fighter small in frame) gets a close-up row of the same boxed area on
  both sides.

### One Dolphin at a time, and timing

The capture holds the harness Dolphin lock (`shared/ingame/dolphin_lock.py`)
for the whole capture step. If another tool holds it (melee-harness,
`frameshot.py`, `replay_dump.py`, `stage_dump.py`), the capture queues for up to
`--wait` seconds (default 1800). Never run two captures at once. The capture
only kills the Dolphin PID it started.

- Index: about 2 minutes the first time for the owner's 25,000 replays; after
  that, seconds.
- Pick: seconds to a few minutes. It derives candidate replays, up to 400 per
  definition, until a frame qualifies.
- Capture: about 11 to 15 s per frame. A 70-frame wave took 14 minutes.
- Compose: about 2 s per pair.

A 30-pair pilot takes about 10 minutes end to end.

### Handing the pairs to a reviewer

- The reviewer must have fresh context: an agent or person that did not build,
  fix or pick what it judges. Give it `<run>/REVIEW_BRIEF.md` as its whole
  brief. The brief lists every pair, what to look at, what is out of scope and
  the verdict format (`NN-id | OK`, `| WRONG | what, where`, `| UNCLEAR | why`).
- It opens every PNG at native resolution. Pairs are about 1,600 px wide; a
  contact sheet or thumbnail hides the errors this check exists to catch.
- Fix after each wave, rerun `--from compose` on the same frames, and have a new
  fresh reviewer judge again. Then pick new frames with `--exclude`.
- The template is `sidebyside/review_brief.md` (placeholders `{count}`,
  `{pairs_dir}`, `{pair_list}`). Its out-of-scope list is the owner's call; do not
  report:
  - Watch Lite's flat style (flat colours, no shading, textures, lighting, backgrounds, HUD);
  - perspective (background parts shift, sizes differ slightly with depth);
  - capes, hair, tails and dresses;
  - thrown-victim poses (whether the victim is drawn, and where, still counts);
  - small effects (sparks, hit flashes, trails other than a sword's, small particles;
    movement dust is in scope);
  - fighter draw order;
  - custom m-ex characters and stages (unsupported).
