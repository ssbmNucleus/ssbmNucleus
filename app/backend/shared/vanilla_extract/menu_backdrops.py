"""
menu_backdrops.py -- the CSS and SSS layout editors' backdrops, rendered from
the user's own game instead of shipped.

The editors draw icons over a picture of the select screen as the game shows
it. Those pictures used to ship as css_template.png / sss_template.png, 640x527
screenshots of the running game. Nothing that can be made from the game ships
(owner, 2026-11-19), and since HSDLib v2026.11.19.1 the app's HSDRawViewer
draws the scene itself: `--menu-render` poses MnSlChr / MnSlMap at the
screen's idle state and renders it through the camera, lights and fog the file
defines (four closed doors and no icons on the CSS; the frame and background,
no icons, preview or stage name on the SSS). Text the game draws at run time,
such as the rules banner, is not part of the scene.

Source: the vanilla MnSlChr.usd / MnSlMap.usd, taken out of the recorded
vanilla ISO by vanilla_refs.ensure_vanilla_ref (one bounded read each; no
project needed). Cache: utility/assets/menu_refs/menu_backdrops/<screen>.png
beside a <screen>.json stamp naming the source's sha256 and RENDER_VERSION, so
another source or a renderer change renders again. A missing ISO, a missing
renderer or a failed render answers None -- the editors then draw a plain
background -- and a render that failed is not retried for the same source
until the app restarts.

backdrop_path() renders on demand (about two seconds a screen); app start warms
both in the background (warm_at_start) so the editors usually find them made.
"""

import hashlib
import json
import logging
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import file_retry
from core.config import HSDRAW_EXE, get_subprocess_args
from shared.vanilla_extract.menu_refs import MENU_REF_DIR

logger = logging.getLogger(__name__)

BACKDROP_DIR = MENU_REF_DIR / "menu_backdrops"

# screen -> the menu file it is rendered from
SCREENS = {"css": "MnSlChr.usd", "sss": "MnSlMap.usd"}

# Bump when the render itself changes (new --menu-render options, a renderer
# fix that changes the picture): every cached backdrop is then rendered again.
RENDER_VERSION = 1

RENDER_TIMEOUT_SECONDS = 120
STARTUP_DELAY_SECONDS = 25

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

_lock = threading.Lock()
_failed = set()      # (screen, source sha256) renders that failed this run
_sha_memo = {}       # (path, size, mtime_ns) -> sha256


def _source_file(screen):
    """The vanilla menu file for `screen`, extracted from the known ISO the
    first time; None when there is no ISO and no earlier extraction."""
    from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
    return ensure_vanilla_ref(SCREENS[screen])


def _sha256(path: Path) -> str:
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    digest = _sha_memo.get(key)
    if digest is None:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        _sha_memo[key] = digest
    return digest


def _stamp(source_sha) -> dict:
    return {"source_sha256": source_sha, "render_version": RENDER_VERSION}


def _cached(screen, source_sha):
    """The cached PNG when its stamp matches this source and renderer."""
    png = BACKDROP_DIR / f"{screen}.png"
    try:
        stamp = json.loads((BACKDROP_DIR / f"{screen}.json").read_text(encoding="utf-8"))
        if stamp == _stamp(source_sha) and png.is_file():
            return png
    except (OSError, ValueError):
        pass
    return None


def _publish(name: str, data: bytes) -> None:
    """Write one file through a temp name so a reader never sees a partial."""
    destination = BACKDROP_DIR / name
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        file_retry.retry_locked(temporary.write_bytes, data)
        file_retry.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _render(source: Path, out_png: Path) -> bool:
    """HSDRawViewer --menu-render (the mode flag comes first, so the viewer's
    window never opens). True when a PNG was written."""
    exe = Path(HSDRAW_EXE)
    if not exe.exists():
        logger.warning("[menu_backdrops] HSDRawViewer not found at %s", exe)
        return False
    try:
        result = subprocess.run(
            [str(exe), "--menu-render", str(source), str(out_png)],
            capture_output=True, text=True, timeout=RENDER_TIMEOUT_SECONDS,
            cwd=str(exe.parent), **get_subprocess_args())
    except Exception as e:  # noqa: BLE001 - timeout, permissions, missing runtime
        logger.warning("[menu_backdrops] --menu-render %s failed to run: %s", source.name, e)
        return False
    try:
        written = out_png.read_bytes()[:8] == _PNG_MAGIC
    except OSError:
        written = False
    if result.returncode != 0 or not written:
        logger.warning("[menu_backdrops] --menu-render %s exit %d: %s", source.name,
                       result.returncode, (result.stderr or result.stdout or "")[-500:])
        return False
    return True


def backdrop_path(screen, render=True):
    """The backdrop PNG for `screen` ("css" or "sss"), rendering it first when
    the cache is missing or stale and `render` is true. None when there is no
    source, the renderer is missing or the render failed. Never raises."""
    if screen not in SCREENS:
        return None
    try:
        source = _source_file(screen)
        if source is None:
            return None
        source = Path(source)
        source_sha = _sha256(source)
        cached = _cached(screen, source_sha)
        if cached is not None or not render:
            return cached
        with _lock:
            cached = _cached(screen, source_sha)   # another request rendered it
            if cached is not None:
                return cached
            if (screen, source_sha) in _failed:
                return None
            BACKDROP_DIR.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="menu_backdrop_",
                                             ignore_cleanup_errors=True) as tmp:
                out_png = Path(tmp) / f"{screen}.png"
                if not _render(source, out_png):
                    _failed.add((screen, source_sha))
                    return None
                _publish(f"{screen}.png", out_png.read_bytes())
            _publish(f"{screen}.json",
                     (json.dumps(_stamp(source_sha), indent=2) + "\n").encode("utf-8"))
            logger.info("[menu_backdrops] rendered the %s backdrop from %s", screen, source)
            return BACKDROP_DIR / f"{screen}.png"
    except Exception as e:  # noqa: BLE001 - the editor falls back to a plain background
        logger.warning("[menu_backdrops] %s backdrop unavailable: %s", screen, e)
        return None


def warm_at_start(delay=STARTUP_DELAY_SECONDS):
    """App start: render the backdrops that are missing or stale, on a
    background thread after `delay` seconds. Returns the thread."""
    def _run():
        time.sleep(delay)
        for screen in SCREENS:
            backdrop_path(screen)

    thread = threading.Thread(target=_run, name="menu-backdrops-startup", daemon=True)
    thread.start()
    return thread
