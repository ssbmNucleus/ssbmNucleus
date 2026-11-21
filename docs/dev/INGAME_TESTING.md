# In-Game Testing (`backend/shared/ingame/`)

Frame-step failures retain before/after/recovery snapshots of the game and render
counters plus pause, request and shadow bytes in the error. These are read-only
diagnostics for distinguishing a game stall from the step handshake; they do
not change the stepping timeout, recovery policy or acceptance criteria.

The in-app "Test in game" engine: a self-contained, **Windows-only** harness
(stdlib + Pillow — no Node, no pywin32, no PowerShell, no extra installs) that
boots a freshly-built ISO in an isolated Slippi Dolphin, drives it to a real
**offline** match, selects the modded character/stage, optionally triggers an
effect move, and reports **PASS / CRASH / HUNG** with screenshots.

Public entry point: `shared.ingame.run_test(...)` (defined in `runner.py`; the package is `backend/shared/ingame/`).

Per-mod UI tests pass `interactive=True`: the selected character/costume loads
on Battlefield, or Mario loads on the selected stage. `interactive.py` keeps the
match open until an explicit stop or the owned Dolphin closes. Manual sessions
do not produce an automated PASS or end on a frame-health timeout.

After `nav_to_css`, playable previews wait for the port-4 automation hand to
exist and remain stable through 90 advancing emulated frames before writing
rules, player data or the CSS-to-SSS transition. The CSS scene flag alone is
too early: initialization can discard those writes. Pointer replacement or
frame-counter reset restarts the interval; unreadable/stalled state times out
after 15 seconds, Stop interrupts the wait, and leaving offline CSS aborts it.
This readiness check does not depend on a connected port-1 controller. Failed
transitions log the observed major/minor scene and name the failed menu step.

## Pose and model visibility captures

Research probes should use `Player.pose(count, secondary=True)` and
`Player.visibility(expected_count=count)` from `backend/shared/ingame/gamestate.py`.
The shared `shared.ingame.pose` reader owns the NTSC 1.02 layouts and read validation;
do not duplicate JObj rotation or model-state offsets in each character pilot.
Supply counts verified from the actual costume, freeze before reading, and
save the schema and unrounded animation time. See `backend/shared/ingame/README.md`
for optional-pointer, quaternion-storage and legacy-capture handling.

Visibility flags alone are not a rendered-image verdict. Likewise, agreement
between live matrices and a packed animation does not prove that the author
decoded the source correctly. Source parity needs an independent raw-source
reference, including fractional frames; author and verifier sharing one sampler
can agree on the same defect. Preserve failures and identify each evidence layer
explicitly instead of turning a missing observation into a PASS.

## Key Properties

- **Isolated Dolphin**: `boot.py` never launches the user's real User dir. It
  makes a temp copy of their `Config/` + Slippi login, patches it (pipe
  controller on port 1 for automated checks, windowed, no confirm-stop) and boots Dolphin with
  `-u <temp dir>`. The user's netplay setup is untouched.
  Interactive previews preserve the real port-1 device and mapping, use a menu
  automation pipe on port 4, and route the solo fighter to pad 0 for manual play.
  They do not detect controllers or select another port.
- **Closed-loop control via RAM feedback**: menu navigation reads the live
  scene state from emulated RAM rather than relying on blind timing.
- **Never goes online**: `nav.py` only succeeds when it confirms the offline
  VS character select screen, and hard-aborts (holding B to back out) if it
  ever detects the online CSS scene (major `0x08`). The harness can never
  enter matchmaking or waste a real player's time.
- **One test at a time**: two test jobs would fight over the screen and pipe;
  the blueprint enforces a single running test. If the user already has a
  Dolphin emulator window open, the engine waits and streams a progress message
  explaining why it needs that window closed before it continues.

## Module Map

