# Nucleus modded-ISO builder

Builds a modded Melee ISO through the SSBM Nucleus backend REST API, one mod type
at a time, for in-game tests with the solo engine (`backend/shared/ingame/`) or the
`melee-harness` MCP server.

> ## ⚡ PREFERRED: in-app engine (`backend/shared/ingame/`) for getting into a match
>
> For "boot the ISO and get a specific character into a match" — probes, FSM
> checks, screenshot/diagnostic work — **do NOT drive the CSS cursor or add a
> CPU**. Use the in-app ingame engine's memory-loading path, which is faster and
> far more reliable:
>
> 1. `DolphinBoot` (isolated throwaway User dir) → `nav.nav_to_css`
> 2. `match_setup.patch_one_player` + `force_time_infinite` → **solo match,
>    no CPU**
> 3. `match_setup.write_solo_player(d, ckind, color)` +
>    `warp_to_stage_select(d)` — writes the player block directly
>    (ckind = CSS external id; first added m-ex fighter = 0x1A) and warps
>    CSS→SSS with **no cursor movement at all**
> 4. `StageCursor.force_select(INTERNAL_STAGE_ID["finaldestination"])` —
>    direct stage-id write, no SSS cursor
>
> Template: [`backend/devtools/research/fsm_crash_probe.py`](../../../app/backend/devtools/research/fsm_crash_probe.py)
> (run from `backend/` with plain `python`).
> A solo match also removes the CPU as a confound (nothing attacks you or
> moves the camera).

## Pipeline

```
build-modded-iso.js
───────────────────
spawn dev backend (_run_backend)
create + open project
install mod (by --type):
  costume   /api/mex/import
  character /custom-characters
  stage     /custom-stages
export ISO
last-build.json (manifest)
```

## Usage

Mod types and how each is triggered in-game:

