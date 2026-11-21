# `backend/shared/ingame/` — in-game test engine (SOLO, no CPU, no cursor)

**This is THE way to boot a built ISO and get a fighter into a match for any
in-game test** — crash probes, move/side-B tests, screenshots, RAM diagnostics.

It loads the match by **writing the player block directly to game RAM** and
relaxing the "Ready to Fight" gate, so you play **alone (1 player, no CPU)** and
never touch the character- or stage-select cursor.

The native fighter-port rig checks (`rig_preflight`) are in `tools/fighterport/fighter_port/compat/`,
and the dev-only RAM evidence readers (`contacts`, `input_evidence`) and `owned_session` are in
[`tools/ingame/`](../../../../tools/ingame/README.md#ram-evidence-readers-python); none of them ships.

## Why this, and NOT the CPU/cursor method

There is an older path (`tools/ingame/dolphin/` +
`pipe.js cpustep`) that steers the CSS cursor and **adds a CPU** to satisfy
Melee's 2-player start gate. **Do not use it for gameplay/crash testing.** It is:

- **Slower** — a multi-second cursor sweep to click a character + add a CPU,
  with timing-calibrated stick holds that drift per build.
- **A confound** — the CPU walks over, attacks you, and moves the camera, which
  corrupts move/crash repros (e.g. a CPU hit interrupts the move you're testing).
- **Fragile** — custom fighters aren't in the cursor grid, so it needs CSS-icon
  coordinates from the build manifest.

The cursor path is only correct when the **CSS/SSS UI itself** is under test
(icon placement, grid layout, menu mods).

> Recurring failure: agents discover `tools/ingame/dolphin/` first, wire up
> `cl_match` + `cpustep`, fight a CPU, and waste a build cycle. If you're here
> to test *gameplay*, use the solo flow below.

> **MCP server:** all of this is also exposed as MCP tools
> (`tools/harness/harness_mcp.py`, registered in the workspace `.mcp.json` as
> `melee-harness`): `boot_match` → `do_move`/`step`/`screenshot`/`poke_dat`
> → `end_session`, plus one-shot `frameshot`/`effect_probe`/`run_ingame_test`.
> If those tools are available in your session, prefer them over hand-rolling
> the flow below. See `docs/dev/INGAME_TESTING.md` § MCP server.

## Playable UI previews

`runner.run_test(..., interactive=True, stop_event=event,
on_interactive_state=callback)` opts into a playable preview. Automated checks
and frame-exact captures retain their existing flow by default. An automated
`run_test` and the `capture_*` functions also take `stop_event`: a set event
ends their Dolphin lock queue, boot and menu waits at once (the app passes its
job's stop, so a Cancel does not wait out a timeout). The `capture_*`
functions also give their Dolphin a `deadline` (`DolphinBoot(deadline=seconds)`):
a Dolphin still running then is ended, the capture returns `timedOut: True`
with a reason that says so, and its own cleanup releases the Dolphin lock.
The waits in a run have time limits; the deadline is for a call that blocks,
which has none. An automated `run_test` sets one too (300 seconds plus 90 per
check and the watch time asked for) and a run ended there returns verdict
`error` with `timedOut`, never `crashed`: the death its check saw was the
harness's. Playable previews and the harness sessions set no deadline.
Interactive
mode copies the user's real port-1 controller configuration and reserves port 4
for menu automation; it does not detect or remap physical controller ports.
Configure port 1 in Slippi first. The selected fighter/costume loads on
Battlefield; stage previews load Mario on the selected stage. One-skin DAS
preview builds must set `defaultVariant=True` and install the selected skin as
the default, so selecting it does not depend on a held automation button.

After loading, player slot 0 polls pad 0 and the automation pipe is neutral.
The preview stays open until `stop_event` is set or Dolphin closes, including
when the game is paused. Callback dictionaries contain `phase`
(`loading`, `playing`, `stopped`, `error`), `controllerPort: 1`, and `message`.
Normal completion reports `interactive: true`, `success: true`, and verdict
`stopped` or `closed`; it is never an automated test PASS. Only the isolated
profile is edited. Copied absolute memory-card paths are cleared so reads and
writes use that run's copied `User/GC` cards. This flow requires packaged controller/GPU acceptance;
synthetic tests verify routing, configuration preservation, and lifecycle.

## Shared pose and visibility evidence

`stage_state.capture_stage_state(d)` reads the engine's `StageInfo.grkind`
within the caller's game-counter bracket, preserving the signed word and raw
bytes. Ground kind differs from SSS icon and internal stage-selection IDs;
unknown and reset (`-1`) values are retained without an inferred stage name.
This is a GALE01 layout reader, not proof of a stage asset's identity. Damage
probes now include it; older captures without this field remain unobserved.

While debugger-frozen, use `Player.pose(joint_count, secondary=True)` and
`Player.visibility(expected_count=...)` instead of copying fighter/JObj offsets
into a probe. The count must come from the exact costume being tested. These
read-only helpers in `shared.ingame.pose` preserve full world matrices, raw animation
time, primary/secondary local SRT, rotation flags and AObj phase. They validate
MEM1 bounds and fail on short reads or invalid non-null pointers. Null optional
secondary joints/AObjs remain `None`, distinct from a valid frame zero.

Pose schema `hsd-jobj-local-srt-v2-xyz` reads rotation at `+0x1C`, not `+0x20`.
`rotation_kind` determines whether the four stored words mean quaternion XYZW
or Euler XYZ plus unused storage. `rotation_words` preserves the raw bits;
nonfinite unused W storage is JSON `null`, but nonfinite active values fail.
Historical schema-less Y/Z/W captures still require their explicit legacy
auditor; this helper does not relabel or repair old evidence.

Visibility capture records DObj count/pointers/flags and model-state prev/idx
bytes. It does **not** issue a visibility verdict: render passes can temporarily
hide all DObjs, so use drawn-frame witnesses and images. Multiple reads are not
an atomic snapshot; keep the fighter update frozen during capture.

Portable regression checks need no game files or emulator:
`python -B -m unittest discover -s tests -p test_ingame_pose.py -v`.

When a campaign reveals a repeated harness defect, fix the shared helper and
add a regression reproducing that failure before copying the fix into another
pilot. Keep source fidelity, packed-byte playback, native state transitions,
and rendered visibility as separate evidence; one passing layer does not
establish the others.

## The solo flow (copy `backend/devtools/research/fsm_crash_probe.py`)

`fsm_crash_probe.py` is the worked template.
Run from `backend/` with plain `python` (uses the backend's deps).

```python
from shared.ingame.boot import DolphinBoot          # isolated throwaway Slippi User dir
from shared.ingame.melee_mem import Dolphin          # RPM read/write of MEM1
from shared.ingame.melee_pipe import Pipe            # controller input over the named pipe
from shared.ingame.melee_css import Cursor
from shared.ingame.melee_sss import StageCursor, INTERNAL_STAGE_ID
from shared.ingame.observe import wait_in_game, wait_game_frames
from shared.ingame import nav, match_setup

boot = DolphinBoot(str(iso), None, str(runs_root), log=print)
boot.prepare(); boot.launch()
boot.wait_for_pipe(timeout=45)
d = Dolphin(boot.pid)
while not d.locate(): ...                     # find MEM1 base

match_setup.patch_one_player(d)               # CSS gate cmpwi r4,2 -> r4,1 (allow solo)
p = boot.open_pipe()                          # controller pipe, retried across Dolphin's re-arm windows
nav.nav_to_css(d, p)                          # Slippi online menu -> offline VS CSS
nav.wait_css_ready(d, Cursor(d, p))
match_setup.force_time_infinite(d)            # Time / no limit, so a solo match sustains

CKIND = 0x1A                                  # external CSS id; FIRST added m-ex fighter = 0x1A
match_setup.write_solo_player(d, CKIND, 0)    # write port-0 = fighter, ports 1-5 = NA
match_setup.warp_to_stage_select(d)           # memory warp CSS -> SSS (no cursor)
sc = StageCursor(d, p); sc.wait_for_stage_select()
match_setup.write_solo_player(d, CKIND, 0)    # re-assert after the warp
sc.force_select(INTERNAL_STAGE_ID["battlefield"])   # direct stage-id write, no SSS cursor

wait_in_game(d); wait_game_frames(d, 200)     # past READY/GO!
# ... now drive inputs + sample state ...
boot.cleanup()
```

### `ckind` (which fighter)
`ckind` is the **external CSS fighter id**. Vanilla = 0x00–0x19. **m-ex added
fighters start at 0x1A** (the first added fighter = 0x1A, the next 0x1B, …). For
a build whose only custom fighter is Metal Mario, `ckind = 0x1A`. Confirm with
`mexcli list-fighters <project.mexproj>` (the `externalId`).

### Driving inputs (`Pipe`)

The default remains the named pipe. On a machine that runs several harness
Dolphins (`harness-dolphin.json` beside the lock files; INGAME_TESTING.md,
"Several Dolphins on one machine") each slot has its own copy of Dolphin with
pipes of its own, `DolphinBoot` runs the copy of the slot it was given, and
`melee_pipe` follows that slot's pipe prefix: nothing to do in the caller.
Without copies, Windows parallel workers opt into
`NUCLEUS_DOLPHIN_INPUT=memory` with more than one slot. The existing
`boot.wait_for_pipe()` / `boot.open_pipe()` API then waits for the emulated
pad hook and returns a command-compatible memory controller. Menu navigation,
move recipes and retail debug frame stepping use the same calls. Do not open
`Pipe(...)` directly in a parallel worker. See
[the backend switch and desktop verification](../../../../docs/dev/INGAME_TESTING.md#memory-input-for-parallel-windows-workers).

Open the pipe with **`boot.open_pipe()`** (not `Pipe(...)` directly): Slippi
Dolphin tears its controller pipe down and re-arms it on controller refreshes
(game boot / stage load), so a single-shot open can land in that gap and die with
`CreateFile(...slippibot1) failed: 2`. `open_pipe()` retries across the gap and
bails fast if Dolphin actually exited.

`press/release/tap(btn,hold)`, `main(x,y)` / `c(x,y)` control & C sticks
(0.0–1.0, 0.5 center; **y=1.0 UP, y=0.0 DOWN** — libmelee's convention, per
melee_pipe.py; an earlier version of this line had it inverted and caused
up-B/down-B mixups), `tilt(x,y,hold)`, `center()`, `neutral()`, and
`frame([...])` for one raw atomic frame.

A **side-special (side-B)** = stick to a side + B, atomically:
```python
p.frame(["SET MAIN 1.000 0.500", "PRESS B", "FLUSH"]); time.sleep(0.1)
p.frame(["RELEASE B", "SET MAIN 0.500 0.500", "FLUSH"])
```

### Detecting a crash / hang
- **Hang / assert halt** (e.g. m-ex `assertion "0" failed ... item not
  initialized`): the global frame counter `0x80479D60` stops advancing while the
  game stays in-scene. Sample it; >2–3 s frozen = hung.
  ⚠ **The scene flags cannot detect this.** `wait_in_game()` reads only
  `major/sub`, and a build that hangs during the stage load leaves those
  reading in-game — it logs `in-game after 0.0s` and every later screenshot is
  the same stale frame. Any loop that boots once and captures many things MUST
  gate on the frame counter (`wait_game_frames`, or
  `Observer.watch_health` / `frameshot.liveness`) before it trusts a capture.
- **Hard crash**: `d.alive()` false or MEM1 unreadable.
- Per-player ftData: `gobj = u32(0x80453080 + 0xE90*port + 0xB0); ft = u32(gobj+0x2C)`;
  action state at `ft+0x10`, anim frame f32 at `ft+0x894`.

## Frame-exact move screenshots (`frameshot.py` + framestep/gamestate/moves)

Collision graphics: `frameshot --debug-draw overlay` shows retail attack spheres
and hurt capsules over the model. `--debug-draw collision` hides the model;
`off` restores it. Live MCP sessions support `boot_match debug_draw="overlay"`
and the `debug_draw` tool with the same modes and optional `ports` list.
Python probes can call `shared.ingame.debug_draw.set_debug_draw(d, "overlay")`.
These are live instance flags, so reapply after loading another match. This
uses Melee's actual collision renderer; screenshots do not invent hit geometry.

**"Screenshot Marth's fair on frame 4"** is a one-liner (run from `backend/`).
Full doc: [docs/dev/INGAME_TESTING.md](../../../../docs/dev/INGAME_TESTING.md#frame-exact-move-screenshots-devtoolsframeshotpy).

```
python devtools/frameshot.py --char marth --move fair --frame 4
python devtools/frameshot.py --char falco --move dair --frames 1-8      # contact sheet
python devtools/frameshot.py --char 0x1A --move sideb --frames 1,5,9 --iso <built.iso>

# many moves in ONE boot (per-character sweeps, e.g. the extras audit) --
# the fighter settles to idle and re-centers between moves:
python devtools/frameshot.py --char marth --shot fair:1-8 --shot fsmash:10 --shot jab:3

# many CHARACTERS/COSTUMES in ONE boot instead of a boot per costume --
# between targets it quits to the CSS (nav.reset_to_css), memory-selects the
# next fighter and warps back to the stage. Writes <out>/<id>/*.png +
# batch.json (judge a target by its manifest STATUS, never by a file glob):
python devtools/frameshot.py --batch targets.json --closeup --plain-bg 404040
```

Boots the solo engine onto FD (default), then TAS-steps the game one logic
frame at a time:

- **`framestep.py`** — retail Melee's scene loop gates every logic frame on a
  debug-pause bitmask (`0x80479D68` bit0 = freeze, `0x80479D6A` bit0 = run one
  frame). We poke those bits directly via RPM: full-speed boot, zero-drift
  stepping, no pause HUD (rendering continues, so PrintWindow still captures).
  Do NOT write the step byte back-to-back yourself — if a second request lands
  while the engine's shadow byte (`0x80479D6B`) is still set, both wedge at 1
  and the game **free-runs with the freeze bit still set**. `step()` handles
  the clear/settle handshake.
- **`gamestate.py`** — fighter state reader (action state id/name, anim frame,
  pos, facing, airborne, internal `kind()`); `motion_states.py` = all 341
  universal state names generated from the decomp. Frame numbers follow
  community frame data (frame 1 = first frame in the move's action state; for
  vanilla chars the anim-frame float matches the move frame exactly — a
  built-in sanity check). Also `Follower`/`nana_of()` — the Ice Climbers'
  Nana, and `hide()` to drop her from the render passes (she spawns
  COINCIDENT with Popo, so an un-hidden ICs capture is two bodies in one
  space and neither can be graded).
- **`moves.py`** — input recipes for jab/tilts/smashes/aerials/dash attack/
  grabs/**throws + pummel**/specials/shield/run/taunt. Inputs are set while frozen, so they
  register as fresh presses on exactly the next stepped frame. ⚠️ **The pipe
  stick scale is not the engine's**: `in_game = (pipe * 255 - 128) / 80`, so
  `SET MAIN 0.800` is 0.95 in game — over the 0.8 smash threshold. Express
  recipes with `moves.stick(v)` in engine units (tilts sit at 0.60); specials
  send stick+B atomically.

  **Throws and pummel are the one family that cannot run solo** (`fthrow`,
  `bthrow`, `uthrow`, `dthrow`, `pummel`): they exist only while an opponent is
  HELD, so they need a bag inside grab range — `boot_match bag=dk bag_pos="6,0"`
  or `frameshot --bag dk --bag-pos 6,0`. The recipe grabs with L+A (a bare Z is
  swallowed by the pipe), waits for **CatchWait (216)** — a whiff never reaches
  it and raises with that hint — then applies a stick direction (a throw needs
  no attack button) or A for the pummel. `park_bag` waits out `DOWNED_STATES`
  as well as hitstun and, if the bag is still lying there, drops it from just
  above the ground: an uncontrolled human port NEVER gets up on its own, so
  without that the second throw of a batch whiffs on a body at the attacker's
  feet.

Gotcha: the throwaway config gets `SlippiOnlineDelay = 0` — Slippi's local
input-delay pipeline runs even offline, adding 2 frames of pipe latency and a
"Delay: 2f" OSD into captures (frameshot patches this; `clean_osd=True` kills
the FPS/memcard overlays).

## The no-CPU memory pokes (`match_setup.py`)
- `patch_one_player(d)` — RPM-patches the CSS start gate at `0x80263064`
  (`cmpwi r4,2` → `cmpwi r4,1`) so a 1-player roster is "Ready to Fight".
- `force_time_infinite(d)` — GameRules `0x8045BF10`: mode=Time, time=0.
- `write_solo_player(d, ckind, color)` — writes the StartMeleeData /
  VsModeData player blocks: port 0 = fighter, ports 1–5 = NA.
- `write_bag_player(d, ckind, color, bag_ckind=0x01, bag_color=0)` — same, but
  port 1 = a punching-bag 2nd HUMAN (no controller: stands still, never
  attacks, never moves the camera — do NOT use a CPU) so ON-HIT-only effects
  are capturable. `gamestate.Bag` parks it in front of the attacker
  (`moves.park_bag`) and confirms hits via Damage* states; frameshot exposes
  it as `--bag [char] --bag-pos dx,dy`, effect_probe as the `"bag"` spec key.
- `warp_to_stage_select(d)` — pokes the scene loop (`0x80479D35`/`0x80479D64`)
  to jump CSS→SSS without the cursor or START gate.

All addresses are NTSC 1.02. See `match_setup.py` for the authoritative list.

## Cached pose matrices at state transitions

`Player.pose` preserves raw local SRT, cached world matrices, and the HSD `JOBJ_MTX_DIRTY` bit as `matrix_dirty` on primary and secondary joints. A late collision-driven state change may update the local pose before every cached world matrix is rebuilt. Keep adjacent samples and compare both local channels and cached matrices before attributing a world mismatch to animation. A dirty bit alone is neither a failure nor an acceptance waiver; never silently discard that frame or force a matrix update during a read-only probe.

Shield/contact batches must also declare resource readiness. `MoveRunner.reset()` does not refill shield health: wait for native recharge between independent full-health trials, or explicitly record a depleted-shield scenario.

For a suspected render-cache lag, retain paired raw poses before and after a render-counter advance, bracket both reads with game/render counters, and require unchanged game count and local channels. In the fighterport repo, `incineroar_campaign/probe_guard.py --render-witness` and `audit_render_witness.py` implement this observation without calling `SetupMatrix` or rewriting the pose. Incineroar's first shield-hit frame demonstrated weighted caches updating during rendering with no logic advance. The original failed snapshot remains evidence; a later render observation is a separate measurement.

Collision timing is a different contract: the priority-13 shield test consumes the pre-hit Guard pose, and priority 14 then enters GuardDamage. Collider coordinates left from that already-resolved hit are not evidence of stale collision consumption. Hurtbox consumers refresh lazily through `HSD_JObjSetupMatrix`; shield centre retention during hitlag follows the native physics-reset policy. See the incineroar guard-collision review (ssbmNucleus-fighterport repo) for the exact callsites and limits. Do not generalize this finding into ignoring dirty matrices in other states.