| Module | Role |
|--------|------|
| `runner.py` | Orchestrator. Builds a test PLAN from the build manifest, runs each check, aggregates the verdict, always cleans up Dolphin + temp User dir |
| `interactive.py` | Manual preview selection and port-1 handoff; cancellation-aware setup and a persistent offline session until Stop or process exit |
| `boot.py` | Locate Slippi Dolphin, create the throwaway User dir, launch the ISO. Also exposes `launch_real()` for playing builds in the user's real Slippi (used by bundles/xdelta "Play" endpoints) |
| `boot_errors.py` | Read known graphics-failure dialogs from the retained live Dolphin process, with bounded Win32 control reads; never dismiss or modify dialogs |
| `nav.py` | Drive the post-boot menus to the offline VS CSS by scene-state feedback; abort on the online scene |
| `melee_mem.py` | Read live emulated GameCube RAM (finds the MEM1 region tagged `GALE01` in the Dolphin process, like Dolphin Memory Engine) |
| `melee_pipe.py` | Send controller input over Dolphin's named pipe (one persistent connection, libmelee-style) |
| `melee_css.py` / `char_select.py` | Closed-loop character select (cursor driven by RAM position feedback; grid data in `grid.json`) |
| `melee_sss.py` | Closed-loop stage select |
| `match_setup.py` | In-match setup and RAM patches for solo 1-player starts, no timer, direct player block writes (`write_solo_player`, plus `write_bag_player` for a punching-bag 2nd player), and CSS-to-SSS warps |
| `observe.py` | Crash/hang detection: process death or MEM1 gone → CRASH; frozen frame counter → HANG; otherwise healthy |
| `screenshot.py` | Capture Dolphin's render window via `PrintWindow(PW_RENDERFULLCONTENT)` (works even when occluded/background), with a desktop-grab fallback |
| `capture.py` | Live screenshot capture for stages, pause-screen mods, and batched DAS variants |
| `embed.py` | Tracks the retained test process/session, exposes its exact capture HWND, and presents it behind the app after the first video frame; retains legacy positioning for Watch Mods |
| `framestep.py` | TAS-style freeze + single-frame stepping via the retail debug-pause bits (see [Frame-Exact Move Screenshots](#frame-exact-move-screenshots-devtoolsframeshotpy)) |
| `gamestate.py` | Fighter state reader: action state id/name, anim frame, position, facing, airborne, percent; `Bag` subclass = the punching-bag 2nd player (park-in-front + in-damage hit check) |
| `motion_states.py` | All 341 universal action-state names, generated from the melee decomp enum |
| `moves.py` | Frame-exact input recipes (jab/tilts/smashes/aerials/dash attack/grabs/throws+pummel/specials/taunt) executed against a frozen game |
| `datram.py` | Locate a loaded DAT file's image in MEM1 and poke file offsets LIVE — no ISO rebuild/reboot between color experiments. One boot = dozens of byte→visual mapping probes (workflow + gotchas: `docs/dev/EXTRAS_AUDIT.md` "Fast mapping" section) |
| `devtools/effect_probe.py` (in `backend/devtools/`, not `shared/ingame/`) | Spec-driven live-poke probe tool: `python devtools/effect_probe.py <spec.json>` runs one boot, locates every DAT named in the spec via `datram.py`, applies/verifies/restores pokes per experiment, captures per-move frame lists, and recenters between movement moves; spec key `"bag": {"char": "dk", "dx": 8}` adds the punching-bag 2nd player for on-hit effects. The generalized replacement for one-off drivers like `datram_probe.py`/`datram_probe_ca.py` — write a JSON spec instead of a new script. `--dry-run` parses the spec and prints the plan without booting. Example: `backend/probes/effect_probe.example.json` |

## Public Python API

The harness is normally reached through the Flask blueprint, but these are the
stable Python entry points:

```python
shared.ingame.run_test(
    iso_path,
    slippi_path,
    runs_root,
    manifest=None,
    emit=None,
    log=None,
    observe_seconds=9,
    hires_textures=False,
    load_seed=None,
    interactive=False,
    stop_event=None,
    on_interactive_state=None,
)
```

`emit(stage, percentage, message)` receives progress updates. The return value
is a result dict with `verdict`, `pass`, `reason`, `checks`, `screenshot`,
`drove`, and `online_aborted`.

With `interactive=True`, pass a `threading.Event` for Stop and a callback receiving
`{phase, controllerPort: 1, message}`. `playing` means manual play is ready;
`loading`, `stopped`, and `error` describe the other transitions. Normal completion
returns `interactive: true`, `success: true`, `verdict: "stopped" | "closed"`;
`pass` remains false. Errors return `success: false` and a reason. The default
automated callers and frame-exact capture paths retain their existing behavior.

Interactive stage-skin builds call `build_stage_skin_iso(default_variant=True)`:
the selected DAT replaces the temporary DAS folder's `vanilla.dat` instead of
requiring a held button on the player's controller. The Vault archive is untouched.

Known graphics startup failures return `verdict: "error"`, `pass: false`, and
`error_code: "graphics_initialization_failed"`, with the native failure text in
`reason`. Startup checks run during controller, RAM, and menu waits. The copied
profile uses a separate render window but preserves the selected video backend
and graphics adapter. A generic Direct3D device-creation error alone does not
identify an unsupported GPU or its underlying cause.

If offline menu navigation fails, healthy RAM cannot produce a PASS. The result
keeps `pass: false`, the screenshot and a `boot_health: {verdict, reason}`
diagnostic; healthy observation becomes an `error` verdict because the requested
checks did not run. A boot-health check after confirmed offline CSS remains valid.

Other direct entry points:

- `shared.ingame.capture.capture_stage(...)` - one clean live stage preview.
- `shared.ingame.capture.capture_pause(...)` - live preview for a pause-screen mod.
- `shared.ingame.capture.capture_stage_batch(...)` - many DAS stage previews in one
  boot where possible.

  All three captures give their Dolphin a deadline, counted from its launch:
  300 seconds, plus 5 per sweep camera, a requested Stadium form's own budget,
  or 60 per batch variant (`deadline=` overrides it). A Dolphin still running
  then is ended through the handle the boot kept. The capture returns
  `timedOut: True` and the reason "Dolphin stopped responding, so the capture
  was ended after N seconds."; a batch keeps the shots it already took, and its
  caller's retry treats the rest as a crash. This exists because the waits in a
  capture have time limits but a call that blocks has none: on 2026-11-10 a
  pause capture held its Dolphin and the machine-wide lock for three hours.
  An automated `run_test` has the same deadline (300 seconds, plus 90 per
  check and the watch time asked for; `deadline=` overrides it). A run ended
  there returns verdict `error` with `timedOut: True`, never `crashed`, because
  the death its check saw was the harness's own. Playable previews and harness
  sessions have no deadline.
- `shared.ingame.boot.launch_real(slippi_path, iso_path)` - launch a build in the
  user's real Slippi Dolphin for normal play.
- `shared.ingame.boot.iso_dir_from_slippi(slippi_path)` - resolve the user's ISO
  library folder from Dolphin.ini.
- `shared.ingame.embed.capture_target()` / `present_capture(...)` - identify and present
  the current retained test process's render window for the Windows live preview.
- `shared.ingame.embed.position(x, y, width, height)` / `shared.ingame.embed.park()` - legacy
  overlay positioning, retained for other window-controller callers.

### Windows live preview

Nucleus Randall can now launch these interactive single-mod sessions through
`test_in_game`. The chat card reuses `InGameTestRunning` and `DolphinEmbedPanel`;
its status/Stop endpoint verifies chat ownership. Exported costume handles can be
tested directly without saving a vault copy. Capture preparation can specify an
expected native session, preventing a stale card from attaching to a newer test.
This does not expose automated moves or game vision to the chat model. See
[RANDALL.md](RANDALL.md#7-in-game-tests-test_in_game).

Electron's `viewers/dolphin-capture.js` obtains the authenticated backend target and
matches its exact HWND against `desktopCapturer` window sources. Main-frame IPC
issues a short-lived media lease; media permission requires that owner/frame.
`DolphinEmbedPanel` displays the selected stream in a contained HTML video. The lease also carries
the target's `client` geometry (refreshed by each check); Randall's workbench In game tab
(`WorkbenchGameTest`, `captureCrop`) uses it to show only the game at 4:3, without Dolphin's title bar. There
is no screen/title/first-source fallback, audio capture, or JPEG polling loop.

The test runner configures a 640×480 render window before launch, matching its
diagnostic screenshot cap. No window presentation occurs until the first decoded
video frame. Then the retained renderer and its GUI sit behind Nucleus, without
render resizing, minimization or offscreen parking. The **Open Dolphin window**
button and failed-capture cleanup restore a separate window. Session changes,
track termination, sustained source muting and component cleanup end the media
stream. Unchanged or paused images are valid; Chromium suppresses duplicate frames.
Pipe control, RAM navigation and frame-exact screenshot timing remain independent
of live video. Watch Mods retains its separate existing window-controller path.

This remains a captured native window: a very small Nucleus window may not fully
cover Dolphin behind it. The Electron 44 synthetic-window smoke verifies frames
continue while covered; it does not prove every Dolphin graphics backend or GPU
captures correctly. Keep the separate-window fallback for real GPU acceptance.

Related build helper:

- `backend/projects/install/test_build.py` builds throwaway one-mod ISOs for the blueprint's
  single-mod endpoints, including costumes, custom characters and skins, custom
  stages, DAS stage skins, pause-screen mods, and batched DAS screenshot ISOs.
- `backend/projects/install/pristine_base.py` keeps the untouched m-ex project each of
  those builds copies (`storage/test-builds/pristine-base/base-<key>/`). `mexcli create`
  runs once per vanilla ISO and MexCLI (the key hashes both), into `.building-<id>/`,
  and becomes the base with one rename after it succeeds; a Stop kills it and renames
  the folder to `.trash-<id>` for the next build to delete. The base's record counts its
  files and bytes; a base that no longer matches is rebuilt, not copied. Every build
  copies the base (real copies, never hard links) into its own `proj_<id>`, installs
  its mod there and deletes the copy, so no test sees another.

## Smart Test Plan

`runner.build_plan(manifest)` derives the minimal set of checks from a build
manifest. A full modpack (all six mod types in one ISO) is covered by just two
matches:

- **A)** the custom character on the custom stage → covers character + stage + menu background
- **B)** the modded fighter's costume on the DAS stage (holding its button), then the effect move in-match → covers costume + DAS + effect

Single-type builds get one matching check. Anything that can't be driven
specifically falls back to a **boot-health watch** (boot → reach the CSS so the
mod's data loads → watch process/frame health), which still catches most
broken builds.

Verdict severity (worst wins): `healthy < ended < never_started < hung < crashed < error`.

## Manifest Fields

`run_test` can run without a manifest; that becomes a boot-health check at the
offline CSS. A manifest lets it select the exact content to exercise. A modpack
manifest can include several of these keys at once:

| Key | Required fields | What it drives |
|-----|-----------------|----------------|
| `costume` | `{ "fighter": "Fox", "colorIndex": 4 }` | Selects a vanilla fighter and costume slot |
| `character` | `{ "name": "Sonic", "cssIcon": { "x": ..., "y": ..., "index": ..., "fighter": 0x1A } }` | Selects a custom m-ex fighter by placed CSS icon; `fighter` enables the faster direct memory path |
| `customStage` | `{ "name": "...", "sssIcon": { "page": 1, "x": ..., "y": ..., "stageId": 0x40 } }` | Selects a custom m-ex stage by internal id when known, otherwise by SSS icon |
| `das` | `{ "stage": "battlefield", "button": "X" }` | Holds a DAS button while force-selecting the stage |
| `effect` | `{ "fighter": "Fox", "move": "neutralb" }` | Starts a match and performs the move that loads the effect |

The runner prefers cursor-free memory selection when the manifest gives enough
IDs to write the player block and force-select the stage. It falls back to the
closed-loop CSS/SSS cursor path when it must verify UI placement itself.

## Frame-Exact Move Screenshots (`devtools/frameshot.py`)

**The tool for "screenshot Marth's fair on frame 4"** — and the workhorse for
auditing per-character content that only shows mid-move (sword trails, effect
recolors, **extras**) against its vault/menu preview. Run from `backend/`:

```
python devtools/frameshot.py --char marth --move fair --frame 4
python devtools/frameshot.py --char falco --move dair --frames 1-8        # contact sheet
python devtools/frameshot.py --char 0x1A --move sideb --frames 1,5,9 --iso <built.iso>

# Many moves in ONE boot (use this for per-character sweeps — the fighter
# settles back to idle and re-centers between moves):
python devtools/frameshot.py --char marth --shot fair:1-8 --shot fsmash:10 --shot jab:3

# Flat gray background + no stage textures, so effect colors read
# unambiguously (Achilles' plain-background code applied as RAM pokes).
# On FD this also kills the stage's drifting background star PARTICLES
# (bank-0x1E psLib generator unlink — fighter effect particles untouched;
# see research/docs-research/fd-star-particles.md):
python devtools/frameshot.py --char marth --move fsmash --frames 9-16 --plain-bg

# Punching-bag 2nd player, so ON-HIT-only effects are capturable (Raptor
# Boost's uppercut burst, PK Fire's pillar, ...). The bag is a HUMAN port
# with no controller: it stands still, never attacks, never moves the
# camera (do NOT use a CPU for this). --bag-pos = units in front of the
# attacker (dx,dy), re-parked every rep; default char dk (big hurtbox):
python devtools/frameshot.py --char falcon --move sideb --frames 14-30 --bag dk --bag-pos 12,0
```

Outputs `<char>-<move>-f<NN>.png` plus a `.json` sidecar per move (state name,
anim frame, position for every capture) into `--out`
(default `app/scratch/frameshot/`). `--char` accepts `char_select.py`
names (sheik included) or a raw external id (`0x1A` = first m-ex fighter), so
custom characters work against their built ISO. `--stage` defaults to
`finaldestination`. Exit code 0 = every requested frame captured.

### Many CHARACTERS/COSTUMES in one boot (`--batch`, 2026-07-30)

One boot per costume is mostly boot. `--batch` captures a **list** of targets
through a single Dolphin — between targets it quits the match back to the CSS
(`nav.reset_to_css`), memory-selects the next fighter and warps straight back to
the stage, the same loop `shared/ingame/capture.py` uses for DAS stage variants.
`nav.reset_to_css` returns once the CSS is running, which is about a quarter
second after the scene bytes name it: until the CSS's own loop restarts the
frame counter, a stage-select warp is wiped (2026-11-10, when this cost a bulk
stage capture every variant after the first). The stage batch also recovers by
what the game says rather than by assumption: between variants it quits a
running match, backs out of the stage-select screen with B, and leaves a CSS
alone (the quit combo pressed on a menu backs out to the main menu); and its
cursor path presses START first, because the CSS a match returns to still has
the fighter picked and locking it again un-picks it:

```
python devtools/frameshot.py --batch targets.json --closeup --plain-bg 404040 \
                    --iso <built.iso> --out <dir>
```

```json
{"shots": ["idle", "jab:1"],
 "targets": [{"id": "machoke", "char": "falcon",  "color": 5},
             {"id": "hypno",   "char": "drmario", "color": 5,
              "shots": ["idle", "fair:2"]}]}
```

A bare JSON list works too, as does the `"falcon:5"` shorthand; the top-level
`shots` (or `--shot`) is the default for targets that don't carry their own.
Every camera/background flag (`--closeup`, `--orbit`, `--plain-bg`, …) applies
to the whole batch.

**Measured 2026-07-30** (`pokemon-grading.iso`, warm cache, `--closeup
--plain-bg`):

| run | targets | boots | total | per target |
|---|---|---|---|---|
| 2 shots, one process per target | 1 | 1 | 29 s | **29 s** |
| 2 shots, `--batch` | 5 | 1 | 83 s | **16.6 s** (14.9 s steady state) |
| `verify_mon` shape — 5 moves × 4 orbit angles = 20 images, `--batch` | 3 | 1 | 87 s | **29.1 s** (26.9 s steady state) |

So the batch removes the whole per-target fixed cost (boot + memory attach +
menu nav + teardown ≈ 14 s here, far more on a cold cache): **~134 costumes/hour
at the full 20-image verification shape**, ~240/hour for a 2-shot smoke pass.
It scales the obvious way — the more targets in one file, the closer the
per-target cost gets to the pure capture time.

Each target writes into `--out/<id>/` plus a **`batch.json` manifest** —
`{seconds, boots, seconds_per_target, targets: [{id, char, color, status,
reason, seconds, images[]}]}`. **Read the manifest, never a glob**: only
`status == "ok"` means the shots are real; `partial`, `failed`, `hung` and
`skipped` are the ways a target did not produce trustworthy evidence.

Four correctness rules the batch loop exists to enforce — every one of them is
a bug that already shipped once:

- **"in-game after 0.0s" is not proof of anything.** `wait_in_game()` reads the
  SCENE FLAGS, and a costume that hangs the engine during the stage load can
  leave them reading in-game — so the old harness logged a clean start and then
  photographed the same stale frame forever. The gate is the **game frame
  counter**: `wait_game_frames(d, 200)` must actually elapse, and
  `frameshot.liveness()` (`observe.Observer.watch_health`) classifies a failure
  as `hung`/`crashed`. A hung target is recorded as such and the game is never
  photographed again until it is proven live.
- **A hang must not be inherited.** After any failure the loop must reach a
  *live* CSS (`recover_to_css` = unfreeze → neutral → verify the counter
  advances → back out of the SSS / quit the match). If it can't, the session is
  torn down and — `--on-hang reboot`, the default — Dolphin is rebooted for the
  remaining targets (capped by `--max-reboots`). With `--on-hang abort`, or once
  the cap is hit, every remaining target is written to the manifest as
  `skipped`, **never** as captured. A broken run always keeps its
  `storage/test-runs/<run>/User/Logs/dolphin.log` (as if `--keep-run`).
- **Nothing is named `-FAILED.png` any more.** Windows globbing is
  case-insensitive, so the obvious success glob `<char>-*-f*.png` matched
  `<char>-<move>-FAILED.png` and a hard crash was counted as a successful
  capture. A move that never ran is now `_error-<char>-<move>.png`, which shares
  no prefix with the shots.
- Batch captures are **PrintWindow-only** (occlusion-safe, so the batch can run
  behind other windows). `capture_png`'s `SetForegroundWindow` fallback is off
  unless you pass `--allow-focus-fallback`; single-target runs keep it. The
  fallback grabs a screen area, so since 2026-11-18 it first checks that the
  middle and four inner corners of that area all show a window of Dolphin's own
  process (`screenshot_win._shows_only`) and returns nothing otherwise: a
  single-target frameshot run from the app MCP had returned the browser the
  user was reading, as an ok shot.

### The close-up camera FOLLOWS the fighter, and the frame follows the model

`--closeup` parks the DEBUG_FREE camera (mode 8 — the only write-stable camera
mode) on the fighter. It is re-parked **immediately before every capture**, not
once per move: the fighter is a moving target, and the late frames of a move are
the ones worth looking at. Bowser is 31.5 world units off the ground by frame 10
of his nair — more than a full frame height at a 42-unit camera.

Re-parking keeps the fighter's *origin* in shot. It does not keep the *model* in
shot: `--cam-dist` is calibrated per DONOR (Melee's fighters differ ~4× in
height) and a ported costume is a different size from the fighter it rides on.
On the 83-target 2026-07-31 overnight run, 5/5 marth `utilt:10`, 5/5 mewtwo
`nair:10`, 5/5 Ice Climbers `idle`/`shield`/`usmash` and every kingler/granbull
cell ran off the frame edge — while the **vanilla control in the same row never
did**. So with `--closeup --plain-bg`, each capture is **measured** against the
flat background and, only when the subject is clipped by the frame edge or
missing entirely, re-shot from further back (`--no-autofit` disables it):

- a shot that was already fully in frame is returned from the first grab and is
  byte-identical to what the old code produced — autofit cannot re-frame a
  picture that was already correct;
- a refinement costs one extra PrintWindow grab (~0.15 s), paid only by cells
  that were unusable anyway (measured 58.5 s → 64.1 s on a 12-image batch where
  3 cells needed work);
- a refined cell is at a different camera distance from its vanilla control, so
  that pair is no longer a like-for-like **size** comparison. The adjustment is
  recorded in the move sidecar (`captures[].autofit`) and in `batch.json`
  (`autofit`, `autofit_refits`) so a sheet builder can say so;
- `autofit` is part of the control-cache key (`control_cache.SCHEMA` 3), so a
  control shot taken with it off can never be served to a run with it on.

**What it fits is the MODEL, not the picture** (rewritten 2026-07-31). The first
version measured every non-background pixel and re-aimed at that centroid, which
on a translating move is not the model: `run` leaves a dust trail ~24 world
units behind the fighter, just outside a calibrated frame and the first thing a
widening camera finds. That produced a feedback loop — smoke clips an edge → the
camera pulls back → more of the trail comes into frame → it re-aims towards the
smoke — and the cells it shipped had the model 197–216 px off centre and 17–30 %
smaller. Every one of the 64 `run` cells that `grading_sheets.py` flagged as
clipped in the 2026-07-31 set was grey smoke, not a model. So the fit now:

- measures with the **psLib particles unlinked** (`frameshot.hidden_particles`,
  reversible) and, when something still reaches a border, differences against a
  **fighter-hidden** render of the same frozen frame (`hidden_fighter`,
  `model_extent`) — the run dust is two systems and only the fighter can be
  hidden with one lever;
- fits the **root-relative radius about the principal point** (where the camera
  parks the gameplay root), never the silhouette midpoint;
- **never re-aims.** Re-centring each subject on its own silhouette hides a bad
  model-origin offset and decouples a port's framing from its control's;
- backs off **exponentially** (×1.25) until the model is clear of every border —
  a clipped bbox is only a lower bound, so one nudge cannot work — then refines
  once to leave 8 % headroom, and **never comes closer than the calibrated
  distance**;
- logs `an EFFECT touches the edge, not the model` when it keeps the framing,
  and records `effects_edge` / `effects_only` in the sidecar.

Frame provenance was tested at the same time and is **sound**: the fighter's
rendered root matrix equals `cur_pos` exactly (`prev_pos` is a whole velocity
step behind), a commanded camera offset appears in the very next capture
(40.2 px per world unit, linear and immediate), and four captures of one frozen
pose are byte-identical. `_tools/runcam_probe.py` in the pokedex repo
re-runs that experiment.

**A subject that is not drawn is now loud.** If the frame is still empty after a
wide search, the capture is reported as `SUBJECT-NOT-DRAWN` in the log, in the
sidecar (`captures[].autofit.missing`) and in `batch.json`
(`targets[].subject_missing`). This is not always a harness problem: **Bowser's
`nair` swaps to a shell model part that ported costumes do not carry**, so from
frame 8 the game draws essentially nothing (measured: ported 153 572 px at f6 →
145 px at f8; vanilla Bowser 140 718 → 63 824 in the same boot). Shoot
`nair:1-6` on a Bowser donor. `frameshot.SHOT_HAZARDS` warns before the shot
runs. Also recorded there: `shield` is a poor evidence shot (the translucent
bubble washes out and occludes the model) — use `dtilt:1` for the compression
pose.

With `--bag`, each capture's sidecar row carries a `bag` snapshot and the
sidecar gets `bag.hit` (true if the bag entered a damage state on any captured
frame — the machine check that the move actually connected). Between reps the
bag's percent is zeroed (minimal knockback: an uncontrolled port can never
tech or get up, so it must never be launched/knocked down) and it is
teleported back in front of the attacker (`shared/ingame/moves.py park_bag`). Bag
characters can sit in a harmless char-specific idle state (DK shows
`CharSpecific_379`) — judge hits by the Damage* states, not by Wait.

**Pad routing (mirror fix, 2026-07-02).** The CSS→SSS warp skips vanilla's
PlayerInitData→StaticPlayer copy (gm_16AE.c `fn_8016D8AC`), so without a fix
every port keeps the default `player_id = 0` and the fighter polls
`HSD_PadGameStatus[player_id]` = pad 0 = the harness pipe — making the bag
**mirror the attacker's inputs** (bag did the attacker's up-B; both clanked into
Rebound). `match_setup.fix_player_pad_indices(d, ports)` fixes it by writing each
active port's `StaticPlayer.player_id` (+0x48; base `0x80453080`, stride
`0xE90`) AND its live fighter's cached `ft+0x618` copy, right after
`wait_in_game`. This is `player_id` (+0x48), **not** `controller_index` (+0x46,
which drives color/effects only). frameshot does this automatically for both the
solo `[0]` and bag `[0,1]` port sets.

