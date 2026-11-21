# SSBM Nucleus — Architecture Map

Evergreen dev doc (see [DOCUMENTATION.md](DOCUMENTATION.md) for tiers). Keep
this current: new blueprint / package / hook / gate → update the matching table.
Last full rewrite: 2026-08-22; layout, the backend tables (§3), layering rules (§3.6) and the debt register (§9) rewritten against the tree on 2026-10-03 after the reorganisation.

---

## 1. The 30-second model

**Two products in one desktop shell, sharing one data directory.**

| Product | UI mode | What it does | Backend home |
|---|---|---|---|
| **Nucleus** (default) | `nucleus` | Melee mod manager: vault of costumes/stages/menus/codes, install into an m-ex project, build an ISO | everything under `/api/mex/*` |
| **Tracker** (internal id `nucleome`) | `nucleome` | Slippi replay stats, combos, tournaments, cloud Vault (phone pairing + replay sync, shipped 0.7.2), and, from 0.7.3 to 0.8.15, Friends (removed in 0.8.16; the code is on the `archive/friends` tag); Randall (AI analyst) and Combo Video remain **gated off** in shipped builds | `/api/nucleome/*` → `backend/tracker/` |

The user flips modes by clicking the header wordmark. Both modes are one React
app talking to one Flask process, launched by one Electron main process.

```
 ┌──────────────── Electron main (electron/main.js) ────────────────┐
 │  spawns ──► Flask backend (backend/app.py, :5000 or next free)    │
 │  loads  ──► React viewer  (dev: Vite :3000 / prod: frontend/dist)   │
 │  hosts  ──► HSDRaw native renderer → canvas (all platforms) │
 └───────────────────────────────────────────────────────────────────┘
         React ──HTTP fetch + Socket.IO──► Flask
         Flask ──subprocess──► MexCLI (C#) · HSDRawViewer (C#) · xdelta · Slippi Dolphin
         Flask ──files──► storage/ (the vault) · projects/ (m-ex projects) · output/
```

Repo layout (2026-10-03): this document describes `app/` (backend, frontend,
electron, `utility/` for the vendored toolchain, `tools/build/`). Beside it:
`services/` (Cloudflare workers + phone PWA, deployed separately; they talk to
Supabase, not to this backend), `docs/` (`dev/` is this tier, `guide/`, `wiki/`),
`tools/` (every dev-only script: harness MCP, Dolphin driver, admin, wiki server,
`clean.py`), `eval/` (benchmarks), `tools/rank-baselines/`, `research/`.
Rule: if it is not in the installer it is not in `app/`. Vendored dependencies
(MexManager fork, HSDLib, the AI runtime) live in `app/utility/`.

---

## 2. Process model and startup

1. `electron/main.js` spawns the backend through `electron/runtime/backend.js` — dev: `venv` python running
   `backend/app.py`; prod: the PyInstaller exe `mex_backend` from
   `process.resourcesPath`. Packaged builds get feature-gate env vars (§7).
2. `app.py` picks a free port from 5000 and prints `BACKEND_PORT:<n>` to
   **both** stdout and stderr; Electron regex-matches it (60 s timeout) and keeps
   an 80-line ring buffer of backend output for the `backend-diagnostics` IPC.
   If the backend dies after this point outside a quit, `runtime/backend.js` sends
   `backend:exited` to the window and records the exit in `backend-diagnostics`;
   `shared/ui/BackendStoppedScreen.jsx` covers the app and offers Restart
   (`app:relaunch`, a full relaunch, since the renderer holds the port and token).
3. Window load — dev: wait for Vite to write `frontend/.vite-port`, then
   `loadURL`; prod: `loadFile(frontend/dist/index.html)`.
4. React mounts; `FirstRunSetup` replaces the whole app until
   `GET /api/mex/setup/status` says setup is complete (ISO located, vanilla
   assets derived).
5. Shutdown is defensive: Windows `taskkill /F /T`, POSIX process-group kill.

`app.py` (was `mex_api.py`) is the **only** app entry point (no factory). Boot order inside
it: `freeze_support()` first line (PyInstaller fork-bomb guard) → the `--storage-maintenance`
and `--build-smoke-test` dispatches (both exit before Flask; the smoke routine is
`core/build_smoke.py`) → Flask + CORS
→ SocketIO(threading) stashed in `core.state` → optional SQLite vault migration
→ 38 `register_blueprint` calls → launch side-effects guarded by
`_IS_MP_SPAWN_CHILD` (vault autostart) → `socketio.run`.

---

## 3. Backend (`backend/`, ~170k lines Python)

### 3.1 Layout

Folders mirror how the app works for a user, with the same areas as the frontend (§4):
**Vault**, **Projects**, **Upload**, **Tracker** and **Randall**, plus `shared/` for the
engines and routes several areas use. Each area keeps its HTTP routes in its own
`routes/` package (§3.2). The backend runs with `backend/` on `sys.path`; the top-level
packages are `core`, `vault`, `projects`, `upload`, `tracker`, `randall`, `shared`,
`nucleus_api`, `devtools`, `file_retry` and `mexcli` (reorganised 2026-10-03; ids did not move:
every URL, blueprint name, socket event, env var, DB filename and storage path is the
same). `tests/backend/test_backend_layout.py` pins the root files and the package list.
About 259k lines of Python in all (the two big ones: `randall/` 80k and `shared/` 77k).
The import rules between these packages are in §3.6.

The tables below list every top-level package, then one table per area with its
subpackages. Line counts are approximate (2026-10-03).

**Top level of `backend/`**

