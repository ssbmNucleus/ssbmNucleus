"""A Skin Lab viewer session the BACKEND owns, with no UI state attached.

The other place that opens a viewer cannot be borrowed by library code:
``randall/recolor/skin_lab.py`` keeps a registry of at most two agent sessions
keyed by conversation, so reading a costume's part map through it means reading
whatever costume that conversation happens to have open. (The Skin Creator's
module-global session, the other owner this was written beside, was removed
with the AI Skin/Stage Studio.)

So this module does the one thing a viewer owner has to do -- copy the DAT
somewhere private, start ``HSDRawViewer --stream`` on the copy, hand back the
session, close it afterwards -- and nothing else:

    with lab_session.open_costume(dat_path, character='Fox') as viewer:
        print(viewer.textures)

The copy matters: the viewer opens its file for writing, and the caller's DAT
(often a vault extract) must not be touched.
"""
import contextlib
import logging
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class LabSessionUnavailable(RuntimeError):
    """No viewer could be started (missing renderer, missing websocket, timeout)."""


def _viewer_assets(character):
    """Scene / animation / fighter-data files for a character, when present."""
    if not character:
        return {}
    try:
        from core.viewer_tools import find_aj_file, find_fighter_data_file, find_scene_file
    except Exception as exc:                        # a caller without the app's config
        logger.debug('[lab_session] no viewer asset lookup: %s', exc)
        return {}
    found = {}
    for key, finder in (('scene_file', find_scene_file), ('aj_file', find_aj_file),
                        ('data_file', find_fighter_data_file)):
        try:
            value = finder(character)
        except Exception:
            value = None
        if value:
            found[key] = value
    # the fighter-data file is positional behind the AJ and useless without it
    if 'aj_file' not in found:
        found.pop('data_file', None)
    return found


def _free_port():
    try:
        from core.viewer_tools import find_available_port
        return find_available_port()
    except Exception:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('localhost', 0))
        port = sock.getsockname()[1]
        sock.close()
        return port


@contextlib.contextmanager
def open_costume(path, character=None, startup_timeout=40.0):
    """Open a private viewer session on a COPY of one costume DAT.

    Args:
        path: the .dat/.usd to read. Never modified, never opened in place.
        character: fighter name, so the viewer can load the matching scene,
            animation archive and fighter-data file. Optional.
        startup_timeout: seconds to wait for the renderer.

    Yields:
        shared.rendering.session.ViewerSession

    Raises:
        LabSessionUnavailable: the renderer could not be started.
    """
    from core import config
    from shared.rendering.session import ViewerSession, ViewerSessionError

    source = Path(path)
    scratch = tempfile.TemporaryDirectory(prefix='part-identity-')
    viewer = None
    try:
        private = Path(scratch.name) / source.name
        shutil.copyfile(source, private)
        try:
            viewer = ViewerSession(config.HSDRAW_EXE, _free_port(), private,
                                   logs_path=config.LOGS_PATH,
                                   subprocess_kwargs=config.get_subprocess_args(),
                                   startup_timeout=startup_timeout,
                                   **_viewer_assets(character))
        except (ViewerSessionError, OSError) as exc:
            raise LabSessionUnavailable(str(exc)) from exc
        yield viewer
    finally:
        if viewer is not None:
            try:
                viewer.close()
            except Exception:
                logger.warning('[lab_session] viewer did not close cleanly', exc_info=True)
        scratch.cleanup()


def textures_and_masks(path, character=None, startup_timeout=40.0):
    """``(textures, uv_layout)`` from a private session, or ``None`` if unavailable.

    A convenience for callers that only need the live lists and would rather
    degrade to the offline map than fail.
    """
    try:
        with open_costume(path, character, startup_timeout) as viewer:
            try:
                layout = viewer.get_uv_layout()
            except Exception as exc:
                logger.warning('[lab_session] no UV layout: %s', exc)
                layout = []
            pixels = {}
            for texture in viewer.textures:
                try:
                    pixels[texture['index']] = viewer.get_full_texture(texture['index'])
                except Exception:
                    pass
            return list(viewer.textures), layout, pixels
    except Exception as exc:
        logger.warning('[lab_session] costume session unavailable: %s', exc)
        return None
