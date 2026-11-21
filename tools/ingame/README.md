# Test Harnesses

This directory contains local harnesses used to boot Melee ISOs, drive Slippi
Dolphin, and collect screenshots or crash signals. The production in-app engine
lives in `app/backend/shared/ingame/`; see `docs/dev/INGAME_TESTING.md` for that Windows-only
runtime harness. The files here are lower-level developer tools and prototypes.

## `tools/ingame/dolphin`

`tools/ingame/dolphin` provides Dolphin launch and controller primitives.

### `driver.js`

Launches a chosen ISO in an isolated Dolphin `User` directory, applies known
controller/config settings, runs a scenario JSON, and writes artifacts.

```powershell
node tools/ingame/dolphin/driver.js --iso "C:\path\to\game.iso"
```

Options:

```text
--iso <path>                ISO to boot. Required unless --help is used.
--dolphin <path>            Dolphin executable. Defaults to Slippi Launcher netplay/playback if found.
--scenario <path>           Scenario JSON. Default: tools/ingame/dolphin/scenarios/boot-and-hold-a.json.
--template-user-dir <path>  Template Dolphin User dir. Defaults to "<dolphin dir>\User" when present.
--run-dir <path>            Use an explicit artifact directory for this run.
--pipe-index <n>            Use \\.\pipe\slippibot<n> for port 1. Useful for two-Dolphin tests.
--texture-dump              Enable DumpTextures and HiresTextures before boot.
--keep-open                 Leave Dolphin running after the scenario finishes.
--dry-run                   Build the isolated config and print the launch plan without starting Dolphin.
--help                      Show command help.
```

Scenario steps support `wait`, `focus`, `tap`, `keyDown`, `keyUp`,
`screenshot`, and `checkpoint`. Built-in scenarios live under
`tools/ingame/dolphin/scenarios/`.

Each run writes `run.json`, `driver.log`, the temporary Dolphin `User` dir,
Dolphin stdout/stderr logs, optional `dolphin.exit.json`, and screenshots under
`app/scratch/ingame/dolphin/<timestamp>-<scenario>/` unless `--run-dir` is set.

### `control.js`

Interactive wrapper for a running Dolphin. It can launch an ISO, discover or
record the live PID, tap keyboard-mapped GameCube buttons, hold buttons across
calls, capture screenshots, and kill the process tree.

```powershell
node tools/ingame/dolphin/control.js launch --iso "C:\path\to\game.iso"
node tools/ingame/dolphin/control.js status
node tools/ingame/dolphin/control.js shot --label css
node tools/ingame/dolphin/control.js press A START --ms 80
node tools/ingame/dolphin/control.js down B
node tools/ingame/dolphin/control.js up B
node tools/ingame/dolphin/control.js kill
```

Screenshots and session state are stored under
`app/scratch/ingame/dolphin/live/`.

### `pipe.js`

Focus-free controller input through Slippi Dolphin's named pipe. It opens a new
pipe connection per input frame, matching Dolphin's one-flush-per-connection
behavior.

```powershell
node tools/ingame/dolphin/pipe.js neutral
node tools/ingame/dolphin/pipe.js tap A --ms 50
node tools/ingame/dolphin/pipe.js tilt MAIN 1.0 0.5 --ms 100
node tools/ingame/dolphin/pipe.js char Fox --color 4
node tools/ingame/dolphin/pipe.js startmatch Fox --color 4
node tools/ingame/dolphin/pipe.js gotocss
node tools/ingame/dolphin/pipe.js cpustep
node tools/ingame/dolphin/pipe.js gotostage
```

Use `--port <n>` to target `\\.\pipe\slippibot<n>`.

### `pipe-daemon.js`

Persistent bridge from a local TCP socket to Dolphin's named pipe. This keeps
one pipe connection open, which is useful when reconnect-per-frame input causes
stuck releases or stick recentering problems.

```powershell
node tools/ingame/dolphin/pipe-daemon.js --port 1 --tcp 48010
```

TCP commands are newline terminated: `TAP`, `PRESS`, `RELEASE`, `TILT`,
`HOLDTILT`, `STICK`, `TRIG`, `NEUTRAL`, and `RAW`. Logs go to
`app/scratch/ingame/dolphin/live/pipe-daemon.log`.

### Native helper scripts

These are implementation helpers used by `driver.js` and `control.js`:

- `win-input.ps1` focuses a Dolphin window and emits one keyboard action.
- `win-window.ps1` reports window status or captures a screenshot.
- `win-batch.ps1` batches focus, key taps, gaps, and optional screenshot capture
  in one PowerShell process for lower latency.