**Kirby copy abilities (`--kirby-copy <donor>`, 2026-07-02).** A solo/bag
harness Kirby can never inhale+swallow, so his copied specials (and the
`EfKb<XX>.dat` copy effect banks) are unreachable through gameplay. The
primitive in `shared/ingame/match_setup.py` installs a copy ability directly:

```
python devtools/frameshot.py --char kirby --bag ganon --kirby-copy ganon --move neutralb --frames 8-44
# effect_probe: top-level/per-experiment "kirby_copy": "ganon" spec key
```

Mechanism (kirby.md §6.4a/b): `ftKb_Init_OnDeath` installs a copy on rebirth
via `ftKb_SpecialN_800F1BAC` when the persisted copy kind (StaticPlayer
`+0x4D`) is armed, so the primitive pokes the kind, KOs Kirby (blastzone
teleport at 999%), and rides the rebirth. Three hard rules:

- **`arm_kirby_copy_ondeath(d)` must run in the early boot phase** (frameshot
  does this automatically): it NOPs the team-fighter gate inside
  `ftKb_Init_OnDeath` (verified opcode patch @`0x800EE638`). Dolphin's JIT
  never sees external writes to already-compiled code, and the function
  compiles at Kirby's FIRST spawn — a mid-match patch does nothing. (Do NOT
  set the §6.4a `flags.b1` bit instead: that's the Classic team-fighter flag
  and makes the death REMOVE the player — gobj NULL forever.)
