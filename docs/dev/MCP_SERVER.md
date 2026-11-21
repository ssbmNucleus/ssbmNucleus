# MCP Server (`tools/harness/harness_mcp.py`)

This page documents the private developer harness. The installed app's own MCP server for users' AIs is a
different thing: [APP_MCP.md](APP_MCP.md) (it forwards only `native_port` and `stage_workbench` here).

The project's AI-facing capability surface as one MCP server, so agents get
the *correct* paths as schema-described tools instead of rediscovering raw
scripts (and falling into known traps like the `tools/ingame/dolphin/` CPU/cursor
path). Zero extra dependencies: line-delimited JSON-RPC 2.0 over stdio (the
MCP stdio transport) in plain stdlib, running under the backend's normal
`python`.

Register in your local MCP client's configuration as **`melee-harness`**.
The development machine's workspace `.mcp.json` is not included in a clone.
Use the Python environment where you installed the app's requirements:

```json
{ "mcpServers": { "melee-harness": {
    "command": "<absolute path to your Python environment's python executable>",
    "args": ["<absolute checkout path>/tools/harness/harness_mcp.py"] } } }
```


Long calls stream MCP progress notifications (clients reset their timeout on
progress); if a client still times out, set `MCP_TOOL_TIMEOUT=600000`.
`harness_info` is the orientation tool — call it first.

## Tool families (45 tools)

### 1. In-game live session (solo engine, `backend/shared/ingame/`)

Boot Dolphin ONCE, then iterate across tool calls. The session is the solo
no-CPU no-cursor engine, frozen via the retail debug-pause bits, exactly like
`frameshot.py` (whose helpers it reuses).

| Tool | Purpose |
|---|---|
| `boot_match` | Boot an ISO into a frozen solo offline match (supports `bag`, `kirby_copy`, `plain_bg`) |
| `do_move` / `step` / `send_input` | Execute move recipes, TAS-step frames, raw pipe input |
| `screenshot` | PrintWindow capture, returned inline as an image |
| `game_state` | State/anim/pos snapshot + hang/crash health watch |
| `read_ram` / `write_ram` / `poke_dat` | Live MEM1 reads/pokes; datram DAT-offset pokes |
| `set_player` / `freeze` | Teleport/percent; freeze-unfreeze game logic |
| `end_session` | Kill Dolphin + remove throwaway User dir |

One-shot wrappers (each boots + cleans its own Dolphin; refuse while a live
session is active): `frameshot` (frame-exact move screenshots,
`shots=["fair:1-8", ...]`), `effect_probe` (spec-driven live DAT pokes),
`run_ingame_test` (full PASS/CRASH/HUNG verdict).

