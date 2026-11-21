"""
menu_refs.py -- vanilla HUD / pause / series / stage-select reference art,
derived on the user's machine instead of shipped.

Four sets of retail imagery back the menu editors, Tracker and the stage panels
(docs/dev/VANILLA_ASSET_POLICY.md, `retail-hud-and-pause`, `retail-stage-art`):

  hud_vanilla     the IfAll slot manifests plus one preview PNG per editable
                  glyph (digits, %, HP, READY/GO!/GAME!...)
  pause_vanilla   the 11 GmPause textures, the base image set for per-texture
                  editing of picture-sourced mods
  series          the 16 vanilla m-ex series emblems
  vanilla_stages  each vanilla stage's stage-select icon and banner,
                  <code>_icon.png / <code>_banner.png

All four are exports of files the user already owns, and the app already ships
the tool that makes them. `HSDRawViewer --hud-textures export` on IfAll and
`--pause-screen export` on GmPause reproduce the PNGs and manifests that used to
ship byte-for-byte; the series emblems and stage pictures are plain PNGs a
`mexcli create` project writes into its own `assets/`. Deriving all four costs
about three seconds.

**Source must be a MEX project, not the raw disc.** m-ex adds an
`Eblm_matanim_joint` root to IfAll, so a project's export has 1349 slots where
the disc's has 1333 -- and `percent._build_replacement_spec` maps a mod's slots
onto *global* texture indices in the project's IfAll. A manifest derived from
the raw ISO would describe a file the app never writes to. First-run setup has
the freshly-created project in hand, which is where this runs.

Self-healing: opening a project (core.state.set_project_path) derives the sets
that are still missing -- installs that predate a set, or a setup pass that
failed -- and only those, so a set already taken from setup's fresh project is
never overwritten from a modded one. App start does the same from the known
vanilla ISO (derive_missing_at_start), so an upgraded install has its Tracker
stage icons without opening a project: from the pristine test base when one is
built, else from a temporary `mexcli create` project it deletes afterwards.

No pictures ship (owner, 2026-11-19: nothing that can be made from the game
ships in the desktop app). `pause_dir()`, `series_dir()` and `stage_art_path()`
answer from the derived copies only; until a set exists its callers find
nothing and say so. `hud_dir()` is the one fallback: backend/assets/hud_vanilla
still ships the two IfAll slot manifests -- sizes, formats and a checksum per
slot, no imagery -- so installing a HUD mod never waits on derivation. Every
answer is resolved per call, so a derivation that lands mid-session is picked
up.
"""

import json
import logging
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import file_retry
from core.config import (
    BACKEND_ASSETS_DIR, HSDRAW_EXE, PROJECT_ROOT, get_subprocess_args,
)
from core.hud_words import group_slots

logger = logging.getLogger(__name__)

# Writable home for the derived copies, next to the other user-extracted vanilla
# assets (utility/assets/vanilla) rather than inside the read-only bundle.
MENU_REF_DIR = PROJECT_ROOT / "utility" / "assets" / "menu_refs"

MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1

HUD_SUBDIR = "hud_vanilla"
PAUSE_SUBDIR = "pause_vanilla"
SERIES_SUBDIR = "series"
STAGES_SUBDIR = "vanilla_stages"

# Every set derive_menu_refs knows, in the order it derives them.
SETS = ("pause", "hud", "series", "stages")

STAGE_ART_KINDS = ("icon", "banner")
_STAGE_CODE_RE = re.compile(r"^Gr[A-Za-z0-9]{1,6}$")

# The vanilla m-ex series list is 17 long but the last has no icon.
VANILLA_SERIES_COUNT = 17

_lock = threading.Lock()


# --------------------------------------------------------------------------
# resolution
# --------------------------------------------------------------------------

# The file whose presence means a set has been derived.
_MARKERS = {
    "hud": (HUD_SUBDIR, "manifest_usd.json"),
    "pause": (PAUSE_SUBDIR, MANIFEST_NAME),
    "series": (SERIES_SUBDIR, "icon_0.png"),
    "stages": (STAGES_SUBDIR, MANIFEST_NAME),
}


def _derived(key: str) -> bool:
    subdir, marker = _MARKERS[key]
    try:
        return (MENU_REF_DIR / subdir / marker).is_file()
    except OSError:
        return False