- **The donor must be in the match** — pass `--bag <donor>` (frameshot
  enforces this). Copy data for absent donors is never loaded; installing
  their copy dereferences garbage and hangs the game hard.
- The harness StaticPlayer has no stocks (warp path), so the primitive seeds
  stocks before the KO; without it the death destroys the fighter.

Success check: `read_kirby_hat(d)` == the donor's INTERNAL FtKind (u32 at
`ft+0x2238`), and neutral-B enters the donor's copy state
(`match_setup.KIRBY_COPY_STATES`; e.g. Ganon 528) instead of inhale (353).

### How it works

Retail Melee's scene loop gates every logic frame on a **debug-pause bitmask
that ships in every build** (the develop-mode pause buttons merely set bits in
it). `framestep.py` sets those bits directly over RAM:

- freeze = bit0 of u8 `0x80479D68` — game logic stops, **rendering
  continues** (no pause HUD, no camera change, PrintWindow still captures)
- single-step = bit0 of u8 `0x80479D6A` — exactly one logic frame runs; the
  global frame counter (`0x80479D60`) confirms each step

Because the game renews its per-frame pad snapshot only on frames that run,
pipe inputs held while frozen register as fresh presses on **exactly the next
stepped frame** — deterministic, TAS-grade move execution at full emulation
speed (no slow boot, no develop mode, no savestates).

