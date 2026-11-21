# Development Setup Guide

This guide will help you set up the development environment for Nucleus Desktop.

## Prerequisites

1. **Python 3.10+** - [Download from python.org](https://www.python.org/downloads/)
   - Make sure to check "Add Python to PATH" during installation

2. **Node.js 20.19+ or 22.12+** - [Download from nodejs.org](https://nodejs.org/)
   - Includes npm (Node Package Manager)

3. **GitHub access, only for private forks.** The launcher fetches the pinned MexCLI and HSDRawViewer builds from the fork repos' GitHub Releases. The public repos (`ssbmNucleus/HSDLib`, `ssbmNucleus/m-ex`) need no login; private forks need the GitHub CLI (`gh`) logged in, or a token in `NUCLEUS_FETCH_TOKEN`. No .NET SDK is needed to run the app.

4. **Git** - [Download from git-scm.com](https://git-scm.com/)

## Quick Start (recommended)

`tools\dev\run.bat` is the primary dev launcher. It checks installed dependencies and that the
pinned MexCLI and HSDRawViewer builds are unpacked and current (fetching them if not) before every
launch, then starts an owned Vite child and a visible Electron app. Electron starts
Flask. It does not install dependencies or kill existing sessions. Logs are written
to `app/logs/`; close the app window to finish its launcher session.

```bash
tools\dev\run.bat --check    # preflight only
tools\dev\run.bat            # fetch the pinned native tools if stale, then launch the dev checkout
tools\dev\run.bat --rebuild  # force a re-fetch of the pinned native tools
```

Use the manual setup below for missing dependencies.

The launcher fetches pinned mexcli/HSDRaw builds: `app/utility/mex.manifest.json` and
`app/utility/hsdlib.manifest.json` name a release tag and a sha256 per platform of the
`ssbmNucleus/m-ex` and `ssbmNucleus/HSDLib` fork repos (the m-ex and HSDLib source
no longer lives in this repo). They unpack to `app/utility/mex/<rid>/` and
`app/utility/hsdraw/<rid>/` (git-ignored). To bump a tool, publish a new tag on the fork and edit
`tag` and the `sha256` values in the manifest from that release's `SHA256SUMS.txt`. `--check` only
reports whether a fetch would run. A failed fetch stops launch, so an older MexCLI cannot silently
reject newer backend commands.

To fetch by hand (a private fork needs `gh auth login` first, or `NUCLEUS_FETCH_TOKEN`; public releases need neither):

```powershell
python tools/build/fetch_native.py all --platform host          # add --check to just verify
```

If a development preview reports `hsdrawviewer exited during startup`, check the viewer path and
native output in the launcher log. Streaming startup failures include a bounded stdout tail and stderr.

## Initial Setup (manual)

### Desktop bridge regression checks

Before packaging a preload change, run `node --test tests/electron/preload.test.js` (from the repo root)
and run `tools/ingame/preload-smoke.cjs` with the installed Electron executable. Clear
`ELECTRON_RUN_AS_NODE` first. The smoke test uses a hidden sandboxed window,
an isolated profile and a synthetic loopback backend to test the real frontend
API client; it does not start the Nucleus app or Flask. On Windows, wait for
the process with `Start-Process -Wait -WindowStyle Hidden` and set
`NUCLEUS_PRELOAD_SMOKE_RESULT` to a new JSON output path to capture its result.
The test reports its temporary profile for cleanup after the process exits.

Run `node tools/ingame/iso-import-smoke.cjs` for the Import picker and OS-file drop.
It launches a hidden Electron window with the real import components, disk-backed
Files and a synthetic scanner API. It checks full ISO/GCM paths, mixed ZIP imports,
and recovery from missing paths. `NUCLEUS_ISO_IMPORT_PRELOAD_PATH` can point at a
staged or extracted preload; Windows builds run this against the staged bridge.
File paths must use preload `webUtils.getPathForFile`, since `File.path` was
removed in Electron 32.

The production preload is loaded directly, without bundling. Keep it
self-contained: sandboxed `require()` cannot import local CommonJS modules.
Testing an extracted helper with Node does not verify that the preload loads.

### 1. Clone the Repository

Each release's source is published as one snapshot commit in
`ssbmNucleus/ssbmNucleus` (development history stays private); the app tree is
`app/`.

```bash
git clone https://github.com/ssbmNucleus/ssbmNucleus.git
cd ssbmNucleus
```

The steps below run from `app/` unless a path says otherwise; the repo root holds
`tools/`, `tests/`, `docs/` and `pytest.ini`.

### 2. Install Python Dependencies

Create a virtual environment and install Python packages:

```bash
cd app

# Create virtual environment
python -m venv venv

# Activate virtual environment (Windows)
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt        # add requirements-dev.txt for the test tools
```

### 3. Install Node Dependencies

Install npm packages for `app/` and `app/frontend/`:

```bash
# Install app dependencies (Electron), from app/
npm install

# Install frontend dependencies (React + Vite)
cd frontend
npm install
cd ..
```

### 4. Fetch MexCLI and HSDRawViewer

The pinned prebuilt builds (`mexcli.exe` with its `codes.gct`, and the 3D viewer
`HSDRawViewer.exe`) come from the fork repos' GitHub Releases:

```bash
python tools/build/fetch_native.py all --platform host   # from the repo root
```

`codes.gct` and `seed_codes.ini` arrive in the same zip as `mexcli`, so there is nothing to copy.
The viewer supports the `--embedded` flag, so it runs as a child process controlled by Electron.

## Running in Development Mode

The primary way to run the app is the root launcher:

```bash
tools\dev\run.bat
```

This starts two terminal windows (the Flask backend is spawned by Electron):
- **Vite Dev Server** - React frontend (http://localhost:3000 preferred; the port actually bound is recorded in `app/frontend/.vite-port`)
- **MEX Manager** - Electron desktop app (includes the Flask backend)

Alternatively, `tools\build\start.bat` is a minimal launcher that skips all
setup checks and opens three windows (Backend, Vite, Electron) directly. It first
stops this checkout's stale backend, Vite and Electron by PID through
`tools\build\stop_stale_dev.ps1` (`-DryRun` lists them), never by image name:

```bash
tools\build\start.bat
```

- **MEX Backend** - Flask API server (prefers port 5000, falls back to a free OS-assigned port)
- **Vite Dev Server** - React frontend (http://localhost:3000)
- **MEX Manager** - Electron desktop app

The backend port is dynamic: it tries 5000 first and falls back to a free
port; Electron picks up the actual port at startup.

### What Each Component Does

- **Backend (Flask)**: Python API server that handles file operations, ISO manipulation, and MEX integration
- **Vite Dev Server**: Hot-reloading React development server for the UI
- **Electron**: Desktop wrapper that loads the Vite server and manages native OS features

## Logs

Logs go to `app/logs/`:
- `dev-launch-<timestamp>-<pid>.log` - the `tools\dev\run.bat` launcher session
- `backend_YYYYMMDD_HHMMSS.log` - Backend log when started by `tools\dev\run_backend.bat` (the `start.bat` path)
- `mex_api_YYYYMMDD.log` - Daily backend API log (includes setup errors). Secret query values in its request lines,
  the session token among them, are written as `***` (`core/log_redaction.SecretQueryFilter`).

### Cleaning up

`tools\dev\clean.bat` (runs `tools/clean.py`) removes regenerable debris: `app/scratch/*`, `app/backend/artifacts`, `app/storage/test-runs/*`, `app/storage/test-builds/*`, `.tmp*` folders, `.pytest_cache` and `__pycache__` at the usual spots, old `app/SSBM Nucleus Setup*.exe`, loose `app/*.iso` and `app/ship-report.txt`. Anything git tracks is refused, and `app/storage` itself, `venv` and `node_modules` are never touched.

It is a dry run by default (lists paths and sizes). Run `tools\dev\clean.bat --yes` to delete.

### Running the tests

Every test lives under the repo-root `tests/`. Run each suite from where shown (counts as of 2026-10-03):

| Suite | Command | Tests |
|---|---|---:|
| Backend, fast set | `app/venv/Scripts/python -m pytest tests/backend` (repo root; about 4.5 minutes) | 7,624 |
| Backend, slow set | `app/venv/Scripts/python -m pytest tests/backend -m slow` (repo root) | 738 |
| Benchmarks' own tests | `app/venv/Scripts/python -m pytest tests/eval` (repo root) | 202 |
| Electron | `cd app && node --test ../tests/electron/*.test.js` (in PowerShell, expand the glob: `node --test (Get-ChildItem ../tests/electron/*.test.js).FullName`) | 111 |
| Frontend | `cd app/frontend && npm test` (the colocated `src/**/*.test.js`) | 542 |

The two Electron storage tests that run the backend's maintenance entry point use `NUCLEUS_TEST_PYTHON` when it is set and the checkout's `app/venv` Python otherwise; they skip only when neither exists.

### Test isolation (`tests/backend/conftest.py`)

pytest-xdist runs many test files in one worker process, and which files share a worker changes between runs, so process-wide state one test leaves behind fails a different test in a different run. Autouse fixtures in `conftest.py` reset it around every test:

- **Open project** (`open_project_is_per_test`): `core.state`'s open project and `MexManager` are restored when the test ends, and any menu-ref derivation thread the test started is waited for.
- **Workspace cache** (`nucleus_api_workspace_is_per_test`): `nucleus_api`'s cached workspace root is reset before and after, since pytest reuses a deleted `tmp_path`'s name.
- **Scratch** (`private_scratch`): `core.config.SCRATCH_PATH` points at a per-test folder under pytest's temp dir, never the shared `app/scratch`.

To open a project in a test, use the `open_project` fixture (`open_project(path)`), not `core.state.set_project_path`: `set_project_path` also starts the menu-ref derivation, which runs HSDRawViewer on the test project and publishes over the developer's real `app/utility/assets/menu_refs`.

### Fast vs slow tests

The fast set runs in parallel by default (`-n auto --dist loadfile`, one worker per core, each test file on one worker): about 4.5 minutes on this machine instead of 16. Add `-n 0` to run serially when debugging.

Backend tests that touch real game files, spawn subprocesses (MexCLI, HSDRaw, Blender, ffmpeg) or run the rig/fit pipeline carry `pytest.mark.slow` (module-level `pytestmark`, or on the single test).
The root `pytest.ini` sets `addopts = -m "not slow"`, so `pytest tests/backend` (or `python -m pytest tests/backend`) from the repo root runs the fast set only; this is the per-item gate.
Run the rest with `python -m pytest tests/backend -m slow`, and everything with `python -m pytest tests/backend -m "slow or not slow"`.
CI (`backend-tests.yml`) runs both sets as two steps. Mark any new test that needs real assets or a subprocess `slow`.
A slow test that skips without its tools (kits, Blender, vanilla files) still counts as slow, so the fast set never pays for loading them.


## First-Run Setup

When you first launch the app, you'll need to:
1. Select your vanilla Melee 1.02 ISO (auto-detected when possible)
2. Wait for asset extraction (~1-2 minutes)
3. The app will extract CSPs, stocks, and stage icons from the ISO

## Project Structure

```
<repo root>/
├── app/                  # what ships
│   ├── backend/          # Flask API server: app.py entry point; vault/, projects/, upload/, tracker/, randall/, shared/, core/, mexcli/
│   ├── electron/         # Electron main process: main.js (composition), preload.js, runtime/ storage/ viewers/ protocol/ updates/ shell/ ipc/
│   ├── frontend/         # React frontend (Vite): src/ = App.jsx shell + vault/, projects/, upload/, tracker/, randall/, settings/, setup/, shared/
│   ├── utility/          # manifests, assets and fetched tools
│   │   ├── mex/          # fetched MexCLI (git-ignored; tools/build/fetch_native.py)
│   │   ├── hsdraw/       # fetched HSDRawViewer (git-ignored)
│   │   └── assets/       # extracted vanilla assets
│   ├── storage/          # user's mod collection (git-ignored)
│   ├── logs/             # runtime and launcher logs (git-ignored)
│   └── venv/             # Python virtual environment (git-ignored)
├── tests/                # backend, electron, tools, eval and service tests
├── tools/                # dev/ (run.bat, launch.cjs), build/, admin/, ingame/, clean.py
├── docs/                 # dev/ (this tier), wiki/ (user docs)
└── research/             # findings and archived scripts
```

## Common Issues

### "ModuleNotFoundError: No module named 'flask'"

Make sure you activated the virtual environment and installed dependencies (from `app/`):
```bash
venv\Scripts\activate
pip install -r requirements.txt
```

### "codes.gct not found"

Re-run `python tools/build/fetch_native.py mex --force` (step 4 above); `codes.gct` ships in the MexCLI zip.

### Backend won't start

Check `app/logs/` (`mex_api_*.log`, or the `dev-launch-*.log` for the session) for errors. Make sure:
- Virtual environment is set up correctly
- All Python dependencies are installed

(The backend picks a free port automatically — port 5000 being in use is not
fatal, it just falls back to another port.)

### 3D Viewer doesn't connect / shows "FileNotFoundException: --embedded"

The fetched HSDRawViewer is stale or missing. Re-fetch the pinned build:
```bash
python tools/build/fetch_native.py hsdlib --force
```
Then restart the Electron app. You should see "Embedded mode detected" in the console when opening the 3D viewer.

## Development Tips

- **Hot Reload**: The Vite dev server will automatically reload when you edit frontend code
- **Backend Changes**: Close the app window and relaunch (`tools\dev\run.bat`); Electron starts the Flask backend. With `tools\build\start.bat`, restart the Backend window instead
- **Electron Changes**: Relaunch after editing anything under `app/electron/`

## Building for Production

See [RELEASE_PIPELINE.md](RELEASE_PIPELINE.md) and [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) for building and publishing installers.

## Additional Documentation

- [DOCUMENTATION.md](DOCUMENTATION.md) - How docs are organized + the ship checklist
- [ROADMAP.md](ROADMAP.md) - Feature roadmap and current status
- [MEX_INTEGRATION.md](MEX_INTEGRATION.md) - MEX framework integration details
- [RELEASE_PIPELINE.md](RELEASE_PIPELINE.md) - Building and packaging
