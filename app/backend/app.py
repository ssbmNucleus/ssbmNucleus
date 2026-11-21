"""
The backend's bootstrap: the one entry point Electron starts (dev:
`python backend/app.py`; packaged: the PyInstaller exe `mex_backend` built from
this file).

In order: process guards (freeze_support, safe stdio, the storage-maintenance
and build-smoke dispatches, both of which exit before Flask), imports (core
configuration and every blueprint object), app creation with its hooks and
gates (backend token, CORS, socket auth), startup configuration (data dirs,
logging, feature switches, vault backend), the blueprint registry, launch side
effects, shutdown handlers, main (port pick, the BACKEND_PORT line, run).
Routes live in the areas' routes/ packages; nothing here serves a URL.
"""

import multiprocessing
import os
import sys
import socket
import signal
import atexit
import hmac
import logging
import re
import secrets
from urllib.parse import urlparse
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler

# MUST be the first thing that runs in a frozen build, before any import that
# might touch multiprocessing.
#
# When a dependency creates a multiprocessing primitive, Python starts a
# resource_tracker child by re-executing sys.executable with `-c <tracker>`.
# In a PyInstaller build sys.executable IS this app, and it ignores `-c` --
# so instead of a tracker you get a SECOND WHOLE BACKEND, which boots, creates
# its own primitive, spawns another, and so on. That is a fork bomb: observed
# on macOS eating ~50 GB and wedging the machine.
#
# It bites wherever the start method is 'spawn' (macOS and Windows); Linux
# defaults to 'fork', which never re-executes, which is why it stayed hidden.
# freeze_support() makes the re-executed child recognise itself and run the
# tracker instead of restarting the app.
multiprocessing.freeze_support()

# CVE-2024-3220, fixed in CPython 3.13.18, which has no Windows build: on Windows
# mimetypes also reads its `knownfiles` (paths such as C:\etc\mime.types, which any
# local user can create), and Flask serves files with the types it guesses. Read
# the registry and the built-in table only, as 3.13.18 does. Before any import
# can call mimetypes.init().
if sys.platform == 'win32':
    import mimetypes
    mimetypes.knownfiles = []

# --- Safe stdout/stderr for PyInstaller GUI-mode or broken pipes ---
def _safe_stream(stream):
    """Return the stream if it's usable, otherwise open os.devnull."""
    if stream is None:
        return open(os.devnull, "w")
    try:
        stream.fileno()
        return stream
    except (OSError, AttributeError):
        return open(os.devnull, "w")

sys.stdout = _safe_stream(sys.stdout)
sys.stderr = _safe_stream(sys.stderr)
# -------------------------------------------------------------------

# Storage maintenance must not import Flask/core, open the live Vault or start
# watchers. Its standalone stdlib worker snapshots databases before normal boot.
if '--storage-maintenance' in sys.argv[1:]:
    from storage_relocation import main as _storage_maintenance_main
    raise SystemExit(_storage_maintenance_main(sys.argv[sys.argv.index('--storage-maintenance') + 1:]))