**Frame numbering** follows community frame data: frame 1 = the first frame in
the move's action state. For vanilla characters the anim-frame float
(`ft+0x894`) equals the move frame — the sidecar shows both, a built-in sanity
check. (FSM-modified characters rescale the anim float; the step count is the
truth.)

### Gotchas (hard-won — do not rediscover these)

- **Step-request wedge**: the engine clears the step byte only when it differs
  from its shadow (`0x80479D6B`). Two raw writes within ~2 frames wedge both
  at 1 and the game **free-runs with the freeze bit still set**. Always step
  through `framestep.step()` (it clears + settles the handshake).
- **Slippi input delay applies offline**: `SlippiOnlineDelay = 2` adds 2
  frames of pipe latency and draws a "Delay: 2f" OSD into captures. frameshot
  writes it to 0 in the throwaway config, and boots with
  `DolphinBoot(clean_osd=True)` to kill the FPS/memory-card overlays.
- **⚠️ The pipe stick scale is ~1.6x (tilt vs smash)**: `SET MAIN 0..1` is the
  RAW GameCube axis byte (128 = center) and Melee divides the offset by 80, so
  `in_game = (pipe * 255 - 128) / 80`. **`SET MAIN 0.800` is 0.95 in the
  engine**, over the 0.8 smash threshold — which is why `ftilt`, `dtilt` and
  `dashattack` silently produced `AttackS4S` / `AttackLw4` / `AttackS4S` until
  2026-07-31. Holding the stick longer does NOT help: the from-dash smash check
  (`ftCo_AttackS4_8008C114`) and `ftCo_AttackLw4_CheckInput` read the
  MAGNITUDE, not the tilt timer. Use `moves.stick(v)` to express a recipe in
  engine units; the tilt band is 0.25 (tilt gate) .. 0.8 / 0.6625 (smash
  gates), and the recipes sit at 0.60. A dash must still be *started* at ≥ 0.8
  and then eased back to 0.70 before A. Specials send stick+B as one atomic
  pipe frame, and are verified as "reached a character-specific state"
  (id >= 0x155) since their state ids vary per character.
- **`dashattack` is the only capturable frame with real locomotion** (a `run`
  recipe was added alongside it for the same reason): every other recipe is a
  standing or attacking pose, so a port whose skeleton doesn't travel with the
  fighter can pass a whole grading sweep unnoticed.
- **Ice Climbers**: Nana spawns COINCIDENT with Popo (same x within 0.1, z
  −3.8), so an ICs capture is two bodies in one space — at rest she is exactly
  behind him, and the moment a move separates them she smears across the shot.
  frameshot detects her (`gamestate.nana_of`, kind-checked against
  `FTKIND_NANA`) and calls `Follower.hide()`, which clears the
  OPA/XLU/TEXEDGE display bits on her root `HSD_JObj` — she stays in the
  simulation, she just isn't drawn. Do **not** try to solve this by moving
  her: `cur_pos` is engine-owned for a follower (a z of −5000 is back to −3.8
  after one stepped frame), and a position write with no stepped frame after
  it changes nothing on screen at all, because the render loop redraws from
  matrices baked during the last fighter update. Do **not** use the engine's
  solo-Popo id `CHKIND_POPO` (0x20) either — see the note in
  `shared/ingame/char_select.py`; it ignores the costume slot and collides with the
  m-ex added-fighter range.

### Extending

Add recipes in `moves.py` (`MOVES` lists the current set: jab, f/u/d-tilt,
f/u/d-smash, dash attack, all five aerials, grab, dash grab, **all four throws
and the pummel**, all four specials, shield, run, taunt). Current gap:
ledge/getup attacks (need a ledge setup). `gamestate.Player` exposes
state/anim/position/facing/airborne reads and `set_pos()` teleports.

**Char-specific move states are generated, not hand-kept.** Several fighters
enter their own action states (>= 0x155) for a normal or a taunt: Peach's
fsmash is AttackS4Club/Pan/Racket (349-351), Ness's smashes are his own
AttackS4 / AttackHi4(+Charge/Release) / AttackLw4 yo-yo states, Young Link
(and sometimes Link) taunt through AppealSR/SL (342/343), Mario/Fox/Falco/Dr.
Mario taunts and most of G&W's normals are char-specific too.
`gamestate.attack_states(move, kind)` accepts the common ids plus
`shared/ingame/char_move_states.py`, which `devtools/gen_char_move_states.py` derives
from the decomp's `ftData_CharacterStateTables` (per-FighterKind table → its MS
enum → state names matched to moves). Re-run it (`--check` reports drift) if
the decomp's names change; `tests/backend/test_char_move_states.py` fails when the
committed table is stale.

**Throws and pummel need a bag** (`--bag dk --bag-pos 6,0`): they only exist
while an opponent is held. The recipe grabs with L+A, waits for **CatchWait
(216)** — a whiff never reaches it and raises saying so — then applies a stick
direction (no attack button) or A. Two traps, both hit and fixed 2026-09-03: an
uncontrolled human port **never gets up** from `DownWaitU/D` (it is waiting for
a button nobody presses), so `park_bag` now waits out `DOWNED_STATES` and, if
the bag is still down, drops it from just above the ground — Fall → Land → Wait;
and a downed body parked in front of the attacker looks like a valid target
while being ungrabbable, which silently whiffs every throw after the first.