def hud_dir() -> Path:
    """The derived HUD set (manifests and glyph previews) when it exists, else
    the shipped manifests alone: backend/assets/hud_vanilla has no pictures."""
    if _derived("hud"):
        return MENU_REF_DIR / HUD_SUBDIR
    return BACKEND_ASSETS_DIR / HUD_SUBDIR


def pause_dir() -> Path:
    """The derived GmPause textures. Nothing ships: before derivation the
    directory does not exist and the pause editor has no vanilla base."""
    return MENU_REF_DIR / PAUSE_SUBDIR


def series_dir() -> Path:
    """The derived vanilla series emblems. Nothing ships."""
    return MENU_REF_DIR / SERIES_SUBDIR


def stage_art_dir() -> Path:
    return MENU_REF_DIR / STAGES_SUBDIR


def stage_art_path(code, kind):
    """The derived stage-select picture for vanilla stage `code` ("GrCs"),
    `kind` "icon" or "banner"; None when it has not been derived. Nothing is
    bundled to fall back on."""
    if kind not in STAGE_ART_KINDS or not isinstance(code, str) \
            or not _STAGE_CODE_RE.match(code):
        return None
    path = stage_art_dir() / f"{code}_{kind}.png"
    try:
        return path if path.is_file() else None
    except OSError:
        return None


def menu_ref_status() -> dict:
    """Whether each set has been derived, for setup health reporting."""
    return {"path": str(MENU_REF_DIR), **{key: _derived(key) for key in SETS}}


def missing_sets() -> list:
    """The sets not derived yet, in derivation order."""
    status = menu_ref_status()
    return [key for key in SETS if not status.get(key)]


# --------------------------------------------------------------------------
# derivation
# --------------------------------------------------------------------------

def _run_hsd(args, timeout=300) -> bool:
    if not Path(HSDRAW_EXE).exists():
        logger.warning("[menu_refs] HSDRawViewer not found at %s", HSDRAW_EXE)
        return False
    try:
        result = subprocess.run(
            [str(HSDRAW_EXE), *args],
            capture_output=True, text=True, timeout=timeout,
            **get_subprocess_args()
        )
    except Exception as e:  # noqa: BLE001 - timeout, missing exe, permissions
        logger.warning("[menu_refs] HSDRawViewer %s failed to run: %s", args[0], e)
        return False
    if result.returncode != 0:
        logger.warning("[menu_refs] HSDRawViewer %s exit %d: %s",
                       args[0], result.returncode, (result.stderr or result.stdout)[-500:])
        return False
    return True


def _publish(out_dir: Path, name: str, data: bytes) -> None:
    """Write one file through a temp name so a reader never sees a partial."""
    destination = out_dir / name
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        file_retry.retry_locked(temporary.write_bytes, data)
        file_retry.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _derive_pause(files_dir: Path, out_dir: Path) -> int:
    """Export GmPause's 11 textures. Stored as t<index>.png plus a manifest
    keyed with `file`, the shape vault/routes/menus/pause.py already reads."""
    source = files_dir / "GmPause.usd"
    if not source.is_file():
        source = files_dir / "GmPause.dat"
    if not source.is_file():
        logger.warning("[menu_refs] no GmPause in %s", files_dir)
        return 0

    # A virus scanner can still hold a just-dumped PNG when the dump is
    # deleted; leftover scratch must not fail a derivation already published.
    with tempfile.TemporaryDirectory(prefix="pause_ref_",
                                     ignore_cleanup_errors=True) as tmp:
        dump = Path(tmp) / "dump"
        if not _run_hsd(["--pause-screen", "export", str(source), str(dump)]):
            return 0
        try:
            entries = json.loads((dump / MANIFEST_NAME).read_text(encoding="utf-8"))["textures"]
        except (OSError, ValueError, KeyError) as e:
            logger.warning("[menu_refs] unreadable pause manifest: %s", e)
            return 0

        out_dir.mkdir(parents=True, exist_ok=True)
        stored = []
        for entry in entries:
            png = dump / entry["filename"]
            if not png.is_file():
                continue
            name = f"t{entry['index']}.png"
            _publish(out_dir, name, png.read_bytes())
            stored.append({
                "index": entry["index"],
                "width": entry["width"],
                "height": entry["height"],
                "format": entry["format"],
                "file": name,
            })
        if not stored:
            return 0
        _publish(out_dir, MANIFEST_NAME,
                 (json.dumps({"textures": stored}, indent=2) + "\n").encode("utf-8"))
        return len(stored)