# The frozen build's self-check (core/build_smoke.py): build.bat, build-linux.sh
# and build-macos.sh run the packaged exe with this flag. It imports the packaged
# tools, then exits before anything below imports Flask.
if "--build-smoke-test" in sys.argv[1:]:
    try:
        from core.build_smoke import run_build_smoke_test
        run_build_smoke_test()
    except Exception as exc:  # noqa: BLE001 - this is a build-gate diagnostic
        print(f"Build smoke test failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    raise SystemExit(0)

# --- Imports: Flask, core configuration, every blueprint object ---
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_socketio import SocketIO

# Import core configuration
from core.config import (
    PROJECT_ROOT, STORAGE_PATH, LOGS_PATH, MEXCLI_PATH,
    MEX_PROJECT_PATH, HSDRAW_EXE
)
from core.state import set_socketio
from core.helpers import cleanup_output_folder, migrate_legacy_character_names, backfill_dat_hashes

# Import every blueprint object, in the order they were always imported
# (each module from the area that owns it; registration order is below).
# A gated feature (core/gates.py) is imported only while its gate is open: a
# stable build does not carry that code at all (tools/build/mex_backend.spec
# leaves the packages out), so an unconditional import would stop the backend.
# A closed gate's routes are simply never registered, which 404s them.
from core import gates as _gates
from core.log_redaction import SecretQueryFilter
from shared.routes.assets import assets_bp
from shared.routes.legal import legal_bp
from shared.routes.account import account_bp
from shared.routes.jobs import jobs_bp
# POST /api/mcp: the user's own AI (MCP). Always registered; it says so itself when the
# assistant gate is closed, and imports randall.mcp only behind that gate.
from shared.routes.mcp import mcp_bp
from projects.routes.project import project_bp
from projects.routes.costumes import costumes_bp
from projects.routes.export import export_bp
from vault.routes.storage_costumes import storage_costumes_bp
from vault.routes.storage_stages import storage_stages_bp
from vault.routes.vault_backup import vault_backup_bp
from projects.routes.mod_export import mod_export_bp
from vault.routes.import_unified import import_bp
from vault.routes.das import das_bp
from projects.routes.stage_slots import stage_slots_bp
from vault.routes.poses import poses_bp
from shared.routes.setup import setup_bp
from shared.routes.slippi import slippi_bp
from vault.routes.xdelta import xdelta_bp
from vault.routes.bundles import bundles_bp
from shared.routes.viewer import viewer_bp
from vault.routes.iso_scan import iso_scan_bp
from vault.routes.menus import menus_bp
from vault.routes.custom_stages import custom_stages_bp
from vault.routes.climbers import climbers_bp
from vault.routes.custom_characters import custom_characters_bp
from vault.routes.character_sounds import character_sounds_bp
from projects.routes.music_playlists import music_playlists_bp
from projects.routes.test_in_game import test_in_game_bp
from upload.routes.publish import publish_bp
from vault.routes.gaw import gaw_bp
from tracker.routes.nucleome import nucleome_bp
if _gates.enabled('randall'):
    import randall.routes.coach  # noqa: F401  (adds the Randall coach's /coach/* routes to nucleome_bp)
combo_video_bp = None
if _gates.enabled('combo_video'):
    from tracker.routes.combo_video import combo_video_bp
from vault.routes.codes import codes_bp
from vault.routes.extras import extras_bp
from vault.extras.helpers import init_extras_api
assistant_bp = wishes_bp = chat_reports_bp = model_import_tools_bp = None
if _gates.enabled('assistant'):
    from randall.routes.assistant_bp import assistant_bp
    from randall.routes.wishes import wishes_bp
    from randall.routes.chat_reports import chat_reports_bp
    # the model import's downloadable tools (Settings card; registers its job kind before recover_interrupted)
    from randall.routes.model_import_tools import model_import_tools_bp
from vault.routes.stage_editor import stage_editor_bp
from core.state import get_project_files_dir

# --- App creation, hooks and gates (backend token, CORS, socket auth) ---
app = Flask(__name__)
_backend_token = os.environ.get("NUCLEUS_BACKEND_TOKEN", "").strip()
_generated_backend_token = not _backend_token
if _generated_backend_token:
    _backend_token = secrets.token_hex(32)


def _allowed_origin(origin):
    if origin in (None, "null", "file://"):
        return True
    parsed = urlparse(origin)
    return parsed.scheme in ("http", "https") and parsed.hostname in ("127.0.0.1", "localhost")


_LOCAL_CORS_ORIGINS = [
    re.compile(r"^https?://(?:127[.]0[.]0[.]1|localhost)(?::[0-9]+)?$"),
    "null",
    "file://",
]
CORS(app, resources={
    r"/api/*": {"origins": _LOCAL_CORS_ORIGINS},
    r"/vanilla/*": {"origins": _LOCAL_CORS_ORIGINS},
    r"/utility/*": {"origins": _LOCAL_CORS_ORIGINS},
    r"/storage/*": {"origins": _LOCAL_CORS_ORIGINS},
    r"/assets/*": {"origins": _LOCAL_CORS_ORIGINS},
}, allow_headers=["Content-Type", "X-Nucleus-Token", "X-Nucleus-Project"])

# Socket connections authenticate with the backend token, not a cloned Flask
# cookie session. Let Flask own its session; SocketIO's managed-session copy
# writes RequestContext.session, which is read-only in the pinned Flask version.
socketio = SocketIO(app, cors_allowed_origins=_allowed_origin,
                    async_mode='threading', manage_session=False)
set_socketio(socketio)


def _valid_backend_token(candidate):
    return isinstance(candidate, str) and hmac.compare_digest(candidate, _backend_token)


_PUBLIC_MEDIA_PREFIXES = (
    "/api/nucleome/stock/",
    "/api/nucleome/stage-icon/",
    "/api/nucleome/sprites/",
)


@app.before_request
def require_backend_token():
    if request.method == "OPTIONS" or not request.path.startswith("/api/"):
        return None
    if app.testing:
        return None
    if request.method in ("GET", "HEAD") and request.path.startswith(_PUBLIC_MEDIA_PREFIXES):
        return None
    candidate = request.headers.get("X-Nucleus-Token")
    if request.method in ("GET", "HEAD") and not candidate:
        candidate = request.args.get("_nucleus_token")
    if not _valid_backend_token(candidate):
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    return None


# One request sees one open project from start to end, and a request made for a
# project the window has since switched away from answers 409 project_changed
# (core/state.py, X-Nucleus-Project).
from core import state as _project_state
app.before_request(_project_state.pin_request_project)
app.after_request(_project_state.finish_project_check)
app.register_error_handler(_project_state.ProjectChanged, lambda error: (
    jsonify({"success": False, "code": "project_changed", "error": str(error)}), 409))


# The file routes outside /api (/storage, /vanilla, /utility, /assets) serve
# media without the token and everything else with it (databases never), and
# every request must name a loopback Host (no DNS rebinding). After SocketIO(app),
# so the Host check wraps /socket.io too. See shared/request_guard.py.
from shared import request_guard as _request_guard
_request_guard.install(app, _valid_backend_token)


@socketio.on("connect")
def authorize_socket(auth):
    if app.testing:
        return True
    token = auth.get("token") if isinstance(auth, dict) else None
    return _valid_backend_token(token)


@socketio.on('disconnect')
def handle_disconnect():
    """Handle WebSocket disconnection."""
    print('Client disconnected')


# --- Startup configuration: data dirs, logging, feature switches, vault backend ---
# Ensure directories exist
STORAGE_PATH.mkdir(exist_ok=True)
LOGS_PATH.mkdir(exist_ok=True)
MEX_PROJECT_PATH.parent.mkdir(exist_ok=True)

# Configure logging
log_file = LOGS_PATH / f"mex_api_{datetime.now().strftime('%Y%m%d')}.log"
LOG_HANDLERS = [
    RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5),
    logging.StreamHandler(sys.stdout)
]
# Secret query-string values (the session token media URLs carry, any *_key or *token) never reach the log file or
# stdout, which Electron echoes: blanked on both handlers as each line is written (0.9.0 smoke test).
for _handler in LOG_HANDLERS:
    _handler.addFilter(SecretQueryFilter())
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=LOG_HANDLERS
)
logger = logging.getLogger(__name__)