**`run` and `shield` deliberately keep their input HELD** when `execute()`
returns (no `neutral()`), because the capture frames happen after the return —
releasing would drop the shield bubble / brake the run. The next `reset()`'s
`settle_to_wait()` releases everything. `run` waits for state **Run (21)**
specifically: Dash (20) comes first and lasts ~11-15 frames, so waiting for
"either" lands every capture on the dash lunge.

**Grab window:** `grab`/`dashgrab` trigger with `max_steps=14` (most
`_trigger()` calls default to 6) — Link's hookshot tether grab takes ~10f to
enter Catch (212)/DashCatch (214), and the old 6-frame window timed the
probe out in `Wait`/`Dash` before it ever reached the grab state (found
auditing EfCoData scripts 93/331 `hookshot_grapple`,
`research/docs-research/effect-maps/efcodata.md` §6b). The wider window is a strict
superset for every other fighter's grab startup.

## MCP server (`tools/harness/harness_mcp.py`)

The harness is also exposed as an **MCP server** (registered as
`melee-harness` in the workspace `.mcp.json`) so AI agents get the correct
solo-engine path as schema-described tools instead of rediscovering the raw
scripts (and falling into the `tools/ingame/dolphin/` + CPU/cursor trap). The
in-game family: a persistent live session (`boot_match` → `do_move`/`step`/
`send_input`/`screenshot`/`game_state`/`read_ram`/`write_ram`/`poke_dat`/
`set_player`/`freeze` → `end_session`) plus one-shot `frameshot` /
`effect_probe` / `run_ingame_test` wrappers. Only one Dolphin at a time by
default; the server cleans up its Dolphin on disconnect/exit.

**Several Dolphins on one machine.** A machine with the memory for it says so
in ONE place, the file `harness-dolphin.json` beside the lock files
(`%LOCALAPPDATA%/SSBM Nucleus/` on Windows):

```
{"slots": 4, "slot_dir": "C:/path/to/dolphin-slots"}
```

`slots` (1–8, default 1) is how many harness Dolphins may run at once. A key
the file does not give comes from the environment (`NUCLEUS_DOLPHIN_SLOTS`,
`NUCLEUS_DOLPHIN_SLOT_DIR`), which is how a node without the file is set up.
Do not set the size per tool: every harness run takes the first free lock slot
(`harness-dolphin.lock`, `harness-dolphin.1.lock`, ...), and that only works
when every tool on the machine counts the same slots. Until 2026-11-10 each
tool set its own size and one pinned its groups to fixed slots, so tools
waited on a slot while others stood free.

On Windows a different pipe NUMBER does **not** isolate two Slippi Dolphins
(see the next section; checked again 2026-11-10: of two stock captures started
together one failed with "pipe not available"). A slot is isolated by one of
two means:

- **A copy of Dolphin per slot.** `slot_dir` holds `<i>/Slippi Dolphin.exe`,
  a copy whose pipes are `slipslot<A..H>1-4`, and `<i>/slot.json` naming that
  prefix and the exe it was copied from (`stock_exe`). `DolphinBoot` runs the
  copy of the slot it was given and drives its first pipe
  (`dolphin_lock.slot_kit`, `melee_pipe.set_pipe_prefix`). A copy stands in
  only for the Dolphin it was copied from: a boot that resolves to any other
  one (`NUCLEUS_SLIPPI_PATH` naming an alternate build, or a slot copy itself)
  keeps it. On a node with no Slippi install, point `NUCLEUS_SLIPPI_PATH` at
  the stock exe the node's copies were made from. It works with any ISO. The copies are made outside the app by the dev tool
  `dolphin_slots.py`, kept outside this repo (it rewrites the one
  pipe-name literal in a copy of the installed exe; the install is only read).
  With this in place four captures started together all succeed.
- **The memory input backend** below, which needs no copy but only drives
  NTSC 1.02.

Each run gets its own run dir, and a run dir that another live harness process
made is never pruned (`boot.live_runs`). With N > 1 the harness no longer
waits for other open Dolphins to close. `dolphin_status` reports `slot_count`,
`free_slots` and each slot's owner. Code: `shared/ingame/dolphin_lock.py`,
`boot.py`; tests: `tests/backend/test_dolphin_lock_slots.py`,
`tests/backend/test_dolphin_pool.py`.

The server also covers the rest of the app's AI-usable surface (vault
import, CSP rendering, model tools, headless backend REST, ISO builds) —
**full tool reference: [MCP_SERVER.md](MCP_SERVER.md)**.

### Memory input for parallel Windows workers

`NUCLEUS_DOLPHIN_INPUT=pipe` is the default; its transport and recipes remain
unchanged. Set `NUCLEUS_DOLPHIN_INPUT=memory` **in every worker's environment**
with `NUCLEUS_DOLPHIN_SLOTS>1` to bypass Windows named pipes. Ordinary
single-slot runs reject that environment combination rather than silently
changing backend. The native verification tool explicitly passes
`DolphinBoot(input_backend="memory")` to test ONE Dolphin without raising slots.
Playable previews reject memory input; this backend controls automated pad 0.