def _derive_hud(files_dir: Path, out_dir: Path) -> int:
    """Export both IfAll regions. Keeps each region's manifest verbatim -- the
    slot ordinals and global indices in it are what the install path maps
    against -- plus one preview PNG per editable glyph."""
    exported = 0
    out_dir.mkdir(parents=True, exist_ok=True)
    for region, filename in (("usd", "IfAll.usd"), ("dat", "IfAll.dat")):
        source = files_dir / filename
        if not source.is_file():
            logger.warning("[menu_refs] no %s in %s", filename, files_dir)
            continue
        # Same as _derive_pause: a scanner holding a dumped PNG must not
        # turn a cleanup failure into a failed derivation.
        with tempfile.TemporaryDirectory(prefix=f"hud_ref_{region}_",
                                         ignore_cleanup_errors=True) as tmp:
            dump = Path(tmp) / "dump"
            if not _run_hsd(["--hud-textures", "export", str(source), str(dump)]):
                continue
            try:
                manifest = (dump / MANIFEST_NAME).read_bytes()
                entries = json.loads(manifest.decode("utf-8"))["textures"]
            except (OSError, ValueError, KeyError) as e:
                logger.warning("[menu_refs] unreadable %s manifest: %s", region, e)
                continue
            _publish(out_dir, f"manifest_{region}.json", manifest)
            exported += 1

            # One preview per glyph, from the US file only: the editor shows
            # these as "what vanilla looks like", and the two regions differ
            # only in the localized word banners.
            if region != "usd":
                continue
            for key, slots in group_slots(entries).items():
                if not slots:
                    continue
                png = dump / slots[0]["filename"]
                if png.is_file():
                    _publish(out_dir, f"glyph_{key}.png", png.read_bytes())
    return exported