| `--type` | what | in-game trigger |
|---|---|---|
| `costume` | fighter skin | select fighter + color |
| `character` | custom m-ex fighter | select its CSS grid slot (app's placement) |
| `stage` | custom m-ex stage | R to its SSS page + select |
| `das` | stage skins (Dynamic Alternate Stages) | hold X/Y/Z on stage-select; many per ISO |
| `effect` | blaster/laser/sword model | select fighter, perform the move (neutral-B) |
| `menu` | CSS background / icon grid / doors | reach the CSS (boot-health + screenshot) |
| `modpack` | one representative of every mod type | smart two-match plan in `backend/shared/ingame/runner.py` |
| `stress` | many vault costumes for CSP/compression testing | boot-health / online-CSS memory checks |

```sh
# Build a modded ISO by type (no game):
node tools/ingame/nucleus/build-modded-iso.js                      # Fox + first vault costume
node tools/ingame/nucleus/build-modded-iso.js --type character --mod wolf
node tools/ingame/nucleus/build-modded-iso.js --type stage --mod "Hyrule Castle 64"
node tools/ingame/nucleus/build-modded-iso.js --type das --variants-per-stage 3   # up to 18 skins/ISO
node tools/ingame/nucleus/build-modded-iso.js --type effect --fighter Fox --extra gun
node tools/ingame/nucleus/build-modded-iso.js --type menu --menu icon_grid   # or background / doors
node tools/ingame/nucleus/build-modded-iso.js --type modpack
node tools/ingame/nucleus/build-modded-iso.js --type stress --count 250 --compression 0.55
node tools/ingame/nucleus/build-modded-iso.js --texture-pack --type stress --count 250
```

Common `build-modded-iso.js` flags:

- `--backend <url>` uses an already-running backend; otherwise the harness
  spawns `tools/ingame/nucleus/_run_backend.py`.
- `--keep-backend` leaves a spawned backend alive after the build.
- `--keep-project` reuses an existing project directory instead of deleting it.
- `--export-only` opens an existing project and re-exports without reinstalling
  content; useful with `--compression`.
- `--compression <ratio>` overrides the recommended CSP compression ratio.
- `--color-smash` exports with color-smash enabled.
- `--texture-pack` exports placeholder CSPs plus a texture mapping JSON for the
  texture-pack harvest/offline naming flow.
- `--slippi <path>` sets the Dolphin/Slippi path used by texture-pack export.

For `character` and `stage` mods the build places the new icon into a real roster
slot / stage page (the app's "add to grid / new page" step) and records its
coordinate in the manifest (`cssIcon` / `sssIcon`).

The build writes the ISO to `output/<project>.iso` and a manifest to
`app/scratch/ingame/nucleus/last-build.json`, e.g.:

```json
{ "iso": ".../output/harness-test.iso", "modType": "costume",
  "fighter": "Fox", "colorIndex": 4, "costumeId": "angy-plfxag" }
```

`colorIndex` is the modded costume's slot = the number of `X` presses on the CSS
to reach it. For `character`/`stage` mods the manifest carries
`characterName`/`stageName` instead.

## Texture-pack harvest (`run-texture-harvest.js`)

Automates the texture-pack export flow for CSP replacement packs:

1. `build-modded-iso.js --texture-pack` exports an ISO with encoded 16x16
   placeholder CSPs and `output/<buildId>_texture_mapping.json`.
2. `control.js` boots that ISO in the fixed texture-pack run directory with
   `--texture-dump`.
3. The backend watcher decodes dumped placeholders and maps each global CSP
   index to Dolphin's real dumped filename.
4. `tex_scroll.py` sweeps the CSS so every placeholder is rendered.
5. The final table is merged into
   `app/scratch/ingame/nucleus/texture_filename_table.json`.

Usage:

```sh
node tools/ingame/nucleus/run-texture-harvest.js --type stress --count 250
node tools/ingame/nucleus/run-texture-harvest.js --offline --compute --type stress --count 250
node tools/ingame/nucleus/run-texture-harvest.js --sheik
```

`--offline` skips Dolphin and names the pack from a harvested table. Adding
`--compute` generates the index-to-filename table by computation instead of a
prior harvest. `--sheik` performs the short, guarded online-CSS Sheik pass used
when that cell cannot be rendered through the offline CSS.

## Online CSS memory check

The online CSS loads more CSP memory than the offline VS CSS. For compression
and CSP stress work, prefer the backend batch probe when pinning limits:

```sh
cd backend
python devtools/fps_batch.py --mode online ../output/count-comp-1000.iso
python devtools/fps_batch.py --mode both ../output/count-comp-800.iso ../output/count-comp-1000.iso
```

Use `--mode offline` for the console/local-play number and `--mode online` for
the Dolphin/Slippi number. The online path enters the Slippi unranked CSS
briefly, watches RAM/process health, and holds B out before matchmaking can pair
anyone.

The older shell wrapper is still available for a single ISO:

```sh
tools/ingame/nucleus/online_test_iso.sh output/harness-test.iso
```

## How it drives the app

- **Backend, not UI** — calls the Flask REST API the desktop app's frontend uses,
  exercising the real build engine (MexCLI, CSP gen, ISO export) without Electron.
- **Isolated** — the dev backend roots data in the repo (`projects/`, `storage/`,
  `output/`); the installed app uses `%LOCALAPPDATA%\SSBM Nucleus`. Picks a free
  port (prefers 5000).
- **`_run_backend.py`** presents a fake-TTY stdin (flask-socketio's dev-server
  guard) and drops `tools/ingame/nucleus` from `sys.path` (so harness modules don't
  shadow stdlib), then runs `backend/app.py` unchanged.

## Requirements

- Nucleus dev setup complete (`GET /api/mex/setup/status`); MexCLI fetched
  (`python tools/build/fetch_native.py mex`) to `utility/mex/win-x64/mexcli.exe`.
- A vanilla 1.02 ISO for `project/create` (default: the dolphin tests' working ISO).
- Node 18+ (global `fetch`); the repo `venv` for the backend; `melee_venv`
  (`numpy`, `pywin32`) for the Python observer/control — both gitignored.
```