# The live feature switches, once, at startup, so a preview bug report says
# which were in force. The table is backend/core/gates.py.
logger.info("Feature switches: %s", _gates.policy_log_line())

# Clean up output folder on startup — but NOT when this process is a
# short-lived worker spawned by the running app (watch-with-mods). The sweep
# empties output/artifacts, which is where a finished export waits for the
# user's Save: a child doing it would throw away the parent's work.
if os.environ.get("NUCLEUS_WORKER") != "1":
    cleanup_output_folder()

# Initialize extras API with dependencies
init_extras_api(STORAGE_PATH, get_project_files_dir, HSDRAW_EXE)

# Vault storage backend: when the SQLite backend is selected (NUCLEUS_VAULT_DB),
# make sure the DB is built from metadata.json before serving — otherwise the
# vault would read as empty. On any failure, fall back to JSON so the user is
# never blocked or shown a blank vault. Default (json) mode is a no-op.
import core.config as _core_config
from core import vault as _vault_store
if _core_config.VAULT_BACKEND == 'db':
    try:
        _result = _vault_store.ensure_migrated()
        logger.info("Vault DB backend ready: %s", _result)
    except Exception as _e:
        logger.error("Vault DB migration failed; falling back to JSON backend: %s", _e, exc_info=True)
        _core_config.VAULT_BACKEND = 'json'