def _derive_series(project_dir: Path, out_dir: Path) -> int:
    """Copy the vanilla series emblems out of the project's own assets/."""
    series_json = project_dir / "data" / "series.json"
    assets_dir = project_dir / "assets"
    try:
        series_list = json.loads(series_json.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("[menu_refs] unreadable series.json: %s", e)
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for series_id, entry in enumerate(series_list[:VANILLA_SERIES_COUNT]):
        ref = (entry or {}).get("icon")
        if not ref:
            continue  # the last vanilla series genuinely has no icon
        icon = assets_dir / (ref.replace("\\", "/") + ".png")
        if not icon.is_file():
            continue
        _publish(out_dir, f"icon_{series_id}.png", icon.read_bytes())
        copied += 1
    return copied


def _stage_root_code(file_name) -> str:
    """'/GrCs.dat' -> 'GrCs'; '\\GrPs' -> 'GrPs' (Stadium's root has no extension)."""
    name = str(file_name or "").replace("\\", "/").lstrip("/")
    return name.rsplit("/", 1)[-1].split(".")[0]


def _derive_stages(project_dir: Path, out_dir: Path) -> int:
    """Copy each vanilla stage's stage-select icon and banner out of the
    project's own assets/. A stage's data/stages/<internal id>.json says which
    pictures it uses; the slot only counts while its root file is still that
    stage's, so a slot that holds some other stage gives nothing."""
    from core.stages import VS_STAGES

    stages_dir = project_dir / "data" / "stages"
    assets_dir = project_dir / "assets"
    found = {}
    copied = 0
    for stage in VS_STAGES:
        code = stage["code"]
        try:
            entry = json.loads((stages_dir / f"{stage['internal_id']:03d}.json")
                               .read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(entry, dict) or _stage_root_code(entry.get("fileName")) != code:
            continue
        refs = entry.get("assets") or {}
        for kind in STAGE_ART_KINDS:
            ref = refs.get(kind)
            if not ref:
                continue
            picture = assets_dir / (str(ref).replace("\\", "/") + ".png")
            if not picture.is_file():
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            _publish(out_dir, f"{code}_{kind}.png", picture.read_bytes())
            found.setdefault(code, []).append(kind)
            copied += 1
    if copied:
        # The manifest is the set's "derived" marker: written last, and only
        # when something was copied, so an empty pass is retried next time.
        _publish(out_dir, MANIFEST_NAME,
                 (json.dumps({"stages": found}, indent=2, sort_keys=True) + "\n")
                 .encode("utf-8"))
    return copied


def derive_menu_refs(project_dir, progress_callback=None, only=None) -> dict:
    """Derive the sets from a `mexcli create` project directory.

    `project_dir` is the project root -- the one holding `files/`, `data/` and
    `assets/`. `only` limits the pass to those set names (see SETS); the
    project-open and app-start repairs pass just the missing ones, and such a
    pass takes only the ones STILL missing once it holds the lock: another pass
    may have derived one meanwhile, and a derived set is never overwritten from
    a later source. Never raises: each set is independent and a failure just
    leaves that one missing.
    """
    project_dir = Path(project_dir)
    files_dir = project_dir / "files"
    wanted = set(SETS if only is None else only)
    result = {key: 0 for key in SETS}

    with _lock:
        try:
            MENU_REF_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("[menu_refs] cannot create %s: %s", MENU_REF_DIR, e)
            return result
        if only is not None:
            wanted &= set(missing_sets())

        steps = [step for step in (
            ("pause", lambda: _derive_pause(files_dir, MENU_REF_DIR / PAUSE_SUBDIR)),
            ("hud", lambda: _derive_hud(files_dir, MENU_REF_DIR / HUD_SUBDIR)),
            ("series", lambda: _derive_series(project_dir, MENU_REF_DIR / SERIES_SUBDIR)),
            ("stages", lambda: _derive_stages(project_dir, stage_art_dir())),
        ) if step[0] in wanted]
        for done, (key, step) in enumerate(steps):
            if progress_callback:
                progress_callback('deriving_menu_refs', int(100 * done / len(steps)),
                                  'Deriving menu reference art...', done, len(steps))
            try:
                result[key] = step()
            except Exception as e:  # noqa: BLE001 - one set must not sink the others
                logger.warning("[menu_refs] deriving %s failed: %s", key, e)

        # A partial pass (`only`) keeps the counts an earlier pass recorded.
        counts = {}
        try:
            previous = json.loads((MENU_REF_DIR / MANIFEST_NAME).read_text(encoding="utf-8"))
            counts = {key: previous[key] for key in SETS if isinstance(previous.get(key), int)}
        except (OSError, ValueError, AttributeError):
            pass
        counts.update({key: result[key] for key in wanted if key in result})
        try:
            _publish(MENU_REF_DIR, MANIFEST_NAME,
                     (json.dumps({"version": MANIFEST_VERSION,
                                  "source": "user-verified-iso", **counts},
                                 indent=2) + "\n").encode("utf-8"))
        except OSError:
            pass

    logger.info("[menu_refs] derived %d pause textures, %d IfAll manifests, "
                "%d series icons, %d stage pictures", result["pause"], result["hud"],
                result["series"], result["stages"])
    return result


# --------------------------------------------------------------------------
# app start: the missing sets, from the known vanilla ISO
# --------------------------------------------------------------------------

# What the last app-start pass was given and could not finish: the same ISO
# missing the same sets is not tried again at every start (a project open
# still is). Removed once nothing is missing.
ISO_ATTEMPT_NAME = ".iso_attempt.json"
TEMP_PREFIX = "nucleus_menu_refs_"
STARTUP_DELAY_SECONDS = 20          # let the window come up first
CREATE_TIMEOUT_SECONDS = 30 * 60
FREE_BYTES_NEEDED = 3 * 1024 ** 3   # the m-ex project of the ISO is about 1.4 GB
STALE_TEMP_SECONDS = 2 * 60 * 60    # a live pass ends well inside this


def _iso_attempt(iso, missing) -> dict:
    stat = Path(iso).stat()
    return {"iso": str(iso), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "missing": list(missing)}


def _last_iso_attempt():
    try:
        return json.loads((MENU_REF_DIR / ISO_ATTEMPT_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _record_iso_attempt(attempt) -> None:
    path = MENU_REF_DIR / ISO_ATTEMPT_NAME
    try:
        if attempt is None:
            path.unlink(missing_ok=True)
        else:
            MENU_REF_DIR.mkdir(parents=True, exist_ok=True)
            _publish(MENU_REF_DIR, ISO_ATTEMPT_NAME,
                     (json.dumps(attempt, indent=2) + "\n").encode("utf-8"))
    except OSError as e:
        logger.warning("[menu_refs] cannot record the ISO attempt: %s", e)


def _sweep_temp_projects() -> None:
    """Temporary projects a killed app left behind (about 1.4 GB each)."""
    now = time.time()
    for path in Path(tempfile.gettempdir()).glob(TEMP_PREFIX + "*"):
        try:
            if now - path.stat().st_mtime > STALE_TEMP_SECONDS:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            continue


def _mexcli_create(iso, dest: Path) -> bool:
    """`mexcli create` the ISO into dest; tied to this process, so an app exit
    cannot leave it running."""
    from core.child_procs import own
    from core.config import MEXCLI_PATH

    if not Path(MEXCLI_PATH).exists():
        logger.warning("[menu_refs] MexCLI not found at %s", MEXCLI_PATH)
        return False
    argv = [str(MEXCLI_PATH), "create", str(iso), str(dest), "menu_refs"]
    try:
        proc = own(subprocess.Popen(argv, cwd=str(dest.parent), stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    **get_subprocess_args()))
    except OSError as e:
        logger.warning("[menu_refs] mexcli create failed to start: %s", e)
        return False
    try:
        proc.wait(timeout=CREATE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)
        logger.warning("[menu_refs] mexcli create did not finish in %d minutes",
                       CREATE_TIMEOUT_SECONDS // 60)
        return False
    if proc.returncode != 0:
        logger.warning("[menu_refs] mexcli create exit %d", proc.returncode)
    return proc.returncode == 0


def _from_pristine_base(iso, missing):
    """Derive from the pristine test base when one is already built for this
    ISO (projects/install/pristine_base.py): no `create` needed. None when there
    is none, or a test build holds it."""
    try:
        from core.config import MEXCLI_PATH
        from projects.install import pristine_base
        from projects.install.test_build import PRISTINE_BASE_DIR
        with pristine_base.ready_base(iso, root=PRISTINE_BASE_DIR, mexcli=MEXCLI_PATH) as base:
            if base is None:
                return None
            logger.info("[menu_refs] deriving %s from the pristine test base", ", ".join(missing))
            return derive_menu_refs(base, only=missing)
    except Exception as e:  # noqa: BLE001 - fall back to a temporary project
        logger.warning("[menu_refs] pristine test base unusable: %s", e)
        return None


def _from_temp_project(iso, missing):
    """`mexcli create` a temporary project of the ISO, derive, delete it. None
    when there is no room for it (tried again at the next start)."""
    _sweep_temp_projects()
    try:
        free = shutil.disk_usage(tempfile.gettempdir()).free
    except OSError:
        return None
    if free < FREE_BYTES_NEEDED:
        logger.info("[menu_refs] not enough free space for a temporary project (%d MB free)",
                    free // (1024 * 1024))
        return None
    temp = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    try:
        logger.info("[menu_refs] deriving %s from a temporary project of %s",
                    ", ".join(missing), iso)
        if not _mexcli_create(iso, temp):
            return {key: 0 for key in SETS}
        return derive_menu_refs(temp, only=missing)
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def derive_missing_from_iso(iso=None):
    """Derive the sets still missing from the vanilla ISO (default: the one
    setup recorded). Returns derive_menu_refs' counts, or None when nothing was
    tried: nothing missing, no known ISO, this ISO already failed to give these
    sets, or no room for a temporary project. Never raises."""
    try:
        missing = missing_sets()
        if not missing:
            _record_iso_attempt(None)
            return None
        if iso is None:
            from shared.vanilla_extract.vanilla_refs import known_vanilla_iso
            iso = known_vanilla_iso()
        if iso is None or not Path(iso).is_file():
            return None
        if _last_iso_attempt() == _iso_attempt(iso, missing):
            return None
        result = _from_pristine_base(iso, missing)
        if result is None:
            result = _from_temp_project(iso, missing)
        if result is None:
            return None
        still = [key for key in missing if key in missing_sets()]
        _record_iso_attempt(_iso_attempt(iso, still) if still else None)
        return result
    except Exception as e:  # noqa: BLE001 - a missing set stays missing
        logger.warning("[menu_refs] app-start derivation failed: %s", e)
        return None


def derive_missing_at_start(delay=STARTUP_DELAY_SECONDS):
    """App start: derive_missing_from_iso on a background thread, after `delay`
    seconds. Returns the thread, or None when nothing is missing."""
    if not missing_sets():
        return None

    def _run():
        time.sleep(delay)
        derive_missing_from_iso()

    thread = threading.Thread(target=_run, name="menu-refs-startup", daemon=True)
    thread.start()
    return thread