## `tools/ingame/nucleus`

`tools/ingame/nucleus` layers the Dolphin primitives over the Nucleus dev backend. It
builds modded ISOs through the same Flask API the desktop app uses, then boots
and observes them. See `tools/ingame/nucleus/README.md` for command details.

Build a modded ISO with:

```powershell
node tools/ingame/nucleus/build-modded-iso.js --type costume --fighter Fox
```

The old boot-and-match orchestrator (`run-modded-match.js`) was removed on
2026-07-17. Boot and drive builds with the solo engine in `backend/shared/ingame/` or
the `melee-harness` MCP server instead.

## RAM evidence readers (Python)

Dev-only Python beside the harness; nothing here ships. These stand on the in-game engine
(`app/backend/shared/ingame/`), and importing `tools.ingame` puts `app/backend` on `sys.path`.
They lived in `shared/ingame/` and `devtools/` until 2026-11-04.

- `contacts.py`: hit and hurt capsules and hit-victim lists.
- `input_evidence.py`: the fighter's pad and stick state.
- `owned_session.py`: closes only the Dolphin a capture started.
- `verify_memory_input.py`: one worker of the pipe-versus-memory input parity check; run it from `app/backend`
  (`python -B ../../tools/ingame/verify_memory_input.py --help`). `verify_memory_input_parallel.py` runs six.
  See `docs/dev/INGAME_TESTING.md`.

### Contacts

For contact evidence, `contacts.decode_hit_victims` reads all twelve slots in
each native victim array. The bytes at +44/+45 are replacement cursors; zero
does not establish an empty list. Bind an occupied pointer to a separately
captured target Fighter pointer, and retain percent, live damage and hitlag
evidence. Legacy `decode_hitboxes` count labels remain unchanged for old
receipt compatibility; do not use them to infer whether contact occurred.

`contacts.capture_hurtboxes(d, fighter)` retains the native count byte
and complete 15-entry array, then decodes only the count-bounded prefix. It
preserves enabled, disabled, and intangible entries, attachment pointers,
flags, local geometry, cached endpoints, height, and grabbability. Local
endpoints and scale must be finite. Nonfinite cached components become JSON
`null`, `cached_positions_finite` marks the limitation, and per-entry raw hex
retains their exact bits because they may be stale until the native
position-update phase. Cached endpoints establish only the observed cache
state, not collision-consumer timing.

### Frozen attack capsule evidence

`contacts.capture_hitboxes(d, fighter)` reads all four native HitCapsules in one block, retains the raw bytes, and returns every nonzero live state. The JObj attachment is at capsule `+0x48`; `+4` is not a bone pointer. It exposes integer and adjusted damage separately, local and cached world positions, victim counts and the grabbed-only bit. Short reads and nonfinite live data fail.

Bracket capture with the game-frame counter while frozen. A cached position is evidence of that observed phase, not proof of which position a collision consumer used; apply the phase-order guidance above. The grab probe uses this reader for new captures; historical captures are unchanged.

For script-to-native geometry comparisons, use `native_hitbox_geometry(fields)`.
The GALE01 interpreter multiplies encoded size and signed offsets by the literal
float32 constant `0.003906f`, then rounds the product to float32. It does not
divide by exactly 256. For example, encoded radius 1331 becomes
`5.198885917663574`, whereas division by 256 gives `5.19921875`. Preserve the
comparison tolerance and model the native arithmetic. The editor's first offset
word (`z_offset`) becomes native local X; its third (`x_offset`) becomes local Z.
The helper validates the original integer field widths before conversion.

### Owned capture cleanup

`owned_session.close_owned_session` checks the retained child Popen handle,
parent PID, executable and current ancestors before session cleanup. PID 12348
is always protected. It never sweeps process names or port owners. Use
`persist_and_close(session, save, artifacts)` when writing final capture files:
an artifact writer failure propagates after owned cleanup. Damage and Passive
use this shared path; unrelated sessions remain protected by the harness lock.

### Input evidence

`input_evidence.capture_input_evidence(d, fighter)` records the fighter's pad
index, raw and normalized pad stick, filtered/current and previous fighter
stick, tilt timer, and live common input thresholds. Raw producing blocks are
retained. Freeze and bracket the reads with the game counter. Requested pipe
commands are separate evidence: a below-deadzone command can be delivered
correctly while the fighter receives zero. Choose walking and dash stimuli
against the shipped common thresholds, rather than character animation-speed
denominators, and verify the observed state/action before judging port behavior.