# --- Blueprint registry ---
app.register_blueprint(extras_bp)
app.register_blueprint(assets_bp)
app.register_blueprint(legal_bp)
app.register_blueprint(project_bp)
app.register_blueprint(costumes_bp)
app.register_blueprint(export_bp)
app.register_blueprint(storage_costumes_bp)
app.register_blueprint(storage_stages_bp)
app.register_blueprint(vault_backup_bp)
app.register_blueprint(mod_export_bp)
app.register_blueprint(import_bp)
app.register_blueprint(das_bp)
app.register_blueprint(stage_slots_bp)
app.register_blueprint(poses_bp)
app.register_blueprint(setup_bp)
app.register_blueprint(slippi_bp)
app.register_blueprint(xdelta_bp)
app.register_blueprint(bundles_bp)
app.register_blueprint(viewer_bp)
app.register_blueprint(iso_scan_bp)
app.register_blueprint(menus_bp)
app.register_blueprint(custom_stages_bp)
app.register_blueprint(custom_characters_bp)
app.register_blueprint(climbers_bp)
app.register_blueprint(character_sounds_bp)
app.register_blueprint(music_playlists_bp)
app.register_blueprint(nucleome_bp)
if combo_video_bp is not None:
    app.register_blueprint(combo_video_bp)
app.register_blueprint(test_in_game_bp)
app.register_blueprint(publish_bp)
app.register_blueprint(account_bp)
app.register_blueprint(gaw_bp)
app.register_blueprint(codes_bp)
app.register_blueprint(stage_editor_bp)
if assistant_bp is not None:
    app.register_blueprint(assistant_bp)
    app.register_blueprint(wishes_bp)
    app.register_blueprint(chat_reports_bp)
    app.register_blueprint(model_import_tools_bp)
app.register_blueprint(jobs_bp)
app.register_blueprint(mcp_bp)

# --- Launch side effects ---
# Multiprocessing 'spawn' children re-import this module as __mp_main__ —
# the vault-sync derive pool does exactly that on every worker start. Launch
# side effects MUST NOT run there: a child that calls maybe_autostart()
# starts its own sync, whose derive pool spawns another child, forever — a
# one-full-CPU-process-every-few-seconds chain that saturates the machine
# (hit live 2026-08-17, ~90 runaway backends). freeze_support() cannot catch
# this: it only intercepts the FROZEN build's re-exec, not the dev spawn
# bootstrap, which re-imports the parent's main module by design.
_IS_MP_SPAWN_CHILD = (__name__ == '__mp_main__')

if not _IS_MP_SPAWN_CHILD:

    # Launch chores the user opted into (replay index -> combos -> vault
    # push), in one background thread. A no-op unless the kv flags are set,
    # and it swallows everything: an unreadable replay folder or a dead vault
    # token must cost an out-of-date index, never a backend that fails to
    # start.
    from tracker.cloud.vault_jobs import maybe_autostart  # noqa: E402
    maybe_autostart()