`frameshot` also takes **`targets=[{id, char, color, shots?}, …]`** to capture
many characters/costumes in ONE boot (~15 s per target vs ~90 s per boot) — it
quits to the CSS and memory-selects the next fighter between targets. The result
carries a `batch` manifest: **judge each target by its `status` (`ok`), not by
the returned file list** — a target that hangs the engine is reported `hung`
with no images, and the ones behind it are `skipped`, never faked. See
[INGAME_TESTING.md](INGAME_TESTING.md#many-characterscostumes-in-one-boot---batch-2026-07-30).

### 2. App backend (REST)

`backend_start` spawns a headless dev Flask instance via
`tools/ingame/nucleus/_run_backend.py` (repo `storage/`/`projects/`/`output/`,
auto-picks a free port, stdout to a log file — never a pipe, see the
64KB-buffer deadlock note in `run-texture-harvest.js`). The installed desktop
app (LOCALAPPDATA, port 5000) is never touched; pass `url` to attach to an
external instance instead.

| Tool | Purpose |
|---|---|
| `backend_start` / `backend_stop` | Manage the headless app backend |
| `api` | ANY of the ~230 REST routes (`docs/dev/API_REFERENCE.md`); JSON or multipart |
| `vault_import` | Universal auto-detect mod intake (`/api/mex/import/file`) |
| `vault_list` | Trimmed vault/project listings (costumes, das_variants, custom_characters, custom_stages, project_fighters) |
| `retake_csp` | Headless vault CSP re-render (preview/apply, single or batch); note `skinId` = the vault skin's `folder` string |
| `build_modded_iso` | Full build via `tools/ingame/nucleus/build-modded-iso.js` (project create → install → icon placement → export); reuses the running backend |
| `wait_for_file` | Completion polling for async REST jobs (e.g. `export/start` → watch `output/<name>.iso`) |

`export/start` completes over Socket.IO, which the server does not speak — poll
its artifact with `wait_for_file`, or use `build_modded_iso` which already does.
`setup/start` and the test-in-game starts return a `jobId`; poll
`GET /api/jobs/<jobId>` until its status is final.

### 3. Direct engines (no backend needed)

| Tool | Purpose |
|---|---|
| `render_csp` | Canonical portrait render from any costume DAT (`generate_csp` + HSDRawViewer `--csp`: char/color autodetect, pose+camera, low-poly hiding, IC pairing, Fox gun). Renders on a temp copy; returns the image inline |
| `dat_probe` | `shared.rendering.datprobe` texture inventory incl. MatAnim blink frames |
| `detect_content` | Offline `detect_content_type` classification of any mod archive |
| `hsdraw` | HSDRawViewer headless passthrough (`--model export/import`, `--texture`, `--dobj-info`, `--remove-dobjs`, `--inject-lowpoly`, `--accessory`, `--stage-render`, ...). arg0 must be a `--mode` flag or the GUI opens |
| `mexcli` | MexCLI passthrough (~50 verbs; absolute paths only). Only for throwaway/test projects — shared-workspace ops must go through the REST backend, which holds `mexcli_lock` |
| `stage_workbench` | Freeform stage authoring primitives from the Colosseum/CS2 work: `guide`, `inspect`, `mesh`, `graft`, `cameras`, `package`. Animated 3D donors and custom meshes/baked backgrounds; new revision outputs, advisory memory/collision reports, no mandatory game test or automatic install. [Guide](../../tools/stages/README.md) |
| `decomp` | Read-only reference into the local Melee decompilation (doldecomp/melee checkout; auto-located, `MELEE_DECOMP` env overrides). Ops: `symbol` (name search → address), `addr` (address → containing symbol + offset), `grep` (regex over decomp `src/`), `source` (a function's C source), `info`. The DOL loads statically, so symbol addresses ARE live MEM1 addresses — chain with `read_ram`/`write_ram` to inspect or poke engine state by name. m-ex builds hook a few functions and add content the decomp doesn't know |

### 4. Skin lab (live texture editing)

Drives the same HSDRawViewer `--stream` session as the Skin Creator UI
(one session at a time; needs `backend_start`). Open a vault skin
(`{character, skin_id}`), a vanilla costume (`{character, costume_code}`),
or ANY raw DAT (`{dat_path}`); edits stay in-session until saved.

| Tool | Purpose |
|---|---|
| `skinlab_open` / `skinlab_close` | Open/close the live 3D session (open returns the view inline) |
| `skinlab_textures` | Texture list (index/size/name/matanim; thumbnails stripped) |
| `skinlab_get_texture` / `skinlab_set_texture` | Fetch a texture as PNG / replace one (auto-resized) |
| `skinlab_edit` | Parameterized ops: `regions`, `palette_analyze`/`apply`/`reset`, `hue_shift`, `tint`, `composite` (incl. AI-generated material), `generate_texture`; visual ops return the refreshed 3D view inline |
| `skinlab_frame` | Grab the view; optional camera (absolute or deltas) + animation pose |
| `skinlab_save` | `dat_out=` exports the edited DAT; `name=` saves to the vault as a new skin (unified intake) |

Note: `regions` needs a per-character texture-region map — raw-DAT sessions
don't have one; use explicit `textures` + `mask` there.

### 5. Gap-audit wave (2026-07-12)

Added after an adversarial audit of proven-but-unreachable capabilities.

| Tool | Purpose |
|---|---|
| `iso_file` | Pure-Python GC FST reader (`vanilla_refs.py`): `list` / `extract` any file straight out of an ISO, `ensure_ref` for cached vanilla reference DATs. Defaults to the app's recorded vanilla ISO |
| `ram_search` | Live MEM1 forensics in a `boot_match` session: `find` (hex pattern or typed value), `snapshot` (stash a full-MEM1 baseline, max 4), `diff` (changed regions vs a baseline — snapshot → act → diff). Chain hits through `decomp addr` |
| `render_stock` | Stock icon for a MODDED costume DAT via the canonical `costume_assets.build_stock` (texture-diff → head-shot crop → csp-diff; G&W recolor). The companion to `render_csp` |
| `stage_shot` | Headless stage-alone screenshot (`shared/ingame/capture.py`): DEBUG_FREE camera, invisible fighter, no HUD; `pause=true` for the pause-overlay preview; `variants=[…]` for one-boot DAS batches; `framing_sweep=[…]` for camera views from `stage_workbench` with per-view results |
| `fps_batch` | CSS memory/FPS HEALTHY/DEGRADED/HUNG verdict per ISO (`fps_batch.py`) — the compression/modpack stress check |
| `extras_doctor` | No-boot extras triage of a built project: VANILLA/MODDED bytes + offset resolution per layer |
| `fsm_patch` | Standalone Crazy Hand FSM ops on a `main.dol`: `state` / `apply` (idempotent, sidecar backup) / `remove` |
| `csp_regression` | The golden-image CSP renderer suite (`utility/tools/processor/csp_regression`) — run after any renderer change; `update_goldens` after reviewed changes |
| `mex_codes` | Safe bundled m-ex codes maintenance (`tools/dev/mex_codes.py`): `status` (default, read-only) / `backup` / `update` / `restore` / `list` |
| `netplay_desync` | Two-client Slippi netplay desync test (`devtools/netrig.py`, verdict CLEAN/DESYNC, then `slpdiff.py` on both clients' replays): `check` (default: what the rig needs, no boot) / `play` / `status` / `kill`. Needs `NETRIG_ROOT/instance-a` (a netplay Dolphin copy logged into a second Slippi account), the launcher logged into the first, and vgamepad + ViGEmBus in the creation settings' Python |

Users reach a subset of these through the app MCP once a creation toolkit is connected: `toolkit_tools` lists and `toolkit_call` runs the tools in `randall/mcp/toolkit.py` `PASSTHROUGH` (the in-game session, `frameshot`, `stage_shot`, `run_ingame_test`, `fps_batch`, `netplay_desync`, `extras_doctor`, `mexcli`, `fsm_patch`, the ISO/DAT readers, `render_csp`/`render_stock`, `decomp`). Not the dev backend, raw RAM pokes or maintenance (`docs/dev/APP_MCP.md`).

## Creation workflows

| Tool | Purpose |
|---|---|
| `native_port` | Source readers, current native-fighter build pipeline, receipts, checklist and focused adapters; background jobs |
| `rigswap` | Model-to-costume import and fixes through the existing Randall importer, including vault save; background jobs |

## Ground rules baked into the tools

`stage_workbench` is developer tooling, separate from Randall's unfinished stage
import tile. Its native builder compiles on demand against the configured
HSDRaw.dll with the .NET SDK; no game assets are included. Agents can use any
subset of its operations and continue writing custom scripts. Reconnect the
MCP client after updating the server to discover newly registered tools.

`native_port` is registered again, using the current engine and source readers
maintained in `tools/fighterport` in this repository. `rigswap` exposes Randall's
existing model-import/fix path. Both use persistent background jobs for long
operations; poll their `status` operation until completion. Neither requires an
end-user harness. See [`tools/creation/README.md`](../../tools/creation/README.md)
for arguments, local dependency setup, job cancellation and limitations. These
are developer MCP integrations, separate from the unfinished creation UI tiles.

Successful `mexcli export` calls also return `dvd_read_admission`. Melee reads
FST files with lengths rounded up to 32 bytes. The export guard appends only
missing zero padding when a valid file's rounded read would exceed ISO EOF;
it refuses truncated payloads. FST offsets, lengths and existing payload bytes
remain unchanged.
The MexManager source exporter also reserves a zero-filled safety tail of at
least 31 bytes and rounds the result to a DVD sector. This unconditional tail
protects exports made outside the Python entrypoints after the next tool build;
the Python guard supports the currently installed binary independently.

- Gameplay tests use the solo engine — never the `tools/ingame/dolphin/` +
  `cl_match` + `cpustep` CPU/cursor path (CSS/SSS UI tests only).
- One Dolphin at a time — **ENFORCED machine-wide at the chokepoint**:
  `DolphinBoot.launch()` itself acquires the lock
  (`shared/ingame/dolphin_lock.py`, lock file under `%LOCALAPPDATA%/SSBM Nucleus/`)
  and additionally queues behind any Dolphin process launched *outside* the
  lock, so every new process that boots Dolphin serializes automatically —
  no caller opt-in. `dolphin_status` shows the owner (pid, purpose, since
  when; dead owners reclaimed as stale). Queue budget:
  `wait_for_dolphin=<seconds>` on `boot_match`/`frameshot`/`effect_probe`/
  `run_ingame_test`/`stage_shot`/`fps_batch`, or env
  `MELEE_DOLPHIN_LOCK_WAIT` (default 600 s) for
  scripts; `MELEE_DOLPHIN_LOCK=0` is the emergency bypass. Subprocess
  one-shots inherit enforcement in the child — the parent must NOT hold the
  lock across them (different pid = deadlock). Long-lived MCP servers
  started before this change enforce nothing in-process until reconnected.
- Never poke the debug-pause step bytes by hand (wedge); `step` uses
  `framestep.step()`'s handshake.
- Two `mexcli.exe` processes on one workspace corrupt it — prefer REST.
- Session artifacts: `app/scratch/mcp/<stamp>/`; frameshot-tool runs:
  `app/scratch/frameshot/mcp/<stamp>/`.

## Verification (2026-07-11)

Driven end-to-end over real MCP stdio: Marth fair frame 4 (anim float ==
move frame), screenshot inline; Fox `render_csp` (gun splice present);
Bowser `retake_csp` preview; `vault_import` duplicate-skip; `dat_probe`,
`detect_content`, `hsdraw --dobj-info`, `mexcli help`; backend spawn →
`api`/`vault_list` → shutdown; `build_modded_iso` costume build (1.39 GB
ISO); skin lab: open vanilla Fox DAT → textures → hue_shift 140° (overalls
visibly green→blue in the live view) → camera orbit frame → export DAT →
close.

2026-07-12, `decomp` (over real MCP stdio): 34,663 symbols parsed; exact +
regex symbol search; addr→symbol with mid-function offset; `grep` scoped to
`melee/mn`; `source` extraction of `mn_8022DD38_OnFrame`; miss + bad-op
error paths.

2026-07-12, `dolphin_lock` + `dolphin_status`: acquire/release/status;
BusyError with owner identity while a second process held it; queued
acquire reclaimed the lock after the holder was killed; dead-pid lock
reported stale and reclaimed; `dolphin_status` over real MCP stdio.

2026-07-12, gap-audit wave (over real MCP stdio): `iso_file` list/extract
(`PlFxGr.dat` off the recorded vanilla ISO)/`ensure_ref` (`EfMrData.dat`
into `test-base/files/`); `render_stock` on vanilla PlFxGr → `generated`
via `texture-diff`, icon inline; live session: `ram_search` find located
the frame counter `0x80479D60` by value, snapshot (24 MB) → `step 10` →
diff (200 coalesced regions, truncated flag), bounded find behaved;
`stage_shot` Battlefield → clean stage-alone DEBUG_FREE capture inline;
`fsm_patch op=state` → `vanilla` on a project `main.dol`; `extras_doctor`
Bowser fire-breath triage (11 modded layers, in-place); `mex_codes status`
upstream compare; error paths (no-session `ram_search`, unknown stage,
missing DOL, bad action) all clean tool errors. `fps_batch`/
`csp_regression` are thin flag-passthroughs to their documented CLIs and
were verified to schema only. (`css_ui_test`, the CSS/SSS cursor wrapper, was
removed 2026-10-03: the `run-modded-match.js` it ran was deleted 2026-07-17.)
