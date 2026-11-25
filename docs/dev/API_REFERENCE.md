# API Reference

## Randall model import tool

The `/api/assistant/files` upload accepts `.glb`, `.gltf`, `.obj` and `.dae` alongside ZIP and the existing mod
formats. Companion files (textures, materials) belong in a ZIP; the file-handle store does not merge separately
uploaded filenames.

`import_model(source, fighter?, name?)` imports an attached model (a zip, or a GLB/glTF, FBX, DAE or OBJ file; not
SMD) straight through: rigswap runs as a subprocess, nothing is asked of the user, and the costume is saved to the
vault as a new costume. With no `fighter`, rigswap picks the one the model fits best and the reply's `fighter_pick`
says which and why. The reply is `status: done` (the fighter, the saved costume, its portrait, rigswap's `seconds`
and `cost_usd`; `not_saved` when the vault refused it), `status: failed` (where it stopped, its cause, what the user
can do; nothing saved) or `status: cancelled` (the user pressed Stop; nothing saved). Another fighter is
`import_model` again with the same source: a second costume. The schema is `chat/import_job.SCHEMA`; the path is
[`randall/model_import/README.md`](../../app/backend/randall/model_import/README.md) and
[RANDALL.md](RANDALL.md#1-model-import-model_import).

The older `model_fit`, `model_mesh`, `model_revise`, `model_candidate` and `model_physics` tools are not registered
(`tools.py`); older chats still draw their cards.


## Randall in Nucleus (local preview)

All sixteen routes are gated by `NUCLEUS_ASSISTANT` and use normal local backend
authentication. See [RANDALL.md](RANDALL.md) for tools and lifecycle details.
The chat body also accepts optional `api_key`, a per-turn provisioned Patreon
credential from the existing `ai-entitlement` flow. It is used only for that turn
and is never persisted. The viewer combines service readiness with Patreon
entitlement and shared balance; there is no local-key fallback. Optional
`account_token` is the Nucleus Supabase session for account actions, kept only in
run memory and excluded from model messages and persisted chat.

The chat tool catalog also includes `list_projects`, `inspect_project`,
`create_project`, and `install_project_mods`. Project creation and costume installs
use the existing approval endpoint with `project_action` previews and no choice
parameter. Receipts carry `project_changed` plus a `project` object (opaque `id`,
display `name`, server-resolved `path`); installs report `installed_count`,
`failed_count`, `per_fighter`, and `installed_items` for wholly successful batches.
The receipt's Open project button uses the existing `/api/mex/project/open` route.
There is no assistant ISO export tool. See [RANDALL.md](RANDALL.md) for scope
and revalidation rules.

| Method | Route | Contract |
|---|---|---|
| GET | `/api/assistant/status` | Service readiness, model, tools, active run ID; no key disclosure. `tasks`: the starting points, in display order (two groups, Characters then Stages), `[{id, label, group, placeholder, hint, picker, available}]` (`recipes.LAUNCHABLE`, minus any task whose operations are all switched off in this build): `recolor_part` "Retexture a costume" (`picker: 'costume'`), `model_import` "Import a character model" (`picker: 'fighter'`), `recolor_stage` "Retexture a stage" (`picker: 'stage'`), each `available: true`, and the two stubs `create_character` "Create a character" (group Characters, third) and `stage_import` "Import a stage model" (group Stages, last), each `picker: null`, `placeholder: null`, `available: false`, a hint that starts "Coming later". `picker` names what the panel asks the user to choose before the first message. `available: false` means the row is shown but can never start a chat (`chat` drops its id). `import_fighters`: the sorted fighter names a model import can target (the importer's roster minus the Ice Climbers); the fighter picker offers exactly these. `recolor_stages`: the stages the Stage Lab opens, the stage picker's list, `[{code, name, folder, legal, art}]` (`recolor/stage_lab.supported_stages`: the 29 versus stages of `core/stages.ALL_STAGES`, the six tournament stages first; `legal` marks those six; `art` is a backend path to the stage's picture, `/vanilla/stages/<file>.png` or `/api/mex/stages/<code>/art/icon`) |
| POST | `/api/assistant/files` | Multipart `file`, at most 128 MB. Returns server-owned `{file: {file_id, name, size, extension, sha256}}`; supported DAT/archive/model/PNG extensions only. PNGs must be valid and at most 16 megapixels. Invalid upload: 400. |
| GET | `/api/assistant/files/<file_id>` | Download an immutable attached/generated file; optional `?preview=1` displays PNG inline. Normal backend auth, UUID validation, hash/location checks and `nosniff`; unknown/changed file: 404. |
| GET | `/api/assistant/chats` | Most recent 100 local conversations: `{id, title, updated, task}` (`task` null when the chat has no declared task) |
| GET / DELETE | `/api/assistant/chats/<chat_id>/game-tests/<session_id>` | Read a chat-owned manual game session or request Stop. Returns `session_id`, `label`, `running`, `status`, `lastEvent`, `stopRequested`, `capture_session_id`, `capture_supported`. Unknown/cross-chat IDs: 400; normal assistant auth/gate applies. GET never launches a process. Deleting the parent chat is refused while its game is active. |
| GET | `/api/assistant/chats/<id>` | Transcript with tool receipts, `task` (the chat's declared task, or null), `active_run_id`, `reply_run_id`, and `download_run_ids`, plus durable `pending_inputs`. Assistant messages have stable `id` and `run_kind` (`reply` or `download`); active runs share the latest transcript. |
| DELETE | `/api/assistant/chats/<id>` | Delete local transcript; 409 if active; does not undo vault edits |
| POST | `/api/assistant/chat` | `{chat_id?, input_id?, message, context?: {page, character, stage, selection, files, editor, task, fighter}, api_key?: string, account_token?: string}` → SSE `started`, `turn_progress`, `delta`, `tool_start`, `tool_result`, `approval_requested`, `approval_update`, `inputs_changed`, `turn_done`, `input_applied`, `done`; heartbeat comments. `started` includes `message_id` for the reply. `input_id` resumes a stored input using its server-owned content/context and fresh credentials. `turn_done` settles a reply before the same worker delivers the next input; `input_applied` carries `users`, the new assistant `message`, and remaining `pending_inputs`. Only `done` closes the stream. Tool receipts include `started_at`, `completed_at`, and `elapsed_ms`. IDs and tool results originate on the server. Invalid body/missing key: 400; another provider reply: 409. A direct download may run concurrently. `files` accepts up to eight file IDs/descriptors and is resolved to server metadata; `editor` is descriptive skin/texture context, never execution authority. `task` declares the chat's task (an id from `/status` `tasks` with `available: true`); any other value, `stage_import` included, is dropped silently (the chat is an ordinary chat), and only the task on the chat's first user message counts (a later one is ignored). `fighter` is the fighter picked for a model import: kept as the roster's own name (any case; long-name aliases such as `Captain Falcon` accepted, at most 40 characters), dropped silently when it is not one of `import_fighters`. A recolor's starting costume travels as ONE entry in `selection`: `{id, character, name}` for a vault costume, or `{character, vanilla: true, color, name}` for a stock one (no `id`); the backend opens it directly only when `selection` has exactly one entry. A stage recolor's starting stage travels the same way, as ONE `selection` entry of kind `stage`: `{kind: "stage", stage: "GrNBa", id: "<variant id>", name}` for a vault stage variant (the `id` the Vault's `GET /api/mex/das/storage/variants` serves; its archive `<storage>/das/<folder>/<id>.zip` must exist) or `{kind: "stage", stage: "GrNBa", vanilla: true, name}` for the stock stage (no `id`). `stage` is a `recolor_stages` code (its vault `folder` is accepted and rewritten to the code); `name` is a label, trimmed to 120 characters (the stage's own name when missing). The blueprint keeps such an entry with exactly these keys or drops it (an unsupported stage, a malformed or missing variant, both shapes at once); every entry without `kind: "stage"` passes untouched. In a `recolor_stage` chat's first turn with exactly one such entry, code opens it with `stage_lab_open` before any model round. Each reply's `routing` carries `declared_task` (always; null when none) and `task_mismatch` (`'model_import'` or absent): it fires only when a model-only file (`.glb`, `.gltf`, `.obj`, `.fbx`, `.dae`, `.smd`; never a `.zip`) is attached to THIS message, not yet imported and asked about, in a declared chat that is not a model import. The words of a message never set it. |
| POST | `/api/assistant/chats/<id>/approvals/<approval_id>` | `{decision: "approve" or "deny", choice?: "default", "all", "fix", or "import_as_is"}`; choice must match an option offered by that approval. Variant reviews offer default/all; a post-download `slippi_review: true` approval offers fix/import_as_is before vault writes. Same decision and choice are idempotent; malformed body 400, unknown ID 404, conflicting/expired decision 409. Requests expire after 15 minutes. Arbitrary arguments and legacy `allow_changes` are rejected. Window only: needs the window-only key `X-Nucleus-UI-Key` (`core/ui_channel.py`); without it 403 `not_the_app_window`, a request marked as an agent's 403 `automation_caller`, no key configured 503 `ui_approval_channel_unavailable`. |
| POST | `/api/assistant/runs/<id>/cancel` | Cooperatively stop after any already-running tool; completed results persist |
| POST | `/api/assistant/chats/<id>/inputs` | `{id: UUID hex, message, context?, mode?: "queue" or "steer"}` adds a durable input. Same ID retries are idempotent, including after delivery. Same context whitelist/attachment resolution as chat; no credentials accepted. Maximum 20 inputs. Returns `pending_inputs` and `reply_run_id`. |
| PATCH / DELETE | `/api/assistant/chats/<id>/inputs/<input_id>` | PATCH accepts `message` and/or `mode`; DELETE removes the pending input. Already delivered/removed: 409. |
| POST | `/api/assistant/chats/<id>/inputs/batch` | `{ids: [UUID hex], action: "send" or "clear"}` atomically promotes or removes the visible queue. Send delivers active corrections oldest first at the next safe boundary; an idle queue remains available for `/chat` with `input_id`. Already-delivered IDs are ignored. |
| POST | `/api/assistant/actions/<id>/undo` | Restore an organization action; 409 on intervening membership edits or active turn |
| GET | `/api/assistant/previews/<id>` | UUID-scoped portrait PNG, or 404 |
| POST | `/api/assistant/website/like-status` | `{post_id, account_token}` → `{liked, like_count}` for the signed-in Nucleus account. Invalid input/session or website failure: 400 |
| POST | `/api/assistant/website/like` | `{post_id, liked: boolean, account_token}` → confirmed desired like state, count and updated mod card. Does not blindly toggle or retry failed writes. Invalid input/session or website failure: 400 |
| POST | `/api/assistant/website/download` | `{chat_id?, post_id, file_id?}` or `{chat_id?, items: [{post_id, file_id?, variants?}]}` → `{chat_id, run_id}`. Batches accept 1–24 unique posts; each item may select an exact file or `variants: "default"/"all"`, never both. One batch approval requires `fix` (default) or `import_as_is`; deny omits choice. Starts a fixed download proposal without an LLM/key, including while a provider reply is active. Poll the chat for approval and per-post progress; no bytes download until approval. Receipts preserve partial successes and include exact `imported_items` with CSP/stock URLs and `imported_stages` with IDs, folders and screenshot URLs. Approval file previews fall back to the website image. Invalid input: 400; another direct download: 409 |
| GET | `/api/assistant/chats/<id>/approvals/<approval_id>/files` | Active prepared download inventory. Query: `choice=all/default`, `kind=mods/files`, `query` (max 160 chars), `offset`. Returns 20 items, total, next_offset and grouped counts. No download or website request. Invalid filter/unknown review: 400; inactive run: 409 |

`POST /api/assistant/chat` also accepts optional `game_settings` containing only
`vanillaIsoPath` and `slippiDolphinPath` strings (up to 4096 characters each).
These request-owned settings are not provider context or transcript data.
The `test_in_game` chat tool supports `start`, `status`, `stop`, and `list`;
start uses an exact costume, exported file, custom character/stage or DAS variant
selection and returns a `game_test` receipt immediately. See [RANDALL.md](RANDALL.md#7-in-game-tests-test_in_game).

Assistant `turn_progress` events carry `{message_id, started_at, model_rounds}`.
`started_at` is a Unix timestamp in seconds; both progress fields also persist on
the assistant message. Model iterations include fast and main responses, excluding
automatic setup batches and direct downloads. There is no fixed task-level round
cap. The client uses progress and elapsed time for a non-blocking long-task notice;
provider limits, errors and cooperative cancellation still apply.

## Overview

- **Base URL**: `http://localhost:5000` (port is dynamic — the backend prefers 5000 but falls back to a free OS-assigned port; Electron reads the actual port at startup)
- **Response Format**: JSON with `{ success: boolean, ... }`
- **Async Operations**: WebSocket events for progress (export, import, setup, ISO scan, in-game testing)
- **File Uploads**: Multipart form data

---

## Blueprint Summary

| Blueprint | Purpose | Endpoints |
|-----------|---------|-----------|
| assistant_bp | Nucleus assistant (development preview) | 21 |
| project_bp | MEX project management | 16 |
| assets_bp | File serving (images, assets) | 5 |
| costumes_bp | Import/replace/remove/reorder in MEX | 8 |
| export_bp | ISO export job, save and download of its ISO | 3 |
| storage_costumes_bp | Vault costume operations | 18 |
| storage_stages_bp | Stage vault operations | 7 |
| vault_backup_bp | Backup/restore storage | 5 |
| mod_export_bp | Export as ZIP mods | 3 |
| import_bp | Unified import (auto-detect) | 1 |
| das_bp | Dynamic Alternate Stages | 8 |
| stage_slots_bp | Stage catalog + replace slots for non-tournament stages | 7 |
| poses_bp | CSP pose management | 5 |
| setup_bp | First-run setup | 4 |
| slippi_bp | Dolphin/texture packs | 6 |
| xdelta_bp | Binary patches | 10 |
| bundles_bp | .ssbm mod bundles | 10 |
| viewer_bp | 3D model preview | 5 |
| settings_bp | Settings (placeholder, no routes) | 0 |
| iso_scan_bp | Rip costumes from ISOs | 7 |
| menus_bp | CSS/SSS menu mods | 37 |
| custom_stages_bp | Custom (m-ex) stages | 16 |
| custom_characters_bp | Custom (m-ex) fighters | 12 |
| test_in_game_bp | In-game test harness | 14 |
| publish_bp | Publish vault packages to ssbmnucleus.net | 1 |
| account_bp | The Discord sign-in the backend holds | 3 |
| extras_bp | Character effects (extras) | 12 |
| character_sounds_bp | Character sound-bank packs | 11 |
| music_playlists_bp | Stage + menu music playlists | 10 |
| stage_editor_bp | Human Stage Creator sources and copy saves | 2 |
| nucleome_bp | Tracker: replays, stats, combos, Lite, Watch, icons, ranks, cloud vault, share (`tracker/routes/`) and the Randall coach (`randall/routes/coach.py`) | 62 |
| codes_bp | Gecko codes (vault library + project sync) | 7 |
| chat_reports_bp | "Report this chat" for Randall (review + submit) | 2 |
| jobs_bp | Background jobs (`core/jobs.py`): list, get, cancel, mark seen | 4 |
| play_bp | Play, the Melee Unlocked launcher (gate `play`; `play/routes/play.py`) | 16 |
| mcp_bp | `POST /api/mcp`: MCP JSON-RPC for the user's own AI; `POST /api/mcp/account`: the window's Patreon token for its AI calls; `POST /api/mcp/window`: the window's Slippi Dolphin folder for `test_in_game`; `GET`/`POST /api/mcp/window/confirmations[/<id>]`: the questions an MCP call asks the person; `GET /api/mcp/window/problem-reports`, `POST .../<id>/review` (`{include, app_version}` -> a frozen chat report submission, sent by `POST /api/mex/chat-reports/submit`) and `POST .../<id>/discard`: the problem reports the user's AI wrote with `report_problem`. All window only (`X-Nucleus-UI-Key`, `core/ui_channel.py`), so the AI client cannot set, answer, read or send them ([APP_MCP.md](APP_MCP.md)) | 9 |

---

## Jobs Blueprint

Background jobs run through `core/jobs.py`. A job record is `{id, kind, label,
status, progress, detail, error, result, params, project, owned, notes, extra,
seen, created_at, started_at, ended_at, seq, owner}`. `status` is `queued`,
`running`, `done`, `failed`, `cancelled` or `interrupted`. Every change is also
emitted as the `job` socket event carrying the same record; `seq` orders
records from one backend process.

Kinds: `texture_matching` (live texture matching), `stage_render` (bulk stage previews), `csp_retake` (bulk portraits), `builtin_character` (built-in fighter setup), `iso_scan` (ISO Scan), `vault_restore` (Vault Backup), `iso_export` (Export), `texture_pack`
(Slippi auto-apply), `xdelta_build`, `xdelta_create`, `patch_play` (XDelta),
`bundle_export`, `bundle_install`, `bundle_play` (Bundles), `replay_watch` (Watch
with mods), `combo_video_render` (Combo Video final render), `first_run_setup`
(first-run setup), `ingame` (in-game tests and captures), and the memory-only
`replay_scan`, `combo_scan`, `deep_stats`, `cloud_sync`, `cloud_autorun`
(Tracker library passes and the cloud chain). A job only writes
files named by its own id and owns its temporary files, so a failed, cancelled
or interrupted job leaves none behind and one job's result is never another's.

### GET /api/jobs
This process's jobs, plus interrupted jobs from an earlier run the user has not
seen, newest first. `?kind=<kind>` narrows to one kind; `?active=1` returns only
queued/running jobs. `owner` is this backend process (`{pid, created}`), so a
window ends a queued/running job of an earlier process that the list leaves out
(a memory-only kind that died with it). **Response:** `{ success, owner, jobs: [record] }`

### GET /api/jobs/{job_id}
One record (this process's, else the one on disk). 404 if unknown.
**Response:** `{ success, job }`

### POST /api/jobs/{job_id}/cancel
Asks a running job to stop; it ends `cancelled` when its work next checks.
A kind whose work waits on a Dolphin closes it too: `replay_watch` closes its
playback Dolphin as the popup's Stop does (the watch ends `done`). `ingame`
closes an automated test's or capture's Dolphin, and the same stop ends its
wait for the Dolphin lock, the boot and the menus, so it ends `cancelled` at
once with no verdict and no partial batch result. An interactive session stops
as `/test-in-game/stop` does (it ends `done`, verdict `stopped`).
**Response:** `{ success, stopping }` (`false` if the job is not active here).

### POST /api/jobs/{job_id}/seen
The user has seen an ended job's outcome; an interrupted job stops being listed.
**Response:** `{ success, seen }`

Kinds so far: `vault_restore` (Vault Blueprint, restore), the Tracker passes
`replay_scan`, `combo_scan` and `deep_stats` and the cloud's `cloud_sync` and
`cloud_autorun` (Tracker Blueprint; kept in memory only, the newest five ended
of each), and `replay_watch`
(Tracker Blueprint, Watch with mods): one watch at a time; `params` has
`replay`, `record`, `widescreen`, `batch_total`; `extra` has `phase`
(`starting-worker`, `creating-project`, `installing`, `exporting`, `launching`,
`playing`, `cleaning`), `capture_session_id`, and for a per-game recording
batch `batch_index` and `recordings`; `result` is `{last_recording,
recordings}`.

---

## Project Blueprint

### GET /api/mex/status
Get current MEX project status.

**Response:**
```json
{
  "success": true,
  "connected": true,
  "projectLoaded": true,
  "generation": 4,
  "project": { "name": "MyMod", "path": "/path/to/project" },
  "counts": { "fighters": 26, "stages": 29 }
}
```

`generation` counts project opens, closes and deletes. The window sends the one
it is showing as the `X-Nucleus-Project` header; any request that touches the
project with an older one answers **409** `{ "code": "project_changed" }` and
changes nothing. Status, open, close, delete and list never check the header.

### POST /api/mex/project/open
Open existing MEX project. Recovery runs and MexCLI reads the project before it
becomes the open one; on any failure the previous project stays open. 409 with
`code` `quarantined`/`error` (recovery refused) or `busy` (another operation
holds the build). Success returns `generation` with `project`.

**Body:**
```json
{ "projectPath": "/path/to/project.mexproj" }
```

### GET /api/mex/project/list
List all app-managed MEX projects (with which one is currently open).

### POST /api/mex/project/close
Close the currently loaded MEX project without deleting it.

### POST /api/mex/project/create
Create new MEX project from vanilla ISO.

**Body:**
```json
{
  "isoPath": "/path/to/vanilla.iso",
  "projectDir": "/path/to/output",
  "projectName": "MyMod",
  "patchId": "optional vault xdelta id",
  "starterCodes": true
}
```

`starterCodes: true` (the Projects page sends it) also adds the codes a user's
new project starts with, enabled: today **Now Playing** (the song name at match
start, `docs/dev/NOW_PLAYING.md`). They are added only here, never by export, so
existing projects are untouched. Omitted for the throwaway projects other
features create (replay playback, combo videos, test builds).

### POST /api/mex/project/delete
Delete an app-managed MEX project directory. Deleting the open project closes
it first; a failed removal still reports `currentProjectClosed` (and
`generation`) with its error, so the window can follow the close.

**Body:**
```json
{ "projectPath": "/path/to/project" }
```

### GET /api/mex/project/build
Get disc-banner metadata (title/creator/description) and banner image preview.

### POST /api/mex/project/build
Set disc-banner fields and (optionally) the 96x32 banner image.

**Body:** any of `shortName`, `longName`, `shortMaker`, `longMaker`, `description`, `bannerPngBase64`.

### GET /api/mex/fighters
List all fighters in project.

**Response:**
```json
{
  "success": true,
  "fighters": ["Mario", "Fox", "C. Falcon", ...]
}
```

### GET /api/mex/fighters/{fighter_name}/costumes
Get costumes for specific fighter.

**Response:**
```json
{
  "success": true,
  "fighter": "Fox",
  "costumes": [
    { "index": 0, "code": "PlFxNr", "cspUrl": "/assets/...", "stockUrl": "/assets/..." },
    ...
  ]
}
```

### GET /api/mex/fighters/{fighter_name}/team-colors
Get team color costume indices.

**Response:**
```json
{
  "success": true,
  "fighter": "Fox",
  "red": 1,
  "blue": 2,
  "green": 3
}
```

### POST /api/mex/fighters/{fighter_name}/team-colors
Set team color index.

**Body:**
```json
{ "color": "red", "costumeIndex": 5 }
```

### GET /api/mex/recommended-compression
Get recommended CSP compression ratio.

**Response:**
```json
{
  "success": true,
  "totalCostumes": 156,
  "vanillaCostumes": 128,
  "addedCostumes": 28,
  "ratio": 0.8
}
```

### GET /api/mex/project/disc-usage
Per-category disc space usage of the open project's `files/` (costumes, stages,
video, audio, trophies, other) plus capacity and skins-remaining estimates.
`reclaimable.video` is what `/project/strip` would actually free (the vanilla
movies minus their stub size), which is smaller than `breakdown.video` — that
category also includes any added fighter's own movie, which strip never touches.

**Response:** `{ success, capacity, used, free, overCapacity, breakdown, reclaimable, avgSkinBytes, skinsRemaining, skinsRemainingHd }`

### POST /api/mex/project/strip
Shrink strippable file categories to free disc space. Currently only `video` is
allowed: the 28 vanilla `Mv*.mth` cutscenes/movies (~810 MB full) are each
replaced with a short valid stub cut from the movie's own opening frames
(`MvOpen.mth` gets a longer low-detail stub) instead of being deleted — deleting
them crashes the build after every 1P clear, on the title attract loop, and in
Data → Movies (`core/movie_stubs.py`, Tracker #92). Idempotent; also regenerates
a stub for any vanilla movie a pre-0.8.11 build already deleted, from the
recorded vanilla ISO if one is known. Never touches an added fighter's own movie
or any other `mv*` file.

**Body:**
```json
{ "targets": ["video"] }
```

**Response:** `{ success, removed, freedBytes, targets, stubbed, restored, unresolved }`

### POST /api/mex/shutdown
Shutdown the Flask server. While a critical operation is in flight (ISO
export/save/download — see `core/critical_ops.py`) it answers
`409 { "deferred": true, "operations": [...] }` instead of exiting; the
Electron shell polls until it drains. With nothing in flight it replies
success and exits shortly after the response is sent, first removing the
workbench checkpoint copies it made (`paths-checkpoint`; the exit skips
atexit handlers).

---

## Codes Blueprint

Gecko code management: a vault library at `storage/codes/` (lazily seeded from
the bundled community `codes.ini`, 49 codes) and per-project code sync through
`mexcli sync-codes`. See the "Gecko Codes" wiki page for the user-facing flow.

### GET /api/mex/codes/vault/list
List the vault code library (runs the lazy first-run seed).

**Response:** `{ success, codes: [{ id, name, creator, category, description, source, builtin, created }], categories }`

### POST /api/mex/codes/vault/parse
Smart-parse pasted text into normalized codes (raw hex, `$Name [Creator]` INI
blocks, Dolphin ini sections, loose forum pastes). Preview only — saves nothing.

**Body:** `{ "text": "..." }`

**Response:** `{ success, codes: [{ name, creator, description, source, enabled, valid, error?, warnings }], warnings }`

### POST /api/mex/codes/vault/save
Save parsed/edited codes into the vault. Validates every source (only gecko
opcodes 00/02/04/C2 compile in the m-ex loader) and dedupes by
`Name [Creator]` header.

**Body:** `{ "codes": [{ name, creator?, category?, description?, source }] }`

**Response:** `{ success, added: [...], skipped: [{ name, reason }] }`

### POST /api/mex/codes/vault/update/{code_id}
Edit a vault code. Any of `name`, `creator`, `category`, `description`,
`source` (re-validated).

### POST /api/mex/codes/vault/delete/{code_id}
Delete a vault code. Deleted built-ins stay deleted (tracked in
`storage/codes/seed_state.json`).

### GET /api/mex/codes/project
List the codes in the open project's `files/codes.ini`. Collapses exact
duplicates (the historical add-code dedupe bug appended the default Slippi
code on every export). Default-on codes (`default: true`, the Skip Slippi SSS
fix) missing from `codes.ini` (a never-exported project) are synthesized into
the response as enabled — export adds them to any project that lacks them, so
"In this build" lists them regardless.

**Response:** `{ success, codes: [{ name, creator, description, source, enabled, default, inVault, vaultId }], duplicatesCollapsed }`

### GET /api/mex/codes/dolphin
Best-effort list of gecko codes the user's Slippi Dolphin applies at RUNTIME
(its `Sys/GameSettings/GALE01r2.ini` enabled set plus user GameSettings
overrides), resolved from `?slippiPath`. These layer over whatever the
exported ISO carries; the codes manager lists them for clarity. Never errors:
unreadable (no Slippi, AppImage Sys) → `available: false`.

**Response:** `{ success, available, codes: [{ name, creator }] }`

### GET /api/mex/codes/nucleus
The codes SSBM Nucleus makes itself, offered to any build in the codes
manager's code list, first in their category (today: Now Playing). New projects already start
with them; this is how an existing build adds one. `iniName` + `creator` is the
header the code takes in `codes.ini`; `conflict` is a reason not to add it to
the open build (Now Playing on a build that already has ACE's
`bgm_display.dat` would show the song twice), else null.

**Response:** `{ success, codes: [{ id, title, iniName, creator, description, source, conflict }] }`

### POST /api/mex/codes/project/sync
Replace the project's code list with the FULL desired state. Pre-validates
everything, honours the `enabled` flag of default codes (the Slippi SSS fix
can be turned off), and keeps a default code omitted from the list as a
DISABLED entry so export does not re-add it enabled; then runs `mexcli sync-codes` under `mexcli_lock` to
rewrite `files/codes.ini` and recompile `files/codes.gct`. Disabled codes stay
listed in the ini but are excluded from the gct.

**Body:** `{ "codes": [{ name, creator, description, source, enabled }] }`

**Response:** `{ success, applied, enabled, gctBytes }` (400 with per-code errors on invalid input)

---

## Costumes Blueprint

### GET/POST /api/mex/replace-vanilla/{fighter}/{index}

GET returns a project/fighter-state `version` and the destination's original
vanilla file/color identity. POST accepts `{version, costumePath,
pairedCostumePath?}`. Paths must resolve inside the vault. The optional paired
path replaces Nana at the same index as Popo in one `replace-costume` MexCLI
save. Zelda/Sheik replacements affect only the selected half; indices and team
assignments do not move. Stale versions return 409. Invalid source packages or
destinations fail before project publication.

`GET /fighters/{fighter}/costumes` now includes `vanillaTarget` (null for
unrelated imported slots), `replacesVanillaFile`, and `visibilityIndex`.
Replacement retains its original slot identity across later replacements and
reorders. Ordinary costumes retain source visibility metadata; Falcon is
strictly converted to the destination skeleton and root symbols. Active vault
portraits are included through the existing temporary install-copy helper.

Popo's version also covers Nana's data to reject stale paired replacements.
Kirby replacement remaps each donor's copy-costume row by source color without
changing table length. Jigglypuff retains its source hat symbols and lookup;
replacement adds the project's required `Nucleus: Jigglypuff source costume
dynamics` code and corrects the recognized m-ex hat-loader fighter-kind read.
This makes the separate hat and its cloth physics follow the source even in
neutral destinations. Export-time hat repair honors that lookup too. The patch
is project-local and idempotent; unknown core signatures or conflicting hooks
abort before saving. See upstream [Puff Hat Symbol.asm](https://github.com/akaneia/m-ex/blob/master/asm/m-ex/MnSlChrData%20-%20Costume%20File%20Names/Puff%20Hat%20Symbol.asm)
and the local `JigglypuffReplacementCompatibility` implementation.

### POST /api/mex/import
Import costume to MEX project. The install carries the skin's **active**
portrait (Portraits / "Manage CSPs" pick): when an alternate is active, or the
zip has no `csp.png` but the vault has one, MexCLI is handed a temp copy of the
zip with that `csp.png` (`core/active_portrait.py`); the vault zip is never
modified. Falcon costumes are neutralized the same way first. `/import-batch`
does the same per item.

**Body:**
```json
{
  "fighter": "Fox",
  "costumePath": "storage/Fox/<skin id>.zip"
}
```

### POST /api/mex/remove
Remove costume from project.

**Body:**
```json
{
  "fighter": "Fox",
  "costumeIndex": 5
}
```

### POST /api/mex/reorder
Reorder costume slots by SWAPPING two indices. One full workspace recompile per
call — prefer `/reorder-batch` for anything driven by drag-and-drop.

**Body:**
```json
{
  "fighter": "Fox",
  "fromIndex": 3,
  "toIndex": 1
}
```

### POST /api/mex/reorder-batch
Apply many costume MOVES in ONE workspace recompile. A move is a splice
(remove + insert) — what a drag actually does — so one drag is one move
regardless of distance. Moves apply in order, each against the list as it
stands after the previous one.

This is what the CharacterMode costume list uses. Reordering via `/reorder`
required replaying a drag as |to−from| adjacent swaps, i.e. that many full
recompiles (~3s each) for a single drag.

**Body:**
```json
{
  "moves": [
    {"fighter": "Fox",   "fromIndex": 15, "toIndex": 0},
    {"fighter": "Falco", "fromIndex": 2,  "toIndex": 1}
  ]
}
```

Ice Climbers (Popo/Nana), Kirby hat tables and G&W color rows move in lockstep,
same as `/reorder`.

---

## G&W Blueprint

Mr. Game & Watch color mods — his colors are engine-side (m-ex GawColors
table), not in his DAT. See [Extras-And-Effects-Workflow.md](../wiki/Extras-And-Effects-Workflow.md).

### POST /api/mex/gaw/create
Create a G&W color mod in the vault (renders CSP/HD/stock, writes the costume
zip with a `gaw.json` sidecar, registers the skin with `gaw_colors` metadata).

**Body:**
```json
{
  "name": "Lavender",
  "fill": "#FFB48EAD",
  "outline": "#80FFFFFF"
}
```

### GET /api/mex/gaw/preview-source
The vanilla black G&W CSP (PNG) — recolored client-side for the creator
modal's live preview.

---

## Export Blueprint

### POST /api/mex/export/start
Start ISO export (async).

**Body:**
```json
{
  "filename": "MyMod.iso",
  "cspCompression": 0.8,
  "useColorSmash": true,
  "texturePackMode": false,
  "slippiDolphinPath": "/path/to/slippi"
}
```

**Response:** `{ success, message, filename, artifactId, buildId }`.

The export runs as an `iso_export` job whose id is `artifactId`: progress and
the outcome are its record (`job` events, `GET /api/jobs/{artifactId}`). A
`done` record's `result` is `{ filename, path, texturePackMode, buildId,
totalCostumes, warnings[], cspCompression, cssBytes, costumeCount }` --
`warnings` carries anything MexCLI had to do to keep the build bootable (the
character-select memory guard compresses portraits when `MnSlChr.usd +
mexSelectChr.dat` would exceed 7.8 MB and freeze the select screen);
`cspCompression` is the portrait quality that actually shipped. A failed export
is a `failed` record with its `error`, answered like any other record.

The job ends `done` only after the result is verified: a MexCLI run that
reports an error JSON (even with exit code 0) or exits cleanly without writing
the ISO fails the job instead. The job is a critical operation, so app shutdown
waits for it. It owns its staged `.part.iso` and, in texture-pack mode, the
temporary project copy; its cleanup removes them however it ends, or on the
next start if Nucleus closed mid-export.

The native ISO exporter drains stdout and stderr concurrently, retains up to
65,536 characters of stderr text, and has a two-hour deadline. Pipe failures and timeouts
fail the export and stop its owned child process.

### POST /api/mex/export/save
Copy an exported ISO from `output/` to an absolute destination path. The
Electron viewer's Save button uses this (native save dialog picks the
destination) instead of streaming the download through Chromium: the copy is
registered as a critical operation, so app shutdown waits for it — a killed
stream used to leave a truncated ISO that boots to a black screen.

Every start returns an `artifactId` and writes to a unique staged file. Only a
successful, nonempty output is published under `output/artifacts/<artifactId>.iso`.
Save and Download require that export's `done` job record and its file under
`output/artifacts/`; a filename alone is insufficient. Startup cleanup empties
`output/artifacts/`, so after a restart a new export is needed.
Display filenames must be single-segment `.iso` basenames. Save stages a unique
sibling at the chosen destination before replacement. The ownership marker
(`<name>.nucleus-build.json`) is written as pending before the replace and final
after it, so a copy whose final marker failed to write is still Nucleus's: the
save's own retry, or a later Save, finishes the marker instead of refusing the
file as foreign.

**Body:** `{ "artifactId": "...", "filename": "build.iso", "destination": "C:\\path\\build.iso" }`

**Response:** `{ "success": true, "path": "...", "bytes": 1459978240 }`
**Errors:** `409 { success, status, error }` while the job is queued or
running, or when it ended `failed`, `cancelled` or `interrupted`,
`404` (unknown artifact), `400` (invalid ID/name/destination), `500 { error }`.

### GET /api/mex/export/download/{artifactId}/{filename}
Download that completed ISO (browser fallback outside Electron). Registered as
a critical operation while streaming. Startup cleanup removes old managed
artifacts; restarting the backend requires a new export.

---

## Melee Unlocked Blueprint

Fighter plugins for Melee Unlocked's Source Port (`projects/routes/melee_unlocked.py`, engine
`projects/install/melee_unlocked.py`). The Source Port runs the game natively, so a custom fighter's
compiled PowerPC cannot run there: it loads `<name>.mufighter` from a `fighters` folder beside its game
library instead, built from the fighter's MexTK C. That C lives in the Vault at
`custom_characters/<slug>/code/` (`*.c`, `*.h`, optional `native.edits`). A fighter zip with a `code/`
folder brings it in on import, and the fighter-port tool's packages carry one.

A plugin is native code the game runs, so the export builds only source a person vouched for
(`projects/install/fighter_source.py`): source **attached** in the window (`POST .../source/{slug}`), or
imported source the user **confirmed** in the window for that fighter (`POST .../source/{slug}/confirm`).
Source that came in a package (a website download, a `nucleus://import` link, a zip from disk) is recorded
as **untrusted** with where it came from and when; source with no record (from before the records) is
untrusted too. The records live in `fighter_source_trust.json` beside `custom_characters/`, out of reach of
anything a package carries, and each is bound to the sha256 of the source, checked again on the bytes staged
for the kit: source that changed after it was confirmed is untrusted again. Untrusted fighters are listed as
not built, with the reason. The manifest the kit reads is checked too: a fighter name with a control
character or line break, or a data file that is not `PlXx.dat`/`PlXx.usd`, fails that fighter.

The export needs a fighter plugin kit (made by Melee Unlocked's `tools/mexft/mexft_kit.py`) and a
MinGW-w64 GCC; the frontend keeps both folders in `localStorage` (`melee_unlocked_kit_path`,
`melee_unlocked_gcc_bin`) and sends them in the body. The kit's Python tools run in a child process
that is the backend program itself in its `--mu-kit` mode (`projects/install/mu_kit_runner.py`), so
the installed app needs no Python of its own: the child gets no backend token, no window key and no
other `NUCLEUS_*` setting (`core/child_env.py`), and is stopped with the compiler it started after 10
minutes per fighter.

Every route but the fighter list needs the window's own key, `X-Nucleus-UI-Key` (`core/ui_channel.py`):
403 without it or from an agent, 503 when the backend has no key to check. Every folder (`kitPath`,
`gccBin`, `destination`, `folder`) must be a drive-letter path on this computer (`core/path_safety.py`
`local_path`): a share, a device path or the NT namespace is a 400.

### GET /api/mex/melee-unlocked/fighters
The open project's custom fighters, by whether a plugin can be built.

**Response:** `{ success, buildable: [{name, slug, plugin}], unconfirmed: [{name, slug, plugin, origin,
recordedAt, sha256, reason, confirmText}], withoutSource: [{name, slug, plugin}] }`. `unconfirmed` are the
fighters whose source came in a package and was not confirmed; `confirmText` is the question the window
asks (it names the fighter and the origin) and `sha256` the source it is about.

### POST /api/mex/melee-unlocked/export
Start a `melee_unlocked_export` job that builds the plugins into `<destination>/fighters/`. A fighter
that fails to compile is reported and does not stop the others. Nothing in the project or an exported
ISO changes.

**Body:** `{ "destination": "C:/out", "kitPath": "...", "gccBin": "..." }`

**Response:** `{ success, job_id }`. Follow the job at `GET /api/jobs/{job_id}` or its `job` events:
`progress` and `detail` ("Building Shulk (3 of 15)") per fighter, and the result
`{ abi, folder, built: [{name, slug, file, path, size}], failed: [{name, slug, error}], unconfirmed: [{name, slug,
origin, reason, ...}], withoutSource: [{name, slug}] }`.
400 with `error` when the kit or compiler folder is missing or wrong (checked before the job starts);
409 with the running job's `job_id` when an export is already running.

### POST /api/mex/melee-unlocked/verify
Check the two folders. **Body:** `{ kitPath, gccBin }` (either may be empty).

**Response:** `{ success, kit: {valid, abi | error}, compiler: {valid, error} }`.

### POST /api/mex/melee-unlocked/source/{slug}
The attach action: copy the C in a folder (or its `code` subfolder) into that Vault character, replacing what
was there, recorded as attached by the user (built without a question). **Body:** `{ "folder": "..." }`.
**Response:** `{ success, files }`.

### POST /api/mex/melee-unlocked/source/{slug}/confirm
Allow the export to build that character's imported source. **Body:** `{ "sha256": "..." }`, the digest the
window showed with the question (`unconfirmed[].sha256`). **Response:** `{ success, source: {state:
'confirmed', sha256, origin, recordedAt, confirmedAt} }`; 409 `source_changed` when the source is no longer
the one shown (nothing is confirmed).

### DELETE /api/mex/melee-unlocked/source/{slug}
Remove the character's stored source and its record.

## Play Blueprint

Play, the launcher for Melee Unlocked (`play/routes/play.py`; engines `play/shelf.py`, `play/client.py`,
`play/launch.py`). Gated: `NUCLEUS_PLAY=0` (every packaged build, for now, except a local Play test build: docs/dev/PREVIEW-0.9.0.md "Play test builds") and the routes do not exist.
Windows only for now: elsewhere the shelf answers `platform.supported: false` and nothing starts.

Every `{id}` is an entry id looked up on the shelf: `retail` and `vanilla` (the built-in games) or a
12-character id the shelf generated. No route builds a path from a request string. Every route that is
not a GET (it starts a program, changes the saved Melee Unlocked folder or changes the shelf) needs the
window's own key, `X-Nucleus-UI-Key` (`core/ui_channel.py`): 403 without it or from an agent, 503 when
this process has no key to check.

### GET /api/play/shelf
**Response:** `{ success, entries: [entry], platform: {supported, message}, client: {set, valid, error,
folder, version, engines: {source, compat}, ...}` (the `/api/play/client` fields below)`, retailIso: {set,
missing}, gameSettings: {exists, seededAt, canSeed}, running: id | null }`. `retailIso.missing` is the path the
Melee ISO was recorded at when that file is gone (the cards name it), else null. `gameSettings` is Play's one shared
`port-settings.ini`: whether it exists, when it was copied from the Melee Unlocked folder's own one (the first
game, the settings window or a replay copies that file in once, `shelf.seed_game_settings`, and never again,
even if Play's is deleted), and `canSeed`, whether the next start will. An entry is
`{ id, name, description, builtin, removable, hasCover, disc: {kind: retail|owned, size?, sha256?},
targets: {mu: {available, reason?}, dolphin: {...}}, defaultTarget, lastTarget?, engine: source|compat,
engineReason?, engineChoice: auto|source|compat, options: {vanilla?, engine?}, origin?, createdAt?,
fighters?: [{name, file, code: none|own|unknown, why}] }`; never a path. `fighters` are the ones an
added game's m-ex disc adds, read when it was added (`play/routing.py`: no `ftFunction` symbol and every
MxDt function in the retail code means no code of its own). `engine` is the one a launch would use now:
the Source Port unless a fighter with code has no plugin of its name in the game's own fighters folder
(`games/<id>/fighters`; the Melee Unlocked folder's own `fighters` never counts), then the compatibility
engine, with `engineReason` saying which; or what `engineChoice` forces. When the client's facts are
known, a plugin counts only if its `mu_fighter_plugin` record (`MUFT`, format, 16-byte ABI id in the
`.mufighter` COFF object) matches the client's `pluginFormat` and `pluginAbi` (one built for another
version is named as such in `engineReason`), and a fighter in the client's `linkedFighters` needs none.

### GET /api/play/client · POST /api/play/client · POST /api/play/client/verify
The Melee Unlocked folder every game starts from. **Body:** `{ "folder": "C:\\Games\\MeleeUnlocked" }`.
It must be a drive-letter path on this computer (no share, `\\?\`, `\\.\` or `\??\` path) holding
`melee_source.exe`, `melee_game.dll` and `Sys\`, and not overlap Play's own data folder. POST saves it
(`""` forgets it; 400 with `error` when it is not one), `/verify` only checks it:
`{ success, valid, error, folder, version, engines, engine, cpuBaseline, cpuSupported, pluginFormat,
pluginAbi, linkedFighters, features: {fighters_dir, no_remember_iso, no_crash_dialog, no_dialogs},
playback }`. The facts come from `melee_source.exe --print-info` (`play/client.py` `read_info`): run
as an argument list, never through a shell, with Nucleus's settings and secrets out of its environment,
no window, in Play's own `data/_info` folder, and ended after 10 seconds; only a program whose file
names `--print-info` is started (the compatibility engine never is). The answer is cached in
`<data>/play/client-info.json` under the program's size and modification time, so it runs again only
when the program changes (a failure is kept for five minutes). A folder whose client lacks
`fighters_dir` or `no_dialogs` (older than 1.0.6) is refused as too old. `cpuSupported: false` (no
AVX2) stops every Melee Unlocked launch with that sentence; Dolphin still plays. `playback` is whether
the folder has `SysPlayback\` (replays from Tracker).

### GET /api/play/account
The Slippi account the games sign in with, from the netplay `user.json`: `{ success, signedIn,
displayName, connectCode }` (nothing else from that file).

### POST /api/play/launch/{id}
Start a `play_launch` job. **Body:** `{ target?: "mu" | "dolphin", slippiPath? }` (target defaults to
the entry's last one; `slippiPath` is the Slippi Dolphin folder, for the Dolphin target). The program is
always `melee_source.exe` (or `melee_port.exe` for the compatibility engine) inside the saved folder,
started detached with the command line of Melee Unlocked's launch contract and without Nucleus's own
environment variables (`MELEE_FIGHTER_PLUGINS` is never set or inherited). Every launch passes
`--fighters-dir`: the game's own `games/<id>/fighters` when it has one, else `none` (the built-in Nucleus Unlocked
and Vanilla always `none`), plus `--no-remember-iso` and `--no-dialogs`; a program that predates those
options (the compatibility engine of a 1.0.6 install) does not get them. The built-in Nucleus Unlocked and Vanilla
both pass `--replay-dir` the folder Tracker indexes (`launch.tracker_replay_folder`: the replay folder
chosen in Tracker when it still exists, else the Slippi Launcher's `rootSlpPath`, else `Documents\Slippi`;
when that folder does not exist, the game's own `data/<id>/Replays`), so their games show up in Tracker;
Nucleus also passes `--user-dir` the netplay Dolphin's `User/Slippi`
(the user's Slippi account), Vanilla its own `data/vanilla/User/Slippi`. An added game keeps both in its
own data folder. The game's console output goes to `melee_port_console.txt` in its data folder. **Response:** `{ success, job_id }`; 400 with a sentence
saying what to set up first; 404 for an id not on the shelf; 409 with `job_id` while a game (or the
settings window) runs. The job's `extra.phase` is `launching` then `running` (with `extra.pid`, updated
when the game restarts itself); its result is `{ outcome: quit | disc_error | refused | cpu | fatal |
crashed | stopped | started, exitCode, message, detail, crashed, relaunched }`. Exit codes: 0 and 4
`quit`, 1 `disc_error`, 2 `refused`, 3 `cpu` (no AVX2), 70 `fatal`, an exception code `crashed`; a crash
file newer than the launch also means `crashed`. `message` says it in words with `detail`, the useful
line from the game's console output, log or crash file, and for a fatal error or crash the folder the
log is in.

**Across a restart of Nucleus:** while a game (or the settings window, or a replay) runs, the job keeps
`<data>/play/running.json`: the session (`entryId`, or `replay` / `settingsWindow`) and the process's
`pid`, start time (`created`) and program (`exe`), read from the live process and rewritten when the game
restarts itself; it is removed when the watch ends. At startup (`app.py`, after the job recovery,
`launch.reattach`) a record whose pid is a live process with the same start time and the same program
starts a new `play_launch` job watching it (`params: {entryId, target: mu, reattached: true}`, phase
`running` at once), so the shelf shows that game running and the usual end handling follows; any
mismatch (a pid Windows gave to another program, the game gone, the entry removed, a malformed record,
not Windows) drops the record and starts nothing. The folders the job reads the log and crash file from
come from the session, never from the record. Its result carries `reattached: true`. Not recovered: the
restarts counted before Nucleus closed, a game that ended while Nucleus was closed (nothing is reported),
and the exit code of one that ended in the moment between two looks (`exitCode: null`, read as a quit).
Dolphin is never watched, before or after a restart.

### POST /api/play/settings-window
The game's own settings window, on the shared settings file (a `play_launch` job with
`params.settingsWindow`; the first start copies the Melee Unlocked folder's own settings in, once). 409 while a
game runs.

### GET /api/play/replay · POST /api/play/replay
"Watch in Melee Unlocked" for a Tracker replay row. GET (no key needed) answers `{ success, available,
reason }`: whether a replay could start now (the saved folder verified, its processor supported, a
`SysPlayback\` folder in it, the user's Melee ISO set) and, when not, the sentence saying why. POST
(window only) **Body:** `{ path }`: the replay, which must be one Tracker indexed (the rule
`/api/nucleome/replays/watch` uses), on this computer (the request-path gate: no share or device path),
a `.slp` file, and within `slp_meta.peppi_refusal`'s size and shape checks (slp_guard's first step).
Starts a `play_launch` job (`params: {entryId: null, replay: true, file}`) running `melee_source.exe
--iso <disc> --replay <file> --sys-dir <folder>\SysPlayback` with no installed fighters
(`--fighters-dir none`), `--no-remember-iso`, `--no-dialogs`, the shared settings file and shader
cache, and its log, console output and saves in Play's `data/_replay`. The viewer records what it
shows: `--replay-dir` is `data/_replay/Replays`, whose `.slp` files are cleared before each replay, so
nothing is added to the user's Slippi replay folder or to Tracker. **Response:** `{ success, job_id }`;
400 with the reason (not set up, no SysPlayback, not a replay file, refused by the shape checks, not
on this computer); 404 for a path Tracker has not indexed; 409 while a game runs. The result is the
usual one, read as a replay: exit 0 or 4 `quit`, 1 "could not open the replay", a crash with the crash
file's first line.

### POST /api/play/reveal/{id}
Open the entry's data folder (saves, `melee_port.log`, crash files) in the file manager.

### POST /api/play/shelf/add
Put a finished ISO export on the shelf (a `shelf_add` job, `play/adding.py`). **Body:** `{ artifactId,
name?, description? }`: `artifactId` is the export job's id (`/export/start`); the ISO's path comes from
that job's record and must be in `output/artifacts`. The disc is hard-linked into the entry's folder
(copied when that is not possible; 507 in the job's error when the drive is too full), hashed, and its
banner becomes the cover, and the fighters the disc adds are checked for code of their own (which
decides the engine). No fighter code is built. **Response:** `{ success, job_id }`; 404 when the
export is not finished (or Nucleus restarted since), 400 for a texture-pack build or a disc that is not
GALE01, 409 while another add runs. The job's result is `{ entryId, how: linked | copied, name }`; until
the entry is stored the job owns its folder, which a failure, a Cancel or a restart removes.

**Cover:** sent as multipart instead of JSON (the same fields as form fields) with a `cover` picture,
it becomes the cover: 413 over 8 MB, 400 for one that does not decode (PNG, JPEG, GIF or WebP, at most
6000 x 6000), scaled to 1024 px at most and written re-encoded as PNG inside the entry's own folder (a
folder that resolves outside `games/` through a link is refused). The picture is bytes in the request,
never a path. Without one: the Vault item's picture, else the disc's banner, else the shelf's plain card.

**Same game:** an added game whose stored name matches `name` (ignoring case; the built-in Nucleus Unlocked and
Vanilla never match) makes the add answer 409 `{ code: "already_on_shelf", existing: {id, name} }` before
any work starts. `replace: <that id>` in the body replaces it instead: the new build goes into a folder of
its own beside the old one, and one write of `shelf.json` swaps the entry over to it (the entry records
`files`, the folder its game files are in), then the old folder is removed. Kept: the entry's id (so its
saves and memory card in `data/<id>`), name, description (unless a new non-empty one is given), engine
choice, last target (while still offered), place on the shelf, its `fighters` folder (copied across) and
its cover (unless a new one is given). 400 replacing a built-in game, 404 for an id not on the shelf, 409
while that game runs (asked when the add starts and again just before the swap; a launch planned before
the swap is refused with "Press Play again"). A failed, cancelled or interrupted replace leaves the old
entry exactly as it was. The result adds `replaced: true`.

### GET /api/play/shelf/same?name=
The added game an add called `name` would replace: `{ success, existing: {id, name, running} | null }`
(the export page asks before it builds, so the question comes before the wait). No key needed.

**From the Vault:** `{ patchId | bundleId, name?, description? }` (exactly one of `artifactId`,
`patchId`, `bundleId`; 400 otherwise) puts a Vault patch or bundle on the shelf. The id is looked up in
the Vault's own index (404 when it is not there or its file is gone); the file's path is made from the
indexed id, never the request. Needs the user's Melee ISO (400 without it); the job checks it is the
unmodified disc, then decodes the patch onto it straight into the entry's folder with the same decode
as Play in Dolphin (`projects/install/xdelta.decode_patch`; Cancel ends xdelta3), refuses a result
that is not GALE01, hashes it and reads its fighters. The Vault item's name, description and picture
(as the cover, else the disc's banner) are copied. A bundle goes through the Vault's bundle checks
(`check_bundle`: every member's name and size before any is read; 400 for one that fails) and its
`textures/*.png` are kept in the entry's `textures` folder; the Dolphin target loads them into Slippi's
`Load/Textures/GALE01/ssbm-nucleus/<build_name>` and turns HD textures on, as Play in Dolphin does for
the bundle. `how` is `built`; `origin` is `{kind: patch | bundle, name}`. The entry keeps no link to
the Vault: editing or deleting the Vault item later changes nothing on the shelf. An entry from a bundle
shows `textures: <count>`.

### PATCH /api/play/shelf/{id} · DELETE /api/play/shelf/{id}
Rename or describe an added game (**Body:** `{ name?, description?, engine?: auto | source | compat }`,
name and description stored as plain text; `engine` is the engine choice in its menu) or remove it with
its disc and saves. 400 for the built-in games; 409 removing a game that is running.

### GET /api/play/shelf/{id}/cover · POST /api/play/shelf/{id}/cover
An added game's cover (PNG). POST takes multipart `cover` (8 MB at most); it is decoded, scaled to
1024 px at most and stored re-encoded as PNG; anything that does not decode is refused. GET for the
built-in `vanilla` is the banner of the user's own disc at its own 96x32 (the page scales it by whole pixels;
`play/adding.py disc_banner`: read from the disc
the first time it is asked for, kept as `<data>/play/disc-banner-<stamp>.png`, 404 when there is no disc
or no banner); the shelf says `hasCover: true` for it whenever Nucleus knows the disc. The built-in
`retail` (named Nucleus Unlocked) has no cover: the Play page draws its picture.

## Storage Costumes Blueprint

### GET /api/mex/storage/metadata
Get the storage vault `metadata.json` (all characters/stages/custom content).

### GET /api/mex/storage/costumes
List all costumes in vault.

**Query:** `?character=Fox` (optional filter)

**Response:**
```json
{
  "success": true,
  "costumes": {
    "Fox": {
      "skins": [
        {
          "id": "abc123",
          "color": "Green Fox",
          "costumeCode": "PlFxGr",
          "cspUrl": "/storage/Fox/abc123/csp.png",
          "stockUrl": "/storage/Fox/abc123/stock.png",
          "slippiSafe": true
        }
      ],
      "folders": []
    }
  }
}
```

### POST /api/mex/storage/costumes/delete
Delete costume from vault. Serialized with costume import publication under the
metadata write lock. Removes every legacy non-folder row with the requested
identity and its owned archive/portrait files, leaving other identities intact.
An identity already absent returns 404; the frontend retires that stale selection.

**Body:**
```json
{ "character": "Fox", "skinId": "abc123" }
```

### POST /api/mex/storage/costumes/rename
Rename costume.

**Body:**
```json
{ "character": "Fox", "skinId": "abc123", "newName": "Cool Fox" }
```

### POST /api/mex/storage/costumes/update-csp
Update CSP image (multipart form).

**Form Data:**
- `character`: "Fox"
- `skinId`: "abc123"
- `csp`: (file)
- `isHd`: "true" (optional)

### POST /api/mex/storage/costumes/generate-csp
"Retake CSP": re-render a vault costume's portrait headlessly with whichever
pose is currently active for the skin. Two-step so nothing is overwritten
without confirmation. The preview is rendered at 4x; apply derives the in-game
SD portrait from it and saves **both** SD (`<id>_csp.png` + zip `csp.png`) and
HD (`<id>_csp_hd.png`), or overwrites the active pose alternate in place.

**Body (preview, writes nothing):**
```json
{ "character": "Fox", "skinId": "abc123" }
```
**Response:** `{ "success": true, "poseName": "Default", "dataUri": "data:image/png;base64,..." }`

**Body (apply):**
```json
{ "character": "Fox", "skinId": "abc123", "apply": true, "imageData": "data:image/png;base64,..." }
```
**Response:** `{ "success": true, "cspUrl": "/storage/Fox/abc123_csp.png", "hasHd": true }`

Both bodies take an optional `"poseName"` (the Pose button on the costume's own
menu): that pose of the character's library is rendered instead of the active
one, and applying it files the picture as that pose's portrait (one per pose,
replaced in place) and makes it the portrait the costume shows. `null` is the
default pose: the original portrait is rewritten and shown again. A pose that
is not in the character's library is a 404; a named pose that cannot be
rendered is an error, never a default-pose picture.

### POST /api/mex/storage/costumes/batch-retake-csp
Vault-wide bulk retake (the **Bulk Retake CSPs** button above the character
grid). Renders each selected costume with its own active pose through one
warm CSP render pool and saves temporary previews; vault portraits stay unchanged. The client
reviews the before/after grid and applies the kept ones with `generate-csp`
(`apply: true`). One batch at a time (409 if one is running).

**Body:**
```json
{ "items": [ { "character": "Fox", "skinId": "abc123" }, { "character": "Marth", "skinId": "def456" } ] }
```
The legacy single-character form `{ "character": "Fox", "skinIds": ["abc123"] }` is still accepted.

**Response:** `{success, job_id, count}` (returns immediately). Follow the
`csp_retake` record through the shared job store. `extra.items` carries each
`{character, skinId, done, total, ok, poseName, previewUrl | error}`;
`result` is `{total, rendered, items}`. PNG bytes are never in job events.
Cancel through `/api/jobs/{job_id}/cancel`, checked between costumes.
The job owns its extraction and preview directory until success; failure,
cancellation and startup recovery remove it.

### GET /api/mex/storage/costumes/batch-retake-csp/{job_id}/{index}.png
Fetch one preview PNG for review or applying via `generate-csp`.

### DELETE /api/mex/storage/costumes/batch-retake-csp/{job_id}
Remove a finished retake's preview files after review.

### POST /api/mex/storage/costumes/{character}/{skin_id}/csp/manage
Manage CSPs (swap, remove, add, regenerate).

**Body (varies by action):**
```json
{ "action": "swap", "altId": 2 }
{ "action": "reset" }
{ "action": "remove", "target": "alt", "altId": 1 }
{ "action": "regenerate-hd", "scale": 4 }
```

### POST /api/mex/storage/costumes/update-stock
Update stock icon (multipart form).

### POST /api/mex/storage/costumes/retest-slippi
Retest for Slippi safety.

**Body:**
```json
{ "character": "Fox", "skinId": "abc123", "autoFix": true }
```

### POST /api/mex/storage/costumes/override-slippi
Manually override Slippi status.

**Body:**
```json
{ "character": "Fox", "skinId": "abc123", "slippiSafe": true }
```

### POST /api/mex/storage/costumes/reorder
Reorder skins in vault.

**Body:**
```json
{ "character": "Fox", "fromIndex": 0, "toIndex": 3 }
```

### POST /api/mex/storage/costumes/move-to-top
Move skin to top of list.

**Body:**
```json
{ "character": "Fox", "skinId": "abc123" }
```

### POST /api/mex/storage/costumes/move-to-bottom
Move skin to bottom of list.

### POST /api/mex/storage/folders/create
Create folder for organizing skins.

**Body:**
```json
{ "character": "Fox", "name": "Tournament Skins" }
```

### POST /api/mex/storage/folders/rename
Rename folder.

**Body:**
```json
{ "character": "Fox", "folderId": "folder123", "newName": "New Name" }
```

### POST /api/mex/storage/folders/delete
Delete folder (skins moved to root).

### POST /api/mex/storage/folders/toggle
Toggle folder expanded/collapsed state.

### POST /api/mex/storage/skins/set-folder
Assign skin to folder.

**Body:**
```json
{ "character": "Fox", "skinId": "abc123", "folderId": "folder123" }
```

---

## Storage Stages Blueprint

### POST /api/mex/das/scan-iso
Import stage variants from an ISO, including files inside `Gr*` folders.

**Body:** `{ "isoPath": "C:/build.iso" }`

Returns `success`, `imported`, `importedCount`, `byStage`, and `skipped`.
Imported entries contain `stageCode`, `stageName`, `name`, `id`, `source`, and
`screenshotUrl` when a preview is available. The HSD renderer creates 768×432
previews from the extracted DATs using a persistent worker. Preview failures
keep the imported stage; no Dolphin session is required. Known ISO-imported
variants are returned under `skipped`, with their saved image URLs. Rescanning
backfills missing previews while preserving existing screenshots.

### POST /api/mex/storage/stages/delete
Delete stage variant.

**Body:**
```json
{ "stageFolder": "Battlefield", "variantId": "abc123" }
```

### POST /api/mex/storage/stages/rename
Rename stage variant.

**Body:**
```json
{ "stageFolder": "Battlefield", "variantId": "abc123", "newName": "Night BF" }
```

### POST /api/mex/storage/stages/update-screenshot
Update screenshot (multipart form).

**Form Data:**
- `stageFolder`: "Battlefield"
- `variantId`: "abc123"
- `screenshot`: (file)

### POST /api/mex/storage/stages/render-screenshots
Vault-wide bulk stage preview render (the **Bulk Render Screenshots** button
above the stages grid). Draws each selected variant straight from its vault zip
with the offline HSD stage renderer through one warm render pool — no test ISO
build, no Dolphin, and no vanilla ISO / Slippi path. Vault images stay unchanged: the
client reviews the grid and saves the kept shots with `update-screenshot`. One
batch at a time (409 if one is running). Only the six competitive stages have a
calibrated camera; other stages report per-variant failures and are listed in
`unsupportedStages` (the variant listing carries the same fact as `canRender`).

**Body:**
```json
{ "variants": [ { "stageCode": "GrNBa", "variantId": "abc123", "name": "Night BF" } ] }
```

**Response:** `{ "success": true, "job_id": "...", "count": 1, "unsupportedStages": [] }` (returns immediately)

Follow the returned `job_id` (`stage_render`) through the shared job store.
`extra.items` carries `{stageCode, stageFolder, variantId, name, done, total,
ok, previewUrl | error}`. `result` is `{total, rendered, stopped, failures, items}`.
Cancel through `/api/jobs/{job_id}/cancel`; the current variant finishes and
remaining variants are skipped. A cancelled job retains completed previews in
`extra.items` and its summary in `extra.summary` for review. Interrupted and
failed jobs clean up their extraction and preview files.

### GET /api/mex/storage/stages/render-screenshots/{job_id}/{index}.png
Read a preview PNG for review or saving through `update-screenshot`.

### DELETE /api/mex/storage/stages/render-screenshots/{job_id}
Remove a finished render's preview files after review.


### POST /api/mex/storage/stages/set-slippi
Set Slippi safety status by hand (`true` / `false` set a manual override; an
explicit `null` clears the variant back to unknown).

**Body:**
```json
{ "stageName": "Battlefield", "variantId": "abc123", "slippiSafe": true }
```

### POST /api/mex/storage/stages/reorder
Reorder variants.

### POST /api/mex/storage/stages/move-to-top
Move variant to top.

### POST /api/mex/storage/stages/move-to-bottom
Move variant to bottom.

---

## Import Blueprint

### POST /api/mex/import/file
Unified import endpoint (auto-detects content type).

Character imports stage their archive and rendered assets privately, then choose
a unique identity against live metadata and existing files under the metadata
lock. Concurrent imports with the same base name receive separate identities;
failed publication attempts clean up their staged/published files.

**Form Data:**
- `file`: ZIP, 7z or RAR archive, a loose `.dat`/`.usd`/`.xdelta`/`.ssbm`, or an image (`.png/.jpg/.jpeg/.webp/.gif/.bmp`). 7z and RAR archives — uploads and container members alike — are repacked to a temp zip at entry and loose files are wrapped in one, so the whole pipeline behind detection only ever sees zips. RAR decoding goes through the bundled UnRAR binary (`utility/unrar*`, driven by `core/rar_tools.py`); a `.rar` upload is refused with 400 when that tool is missing or the archive cannot be read. The field may repeat: several files under `file` are packed into ONE archive and detected as a set (the app sends pictures picked together this way, so ten digit PNGs arrive as a glyph pack).
- `slippi_action`: "fix" | "import_as_is" (optional, for retry)
- `duplicate_action`: "skip" | "import_anyway" (optional, for retry; "skip" drops only the already-owned items — costumes, stage variants, or patches — and imports the rest of the archive)
- `custom_title`: Custom name (optional)
- `mod_type`: explicit kind, skipping detection (optional). Website links and the app's choice dialog send it: `effect` (with `effect_type`, optionally `character`), `effect_image` (with `character` + `effect_type`), `css_icon_grid`, `css_background`, `sss_background`, `css_doors`, `pause_screen`, `pause_picture`, `percent_font`, `ready_go`.

Detected kinds beyond costumes/stages/packages/patches: menu files (`MnSlChr`/`MexSelectChr` → icon grid, `MnSlMap` → SSS background, `GmPause` → pause screen, `IfAll` → percent font / Ready-Go), picture packs (ten digit images → percent glyph pack; three or more word banners → Ready-Go pack), loose pictures (ALWAYS answered with the choice dialog below — door texture / pause picture / an image-capable extra — with the detector's reading from the name and size preselected; the Menus page's "+" cards send `mod_type` and skip the question), and effect files (`Ef??Data.dat`, `PlFx.dat`-style character data): every extra type targeting the file is read with the extras offset system and diffed against the vanilla reference; each DIFFERING type imports as its own mod under that character's Extras, an all-vanilla file is refused (400), and with no vanilla ISO recorded the route asks.

**Response (choice dialog)** — the upload is genuinely ambiguous (a lone unnamed picture, a whole `MnSlChr` that could be the icon grid or the backdrop, an effect file with nothing to diff against). Re-post the same file with the chosen option's `hints` as form fields; batch imports take `default`:
```json
{
  "success": false,
  "type": "choice_dialog",
  "filename": "x.png",
  "question": "What is this picture (300×200)?",
  "options": [
    { "key": "pause_picture", "label": "Pause screen picture", "description": "Replaces the central graphic of the pause screen.", "hints": { "mod_type": "pause_picture" } },
    { "key": "css_doors", "label": "CSS door texture", "description": "Stretched onto the 128×200 character-select port door.", "hints": { "mod_type": "css_doors" } }
  ],
  "default": "pause_picture"
}
```

Menu-mod responses are `{ type: "menu_mod", menu_mod_type: <kind>, mods: [...], imported_count, message }` and effect responses `{ type: "effect", imported_count, effects: [...], message }`; `message` ends with where the mod landed ("— Menus › Character Select › Doors", "— Characters › Fox › Extras").

Falco side-B also recognizes validated static, untextured replacement afterimage
graphs (Spooky Phantasm), including automatic detection without a vanilla
reference. Stored `format: "sideb_model"` mods carry
`modifications.sideb_model: {version: 1, sha256}` and the donor DAT path.
The signature is independent of DAT pointer layout. Website-tagged imports and
duplicate detection use the same graph classification. Other fighter content
in the donor is not part of this extra.

Stage skins are recognised as `Gr<Code>.dat` or `.usd` for any of the six
tournament-legal codes. Pokemon Stadium additionally accepts the
per-transformation **bundle** shape a Nucleus Stadium export produces, where the
base file is named after the VARIANT rather than the stage:

```text
Minecraft.dat            <- the base skin (no stage code in the name)
Minecraft/GrPs1.dat      <- fire / grass / water / rock, all four required
Minecraft/GrPs2.dat
Minecraft/GrPs3.dat
Minecraft/GrPs4.dat
```

The sibling folder is what identifies it; the whole thing imports as ONE
Stadium variant with `transformation_skins: 4`, and `GrPs1`-`GrPs4` are never
treated as variants of their own. A partial form set is not a bundle (the
runtime loader probes `GrPs1` and then switches all four paths at once).

Container zips (archives whose members are themselves `.zip`/`.7z`/`.rar` archives — e.g. a zipped skin folder) are recursed into, two levels deep. Inner archives run the same detection cascade with Slippi issues auto-fixed and owned duplicates auto-skipped (a container import is treated as a batch, so no dialogs). `.7z` and `.rar` members are repacked to a temp zip first; one that cannot be opened is reported in `failed`.

**Response (character):**
```json
{
  "success": true,
  "type": "character",
  "imported_count": 1,
  "skipped_count": 0,
  "fixed_count": 0,
  "costumes": [{ "id": "abc123", "character": "Fox", "color": "Green", "csp_source": "provided" }]
}
```

**Response (Slippi dialog):**
```json
{
  "success": true,
  "type": "slippi_dialog",
  "message": "This costume is not Slippi safe. Choose an action:",
  "costumes": [{ "path": "...", "character": "Fox", "color": "Green" }]
}
```

**Response (container zip):**

Successful costume entries include the exact created vault `id`. Container responses
also aggregate `costumes` from their inner archives, so consumers can resolve saved
CSPs and stock icons without guessing names or including unrelated imports.

```json
{
  "success": true,
  "type": "multi",
  "types": ["character", "stage"],
  "imported_count": 42,
  "skipped_count": 3,
  "fixed_count": 5,
  "units": [{ "name": "fox pack.zip", "type": "character", "imported_count": 4, "skipped_count": 0 }],
  "failed": [{ "name": "old pack.rar", "type": "rar", "error": "could not be opened as a rar archive" }],
  "message": "Imported 42 item(s) from skins.zip — auto-fixed 5 costume(s) for Slippi — skipped 3 already owned — 1 file(s) not imported (…)"
}
```

---

## Mod Export Blueprint

### POST /api/mex/storage/costumes/export
Export costume as ZIP.

**Body:**
```json
{ "character": "Fox", "skinId": "abc123", "colorName": "Green Fox" }
```

### POST /api/mex/storage/stages/export
Export stage as ZIP.

**Body:**
```json
{
  "stageCode": "GrBf",
  "stageName": "Battlefield",
  "variantId": "abc123",
  "variantName": "Night BF"
}
```

### GET /api/mex/export/mod/{filename}
Download the exported mod ZIP using the exact `filename` returned by either
export endpoint. Each export has a unique lookup filename, so simultaneous
exports with the same display name remain independent. `Content-Disposition`
suggests the readable name without the lookup token.

GET serves the complete archive with `Content-Length` and `Cache-Control:
no-store`; Range and conditional requests do not produce partial responses.
HEAD inspects it without consuming it. Cleanup runs after all active stream
handles release the archive, including interrupted downloads. Create another
export to retry after cancellation. Invalid path segments/non-ZIP names return
400; missing files or symlinks return 404.

---

## DAS Blueprint (Dynamic Alternate Stages)

### GET /api/mex/das/status
Whether DAS is set up in the open project. A stage counts in `installedStages`
only when its root file is the DAS loader itself (`das_loaders.has_das_loader`:
the patch's target bytes) and its variants folder exists; a folder alone does
not work in game. `installed` is true once DAS was set up at all (any stage
folder), and `missingStages` then lists the stages still without a loader (an
install that found no vanilla source for them). The Stages tab shows those with
an **Install Again** button.

**Response:**
```json
{
  "success": true,
  "installed": true,
  "installedStages": ["GrOp", "GrSt", "GrNBa", "GrIz", "GrNLa"],
  "missingStages": ["GrPs"],
  "totalStages": 6
}
```

### POST /api/mex/das/install
Install DAS framework to project. Each stage's loader replaces its root file.
Every loader is rebuilt from the user's own vanilla root (the project's, or the
recorded ISO's) with the shipped `<root>.xdelta`, e.g. `GrNBa.dat.xdelta`
(`projects/install/das_loaders.py`). A stage with no vanilla copy found is
skipped, the others still install, and the response carries `warning` (shown by
Create Project and the Stages tab, `projects/stages/dasInstall.js`).

### GET /api/mex/das/stages
List all DAS-supported stages.

### GET /api/mex/das/stages/{stage_code}/variants
Get variants for specific stage.

For Stadium (`GrPs`), legacy runtime stems are checked before listing. Safe
case-only differences (including `vanilla`) are left unchanged. Normalized-name
collisions use salted, length-bounded stems and preserve transformation sidecars.
Allocation stops with an error after 1,000 occupied candidates rather than
retrying indefinitely; a failed sidecar move rolls the associated DAT rename back.

### GET /api/mex/das/storage/variants
List variants in storage (metadata order, inline `type:'folder'` rows; each
variant carries `date_added` for the vault's Date sort — `null` for disk-only
zips with no metadata entry).

**Query:** `?stage=GrBf` (optional filter)

### POST /api/mex/das/import
Import DAS variant to project.

**Body:**
```json
{ "stageCode": "GrBf", "variantPath": "/path/to/variant" }
```

Pokemon Stadium variants (`GrPs`) are run through the transformation-
visibility repair (`backend/vault/importing/stadium_transform_fix.py`) on import. Separable
duplicate geometry is relocated, while welded playfields are conservatively
split into the model group the engine hides with the normal form. The response
carries a `transformFix` object (`status`: `repaired` | `clean` | `flagged` |
`skipped`, plus `actions` / `notes`). `flagged` means no safe classification
was available or the archive could not be decoded; those responses add
`"recommendation": "freeze"` (`vault/importing/stadium_freeze.py` can freeze the
build's transformations; no route exposes it). The stage-variant UI
surfaces this result after both single and batch imports.

For per-variant Stadium transformation skins, the variant ZIP may also contain
a complete `GrPs1.dat` through `GrPs4.dat` set (the members may live in any ZIP
subdirectory). Nucleus installs them beside the normal archive using this
layout:

```text
files/GrPs/<NormalizedVariantName>.dat
files/GrPs/<NormalizedVariantName>/GrPs1.dat
files/GrPs/<NormalizedVariantName>/GrPs2.dat
files/GrPs/<NormalizedVariantName>/GrPs3.dat
files/GrPs/<NormalizedVariantName>/GrPs4.dat
```

The response includes `transformationSkins` with `status: "installed"` and
`count: 4`. Partial sets are rejected with
`reason: "incomplete_stadium_transformations"`. Variants without sidecars
continue to use the build's shared root transformation files. Rename and remove
operations carry the sidecar directory with the normal variant.

### POST /api/mex/das/remove
Remove DAS variant from project.

### POST /api/mex/das/rename
Rename DAS variant file.

---

## Stage Slots Blueprint (stage catalog + replace-slot stages)

`projects/routes/stage_slots.py`. The six DAS stages above are the only ones with a
loader binary; every other versus stage is a **replace slot**: one skin written
over the vanilla root file(s) in the open project, restorable from the recorded
vanilla ISO. Which stages exist, their names, vault folders and dual-language
roots all come from `core/stages.py` (the single stage registry -- adding a
stage is one row there).

Skins for these stages are ordinary vault stage variants: `stage_detector`
covers every code in the registry, so a raw `GrXx.dat` mod imports through
`import_stage_mod` into `storage/das/<folder>/<id>.zip` with metadata under
`stages.<folder>.variants` -- the same layout as the six DAS stages. The DAS
storage listing (`/api/mex/das/storage/variants`), the vault stage page, folder
endpoints, rename/delete, screenshots, export and duplicate detection therefore
cover all 29 stages with no stage-specific code. Only the project-side install
differs: DAS alt folder for the six, this blueprint's replace slot for the rest.

### GET /api/mex/stages/catalog
All 29 versus stages: `code`, `name`, `projectName`, `folder`, `series`,
`legal`, `dualRoot`, `mode` (`das` | `replace`), `internalId`, `slippiId`,
`rootFiles`, `artUrl`, `iconUrl`, `bannerUrl`; plus `legal` / `more` code
lists. `artUrl` is what a UI should show: the six legal stages' full art, and
for the rest the vanilla stage-select **icon** (the stage thumbnail, same image
Tracker serves per Slippi id at `/api/nucleome/stage-icon/<id>`). `bannerUrl`
is the SSS text logo, secondary. Both come from the user's own game
(`menu_refs`, `utility/assets/menu_refs/vanilla_stages`) and 404 until derived.

### GET /api/mex/stages/slots
Per replace-mode stage: `{ state, installed, availableCount }` for the Stages
list rows. `state` is `vanilla` | `installed` | `modified` |
`unknown` (vanilla ISO not recorded) | `missing` | `no-project`.

### GET /api/mex/stages/{code}/slot
`stage` (catalog entry), `slot` (state + `installed {slug,name,icon_url}` +
`files [{name, exists, size}]`), `available` (vault skins for this code) and
`added` (custom stages in the project whose file is `GrXx.dat` / `GrXx_NNN.dat`).
Slot state is derived by hashing the project root against the vanilla reference
and each vault skin -- nothing is stored.

### POST /api/mex/stages/{code}/slot/install
**Body:** `{ "variantId": "<vault variant id>" }` (a `storage/das/<folder>/<id>.zip`).
Writes the skin's DAT over every root file of the stage (both `.dat` and `.usd`
for Corneria, Venom, Onett). Rejects DAS stages (`400`, `reason: das_stage`),
unknown codes (`404`), ids that are not a skin for this stage (`404`).

### POST /api/mex/stages/{code}/slot/restore-vanilla
Copies the pristine root file(s) back from the vanilla reference
(`vanilla_extract/vanilla_refs.ensure_vanilla_ref`). `409` with
`reason: no_vanilla_reference` when no vanilla ISO is recorded.

### POST /api/mex/stages/{code}/slot/add-as-stage
**Body:** `{ "variantId": "<vault variant id>" }`. Wraps the skin as an ADDED
custom-stage package (`vanilla_stage_import.build_vanilla_stage_package`: the
vanilla stage's DOL code tables + SSS art + `nucleusVanillaStage` sidecar) and
imports it into the custom-stages vault. Returns `{ slug, name, entry }`; the
client then installs it through `/api/mex/custom-stages/install-batch`.

### GET /api/mex/stages/{code}/art/{icon|banner}
Vanilla SSS icon/banner PNG, copied out of the user's own game at first-run
setup, or later at app start or project open while missing
(`menu_refs.stage_art_path`; nothing is bundled).
404 until it has been derived.

---

## Poses Blueprint

### POST /api/mex/storage/poses/save
Save pose scene for CSP generation.

**Body:**
```json
{
  "character": "Fox",
  "poseName": "Action Pose",
  "sceneData": { /* YAML scene data */ }
}
```

### GET /api/mex/storage/poses/list/{character}
List saved poses.

### GET /storage/poses/{character}/{filename}
Serve pose thumbnail image.

### POST /api/mex/storage/poses/delete
Delete saved pose.

### POST /api/mex/storage/poses/batch-generate-csp
Generate CSPs for multiple skins using a pose. Each skin keeps one portrait per
pose (taking the pose again replaces its picture), and the pose's portrait
becomes the one the skin shows.

**Body:**
```json
{
  "character": "Fox",
  "poseName": "Action Pose",
  "skinIds": ["abc123", "def456"],
  "hdResolution": 4
}
```

---

## Setup Blueprint

### GET /api/mex/setup/status
Check if first-run setup is needed.

**Response:**
```json
{
  "success": true,
  "complete": false,
  "reason": "missing_vanilla_assets",
  "details": "Run setup with vanilla ISO"
}
```

A setup that is running or has ended is not reported here: it is a
`first_run_setup` job (see `POST /api/mex/setup/start`).

### POST /api/mex/setup/health
Boot-time setup health check. Unlike `/setup/status` (vanilla assets only), it
also validates the saved vanilla ISO path the viewer keeps in localStorage
(exists + size + GALE01 1.02 header — no hashing). The viewer shows a
dismissible "re-run first-run setup" banner when problems come back.

**Body:**
```json
{ "isoPath": "/path/to/vanilla.iso" }
```

**Response:**
```json
{
  "success": true,
  "problems": [
    { "id": "iso_not_configured", "message": "No vanilla Melee ISO is saved. ..." }
  ]
}
```

Problem ids: `assets_<reason>` (from `/setup/status` reasons), `iso_not_configured`,
`iso_missing`, `iso_invalid`.

### POST /api/mex/setup/start
Start first-run setup as a `first_run_setup` job (see Jobs Blueprint).

**Body:**
```json
{ "isoPath": "/path/to/vanilla.iso" }
```

**Response:** `{ "success": true, "message": "Setup started", "jobId": "<id>" }`

It returns before the ISO is hashed: the job MD5-verifies the ISO, then
extracts the vanilla assets. Progress, the final status and the result arrive as
`job` events and at `GET /api/jobs/{jobId}`. `extra.phase` is `verifying`, then
the engine's phases; the engine's `complete` phase comes while it still cleans
up, so only the job's `done` status ends setup. `result` is
`{message, characters, stages, isoPath}`. A rejected ISO fails the job with the
message in `error`, the reason in `extra.reason` (`not_found`, `unreadable`,
`compressed`, `nkit`, `not_gamecube`, `wrong_game`, `wrong_version`, `trimmed`,
`modified`) and `extra.md5` when it was hashed. The job owns the temporary
project (the extracted ISO); if Nucleus dies mid-setup, the next start deletes
it and marks the job `interrupted`. A missing `isoPath` returns 400; another
running setup returns 409 with its `jobId`.

### GET /api/mex/setup/auto-detect
Auto-detect Slippi path and ISO.

**Response:**
```json
{
  "success": true,
  "slippiPath": "/path/to/slippi",
  "isoPath": "/path/to/melee.iso",
  "isoFolderPath": "/path/to/iso/folder"
}
```

### POST /api/mex/verify-iso
Verify ISO is vanilla NTSC 1.02.

Only a successful response with explicit `valid: false` establishes an invalid
ISO. Settings treats HTTP, connection, and malformed-response failures as
verification unavailable and offers Retry; the exact MD5 rule is unchanged.

**Body:**
```json
{ "isoPath": "/path/to/melee.iso" }
```

**Response:**
```json
{
  "success": true,
  "valid": true,
  "md5": "0e63d4223b01d9aba596259dc155a174",
  "expected": "0e63d4223b01d9aba596259dc155a174"
}
```

---

### GET /api/mex/logs/download
Bundle the app's logs into a zip for a bug report: `logs/**` (redacted — OS
usernames in paths masked, token-shaped values blanked), optional Slippi
Dolphin logs, and a generated `diagnostics.txt` (app version, platform,
paths, what was gathered).

**Query:** `slippiPath` (optional) — the user's Slippi Dolphin folder; adds
Dolphin's `Logs/` + `.dmp/.log/.txt` at known top levels under
`slippi-dolphin/` (25 MB/file, 100 MB total caps; never replays or ISOs).

**Response:** the zip (`application/zip`, attachment).

### POST /api/mex/bugreport
Send a bug report privately: builds the same logs zip (budgeted to ~48 MB
uncompressed, newest logs first) plus `report.json` / `electron-diagnostics.json`
/ `renderer-errors.json`, and uploads it to the bugreport worker
(`services/cloudflare/bugreport-worker` → R2 + a private Discord ping). The Discord
session token is attached when present so the report can carry the
reporter's username; anonymous otherwise.

**Body:**
```json
{
  "description": "what happened (required, ≤4000 chars)",
  "contact": "optional",
  "slippiPath": "optional — include Slippi Dolphin logs",
  "app_version": "fallback when NUCLEUS_APP_VERSION is unset (dev)",
  "electron": { "...": "diagnostics from window.electron.getElectronDiagnostics()" },
  "renderer_errors": [{ "ts": "...", "message": "...", "stack": "..." }]
}
```

**Response:** `{ "success": true, "id": "...", "notified": true, "size": 123, "truncated": false }`

**Errors:** `400` no description / unknown app version · `426`
`{error: "update_required", latest, url}` — the worker refuses clients older
than `latest.json` for the platform (the UI shows "update first" and won't
submit; this is the server-side backstop) · `429` rate limited · `502` worker
unreachable. Env: `NUCLEUS_BUGREPORT_URL` overrides the worker URL for local
testing.

### POST /api/mex/chat-reports/review
"Report this chat" step 1 (`randall/routes/chat_reports.py`,
`randall/reports/chat_report.py`). Builds, scrubs and **freezes** a report of one
Randall conversation and returns what it contains. Sends nothing. See
[`RANDALL.md`](RANDALL.md#11-report-this-chat).

**Body:**
```json
{
  "surface": "mods | tracker",
  "conversation_id": "assistant chat id (32 hex) or tracker chat id",
  "note": "optional, ≤4000 chars",
  "contact": "optional, ≤200 chars",
  "app_version": "fallback when NUCLEUS_APP_VERSION is unset (dev)",
  "budget": { "source": "patreon", "active": true, "period_budget": 5, "remaining": 3.2,
              "usage": 1.8, "resets_at": "2026-11-01T00:00:00Z" }
}
```
`budget` is allowlisted server-side (`chat_report.BUDGET_FIELDS`, the same list as the
frontend's `chatReport.js`: ai-entitlement's `active`, `linked`, `paused`, `patron_status`,
`period_budget`, `remaining`, `usage`, `resets_at`, plus `source` and Tracker's `spent`/`cap`;
status and numbers only, a key is never kept). The budget fields are USD and stay in the
report, which only the developer reads; the review preview's transcript leaves out each
reply's dollar cost. Budgets have been monthly since the 2026-09 rollout.

**Response:** `{success, submission_id, approval_hash, conversation_sha256, manifest:
{members: [{name, bytes, sha256}], bundle: {bytes, sha256}}, meta, includes: [...],
not_included: [...], transcript, counts, truncated, turn_running}`

**Errors:** `400` `app_version_unknown` / `unknown_surface` · `404` `unknown_conversation`.

### POST /api/mex/chat-reports/submit
Step 2: send exactly the frozen bundle through the bug-report worker
(`kind: "chat"`, anonymous — no Discord bearer). The remote report id is stored
before the upload, so a retry after a lost reply goes into the same report.

**Body:** `{ "submission_id": "...", "approval_hash": "...", "consent": true }`
(`consent` must be the boolean `true`).

Window only: the consent is the person's, so the send needs the window-only key
`X-Nucleus-UI-Key` (`core/ui_channel.py`). An MCP client or a script holding the
backend token gets 403 `not_the_app_window` (`automation_caller` for a request
marked as an agent's), and 503 `ui_approval_channel_unavailable` when the
backend has no key. Step 1 (review) needs only the backend token; it sends nothing.

**Response:** `{success: true, state: "sent", id, notified, confirmed, size}` —
`confirmed: false` means an earlier upload of this report reached the server
and only its reply was lost. A repeated click returns the stored receipt
(`reason: "already_sent"`).

**Errors:** `400` `consent_required` · `404` `unknown_submission` · `409`
`consent_invalid` (hash mismatch) / `bundle_changed` / `already_sending` /
`retries_exhausted` · `426` `{error: "update_required", latest, url}` · `429`
`rate_limited` · `502` worker unreachable or refused (`retry: true` when a retry
can succeed).


## Vault Backup Blueprint

### GET /api/mex/storage/stats
Get disk usage in bytes, split by what holds the space.

**Response:**
```json
{
  "success": true,
  "stats": {
    "storage": 52428800,
    "projects": 3221225472
  }
}
```
`storage` is the Vault tree; `projects` is the m-ex projects tree (extracted
ISOs and per-project build state). Counts shown next to these in Settings come
from the metadata catalog, not this endpoint.

### POST /api/mex/storage/backup
Create a ZIP of storage, generating root metadata from the active JSON/SQLite
catalog. `vault.db` is excluded (a restore rebuilds it). Every other SQLite database
in storage (by its header: `assistant/chats.db`, `assistant/tasks/tasks.db`,
`assistant/chat_reports/submissions.db`) goes in as a consistent snapshot read through
the SQLite backup API (`vault_backup._sqlite_snapshot`: WAL included, a single file in
DELETE journal mode); no `-wal`/`-shm`/`-journal` file is ever zipped, and writes to those
databases during the backup do not fail it. This computer's setup files are excluded too
(`vault_backup._LOCAL_FILES`: `assistant/mcp.json`, `assistant/settings.json`,
`vanilla_iso.json`, `ai_studio.json`) and folders (`_LOCAL_FOLDERS`: the delivery
receipts in `assistant/deliveries/`, whose recorded paths a delivery undo writes to, and
Watch Lite's ~90 MB of animation zips in `nucleome/anim_zips/`, which the app downloads
again whenever they are missing, at first-run setup and every start; a restore never
writes them and a replace keeps this computer's).
The Tracker store goes in as one sanitized
SQLite snapshot, `nucleome.db` (`tracker/store/backup.py`: read through the SQLite
backup API, WAL included; the sign-ins, the cloud ledger and its bookkeeping, the
replay and recording folders, and every trigger or view taken out; VACUUMed).
`storage_relocation.PATH_SETTINGS_FILES` / `TRACKER_PATH_KEYS` list every stored path
setting, and a test keeps both lists in step. Sources are confined to storage and
rechecked before and after copying; detected concurrent edits fail the backup
instead of publishing the staged ZIP. Saved poses outside storage are excluded.

**Body (optional JSON):** `{"destination": "C:\\Backups\\SSBM-Nucleus-Vault-2026-11-20.zip"}`,
the path Settings > Export Vault picked in the app's save dialog (`saveVaultBackupDialog`,
IPC `save-vault-backup-dialog`, asked before the backup is made, so Cancel makes none). It must
be an absolute `.zip` path in an existing folder, outside the Vault (400 otherwise, before
anything is made). The backup is then copied beside it under a hidden `.part` name and
renamed into place: a failed save leaves no part file and keeps a file the user chose to
replace. Nothing stays in `output/vault_backups`, and `filename` / `path` in the response name
the saved file. Without `destination` the ZIP stays in `output/vault_backups` for the download
below (the browser dev flow).

**Response:**
```json
{
  "success": true,
  "filename": "vault_backup_20240115.zip",
  "size": 52428800,
  "path": "/path/to/backup.zip"
}
```

### GET /api/mex/storage/backup/download/{filename}
The browser dev flow only; the app saves through `destination` above. A Chromium download
showed its URL, backend token included, as the Save As title, and its Cancel deleted the backup.
Download the complete backup with the same one-shot streaming/cleanup semantics
as mod ZIP downloads above. HEAD leaves the archive available. Cleanup follows
the last active stream, including interruption; create a new backup to retry
after cancellation. The temporary ZIP is never deleted while an active
download still owns its file handle.

### POST /api/mex/storage/restore
Restore from backup (multipart form).

**Form Data:**
- `file`: ZIP backup
- `mode`: "replace" | "merge"
- `restore_id`: optional UUID generated by the caller before upload; it becomes
  the restore job's id (see Jobs Blueprint) and is echoed in the start response.
  Invalid modes or supplied IDs return 400. Omitting it uses a server-generated ID.

Replace extracts into a private sibling staging directory, parses the main
catalog and side catalogs, and verifies a staged SQLite database when enabled.
Only then does it move the previous Vault aside and publish the replacement.
The job's `result` is `{mode, message, recovery_path, tracker}` for replace (`recovery_path`
when a previous Vault was retained) and `{mode, message, added, report, tracker}` for merge.
`tracker.status` says what happened to the backup's Tracker store: `restored` (replace: the
sanitized store goes live with this computer's sign-in and folder rows put back), `merged` (with
`games` added; games match by replay path and this computer's rows stay), `none`, `unreadable`
(left out, this computer's store unchanged) or `failed` (merge only, with `error`). No restore
takes a sign-in, a folder setting, the cloud ledger or a trigger from a backup, an old raw
`nucleome.db` + WAL included, nor any row naming a network path (`\\server\share`): such
games (with their rows), replay hashes and kv values are dropped from the backup's store, as
are Combo Video songs whose extension is not one the app makes. The setup files and folders above are
skipped on extraction and a replace carries this computer's own into the restored Vault.
A backup made before 0.9.0 holds those databases raw with their companions: both modes open
each such database once in the extracted tree, so SQLite takes in its WAL (or rolls back a
hot journal), and then drop every companion (`_settle_sqlite_journals`), so a merge never
puts a backup's WAL beside this computer's copy of that database.
A failed publish attempts rollback; if rollback also fails, the error identifies
the preserved previous directory. Custom database paths outside the Vault are
rejected for replace mode because they cannot participate in the directory switch.
This is a recoverable switch, not full isolation from legacy unlocked writers.

The restore runs as a `vault_restore` job: progress, the final status and the
result arrive as `job` events and at `GET /api/jobs/{restore_id}`. The job owns the
upload, the staging tree and, between the two renames of a replace, the
moved-aside Vault; if Nucleus dies mid-restore, the next start deletes the
upload and staging, puts the old Vault back when no new one went live, and marks
the job `interrupted`. The frontend sends `X-Nucleus-Token` for the upload. Knowing
the ID before upload means a job event that beats the upload response is already
recognised; the window asks `GET /api/jobs/{restore_id}` only after the upload response,
since the job exists only from then (`useJob(id, { ask: false })` while uploading).
An in-transit upload is not resumable. A reused ID or another active
restore returns 409.

A merge that fails before its catalogs are written removes the files it had
already added, so a later merge does not skip those items as present.
Merge includes character effects and separate menu/code catalogs, keeping current
item identities and their file families. Catalog writes are atomic individually;
the entire multi-catalog merge is not one filesystem transaction.

### POST /api/mex/storage/clear
Clear storage.

**Body:**
```json
{ "clearIntake": true, "clearLogs": true }
```

Returns 409 while a Vault restore job runs, and clears under the metadata lock,
so it never deletes files a merge is about to catalog.

---

## Slippi Blueprint

### POST /api/mex/settings/slippi-path/verify
Verify Slippi Dolphin path.

**Body:**
```json
{ "slippiPath": "/path/to/slippi" }
```

### GET /api/mex/texture-pack/stats
Get texture pack folder statistics.

**Query:** `?slippiPath=/path/to/slippi`

### POST /api/mex/texture-pack/clear
Clear texture pack folder. 409 while the texture listener runs for that Slippi
folder (stop it first): it would keep counting the deleted textures as matched.

### POST /api/mex/texture-pack/start-listening
Start watching for dumped textures. 404 when the build has no texture mapping;
that refusal changes no Dolphin setting and leaves a running listener alone.

**Body:**
```json
{ "buildId": "build123", "slippiPath": "/path/to/slippi" }
```

**Response:** `{success, job_id}`. Runs as `texture_matching`, one at a time
(409 with the active id if busy). `extra` carries `matched`, `total` and
`last_match` (`{character, costumeIndex, skinId, filename}`). Progress and status
use the shared `job` event and `/api/jobs/{job_id}`. The harvester CLI is the
current caller; the window uses offline auto-apply instead.

`POST /api/jobs/{job_id}/cancel` stops between textures and finalizes collected
matches, ending `done` with `{matchedCount, totalCount, texturePackPath, stopped}`.
Matching all textures also ends the job. The job owns partial PNG/mapping writes
and the prior Dolphin DumpTextures setting: normal completion, failure and
startup recovery restore that setting and remove unfinished copies. HD texture
loading stays enabled for the completed pack.

### POST /api/mex/texture-pack/apply-offline
Apply a build's texture pack from a harvested index→filename table — no ISO boot, no CSS scrolling. Copies each real CSP into Dolphin's `Load/` folder under the precomputed filename.

### POST /api/mex/texture-pack/auto-apply
Fully automatic texture pack naming using a managed, build-independent index→filename table (no Dolphin launch at all).

**Body:** `{ buildId, slippiPath }`. **Response:** `{ success, job_id }`.

Runs as a `texture_pack` job. Its `result` is `{ buildId, matched, total,
computed, missingFromTable, copyFailed, texturePackPath }`. The job fails when the
build has no costume portraits or Dolphin's HD-texture setting cannot be turned on.

---

## XDelta Blueprint

### GET /api/mex/xdelta/list
List all xdelta patches.

### POST /api/mex/xdelta/import
Import xdelta patch (multipart form).

**Form Data:**
- `file`: .xdelta file
- `name`: Patch name
- `description`: Description
- `image`: Preview image (optional)

### POST /api/mex/xdelta/update/{patch_id}
Update patch metadata.

### POST /api/mex/xdelta/update-image/{patch_id}
Update patch image.

### POST /api/mex/xdelta/delete/{patch_id}
Delete patch.

### POST /api/mex/xdelta/build/{patch_id}
Build ISO from xdelta patch.

**Body:**
```json
{ "vanillaIsoPath": "/path/to/vanilla.iso" }
```

**Response:** `{ success, job_id }`. Runs as an `xdelta_build` job. It writes
`output/artifacts/<job_id>.part.iso`, moves it to `<job_id>.iso` only when the
build succeeded, and its `result` is `{ patch_id, filename, path }`.

### POST /api/mex/xdelta/play/{patch_id}
Build the patch's ISO (if missing) and launch it in the user's real Slippi Dolphin.

**Body:**
```json
{ "slippiPath": "/path/to/slippi", "vanillaIsoPath": "/path/to/vanilla.iso" }
```

**Response:** `{ success, job_id }`. Runs as a `patch_play` job; a failed build
or launch fails the job. `result` is `{ iso_path }`.

### GET /api/mex/xdelta/download/{job_id}
Download the ISO a `done` `xdelta_build` job built, under the job's result
`filename`. 404 for any other job or a missing file. The file is deleted once sent.

### POST /api/mex/xdelta/create
Create xdelta patch from modded ISO.

**Body:**
```json
{
  "vanillaIsoPath": "/path/to/vanilla.iso",
  "moddedIsoPath": "/path/to/modded.iso",
  "name": "My Mod",
  "description": "Description"
}
```

**Response:** `{ success, job_id }`. Runs as an `xdelta_create` job. Its `result`
is `{ patch_id, name, size, size_mb }`; the patch joins the list only when the
job is done.

### GET /api/mex/xdelta/download-patch/{patch_id}
Download xdelta patch file.

Requires the backend token, including for `HEAD`. Frontend download actions
first use authenticated `HEAD` with a ten-second timeout to surface errors,
then hand an authenticated GET URL to the browser. Attachment filenames come
from `Content-Disposition`. Neither request removes the stored patch.

---

## Bundles Blueprint

### GET /api/mex/bundle/list
List all bundles.

### POST /api/mex/bundle/play/{bundle_id}
Build the bundle's ISO (if missing), load its texture pack, and launch it in the user's real Slippi Dolphin.

**Body:**
```json
{ "slippiPath": "/path/to/slippi", "vanillaIsoPath": "/path/to/vanilla.iso" }
```

**Response:** `{ success, job_id }`. Runs as a `bundle_play` job; a failed build,
texture copy, HD-texture setting or launch fails the job. `result` is
`{ iso_path, texture_count }`.

Before anything is read or written, every member of the bundle is checked
(`vault/catalog/bundles.check_bundle`, the `core.safe_extract` preflight): a
name with a drive, an alternate data stream (`:`), `..`, a device name or a
collision fails the job with `Invalid bundle: ...`, as do a manifest.json over
1 MB, a texture over 128 MB, an unsafe compression ratio, more than 20,000
members or 8 GB in all. The texture pack is the PNGs directly in `textures/`,
each loaded under its own file name. Install and import apply the same check.

### POST /api/mex/bundle/delete/{bundle_id}
Delete bundle.

### POST /api/mex/bundle/update/{bundle_id}
Update bundle metadata.

### POST /api/mex/bundle/update-image/{bundle_id}
Update bundle image.

### POST /api/mex/bundle/export
Export .ssbm bundle.

**Body:**
```json
{
  "name": "My Bundle",
  "description": "Bundle description",
  "buildName": "build123",
  "vanillaIsoPath": "/path/to/vanilla.iso",
  "exportedIsoPath": "/path/to/modded.iso",
  "texturePackPath": "/path/to/textures"
}
```

Multipart form data with the same fields plus an optional `image` is also
accepted.

**Response:** `{ success, job_id, bundle_id }`. Runs as a `bundle_export` job
that writes `<bundle_id>.ssbm.part` and publishes `<bundle_id>.ssbm` and its
metadata only after packaging succeeded. `result` is `{ bundle_id, filename, size, size_mb,
texture_count }`. The job owns its temporary folder, the partial bundle and the
uploaded image.

### GET /api/mex/bundle/download/{bundle_id}
Download .ssbm bundle.

### POST /api/mex/bundle/install/{bundle_id}
Install bundle from storage.

**Body:**
```json
{
  "slippiPath": "/path/to/slippi",
  "vanillaIsoPath": "/path/to/vanilla.iso"
}
```

**Response:** `{ success, job_id }`. Runs as a `bundle_install` job. It decodes
the ISO to `<name>.<job_id>.part.iso` beside the destination (never `xdelta3 -f`
over the existing ISO), copies the textures, turns on Dolphin's HD textures, and
only then replaces `<name>.iso`. Any failure, including the HD-texture setting,
fails the job and leaves an earlier copy of the ISO untouched; the job owns the
extraction folder and the partial ISO. `result` is `{ name, iso_path,
texture_count }`.

### POST /api/mex/bundle/import
Import .ssbm bundle (multipart form). The bundle is checked as for play (above)
before it is stored; an `image.png` over 32 MB is left out, not the bundle.

### POST /api/mex/bundle/preview
Preview bundle without importing. Reads manifest.json only, within 1 MB (400
`Invalid bundle: ...` otherwise).

---

## Viewer Blueprint

### POST /api/viewer/paths
Get file paths for embedded viewer.

### POST /api/mex/viewer/paths-vanilla
Get paths for vanilla costume.

The Skin Creator's three path endpoints (`paths-vanilla`, `paths-vault`,
`paths-checkpoint`, and each `paintPair` member) also return `textureModels`:
`[{width, height, model}]`, one row per texture of the costume's model in the
viewer's order, `model` being `high`, `low` or `both` (which of the fighter's
models draws it, from its ftData lookup tables; `shared/rendering/lowpoly.texture_models`).
`null` when unknown. The texture strip sections by it (`textureSections.js`).

All three path endpoints automatically include `members` for `character:
"Ice Climbers"` or `"Nana"`. Members are in Popo/Nana order, each with stable
`memberId` (`popo` or `nana`), `name`, `datName`, `datFile`, `sceneFile`,
`ajFile`, `dataFile`, and `logsPath`. Only `paintPair: true` adds original
`datBase64` for editing. Ordinary previews avoid that additional payload.
Vanilla partners follow the actual color mapping (Nr→Nr, Re→Wh, Or→Aq, Gr→Ye).

`paths-checkpoint` copies Randall's working DAT to a fresh
`<scratch>/viewer_checkpoint_*` folder per call (the viewer holds its file
open), and `/api/viewer/paths` and `paths-vault` take the costume out of its
ZIP into a fresh `viewer_<8>` / `viewer_vault_*` folder. A checkpoint call
prunes copies over an hour old; the backend removes every viewer folder it
made when it shuts down, and a start removes every one an earlier run left,
never one this backend made (`shared/routes/viewer.py`
`remove_own_viewer_folders`, `sweep_viewer_folders`; a folder a viewer still
holds open stays until then).

### POST /api/mex/viewer/paths-vault
Get paths for vault costume.

Ice Climbers and Nana return the same automatic `members` payload. Explicit
custom partner links take precedence over vanilla, including legacy reverse
links. A broken explicit link fails instead of substituting another costume.
Unpaired costumes use the canonical vanilla partner. Other characters retain
the single-costume response.

Generic previews send `loadPaintPair` with `preview: true` and the selected
`primaryMemberId`, and wait for a correlated `paintPairLoaded` acknowledgement
before reporting ready. Startup is bounded to 30 seconds. Common animations
play and seek together; scene export preserves the selected member's settings
without persisting the temporary side-by-side placement.

For paired previews, `getAnimList` returns Popo's full shared action catalog,
using Nana's matching symbol where available when Nana is the primary member.
`loadAnim` resolves each member's own action; Nana inherits missing shared
motions from Popo. A Nana-only action does not create a shared catalog entry.
Both payloads are validated before either model's animation changes, so a
malformed partner animation leaves the previously loaded pair intact.

The combined editor sends `loadPaintPair` through the existing Electron viewer
channel. Pair commands carry `sessionId`/`requestId`; texture commands also
carry `memberId` and member-local `index`. `exportPaintPair` acknowledges both
DATs together. Manager events carry the distinct `viewerSessionId` supplied to
`viewerStart`. See [the pair protocol](ICE_CLIMBERS_PAINT_PROTOCOL.md).

The paint canvas requests `getFullTexture` before accepting unedited pixels;
the list thumbnail is never an editable/exportable canvas source. Paired replies
use the existing session/request/member correlation; single-file replies remain
index-only for native compatibility. Canvas adoption also checks viewer
generation, current selection, expected dimensions and the pending read object.

For an Ice Climbers character import, `/api/mex/import/file` additionally returns
`pairing_complete`. It is true only after reciprocal metadata links commit.
The editor requires `imported_count === 2` and `pairing_complete === true` before
reporting a saved pair; an incomplete acknowledgement retains the editor's edits.

### GET /api/mex/vanilla/costumes/{character}
Get vanilla costumes for character.

**Response:**
```json
{
  "success": true,
  "costumes": [
    { "code": "PlFxNr", "colorName": "Default", "hasCsp": true, "hasStock": true },
    { "code": "PlFxOr", "colorName": "Orange", "hasCsp": true, "hasStock": true }
  ]
}
```

---

## Settings Blueprint

Registered but currently a placeholder with no routes (the custom vault
location feature it hosted was removed).

---

## ISO Scan Blueprint

Rips new costume skins out of vanilla/modded ISOs as a background job (see
`backend/vault/importing/iso_scanner.py` for the pipeline). Progress is emitted over WebSocket.

**Diet Melee repair:** ISOs from the Diet Melee family (hacked DOL entry point
plus stripped-texture costume materials) author their skins for the low-poly
display their patched engine forces; imported raw they show near-vanilla and
can hang normal builds at match load. The scan detects such sources and
repairs each candidate in place — low-poly art promoted into the visible DObj
slots, stripped TEX flags cleared, eye-blink indices shimmed — before the CSP
thumbnail and the vault import (`shared/rendering/lowpoly_promote.py`). The universal
`/import/file` costume path applies the same repair to individual uploads
carrying the stripped-texture fingerprint.

### GET /api/mex/iso-scan/preflight
Reports `native_available: true` for the built-in GameCube reader.

### POST /api/mex/iso-scan/start
Start a scan job over a list of ISO paths.

**Body:**
```json
{ "iso_paths": ["/path/to/a.iso", "/path/to/b.iso"] }
```

**Response:** `{success, job_id, skipped}`. Follow `iso_scan` through `GET /api/jobs/{job_id}`
and the shared `job` event. `extra` holds phase counts and stats; `result` holds
candidates grouped by character, import data, stats and the summaries below.
`phase_current` and `phase_total` are nullable counts for the current phase.
`skipped_vault` lists unique matched vault skins as `{id, character, name, csp_url,
source_iso}`; `csp_url` is null when no saved portrait exists. Both original and
Slippi-fixed hashes resolve to the saved skin. Vanilla matches are excluded from
this list; raw file counts remain in `stats`. Empty scans skip thumbnail preparation.
`extraction_failures` lists unreadable ISO filenames in a mixed batch. If every
ISO fails extraction, the job ends with `status: "failed"`, not empty results.
The shared window job store reconciles on start and reconnect. Cancel through
`POST /api/jobs/{job_id}/cancel`; cancellation is checked between ISOs and candidates.
Failed, cancelled and interrupted scans remove their work directory; successful
scans retain candidate files for import until dismissal or stale-file cleanup.

### GET /api/mex/iso-scan/{job_id}/csp/{key}/csp
Serve a candidate skin's generated CSP PNG.

### POST /api/mex/iso-scan/{job_id}/import
Import the selected candidate keys into the vault.

### DELETE /api/mex/iso-scan/{job_id}
Drop a completed scan's candidate files. Active scans cannot be deleted; their
job record remains available through the shared jobs API.

---

## Menus Blueprint

CSS/SSS menu mod management. See [MENUS_SYSTEM.md](MENUS_SYSTEM.md) for concepts.

### GET /api/mex/menus/installed

Return `{success: true, installed: {...}}` with the menu slots recorded by app
installs for the open project. Keys include `css:background`, `sss:background`,
`css:doors`, `css:icon_grid`, `hud:pause_screen`, `hud:percent_font` and
`hud:ready_go`. Values contain the mod's display metadata, kind and install
timestamp. Records live in the project's `nucleus_menus.json`; an unopened or
unrecorded project returns an empty map. This is installation bookkeeping,
not an inspection of external edits to the project's files. Old HUD records
that filed a Ready/Go pack under `hud:percent_font` are repaired on read.
Entries installed since preview snapshots existed carry `snapshotUrl`.

`?verify=<menus>` (comma list of `hud`, `css`, `sss`) also reads those menus'
slots from the project files: `hud` = the Percent Font / Ready-Go slots of
`IfAll.usd` and the pause screen (`GmPause.usd`), `css` = icon grid (project
icon assets), doors and background (`MnSlChr.usd`), `sss` = background
(`MnSlMap.usd`). Pictures are decoded with HSDRawViewer exports (cached by
file mtime/size) and compared with a tolerance for re-encoding. Adds
`verification: {slot_key: {state, stale?, unverified?}}`: `state` is `installed` (the file holds the recorded mod;
`unverified` when that can't be checked, e.g. the vault mod is gone),
`vanilla`, or `custom` (changed by something not recorded); `stale` means a
record exists but the file no longer holds it. Slots that cannot be checked
(tool missing, export failed) are left out.

### GET /api/mex/menus/installed/preview/{menu}/{submod}
Serve the preview snapshot copied into the project when the mod in
`<menu>:<submod>` was installed (unaffected by later vault edits or
deletes). 404 when the slot has no snapshot.

### POST /api/mex/menus/percent/install/{mod_id}
Install a HUD typeface mod into the project's `IfAll.usd`. Optional JSON body
`{slot: "percent_font"|"ready_go"}` names the tab it was installed from; the
install is recorded under that slot and under every category the mod covers
(a full typeface fills both). The categories the mod covers are first put
back to vanilla (from the vanilla ISO's `IfAll.usd`) in the same write, so the
previous typeface leaves nothing behind. Returns `{message, installed:
{slot_key: entry}, resetSkipped}`; `resetSkipped` is true when no vanilla ISO
was available (the mod is still installed; the message says so).

### POST /api/mex/menus/percent/restore-vanilla
Body `{slot: "percent_font"|"ready_go"}`. Put that category's vanilla HUD
pictures (from the vanilla ISO's `IfAll.usd`) back into the project's
`IfAll.usd` and clear the slot's record. Stock icons, emblems and the other
category are untouched. 400 when no vanilla ISO is known.

### CSS Icon Grid

### GET /api/mex/menus/css/icon_grid/list
List imported icon grid mods.

### POST /api/mex/menus/css/icon_grid/import
Import an icon grid mod (multipart form; loose PNGs or compiled `MnSlChr` dat).

### GET /api/mex/menus/css/icon_grid/{mod_id}/icons
List the per-character icons of a mod.

### POST /api/mex/menus/css/icon_grid/update/{mod_id}
Update mod metadata (name, etc.).

### POST /api/mex/menus/css/icon_grid/{mod_id}/relabel
Re-assign an icon to a different character.

### POST /api/mex/menus/css/icon_grid/{mod_id}/replace_icon
Replace a single icon image (multipart form).

### POST /api/mex/menus/css/icon_grid/{mod_id}/delete_icon
Delete a single icon from the mod.

### POST /api/mex/menus/css/icon_grid/{mod_id}/add_icon
Add an icon image for a character (multipart form).

### POST /api/mex/menus/css/icon_grid/install/{mod_id}
Return the install plan (`{icons, total}`) without patching anything. Each
planned icon carries `plan` (an id for this install) and `total`.

### POST /api/mex/menus/css/icon_grid/install/{mod_id}/icon
Install a single icon from the mod into the project. On success the grid is
recorded as `css:icon_grid`; icons posted with the same `plan` accumulate in
the record's `icons_installed` (with `icons_total`), so a partial install
shows as one. Nothing is recorded until an icon really lands.

**Body:** one planned icon, e.g. `{ "character": "Fox", "icon": "Fox.png", "plan": "...", "total": 26 }`

### POST /api/mex/menus/css/icon_grid/delete/{mod_id}
Delete an icon grid mod from storage.

### CSS / Menu Backgrounds

(`/api/mex/menus/background/...` aliases exist for list/import/delete.)

### GET /api/mex/menus/css/background/list
List imported background mods.

### POST /api/mex/menus/css/background/import
Import a background mod (multipart form).

### POST /api/mex/menus/css/background/install/{mod_id}
Install a background into the project's CSS.

### GET /api/mex/menus/css/background/status
`{custom: bool}` -- whether the open project's CSS background looks custom
(recorded install, or the "Disable Hardcoded CSS BG Anim" code is present).

### POST /api/mex/menus/css/background/restore-vanilla
Put the vanilla CSS background back into the open project: exports the
background from the vanilla `MnSlChr.usd` (via the recorded vanilla ISO),
re-imports it into the project's `MnSlChr.usd` with its scene, drops the
"Disable Hardcoded CSS BG Anim" code, and clears the `css:background` record.
Returns `{message, codeRemoved}`; 400 when no vanilla ISO is known.

### POST /api/mex/menus/css/background/delete/{mod_id}
Delete a background mod.

### POST /api/mex/menus/background/update/{mod_id}
Update background mod settings.

### POST /api/mex/menus/sss/background/install/{mod_id}
Install a background into the project's SSS.

### SSS Layout

### GET /api/mex/menus/sss/layout
Get the project's stage select screen layout.

### POST /api/mex/menus/sss/layout
Set the stage select screen layout.

### GET /api/mex/menus/sss/stage-icon
Serve a stage's SSS icon image.

### GET /api/mex/menus/sss/backdrop
The SSS layout editor's backdrop: a 640x527 PNG of the stage select screen,
rendered from the vanilla `MnSlMap.usd` of the user's own ISO by
`HSDRawViewer --menu-render` and cached (`shared/vanilla_extract/menu_backdrops.py`,
`utility/assets/menu_refs/menu_backdrops`). The first request after a new
source renders it (a few seconds). 404 when there is no ISO, no renderer or
the render failed; the editor then draws a plain panel. Needs no project.

### CSS Layout

### GET /api/mex/menus/css/layout
Get the project's character select screen layout. Includes `lload`: the
project's L-load groups (`groups`, `problems`, `baseExternalIds`,
`altExternalIds`, `eligible`; see `docs/dev/L_LOAD.md`).

### POST /api/mex/menus/css/layout
Set the character select screen layout. L-load alternates are re-tucked
behind their bases whatever the request sends.

### GET /api/mex/menus/css/lload
The project's L-load groups (`[{base, alts}]`, by fighter name) and the
fighters that can be in one.

### POST /api/mex/menus/css/lload
Save L-load groups (`{groups: [{base, alts}]}`) and tuck the alternates' icons
at once. Unknown, blocked or duplicate names are dropped and listed in
`problems`; a group with no alternates is removed.

### GET /api/mex/menus/css/fighter-icon
Serve a fighter's CSS icon image.

### GET /api/mex/menus/css/backdrop
The CSS layout editor's backdrop: the character select screen with four
closed doors and no icons, rendered from the vanilla `MnSlChr.usd` the same
way as `/api/mex/menus/sss/backdrop` (same cache, same 404).

### CSS Doors

### GET /api/mex/menus/css/doors/list
List imported door mods (CSS hand/door textures).

### GET /api/mex/menus/css/doors/image/{mod_id}
Serve a door mod's preview image.

### POST /api/mex/menus/css/doors/import
Import a door mod (multipart form).

### POST /api/mex/menus/css/doors/delete/{mod_id}
Delete a door mod.

### POST /api/mex/menus/css/doors/install/{mod_id}
Install a door mod into the project.

---

## Custom Stages Blueprint

Wholly new (m-ex) stages, distinct from DAS texture variants. See
[CUSTOM_CONTENT.md](CUSTOM_CONTENT.md).

### GET /api/mex/custom-stages/list
List custom stages in the vault.

### GET /api/mex/custom-stages/in-project
List custom stages installed in the open project.

### GET /api/mex/custom-stages/{slug}/icon
Serve the stage's SSS icon.

### GET /api/mex/custom-stages/{slug}/banner
Serve the stage's banner image.

### POST /api/mex/custom-stages/{slug}/delete
Delete a custom stage from the vault.

### POST /api/mex/custom-stages/{slug}/rename
Rename a custom stage.

### GET /api/mex/custom-stages/{slug}/export
Download the stage's original ZIP.

### POST /api/mex/custom-stages/install
Install a vault custom stage into the open project.

**Body:** `{ "slug": "green-hill-zone" }`

### POST /api/mex/custom-stages/remove-from-project
Remove a custom stage from the open project.

### POST /api/mex/custom-stages/reorder
Reorder custom stages in the vault.

### POST /api/mex/custom-stages/folders/create
Create a vault folder for custom stages.

### POST /api/mex/custom-stages/folders/rename
Rename a folder.

### POST /api/mex/custom-stages/folders/delete
Delete a folder (stages move to root).

### POST /api/mex/custom-stages/folders/toggle
Toggle folder expanded/collapsed.

---

## Custom Characters Blueprint

Entirely new (m-ex) fighters. See [CUSTOM_CONTENT.md](CUSTOM_CONTENT.md).

### GET /api/mex/custom-characters/list
List custom characters in the vault.

### GET /api/mex/custom-characters/builtins
List built-in fighters (Giga Bowser) that first-run setup staged but has not
rendered yet — the greyed-out cards on the Custom Characters page — plus the
cards for any build in flight. Read build state from the shared job store.

### GET /api/mex/custom-characters/builtins/{slug}/icon
Serve the bundled CSS icon for a not-yet-built built-in fighter.

### POST /api/mex/custom-characters/builtins/{slug}/setup
Build a staged built-in fighter (CSPs, recolors, stock icons) into the vault.
Returns `{success, job_id}` for a `builtin_character` job. One build runs at a
time (409 with the running `job_id` if busy). The shared `job` event and
`GET /api/jobs/{job_id}` carry progress, outcome and errors; `params` identifies
the slug, name and costume count. Cancel is checked between rendering steps.
The job owns its temporary recolors; startup recovery removes them while
retaining staged source inputs for retry.

### GET /api/mex/custom-characters/{slug}/icon
Serve the fighter's CSS icon.

### GET /api/mex/custom-characters/{slug}/detail
Get full fighter metadata (costumes, etc.).

### GET /api/mex/custom-characters/{slug}/csp/{index}
Serve a per-costume CSP portrait.

### GET /api/mex/custom-characters/{slug}/stock/{index}
Serve a per-costume stock icon.

### POST /api/mex/custom-characters/{slug}/delete
Delete a custom character from the vault.

### POST /api/mex/custom-characters/{slug}/rename
Rename a custom character.

### GET /api/mex/custom-characters/{slug}/export
Download the fighter's original ZIP.

### POST /api/mex/custom-characters/install
Install a vault custom character into the open project.

**Body:** `{ "slug": "shadow" }`

### POST /api/mex/custom-characters/remove-from-project
Remove a custom character from the open project.

---

## Test In Game Blueprint

Boots a freshly-built ISO in an isolated throwaway Dolphin and drives it to a
real offline match (see [INGAME_TESTING.md](INGAME_TESTING.md)). Every start
endpoint runs its work as the one `ingame` job (see Jobs Blueprint): only one
test or capture at a time, and another start returns 409 with the running
`jobId`. The start response carries `jobId`; progress (`extra.stage`), the final
status and the result arrive as `job` events and at `GET /api/jobs/{jobId}`. A
failure fails the job with its message in `error`. Automated callers may send
their own `jobId` (a UUID) so they can find the job if the start response is
lost; a used or malformed one returns 400. Only an interactive session also
streams `test_progress`, `test_complete` and `test_error` (below).

The job owns every Dolphin it launches (pid and executable). Whatever is still
running when the job ends, or after Nucleus died mid-test (the next start marks
the job `interrupted`), is closed, but only while that pid is still a process of
that executable started at the recorded time; nothing is matched by image name.

A test's result uses `pass: false`, `verdict: "error"` and
`error_code: "graphics_initialization_failed"` for recognized graphics startup
failures; `reason` includes the native error. Unconfirmed offline menu navigation
also cannot PASS. Its result retains a `boot_health: {verdict, reason}` diagnostic
and any screenshot; healthy RAM observation becomes an error because the requested
checks did not run.

The six interactive start routes (`start`, `costume`, `custom-character`,
`custom-character-skin`, `custom-stage`, `stage-skin`) check the test slot and
existing Dolphin processes before starting build/background work. An active test
returns HTTP 409 with the existing busy error. An already-open Dolphin releases
the reserved slot and returns HTTP 409:

```json
{
  "success": false,
  "code": "dolphin_open",
  "dolphinOpen": true,
  "error": "Close the open Slippi Dolphin or Dolphin window, then start the test again. The in-game test needs its own Dolphin window to receive controls."
}
```

The caller should display the error and let the user close Dolphin and retry;
this response does not schedule a deferred test or close their emulator. The
engine's later `waiting` progress stage still handles Dolphin opening after
preflight. Render that stage without a numeric progress claim or empty embedded
window. Screenshot capture endpoints do not check for an open Dolphin first;
the engine waits for it.

### Interactive preview lifecycle

The six test kickoff endpoints below accept optional `interactive` (boolean,
false by default) and `sessionId` (UUID; generated if omitted). Per-mod UI tests
send `interactive: true` and a fresh client UUID. The response echoes the UUID.
Interactive character/costume previews load on Battlefield; stage previews use
Mario. Port 1 is fixed; no controller detection occurs. `observeSeconds` applies
only to automated tests.

Interactive `test_progress`, `test_complete`, and `test_error` events carry
`sessionId`, `interactive: true`, and a monotonically increasing `sequence`.
Clients must filter by UUID and ignore older/equal sequence numbers, including
status snapshots. A `playing` progress event carries `controllerPort: 1` and a
message. Normal Stop/close completion reports `success: true` and
`verdict: "stopped" | "closed"`, not PASS. The session's job id is its
`sessionId`, and the job's result is the `test_complete` payload. The latest 16
interactive sessions retain their final event for recovery.

### POST /api/mex/test-in-game/stop

**Body:** `{ "sessionId": "<UUID from kickoff>" }`.

Requests cancellation of that interactive session only. During an ISO build,
finishes the build safely then skips Dolphin launch. Returns `success`,
`sessionId`, `running`, and `stopRequested` when still active. Repeating Stop on
a completed retained session succeeds with `running: false`; unknown IDs return
404 and a missing ID returns 400. A stale ID never stops a newer test or capture.
For an ambiguous/lost kickoff response, send `cancelPending: true`: an unknown
valid UUID gets a completed cancellation snapshot, and a later kickoff with that
UUID is rejected. The last 256 pending-cancellation IDs are retained separately
from the 16 event snapshots. This does not affect another active session.

### POST /api/mex/test-in-game/start
Start a full build test from a build manifest (smart plan covering all mod types in the build).

**Body:**
```json
{
  "isoPath": "C:/path/to/build.iso",
  "slippiDolphinPath": "C:/path/to/Slippi Dolphin",
  "manifest": { "costume": { "fighter": "Fox", "colorIndex": 4 } },
  "manifestPath": "C:/path/to/manifest.json",
  "observeSeconds": 9,
  "hiresTextures": false,
  "loadSeed": "C:/path/to/Load/Textures"
}
```

`manifest` or `manifestPath` is optional; without one the engine performs a
boot-health check at the offline CSS.

### POST /api/mex/test-in-game/costume
Test a single vault costume. Interactive previews use the selected costume on Battlefield; automated callers retain crash/hang checks.

**Fields:** `character`, `skinId`, `vanillaIsoPath`, `slippiDolphinPath`; optional `colorName`, `observeSeconds`.

### POST /api/mex/test-in-game/custom-character
Test a vault custom character in-game.

**Fields:** `slug`, `vanillaIsoPath`, `slippiDolphinPath`; optional `name`, `observeSeconds`.

### POST /api/mex/test-in-game/custom-character-skin
Test one skin or bundled costume slot of a vault custom character.

**Fields:** `slug`, `vanillaIsoPath`, `slippiDolphinPath`, plus either `skinId` or `costumeIndex`; optional `colorName`, `observeSeconds`.

### POST /api/mex/test-in-game/custom-stage
Test a vault custom stage in-game.

**Fields:** `slug`, `vanillaIsoPath`, `slippiDolphinPath`; optional `name`, `observeSeconds`.

### POST /api/mex/test-in-game/stage-skin
Test a DAS stage skin in-game.

**Fields:** `stageCode`, `stageFolder`, `variantId`, `vanillaIsoPath`, `slippiDolphinPath`; optional `name`, `button`, `observeSeconds`.

### POST /api/mex/test-in-game/capture-stage-screenshot
Boot a match on one DAS stage variant and return a clean live screenshot for preview review.
The job's `result` is `{screenshot, stageFolder, variantId}` (`screenshot` a `/shots` URL, below).

**Fields:** `stageCode`, `stageFolder`, `variantId`, `vanillaIsoPath`, `slippiDolphinPath`; optional `button`, `jobId`.

### POST /api/mex/test-in-game/capture-pause-screenshot
Boot a pause-screen mod, pause a live match, save the live pause preview, and return it.
The job's `result` is `{screenshot, modId}`.

**Fields:** `modId`, `vanillaIsoPath`, `slippiDolphinPath`; optional `jobId`.

### GET /api/mex/test-in-game/shots/{job_id}/{name}
One PNG an in-game test or capture took. A job record never holds an image (it
stays in memory and goes out on every `GET /api/jobs`): the `screenshot` of a
test result and of each of its `checks` and of a capture is this URL. Files live in `output/test-shots/<job_id>/`, and the
newest 20 jobs' folders are kept. Token-checked like any `/api` route, so the
window loads them through `backendMediaUrl`. 404 once pruned; 400 for a path
outside the folder. The harness's direct `run_test` calls still return data URIs.

### GET /api/mex/test-in-game/window/capture-target
Return the Windows render target of the retained, live test subprocess:
`{success, supported, found, sessionId, pid, hwnd, client}`. Identity fields are present
only when found; `hwnd` is a decimal string. Process exit or absent render window
returns `found: false`; other platforms return `supported: false`. `client` is
`{x, y, width, height, frameWidth, frameHeight}` (physical pixels): the render
client area inside the window's compositor bounds, which is what a window capture
delivers, title bar included. It is presentation only (Randall's workbench crops
the title bar out with it) and is `null` when it cannot be measured.

Electron calls this authenticated endpoint itself and matches the exact HWND
against window capture sources. The frontend cannot choose a process or source.

### POST /api/mex/test-in-game/window/capture-target
Present that same captured target after a decoded frame, or restore its separate
window. Body: `{sessionId, hwnd, mode: "behind" | "separate", ownerHwnd, ownerPid}`.
The owner fields identify the Electron window and are required for `behind`.
Stale target/session identity returns `found: false`; invalid modes or owner
arguments return HTTP 400. Behind-window presentation preserves render size and
does not minimize or park the target offscreen.

### POST /api/mex/test-in-game/window/position
Pin the active throwaway Dolphin render window over the frontend preview
placeholder. Coordinates are physical screen pixels.

**Body:** `{ "x": 100, "y": 100, "width": 640, "height": 480 }`

### POST /api/mex/test-in-game/window/park
Move the active throwaway Dolphin render window offscreen.

### GET /api/mex/test-in-game/status

Optional query: `sessionId`. With an ID, returns that session's `running`,
`sessionId`, `interactive`, `stopRequested`, `status` (latest progress), and
`lastEvent: {event, payload}` (latest progress or terminal event). Unknown IDs
return `running: false` and null snapshots. Without an ID, `running` says
whether an `ingame` job is active and other fields describe the active
interactive session, if any. All responses include `success: true`.

---

## Account Blueprint

The Discord sign-in the backend holds (`shared/account/`, routes in
`shared/routes/account.py`). Settings > Files & setup > Account signs in and out here; the
Upload tab reads the account as a publishing identity when there is no
ssbmnucleus.net login, and bug reports attach its token. Not gated. The session
is kept in the Tracker index's kv table under `friends_session`, its name from
when Friends (removed in 0.8.16) owned the sign-in.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/account/discord` | `{account: {user_id, username, discord_username, avatar_url, source: "discord"} \| null, auth: {state: idle\|pending\|done\|error, error}}`. Name and avatar are Discord's own, from the Supabase user |
| POST | `/api/account/discord/start` | opens the Discord sign-in in the browser → `{url, account, auth}`; poll GET while `auth.state` is `pending`. 409 with `error` (and `auth.state` `error`) when the local callback port is taken |
| POST | `/api/account/discord/signout` | → `{account, auth}` |

---

## Publish Blueprint

Publishes a vault package to ssbmnucleus.net as a pending post (the Upload
page's Publish button). Mirrors the website's browser-side intake server-side:
`api_create_pending_post` RPC → `/api/intake/presign` (Cloudflare Pages
Function) → direct R2 PUTs → `api_finalize_pending_post` RPC. All posts land
in the website approval queue.

### POST /api/mex/publish
Multipart form:
- `payload` — JSON `{ accessToken, title, description, tags[], items[], dryRun }`.
  `accessToken` is the signed-in user's Supabase token (viewer
  `shared/account/account.js` `getAccessToken()`); when it is absent the backend falls
  back to the backend's Discord session (`shared/account`), since a Discord
  sign-up is an account on the same website project (its `public.users` row
  carries `origin = 'discord'`). 401 only when neither exists. `items` are Upload-page catalog
  selections; the backend resolves them by `key`
  (`costume:<char>:<id>`, `stage:<stage>:<id>`, `effect:<char>:<type>:<id>`,
  `character:<slug>`, `custom-stage:<slug>`, `patch:<id>`, `bundle:<id>`).
- `screenshot_<i>` — ordered screenshot blobs (first = cover; ≥1 required).
- `manual_<i>` — local files added on the Upload page.

Vault costume/stage zips become nested archives (the original zip is
reconstructed inside `files.zip`), their DATs become website file rows with
character/color/symbol/slippi_safe and named CSP/stock copies, and every image
gets a `__thumb.webp`. `dryRun: true` stops before any remote call and returns
the storage plan for inspection.

**Response:** `{ "success": true, "postId": 123, "url": "https://ssbmnucleus.net/post/123", "status": "pending" }`

---

## Extras Blueprint

Character effect mods (laser colors, shine colors, model swaps, texture hues).

### GET /api/mex/storage/extras/list/{character}
List extras in vault for a character.

### GET /api/mex/storage/extras/current/{character}/{extra_type}
Get the currently installed extra of a type for a character, read from the
project's DAT where a guarded install would write it (the same offset
guard/relocation installs use; see `EXTRAS_AUDIT.md` "Offset safety").
Answers `{colors, isVanilla, status, unknownLayers, layoutVerified, vanilla}`:

- `status` is `vanilla`, `custom` or `unknown`. Each layer is compared to the
  vanilla reference file's exact bytes at the same slot (the config's
  `vanilla` swatches are only the fallback; summary keys such as
  `color1`/`color2` with no bytes of their own are not compared). A layer
  that could not be located is listed in `unknownLayers` and left out of
  `colors`; if nothing located differs from vanilla, the status is `unknown`
  rather than a guess. `isVanilla` is true only when `status` is `vanilla`.
- `layoutVerified` is false when no vanilla reference DAT is available; the
  layers are then read at their configured offsets as before.
- Types without color offsets: `texture_recolor` decides vanilla/custom from
  the texture's exact bytes (texels or live palette entries) against the
  vanilla file; its swatch is the texture's dominant hue, so a custom
  reading carries `approximate: true`. `texture_region` (the shield) is
  `unknown` when there is no vanilla reference to compare. Model swaps are
  always `unknown` (the installed model can't be read back). Unknown
  readings may carry a human-readable `detail`.

For a unit, `parts` carries the same reading per nested part (`{part_id:
{colors, isVanilla, status, unknownLayers, vanilla}}`); the unit's `status` is
`custom` if any piece is, else `unknown` if any piece is. For an
`image_model` extra (the Fox/Falco shine) with an image installed, answers
`{colors: {}, isVanilla: false, imageInstalled: true, image: {width, height,
gxFormat}}` instead of colours that describe a model the game no longer draws.

Falco side-B with a supported replacement graph returns
`{colors: {}, isVanilla: false, status: "custom", sidebModel: {version: 1, sha256}, vanilla}`.
An unsupported graph returns `status: "unknown"` with `detail`. Original-shape
color reads follow the active article material, including after native DAT
reserialization, rather than matching an unreachable old color marker.

### POST /api/mex/storage/extras/import
Create an extra from an uploaded file (multipart: `file`, `character`,
`extraType`, optional `name`). Supported color DATs use the unified effect
importer; compatible Falco afterimage DATs become `sideb_model` extras.
Images are accepted by `texture_region` (the shield bubble) and `image_model`
(image shines), not side-B. DATs are classified by content: color recipes,
image shines and supported Falco afterimages retain their distinct formats;
other replacement geometry is rejected.

### GET /api/mex/storage/extras/effect-image/{character}/{extra_type}
An `image_model` extra's picture as PNG. `?mod=<id>` renders a stored mod's
image; with no query it renders what is installed in the open project, and
404s with `installed: false` when the model is still the vanilla untextured
one.

### POST /api/mex/storage/extras/create
Create a color-effect extra (e.g. custom laser/shine color). `{character, extraType, name, modifications, modId?}`.

For an existing `sideb_model` mod, an unchanged recipe may be saved with a new
name. Replacing its model recipe with colors returns 400; create a separate
color mod instead.

A move is ONE extra whose mod carries its parts: `modifications.parts[<part id>]` holds that part's own recipe (`{layer: {color}}`), e.g. an `upb` mod with `parts.upb_charge_fire.color1` (flight puff texture) and `parts.charge_flames.flame_c1…` (Fox's charge flames). The part types (`part_of` in `core/extra_types.py`, registry `UNIT_PARTS`) are never listed on their own by `/extras/list`; mods saved under a part type by older builds are folded into the unit on the next list. Legacy nested textures (`upb` → `fire` → `upb_texture`, `falcon_punch` → `fire` → `punch_texture`) keep their own key.

### POST /api/mex/storage/extras/delete
Delete an extra from the vault.

### POST /api/mex/storage/extras/install
Install an extra into the open project. A unit mod also writes each nested part into its own target file (`EfCoData.dat` for charge flames, `PlMr.dat` for the fireball aura…); a part that could not be written is reported in `partErrors` without failing the primary. A mod whose only content is parts (imported from a parts-only website file) installs those parts and leaves the primary vanilla.

Falco afterimage installs replace only the validated article-3 model graph.
Repeated installation of the same graph is idempotent. A color extra first
restores the original afterimage shape. Unsupported structure or an unavailable
required restore reference returns 409 without publishing partial file changes.

### POST /api/mex/storage/extras/restore-vanilla
Restore an effect to its vanilla state, including every nested part of a unit (`restored_components` names them).

Falco side-B restores original shape and colors and reports `sideb_model` in
`restored_components`. It uses the exact append rollback when still valid;
after native relocation it selectively copies the original graph from the
vanilla reference. It never truncates using a stale rollback offset. Failure
returns 409 with `failed_spans` and leaves the target unchanged.

A model extra (Fox's and Falco's gun) is copied back from the vanilla reference
DAT (`HSDRawViewer --model copy`, the model graph as the game ships it) and
returns `restored_components: ["model"]`. No vanilla reference, or a copy that
fails, returns 409 with the tool's reason and leaves the project DAT unchanged.

### POST /api/mex/storage/models/create
Create a model-swap extra. Multipart: `file` (a `.dae`, or the fighter `.dat`
that carries the model, e.g. `PlFc.dat`), `character`,
`extraType`, `name`. A `.dat` without the model at the type's `model_path` (a
costume file such as `PlFcNr.dat`) returns 400 naming the file to upload; other
HSDRawViewer failures return 500 with the tool's `ERROR:` line.

### POST /api/mex/storage/models/install
Install a model-swap extra.

### POST /api/mex/storage/models/delete
Delete a model-swap extra.

### GET /api/mex/storage/textures/current/{character}/{extra_type}
Get the current texture-hue extra for a character.

### POST /api/mex/storage/textures/install
Install a texture-hue extra.

---

## Assets Blueprint

### GET /api/mex/assets/{path}
Serve MEX project asset files.

### GET /storage/{path}
Serve files from storage folder.

### GET /vanilla/{path}
Serve vanilla Melee assets.

### GET /utility/{path}
Serve utility assets (icons).

### GET /assets/{path}
Serve project assets.

---

## Character Sounds Blueprint

Per-character sound-bank packs in the vault (browse, edit, install). All paths
are under `/api/mex/storage/characters/{character}/sound-packs`. Audio uploads
are converted via MeleeMedia (wav/brstm/dsp/hps).

| Method | Endpoint (suffix) | Purpose |
|---|---|---|
| GET | *(base)* | List the character's sound packs |
| POST | `/create` | Create a pack (copy of the vanilla bank) |
| POST | `/{pack_id}/rename` | Rename a pack |
| POST | `/{pack_id}/delete` | Delete a pack |
| GET | `/{pack_id}/audio/sounds` | List sounds in the pack's bank |
| GET | `/{pack_id}/audio/sound/{index}` | Decode one sound to WAV for preview |
| POST | `/{pack_id}/audio/sound/{index}/replace` | Replace one sound with an uploaded audio file |
| POST | `/{pack_id}/audio/sound/{index}/revert` | Restore one sound from the pristine bank |
| POST | `/{pack_id}/audio/sounds/revert-all` | Restore all sounds |
| POST | `/{pack_id}/install` | Install the pack's bank into the open project |
| POST | `/uninstall` | Restore the character's original sounds in the open project |

---

## Music Playlists Blueprint

### Music loop editing

Shared project-pool tracks are addressed by `music_id`, independent of playlist
indices. Both stage and menu editors expose the same loop controls.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/mex/music/{music_id}/loop` | Read `duration_ms`, `loop_start_ms`, `loop_enabled`, `frequency`, and opaque `version` |
| POST | `/api/mex/music/{music_id}/loop` | Save `{version, loop_start_ms}` and return the actual saved settings |
| GET | `/api/mex/music/{music_id}/loop/preview?version=...` | Decode the version-matched track to WAV for Web Audio preview |

Loop saving enables looping and snaps down to a complete 56-sample HPS audio
group. The full audio and playlist weights are preserved. A song is shared by
all playlists referencing its pool entry. `version` binds the editor to its
project, track path, and source bytes: stale reads/project switches return 409,
invalid times or malformed audio return 400, and unavailable tracks return 404.
Conversion uses the file-only `hps-loop-info` / `hps-set-loop` MexCLI commands.
The backend stages and atomically replaces validated HPS under `mexcli_lock`;
failed conversions leave the original untouched. Client previews use Web Audio
loopStart to hear the repeat boundary without waiting through the whole song.

Preview WAV caches are keyed by source bytes and decoder build identity. Decode
output is staged and checked for complete PCM before publication; failed or
truncated output returns 500 and is not reused. Each version has a separate
immutable path so an older response can finish streaming on Windows. Obsolete
files are retired on a later preview request after their readers release them.

Weighted music playlists edited directly in the open project (no vault
packs). Play chances are integer percentages that always sum to 100 —
every write renormalizes, and adding a song gives it an equal share while
the rest shrink proportionally. Writes go through the MexCLI
`set-stage-playlist` / `set-menu-playlist` commands (entries JSON on stdin).

**`/tracks/add` takes exactly one file per request** (form field `file`, plus
an optional `name`). It re-reads the playlist, appends the upload at an equal
share and republishes the whole renormalized list in one workspace save — so
callers adding several songs MUST issue the requests sequentially. Two in
flight both build on the same pre-upload entries and the second silently drops
the first song. The viewer's bulk picker enforces this in
`frontend/src/projects/playlistUpload.js`.

### Stage music

Each of the six tournament (DAS) stages has its own playlist. An empty
playlist is exactly the vanilla state (the game falls back to the BGM table
in the stage's DAT), so restoring vanilla = setting an empty list. When the
playlist is empty, reads serve the stage's actual vanilla songs (main track
plus the unlock-gated 12% alternate where one exists) as the tracks with
`vanilla: true` — so the UI always shows what plays, and adding a song
seeds the playlist with the vanilla entries instead of dropping them. All
paths under `/api/mex/das/{stage}/stage-music`.

| Method | Endpoint (suffix) | Purpose |
|---|---|---|
| GET | *(base)* | The stage's effective playlist (`vanilla: true` when synthesized) |
| POST | `/tracks/add` | Add a song (converted + deduped via `add-music`; vanilla entries are kept) |
| POST | `/set` | Replace the playlist (`{entries: [{music_id, chance}]}`; `[]` restores vanilla) |
| GET | `/track/{index}` | Decode an entry to WAV for preview (works for vanilla tracks too) |

### Menu music

The open project's menu playlist — one global weighted playlist shared by
every menu (vanilla is two songs at 75%/25%). Requires at least one entry —
an empty menu playlist has no vanilla fallback. All paths under
`/api/mex/menu-music`.

| Method | Endpoint (suffix) | Purpose |
|---|---|---|
| GET | *(base)* | List the menu playlist (name, chance, per entry) |
| POST | `/tracks/add` | Add a song (converted + content-aware deduped via `add-music`) |
| POST | `/set` | Replace the playlist (`{entries}`; must keep at least one song) |
| GET | `/track/{index}` | Decode an entry to WAV for preview |

---

## Tracker Blueprint (`nucleome_bp`)

Tracker's API under `/api/nucleome` (internal id `nucleome`; publicly released
as Tracker in 0.7.0). One blueprint, `nucleome_bp`, defined in
`tracker/routes/nucleome.py` with its gates; the routes live in one module per
feature beside it: `replays.py` (identity, scan, the replay list), `stats.py`
(`/stats`, `/deep/*`), `combos.py`, `lite.py` (`/lite/*`), `watch.py`
(`/watch-mods/*`), `icons.py` (`/stage-icon`, `/stock`, `/sprites`), `ranks.py`
(`/ranks`, `/rank-history`), `cloud.py` (`/vault/*`) and `share.py` (`/share*`).
The coach's `/coach/*` routes are on the same blueprint but live in
`randall/routes/coach.py`. Combo Video (`combo_video_bp`) is a separate
blueprint under the same prefix. Highlights
documented here:

- `GET /api/nucleome/stats` takes `?my_char` (external char id) plus
  `?start` / `?end` — inclusive `YYYY-MM-DD` local-day bounds that scope
  every section of the payload; malformed values answer 400
  (`"bad my_char/start/end filter"`). The combos list's `date_from` /
  `date_to` are validated the same way.
- `POST /api/nucleome/replays/watch` opens a replay with the OS `.slp`
  handler on every platform (`os.startfile` / `open` / `xdg-open`).
- `POST /api/nucleome/replays/scan` (`{dir?}`, a folder the user typed, which
  is remembered) starts a `replay_scan` job → `{started, job_id, dir}`; 400 when
  the folder is missing, 409 `{error, job_id}` while one runs. The screen follows
  the job record (`extra`/`result`: `total, done, added, updated, removed,
  failed`; `result.warning` when part of the folder could not be listed, in
  which case nothing is pruned). `GET /api/nucleome/replays/status` → `{index:
  {indexed, parsed}}`.
- `POST /api/nucleome/deep/start` (`{character?}`) starts a `deep_stats` job →
  `{started: true, job_id}`; 409 `{started: false, reason, job}` while one runs
  or when peppi-py is missing. `GET /api/nucleome/deep/status?character=` →
  `{secs_per_game, coverage?: {mined, pending, total}}`; the running job is its
  record (`params.character`, `extra.done/total/failed`).

### Watch Lite playback

All `/api/nucleome/lite/*` routes share `nucleome_bp`'s `NUCLEUS_NUCLEOME`
gate and the normal desktop backend authentication. Local desktop clips use
`tracker/replays/liteClipLoader.js`: fetch indexed replay bytes, derive a v5
bundle in a module Web Worker, merge conversion metadata, and narrow character
packs to the animations used by the clip. Worker construction failures fall
back to main-thread JS derivation. Frames are true Slippi frames, with rollback
re-emissions removed; combo windows retain 45 frames of padding on either side.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/nucleome/lite/slp/{game_id}` | Stream the indexed `.slp` as `application/octet-stream`. The integer id is the only file selector; client paths are ignored. Missing/unindexed/unparsed files return 404. Supports conditional/range fetches. |
| GET | `/api/nucleome/lite/clip-ref/{ref}/resolve` | Resolve a tool-minted ref to `{game_id, start_frame, end_frame}` in true frames. Unknown refs or missing files return 404; unreadable traces return 422. Invalid/outside windows recover to the highest-damage indexed combo, or null bounds for an uncapped whole game when no combo exists. |
| GET | `/api/nucleome/lite/pack/{cid}` | Full animation geometry for an internal character id: `{animName: [svgPath, ...]}`. Missing/invalid packs return 404. Serialized packs are cached, gzip is negotiated via `Accept-Encoding`, and responses carry `Vary`, ETag and a private one-day cache policy. Includes follower and transformed character ids. |
| GET | `/api/nucleome/lite/conversions/{game_id}?conversions=1` | Conversion sidecar: `{"0": [Interaction, ...], "1": [...]}` from `detect_conversions`, with true-frame coordinates unchanged; `{}` outside two-player games. The query flag is optional because this route only serves conversions. Missing files return 404; unparseable traces return 422. The loader keeps conversions overlapping the actual padded bundle window; unavailable sidecars leave playback without overlays. |
| GET | `/api/nucleome/lite/charmaps` | Action/state-to-animation maps used by the renderer and animation narrowing. |
| GET | `/api/nucleome/lite/clip/{game_id}?start=...&end=...` | Legacy Python `{bundle, anim, available, recovered}` payload. Omit bounds for the whole game. |
| GET | `/api/nucleome/lite/clip-ref/{ref}` | Legacy Python clip payload for a minted ref, including invalid-window recovery. |

For one release, `localStorage.setItem('watchLite.deriver', 'python')` forces
the legacy local game/ref routes for newly loaded clips; removing that key
restores JS derivation. Watch Lite, Randall's inline clips, and the Combo Video
preview/MP4 exporter all use the shared loader. Missing geometry retains dot
playback. The dev-only `window.__wlStep` hook is unchanged.

### Stats loading and aggregation

`GET /api/nucleome/stats` retains its complete summary response and existing
filter/result rules. Aggregation avoids decoding final-state JSON when placements
already decide the result and reuses computed game outcomes and timestamps.
This is a computation change, not a paginated or partial stats response.

The frontend requests this summary before optional facets and rating history.
Filter requests are aborted and fenced so obsolete results cannot replace the
current selection; transport failures remain errors and do not become empty
statistics. The previous summary can remain visible while an update runs.

### Sprites

Melee-derived UI sprites (Randall's cloud faces from `GrSt.dat`, Fox/Falco
shine animation frames rasterized from `EfFxData.dat` geometry + FOBJ
tracks) — extracted from the user's recorded vanilla ISO by
`tracker/video/sprites.py`, never bundled. First-run setup warms them;
otherwise they derive lazily on first request into
`storage/nucleome/sprites/`.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/nucleome/sprites` | Manifest: frame filenames + Randall's blink track (`[frame, face_index]` pairs, 1200-frame loop) + shine loop/reflect frame lists (60 fps). 503 until a vanilla ISO is recorded. |
| GET | `/api/nucleome/sprites/{name}` | A derived sprite PNG (manifest filenames only; cached 24h) |

### Combos

Browsing retains exact counts and stable pagination. The query selects page IDs
before fetching combo/replay JSON, and schema initialization adds covering
recent-order indexes for attacker/victim connect codes. Status counts pending
games directly in SQL using the same eligibility predicate as extraction; it
does not load all pending replay paths and player payloads into Python.

Combo browser over frame data (`tracker/combos/combo_index.py`): a slippi-js-
style state machine over each replay's Post-Frame events, stored in the
`combos` table of `storage/nucleome.db`. Extraction is a `combo_scan` job
(from the Combos tab, or the cloud loop when automatic processing is on) and
incremental (games re-read only when the file's mtime differs from
`games.combos_at`). Each combo is flagged `true_combo`: `1` if the victim
never regained control between hits (pure hitstun/throw/tech-chase), `0` if
they had actionable frames in between (a "string"), `null` for rows extracted
before the flag existed (the migration un-stamps `combos_at` so a rescan
backfills them).

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/nucleome/combos/scan` | Start a `combo_scan` job → `{started, job_id}`; 409 `{error, job_id}` while one runs. Its record's `extra`/`result` carry `total, done, found, failed` |
| GET | `/api/nucleome/combos/status` | `{counts: {combos, games_scanned, games_pending}}` |
| GET | `/api/nucleome/combos` | Filterable list. Query: `mine=me\|vs`, `char`/`opp_char` (attacker/victim external ids), `stage`, `opponent` (code/name search), `min_moves`, `min_damage`, `kills=1`, `min_start`/`max_start` (percent), `kind=true\|string`, `sort=recent\|damage\|moves\|start_percent\|duration` + `direction=asc\|desc` (any metric, either way — UI toggles it), `limit` (capped 2000), `offset` → `{total, combos: [...]}`, each combo carrying `moves_list`, `true_combo`, and an embedded `game` object |

`POST /watch-mods/start` additionally accepts `start_frame`/`end_frame` to
play just a combo's slice of the replay (playback Dolphin queue mode, padded
60 frames in / 90 out).

Both `POST /watch-mods/start` and `POST /watch-mods/playlist-start` take the
playback options `widescreen` and `no_music` (`/start` also takes `anonymize`).
They are one per-user GameSettings override in the playback Dolphin
(`User/GameSettings/GALE01r2.ini` + `GALE01.ini`): `widescreen` enables Slippi's
shipped `$Optional: Widescreen 16:9`, `no_music` enables its shipped
`$Optional: Game Music OFF` (BGM starts at volume 0; audio only, no sync
effect), and `anonymize` disables `$Optional: Show Player Names`. The file is
removed when the job ends, including on error, and a user's own file it
replaced is put back.

Both start routes answer `{started, job_id, ...}`: the watch is a
`replay_watch` job (Jobs Blueprint), and the popup follows its record. 409
`{error, job_id}` while another watch runs (its id) or a Combo Video final
render holds the playback Dolphin (`job_id` null). The job owns the playback
Dolphin and each setting it changed (frame/audio dump flags, `AspectRatio`, the
override files), so they are put back when it ends, or at the next start after
a crash.

Recording requires nonempty Dolphin audio samples and a successful ffmpeg mux.
Missing/empty/invalid audio, encoder launch/timeout/nonzero-exit failures, and
empty output become job errors; there is no video-only AVI success fallback.
Failed partial MP4s and two-pass logs are discarded. Completed playlist outputs
remain available if a later game fails.

### Vault (gated: `NUCLEUS_VAULT`)

Pairing and cloud push for the mobile vault (routes in `tracker/routes/cloud.py`,
`tracker/cloud/vault_client.py` transport, `vault_jobs.py` background threads). **Shipped in 0.7.2.**
`NUCLEUS_VAULT` remains as a hand-set kill switch, but `electron/main.js` no
longer forces it off — `tools/build/preflight.py` BLOCKS a release if
`NUCLEUS_VAULT` reappears in `PACKAGED_OFF_GATES`. See
`research/docs-research/mobile-vault.md`.

Sync and share need a stored Patreon app token, but **a free ($0) Patreon
account is enough** to share. Two actions still need an active pledge —
**pairing a phone** and **whole-library sync** — because both exist to serve
the phone app. Sharing one replay is free and uploads that replay on demand.

The pledge is mirrored from the viewer into the `vault_pledge_active` kv key
by `POST /vault/token`: the backend holds the app token but cannot run the
Patreon entitlement check, which lives in the viewer. Absent means "not yet
told" and permits sync; only an explicit `false` refuses. The viewer sends the
token from `App.jsx` (`tracker/cloud/vaultTokenMirror.js`) at launch and on
every Patreon link change, not only when Settings → Cloud is open. That mirror
never sends `null`, so a sign-out remains `clearPatreonToken()`'s job. It
omits `active` when the entitlement check failed, because an offline check
must not store a lapsed pledge.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/nucleome/vault/status` | Also returns `upload_history` (last 30 UTC upload days: `day`, `uploaded_at`, `games`) and `shared_links` (last 100 locally saved URLs with `game_id`, `combo`, `shared_at`, `start_at`). Records clear on credential changes; history counts only acknowledged uploads after this update. `{configured, pledge_active, auto_scan, auto_sync, synced, pending, unsyncable, last_sync_at}`. `synced` counts games either transport settled (a frames row at the current deriver or a raw row at the current codec). A running sync is its `cloud_sync` job (`GET /api/jobs`), not part of this response. Local only — never calls the vault. `pledge_active` is the mirrored value the autorun acts on (`null` = never told), not a live entitlement check |
| POST | `/api/nucleome/vault/token` | `{token, active?}` validates a new token against the Vault before storing it (401 invalid, 502 verification unavailable; previous credentials preserved on failure) and cancels subsequent work on credential change. Re-sending the stored token skips validation and is not a change; only `active` is applied. It stores the Patreon app token (`null` clears it, and clears the pledge with it) → `{configured}`. The token is never returned. `active` mirrors the viewer's cloud pledge (`isCloudPaid`, any paid tier; not AI access) into `vault_pledge_active`; omit it to leave the stored value alone. When the stored pledge TURNS true for the first time on an install, `auto_scan`/`auto_sync` go true where they were never set (kv `vault_paid_defaults_applied` records it once; a payer already mirrored as true keeps their toggles). A pledge that turns true (or arrives with a new token) starts the autorun chain when `auto_sync` is on (`vault_jobs.kick_autorun`: now, or one more pass after the running chain). A new token without `active` is stored as not paid (`false`) until told. Requests are handled one at a time, so a token still being checked cannot be stored after a later clear |
| GET,POST | `/api/nucleome/vault/settings` | `{auto_scan, auto_sync}` launch flags, both default false until the first paid pledge (see `/vault/token`). A POST may carry either key alone; an explicit false is kept |
| POST | `/api/nucleome/vault/pair` | `{label}` → the vault's mint result plus `pair_url`. The **only** time `device_token` exists — the vault keeps a hash. Needs an active pledge: a free account gets `502 {"error": "pledge_required"}` |
| GET | `/api/nucleome/vault/devices` | `{devices: [...]}` |
| POST | `/api/nucleome/vault/revoke` | `{device_id}` → `{revoked}`. Deliberately does **not** need an active pledge — a lapsed user must still be able to revoke their own devices |
| POST | `/api/nucleome/vault/sync` | Start the push as a `cloud_sync` job → `{started: true, job_id}`; 409 `{error, job_id}` if one is running; **402 `pledge_required`** when `vault_pledge_active` is false. The job's `extra` has `stage` (`reconcile` while it checks pending games against what the cloud already holds, then `upload`; `combos`/`conversions` in the raw metadata follow-up), `done`/`total` (games in the stage) and `progress_at`; its result is `{mode: "upload", transport, pushed, skipped, failed, timings?}` or `{mode: "metadata", committed, conversions, failed}` |
| POST | `/api/nucleome/share` | `{game_id, combo_id}` → `{id, url}`, the permanent public `ssbmnucleus.net/replay/<id>` link. A selected combo is checked for membership in that game's public list before upload; unavailable or below-threshold selections return 404 without syncing or minting. The publishing floor remains four moves, using legacy hit counts only when move data is absent. **Uploads an eligible game if it is not in the vault**, so the first share can be slow. Re-minting the same game returns the same id, and an already-pushed game is not re-uploaded. 409 if the replay cannot be prepared (unparsed, missing, or the deriver refused it) |
| POST | `/api/nucleome/share/thumb` | `{id, png_b64}` stores the unfurl thumbnail. Drawn client-side (`ShareLinkButton.jsx`) and pushed un-awaited, so a failure here never blocks the link |

Routes needing a token read it from the kv and answer `400 {"error":
"not_configured"}` when none is stored; a `VaultError` (dead token, vault
offline, `pledge_required`) maps to `502`, not a 500. Note the vault returns
entitlement verdicts in-band with HTTP 200 and a body `{"error": ...}`, which
`vault_client._call` raises as a `VaultError` — so the *code* survives to the
UI, but the *status* is always 502.

Launch autorun: `vault_jobs.maybe_autostart()`, called from `app.py`, runs replay scan → combo scan → sync in one daemon
thread when the kv flags say so, then repeats every 10 minutes while the app is
open. After the sync, it runs the one-shot combo wire-basis metadata refresh. That
refresh comes last because, after a credential change, it re-commits the whole
library. When auto-sync is on but cannot run because no token is stored or the
pledge is `false`, the backend log says so once per change ("uploads paused").
kv keys: `vault_app_token`, `auto_scan_on_launch`, `auto_sync_on_launch`,
`vault_last_sync_at`, `vault_pledge_active`, `vault_paid_defaults_applied`.

The Combos tab's **"Play [N] combos"** queues the top N filtered combos (N is
user-set, default 25, UNcapped in the UI — combo marathons are a feature — with
only a high `PLAYLIST_CLIP_CAP` = 2000 runaway backstop, in the current
sort+direction order) back-to-back and can dress the whole reel from one
stateless ISO. Both endpoints take `clips: [{game_id, start_frame, end_frame}]`
and frames get the same 60-in/90-out padding.

The Replays tab's multi-select ("Watch / record N games") feeds the same two
endpoints with WHOLE games: each clip carries `full: true`, and the backend
then plays `-123 .. games.last_frame` unpadded, reading the frames from its own
index (the client's `end_frame` is only a fallback when `last_frame` is NULL;
a full clip with neither is dropped). Games are queued oldest first; recording
produces one video of the whole queue. `GET /api/nucleome/replays` rows expose
`last_frame` for this.

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/nucleome/watch-mods/playlist-options` | Union across the queue: `{clip_count, characters: [{character, fighter, costumes: [slots], skins}], stages: [{stage, mods}], vanilla_iso, playback_ready}` |
| POST | `/api/nucleome/watch-mods/playlist-start` | Build one ISO covering every char/stage, then play the queue. `{clips, char_selections: {charId: skinId}, stage_selections: {stageId: variantId}, record, compress, widescreen, no_music, record_dir?}`. A per-character skin installs at **every** costume slot that fighter uses across the queue (replays load by index); a per-stage variant installs as each stage's default Gr file. Recording a queue of **whole games** (`full: true` clips) saves one video per game into `record_dir` (absolute; persisted as the recording folder), one playback Dolphin run per game on the shared ISO, each compressed separately when `compress`; the job then carries `params.batch_total` and `extra.batch_index` / `extra.recordings`. Combo queues record one video. Returns `{started, job_id, clip_count, per_game, record_dir}` |

### Watch playback window (Windows only)

The playing Dolphin shows IN the Watch modal as a live capture, the same one
as Test in game: `playback._set_playback` registers the process with
`shared/ingame/embed.set_active(..., show_gui=True)`, Electron's capture host
reads it from `/api/mex/test-in-game/window/capture-target`, and after the
first decoded frame the render window and Slippi's GUI shell (toolbar, seek
bar) go behind the app. Pop out puts both back where Dolphin opened them, in
front of the app. The watch job's record carries `extra.capture_session_id`,
the session the modal's capture may attach to, and `params.widescreen`, which
picks the 4:3 or 16:9 stage. Before
every launch the backend forces `RenderToMain = False` in the playback
Dolphin's `Dolphin.ini`: with render-to-main the game draws inside the GUI
shell window and there is no dedicated render window to capture.

The routes below are the older overlay, used only by a renderer without the
Electron capture (a browser preview):

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/nucleome/watch-mods/window/position` | Pin the render window over `{x, y, width, height}` (physical px). `found=false` until the window exists |
| POST | `/api/nucleome/watch-mods/window/park` | Move the render window offscreen (placeholder hidden/unmounting) |
| POST | `/api/nucleome/watch-mods/window/popout` | Detach into a normal desktop window (chrome restored, not topmost). position/park no-op until popin |
| POST | `/api/nucleome/watch-mods/window/popin` | Re-embed after a popout (next position tick re-strips the chrome) |
| POST | `/api/nucleome/watch-mods/stop` | `{job_id}` (required, 400 without): stop that watch job and close its playback Dolphin; a per-game recording batch ends after saving the game in progress (finished videos are kept). Stopped while it plays, the job ends `done` with what it recorded; during the build, `cancelled`. An id that is not the running watch stops nothing: `{stopped: false}` |

Off Windows every window route answers `supported: false` alongside
`found: false` — window embedding has no Wayland/X11 analog, so the frontend
shows a "playing in a separate Dolphin window" state and hides pop-out/in
controls. Playback itself works everywhere; only the embedding is
Windows-only. (`/api/mex/test-in-game/window/*` follows the same contract.)

### Coach (Randall) — paid-gated

**Unreleased — gated out of packaged builds.** `electron/main.js` sets
`NUCLEUS_RANDALL=0` in shipped builds, which 404s every `/api/nucleome/coach/*`
endpoint (`_requires_randall` in `randall/routes/coach.py`), and the viewer
hides the Analyst tab and elides the CoachPage chunk from the production
bundle (`RANDALL_ENABLED` in `shared/config/features.js`). Dev builds have it all.
The baseline packs still ship — the Stats page's `/deep/baselines` reads them.

The coach engine (`randall/coach/coach_api.py`) streams a multi-round tool
loop against OpenRouter (`z-ai/glm-5.2`). **The API key comes from the
subscriber**: the viewer checks the website's `ai-entitlement` Supabase edge
function (a linked Patreon account → per-user provisioned OpenRouter key whose limit is
a one-time free pot plus the tier's monthly budget, reset on the 1st; the model is in the
meleeWebsite repo's `docs/ai-budgets.md`; see `frontend/src/shared/account/entitlement.js`) and passes
the key per request. Dev builds fall back to `<monorepo>/.env`
`OPENROUTER_API_KEY` (`status.dev_key: true`); packaged builds ship no `.env`,
so without an entitlement key the chat returns a locked error event.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/nucleome/coach/status` | `{ready, reason, model, usage: {spent, cap}, dev_key}` — `ready` = engine importable; `dev_key` = local .env key present (dev builds bypass the Patreon gate) |
| POST | `/api/nucleome/coach/chat` | `{messages, mode, api_key?}` → SSE stream of `{type: "tool"\|"answer"\|"error"}` events. `api_key` = the subscriber's provisioned OpenRouter key |

### Combo Video (`combo_video_bp`, `/api/nucleome/combo-video`)

**Unreleased — gated out of packaged builds.** `electron/main.js` sets
`NUCLEUS_COMBO_VIDEO=0` in shipped builds, which 404s every endpoint in this
section, and the viewer elides the page from the production bundle
(`COMBO_VIDEO_ENABLED` in `shared/config/features.js`). Dev builds have it all.

Music-synced combo videos: upload a song, the analyzer (numpy + ffmpeg
decode, no librosa — `tracker/video/combo_video/analyzer.py`) finds beats,
drops, and multi-band "hype moments"; the pure scheduler (`tracker/video/combo_video/sync.py`)
arranges combos from the combo index so killing blows land on those moments.
Preview is the audio-slaved Watch Lite player; exports are (a) an in-browser
WebCodecs render muxed with the song and (b) a real-Dolphin final render
(`tracker/video/combo_video/assemble.py`: per-game unthrottled frame dump at ~10x realtime,
frame-index cuts into `storage/combo_video/clips/` cache, one ffmpeg concat
under the song; known limitation: the dump's first frame varies a few frames
per boot, so final-render sync carries up to ~0.25 s per-clip jitter).

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/nucleome/combo-video/songs` | Upload (multipart `file`, `name`; `.mp3/.wav/.ogg/.m4a/.flac`); starts analysis |
| GET | `/api/nucleome/combo-video/songs` | `{songs: [{id, name, duration, analyzed, analysis_error}]}` |
| GET/DELETE | `/api/nucleome/combo-video/songs/{id}` | Song + `analysis` (GET `?`with_analysis) / delete |
| GET | `/api/nucleome/combo-video/songs/{id}/audio` | Range-capable audio stream (the preview's `<audio src>`) |
| POST | `/api/nucleome/combo-video/songs/{id}/analyze` | Re-run analysis (409 while one runs) |
| GET | `/api/nucleome/combo-video/analyze/status` | `{running, song_id, step}` |
| POST | `/api/nucleome/combo-video/timeline/generate` | `{song_id, strictness, filters (combos vocabulary + date_from/date_to), t0?, t_end?, anchor?, allow_repeats?, debug?}` → `{timeline_id, version, timeline}` |
| POST | `/api/nucleome/combo-video/timeline/reflow` | `{timeline_id, base_version, strictness?, ops: [{op: swap\|remove\|move\|lock\|reroll, slot_id, …}]}` — 409 + current version if stale |
| GET | `/api/nucleome/combo-video/timelines` | `?song_id` → saved timelines |
| GET/DELETE | `/api/nucleome/combo-video/timelines/{id}` | Stored timeline / delete |
| GET | `/api/nucleome/combo-video/alternatives` | `?timeline_id&slot_id&limit` → swap candidates with `fit_score` |
| POST | `/api/nucleome/combo-video/export/mux` | Multipart WebCodecs `video` + `song_id` + `codec` (avc = stream copy, vp9 = transcode) → `{path}` (lite export) |
| POST | `/api/nucleome/combo-video/export/start` | Final render: `{timeline_id, char_selections, stage_selections}` (playlist-start vocabulary; union ISO dresses every clip) → `{started, job_id}`, 409 while a render or a watch runs. The render is a `combo_video_render` job: follow it at `GET /api/jobs/{job_id}` (`extra.phase`: starting/building-iso/recording/cutting/assembling, `extra.clip_done`, `params.clip_total`, `result.output`), cancel it at `POST /api/jobs/{job_id}/cancel` |
| POST | `/api/nucleome/combo-video/export/reveal` | Explorer-reveal an export under the recording dir |

---

## Echo (engine only, no routes)

The Echo engine clones a vanilla fighter and changes its attack values.
An Echo is a **diff** (`echo.json` = donor + ops) materialised into an
ordinary custom-character package, so it lives in the vault and installs via
the normal custom-character path. It has no HTTP routes: Randall's clone tool
(`randall/assistant/clone_character.py` over `vault/echo/clone.py`) and the CLIs
(`python -m vault.echo`, `python -m vault.echo.tier2`) drive it. The op schema
(`backend/vault/echo/ops.py`):

```json
{"op": "set_hitbox",    "move": "ftilt", "part": "mid", "hitbox": 0, "field": "damage", "value": 14}
{"op": "set_hitbox",    "move": "usmash", "hitbox": "all", "field": "knockback_growth", "delta": 20}
{"op": "set_throw",     "move": "dthrow", "field": "angle", "value": 90}
{"op": "set_command",   "move": "neutralb", "part": "start", "command": 3, "field": "frame", "value": 4}
{"op": "set_attribute", "name": "gravity", "value": 0.13}
{"op": "set_script",     "move": "ftilt", "part": "mid", "commands": [
    {"cmd": "asynchronous_timer", "frame": 3},
    {"cmd": "create_hitbox", "id": 0, "bone": 40, "damage": 25, "size": 2000, "angle": 361, ...},
    {"cmd": "asynchronous_timer", "frame": 12}, {"cmd": "clear_hitboxes"}]}
{"op": "insert_command", "move": "ftilt", "at": 2 | "end", "command": {"cmd": "...", ...}}
{"op": "delete_command", "move": "ftilt", "command": 3 | [3, 4]}
```

Moves use community ids (`ftilt`, `usmash`, `nair`, `neutralb`, `airsideb`,
`dthrow`...; loose spellings like "forward tilt" resolve). `hitbox` is the
ordinal of the Create Hitbox command in the part's script, or `"all"`. Every
op validates before anything is written; errors come back all at once.

Script ops (`set_script` / `insert_command` / `delete_command`) author a
move's subaction script instead of editing values in place: commands are
dicts in the shape `inspect_move` lists them (`cmd` = key, name or opcode;
unlisted fields are 0; `subroutine` / `go_to` take `pointer` = data offset of
an existing script; an End Of Script is appended). Indices refer to the
CURRENT script and later ops in the batch see the rewrite. The new script is
appended to the DAT and the action slot repointed -- nothing existing moves,
so value ops on other moves and compiled code roots stay valid. Plan steps
for these carry `commands` (the resulting list) and `before`/`after` =
command counts. PROVEN in-game 2026-09-03 (`backend/vault/echo/tier2/README.md`).

Compiled move logic (Tier 2): `code: {"entry": "fighter.c", "files": {name:
text}}` in `echo.json`. The sources are the scaffold from
`python -m vault.echo.tier2 scaffold --donor <name>` (donor special-state table,
hooks in `moves.c`); `materialize` compiles them with MexTK and appends the
`ftFunction` root to the data DAT after all other edits and raises with the
compiler output when they do not compile. Requires MexTK +
devkitPPC on the machine (`python -m vault.echo.tier2 info`). See
`backend/vault/echo/tier2/README.md`.

Animation overrides (`animations` in `echo.json`, checked by
`anim.validate_overrides`), one of `file` / `clip` / `source` / `exaggerate`:
`{ move, part?, clip: <id> | file: <path> | source: <move> (+ source_part?) |
exaggerate: <factor>, error?: <key tolerance>, map?: <joints.ini> }`. Clips keep
the donor's skeleton (same joint count); a clip authored with named joints
needs `map` (`JOBJ_<n> = <name>` per line). Each clip must fit the game's
0x8000-byte per-animation buffer -- the import raises the key tolerance until
it does, or fails.

## Electron viewer frames and lifecycle

`setMaterialColors` accepts an `edits` array of up to 4096 `{id, field, value}`
entries and validates the whole batch before writing. It uses the same material
reply and request ID. The palette queues updates and awaits acknowledgement
before exporting; color alpha remains unchanged during hue/saturation edits.

Native material commands use `viewerSend` with a `requestId`:
`getMaterials`, `setMaterial` (`id`, `field`, `value` or `reset:true`), and
`previewBaseColors` (`enabled`). They reply with `type:materials`, the same
request ID, `success`, `materials`, and `previewBaseColors`; failures use the
same reply type with `error`. Each material lists its ID, display name, fields,
animation marker, render flags and shared-mesh count. Colors are #rrggbbaa;
opacity is 0..1 and shininess 0..128. Capability `materialColors:true` advertises
support; paired editing is currently rejected. This is native IPC, not a new
HTTP endpoint. Preview state is excluded from DAT exports.

`viewerStart(options)` accepts `viewerSessionId` and returns it with `connected`
and `streaming`. All platforms use streaming by default; only an explicit
Windows `NUCLEUS_VIEWER_TRANSPORT=embedded` environment override selects the
native overlay. `viewerStop(viewerSessionId)` refuses to stop a different active
session; omitted IDs retain the legacy unconditional-stop behavior.
`viewerRunning(viewerSessionId)` is true only while that session is the app's
running, connected viewer: a view kept off screen (the Randall workbench) asks
it on the way back, since another view's start replaces it silently.

`onViewerFrame(callback)` passes JPEG bytes and `{viewerSessionId,frameId}`.
The owning subscriber must call `viewerFrameConsumed(metadata)` after drawing
or discarding its frame, including cleanup and decode failures. Main sends at
most one unacknowledged frame and retains only the latest pending replacement.
Old/duplicate acknowledgements cannot advance a newer session. `capabilities`
events describe the native host; authoritative native animation ticks disable
the legacy estimated ticker. The preview JPEGs do not change texture/DAT export
formats. See [VIEWER_STREAMING.md](VIEWER_STREAMING.md).

## Electron data-location interface

These are trusted local IPC operations, not HTTP routes. Errors return
`{success:false,error}`; status and successful schedule/cancel calls return
`{success:true,currentRoot,scratchRoot,pending,previousRoot,progress,busy,disabledReason}`.

| Preload method | IPC | Behavior |
| --- | --- | --- |
| `getStorageLocation()` | `storage:status` | Read the current and scheduled locations |
| `chooseStorageLocation()` | `storage:choose` | Native parent-folder picker; returns `path` or `canceled:true` |
| `scheduleStorageLocation(destination)` | `storage:schedule` | Validate and persist a move for the next full launch |
| `cancelStorageLocation()` | `storage:cancel` | Clear the pending move; retain original and partial copies |

No live move or restart IPC is exposed. Startup recovery can explicitly select
the previous copy; it does not merge subsequent changes. The offline worker's
activation handshake and environment contract are in
[STORAGE_LOCATION.md](STORAGE_LOCATION.md).

## WebSocket Events Summary

| Event | Source | Data |
|-------|--------|------|
| `job` | Jobs | a job record (see Jobs Blueprint): first-run setup, in-game tests and captures, export, texture pack, patch build/create/play, bundle export/install/play, Vault restore, Watch, Combo Video render |
| `test_progress` | Test In Game (interactive session) | `{ sessionId, sequence, stage, percentage, message }` |
| `test_complete` | Test In Game (interactive session) | result with verdict + screenshots |
| `test_error` | Test In Game (interactive session) | `{ sessionId, sequence, error }` |

### Tracker cloud indicators

`GET /api/nucleome/replays` includes `synced` and nullable `share_url` on each
game. `POST /api/nucleome/share` saves successful minted links locally (including
combo ordinals) only if the connected credential still matches. Account history
uses the `vault-read` action described below.

`GET /api/nucleome/vault/activity` reads the authenticated owner's existing cloud
upload totals and share links through bounded `vault-read` `activity-page` requests.
Returns `upload_history` (UTC days/counts) and `shared_links` (URL, content hash,
replay date and players), plus nullable `next_uploads` and `next_shares` cursors.
Initial loads return up to 30 upload days and 50 shares (two Edge calls).
`?kind=uploads&cursor=YYYY-MM-DD` or `?kind=shares&cursor=<id>` fetches only the
requested next page (one Edge call). Cursors are exclusive; upload dates descend
and share IDs ascend. The client never crawls history automatically.
Backend pages are cached in memory for five minutes by credential hash/kind/cursor,
with at most 64 entries. `refresh=1` bypasses the normal TTL after a 30-second
minimum interval; failures are also cached for 30 seconds. Concurrent reads
share cache fills. Cache expiry is checked on demand, with no background polling.
Backfills saved-link badges for mapped local replays in the returned page,
without minting public links. Returns 409 on account changes and 502 on remote
failure (400 for invalid page parameters). Requires the unapplied
`20260906_vault_activity_pages.sql` migration, then deployment of `vault-read`.
The older raw `activity` action remains compatible with existing installers.


### Stage Creator (`stage_editor_bp`, 2 routes)

- `POST /api/mex/stage-editor/open`: `{stageCode, variantId?}` opens a private
  copy of a vanilla stage or vault variant. Returns `id`, `datFile`, `datName`,
  stage/folder/member identity. Source archives must contain one unambiguous base
  DAT; companion files are retained. Native viewing uses the Electron stream host.
- `POST /api/mex/stage-editor/save`: `{workspaceId, data, name, screenshot?}`;
  data and optional PNG screenshot are base64. Writes a unique new vault variant
  and metadata, returns `{success, variantId, folder, name, stageCode,
  vault_changed, slippi_tested:false}`. Does not overwrite existing files. Invalid
  source IDs, changed sources, invalid exports and invalid names fail explicitly.

Assistant schemas additionally expose `stage_lab_open(stage_code, variant_id?)`
and `stage_lab(session_id, action, ...)`; actions are inspect/frame/texture/
replace_texture/recolor/camera/animation/materials/set_material/reset_material/
preview_base_colors/scene/preview_objects/copy_objects/transform_scenery/
hide_objects/export/save/close. PNG inputs use opaque file IDs. Private native
sessions are bounded to two; caller closes when finished.

Scene inspection returns exact object IDs and `can_receive` destination groups.
`preview_objects` and `hide_objects` take `object_ids`; `copy_objects` also takes
`source_session_id`, `target_group`, optional `animation_index` and `transform`.
`transform_scenery` requires the returned `instance_id` and an absolute
`transform` (x/y/z, rx/ry/rz degrees, uniform scale). Scene mutations return a
new DAT and rendered PNG. `export` returns the current DAT as a file ID.
The `hsdraw` equivalents are stage_scene/preview_stage_objects/copy_stage_objects/
transform_stage_scenery/hide_stage_objects, using `file_id` and `donor_file_id`
instead of sessions. See RANDALL_RECOLOR for selection, animation and preservation limits.

Shaded `model_render` inspection requires local Blender. The isolated renderer
reads the exact candidate and checks Blender/LBS playback agreement; it does not
grant gameplay acceptance. There is no artist-mode switch: `model_source`,
`model_region`, `model_prop`, `model_probe` and `model_script` are always offered,
and Randall routes to them itself. Randall-authored Python (`model_script`, and
`model_probe` with `script`) no longer execute: the AppContainer sandbox that was
meant to confine them was removed unwired.

When repeated entries along one source branch bind to the same target joint,
rest alignment now shares the ancestor transform and retains descendant offsets
(e.g. head plus facial joints). Redundant unweighted controls that own no skin
and point only to the same mapped destination are omitted as rest anchors.
Separate branches remain separate deliberate anchors. Fitting receipts record
`rest_anchor_source_joints` and `inherited_rest_source_joints`; weights still
follow the explicit binding map. Use small anatomical maps with inherited
attachments, then inspect motion; this does not infer correct anatomy.

### Pre-binding model placement (Randall chat)

`model_fit` accepts `placement_only` (boolean) and `bind_translation` (three
finite numbers, each -30..30). Placement requires explicit characters after
the normal alignment check; translation requires one target. With
`placement_only=true`, the reply has `operation=placement`, `placements`,
`target_weights_assigned=false`, overlay images, and no candidate handles.
No target binding, bone heat, motion validation or native export runs. Unrigged
sources without an explicit `bind_translation` automatically return this preview
with `binding_deferred=true`. Legacy alignment handles without source-kind
evidence use the same preview path. Repeat the same file/alignment/target/options
with `placement_only=false` and an explicit correction to bind; `[0,0,0]` is an
intentional choice of default placement. Authored skin inputs keep their normal
binding path. This enforces an explicit placement choice, not visual acceptance.
Translation is absolute relative to automatic placement in target coordinates,
applied before weight assignment; repeated calls do not accumulate it.