# --- Shutdown and main ---
def cleanup_on_exit():
    """Cleanup function called on exit."""
    logger.info("Cleaning up MEX API Backend...")

    # every owned child (CSP pool, sessions, workers)
    from core.child_procs import sweep
    sweep()
    # the 3D viewer's folders this backend made (the shutdown route does the same)
    try:
        from shared.routes.viewer import remove_own_viewer_folders
        remove_own_viewer_folders()
    except Exception:  # noqa: BLE001 - swept at the next start
        logger.warning("Viewer folders not removed", exc_info=True)

    logger.info("MEX API Backend shutdown complete")


def signal_handler(sig, frame):
    """Handle termination signals."""
    logger.info(f"Received signal {sig}")
    cleanup_on_exit()
    sys.exit(0)


def find_free_port(preferred=5000):
    """Try the preferred port first; fall back to an OS-assigned free port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(('127.0.0.1', preferred))
        sock.close()
        return preferred
    except OSError:
        sock.close()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        sock.close()
        return port


if __name__ == '__main__':
    print(f"Starting MEX API Backend...")
    print(f"MexCLI: {MEXCLI_PATH}")
    print(f"Default Project: {MEX_PROJECT_PATH}")
    print(f"Storage: {STORAGE_PATH}")

    # Verify dependencies and warn if missing — never exit, so Vault/Settings
    # tabs still work and the user sees a real connection (not a dead backend).
    _missing_deps = []
    if not MEXCLI_PATH.exists():
        _missing_deps.append(f"MexCLI not found at {MEXCLI_PATH} (Install tab will not work)")
    if not HSDRAW_EXE.exists():
        _missing_deps.append(f"HSDRawViewer not found at {HSDRAW_EXE}")
    # Check xdelta3
    from projects.install.xdelta import get_xdelta_exe
    _xdelta = get_xdelta_exe()
    if isinstance(_xdelta, Path) and not _xdelta.exists():
        _missing_deps.append(f"xdelta3 not found at {_xdelta}")
    elif isinstance(_xdelta, str):
        import shutil
        if not shutil.which(_xdelta):
            _missing_deps.append(f"xdelta3 not found on system PATH")
    # Check UnRAR (.rar imports only)
    from core.rar_tools import rar_available, get_unrar_exe
    if not rar_available():
        _missing_deps.append(f"UnRAR not found at {get_unrar_exe()} (.rar imports will be refused)")
    if _missing_deps:
        for dep in _missing_deps:
            logger.warning(f"MISSING DEPENDENCY: {dep}")
        print(f"WARNING: {len(_missing_deps)} optional dependency(ies) missing. Some features may not work.")
        print("  " + "\n  ".join(_missing_deps))

    # MexCLI's export dies with this backend like every other helper.
    import mexcli.project as _mex_project
    from core.child_procs import own as _own_child
    _mex_project.on_spawn = _own_child

    # Register cleanup handlers
    atexit.register(cleanup_on_exit)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    if hasattr(signal, 'SIGBREAK'):
        # Windows-specific signal
        signal.signal(signal.SIGBREAK, signal_handler)

    # Run migration for legacy character names
    print("Checking for legacy character names to migrate...")
    migrate_legacy_character_names()

    # Backfill dat_hash for duplicate detection
    print("Checking for skins missing dat_hash...")
    backfill_dat_hashes()

    # Jobs the last run died in (a crash, a forced quit): mark them interrupted
    # and undo what they owned before anything new starts (core/jobs.py). Not
    # in a worker child, which shares output/ with the app that spawned it.
    if os.environ.get("NUCLEUS_WORKER") != "1":
        from core import jobs as _jobs
        for _record in _jobs.recover_interrupted():
            print(f"Recovered interrupted job: {_record.get('label')} ({_record.get('id')})")
        # What earlier runs left in the data scratch: the 3D viewer's folders (costumes and the
        # workbench's checkpoint copies, shared/routes/viewer.py), and the portrait renderer's debug
        # logs over a few days old or beyond the newest few dozen (processor/csp_logs.py; a clean
        # render deletes its own). The model import's leftovers are swept below, with the assistant.
        try:
            from shared.routes.viewer import sweep_viewer_folders
            _swept = sweep_viewer_folders()
            if _swept:
                print(f"Removed {_swept} 3D viewer folders an earlier run left")
        except Exception as _exc:  # noqa: BLE001 - never blocks startup
            print(f"WARNING: viewer folder sweep failed: {_exc}")
        try:
            import csp_logs as _csp_logs
            _swept = _csp_logs.sweep(_core_config.SCRATCH_PATH)
            if _swept:
                print(f"Removed {_swept} old portrait renderer logs from scratch")
        except Exception as _exc:  # noqa: BLE001 - never blocks startup
            print(f"WARNING: renderer log sweep failed: {_exc}")
        # Randall tasks a dead process left running: close them as interrupted.
        # Only where the assistant exists; a stable build has no randall package.
        if _gates.enabled('assistant'):
            try:
                from randall.assistant.tasks import coordinator as _tasks
                for _task in _tasks.resume_pending():
                    print(f"Closed interrupted Randall task {_task['task_id']}")
            except Exception as _exc:  # noqa: BLE001 - never blocks startup
                print(f"WARNING: Randall task recovery failed: {_exc}")
            # What model imports of earlier runs left in the data scratch: their temp
            # folders (a backend that died mid-import), and from before those, rigswap's and
            # Blender's own loose temp files (randall/model_import/chat/rigswap_temp.py).
            try:
                from randall.model_import.chat import rigswap_temp as _rigswap_temp
                _swept = _rigswap_temp.sweep(_core_config.SCRATCH_PATH)
                if _swept:
                    print(f"Removed {_swept} model import temp leftovers from scratch")
            except Exception as _exc:  # noqa: BLE001 - never blocks startup
                print(f"WARNING: model import temp sweep failed: {_exc}")

        # Vanilla reference art (stage icons, HUD, pause, series) still missing,
        # e.g. after an upgrade that added a set: derive it from the known
        # vanilla ISO in the background, not only when a project is opened.
        try:
            from shared.vanilla_extract.menu_refs import derive_missing_at_start
            derive_missing_at_start()
        except Exception as _exc:  # noqa: BLE001 - never blocks startup
            print(f"WARNING: menu reference derivation did not start: {_exc}")
        # The CSS/SSS layout editors' backdrops, rendered from the vanilla
        # MnSlChr/MnSlMap when missing or stale (menu_backdrops).
        try:
            from shared.vanilla_extract.menu_backdrops import warm_at_start
            warm_at_start()
        except Exception as _exc:  # noqa: BLE001 - never blocks startup
            print(f"WARNING: menu backdrop rendering did not start: {_exc}")

    # No auto-loading - user must select a project
    print(f"INFO: MEX Manager ready. Please open a project to get started.")

    # Pick a free port (prefer 5000, fall back to OS-assigned)
    port = find_free_port(preferred=5000)
    # Electron parses this line to discover the backend port
    print(f"BACKEND_PORT:{port}", flush=True)
    if _generated_backend_token:
        print(f"BACKEND_TOKEN:{_backend_token}", flush=True)
    # Also write to stderr as a fallback so Electron can find the port
    # even if stdout is piped/broken
    sys.stderr.write(f"BACKEND_PORT:{port}\n")
    sys.stderr.flush()

    # Run the Flask app
    # allow_unsafe_werkzeug: Flask-SocketIO refuses to start when stdin is not
    # a TTY (it assumes production). The Electron-spawned backend has no TTY on
    # Linux; Windows only escapes the check because the frozen build keeps a
    # console. This server is loopback-only by design.
    debug_enabled = os.environ.get("NUCLEUS_BACKEND_DEBUG") == "1"
    socketio.run(app, host='127.0.0.1', port=port, debug=debug_enabled, use_reloader=False,
                 allow_unsafe_werkzeug=True)
