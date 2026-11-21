# tools/

Dev-only scripts. Nothing here ships in the installer and the app never imports from it. Stage explicit paths; write throwaway output under `app/scratch/`.

- `build/` build and release: `build.bat`, `build_logged.bat`, Linux/macOS builds, PyInstaller spec, `ship_guard.py`, `fetch_native.py`, preflight and release publishers. Reach for it to cut a build or release (only when asked).
- `harness/` the `melee-harness` MCP server (`harness_mcp.py`). Reach for it to drive the app/Melee from an agent.
- `ingame/` Dolphin driver, smoke runners, the modded-ISO builder (`nucleus/`), plus the dev-only RAM evidence readers and the memory-input parity check (see its README). Reach for it to test something in a real game; output goes to `app/scratch/ingame/`.
- `native_rig/` the FOBJ track reader the Watch Lite audit uses (see its README).
- `liteaudit/` the offline Watch Lite audit of the real bundle and paint paths (see its README).
- `dev/` day-to-day launcher (`run.bat`, `launch.cjs`), `clean.bat`, `open_wiki.bat`, Gecko-code refresh (`mex_codes.py`), part-map build/extract. Reach for it to run the app locally.
- `admin/` release-side admin and storage utilities: bug-report reader (`bug_reports.py`), in-app report tracker sync (`report_tracker.py`), SMD export verifier (`verify_smd_exports.py`).
- `rank-baselines/` offline miner that turns ranked Slippi replays into the tier baseline packs shipped in `app/backend/tracker/baselines/`. Reach for it only at a baseline refresh; corpus is untracked `data/`.
- `wiki/` local wiki server (`serve.py`, `npm run wiki` in `app/`) and the effect-offsets reference generator.
- `part_map_labels/` hand-authored per-character labels read by `dev/part_map_build.py` to produce `app/backend/assets/vanilla_parts.json`.
- `discord/` community bug tracker: Discord export, triage, `tracker_ui.py` (see its README).
- `clean.py` clears scratch, test runs and other regenerable data; dry run by default, `--yes` deletes.
- `release_to_public.py` stages the release-only source drop of all four public repos and leak-gates it (dry run by default; pushing needs `--confirm-repo` per repo). Logic in `public_drop.py`.
