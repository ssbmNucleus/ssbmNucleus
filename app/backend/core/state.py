"""
Global state management for the MEX API backend.

Contains mutable global state (mex_manager, project paths, viewer process)
and functions to access/modify them safely.
"""

from pathlib import Path
import sys
import logging
import threading

from .config import PROJECT_ROOT

# metadata_lock now lives in core.metadata (next to the data it guards) so the
# DAL can offer a locked metadata_transaction(). Re-exported here because many
# blueprints still do `from core.state import metadata_lock` — keep that working.
from .metadata import metadata_lock  # noqa: F401  (re-exported for back-compat)

# Serializes operations that open + save the MexManager workspace (reorder,
# import, remove, set-team-color, export). Two MexCLI processes touching the
# same project concurrently corrupt the workspace, so these are mutually
# exclusive. This matters now that costume reordering applies in the BACKGROUND
# (optimistic UI): while a background reorder is mid-save, any other workspace
# write (e.g. the user hitting Export) must wait for it instead of racing it.
# RLock so a single request thread can nest acquisitions safely.
mexcli_lock = threading.RLock()

from mexcli.project import MexManager, MexManagerError

from .config import MEXCLI_PATH

logger = logging.getLogger(__name__)

# Global MEX manager instance and current project path
_mex_manager = None
_current_project_path = None
# Goes up by one on every open, close and delete. The window sends the
# generation it is showing (PROJECT_HEADER), so a request made for a project
# that has since been switched away is refused instead of landing on the new one.
_generation = 0
_publish_lock = threading.Lock()

PROJECT_HEADER = 'X-Nucleus-Project'

# SocketIO instance (set by main app)
_socketio = None


def get_socketio():
    """Get the SocketIO instance."""
    return _socketio


def set_socketio(socketio):
    """Set the SocketIO instance."""
    global _socketio
    _socketio = socketio


class ProjectChanged(Exception):
    """The request was made for a project that is no longer the open one."""


def project_check_exempt(view):
    """Mark a route that reports or changes the open project (status, open,
    close, delete, list): it is how the window learns the new generation, so a
    stale header must not refuse it."""
    view.project_check_exempt = True
    return view


def _request_project():
    """The open project as this request sees it: pinned when the request began
    (pin_request_project), so one request never mixes two projects. Outside a
    request (worker threads, CLIs) it is the open project right now."""
    from flask import g, has_request_context
    if not has_request_context() or 'nucleus_project' not in g:
        return _current_project_path, _generation
    path, generation = g.nucleus_project
    _check_requested_generation(generation)
    return path, generation


def _check_requested_generation(generation):
    from flask import current_app, g, request
    wanted = request.headers.get(PROJECT_HEADER)
    if not wanted or g.get('nucleus_project_set_here'):
        return
    view = current_app.view_functions.get(request.endpoint)
    if getattr(view, 'project_check_exempt', False):
        return
    if wanted != str(generation):
        # Routes catch Exception and answer 500 themselves; this flag lets
        # finish_project_check turn whatever they answered into the 409.
        g.nucleus_project_changed = True
        raise ProjectChanged('The open project changed while this was in progress. Nothing was changed.')


def pin_request_project():
    """before_request: fix the open project for the rest of this request."""
    from flask import g
    g.nucleus_project = (_current_project_path, _generation)


def finish_project_check(response):
    """after_request: a request refused by ProjectChanged answers 409
    project_changed, however the route itself reported the exception."""
    from flask import g, jsonify
    if not g.get('nucleus_project_changed'):
        return response
    refused = jsonify({'success': False, 'code': 'project_changed',
                       'error': 'The open project changed while this was in progress. Nothing was changed.'})
    refused.status_code = 409
    return refused


def _publish(path, manager=None):
    """Replace the open project (None = closed) and bump the generation. A
    request that does this sees the new project for the rest of its run."""
    global _mex_manager, _current_project_path, _generation
    with _publish_lock:
        _current_project_path = Path(path) if path is not None else None
        _mex_manager = manager
        _generation += 1
        generation = _generation
    from flask import g, has_request_context
    if has_request_context():
        g.nucleus_project = (_current_project_path, generation)
        g.nucleus_project_set_here = True
    return generation


def get_project_generation():
    """The generation of the open project as this request sees it."""
    return _request_project()[1]


def get_current_project_path():
    """Get the current project path."""
    return _request_project()[0]


def _same_project(a, b):
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return str(a) == str(b)


def get_mex_manager():
    """Get or initialize MEX manager instance."""
    global _mex_manager

    path = get_current_project_path()
    if path is None:
        raise Exception("No MEX project loaded. Please open a project first.")

    cached = _mex_manager
    if cached is not None and _same_project(cached.project_path, path):
        return cached
    try:
        manager = MexManager(cli_path=str(MEXCLI_PATH), project_path=str(path))
    except MexManagerError as e:
        raise Exception(f"Failed to initialize MexManager: {e}")
    with _publish_lock:
        # Cache it only while its project is still the open one: a manager built
        # for a project that was switched away meanwhile must not be handed to
        # requests for the new one.
        if _current_project_path is not None and _same_project(_current_project_path, path):
            _mex_manager = manager
    return manager


def set_project_path(path, manager=None):
    """Make ``path`` the open project; returns its generation.

    Callers that opened a manager to check the project first pass it in, so the
    project is never published before it is known to work.
    """
    generation = _publish(path, manager)

    # Opportunistically derive the vanilla reference art (HUD, pause, series
    # emblems, stage icons). It is retail imagery so nothing ships
    # (backend/shared/vanilla_extract/menu_refs.py); first-run setup derives
    # it, but installs made before a set existed have none. A project is the
    # only source -- and the pause/HUD editors need one loaded anyway, so this
    # fires exactly when the art is about to be wanted. Only the MISSING sets
    # are derived: this project may be modded, and a set already taken from
    # setup's fresh project must not be overwritten from it. Background,
    # idempotent, and silent: it is a repair path, not a feature.
    try:
        import threading
        from shared.vanilla_extract.menu_refs import derive_menu_refs, missing_sets

        missing = missing_sets()
        if missing:
            project_dir = _current_project_path.parent

            def _derive():
                try:
                    derive_menu_refs(project_dir, only=missing)
                except Exception:  # noqa: BLE001 - a missing set stays missing
                    pass

            threading.Thread(target=_derive, name='menu-refs-derive',
                             daemon=True).start()
    except Exception:  # noqa: BLE001
        pass
    return generation


def clear_project_path():
    """Clear the current project and reset manager state; returns the new generation."""
    return _publish(None)


def reload_mex_manager():
    """Force reload of MEX manager to pick up file changes."""
    global _mex_manager
    _mex_manager = None


def get_project_files_dir():
    """Get the files/ directory for the currently loaded project."""
    path = get_current_project_path()
    if path is None:
        raise Exception("No MEX project loaded. Please open a project first.")
    return Path(path).parent / "files"
