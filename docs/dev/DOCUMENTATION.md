# Documentation System

How documentation is organized in this repo, and the checklist for keeping it
current when things ship. If you are about to write something down and don't
know where it goes, start here.

## The Tiers

| Tier | Location | Audience | Contract |
|------|----------|----------|----------|
| **User guide** | `docs/guide/sections/*.md` (+ `docs/guide/scripts/` screenshots) | Users of the app | The primary user documentation: RELEASED features only, with screenshots regenerated from the real app. Features, not internals. |
| **Wiki** | `docs/wiki/*.md` | Users + Randall | Workflow notes and Melee modding context. Randall also reads these pages at runtime as its help text (packaged builds bundle them), so they must stay accurate; label preview features. No code paths, no endpoints. |
| **Evergreen dev docs** | `docs/dev/` (see map below) | Developers / AI assistants | Kept current with the code. Wrong info here gets fixed, not tolerated. |
| **Research docs** | `docs/dev/` (the research list in the map below) + `research/docs-research/` (raw reference material; the two reference files the wiki links live in `docs/wiki/reference/`) | Developers | Point-in-time investigation write-ups. Valuable history, NOT maintained against the current code. |
| **Changelog** | `app/CHANGELOG.md` (stays in `app/`: electron-builder and docs/public-shell read it there) | Users | User-visible changes per release, under `## Unreleased` until shipped. |
| **Agent context** | `CLAUDE.md` (root and `app/`) + auto-memory | AI assistants | Hard-won gotchas and workflow rules only — not a mirror of the docs. |

## The Ship Checklist

When a change lands, update docs in the same change (not "later"):

1. **User-visible feature or behavior change** → update the guide section (and
   regenerate its screenshots) for released features, edit or add a wiki page,
   and add an `app/CHANGELOG.md` entry. New wiki pages must be registered in **both**
   `docs/wiki/wiki.js` (`NAV_SECTIONS`) and `docs/wiki/README.md`.
2. **Endpoint added/changed/removed** → `docs/dev/API_REFERENCE.md` (the Blueprint
   Summary table counts AND the endpoint section).
3. **New blueprint, backend module, or frontend hook** → the matching table in
   `docs/dev/ARCHITECTURE.md`.
4. **Behavior a wiki page or dev doc describes changed** → fix the page in the
   same PR that changes the behavior. A stale doc is worse than no doc.
5. **Removed a feature or flow** → delete or rewrite its doc sections. Git
   history is the archive; the working tree should never describe things that
   no longer exist.

## Wiki Conventions

- Plain voice, second person, short sections. Describe what the app does and
  why it matters, not how the code does it.
- No file paths, endpoints, or module names — those belong in `docs/dev/`.
- Every page links its related pages at the bottom.
- Preview locally with `npm run wiki` (run from `app/`; runs `python ../tools/wiki/serve.py`, which serves `docs/`) at
  `http://127.0.0.1:4173/wiki/`.

## Dev Doc Conventions