| Path | Lines | Role |
|---|---:|---|
| `app.py` | 440 | The bootstrap (was `mex_api.py`): process guards, Flask + SocketIO with the token/CORS/socket-auth gates, startup configuration and migrations, the blueprint registry (imports each blueprint object from its area's `routes/` and registers all of them in one fixed order), launch side effects, main. No routes |
| `mexcli/` | 1.1k | All MexCLI access: `project.py` (`MexManager`, one open `.mexproj` workspace: costumes, layouts, ISO export; was `mex_bridge.py`; must not import `core`, which `tests/backend/test_backend_layout.py` checks) and `commands.py` (`run` / `run_json` / `parse_json`, one-shot commands at `MEXCLI_PATH`, the build lock for the mutating ones; moved out of `core/`; it may import `core`). `__init__.py` imports nothing |
| `storage_data_lock.py`, `storage_relocation.py` | 0.5k | Standalone storage bootstrap (`--storage-maintenance`): runs before `core` initialises and must not import the app |
| `file_retry/` | 0.1k | Retried file writes/swaps behind every vault and build write; must not import `core` |
| `core/temporary_download.py` | 0.1k | Shared one-shot ZIP response ownership for vault backups and mod exports. Closes streams before unlinking, counts overlapping readers, protects replacement files, and finalizes abandoned Windows response iterables |
| `core/` | 11.6k | Flat package of app-wide infrastructure. Config/paths (`config.py`), global singletons (`state.py`), `run_retention.py` (keeps only the newest N test-run dirs), `build_smoke.py` (the frozen exe's `--build-smoke-test` self-check), the vault index (`metadata.py` dispatching to the JSON file or to `vault/__init__.py`, the SQLite store, 335 lines; this `core/vault/` is not the top-level `vault/` package), gecko parsing, critical-op registry, build transaction/authorization/access, the safe archive/extract helpers, `stages.py` — the single registry of all 29 versus stages (codes, names, vault folders, dual-language roots, DAS vs replace mode) that every stage table derives from — `extra_types.py` — the 3.2k-line declarative catalog of every "extra" per character (mirrored by `frontend/src/shared/data/extraTypes.js`; data only) — and `extra_lookup.py` (the lookups over it: a character's extras including shared ones, one extra by id, the storage owner of a shared extra, unit parts) |
| `nucleus_api/` | 4.7k | The in-process scripting facade the assistant's scripts call (`API.md` is its contract; modules `vault.py`, `game.py`, `builds.py`, `codes.py`, `menus.py`, `modfile.py`, `render.py`, `website.py`, `_workspace.py`, `gendocs.py`); `app.py` never imports it, the spec names its modules |
| `assets/`, `data/` | data | `assets/` is tracked: `hud_vanilla/` (the two IfAll slot manifests only; the HUD, pause, series and stage-select pictures are derived from the user's own game by `menu_refs`, none ships), `texture_regions/`, `builtin/`, `vanilla_parts.json`. `data/` holds the seed files the spec ships (`any_climbers.ini`, `clone_engine.dat`, `texture_filename_table_seed.json`, `vanilla_geom_hashes.json`, `menus/compatibility_manifest.json`); those five are tracked so clean release checkouts can build, and anything else written there is git-ignored. Both resolve through `core.config.BACKEND_ASSETS_DIR` / `BACKEND_DATA_DIR` (`_MEIPASS/backend/...` when frozen) |
| `devtools/` | 11k | **Not part of the app** (two lazy imports of `frameshot` aside, §3.6). CLI tools that drive the engines: `frameshot.py`, `effect_probe.py`, `extras_audit.py`, `extras_doctor.py`, `fps_batch.py`, `stress_build.py`, `texture_coverage.py`, `netrig.py`, `osdscan.py`, `slpdiff.py` (`tools/harness/harness_mcp.py` shells out to them); `compare_memory_input.py` compares the native input-backend parity captures `tools/ingame/verify_memory_input.py` makes; `research/fsm_crash_probe.py` is the solo-flow template |
| `probes/` | data | `effect_probe.example.json`, the worked spec for `devtools/effect_probe.py` (new specs follow it) |
| `scripts/build/` | 0.1k | `engine_digest.py`: writes `shared/ingame/engine_digest.json` for a packaged build (the frozen verifier's engine identity) |
| `requirements-ingame-qa.txt` | — | Extra pip requirements for the in-game QA tools |
| `vault/`, `projects/`, `upload/`, `tracker/`, `randall/`, `shared/` | 41k / 13.6k / 0.6k / 17k / 80k / 77k | The product areas and the shared engines; one table each below |
| *(tests)* | — | Not here: every test lives under the repo-root `tests/` (`tests/backend/` is the pytest suite; `conftest.py` builds its own Flask app). Root `pytest.ini` pins `testpaths = tests/backend`; slow tests are marked `-m slow` |

**Vault** (`vault/`, 41k: the mod library)

| Path | Lines | Role |
|---|---:|---|
| `vault/routes/` | 13.3k | The Vault's HTTP (§3.2): `storage_costumes/`, `storage_stages.py`, `custom_characters/`, `custom_stages.py`, `das.py`, `menus/`, `extras/`, `character_sounds.py`, `codes.py`, `bundles.py`, `xdelta.py`, `gaw.py`, `vault_backup.py`, `poses.py`, `import_unified/`, `iso_scan.py`, `climbers.py`, `echo.py`, `stage_editor.py`. Route modules import engines, never another route module |
| `vault/importing/` | 12.5k | Mods **into the vault** (was `mod_vault_import/`): `unified/` (the engine behind `vault/routes/import_unified/`: `normalize.py`, `protocol.py`, `detection.py`, `effect_detect.py`, `archive.py` (dispatch one archive, recurse into containers), the per-kind importers `characters.py` / `stages.py` / `effects.py` / `detected_effects.py` / `menu_import.py`, `dialogs.py`, `helpers.py`), `character_detector.py` / `stage_detector.py`, the ISO scan (`iso_scanner.py` = the job and pipeline; beside it `iso_costume_files.py`, `iso_known_hashes.py`, `iso_slot_art.py`, `iso_ice_climbers.py`), `das_scan.py` (DAS variant detection), `custom_character_scan.py` / `custom_stage_scan.py` (what a custom character / stage carries out of a scanned m-ex build), `custom_character_zip.py` / `custom_character_package.py` / `custom_stage_package.py` (a package ZIP into the vault), `sound_banks.py`, `stage_previews.py`, the Stadium transformation repair (`stadium_transform_fix.py` entry, `stadium_dat.py`, `stadium_baked_split.py`, `stadium_freeze.py`), legacy converters (`fighter_yml_converter.py`, `stage_yml_converter.py`, `vanilla_stage_import.py` + `_specs`) |
| `vault/catalog/` | 0.8k | The vault's side catalogs, shared by the Vault routes and the Projects routes that install or build from them (so neither imports the other): `codes.py` (Gecko code catalog, seeded from the bundled library), `bundles.py` (`.ssbm` bundle storage, index and import), `custom_stages.py` (index read and write) and `custom_characters.py` (index reads; also slugs, the series table, fighter.zip rewriting and the skin CSP lookup), `custom_character_skins.py` (a costume stored as a custom character's skin, special-fighter costumes), `costume_folders.py` (folder rows in a character's skin list) |
| `vault/menus/` | 3.3k | The menu mods engine: `store.py`, the per-kind importers and catalogs (`icons.py`, `backgrounds.py`, `doors.py`, `pause.py`, `percent.py`), the pause and HUD install engines (`pause_install.py`, `percent_install.py`), `installed.py` (the "Currently in MEX" record), the file checks (`menu_checks.py`, `hud_verify.py`, `files.py`), `menu_exports.py`, `menu_pixels.py`, `hsd.py`. Used by the Vault menu routes and the Projects install routes alike |
| `vault/extras/` | 5.8k | The extras engine: the configuration `init_extras_api` sets, offset detection (`offsets.py`), colour reading and patching (`color_read.py`, `color_patch.py`), derive, the texture engines (`textures.py`, `texture_recolor.py`, `texture_region.py`), image effect models (`effect_model.py`, `models.py`), validated static Falco afterimage graph import/restore and active-material color editing (`sideb_model.py`), `unit_parts.py`, `relocate.py`, export-time `apply.py` |
| `vault/climbers/` | 2.2k | Ice Climbers pairs: `roster.py`, `pairs.py`, `colors.py` (colour plan), `portraits.py`, `engine_code.py` and `engine/` (the engine's generated code and its disassembler) |
| `vault/echo/` | 3.9k | Clone fighters: the Echo op surface (`ops.py`, `commands.py`, `_command_table.py`, `moves.py`, `subactions.py`, `anim.py`, `attributes.py`, `donors.py`, `clone.py`, `package.py`) and `tier2/` code generation (`python -m vault.echo`, `python -m vault.echo.tier2`) |

**Projects** (`projects/`, 13.6k: install and build)

| Path | Lines | Role |
|---|---:|---|
| `projects/routes/` | 10k | Open/create a project, costumes in the open project, export, single-mod export, stage slots, music playlists, test in game, and the install halves of the custom character, custom stage, DAS, codes, bundle, xdelta, menu and extras blueprints (§3.2); `menus/` is a package of one module per menu kind |
| `projects/install/` | 3.6k | Mods **into a project / playable ISO** (was `mod_install/`): `export_job.py` (the ISO export job: `run_export_job` is what the Build button's `export_bp` and Randall's delivery in `randall/delivery/deliver_steps.py` both run, one lock discipline and one set of pre-export heals; it runs as the `iso_export` job, whose record is the artifact the Save button's `copy_artifact_to` publishes), `fsm_patcher.py` (FSM bake into main.dol), `texture_pack.py` + `texture_filename_table.py` (Dolphin texture packs), `das.py` (DAS variant naming, archive member checks, the heals export runs on DAS folders), `das_loaders.py` (the DAS loader per stage; Stadium's is rebuilt from the user's own `GrPs.usd` with the shipped xdelta patch), `xdelta.py` (patch storage, xdelta3 resolver, Play worker, the cleanup of patch and bundle jobs' files), `test_build.py` (throwaway test ISO — not a test, hence `pytest.ini`) + `pristine_base.py` (the untouched vanilla project each test build copies), `required_codes.py` (the default-on Gecko codes every export carries, and the codes a user's new project starts with), `project_fighters.py` (the open project's fighter JSONs; which vanilla costume a row replaces), `test_inputs.py` (what a test-in-game build drives). The modpack-duel assembler is archived with the duel archive zip |
| `projects/lload/` | 0.5k | L-load alternate fighters (tap L on the CSS to scroll a fighter's group): `groups.py` (the project's `nucleus_lload.json`, by fighter name), `layout.py` (tucked icons: each alternate's icon hidden behind its base, re-applied on every layout save), `code.py` + `code_words.py` (the per-project Gecko code; `gen_code.py` regenerates the words from `lload.s`), `export.py` (the export step, and the icon repair after `remove-fighter`). Design and evidence: `docs/dev/L_LOAD.md` |
| `projects/nowplaying/` | 0.2k | Now Playing (the song name in the top-left corner at match start): `now_playing.s` (the clean-room Gecko code), `gen_code.py` (regenerates `code_words.py`), `code.py` (its name and hex). New projects get it through `projects/install/required_codes.py`. See `docs/dev/NOW_PLAYING.md` |

**Upload** (`upload/`, 0.6k)

| Path | Lines | Role |
|---|---:|---|
| `upload/routes/` | 0.6k | `publish.py`: push a package to ssbmnucleus.net. No engine package: the packaging comes from `vault/` and `projects/` |

**Tracker** (`tracker/`, 17k; internal id `nucleome`, publicly released; was `nucleome_replays/`). One subpackage per Tracker page, mirroring `frontend/src/tracker/`; every `__init__.py` is inert

| Path | Lines | Role |
|---|---:|---|
| `tracker/routes/` | 2.6k | Its two blueprints (§3.2): `nucleome.py` with the feature modules `replays`, `stats`, `combos`, `lite`, `watch`, `icons`, `ranks`, `cloud`, `share`; `combo_video.py`. The request helpers several feature modules share live in `nucleome.py`, including the cloud-token helpers (`_stored_token`, `_token_or_error`: the stored Patreon app token) that `cloud.py` and `share.py` both use |
| `tracker/store/` | 2.1k | What every page reads: `indexer.py` (the replay index, `storage/nucleome.db`: schema, kv, scans, queries), `identity.py` (the player's Slippi codes and replay folder), the `.slp` readers `slp_meta.py` (header and final state, no dependencies) and `game_trace.py` (cached frame trace), `scan_pool.py` (the one worker process the library passes use), `slippi_rank.py` (rank cache), `games.py` (an indexed game's row and the id -> vanilla/Vault folder tables), `backup.py` (the store in a Vault backup: sanitized snapshot, restore and merge, sign-ins never carried) |
| `tracker/replays/` | 1.6k | Watch with mods: `watch_mods.py` (the `replay_watch` job: a stateless cosmetic ISO built by a headless worker backend, then played or recorded; its cleanup puts back what it changed), `dolphin_config.py` (the Launcher's playback Dolphin: paths, User dir, INI and Gecko overrides), `playback.py` (the running playback Dolphin: embed, pop-out, Stop, launch, per-game recording loop), `recording.py` (frame/audio dumps to mp4, the Discord-sized encode, the recordings folder) and `watch_options.py` (which Vault skins/stage variants fit a replay, playlist checks) |
| `tracker/video/` | 3.5k | Replays without Dolphin. Lite: `viz_export.py` (the viz bundle), `stage_items.py`, `interactions.py` (conversions; the coach's single-game detectors too), `clip_render.py` + `anim_fetch.py` (renderer data and geometry), `clip_refs.py` (tool-issued clip refs), `sprites.py` (ISO-derived UI sprites). Combo Video: `combo_video/` (gated: `analyzer.py`, `sync.py` the scheduler, `assemble.py` the Dolphin final render, a `combo_video_render` job, `jobs.py` the song analysis, `store.py`) |
| `tracker/stats/` | 1.5k | `aggregate.py` (metadata stats; was `stats.py`), `deep_stats.py` (frame-mining the player's own replays), `baseline_ranks.py` (per-stat rank mapping), and the vendored `analyzer.py` + `pack_math.py` (kept equal to `tools/rank-baselines` by `tests/backend/test_vendored_sync.py`) |
| `tracker/combos/` | 0.6k | `combo_index.py` (was `combos.py`): combo extraction into the index and the combo browser's queries |
| `tracker/cloud/` | 2.2k | Nucleus on your phone: `vault_client.py` (transport), `vault_sync.py` (derive and push), `vault_jobs.py` (the `cloud_sync` and `cloud_autorun` jobs), `vault_pair.py` (dev pairing CLI), `vault_assets.py` (the phone's static assets) |
| `tracker/share/` | 0.1k | `links.py`: a combo's public `/combo/N` ordinal |
| `tracker/baselines/`, `tracker/tools/` | data | Two data folders that stay at the package root because the spec ships them to `backend/tracker/{baselines,tools}`: `baselines/` (76 JSON packs for the coach and Stats that `tools/rank-baselines` builds) and `tools/` (Watch Lite renderer data: `charmaps.json` and the dev-fetched `anim_zips/`; see its `RENDERER.md`) |

Tournaments has no backend code: the page talks to start.gg from the frontend and matches sets
against `/api/nucleome/replays`.

**Randall** (`randall/`, 33k: the AI assistant; all of it lives here. The assistant and the app MCP ship since 0.9.0; the Tracker coach (`randall/coach`) and the write paths behind the assistant stay gated off in packaged builds, §7; module-by-module map in [RANDALL.md](RANDALL.md#module-map))

| Path | Lines | Role |
|---|---:|---|
| `randall/assistant/` | 5.4k | The chat itself: the turn loop (`engine.py`), `live_runs.py` (runs, queued inputs, approvals, the SSE stream), `main_model.py`, `prompt.py`, the tool registry (`tools.py`: every tool's schema and dispatch), `tool_stage.py` and `refusals.py` (a refused or failed call as its result), the task cards (`recipes.py`), `turn_facts.py`, `approvals.py`, the chat store (`store.py`), `compaction.py`, `continuity.py`, `app_context.py`, `capabilities.py` and `vision.py`; plus what every pipeline shares: chat file handles (`mod_files.py`), HSDRaw edits and `save_mod_copy` (`hsdraw.py`, `stage_scene.py`), vault rows as tools show them (`vault_items.py`), clone a character. [README](../../app/backend/randall/README.md) |
| `randall/assistant/tasks/` | 3.3k | The task journal: contracts, coordinator, events, SQLite store, content hashes, stage journal |
| `randall/recolor/` | 2.3k | Recolor a costume: the recolor workflow (`workflows.py`: acquire, prepare, create and review), the Skin Lab (`skin_lab.py`, `texture_inspection.py`, `materials.py`), generated materials and the swatch index (`texture_material.py`, `swatch_library.py`), stock costumes as working files (`vanilla.py`), and the Stage Lab (`stage_lab.py`). [README](../../app/backend/randall/recolor/README.md) |
| `randall/website/` | 2.0k | Finding and downloading mods from ssbmnucleus.net into the vault (`website*.py`: search, posts and likes, exports, one approval, quarantine, safety, artwork, receipts, bulk) and `vault_presence.py` (which downloads are in the vault) |
| `randall/delivery/` | 3.4k | Putting a result in the game: `projects.py` (project tools), `destination.py` ("My game"), the delivery chain (`deliver.py` over `deliver_*.py`), in-game play sessions and checks (`game_tests.py`) |
| `randall/reports/` | 4.0k | What Randall sends to the developer: "Report this chat" (`chat_report.py`, `chat_report_files.py`), wishes (`wishes.py` over `wish_*.py`), and `report_transport.py` |
| `randall/model_import/` | 1.6k | The model import ([README](../../app/backend/randall/model_import/README.md)): `chat/` (how a chat starts, runs and reports an `import_model` job, which runs rigswap as a subprocess: `studio_import.py`, `import_job.py`, `attached_model.py`, `textures.py`: the texture files a model names, checked before it runs), `studio/` (the vault save `finish.py` and the Slippi check `slippi.py`). Its native fighter-rig readers moved to `tools/native_rig/` 2026-11-04. The v4 engine was deleted 2026-11-03 (tag `archive/v4-importer`) |
| `randall/coach/` | 3.7k | The Tracker coach's engine (`coach_api.py` SSE loop, `coach_tools_*.py`, `coach_data.py`, `coach_store.py`, `coach_profile.py`) |
| `randall/routes/` | 1k | `/api/assistant` (`assistant_bp.py`), chat reports, wishes, and the coach's `/api/nucleome/coach/*` in `coach.py`, which stay on the Tracker blueprint |

A module too big for one purpose is a package of one-purpose modules whose `__init__`
re-exports every name the module had, so import paths did not change.
Kept outside Randall: `shared/aiengine/` (shared with the coach) and `shared/modellab/` (the fighter table).
Within Randall, `assistant/` registers the tools of the feature packages (`recolor/`, `model_import/chat/`,
`website/`, `delivery/`) and reads `reports/`; the feature packages import `assistant/` helpers but never the
turn loop (`engine.py`) (reorganised 2026-10-03; tool names, schemas, prompts, URLs and storage unchanged).

**Shared engines and routes** (`shared/`, 30k; `shared/__init__.py` is inert)

| Path | Lines | Role |
|---|---:|---|
| `shared/rendering/` | 8.5k | Was `skinlab/`. Costume asset machinery: CSP/stock rendering (`costume_assets.py` = canonical entry, `csp_pool.py` persistent workers, `hd_csp_cache.py`), Ice Climbers editor partner resolution (`paint_pair.py`), DAT/particle decoders, HSDRaw `--stream` client (`session.py`); also the Stage Creator engine (`stage_editor.py`), palette and GX texel helpers, `costume_preview.py`, `csp_frame.py` (the SD/HD portrait frame and deriving both from one picture), and `datprobe.py` (kept byte-identical to its copy in `utility/tools/processor/`) |
| `shared/modellab/` | <0.1k | The fighter table the model import reads (`fighter_catalog.py`: the app's fighter names and Pl codes). The v4 model-import engine that filled it was deleted 2026-11-03 (tag `archive/v4-importer`); the old dev lab is archived in `ssbmNucleus-archive/scripts-modellab.zip` |
| `shared/ingame/` | 11.9k | Dolphin harness: boot an isolated throwaway Slippi, drive it by RAM reads + controller pipe (default) or opt-in `memory_input.py` pad injection for parallel Windows workers, frame-step, screenshot, embed window in app. The metered costume verification is `verify_costume.py` (engine identity and the coordinator that owns the machine) with `verify_profile.py`, `verify_cache.py`, `verify_appearance.py`, `verify_evidence.py` and `verify_outcome.py` beside it. See [input backends](INGAME_TESTING.md#memory-input-for-parallel-windows-workers). |
| `shared/aiengine/` | 1.4k | Provider plumbing for Randall: `image_api` (OpenRouter swatches), `fast_lane` (Gemini delegation), `decisions` (routing), `model_upload` |
| `shared/vanilla_extract/` | 2.9k | Reference data extracted from the **user's own ISO** (never shipped — [VANILLA_ASSET_POLICY.md](VANILLA_ASSET_POLICY.md)): `vanilla_refs.py` reference DATs, `bone_refs.py` validator bone tables, `menu_refs.py` HUD/pause/series art and stage-select icons/banners (first run; while a set is missing, also on project open and at app start from the known ISO), `menu_backdrops.py` the CSS/SSS layout editors' backdrops (`HSDRawViewer --menu-render` on the vanilla `MnSlChr`/`MnSlMap`, on demand and at app start), and `first_run_setup.py` (the first-run flow that extracts them + stages builtins) |
| `shared/diagnostics/` | 0.2k | `bug_report.py`: the logs zip behind Settings' "Download logs" and the in-app bug report (both routes in `shared/routes/setup.py`), and the bug-report worker's settings (URL, report zip budget, platform channel, the Discord bearer header). Randall's feature requests and "Report this chat" send through the same worker with it (`randall/reports/report_transport.py`) |
| `shared/account/` | 0.4k | The Discord sign-in the backend holds: `discord.py` (PKCE sign-in with the local callback, sign-out, the account summary, and listeners that follow identity changes; none registers since Friends went) and `session.py` (the stored Supabase session and its refresh). Publishing and bug reports use its token |
| `shared/routes/` | 2.5k | First-run setup, static assets, legal notices, the HSDRawViewer viewer, Slippi/Dolphin settings, the Discord account (`account.py`) (§3.2) |
| `shared/request_guard.py` | 0.1k | Who may read what (§3.2): the loopback-only Host check around the whole WSGI app (Socket.IO included) and the media/token/deny rule for the file routes outside `/api` |

**Root-level modules** (the only `.py` files at the root): `app.py` (the app),
`storage_data_lock.py` and `storage_relocation.py`. The 41-tool
`melee-harness` MCP server is `tools/harness/harness_mcp.py` ([MCP_SERVER.md](MCP_SERVER.md)).
Scripts in `devtools/` put `backend/` on `sys.path` themselves, so
`python app/backend/devtools/<tool>.py` runs from anywhere.

### 3.2 Blueprints (HTTP surface)

Each blueprint lives in the `routes/` package of the area that owns it. `app.py`
imports every blueprint object in one block and registers them in one fixed order; the
name passed to `Blueprint('name', ...)` is the endpoint prefix and did not change in the
2026-10-03 move. Blueprints are flat (each route spells out its full `/api/mex/...` path)
except the Tracker ones (`nucleome_bp`, `combo_video_bp`) and `assistant_bp`,
which set a `url_prefix`. Route counts are URL rules in a dev build with every gate on
(513 in all on 2026-11-04, one of them Flask's `/static`).

**Access.** Every request must carry a loopback `Host` (`127.0.0.1`, `localhost` or `[::1]`,
any port), checked before any route, so a DNS-rebinding page gets a 403. `/api/*` needs the
per-launch backend token (`X-Nucleus-Token`, or `?_nucleus_token=` on GET/HEAD) apart from
three Tracker icon prefixes. The file routes outside `/api` (`/storage`, `/vanilla`,
`/utility`, `/assets`, `/static`) serve media (images, audio, mp4/webm) without the token,
because `<img src>` and `new Audio()` cannot send a header and the backend hands the UI bare
`/storage/...` URLs; any other file needs the token, and databases (`.db`, `.sqlite*`,
`-wal`/`-shm`/`-journal`) and key material are never served. Rules:
`shared/request_guard.py`; tests: `tests/backend/test_backend_request_guard.py`. The token and
any other secret query value (`*token`, `*key`, `*secret`, `sig`, `code`...) is blanked in every
log line as it is written (`core/log_redaction.SecretQueryFilter` on app.py's two handlers;
`tests/backend/test_log_redaction.py`).

**Vault** (`vault/routes/`). Eight blueprints serve both areas and are split by area on one
blueprint object: `custom_characters`, `custom_stages`, `das`, `codes`, `bundles`, `xdelta`,
`menus` and `extras`. The Vault module defines the blueprint (same name, same import name) and keeps
the library routes; the install half, `projects/routes/` under the same name, adds its routes
to that object, and the Vault module imports it at its bottom so the blueprint is complete
before anything registers it (Flask refuses routes added after registration). URLs, methods
and endpoint names did not change; shared non-route code lives in `vault/catalog/`,
`vault/importing/` or `projects/install/` rather than in a route module the other half
imports (the menus halves share the engine `vault/menus/` rather than each other's modules; the kinds' store
accessors). The counts below are each half's.

| Blueprint | File | Routes | URL root | Covers |
|---|---|---:|---|---|
| `storage_costumes_bp` | `storage_costumes/` | 23 | `/api/mex/storage/...` | Vault costumes, one module per purpose on the one blueprint: `library.py` (metadata, list, delete, rename), `csp.py` (portraits: upload, alternates, re-render, batch retake), `stock.py`, `slippi.py` (retest, override), `order.py` (ordering and folders), `animelee.py` |
| `storage_stages_bp` | `storage_stages.py` | 14 | `/api/mex/storage/stage...` | Vault stage entries |
| `custom_characters_bp` | `custom_characters/` | 42 | `/api/mex/custom-characters/...` | Wholly new m-ex fighters in the vault (largest blueprint): `__init__.py` (14: list, reorder, the m-ex content ISO scan `/api/mex/scan-iso/mex-content`, staged built-ins, detail, rename, delete, export), `skins.py` (11: added skins, bundled costumes, default CSP pose, special-fighter costumes), `audio.py` (7: victory theme, announcer, sound bank), `assets.py` (10: franchise/series, fighter.zip icon and banners, wall jump, team colors) |
| `custom_stages_bp` | `custom_stages.py` | 18 | `/api/mex/custom-stages` | Wholly new m-ex stages in the vault: list, icon/banner, playlist, assets, rename, export, folders |
| `das_bp` | `das.py` | 2 | `/api/mex/das/storage/variants`, `/scan-iso` | Stage skins (DAS variants) in the vault, and the ISO scan that imports them |
| `menus_bp` | `menus/` | 56 | `/api/mex/menus` | Menu mod library: CSS icon grids, backgrounds, doors, pause screen, percent font / HUD, sidebar counts. Everything that is not a route (store, importers, install engines, the "Currently in MEX" record, the file checks) is the engine `vault/menus/` |
| `extras_bp` | `extras/` | 15 | `/api/mex/storage/extras` | Per-character effect mods in the vault: color extras (`colors.py`: list, create, delete; the open-project half is `projects/routes/extras.py`), model swaps (`models.py`), hue-shift textures, raw texel recolor and region swap (`texture_routes.py`), the effect image PNG (`effect_model.py`). Engine: `vault/extras/` |
| `character_sounds_bp` | `character_sounds.py` | 11 | `/api/mex/storage/characters/<c>/sound-packs` | Voice/SFX banks |
| `codes_bp` | `codes.py` | 5 | `/api/mex/codes/vault/*` | Gecko code vault (catalog: `vault/catalog/codes.py`) |
| `bundles_bp` | `bundles.py` | 7 | `/api/mex/bundle` | `.ssbm` mod bundles in the vault: list, import, preview, edit, download, delete |
| `xdelta_bp` | `xdelta.py` | 6 | `/api/mex/xdelta` | Patches in the vault: list, import, edit, image, delete, download |
| `gaw_bp` | `gaw.py` | 2 | `/api/mex/gaw` | Game & Watch engine-side colors |
| `vault_backup_bp` | `vault_backup.py` | 6 | `/api/mex/storage/...` | Vault backup/restore/clear |
| `poses_bp` | `poses.py` | 9 | `/api/mex/storage/poses*` | CSP poses, batch pose CSPs |
| `import_bp` | `import_unified/` | 1 | `/api/mex/import/file` | The one import endpoint (`routes.py`); the engine is `vault/importing/unified/` (`detection.py` classifies, `archive.py` dispatches, the per-kind importers ingest) |
| `iso_scan_bp` | `iso_scan.py` | 8 | `/api/mex/iso-scan` | Background rip from ISOs (engine: `iso_scanner.py`) |
| `climbers_bp` | `climbers.py` | 4 | `/api/mex/climbers` | Ice Climbers pairs: candidates, preview, create (engine: `vault/climbers/`) |
| `stage_editor_bp` | `stage_editor.py` | 2 | `/api/mex/stage-editor` | Stage Creator copy sources and saves |

**Projects** (`projects/routes/`)

| Blueprint | File | Routes | URL root | Covers |
|---|---|---:|---|---|
| `project_bp` | `project.py` | 16 | `/api/mex/project*` | Open/create m-ex project, fighter list, status |
| `costumes_bp` | `costumes.py` | 8 | `/api/mex/...` | Install / replace vanilla / remove / reorder costumes **in the open project** |
| `export_bp` | `export.py` | 3 | `/api/mex/export` | Build ISO via MexCLI (start, save, download); progress and outcome are the `iso_export` job's record; the job itself is the engine `projects/install/export_job.py` |
| `mod_export_bp` | `mod_export.py` | 3 | `/api/mex/...` | ZIP a single costume/stage |
| `stage_slots_bp` | `stage_slots.py` | 7 | `/api/mex/stages` | Stage catalog (from `core/stages.py`, the single stage registry) + one replace slot per non-tournament versus stage (install a vault skin over the root file / restore vanilla / wrap a skin as an ADDED custom stage), SSS icon+banner art. Skins are ordinary `storage/das/<folder>/` variants, so the vault side is shared with DAS |
| `music_playlists_bp` | `music_playlists.py` | 10 | `/api/mex/...` | Weighted stage/menu playlists and shared-track loop editing |
| `test_in_game_bp` | `test_in_game.py` | 14 | `/api/mex/test-in-game` | HTTP shell over `shared/ingame/`: the one-Dolphin session state and every route that claims it (its inputs are in `projects/install/test_inputs.py`) |
| `custom_characters_bp` (Vault's) | `custom_characters.py` | 4 | `/api/mex/custom-characters/install*`, `/remove-from-project` | Install a custom character (one, or a batch in one `add-fighters` save) with its series, victory theme and announcer; install one of its skins; remove a fighter |
| `custom_stages_bp` (Vault's) | `custom_stages.py` | 5 | `/api/mex/custom-stages/in-project`, `/install*`, `/remove-*` | Custom stages in the open project: list, install (one or batch), remove (one or batch) |
| `das_bp` (Vault's) | `das.py` | 9 | `/api/mex/das/*` | DAS framework status and install, the six DAS stages, the variants installed in the project (import, rename, remove, restore vanilla), Stadium transformation freeze |
| `menus_bp` (Vault's) | `menus/` | 21 | `/api/mex/menus/*`, `/api/mex/builds/changes/*` | Install each menu kind into the project and restore vanilla (`icons.py`, `backgrounds.py`, `doors.py`, `pause.py`, `percent.py`; the pause and HUD write engines are `vault/menus/pause_install.py` and `percent_install.py`), the "Currently in MEX" record and file checks (`installed.py`), the CSS and SSS layout editors (`layout.py`, `sss.py`), the build-change approval card (`build_changes.py`) |
| `codes_bp` (Vault's) | `codes.py` | 4 | `/api/mex/codes/project*`, `/codes/dolphin`, `/codes/nucleus` | The open project's codes, sync through `mexcli sync-codes`, what Slippi Dolphin applies at runtime, Nucleus's own codes for any build |
| `bundles_bp` (Vault's) | `bundles.py` | 3 | `/api/mex/bundle/export`, `/install/*`, `/play/*` | Export a build as a bundle, install a stored bundle into Slippi, play one; each is a job (`bundle_export`, `bundle_install`, `bundle_play`) |
| `xdelta_bp` (Vault's) | `xdelta.py` | 4 | `/api/mex/xdelta/build/*`, `/play/*`, `/download/<job_id>`, `/create` | Build an ISO from a patch, play it, download the built ISO, create a patch from a modded ISO; each is a job (`xdelta_build`, `patch_play`, `xdelta_create`) |
| `extras_bp` (Vault's) | `extras.py` | 3 | `/api/mex/storage/extras/current/*`, `/install`, `/restore-vanilla` | Extras in the open project: read colors or image/afterimage model identity, install a stored extra, restore vanilla shape and colors (engine: `vault/extras/`) |

**Upload** (`upload/routes/`)

| Blueprint | File | Routes | URL root | Covers |
|---|---|---:|---|---|
| `publish_bp` | `publish.py` | 1 | `/api/mex/publish` | Push a package to ssbmnucleus.net |

**Tracker** (`tracker/routes/`). `nucleome_bp` is one blueprint object defined in `nucleome.py`
with its `NUCLEUS_NUCLEOME` before-request gate, the `NUCLEUS_VAULT` route decorator and the request
helpers several modules share; each feature module adds its routes to it, and `nucleome.py` imports
them all at its bottom. The Randall coach's eight `/coach/*` routes are on the same blueprint (same
URLs, `nucleome.coach_*` endpoint names, Tracker gate first) but live in `randall/routes/coach.py`,
which `app.py` imports before registering `nucleome_bp`.

| Blueprint | File | Routes | URL root | Covers |
|---|---|---:|---|---|
| `nucleome_bp` | `nucleome.py` | 0 | `/api/nucleome` (url_prefix) | The blueprint, its gates, shared request helpers; imports the modules below |
| | `replays.py` | 10 | `/identity*`, `/replays*` | Identity (connect codes), scan, the replay list and month buckets, final stocks, open/reveal a replay |
| | `stats.py` | 5 | `/stats`, `/deep/*` | Stats page: metadata stats, deep-stats mining and packs, baseline rank mapping |
| | `combos.py` | 3 | `/combos*` | Combo scan, status and browser |
| | `lite.py` | 3 | `/lite/*` | Lite clips (by frames, by clip ref) and charmaps; starts the anim-zip fetch at import |
| | `watch.py` | 12 | `/watch-mods/*` | Watch with mods: options, single and playlist starts (a `replay_watch` job), stop, playback window, recordings |
| | `icons.py` | 4 | `/stage-icon/*`, `/stock/*`, `/sprites*` | Stage and stock icons, ISO-derived sprites (public media in `app.py`) |
| | `ranks.py` | 2 | `/ranks`, `/rank-history` | Slippi ranks for connect codes, the player's rank history |
| | `cloud.py` | 8 | `/vault/*` | The cloud vault behind Nucleus on your phone: status, activity, token, settings, pairing, devices, sync |
| | `share.py` | 2 | `/share`, `/share/thumb` | Public replay and combo links (uploads that one game on demand), unfurl thumbnail |
| `combo_video_bp` | `combo_video.py` | 18 | `/api/nucleome/combo-video` (url_prefix) | Songs, timelines, exports |

**Randall** (`randall/routes/`)

| Blueprint | File | Routes | URL root | Covers |
|---|---|---:|---|---|
| `assistant_bp` | `assistant_bp.py` | 25 | `/api/assistant` (url_prefix) | Nucleus chat, history, approvals/file review, direct downloads, account likes, cancellation, attached/generated files, preview artifacts, undo and chat-owned in-game sessions; runtime in `backend/randall/assistant/` and the pipeline packages beside it (`recolor/`, `model_import/chat/`, `website/`, `delivery/`) |
| `chat_reports_bp` | `chat_reports.py` | 2 | `/api/mex/chat-reports/*` | "Report this chat" (mods + tracker Randall): freeze a scrubbed report, then send exactly those bytes through the bug-report worker (`kind: "chat"`); logic in `backend/randall/reports/chat_report.py`, see [RANDALL.md](RANDALL.md#11-report-this-chat) |
| `wishes_bp` | `wishes.py` | 5 | `/api/mex/wishes` | Wishes and capability gaps: list, submit, decline, `capability_status` (logic in `randall/reports/wishes.py`, the public wish API, and its `wish_*` modules) |
| `nucleome_bp` (Tracker's) | `coach.py` | 8 | `/api/nucleome/coach/*` | The Tracker coach (Analyst tab): saved chats, profile, status, the streamed turn (SSE); `NUCLEUS_RANDALL` gate on every route, engine in `randall/coach/` |

**Shared** (`shared/routes/`)

| Blueprint | File | Routes | URL root | Covers |
|---|---|---:|---|---|
| `setup_bp` | `setup.py` | 7 | `/api/mex/setup*` | First-run flow + health |
| `assets_bp` | `assets.py` | 5 | `/vanilla`, `/storage`, `/utility`, `/assets` | Static serving of `/vanilla`, `/storage`, `/utility`, `/assets` |
| `legal_bp` | `legal.py` | 1 | `/api/legal/notices` | Third-party notices for Settings > Credits & Licenses |
| `viewer_bp` | `viewer.py` | 5 | `/api/viewer*` | The files the frontend-launched HSDRawViewer opens (`/viewer/paths*`) and the vanilla costume list |
| `slippi_bp` | `slippi.py` | 6 | `/api/...` | Slippi/Dolphin paths, texture packs |
| `account_bp` | `account.py` | 3 | `/api/account/discord*` | The Discord sign-in the backend holds (engine: `shared/account/`) |
| `mcp_bp` | `mcp.py` | 3 | `/api/mcp`, `/api/mcp/account` | The MCP server for the user's own AI, and the window's Patreon token for its AI calls (memory only); the tools are `randall/mcp/` behind the `assistant` gate ([APP_MCP.md](APP_MCP.md)) |

Endpoint-level detail lives in [API_REFERENCE.md](API_REFERENCE.md).

### 3.3 The word "vault" means three things

| | Where | What |
|---|---|---|
| **Local vault (JSON)** | `storage/metadata.json` via `core/metadata.py` (`load_metadata` / `save_metadata` / `metadata_transaction`) | The mod library index. Dev default. |
| **Local vault (SQLite)** | `storage/vault.db` via `core/vault/`; `NUCLEUS_VAULT_DB=1` (packaged default), dual-writes JSON as rollback | Same data; `core/metadata.py` dispatches. [VAULT_SQLITE_MIGRATION.md](VAULT_SQLITE_MIGRATION.md) |
| **Cloud vault** | `tracker/cloud/vault_{client,sync,jobs,pair,assets}.py`, routes `tracker/routes/cloud.py` | Tracker feature: pair a phone by QR, push derived replay data to Supabase/R2. Unrelated to the two above. Gated by `NUCLEUS_VAULT`. |

`vault/routes/vault_backup.py` backs up the **local** vault. The top-level `vault/` package is the
Vault area's code (routes, importing, Ice Climbers, Echo); the local vault's storage layer stays in
`core/` (`core/metadata.py`, `core/vault/`).

Local catalog mutations use `metadata_transaction()` or the short-route
`metadata_write_transaction` adapter. JSON publication uses unique sibling files,
flush/fsync, and atomic replacement; existing unreadable JSON raises instead of
becoming an empty library. SQLite blob assembly starts one read snapshot.
`core/atomic_archive.py` separately serializes and validates ZIP rewrites before
replacement. These boundaries do not make asset bytes plus multiple catalogs one
transaction; expensive legacy writers still need coordination.

A Vault restore is a `vault_restore` job (`core/jobs.py`), so its record lives
in `output/jobs/<UUID>.json`, outside the replaced Vault. The job owns the
upload, the staging tree and, between the two renames of a replace, the
moved-aside Vault; a restore Nucleus died in is cleaned up at the next start,
which puts that Vault back if no new one went live. First-run setup is a
`first_run_setup` job that owns its temporary project (the extracted ISO) the
same way. Every in-game test and capture is the one `ingame` job (`single`),
which owns each Dolphin it launched by pid and executable; one still running
when the job ends or after a crash is closed, and only if that pid is still that
executable. Clients follow job records and never repeat destructive work after a
missed event or backend interruption.

A Watch with mods (one replay or a playlist, watched or recorded) is a
`replay_watch` job (`tracker/replays/watch_mods.py`), one at a time, its step
in `extra.phase`. It owns the playback Dolphin it launched (pid, start time,
exe) and each playback setting it changes, recorded before the change with the
value it replaced: the frame/audio dump flags in `Dolphin.ini` (put back to
off), `AspectRatio` in `GFX.ini`, and the GameSettings override files (a
user's own file comes back byte for byte). The job's end puts them back, and so
does the next start after a crash; that start kills a Dolphin still matching
the owned identity rather than closing it, because a clean exit writes Dolphin's
settings back over the restored ones. Stop names the job
(`POST /watch-mods/stop {job_id}`), so an old popup cannot stop a newer watch,
and a watch is refused while a Combo Video final render holds Dolphin. The two
popups read the newest watch from the job store (`useWatchJob` in
`WatchPlayback.jsx`, the pure part in `tracker/replays/watchJob.js`) and are
busy from the Start click on.

The Tracker's library passes are jobs too, one at a time per kind: the replay
scan (`replay_scan`, `tracker/store/indexer.py`), the combo pass (`combo_scan`,
`tracker/combos/combo_index.py`) and deep stats (`deep_stats`,
`tracker/stats/deep_stats.py`). Each opens its database inside the job, so a
failure of any kind ends it `failed` with the error. Their counters ride in
`extra` at most twice a second (`tracker/store/pass_progress.py`) and the final
ones are the result. They own nothing and the cloud loop starts the first two
every ten minutes, so they are registered with `keep=5`: memory only. Replays,
Combos, the Stats panel, the coach's card and the Cloud card read them from the
job store (`useLatestJob` / `useJobEnd`, the pure part in
`shared/jobs/passView.js`); a screen reloads its list when a pass that changed
something ends.

The cloud's two pieces of background work are jobs as well, also `keep=5`
(`tracker/cloud/vault_jobs.py`). `cloud_sync` is one push (`params.mode`
`upload`) or the raw chain's metadata follow-up (`metadata`); each record keeps
its own result (`pushed`/`skipped`/`failed`, or `committed`/`conversions`/
`failed`), so a follow-up never hides the upload's failures, and a sync that
ends with failures says `N failed` in its detail. `extra` carries `stage`
(`reconcile`, `upload`, `combos`, `conversions`), `done`/`total` and
`progress_at`, from which the Cloud card tells a stalled sync. The sync opens
its database inside the job and refuses to start, without clearing anything,
when the stored token is no longer the one it was asked with. `cloud_autorun` is
the index -> combos -> upload -> wire-basis refresh chain (`extra.phase`); it is
one job, so one chain runs at a time, and the open-app loop runs it inline
(`jobs.run_inline`). Each pass it waits on must end `done`: a pass still running
at the six-hour wait limit fails the chain, and the frames upload waits for a
combo pass that ended `done`. The wire-basis repair is only marked done when
`refresh_meta` reports `complete`. The Cloud card (`VaultSection.jsx`, the pure
part in `tracker/cloud/cloudJobs.js`) follows both from the job store; it
refetches `/vault/status` when a pass ends and as a sync moves, and does not
poll.

Cloud credentials have a generation separate from content hashes. An exact token
change invalidates account-derived sync/checkpoint state and cancels subsequent
requests. Mobile cache envelopes use a random credential generation to prevent
old-account display or mixed-page publication. Same-account token rotation causes
safe refetch/reconciliation; this is not a stable account-identity mapping.

### 3.4 External tools — how Flask reaches them

| Tool | Path constant (`core/config.py`) | Invocation style |
|---|---|---|
| MexCLI (C#) | `MEXCLI_PATH` | `mexcli/`: `mexcli.commands.run` / `run_json` for one-shot commands (the workspace-saving ones take the build lock), `mexcli.project.MexManager` for the open workspace and ISO export; a few modules still spawn it directly (`core/build_transaction.py`, `projects/install/texture_filename_table.py`, `projects/routes/codes.py`); every workspace-mutating call wrapped in `mexcli_lock` |
| HSDRawViewer (C#) | `HSDRAW_EXE` | One-shot `--csp`/`--model`/etc. calls in ~19 modules; structured clients only in `shared/rendering/session.py` (`--stream` WebSocket) and `shared/rendering/csp_pool.py` (`--csp-server` pool) |
| xdelta3 | `utility/xdelta*` | subprocess |
| Slippi Dolphin | user path from `slippi_bp` | `shared/ingame/boot.py` (isolated User dir); `dolphin_lock.py` enforces ONE Dolphin machine-wide |

`core/config.py` is the single source of every path and branches on
`sys.frozen` × platform. `core/state.py` holds module-level singletons
(`_mex_manager`, `_current_project_path`, `_socketio`).

The open project is checked before it is published: `/project/open` runs
recovery and has MexCLI read the project under `mexcli_lock`, then calls
`set_project_path(path, manager=...)`. A failed, quarantined or busy open leaves
the previous project open. Every open, close and delete bumps a generation.
Each request is pinned to the project that was open when it began
(`pin_request_project`), so `get_current_project_path()`, `get_mex_manager()`
and `get_project_files_dir()` answer the same project for its whole run. The
window sends the generation it is showing as `X-Nucleus-Project`
(`frontend/src/shared/transport/projectGeneration.js`); a request whose header
no longer matches answers 409 `project_changed` as soon as it touches the
project, whatever the route reports itself. Status, open, close, delete and list
are `@project_check_exempt`. A manager built for a project that was switched
away meanwhile is never cached. `mexcli.commands.run_json` locks the project its
command names, not the open one.

Costume reorder queues capture the workspace generation when their hook mounts
and send that generation explicitly with every batch. A delayed batch keeps its
original project even after the workspace unmounts during a switch; the backend
rejects it with `project_changed` instead of editing the newly open project.
Switch Project and Close Project wait for pending order saves to settle.

CSP pools reserve worker slots immediately and start a native process only when
its first job arrives. Ready workers render while other workers initialize;
an idle warm worker is reused before an unused slot. Native starts and one-shot
fallbacks share the launch stagger, while warm renders bypass it. ISO scans
default to at most four workers, bounded by logical CPU count and candidate
count; `MEX_CSP_PARALLELISM` overrides the CPU/default limit. Other CSP batches
retain the shared default limit of sixteen. Startup/job deadlines, blank-output
checks and one-shot fallback remain in place; Fox gun renders still use a fresh
process. Pools with no render jobs start no native processes.

### 3.5 Real-time

Flask-SocketIO uses threading mode and `manage_session=False`: Flask owns its
session, and socket authentication uses the backend token in one connect handler.
This avoids the managed-session copy assigning the pinned Flask version's
read-only request-context session property. Background jobs share one `job`
event (below); other events are ad hoc per feature: `test_progress|complete|error`
(interactive in-game sessions). The frontend holds ONE connection
(`shared/transport/socket.js`); consumers attach handlers through `channel()` /
`subscribe()`.

Background jobs go through `core/jobs.py` (`jobs.start(kind, fn, ...)`) as they
move off their own status dicts. A job has one status (`queued`, `running`,
then `done` | `failed` | `cancelled` | `interrupted`), and the `finally` always
writes a final one. Every change emits one `job` event with the whole record and
a `seq`. The record is also written to `output/jobs/<id>.json` on status changes
and on `job.own()` / `job.release()`. A kind registers `cleanup(name, value)`,
and a kind whose work blocks where it cannot check its stop (it waits on a
Dolphin) also registers `on_cancel(job)`: `cancel` calls it after setting the
stop, and it closes what the work waits on (`replay_watch` its playback Dolphin,
`ingame` an automated test's Dolphin or an interactive session's stop event).
Because the hook breaks the work on purpose, a job of such a kind that fails
after its Cancel ends `cancelled`. In-game jobs also hand `job.stop_event` to the
Dolphin boot (`shared/ingame`), so a test queued behind the Dolphin lock, or
still booting, stops without waiting out a timeout.
Whatever a job still owns when it ends is cleaned up then, before its final
status goes out, so a `single` kind stays busy until that is done. Whatever it owned
when the process died is cleaned up at the next start by
`recover_interrupted()` (in `app.py __main__`, not in worker children), which
marks the job `interrupted`. Owned items are undone newest first (owning a
name again makes it the newest), so a render's Dolphin is closed before the
throwaway ISO it holds open is deleted. Records name their owner (pid + start
time), so a second live backend's jobs are left alone. `critical=True` holds shutdown
through `critical_ops`; `single=True` refuses a second job of the kind
(`JobBusy`). A thread that cannot start fails its job at once, so a `single`
kind never stays busy behind it. A kind registered with `keep=N` (one that runs
often and owns nothing, like the scans the cloud loop starts every ten minutes)
never touches disk and remembers only its newest N ended jobs, so a death leaves
nothing to recover. The window keeps one store (`frontend/src/shared/jobs/`): it upserts
`job` events by `seq`, resyncs from `GET /api/jobs` on every (re)connect (a
running job of a dead backend process that the new list leaves out ends there as
`interrupted`, quietly), keeps
the newest 20 ended records per kind, and screens read it through `useJob(id)` /
`useActiveJob(kind)` / `useLatestJob(kind)`;
`jobOutcome(job)` turns an ended record into `{ ok, result | error }`.
`InterruptedJobsNotice` (App.jsx) tells the user once about an interrupted job
and its cleanup notes, then posts `/seen`.

Kinds so far: `texture_matching` (owns Dolphin dump settings and partial copies);
`stage_render` (owns extraction and previews; Stop keeps completed previews);
`csp_retake` (owns extraction and previews; records carry PNG links);
`builtin_character` (critical; owns temporary recolors); `iso_scan` (owns extraction and preview files until success; completed
candidates stay for import until dismissal); `vault_restore`; `iso_export` (critical), `texture_pack`;
`xdelta_build`, `xdelta_create`, `patch_play`; `bundle_export`,
`bundle_install`, `bundle_play`; `replay_watch`; `combo_video_render` (gated:
owns the recorder settings it changes in the playback Dolphin, the Dolphin it
runs and its throwaway cosmetic ISO and project); `first_run_setup`; `ingame`;
and, kept in memory (`keep=5`), `replay_scan`, `combo_scan`, `deep_stats`,
`cloud_sync`, `cloud_autorun`. The helper processes a job runs (xdelta3, the
MexCLI export and setup's ISO extraction, the headless build worker) are tied
to the backend by `core/child_procs.py`, so a crash cannot leave one writing files the
next start has already recovered. A job writes only files named by its own id
and owns its temporary folders and partial files, so a failed, cancelled or
interrupted job leaves none behind and one attempt's result is never another's.
The Export screen's pipeline (`projects/export/exportPipeline.js`) follows each
step's job by id and starts the next step from its result.

### 3.6 Layering rules

Enforced by convention and review (the one test-checked rule is marked). New code follows them; the
exceptions are listed so nobody copies them.

1. **Route modules import engines, never other route modules.** A route module is anything under a
   `routes/` package. Shared logic lives in an engine package (`vault/catalog/`, `vault/importing/`,
   `vault/menus/`, `projects/install/`, `shared/...`) that both route modules import. Deliberate
   exceptions: (a) blueprint-sharing halves: `projects/routes/*` import the Vault's blueprint object
   from `vault/routes/*` and add their routes to it, the Vault module imports its install half at its
   bottom; `randall/routes/coach.py` and the feature modules of `tracker/routes/` import
   `nucleome_bp` (and the helpers defined beside it) from `tracker/routes/nucleome.py`; (b) the
   assistant's in-process handler calls in `randall/delivery/game_tests.py`, which run the Test in
   Game handlers of `projects/routes/test_in_game.py` directly. There are no other route-to-route
   imports (the last ones moved out 2026-10-03: the cloud-token helpers into `tracker/routes/nucleome.py`,
   the report transport into `shared/diagnostics/bug_report.py` and `randall/reports/report_transport.py`,
   the export job into `projects/install/export_job.py`). Check with
   `git grep -n -E "(from|import) (vault|projects|upload|shared|tracker|randall)\.routes" -- app/backend`:
   only `app.py`'s blueprint registry and the two exceptions above should match.
2. **`mexcli/project.py` and `file_retry/` never import `core`** (`mexcli/project.py`: checked by
   `tests/backend/test_backend_layout.py`, because `core.state` imports it while `core` is still
   initialising). `mexcli/commands.py` may import `core`. The two `storage_*.py` bootstrap files
   import neither `core` nor the app.
3. **`app.py` registers blueprints and nothing else**; it never imports `nucleus_api/`, and no
   package imports `app`. `devtools/` is not part of the app: its only imports are lazy imports of
   `devtools.frameshot` (`nucleus_api/game.py`, `shared/ingame/verify_costume.py`).
4. **`__init__.py` files hold no logic** except where a package re-exports the names of the module it
   replaced, a route
   package assembles its blueprint (`vault/routes/custom_characters/` also holds routes), or the
   package is a single store (`core/vault/`, `file_retry/`).
5. **If it is not in the installer it is not in `app/`.** Dev-only tools, tests, benchmarks and
   experiments live in the repo-root `tools/`, `tests/`, `eval/` and the private side repos; `app/`
   holds only what the installer ships (plus `app/scratch/`, which is gitignored, and the developer READMEs
   beside the code, which the spec keeps out of the bundle). Vendored
   dependencies (the MexManager fork, HSDLib, the AI runtime) live in `app/utility/`.
6. **Randall's pipeline packages never import the turn loop.** `randall/assistant/` registers the tools of
   `recolor/`, `model_import/chat/`, `website/` and `delivery/` and reads `reports/`; those packages import the
   helpers in `assistant/` (`mod_files`, `vault_items`, `approvals`, `tasks/`, ...) but never `engine.py`.
   Check with `git grep -n -E "from randall\.assistant import .*engine|randall\.assistant\.engine" -- app/backend/randall`:
   only `randall/routes/assistant_bp.py` should match.

---

## 4. Frontend (`frontend/`, ~70k lines JSX + 32k lines CSS)

Vite 7 + React 19, plain JS (no TypeScript). **No router, no state library,
no HTTP client library.** `vite.config.js` proxies `/api`, `/storage`,
`/vanilla` to Flask in dev and writes `.vite-port` for Electron.

### 4.1 Shell and navigation

`frontend/src/App.jsx` owns: app mode (`nucleus` | `nucleome`, persisted in
`localStorage`, themed via `<html data-mode>`), active tab (plain state, all
panels stay mounted and are hidden with `.app-panel--hidden`), vault
`metadata` + `onRefresh`, setup gate, download queue.

Paths below are relative to `frontend/src/`. Every tab is its own lazy chunk
(`React.lazy` in `App.jsx`; the Tracker pages are lazy inside `NucleomeApp.jsx`).
Tab ids stay `upload` / `storage` / `mex` / `settings` and mode ids `nucleus` /
`nucleome`: they are sent to Randall as page context and persisted, so the folder
names (`vault/`, `projects/`, `tracker/`) are not ids.

| Mode | Tab | Component |
|---|---|---|
| nucleus | Upload (account-locked) | `upload/UploadPage.jsx` |
| nucleus | **Vault** | `vault/StorageViewer.jsx` → `vault/ModeToolbar` → Characters / Stages / Menus / Patches grids + detail views + ~35 editor modals |
| nucleus | Vault ISO import | `vault/import/VaultImportSurface` → `IsoScanModal`; `IsoScanProgress` / `isoScanProgressModel` for the square shine loader, `isoScanMonitor` for socket/poll recovery, `IsoScanResults` for candidates and saved vault previews |
| nucleus | **Install** (Projects) | `projects/MexPanel.jsx` → `projects/ProjectSelector`, `projects/CharacterMode` + `projects/characters/*`, `projects/StageMode` + `projects/stages/*`, `projects/MenuMode` + `projects/menus/*` |
| nucleus | Settings | `settings/Settings.jsx` → ~19 `settings/*Section.jsx` cards |
| nucleome | Analyst (gated) | `randall/coach/CoachPage.jsx` |
| nucleome | Tournaments / Stats / Replays / Combos | `tracker/{tournaments,stats,replays,combos}/*Page.jsx` |
| nucleome | Latest-request cancellation; first-page data before secondary metadata; deferred playback dialogs | `tracker/lib/latestRequest.js`, `tracker/combos/comboPageRequest.js`, `tracker/combos/CombosPage.jsx` |
| nucleome | Combo Video (gated) | `tracker/video/*` |
| nucleome | Settings | same `settings/Settings.jsx`, plus the Cloud category from `tracker/cloud/` (`VaultSection.jsx`, `CloudActivitySection.jsx`, `MobileSetupGuide.jsx`) |

`src/` holds the shell (`App.jsx`, `App.css`, `main.jsx`, `index.css`) and one folder per
product area; there are no `components/`, `hooks/`, `services/`, `utils/` or `config/` folders
(dissolved 2026-10-03 into their owners). First-run setup is `setup/FirstRunSetup.jsx`; the
export flow is `projects/export/IsoBuilder.jsx`; the skin and stage editor is
`vault/editors/SkinCreator.jsx` beside its hooks (it composes `useViewerPose`, the
viewer-protocol handler `skinCreatorViewerMessages.js`, `skinCreatorLaunch.js`,
`skinCreatorSave.js`, `textureFileActions.js`, `useTextureCanvasLoad` and the
`PreviewPanel` / `TextureViewBar` / `ColorToolsPanel` panels); the 3D viewer host is
`shared/viewer/EmbeddedModelViewer.jsx` (`shared/viewer/viewerPair.js` resolves paired-preview
startup and acknowledgements); the dev premium override is `settings/DebugTierToggle.jsx`.

### 4.2 Directory map

Cloud vault Settings includes `tracker/cloud/MobileSetupGuide.jsx`, a local disclosure
available before account configuration. Opening it only displays setup and upload
guidance; it does not create pairing credentials or start synchronization.

Combos keeps the header mounted through library loading and scan-state changes.
`ComboLoading.jsx` reserves the same controls before the lazy page module loads;
`ComboLibraryStatus.jsx` displays loading, analysis, empty and retry states in one
row. Identity/facet controls enable as metadata arrives after the first page.
The shared `ShareLinkButton` accepts a disabled reason for short sequences.
The share endpoint validates combo membership and the existing four-move
publishing rule before invoking any upload.

Stats uses `tracker/lib/latestRequest.js` to abort and fence obsolete filter requests.
Settings groups the existing mounted cards behind a vertical category tablist;
changing categories preserves card state. General includes help and updates;
Files & setup includes Account and setup; the Patreon deep link targets
`setup`. AI (`ai`, builds with the assistant) holds McpSection, ModelImportToolsSection and
CreationToolkitSection. Nucleus includes Storage & backups
(including HD portraits); Tracker has separate Cloud and Storage categories.
Cards use responsive column flow at their natural heights rather than shared
grid rows, retaining their DOM/focus order without resize-driven remounts.

Per-mod Test in Game uses `useInGameTest` and `inGameSession` for UUID-scoped
progress, Stop, and status recovery. The blueprint serializes jobs and retains
bounded terminal snapshots. `shared/ingame/interactive.py` preserves controller port 1,
uses port 4 only for menu automation, and leaves the solo match open until Stop.
Automated screenshot and frame-exact workflows do not opt into this mode.

Tracker owns `.stats-grid`; Settings storage tiles use `.storage-stats-grid`.
These selectors must remain distinct because lazy stylesheet order changes
after navigation, and storage auto-fit columns are too narrow for charts.
`StatsLoading.jsx` supplies the initial and lazy-module shell; subsequent updates
retain the previous summary with an updating/error indicator. The first stats
response precedes character facets and rating-history requests, and the detailed
stats panel is lazy-loaded. Backend `tracker/stats/aggregate.py` parses final-state
JSON only when the common result rules need it and reuses per-game results and
timestamps across aggregates; the response and eligibility rules are unchanged.

Tourneys keys its page state by start.gg slug. `tournamentLoading.js` publishes
cached data and each history page independently of profile/standings completion,
and fences callbacks after refresh, account change or unmount. `tracker/tournaments/startgg.js`
deduplicates history syncs by slug and checkpoints each page without marking a
partial sync complete. The existing page limit and request pacing still apply.
Bracket and replay-player modules load on demand; replay-index status polling
starts after history is available and stops on cleanup. Bracket requests are
also fenced when the selected event changes.

Interactive Test in Game routes share a preflight that reserves the test slot
and checks for an existing Dolphin before starting any test ISO build. Conflicts
release the slot and return HTTP 409 (`code: dolphin_open`). The engine's later
wait still covers Dolphin opening during a build. The shared `InGameTestPanel`
shows the waiting explanation without an empty embed or percentage; background
screenshot jobs retain their own existing wait policies.

`shared/ingame/boot_errors.py` recognizes graphics-failure dialogs only from the retained
live test process, using bounded Win32 reads. Boot and navigation waits surface
these failures promptly. `runner.py` keeps unsuccessful menu navigation from
passing on RAM health alone; the observation remains available as diagnostic data.

For Windows Test in Game, `electron/viewers/dolphin-capture.js` selects the retained
backend process's exact capture HWND and grants a main-frame media lease.
`shared/viewer/dolphinPreview.js` owns stream startup, first-frame readiness,
heartbeat and disposal; `DolphinEmbedPanel` renders contained video. Backend
`shared/ingame/embed.py` checks process/session/window identity before presentation.
Live video does not drive the controller pipe or frame-exact test timing.
Watch Mods keeps its separately owned legacy overlay controller.

Folders mirror the product: one top-level folder per area, and inside it one
folder per thing the user works with. A file used by one area lives in that area
even when another area imports it (Projects imports the Vault's pose manager, sound
packs and effect previews); only what several areas genuinely share is in
`shared/`. Frontend tests stay colocated as `*.test.js` (`npm test`; they need the
frontend's `node_modules`/esbuild). There are no barrel `index.js` files: import
the file itself, or a lazy chunk can be pulled into another.

| Dir | Files | Role |
|---|---:|---|
| `vault/` | 22 | The Vault (tab id `storage`). `StorageViewer.jsx` with the 350-line `StorageViewer.css` shell, `ModeToolbar`, `EditModal`, folder cards, `CspManagerModal`, `PlayOverlay`, sort control. `StorageViewer.jsx` imports the feature stylesheets in a fixed order (`VaultGrids.css`, `CustomDetailViews.css`, `stages/StageCards.css`, `characters/CharacterSkinCards.css`, `patches/PatchesGrid.css`, `extras/ExtrasPage.css`, `extras/ExtraEditorModal.css`, `FolderCards.css`, `menus/VaultMenusView.css`, …) |
| `vault/characters/` | 11 (+`custom/` 7, `poses/` 15) | Character grids and detail views, custom characters (`CustomCharacterDetailView` and its `custom/` parts: top bar, header, costumes and skins sections, team colours, base-skin and series pickers), G&W colours, Animelee detection, bulk CSP capture; `poses/` is the Pose Manager (`poseModalKeys.js`: its and Generate CSPs' Escape, innermost layer first; `poseSkinCards.js`: the Generate CSPs card's picture version) |
| `vault/stages/` | 8 | Stages home (`StagesGrid`, a 2×4 grid: six DAS stages, Custom Stages, More Stages → `MoreStagesGrid`, the 23 slot stages → their vault skins → `CustomStageDetailView`), stage detail, bulk capture |
| `vault/menus/` | 10 | The Vault's Menus page: `VaultMenusView`, the `menuKinds.js` registry, icon grids, pause and percent-font editors |
| `vault/patches/` | 9 | Patches grid: xdelta browse, import and edit, `.ssbm` bundles, `patchDownload.js`; `PatchModals` renders the import/edit/create dialogs from `useVaultPatches`; `PatchEditModal.css` is the edit modals' screenshot preview |
| `vault/sounds/` | 3 | Sound packs and the sound bank |
| `vault/extras/` | 36 (+`previews/` 11) | Effects (extras): page, cards, previews and every effect editor modal. `ExtraPreviews.jsx` is the card-preview dispatcher; the previews themselves are in `previews/` (bespoke-editor previews, asset previews, `DualColorPreview` and its `dualColor*.jsx` groups by character) |
| `vault/import/` | 25 | `useFileImport` (the one import pipeline), the drop-anywhere `VaultImportSurface` + `ImportFab`, ISO scan (`IsoScan*`, `isoScan*`), the duplicate/choice/Slippi-safety import dialogs, and the website download queue (`useDownloadQueue`, `DownloadModal`; both mounted by `App.jsx`) |
| `vault/editors/` | 49 | Skin Creator and Stage Creator (`SkinCreator.jsx` beside its canvas, palette, layer and undo hooks, the viewer protocol/launch/save modules and panels listed above). `SkinCreator.jsx` imports `SkinCreator.css` and then the sheets split out of its tail (`ViewerAnimPopover`, `areaSelection`, `ReferencePanel`, `TextureViewBar`, `LayersPanel`) in that fixed order |
| `vault/hooks/` | 22 | Vault state hooks: `useCspManager`, `useEditModal`, `useDragAndDrop` (reorder), `useFolderManagement`, `useXdeltaPatches/Progress`, `useVaultBundles`, `useVaultPlay`, `useInGameTest` + `inGameSession`, `useBulk*`. `StorageViewer.jsx` composes three groupings of them: `useVaultLists` (grid lists and fetchers), `useVaultPatches` (patches, bundles, progress socket) and `useVaultItemEditing` (edit modal, CSP manager, netplay safety) |
| `vault/editModalKeys.js`, `vault/vaultActive.js` | 2 | The edit modal's Escape (closes it as other modals do; the name field keeps it only to revert an unsaved name; an open dialog over it, its `covered` prop, answers it instead) and `VaultActiveContext` (App.jsx: the vault is on screen; the modal is portaled into `.app-content`, so it hides itself while another page shows). The Pose Manager and Generate CSPs read it too; App.jsx also provides it around the Install tab, which borrows the Pose Manager for apply-to-all |
| `vault/metadataRefresh.js`, `vault/costumeDisplayIdentity.js` | 2 | Latest-request catalog refresh and unique display identities for legacy duplicate costume rows; preserve raw reorder indices. `useEditModal` owns modal session generations so late deletion/preview responses cannot affect a newer selection |
| `vault/lib/` | 8 | Pure Vault helpers: `vaultSort`, `storageViewerUtils`, `customCharacter`, `imageDownload`, `rgbyColor`, `relativeRecolor` |
| `vault/picker/` | 5 | The fighter and costume picker (`CostumePicker.jsx` + its sheet): a fighter, then one of its vault costumes or stock colour slots (`GET /api/mex/vanilla/costumes/<fighter>`), or a fighter only. The Tracker's watch-with-mods grid (`shared/ui/GalleryGrid`) inline, with arrow-key navigation. `costumePicks.js` is the pure part (roster, options, pick shapes). Used by Randall's starting points (`randall/assistant/StartPicker.jsx`) |
| `projects/` | 21 | Install tab (tab id `mex`). `MexPanel.jsx` with the 665-line `MexPanel.css` shell (the rest is one stylesheet per feature, loaded in order from `MexPanel.jsx`), `ProjectSelector` (its saved-project records in `projectCatalog.js`), the three modes (`CharacterMode`, `StageMode`, `MenuMode`), music modals, `banner.js`, `playlistUpload.js` |
| `projects/characters/` | 21 | Character mode: fighter list, costumes panel, extras view, Zelda/Sheik, team colours, the install-side custom character hooks; `useCostumes` composes `useCostumeTeamColors` and `useCostumeReorder` |
| `projects/stages/` | 13 | Stage mode: the three Stages hooks (`useStageVariants` DAS, `useCustomStages`, `useStageSlots` replace-slot stages) + their panels (`VariantsPanel`, `CustomStagesPanel`, `SlotPanel` with `StageSlots.css`); `StageList` lists the six DAS stages, Custom Stages, then the 23 slot stages as rows |
| `projects/menus/` | 9 | The CSS/SSS layout editors opened from `MenuMode` (`CssLayoutEditor`, `SssLayoutEditor`, canvas, icon properties, `cssGridLayout.js`) |
| `projects/codes/` | 6 | Gecko codes manager and its paste modal |
| `projects/export/` | 8 | Export: `IsoBuilder`, `ExportHome` (with `ExportHome.css`; most of what `IsoBuilder.css` still holds styles screens the builder no longer renders), export reconciliation, the xdelta Build/Create modals |
| `upload/` | 6 | Upload tab: `UploadPage`, post preview, upload catalog, `publish.js` |
| `tracker/` | 3 | Tracker mode shell: `NucleomeApp.jsx` (lazy pages; the `import.meta.env.DEV` fold for Combo Video and the coach), `NucleomeTabs.jsx`, `nucleome.css` |
| `tracker/replays/` | 14 (+`data/` 1) | Replays page (`ReplayRow`, `MonthPager`) and playback: Watch Lite (`WatchLiteModal`, `WatchLiteClip`, renderer `litePaint.js` with the stage inference in `liteStageInference.js`, `meleeRender.js`, `meleeStages.js` with the baked `data/meleeMovers.json`, `meleeReadout.js`), the Watch/playlist mods modals (`WatchModsModal`, `PlaylistModsModal`, the shared `WatchPlayback` with `useWatchJob`; `watchJob.js` is the pure view of the `replay_watch` job) |
| `tracker/combos/`, `stats/`, `tournaments/` | 7, 12, 15 | One folder per page; `stats/` splits its widgets into tooltip, blocks, tables, charts and `RankChart`; `tournaments/` holds the run, set-detail and list sections plus `startgg.js` and `tournamentReplays.js` |
| `tracker/share/`, `video/`, `cloud/` | 3, 11, 4 | Share link and the first-share consent dialog (`ShareNoticeModal`); Combo Video (gated); the Tracker's Cloud settings category (`VaultSection`, `CloudActivitySection`, `MobileSetupGuide`) |
| `tracker/lib/`, `assets/ranks/` | 5, 20 | Helpers shared by Tracker pages (`latestRequest.js`, `LiteGate.jsx`, two modal sheets); rank icons (also copied by `services/mobile/build.py`) |
| `randall/` | 90 | Randall's UI: `assistant/` (the floating chat panel, cards, workbench; the empty chat's starting points: `TaskPicker` tiles, `StartPicker` + `startPick.js` for the costume/fighter pick and its message context), `coach/` (the Tracker AI tab: `CoachPage`, `coachAnswer`, `CoachIndicators`, `ProfileCard`; coach-only styles in `CoachPage.css` and `CoachIndicators.css`), `chat/` (chat UI and "report this chat" shared by both; `ChatUI.css` is the styling both surfaces share; `ChatSidebar` is the history in the Claude desktop layout, its search, date groups and paging in `chatList.js`) |
| `settings/` | 29 | One card per settings concern; `useUpdateStatus`. `AccountSection.css` (split from `Settings.css`) loads after it |
| `setup/` | 4 | First-run setup; `setupJob.js` picks the setup job the wizard shows and its step |
| `shared/` | 87 | Used by more than one area. `ui/` (dialogs, selects, pagers, loaders, icons, `GallerySelect` (the Tracker's picture-first skin/stage dropdown) over `GalleryGrid` (its thumbnail grid, also used inline by `vault/picker/`; each with its own sheet), `ProgressPanel`, `Sprites`, `appDialogs`, the header `BrandWordmark`/`BrandLogo`, and `buttons.css` / `modals.css`: the app-wide button system and modal chrome, imported by `App.jsx`), `viewer/` (`EmbeddedModelViewer`, `viewer*.js`, `DolphinEmbedPanel`, `dolphinPreview`, `InGameTestPanel`, `screenRect`), `audio/` (`sounds`, `audioConvert`, playlist and loop editors), `account/` (Supabase `account.js`, Patreon `entitlement.js`, `usePremium`), `transport/` (`api.js`, `socket.js`), `hooks/`, `lib/` (`EditorContext`, `errorRing`), `config/` (`config.js`, `features.js` release gates, `recordMode`), `data/` (`defaultCharacters`, the 2.9k-line `extraTypes.js`, `meleeNames`) |
| `index.css` / `App.css` | | Design tokens (`--color-*`, ~270 vars), reset and utilities; the app shell (container, header, tab bar, banners, panels, loading states, app-wide keyframes, `.context-menu`) |

### 4.3 Data flow conventions

- **Backend calls:** `shared/transport/api.js` is the one HTTP client —
  `api.get/post/put/delete/blob(path)`. Short paths resolve to `API_URL`
  (`/api/mex`), absolute `/api/...` paths to `BACKEND_URL`. A resolved promise
  means the call worked; network failures, non-2xx and the backend's
  `{success:false}` envelope all throw `ApiError` (`.status`, `.data`). Raw
  `fetch` survives only for streaming (coach SSE), blobs with
  `Content-Disposition`, data-URIs and external downloads.
- **Socket.IO:** `shared/transport/socket.js` owns the single connection;
  consumers use `channel()` (scoped `on/emit/disconnect`) or `subscribe({...})`.
- **State:** `useState` + prop drilling from `App.jsx`; shared hooks; 
  `localStorage` for cross-session flags; one React context (`TipCtx` in
  `tracker/stats/StatsTooltip.jsx`). Window events `nucleus:open-settings`,
  `nucleus:entitlement-changed` as a tiny bus.
- **Electron IPC:** `window.electron.*` (~45 call sites) for dialogs, updater,
  `openExternal`, and the `viewer*` family driving HSDRawViewer.
- **Styling:** global CSS, BEM-ish names, `var(--color-*)` everywhere. Two
  shapes: a component imports its own stylesheet, or — for the Vault and
  Install tabs — the host (`StorageViewer.jsx`, `MexPanel.jsx`; likewise `SkinCreator.jsx`
  for its split sheets) imports a
  shell stylesheet followed by the feature stylesheets **in a fixed order**;
  that order is what keeps the cascade identical to the old monoliths, so
  don't move those imports without re-running the split proof. The same holds
  for `App.jsx` (`App.css`, then `shared/ui/buttons.css` and `shared/ui/modals.css`). The
  2026-10-03 split of `FriendsPage.css` (removed with Friends in 0.8.16), `App.css`, `IsoBuilder.css` and `ChatUI.css` into
  per-component sheets was checked pair by pair on the built CSS, lazy chunk load order
  included; two rules stay beside the rule they must keep their order with (`.brand-toggle h1`
  after `.app-header h1` in `App.css`, `.coach-split-col .coach-turn` before `.shared-chat .coach-turn` in `ChatUI.css`).
  Everything is
  global: the same class in two files shadows by load order (`.shared-note`
  is defined in `vault/extras/ExtraEditorModal.css` and `projects/MexPanel.css`; the latter
  loads last and wins). 8 Vault modals inject `<style>` strings instead
  (largest: `vault/characters/poses/poseManagerStyles.js`).

---

## 5. Electron (`electron/`)

| Path | Role |
|---|---|
| `main.js` | Composition only (about 300 lines): the per-launch secrets (backend token, UI approval key), the packaged-build gate environment `backendEnvironment()` (§7), the shared `ctx` object, the app lifecycle (storage preparation → backend → window; quit), creating the modules below and registering their IPC |
| `preload.js` | Self-contained sandbox preload; `contextBridge` → `window.electron`, including backend port/token. Local CommonJS imports are unsupported, and it stays at this path (`main.js`, `build.bat` and the `tools/ingame` smokes load it by path); test the complete preload with `tests/electron/preload.test.js` and `tools/ingame/preload-smoke.cjs`. |
| `runtime/backend.js` | The Flask child: spawn with the gate environment, `BACKEND_PORT` handshake (60 s), 80-line output buffer for `backend-diagnostics`, startup-failure dialog, `backend:exited` when it dies after startup, graceful then forced shutdown on quit |
| `runtime/backend-launch.js` | Resolve the same backend executable for normal startup and offline maintenance |
| `runtime/backend-port-parser.js` | Line-framed `BACKEND_PORT:<n>` parser for stdout and stderr chunks |
| `runtime/backend-startup-report.js` | Startup-failure report with secrets and home paths removed; save and copy |
| `runtime/owned-child-shutdown.js` | Stop only the owned backend child (Windows tree kill, POSIX process group) |
| `storage/storage-host.js` | Trusted Settings operations, startup progress and explicit recovery before backend launch |
| `storage/storage-location.js` | Persist the selected root in the stable Electron profile; schedule, verify and activate an offline copy |
| `storage/storage-progress.html`, `storage-progress-preload.js` | The move-progress window (loaded relative to `storage-host.js`) |
| `viewers/viewer-host.js` | The app's one `ViewerSession`, sending helper messages and frames to the main window |
| `viewers/viewer-session.js` | Fence helper lifecycle/events and allow only one IPC frame in flight plus one latest pending frame |
| `viewers/stream-viewer-manager.js` | Default on every platform: native renderer over an authenticated local WebSocket, JPEG preview frames to canvas |
| `viewers/viewer-manager.js` | Explicit Windows fallback: named pipe and owned native window overlay |
| `viewers/viewer-executable.js` | Resolve each platform's development and packaged renderer |
| `viewers/dolphin-capture.js` | Backend-owned Windows capture source, main-frame media lease and serialized window presentation |
| `viewers/app-dolphin-capture.js` | Bind the capture host to the main window and the backend's capture-target endpoint |
| `protocol/nucleus-protocol.js` | `nucleus://` registration, `open-url`, the single-instance lock and `second-instance`, cold-start argv, Linux registration |
| `protocol/protocol-handoff.js` | Parse and allowlist `nucleus://` routes; queue each handoff until the renderer acknowledges it |
| `protocol/linux-protocol.js` | Write the AppImage's `.desktop` entry so the desktop hands `nucleus://` to it |
| `updates/updater.js` | Signed auto-update against `releases.ssbmnucleus.net`; the pinned key is `updates/update-public-key.pem` |
| `updates/update-monitor.js` | Single-flight startup/manual checks, five-minute error retry, due checks on focus/resume, and shared update status |
| `updates/update-version.js` | SemVer and preview-tag ordering; which manifest versions each channel accepts |
| `shell/window.js` | `createWindow`: size, navigation guards, Vite or `frontend/dist` load, display zoom, viewer and capture cleanup. Closing the window quits; there is no tray or background mode (removed with Friends) |
| `shell/login-item.js` | Removes the login item 0.8.15's "open Friends when you open Slippi" switch registered (Windows, once) |
| `shell/external-links.js` | Which URLs may open in the system browser (HTTPS; loopback HTTP in development) |
| `ipc/trust.js` | `handleTrustedIpc`: only the app's own renderer origin (or packaged `index.html`) gets an answer |
| `ipc/*.js` | One registration function per feature, each given its dependencies: `files` (dialogs, `open-external`), `window` (`app:relaunch`), `system` (`backend-diagnostics`, `diag:get`, image clipboard), `storage`, `updates`, `viewer` (`viewer:*` and `dolphin-capture:*`), `protocol` |

Shared mutable state (`mainWindow`, `backendPort`, `trustedRendererUrl`,
`isQuitting`, plus the read-only `backendToken`) lives on one `ctx` object
that `main.js` creates and passes to each module; no module reads another's
globals. The packaged gate list stays in `main.js` because
`tools/build/preflight.py`, `tests/backend/test_gates.py` and
`test_preview_policy.py` read it there. Modules below `electron/` get the app
root and icon path from `main.js` (`viewers/viewer-executable.js` defaults to
`../..`); `storage-host.js` and `updater.js` load their own sibling files,
and `updater.js` reads the packaged manifest as `../../package.json`. The
manual harness `tests/electron/manual/test-updater.js` runs the real updater
against the live manifest.

**Renderer Content-Security-Policy.** The built `frontend/dist/index.html`
starts with a CSP `<meta>` (security review 11-19, H1). It is added by
`frontend/rendererCsp.js`, a Vite `transformIndexHtml` plugin with
`apply: 'build'`; the dev server gets none, because its React-refresh
preamble is an inline script.
- Script: only the bundle runs it (no inline, remote or eval). Workers come
  from the bundle or `blob:`.
- Connections: the local backend (HTTP and WebSocket on 127.0.0.1/localhost,
  any port) and any HTTPS/WSS host.
- Images and media: the bundle, the backend, `data:`, `blob:` and HTTPS.
- Styles and fonts: Google Fonts, plus inline styles.
- Blocked: plugins, frames, `<base>` and form posts.

A plain-HTTP remote origin, an inline script or `eval` needs the policy
changed there; the test is `frontend/src/shared/rendererCsp.test.js`. A
`<meta>` policy cannot carry `frame-ancestors`, `report-uri` or `sandbox`.

Update checks start 15 seconds after the main window opens. A successful check
schedules the next six hours later; failures retry after five minutes. Focus and
system resume trigger a check only when due. `NUCLEUS_NO_UPDATE_CHECK=1` disables
automatic scheduling and those triggers, while manual Settings checks remain
available. Every successful check publishes `update:available`, including null
to clear a stale banner. `useUpdateStatus` subscribes before reading the initial
snapshot and prevents that snapshot from overwriting a newer event. Dismissal
remains per release version. Version comparison treats a stable release as newer
than its prereleases; signed manifest and artifact verification remain required.
The download itself belongs to main (`ipc/updates.js`): `update:install-status`
answers whether one is running and how far it got, and `update:install-done`
reports its end, so a Settings card that unmounts mid-download and mounts again
follows the same download instead of offering a second one.

Update channels: a stable build polls only `<platform>/latest.json` and accepts
only a plain `X.Y.Z` from it. A test build — packaged `previewFeatures`
(`NUCLEUS_PREVIEW_FEATURES`) or a prerelease version (`NUCLEUS_BUILD_VERSION`) —
that also carries a packaged `previewChannel` token (`NUCLEUS_PREVIEW_CHANNEL`,
`[A-Za-z0-9_-]{16,64}` with a letter) polls that and the secret
`<platform>/preview/<token>/latest.json`, and offers the newer by SemVer
precedence (`0.9.0-preview.10` > `0.9.0-preview.9`; `0.9.0` > every `0.9.0-*`),
so a stable release moves testers back to the stable channel. Without a valid
token a test build checks the public manifest only. The token exists only in
the packaged `package.json` of test builds: `build.bat` refuses it without
`NUCLEUS_PREVIEW_FEATURES` and verifies the packaged value
(`tools/build/check_preview_channel.js`), so the app source and every stable
build contain no preview path. One unreachable channel does not fail the check.
`NUCLEUS_UPDATE_MANIFEST_URL` (unpackaged only) replaces both. The preview
manifest is written only by `prerelease_to_r2.py --channel <token>`; see
[PREVIEW-0.9.0.md](PREVIEW-0.9.0.md). There is no Settings opt-in: a stable
install cannot join the preview channel, because a test build turns on
unreleased features.

Ice Climbers painting uses the shared native `PaintPairSession` drawable and
owner router in Windows embedded, Windows streaming and headless streaming
hosts. It retains two DATs and correlates commands by session/request/member.
The manager's separate `viewerSessionId` fences transport events in the editor;
single-character commands keep their legacy protocol. See
[ICE_CLIMBERS_PAINT_PROTOCOL.md](ICE_CLIMBERS_PAINT_PROTOCOL.md).

Paired animation catalogs come from Popo's shared archive rather than the
intersection of Popo and Nana archives. Nana uses her own matching action when
present and otherwise inherits Popo's motion; Popo never inherits a Nana-only
override. Both animation payloads are decoded before either model changes.
This preserves the full shared catalog in previews opened from either climber.

The default Windows path uses HSDRawViewer's streaming host; Linux/macOS retain
HSDRawHeadless. `NUCLEUS_VIEWER_TRANSPORT=embedded` explicitly enables the old
Windows overlay for diagnosis; failure does not silently switch transports.
The helper receives an ephemeral session token through its environment and the
Electron client supplies it in HTTP/WebSocket headers. Renderer frame metadata
and acknowledgement are separate from painting-command correlation. Both viewer
surfaces subscribe before helper startup, discard obsolete frames, and acknowledge
owned frames after draw/discard or cleanup. ResizeObserver sizes the canvas;
streaming surfaces do not poll desktop coordinates. See
[VIEWER_STREAMING.md](VIEWER_STREAMING.md).

---

## 6. Data on disk (all gitignored)

Installed builds can schedule a data-folder move in Settings. On the next full
launch, `storage-host` prepares storage before starting the backend or delivering
imports. `backend/storage_relocation.py` runs through the backend's early
`--storage-maintenance` entry point without Flask/core initialization. It holds
an exclusive root lease and SQLite write locks through verified publication and
the activation acknowledgement. Normal managed backends hold shared lifetime
leases (`storage_data_lock.py`). The original folder is retained.

`NUCLEUS_DATA_ROOT` selects the full writable root below; `scratch/` and child
process temporary files follow it. Electron's profile/browser storage stays in
its original location, including the atomic `storage-location.json` pointer.
Missing selected drives fail with explicit recovery instead of creating another
library. Developer and legacy root overrides disable the Settings move workflow.
See [STORAGE_LOCATION.md](STORAGE_LOCATION.md) for boundaries and recovery.

| Path | Owner | Contents |
|---|---|---|
| `storage/` | **the vault** (`NUCLEUS_STORAGE_DIR` override) | Per-character costume dirs, `custom_characters/`, `custom_stages/`, `das/`, `menus/`, `bundles/`, `codes/`, `xdelta/` (base patches incl. the Ace build), `skinlab_materials/`, `_csp_hd_cache/`, `metadata.json` + `vault.db`, `nucleome.db` (replay index), `nucleome/`, `combo_video/`, `ai_studio.json`, `openrouter.key` (encrypted), `vanilla_iso.json`. **`test-base/` is NOT test scratch** — despite the name it holds (a) the vanilla CSP reference bank the app derives at first-run setup (152 DATs + `csp-references.json` + `bone-refs/`; `first_run_setup.py:183`) and (b) in a dev checkout, the FULL vanilla ISO `files/` extraction (~1,000 files) that the extras tooling (`extras_audit.py`, `effect_probe.py`), `test_build.py` and ~40 backend tests read. Regenerate (b) with `shared.vanilla_extract.vanilla_refs.extract_iso_files(<vanilla.iso>, <tmp>)` → copy `<tmp>/files/*` in, then re-derive menu refs (`menu_refs._derive_hud(files_dir, menu_refs.MENU_REF_DIR / 'hud_vanilla')`) — setup derives the HUD manifests from whatever is present, so a partial `test-base` yields wrong `manifest_usd.json`. `test-builds/` and `test-runs/` are genuinely regenerable (test-ISO output; `test-builds/pristine-base/` is the ~1.4 GB m-ex project of the vanilla ISO that every test build copies, rebuilt on demand by `projects/install/pristine_base.py`) |
| `projects/` | m-ex projects | One dir per project (~1.4 GB each: a full ISO layout). Test builds pile up here |
| `output/` | runtime scratch | ISO scans, exports |
| `logs/` | runtime | Rotated backend logs, embedded-viewer logs |
| `user_settings.json` | legacy | Old storage-path pointer |
| `dist-backend/`, `build/`, `dist-electron/`, `releases/` | build outputs | PyInstaller + C# payload, installers |

---

## 7. Feature gating (one table)

| Feature | Packaged backend env (`electron/main.js`) | Viewer flag (`shared/config/features.js`) | How the UI hides it |
|---|---|---|---|
| Combo Video | `NUCLEUS_COMBO_VIDEO=0` | `COMBO_VIDEO_ENABLED` (DEV only) | tab removed, chunk elided via `import.meta.env.DEV` fold |
| Randall / Analyst | `NUCLEUS_RANDALL=0` | `RANDALL_ENABLED` (DEV only) | same |
| Nucleus assistant (Randall's chat + the app MCP) | `NUCLEUS_ASSISTANT` (shipped 0.9.0 — no longer forced off; the variable stays as the kill switch) | `ASSISTANT_ENABLED` (DEV, or `VITE_ASSISTANT_PREVIEW=1`, which every build script sets when `ship_guard.py gate assistant` passes) | On in every package. To hold it back for a build, set `packaged_off=True` in `core/gates.py` and put it back in `main.js`'s list: the spec, the stage (Blender, rigswap), the frontend flag and the frozen smoke all follow, and a `previewFeatures: ["assistant"]` package opens it again |
| Build commit (assistant) | `NUCLEUS_BUILD_COMMIT=0` | — | A prepared menu + code change can still be inspected and authorized; `nucleus_api.builds.commit_change` and `/api/mex/builds/changes/<id>/approve` refuse outright (`outcome=build_commit_disabled`) rather than half-applying. **Stays off in a preview package too** |
| Delivery to the game (assistant) | `NUCLEUS_DELIVERY=0` | — | `randall/delivery/deliver.py` refuses with a sentence; delivery rebuilds and overwrites the file someone boots, so it is closed until the path is exercised on real builds. **Stays off in a preview package too** |
| Any-mod download (assistant) | `NUCLEUS_ANY_MOD_DOWNLOAD=0` | — | Randall still searches, inspects and previews every public post, and still downloads the three published export types (`character_dat`, `stage_dat`, `effects_dat`). A post whose only file is `other` — a menu DAT, a whole-mod archive — reports `can_download=false` and the refusal names the website's own download button. **Stays off in a preview package too**, until the archive containment, nested-budget and destination-binding work from the 2026-09-22 security review is signed off |
| Wish submission | `NUCLEUS_WISH_SUBMIT=0` | — | Wishes are still classified, recorded and counted locally; `POST /api/mex/wishes/<key>/submit` returns `submission_disabled`, the footer offers no "Review and send", and nothing may claim a report was sent. **Stays off in a preview package too** |
| Cloud Vault | `NUCLEUS_VAULT` (shipped 0.7.2 — no longer forced off) | — | `VaultSection` hides on HTTP 404 from `/api/nucleome/vault/status` |
| Tracker mode itself | `NUCLEUS_NUCLEOME` (shipped 0.7.0 — no longer forced off) | `NUCLEOME_ENABLED = true` | wordmark toggle |
| Premium surfaces (Analyst only) | — | `usePremium` ← Patreon entitlement | never gate Tournaments |
| Trailer capture | — | `VITE_SHIP_GATES=1`, `VITE_RECORD_MODE=1` | strips dev chrome, hides studios |

The backend half of every row above is declared once in `backend/core/gates.py`;
`electron/main.js` carries the packaged-build list and `tests/backend/test_gates.py`
fails if the two drift.

**Since 0.8.16 a closed gate's code is not in the installer at all**, not just
switched off (owner, 2026-11-04). The backend packages each gate owns are named
once, in `backend/core/build_smoke.py` `_GATED_PACKAGES`: the assistant is
`randall`, `nucleus_api`, `shared.aiengine`, `shared.modellab` and
the build-change approval route (`projects/routes/menus/build_changes.py`);
the Tracker coach (gate `randall`) is `randall.coach` and `randall.routes.coach`,
inside the assistant's package; Combo Video is `tracker.video.combo_video` and
`tracker.routes.combo_video`. A stable 0.9.0 build carries the assistant and
leaves out the coach and Combo Video.
`tools/build/mex_backend.spec` excludes them unless `ship_guard.gate_ships` says
the gate ships (not `packaged_off`, or a preview build's `NUCLEUS_PREVIEW_FEATURES`), and fails if any
still reached the bundle; the frozen `--build-smoke-test` re-checks from inside
the exe; `ship_guard` refuses a stage whose `frontend/dist` still has a closed
gate's chunk, or lacks a shipping gate's chunk (`GATED_FRONTEND_CHUNKS`). `app.py` imports and registers a gated
blueprint only while its gate is open, so a closed gate's routes 404 by not
existing. Shipped code that needs something from a gated package gets it moved
into shipped code instead (`shared/mod_files.py`, `core/gecko_codes.py`,
`watch_mods.COMBO_RENDER_KIND`); `tests/backend/test_stable_build_boots.py`
boots the app with the packages unimportable (stable, preview, and the assistant held back) and
`tests/backend/test_stable_build_imports.py` refuses an ungated import of one from outside its gate
(the assistant's own code included, for the coach) and pins what a stable build carries. Storage backend switches `NUCLEUS_VAULT_DB` and
`NUCLEUS_VAULT_DUAL_WRITE` are unrelated to the cloud vault and are not gates.

**A gate is also closed when its code is not in the checkout.** The public source
drop (`tools/public_drop.py`) leaves out the coach's and Combo Video's packages and
frontend folders, and a clone of it runs as a dev checkout, where every gate
defaults open. `gates.present(name)` is False when one of the gate's
`_GATED_PACKAGES` has no source on disk (never judged in a frozen build), and
`gates.enabled` then reads closed, so `app.py` and every gated call site skip it as
in a stable build; an ImportError inside a package that is there still surfaces.
The viewer half: `NucleomeApp.jsx` loads both pages through `import.meta.glob`,
which matches nothing without the file, and `COMBO_VIDEO_ENABLED` /
`RANDALL_ENABLED` close the same way; both globs sit behind `import.meta.env.DEV`,
so a stable build folds them away as before. Tests of shipped code that touch the
left-out code skip that part there (`tests/gated.py` `needs()`).

**Three `NUCLEUS_*` variables Electron sets are infrastructure, not gates**, and
`test_gates.py::test_electron_sets_no_other_nucleus_gate` lists them so a real
gate cannot be smuggled in beside them:

| variable | what it is |
| --- | --- |
| `NUCLEUS_APP_VERSION` | the spawning app's version, for diagnostics and bug reports |
| `NUCLEUS_BACKEND_TOKEN` | authenticates the app's private backend process. **Printed to the backend's stdout at startup**, which is how the test harness picks it up — so holding it does not mean being the app's window |
| `NUCLEUS_UI_APPROVAL_KEY` | a second, per-run secret that does. Never printed and never served: Electron hands it, with the backend token, to the app's own page over IPC (`renderer:secrets`, a synchronous call from `preload.js` → `window.electron.uiApprovalKey`; never the renderer's command line, which other local users can read on Linux) and to the backend's environment. `POST /api/mex/builds/changes/<id>/approve` and the MCP's window questions (`/api/mcp/window/confirmations`, `core/ui_channel.py`) require it, because those decisions are made by a person in the window and not by anything that can reach the port. With it unconfigured that endpoint refuses outright |

**Patreon is not a release gate, and it no longer gates much.**
Everything shipped on the desktop is free — Replays, Combos, Stats, Watch Lite,
Watch with mods and share links — except whole-library sync, which feeds the
phone and is priced with it. Signing in with Patreon is still required for the
features that touch our servers, but a free $0 account is enough to share: the
link exists so users are countable and bannable. The paid things are enforced
**server-side** (or by the backend, for sync), not by `usePremium`:

| Paid thing | Where it is enforced |
|---|---|
| The phone (the $5 tier) | `resolveOwner`'s device-token branch requires `patreon_links.is_active`; `vault-sync` `pair` returns `pledge_required` to a free desktop |
| Whole-library sync | `POST /vault/sync` → 402 `pledge_required`, and `vault_jobs._read_settings` forces `auto_sync` off, both keyed on the `vault_pledge_active` kv value. It exists to feed the phone, so it is priced with the phone |
| Randall | `randall-chat` requires `owner.active`; `CoachPage` also self-locks. The assistant ships since 0.9.0; the coach is unreleased regardless |

"Paid" for the cloud is `shared/account/cloudPlan.js` `isCloudPaid`: any paid
tier, i.e. ai-entitlement `source: 'patreon'` (a live pledge or the rest of a
paid month). It is NOT ai-entitlement's `active`, which also covers AI-only
access (grants, the free pot in AI free mode) and drops to false for payers
while AI is paused. `usePremium`, the launch mirror and the Cloud hero all use
it. The Cloud hero (`tracker/cloud/CloudHero.jsx`) is the one place that sells
and explains each level; a pledge turning paid for the first time on an
install turns `auto_scan`/`auto_sync` on where the user never set them and
starts the chain. The pledge is only mirrored when the answer says something
about it (`cloudPledgeKnown`: not on a failed check, not while AI is paused
unless the membership is 'paid'), a new token is unpaid until told, and only
one autorun chain runs at a time (it is one `cloud_autorun` job). Token changes
are handled one at a time (`_token_lock` in `tracker/routes/cloud.py`), so a
token still being checked with the vault cannot land after a later sign-out.
A sign-out whose clear never reached the backend is remembered in
localStorage (`shared/account/signOutPending.js`) and sent again by the launch
mirror. The Cloud card's phones and pairing code belong to the account the
token was sent for (`tracker/cloud/cloudAccount.js`): linking another Patreon
drops them, and revoking the phone a code just paired takes the code down.

Sharing one replay is **not** paid, and `POST /share` uploads the game if it
isn't in the vault yet — on the free tier that is the only thing that ever
puts a replay in R2. `vault_pledge_active` is mirrored from the viewer by
`POST /vault/token` (the backend cannot run the Patreon entitlement check
itself); absent means "never told" and keeps working, only an explicit `false`
disables. That mirror is a viewer-side gate with a server-side backstop, not a
security boundary — it doesn't need to be one, because pairing a phone is
refused independently, so a free account that forced an upload would still
have nothing to read it on.

The ban lever is `patreon_links.banned_at`, checked in `resolveOwner`'s
app-token branch. It exists because ungating desktop means `is_active = false`
no longer stops anyone there.

---

## 8. Everything else in `app/`

| Dir | What it is | Status |
|---|---|---|
| `utility/mex/` | **Fetched, git-ignored**: the pinned prebuilt MexCLI (fork `ssbmNucleus/m-ex`, tag in `mex.manifest.json`); `tools/build/fetch_native.py` unpacks it and the build scripts stage it into `dist-backend/mex*` | live |
| `utility/hsdraw/` | **Fetched, git-ignored**: the pinned prebuilt HSDRawViewer / headless renderer (fork `ssbmNucleus/HSDLib`, tag in `hsdlib.manifest.json`, with its `--csp`, `--stream`, `--csp-server` modes) | live |
| `utility/tools/processor/` | CSP regression fixtures + processor scripts | live |
| `../services/mobile/` | Phone vault PWA (`nucleus-vault` Cloudflare Pages); bundles with esbuild from `app/frontend/node_modules`; talks to Supabase edge functions | live, separate deploy |
| `../services/cloudflare/replay-worker/` | Worker serving `ssbmnucleus.net/replay/*` share pages (Discord unfurls) | live, separate deploy |
| `../services/cloudflare/bugreport-worker/` | Worker serving `ssbmnucleus.net/bugreport/*` — private bug-report intake (R2 `nucleus-bug-reports` + private Discord webhook, version-gates old clients via `latest.json`); admin CLI `tools/admin/bug_reports.py` | live, separate deploy |
| `../tools/ingame/` | Dolphin harness (`dolphin/`, `nucleus/`) for CSS/SSS UI tests, the smoke runners and the dev-only RAM evidence readers (`contacts`, `input_evidence`, `owned_session`, `verify_memory_input.py`) (repo-root `tools/`, not in `app/`) — **not** the unit suite (that's `tests/backend/`) | semi-superseded by `backend/shared/ingame/` + MCP |
| `../tools/build/` | `build.bat` / `build-linux.sh` / `build-macos.sh` (repo-root `tools/build/`), PyInstaller spec, `ship_guard.py`, R2 release scripts, `secret_cache.py` (RELEASE_NOTES.md moved to `docs/dev/release/`) | live |
| `utility/clear_storage.py` | Shipped to `scripts/tools/clear_storage.py` in the installer. Everything else that used to live in `scripts/` (`mex_codes.py`, wiki server, admin, migrations) is in the repo-root `tools/` | live |
| `../docs/wiki/` | user-facing pages + hand-rolled static site (`npm run wiki`) | live |
| `../docs/dev/` | This tier; see [DOCUMENTATION.md](DOCUMENTATION.md) | live |
| `reference/` | Not tracked: gitignored local clones of m-ex / MexTK / akaneia for lookup (the All-Star port inquiry is in git history before 2026-10-03); its stale README was deleted 2026-10-01 | local only |

The agent modpack bake-off (`duel/`) is finished; code and spec archived at ssbmNucleus-archive/duel.zip (2026-10-03).

---

## 9. Known duplication / debt register

The 2026-08 items (one CSP render path, one API client, root-module moves, one gate
table, vendored-copy sync test) and the 2026-10-03 reorganisation (areas, split packages,
`mex_api.py` -> `app.py`) are done and live in git history. What is still true now:

1. **Long files left.** The giant mixed-purpose files were split into packages; what remains long
   is long for a reason:
   - `core/extra_types.py` (3.3k lines): the declarative per-character extras table; data only.
   - `shared/vanilla_extract/first_run_setup.py` (2.1k lines): one class, the first-run flow.
   - `nucleus_api/builds.py` (1.3k lines): the build-change facade.
   - CSS: the four interleaved sheets (`FriendsPage.css`, since removed, `App.css`, `IsoBuilder.css`, `ChatUI.css`)
     were split per component 2026-10-03 (§4.3); the rules for export screens the builder no longer
     renders and `buttons.css`'s second `.btn-export` copy went 2026-11-03. The `.sprite-*`
     rules of `shared/ui/Sprites.jsx` stay in `randall/chat/ChatUI.css` because moving them would
     newly style Replays' cloud-sync Randall icon in release builds, where the assistant chunk
     never loads (a visible change to decide on its own).
   - Other files near 1k lines (`devtools/netrig.py`, `devtools/frameshot.py`,
     `shared/ingame/verify_costume.py`, `projects/routes/test_in_game.py`) have no split planned.
2. **Route-to-route imports**: none left outside the deliberate exceptions of §3.6 rule 1 (closed
   2026-10-03). A new one is debt: move the shared part into an engine module instead.
3. **JSON + SQLite vault dual-write** is by design during rollout; raw `metadata.json` access is
   confined to `vault/routes/vault_backup.py` and the first-run test path.
4. **Side repos** (fighter_port moved out 2026-10-03 to the private `ssbmNucleus-fighterport`;
   pokedex and trailer likewise). `ssbmNucleus-pokedex` and `ssbmNucleus-fighterport` are inactive
   and import the v4 model importer, which left this repo 2026-11-03: to run them, point
   `NUCLEUS_REPO` at a checkout of the `archive/v4-importer` tag.
5. **`app/utility` vendored toolchain**: the MexManager and HSDLib forks live in their own repos
   with a pinned prebuilt manifest, like ffmpeg and Blender. A change to fork source ships as a new
   release tag, bumped in `app/utility/*.manifest.json`.
6. **LF/CRLF warnings** when staging: `.gitattributes` and editor settings disagree; pick one policy.

---

## 10. Dev workflow

```bash
tools\dev\run.bat --check       # Windows dependency-only preflight, no app launch/build
tools\dev\run.bat               # Pinned native tools check/fetch, then owned Vite + Electron/Flask
tools\dev\run.bat --rebuild     # Force a re-fetch of MexCLI/HSDRawViewer
npm run dev            # Flask + Vite in a browser
npm run wiki           # (from app/) user docs at 127.0.0.1:4173/wiki/
app/venv/Scripts/python -m pytest tests/backend -q     # from the repo root; fast set only (about 4.5 min); -m slow runs separately
cd frontend && npm run build && npm test                 # bundle + utils tests
tools\build\build_logged.bat                         # full Windows installer
```

Prefer the `melee-harness` MCP (`tools/harness/harness_mcp.py`) for anything
in-game, CSP, DAT, MexCLI or HSDRaw related — [MCP_SERVER.md](MCP_SERVER.md),
[INGAME_TESTING.md](INGAME_TESTING.md). Release recipe:
[RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md), [RELEASE_PIPELINE.md](RELEASE_PIPELINE.md).

### Shared Randall presentation and approvals

| Module | Responsibility |
|---|---|
| `backend/randall/assistant/engine.py` / `live_runs.py` | Independent provider-reply and direct-download runs (`engine.start`), per-run messages/approvals and serialized shared transcript saves (`live_runs`); records each turn's `routing` (router answers, workflow lane, models) on the answer |
| `backend/randall/reports/chat_report.py` / `frontend/src/randall/chat/ChatReportModal.jsx` + `chatReport.js` | "Report this chat": transcript, tools, routing, model requests, cost and errors for one conversation; scrubbed, size-capped, frozen before consent, idempotent two-stage send (mobile twin: `services/mobile/src/chat-report.js`) |
| `backend/randall/delivery/game_tests.py` | Validated chat targets and request-owned app settings over existing single-mod test handlers; durable session ownership, status and Stop; exact exported costume tests without vault imports |
| `backend/randall/assistant/clone_character.py` / `backend/vault/echo/clone.py` | Immutable costume handles to complete five-costume Echo packages; native texture recolors and portrait rendering, staged vault publication, retry deduplication and retained donor data |
| `frontend/src/randall/assistant/GameTestCard.jsx` / `gameTestSession.js` | Inline manual-play card, scoped status recovery/Stop, existing Dolphin video renderer; history never launches a process |
| `frontend/src/randall/assistant/StudioCards.jsx` / `studio.js` | model import cards routed by the `studio_import` reply tag: the `import_model` job card (the fighter, its time on the status bar's clock, the running lines, where it stopped, the costume file's portrait, the vault save); an older chat's v4 import reply draws plainly from the same fields; for chats from before it, the studio's stage cards with pictures and full-size view, the stage-10 in-game triptych, `fresh_eyes`, `look`, `decide`, `import_status` |
| `backend/shared/mod_files.py` | Immutable file handles and bounded upload/archive/DAT inspection (in `shared/` since 0.8.16: the stage editor, viewer and Echo cloning use it in stable builds); opening a vault costume as a working copy is `randall/assistant/vault_items.py` `open_vault_file` |
| `backend/randall/assistant/hsdraw.py` | Fixed headless HSDRaw operations over file IDs, copy-only edits and new-costume vault saves |
| `backend/randall/model_import/chat/studio_import.py` | The model import in chat, routed per turn (`turn_mode`): an import turn is offered `import_model` with `search_docs` and `test_in_game` and its recipe card; after a finished import, normal turns are also offered `import_model` so the same model can go on another fighter; every other turn is a normal Randall turn; tags every reply `studio_import: {tool, id}` and registers its pictures as chat files |
| `backend/randall/model_import/chat/import_job.py` | `import_model`: rigswap as a subprocess (the installer's own, or the developer's), the fighter it goes on or picks, progress to the running card, Stop by its PID tree, the vault save naming the project (`studio/finish.py`), the reply (`done`, `failed` with where and why, `cancelled`) |
| `backend/randall/assistant/stage_scene.py` | Stage object inspection/preview and scenery transfer over immutable file IDs; validates selection, transforms and copied-instance lineage |
| `backend/randall/recolor/skin_lab.py` | Private copy-only costume viewer sessions; full-resolution palette groups, hue/saturation recolors and reset, camera previews, immutable exports; two-session cap and 15-minute idle cleanup |
| `backend/randall/assistant/vision.py` | Server-resolved lab PNGs converted to bounded images for model context after tool replies; image bytes stay out of stored chats |
| `backend/randall/recolor/materials.py` | Shared skin/stage material actions; validates live-discovered IDs, RGBA and finite bounded numeric values before native commands |
| `backend/randall/recolor/texture_material.py` | Fresh material swatches, mask/candidate previews, geometry projection or pixel tiling, absolute refinements and reset in private costume sessions |
| `backend/randall/recolor/texture_inspection.py` | Live texture geometry summaries, paged contact sheets and temporary on-model highlights using renderer indices |
| `backend/randall/assistant/continuity.py` | Immutable edit checkpoints and bounded source/swatch/session/preview state reconstructed from server-owned receipts |
| `backend/shared/aiengine/image_api.py` | OpenRouter Image API adapter for swatches; request-scoped or stored credentials, bounded PNG decoding, reported cost, no automatic retries/cache |
| `backend/shared/aiengine/fast_lane.py` | Shared per-turn Gemini retrieval path for assistant and coach; scoped tools, whole-batch validation, private handoff with original history, timeout/error fallback, request-scoped credentials |
| `backend/randall/recolor/workflows.py` | Fixed stage ownership for single-costume recolors: Gemini acquisition with typed source evidence, receipt-driven Python setup through the normal executor, main-model creative edits/review; preserves approvals and checkpoints, with no AI requests for automatic setup |
| `frontend/src/vault/editors/materialPalette.js` / `useColorPalette.js` | Unified texture/material color samples, absolute hue/saturation groups, scoped analysis, reset and serialized save flush |
| `frontend/src/vault/editors/useMaterialColors.js` / `MaterialColorsPanel.jsx` | Session-scoped request/acknowledgement, save gating and dirty tracking for material controls shared by character and stage editors |
| `frontend/src/shared/lib/EditorContext.js` | Shared Texture Lab target, selection and explicit PNG apply requests; the existing conversation stays mounted |
| `frontend/src/randall/assistant/ModFileCards.jsx` | Compact file activity, generated/downloadable files and PNG application to the selected editor texture |
| `frontend/src/randall/assistant/StageModCard.jsx` / `stageNavigation.js` | Stage receipt previews and Edit; resolves old folder/new code receipts against current catalog and variants before navigation. Vault editing opens standalone; chat Edit requests the shared Stage Creator with Randall |
| `backend/randall/delivery/projects.py` | Project IDs/discovery, approved vanilla project creation and exact-target costume batch installs with stale-plan checks; no ISO export |
| `backend/randall/website/website.py` / `website_search.py` / `website_posts.py` | Public mod search (`website_search`), metadata previews and account-bound likes (`website_posts`), approval-bound downloads and unified vault import (`website`, with `website_exports`, `website_scope`, `website_receipts`) |
| `backend/randall/website/website_bulk.py` | Exact batch preparation, one download/safety approval, sequential imports and per-post progress with partial-success preservation |
| `backend/randall/website/website_artwork.py` | Match separately hosted CSP/stock images to costume DATs in downloaded archives |
| `backend/randall/website/website_safety.py` | Read-only Slippi preflight of downloaded costumes and supported nested archives before vault writes |
| `frontend/src/randall/assistant/WebsiteModCards.jsx` | Animated galleries, account hearts, and download/approval/ownership states within one card |
| `frontend/src/randall/assistant/websiteCards.js` | Consolidates post receipts so later tool results update the original card |
| `frontend/src/randall/assistant/transcript.js` | Merges polled download receipts without overwriting the SSE-owned reply or duplicating streamed tokens |
| `frontend/src/randall/assistant/ChatMotion.jsx` | Ozone-style typing bubble and gradual streamed text reveal |
| `frontend/src/randall/assistant/PortraitActivity.jsx` | Compact animated CSP status, portrait result, and visible render/image errors |
| `frontend/src/randall/assistant/ProjectToolCard.jsx` | Project review/receipts, costume portraits and direct Open project navigation |
| `frontend/src/randall/assistant/FileReadActivity.jsx` | Collapsed Ozone-style summaries for consecutive help searches, unique source titles/excerpts, and visible errors |
| `frontend/src/randall/assistant/DownloadReceipt.jsx` | Compact Added to vault receipts with exact imported CSPs and stock icons |
| `frontend/src/randall/assistant/DownloadApprovalDialog.jsx` | Compact confirmation with mod portrait cards and visible file inventory; search/paging for large packs |
| `frontend/src/randall/assistant/SlippiApprovalDialog.jsx` | Unsafe costume review with Fix, Add without fixing, and Cancel choices |
| `frontend/src/randall/assistant/VaultModCards.jsx` | Vault portraits and color variants with explicit Select for chat buttons |

`frontend/src/randall/chat/ChatUI.jsx` owns the Tracker and Nucleus chat shell, sidebar, header, input, and Patreon introduction. `backend/randall/assistant/approvals.py` owns expiring, call-bound approval grants; tool policies and transactional plan revalidation live in `randall/assistant/tools.py`.

### Skin Creator viewport controls

`vault/editors/useCanvasScale.js` owns a CSS-only scale/translation for
paint-canvas viewing (5% to 6400%). Its stable update callback keeps viewport
changes out of the texture-loading effect and undo history. Wheel zoom anchors
to the pointer; Space/middle/hand drag pans with window mouse-up/blur cleanup.
Fit follows ResizeObserver; manual zoom persists across panel resizing and resets
when texture ownership changes. Paint coordinates use the transformed canvas rect.
`shared/hooks/usePanelResize.js` exposes accessible separator props, clamps persisted
sizes, bounds pointer dragging to the editor, and cleans up listeners/body styles.
Skin Creator uses container queries so the workspace also adapts beside Randall.
Its 3D preview pans like Randall's workbench: `vault/editors/paintViewerPan.js` reads the
renderer's camera (`exportScene`) once a model is up and passes `useViewerInput` a `panStep`
(`viewerInput.cameraPanStep`), so a right-drag keeps the model under the cursor on both axes.

`randall/chat/visibleText.js` removes reasoning envelopes and streaming tag fragments
at presentation time for Tracker and Nucleus; stored text/tool offsets stay intact.


### Shared live stage rendering and editor

`Rendering/Models/StageScene.cs` loads map_head model groups, stage scale,
group/head lights and default joint/material animations. Both `--stage-render`
and `StreamingServer` use it. Cached texture indices are flattened across groups;
MatAnim frames and standalone root/bank images are included. Standalone roots
use synthetic TOBJs and must explicitly copy encoded bytes back to the root on
update. Camera and animation state remain presentation state. The streaming
server reuses its owned process, bounded command queue and frame protocol.

`SkinCreator.jsx` accepts a stageCode/variantId source via StageDetailView. It
uses the shared canvas/palette/undo controls and the normal Electron streaming
host. `/stage-editor/open` returns an opaque workspace ID and source path;
`/stage-editor/save` writes a unique new stage archive, retaining companion files,
with optional screenshot and metadata refresh. `shared/rendering/stage_editor.py` owns
workspace validation and copy saves; source hashes prevent stale edits.

`randall/recolor/stage_lab.py` provides stage_lab_open and stage_lab (inspection,
rendered frames, PNG export/replacement, recolor, camera, animation, save, close).
The open returns the first picture, labelled texture sheets and per-texture rows;
recolor batches exact-colour edits, reset_texture restores the opened state, and
greyscale (intensity) slots refuse colour, which a saved stage would drop.
Generated materials reach a stage through the costume tools (`generate_material`,
`skin_material`), which accept a Stage Lab session (`randall/recolor/lab_common.py`).
Scenery actions use `randall/assistant/stage_scene.py` and native `StageScenery.cs` to
inspect/preview selected meshes, copy a donor render tree, transform new scenery
instances and hide objects. Immutable file metadata carries instance lineage;
the live viewer is replaced only after the edited copy renders successfully.
Existing stage groups, joint indices, collision and stage logic are retained.
It owns at most two private ViewerSessions, separate from any human editor.
Image files use the existing immutable attachment store and chat cards. Neither
path exposes collision edits or ISO export; saves are marked Slippi-untested and
carry `has_screenshot` and `date_added`. Workspaces under storage/stage_editor are
pruned on each open (`stage_editor.prune_workspaces`: the newest ten and any younger
than three days stay).

Stage Creator palette analysis requests full-resolution PNGs through getFullTexture; it never recolors upscaled thumbnails. Idle Randall Stage Lab sessions close after fifteen minutes.

### Randall queue and steering

`randall/assistant/store.py` stores pending inputs separately from the transcript in the
chat SQLite database. Delivery moves inputs and the new answer into the transcript
in one transaction. Credentials stay on the active `Run`, never in the queue.
The reply worker drains FIFO after normal completion; Stop/errors leave the queue
paused. Send now promotes a visible batch and delivers it oldest first at a safe
provider/tool boundary without terminating running native tools. Completed tool
receipts, checkpoints and visual evidence carry into the continuation. Direct
download workers keep separate cancellation.

`PendingMessages.jsx` ports Ozone's `QueuedPrompts` and desktop overflow menu;
`QueuedPrompts.css` ports the in-thread bubble overrides and `QueueIcons.jsx` the
actual SVGs. The last bubble sends the batch; Edit removes a pending item only
after server acceptance and restores its text/attachments into the composer.
SSE owns the streamed answer while polling merges independent receipts.