The cause is a global Windows namespace collision. Slippi's
[Pipes.cpp](https://github.com/project-slippi/Ishiiruka/blob/60f7b63496fb6ec7b9180a04f16f3edc0ad89fe2/Source/Core/InputCommon/ControllerInterface/Pipes/Pipes.cpp#L42)
unconditionally creates **all four** `slippibot1`–`slippibot4` servers in every
process, with maximum instances 1, regardless of the selected controller
mapping. Changing `GCPad1/Device` neither changes server ownership nor creates
`slippibot5`/`6`. A controller refresh can close those shared names, explaining
wrong-instance delivery and broken connections. There is no per-process pipe
namespace setting in this implementation.

`[Input] BackgroundInput=True` is already the correct setting:
[Device::Control::InputGateOn](https://github.com/project-slippi/Ishiiruka/blob/60f7b63496fb6ec7b9180a04f16f3edc0ad89fe2/Source/Core/InputCommon/ControllerInterface/Device.cpp#L70)
returns true for it, even without UI/render focus. The controller's
"Background Input" option is a virtual alias for that same global setting,
not another INI override. One-Dolphin unfocused pipe delivery and pipe-server
PID queries distinguish this from the desktop's apparent focus correlation.

`shared/ingame/memory_input.py` installs a small Gecko C2 hook in the disposable
`User/GameSettings/GALE01.ini` before boot, avoiding external writes to
already-compiled JIT instructions. It replaces the port-0 `PADStatus` at
`HSD_PadRenewRawStatus` (`0x80376A28`, immediately after `PADRead(now)`). The
[local decomp pipeline](https://github.com/doldecomp/melee/blob/ef0240b6647eff8a2b7888bb53cca06e8dc2bacd/src/sysdolphin/baselib/controller.c)
then owns the raw queue, clamping, normalization, last/pressed/released/repeat
buttons and `HSD_PadGameStatus` snapshots. A Python loop racing writes into the
final HSD buffers would not preserve those semantics.

The mailbox lives inside Slippi's allocated code list. Each atomic command
writes an inactive 12-byte sample, then publishes an aligned sequence word;
PPC acknowledges only after copying. A writer never reuses a buffer until its
previous reader acknowledged it. Raw polling continues while game logic is
debug-frozen, so menu taps, held sticks/buttons and existing `framestep` /
`MoveRunner` recipes all work. The serializer preserves the current pipe's
stick truncation and trigger-origin behavior (full L/R = 128 after SDK
calibration; SI mode 3 analog A/B = zero).

`wait_for_pipe()` and `open_pipe()` remain compatibility entry points: memory
mode waits for a validated hook heartbeat and returns the same command API,
without opening or probing a named pipe. No ISO, real Slippi profile, physical
controller configuration, or host emulator executable is patched. This is an
NTSC 1.02 GALE01 uncompressed-ISO backend. Another revision, a changed DOL
injection site, a conflicting runtime hook, or a stopped acknowledgement
fails explicitly. Keep `SlippiOnlineDelay=0` for exact capture comparisons
(frameshot already sets it). Modified builds still need their own acceptance.

**One-Dolphin comparison** (PowerShell, from `app/backend`; requires the
usual native harness dependencies plus `psutil` for owned-child verification):

```powershell
$env:NUCLEUS_DOLPHIN_SLOTS = '1'
$iso = 'C:\path\to\NTSC-1.02.iso'
python -B ../../tools/ingame/verify_memory_input.py --backend pipe --background --deterministic-visuals --iso $iso --out C:\temp\input-pipe --wait-for-dolphin 120 --protected-pid 26108
python -B ../../tools/ingame/verify_memory_input.py --backend memory --background --deterministic-visuals --iso $iso --out C:\temp\input-memory --wait-for-dolphin 120 --protected-pid 26108
python -B devtools/compare_memory_input.py C:\temp\input-pipe C:\temp\input-memory > C:\temp\input-comparison.json
```

Use new output directories each time. The tool checks `dolphin_status`, holds
the normal lock, captures Marth/Mario/Fox jab:3, ftilt:4, fair:4 and upb:5 via
frameshot, records raw HSD input and per-command foreground PIDs, and validates
the retained child's executable, command line and ancestry before cleanup.
Read `verification.json` (`success`, target failures, cleanup), each move's
sidecar and the PNGs; a partial directory is not a pass. `--background`
returns focus to the pre-boot window before input and refuses a focused
sample. No screenshot focus fallback or control-cache reuse is permitted.
`--deterministic-visuals` seeds HSD RNG before each move and hides the native
HUD before simulation, reducing particle/magnifier noise in this comparison
fixture only. Secondary motion can still differ across boots. Omit the flag
from **both** runs to exercise the ordinary frameshot visual profile.
The comparison command checks complete receipts, matching executable/ISO/
profile, six raw pad samples, 12 sidecars and actual RGB pixels. Exit 0 means
full parity; exit 1 means missing evidence or input/state/config mismatch;
exit 2 means input/state match but some PNGs need visual review. It never
silently ignores pixel differences.

**Laptop evidence, 2026-09-26.** All native runs were sequential, with one
lock slot and protected host PID 26108. Slippi executable SHA-256:
`a837d9f76b68c40b213618d584bdd1d4330224c58b595446f3538ff22a2f7518`.
`GetNamedPipeServerProcessId` reported the same owned Dolphin PID (38168)
for slippibot1, 2, 3 and 4; 5–8 were absent. This matches the source diagnosis.

The final comparison used pipe PID 36320 and memory PID 38144 in separate
locked runs. Both completed all 12 captures with no failures, stale captures
or cache hits; all 98 pipe and 99 memory input deliveries were unfocused.
All six complete 68-byte HSD game-pad blocks matched, including button edges,
sticks and triggers. All 12 action states, animation/move frames, positions
and facing values matched. Ten PNGs were pixel-identical (all eight Marth/
Mario captures plus Fox fair/upb); Fox jab/ftilt differed only in the tail
region on visual inspection, and the comparer correctly returned 2.
The ordinary unseeded comparison also matched all six pad blocks and all 12
move states, with seven exact PNGs and particle/HUD differences in the rest.

Evidence was retained locally (not in the repo) under
`%TEMP%\nucleus-input-evidence`:
`pipe-seeded`, `memory-seeded`, `comparison-seeded.json`, and the earlier
`pipe-v2` / `memory-v2` / `comparison-v2.json`. An initial pipe baseline
(`pipe-v1`) stalled during Mario upb reset (frame step 0/8); its failed
receipt/logs remain, and subsequent full pipe runs completed. Pre-fix
`memory-v1` is retained but is not acceptance evidence for trigger parity.
The four targeted modules (`test_memory_input`, `test_ingame_boot_prepare`,
`test_dolphin_lock_slots`, `test_interactive_preview`) passed **62 tests**
using pytest `--noconftest`; this laptop lacks Flask needed by the unrelated
root conftest. The suite's child-process cleanup was wrapped with PID,
command-line and ancestry checks. No six-Dolphin claim is made from these
single-Dolphin results; run the desktop acceptance below.

**Desktop six-worker verification** (never run this on the low-RAM laptop):

1. Fetch and check out `feature/harness-memory-input` in an isolated desktop
   worktree. Use the same Slippi build and ISO for a one-slot pipe baseline
   above, then close its owned session. Use the desktop host's current PID
   for `--protected-pid`, not the laptop's PID.
2. In a fresh PowerShell at `app/backend`, launch six independent Python
   processes. Keep the editor or shell focused while they work. On a machine
   whose pool is set by `harness-dolphin.json`, that file's `slots` wins over
   the variable below: raise it to 6 for this check, or two workers queue:

   ```powershell
   $env:NUCLEUS_DOLPHIN_SLOTS = '6'
   $env:NUCLEUS_DOLPHIN_INPUT = 'memory'
   $env:MELEE_DOLPHIN_LOCK_WAIT = '300'
   $iso = 'C:\path\to\the-same.iso'
   $pipeBaseline = 'C:\temp\input-pipe' # completed desktop baseline from step 1
   $hostPidToProtect = 12345 # replace with the desktop host PID
   $runRoot = Join-Path $env:TEMP ('parallel-memory-' + (Get-Date -Format yyyyMMdd-HHmmss))
   New-Item -ItemType Directory -Path $runRoot | Out-Null
   $python = (Get-Command python).Source
   $workers = 1..6 | ForEach-Object {
       $workerOut = Join-Path $runRoot "worker-$_"
       $arguments = @('-B', '../../tools/ingame/verify_memory_input.py', '--backend', 'memory',
           '--background', '--deterministic-visuals', '--iso', ('"' + $iso + '"'), '--out', ('"' + $workerOut + '"'),
           '--wait-for-dolphin', '300', '--protected-pid', $hostPidToProtect)
       Start-Process -FilePath $python -ArgumentList $arguments -WindowStyle Hidden -PassThru `
           -RedirectStandardOutput "$runRoot\worker-$_.stdout.log" `
           -RedirectStandardError "$runRoot\worker-$_.stderr.log"
   }
   # Read-only check while workers are running: expect six different slot owners.
   python -B -c "import json,harness_mcp as h; print(json.dumps(h.t_dolphin_status({},print),indent=2))"
   $workers | ForEach-Object { $_.WaitForExit(); $_.Refresh(); $_.ExitCode }
   1..6 | ForEach-Object {
       $r = Get-Content "$runRoot\worker-$_\verification.json" -Raw | ConvertFrom-Json
       [pscustomobject]@{ Worker=$_; Success=$r.success; Slot=$r.lock_slot;
           Dolphin=$r.dolphin_pid; Targets=$r.targets.Count; Exited=$r.cleanup.owned_process_exited }
       python -B devtools/compare_memory_input.py $pipeBaseline "$runRoot\worker-$_" > "$runRoot\worker-$_.comparison.json"
       "Worker $_ comparison exit: $LASTEXITCODE"
   }
   ```

3. Require all six exit codes zero, `success=true`, three complete targets /
   12 images per worker, no failed/stale captures, six distinct Dolphin PIDs,
   slots 0–5, unique run dirs, and overlapping `ready_utc`/`finished_utc` ranges.
   Every `focus_samples` entry must have `foreground != dolphin`. Compare
   each worker's six `hsd_pad_game_status` raw blocks and each capture's state,
   animation frame, move frame, position/facing and rendered pose with the
   single-slot pipe baseline. Global game counters and RAM pointers naturally
   differ. Inspect every PNG difference flagged by comparison exit 2
   (secondary motion can vary across boots); exit 1 is a failed comparison.
   Do not treat matching filenames as acceptance. Keep both visual profiles
   the same when comparing; the desktop baseline must be captured there with
   the same graphics configuration, not copied from the laptop.
4. Confirm all six slots return free with `dolphin_status`. Retain every
   `verification.json`, `run.log`, sidecar, PNG and Dolphin OSReport log,
   including failures. Repeat with the actual benchmark ISO. Finally rerun
   the owner's original `parallel-test` workload with both environment
   variables set. No merge, app rebuild/restart or process-name cleanup is
   involved. Unset `NUCLEUS_DOLPHIN_INPUT` and restore slots to 1 afterward.

## Consumers

- **`projects/routes/test_in_game.py`** — the HTTP/WebSocket shell. Endpoints for
  testing full builds, single costumes, custom characters, custom-character
  skins, custom stages, and DAS stage skins; live stage screenshot capture
  (single + batch — the vault's bulk button renders offline instead, see
  [STAGE_HSD_RENDER.md](STAGE_HSD_RENDER.md)); live pause-screen capture;
  preview window positioning; and
  status. Every test and capture runs as the one `ingame` job (`core/jobs.py`):
  its record carries progress and the result, and it owns the Dolphin it
  launched, so one left open is closed when the job ends or at the next start.
  An interactive session also streams `test_progress` / `test_complete` /
  `test_error`. See [API_REFERENCE.md](API_REFERENCE.md#test-in-game-blueprint).
- **`projects/routes/bundles.py`** and **`projects/install/xdelta.py`** — use
  `shared.ingame.boot.launch_real` / `iso_dir_from_slippi` for their "Play" endpoints
  (launching a built ISO in the user's real Slippi Dolphin).


## Desktop M2 memory-input verification (2026-09-26)

The six-worker vanilla comparison now passes under opt-in Windows Graphics
Capture: `NUCLEUS_DOLPHIN_CAPTURE=wgc`, plus the memory-input/slot settings above.
Install `backend/requirements-ingame-qa.txt` in the project venv for this path
(the installer does not carry `windows-capture`). The six-worker run is
`python tools/ingame/verify_memory_input_parallel.py --iso <iso> --baseline <pipe run> --output <dir>`
from the repo root. The default capture backend remains PrintWindow. WGC retains one subscription
per verified render HWND and closes it before the owned Dolphin exits. It waits
for a compositor QPC timestamp after the request; callback arrival alone can
return a queued older camera image.

Evidence (kept locally, not in the repo): `m2-input-pipe-wgc-03` and
`m2-input-memory-six-wgc-03`. All six workers exit 0 with 12 images each;
all raw pad blocks and 12 sampled states match the pipe baseline. Distinct
PIDs, slots 0-5, directories and overlapping intervals are retained. All input
samples are unfocused and all owned Dolphins exited. Every differing PNG was
inspected (20 differences): Marth cape edges and Fox tail secondary motion;
no missing fighter or stale camera. The comparer correctly returns 2.

Earlier PrintWindow runs contain missing black captures despite successful
Win32 calls. The initial per-shot WGC lifetime crashed in
`GraphicsCapture.dll_unloaded`; the two orphaned owned PIDs were closed after
checking their recorded PID, parent, executable and exact User directory.
Persistent WGC removed that crash, and timestamp gating removed delayed
camera images. All failed receipts, logs and visual reviews remain under the
same benchmark folder. No failed trial is acceptance evidence.

The actual M2 Mario V0 DAT was then inserted into an isolated disc with exact
FST and DAT readback checks. Its pipe baseline and six memory workers passed:
`model-corpus/benchmark/m2-benchmark-game/pipe` and `memory-six-idle`.
All 72 captures and input/state comparisons passed; all 32 differing PNGs were
inspected. Differences were cape/tail secondary motion and two tiny Mario
particles at the image edge. An earlier repeat overlapping eight builders and
eight scorers failed frame-step handshakes in three workers. That failed run
is retained. Benchmark scheduling now finishes offline work before gameplay.

The original six-fighter workload was reconstructed from its surviving sidecars
and rerun under `model-corpus/benchmark/m2-original-parallel`: Fox, Link, Mario,
Marth, Peach and Samus each performed jab frame 3 and forward-smash frame 10
(the recovered shots exercised on every fighter, a documented superset).
All six workers exited 0. All 12 images were visually reviewed: correct attacks,
no blank fighter or stale camera. All six slots returned free, with no remaining
Dolphin process. The original parallel-test directories remain untouched.

These checks establish the opt-in desktop harness prerequisite. They do not
establish that every M2 costume passes its own project step-10 game check.

### M2 game scheduling and startup evidence (2026-09-27 UTC)

The M2 benchmark runner prepares cases offline with eight workers, then runs
cohorts of at most six memory-input Dolphins. Each cohort waits until every
native check and test-disc build/readback/hash is complete. The runner waits
for the entire cohort to exit before preparing the next; simply replenishing
free game slots allowed CPU/IO preparation to overlap other live captures.
Run-owned barrier receipts retain prepared members and preparation failures.
This schedule is undergoing a fresh benchmark check; the earlier failed runs
remain evidence.

`wait_game_frames` still requires the full requested emulated-frame interval.
Its existing safety budget now bounds inactivity and renews only on observed
forward counter progress. A scene reset restarts the interval without itself
renewing the budget; a separate absolute bound prevents endless resets. Dead
or unreadable processes fail. This replaces a total-time cutoff that rejected
slow but advancing concurrent emulators, and logs the observed counters and
reason on failure. The controller acknowledgement protocol is unchanged.

The project game checker writes the primary capture status/error/traceback
before pruning its reproducible ISO. If Windows still locks that file, the
checker retains it with a cleanup finding and the original game verdict.

The cohort's readiness publication and reads now share a file lock. Windows
can expose the renamed readiness filename before the publishing call releases
its handles; serialization prevents readers from racing that interval.

Frame stepping uses its existing one-second per-frame budget for both handshake
re-arming and observing the requested frame. It no longer imposes a separate
250 ms cutoff inside that budget. A failed move step stays failed; the former
unfreeze/sleep/retry could advance uncounted game frames during a recipe. Failure
evidence includes game/render/handshake counters, elapsed time, and memory-pad
publication/consumption/heartbeat when available. These changes require fresh
game verification; they do not retroactively clear earlier stalls.