- Research docs should say so up front (a one-liner like *"Investigation
  write-up (2026-06); describes the state at the time"*) so a reader knows not
  to treat them as current.
- Don't reference scratch scripts that won't be kept. If a one-off probe
  proved something, state the finding and note the probe was not kept.
- One doc per topic; extend the existing doc instead of starting
  `TOPIC_V2.md`.

## Docs Map

Evergreen (kept current):

- `ARCHITECTURE.md` — system overview: layers, blueprints, hooks, dirs
- `API_REFERENCE.md` — every Flask endpoint
- `DEVELOPMENT.md` — dev environment setup and running
- `LINUX_BUILD.md` / `MACOS_BUILD.md` — packaging and installers
- `RELEASE_PIPELINE.md` — SSH builds, verified staging, R2 publishing and recovery, packaging checks
- `RELEASE_CHECKLIST.md` — cross-repo release ordering (app + website + Supabase
  + external accounts); what `tools/build/release.bat` does not cover
- `WINDOWS_SIGNING.md` — why only the installer is signed (owner's choice), what Smart App Control
  can still block, and how to list the unsigned files inside by hand
- `ROADMAP.md` — feature roadmap, updated as phases complete
- `MOVE_PIECES_PLAN.md` — the plan for the pieces a fighter swaps in during a move on imported costumes (not started)
- `FRIENDS_TAKEDOWN.md` — the plan for taking down the Friends servers (presence worker, R2, Supabase tables) after 0.8.16 (not started)
- `MELEE_MODDING.md` — Melee domain knowledge (DAT formats, character codes)
- `MENUS_SYSTEM.md` — CSS/SSS menu-mod backend
- `CUSTOM_CONTENT.md` — custom characters/stages, ISO scanning backend
- `INGAME_TESTING.md` — the `backend/shared/ingame/` test engine
- `EXTRAS_AUDIT.md` — extras-vs-in-game audit workflow + per-extra status
- `RANDALL_RECOLOR.md` — how Randall's recolor works: palette math, materials, texture_material, swatch library, stage lab
- `COACH_BASELINES.md` — coach baseline packs (the coach itself: `RANDALL.md`): what ships, the analyzer-repo
  mining pipeline, the coach tool API
- `VAULT_SQLITE_MIGRATION.md` — vault DB design (live during the migration)
- `raw-slp-vault.md` — the cloud vault stores the compressed `.slp` once; viewers derive playback in JS (plan, wire contract, rollout gates)
- `lite-deriver.md` — the JS `.slp` → Watch Lite bundle module: finalized frames (rollback removed), parser and bundle contract, parity target
- `COMMUNITY_BUG_TRACKER.json` — Discord bug reports and feature requests:
  reporter, version at the time, status, fixing release. Fed by
  `tools/discord/export_server.py` + `tools/discord/triage_new.py`; `tools/discord/tracker.py`
  renders a markdown view into `app/scratch/` (untracked)
- `APP_REPORT_TRACKER.json` — in-app reports (Bug Report + "Report this chat"):
  issues per report, status, fixing build/commit. Maintained by
  `tools/admin/report_tracker.py` (`sync` adds new worker reports, `render`
  writes a markdown view into `app/scratch/`, untracked)
- `RANDALL.md` — the one current description of Randall: assistant workflows,
  Tracker coach, gates, aiengine runtime, data written, module map, tests,
  history, and "Report this chat". The four older Randall docs are in git history before 2026-10-03.
  Beside the code: `app/backend/randall/README.md` (one line per folder) and the two pipeline READMEs,
  `randall/recolor/README.md` and `randall/model_import/README.md` (each pipeline stage by stage).
- `MCP_SERVER.md` — the `melee-harness` dev MCP server
- `APP_MCP.md` — the app as an MCP server for the user's own AI (`POST /api/mcp`, `SSBM Nucleus.exe --mcp`,
  the Settings card, the creation toolkit gateway for `native_port` and `stage_workbench`)
- `MODEL_IMPORT_TOOLS.md` — the model import's Blender and Python as a download from Settings (since 0.9.0):
  the pinned manifest, the assembly, the Settings card, the build, and the macOS/Linux port test
- `STORAGE_LOCATION.md` — moving the data folder (storage manager, startup recovery)
- `VANILLA_ASSET_POLICY.md` — the rule: no Nintendo data ships; everything vanilla
  comes from the user's own ISO
- `VIEWER_STREAMING.md` — how the 3D viewers stream frames to the UI
- `ICE_CLIMBERS_PAINT_PROTOCOL.md` — the paired Popo/Nana painting preview protocol
- `EXTRAS_MISSION_TEMPLATE.md` — standing instructions for extras-campaign agent missions
- `release/RELEASE_NOTES.md` — release notes for the current version
- `../README.md` — index of `docs/`; `../public-shell/` — README, logo and issue templates for the public repo's root (the release source drop, `tools/release_to_public.py`)
- `DOCUMENTATION.md` — this file

Planning contracts and inventories (check approval status and dated baseline):

- `PREVIEW-0.9.0.md` — release gates and preview policy: the living spec that
  `app/backend/core/gates.py` and `app/electron/main.js` cite (the 0.9.0 preview is the worked example)
- `L_LOAD.md` — how ACE 2.0's L-press alternate fighters work, and the proposed Nucleus design: L scrolls a list, tucked icons (core proven in game on scratch ISOs; not built into the app)
- `NOW_PLAYING.md` — the song name at match start: how ACE's `bgm_display` plugin does it, the clean-room Gecko code new projects start with, and how they get it

Research / point-in-time (not maintained; check dates before trusting):

- `MEX_BUILD_LIMITS.md` — build-limit research + its probe-script toolkit
- `STAGE_HSD_RENDER.md` — headless `--stage-render` stage-preview prototype
  (working, shelved; camera calibration + per-stage group tables)
- `CSP_LOWPOLY_HIDING.md` (incl. the in-game shadow/magnifier fix) — a rendering investigation (the findings
  shipped; the write-up is history)
- `CSP_RENDERING_DEBUG.md` — CSP debugging workflow + past-bug casebook
- `MEX_INTEGRATION.md` — early MexCLI integration notes
- `research/docs-research/` (and the two reference files under `docs/wiki/reference/`) — raw reference material

## What NOT To Do

- Don't put user-facing how-tos in `docs/dev/` — they rot invisibly there. If a
  user would want it, it's a wiki page.
- Don't duplicate content across tiers; link instead.
- Don't leave a doc describing removed behavior "for context" — rewrite it as
  explicitly historical or delete it.
