"""
test_build.py -- assemble a MINIMAL, FULLY THROWAWAY test ISO containing the
vanilla Melee base plus exactly ONE mod, for the per-mod "Test in game" feature.

Every build is fresh and self-contained: copy an untouched MEX project of the
user's vanilla ISO into a brand-new folder, install just the one mod, export a
throwaway ISO, and delete the whole project afterwards. The untouched project is
the pristine base (pristine_base.py): `mexcli create` runs once per vanilla ISO
and MexCLI, and the base is never written to, so a test can never be polluted by
a previous one. Each build uses its OWN MexManager instance, so it never touches
the user's currently-loaded project.

Supports four mod kinds:
  * costume          -> import-costume        (drive: fighter + costume index)
  * custom character -> add-fighter + place CSS icon  (drive: lock by CSS icon)
  * custom stage     -> add-stage + place SSS icon    (drive: select by SSS icon)
  * stage skin (DAS) -> DAS framework + variant behind a hold button
"""

import json
import logging
import contextvars
import re
import shutil
import time
import uuid
import zipfile
from pathlib import Path

import file_retry
from core.config import STORAGE_PATH, CUSTOM_CHARACTERS_PATH, BASE_PATH, MEXCLI_PATH
from core.stages import LEGAL_STAGE_CODES, STAGES_BY_CODE
from projects.install import pristine_base
from projects.install.das_loaders import install_das_loader

from mexcli.project import MexManager  # noqa: E402

logger = logging.getLogger(__name__)

TEST_BUILD_DIR = STORAGE_PATH / "test-builds"   # throwaway projects + ISOs
# The untouched project every test copies. Fixed to the real storage on purpose:
# a scratch vault (randall.model_import.studio.finish.vault_storage) repoints
# TEST_BUILD_DIR and still shares this read-only base.
PRISTINE_BASE_DIR = TEST_BUILD_DIR / "pristine-base"
# A proj_<id> folder this old was left by a build that never finished (an app
# exit or a crash): a build deletes its copy right after the export, minutes in.
STALE_PROJECT_SECONDS = 2 * 3600
_PROJECT_DIR = re.compile(r"proj_[0-9a-f]{12}")

# Where each step of a build sits on its 0-100 bar (what progress_cb gets).
# The one-time base build takes the first half; with a base in place a build
# starts at the copy.
BAR_BASE = (0, 50)
BAR_COPY = (50, 58)
BAR_INSTALL = 60
BAR_EXPORT = (62, 100)

CUSTOM_STAGES_PATH = STORAGE_PATH / "custom_stages"
DAS_STORAGE_PATH = STORAGE_PATH / "das"

# DAS stage code -> (storage folder, the stage name the in-game selector uses).
# Derived from core/stages.py; the selector key is shared.ingame.melee_sss.norm() of
# the display name (lower-case alphanumerics only).
DAS_STAGES = {
    code: (STAGES_BY_CODE[code]["folder"],
           "".join(ch for ch in STAGES_BY_CODE[code]["name"].lower() if ch.isalnum()))
    for code in LEGAL_STAGE_CODES
}


# Stop check for the build in progress (set by the test-in-game job around its
# build call). The base build, the base copy and the ISO export all poll it, so
# a Stop ends whichever is running instead of letting it finish first.
STOP_CHECK = contextvars.ContextVar('test_build_stop_check', default=None)


def _step(progress_cb, log, percentage, message):
    log(message)
    if progress_cb:
        progress_cb(percentage, message)


def _band(progress_cb, low, high):
    """progress_cb for one step: its own 0-100 mapped onto [low, high]."""
    if not progress_cb:
        return None
    return lambda percentage, message: progress_cb(
        low + (high - low) * max(0.0, min(100.0, percentage or 0)) / 100.0, message)


def _sweep_stale_projects(progress_cb):
    cutoff = time.time() - STALE_PROJECT_SECONDS
    try:
        stale = [entry for entry in TEST_BUILD_DIR.iterdir()
                 if _PROJECT_DIR.fullmatch(entry.name) and entry.is_dir()
                 and entry.stat().st_mtime < cutoff]
    except OSError:
        return
    if stale and progress_cb:
        progress_cb(BAR_BASE[0], "Removing old test files…")   # ~1.4 GB each
    for entry in stale:
        logger.info("removing abandoned test project %s", entry.name)
        shutil.rmtree(entry, ignore_errors=True)


def create_temp_project(vanilla_iso, log=lambda m: None, progress_cb=None):
    """A FRESH throwaway MEX project of the vanilla ISO: a copy of the pristine
    base, which is built from the ISO the first time (about three minutes) and
    never written to. Returns (proj_dir, project_file); the caller MUST delete
    proj_dir when done. Raises pristine_base.BuildStopped on a Stop."""
    if not vanilla_iso or not Path(vanilla_iso).exists():
        raise FileNotFoundError(
            f"Vanilla Melee ISO not found: {vanilla_iso}. Set it in Settings."
        )
    TEST_BUILD_DIR.mkdir(parents=True, exist_ok=True)
    _sweep_stale_projects(progress_cb)
    proj_dir = TEST_BUILD_DIR / f"proj_{uuid.uuid4().hex[:12]}"
    bands = {'wait': BAR_BASE, 'clean': BAR_BASE, 'base': BAR_BASE, 'copy': BAR_COPY}

    def progress(step, fraction, message):
        if progress_cb:
            low, high = bands[step]
            progress_cb(low + (high - low) * fraction, message)

    pristine_base.copy_fresh_project(
        vanilla_iso, proj_dir, root=PRISTINE_BASE_DIR, mexcli=MEXCLI_PATH,
        progress=progress, should_stop=STOP_CHECK.get(), log=log)
    proj = proj_dir / "project.mexproj"
    if not proj.exists():
        shutil.rmtree(proj_dir, ignore_errors=True)
        raise RuntimeError("the test base copy has no project.mexproj")
    return proj_dir, proj


# --------------------------------------------------------------------------- #
# CSS / SSS icon placement (ported from the harness build-modded-iso.js).       #
# m-ex's add-fighter / add-stage leave a new icon at the default (0,0) -- which  #
# is BELOW the roster grid (the port-panel zone), so in-game the cursor can't    #
# hover+lock it. Move it into a free, lockable grid slot and return the exact    #
# coordinate the runner drives.                                                  #
# --------------------------------------------------------------------------- #
def _r(v):
    return round(v or 0)


def place_custom_fighter_icon(mex, fighter_name):
    """Move the new fighter's CSS icon into a free roster slot; return
    {x, y, index, fighter} (cursor target is (x, y-3.5); index == in-game grid
    index; fighter == the EXTERNAL character id, used by the runner's cursor-free
    memory selection to pick this fighter without steering)."""
    layout = mex.get_css_layout()
    icons = layout.get("icons", []) or []
    if not icons:
        raise RuntimeError("CSS layout returned no icons")
    idx = next((i for i, ic in enumerate(icons) if (ic.get("fighterName") or "") == fighter_name), -1)
    if idx < 0:
        idx = next((i for i, ic in enumerate(icons) if _r(ic.get("x")) == 0 and _r(ic.get("y")) == 0), -1)
    if idx < 0:
        idx = len(icons) - 1
    # Free roster slots: the bottom-row empty edge cells, clear of the port panels.
    candidates = [(-28.15, 2.0, -1.0), (28.25, 2.0, -1.0),
                  (-28.15, 9.2, -1.0), (28.25, 9.2, -1.0),
                  (-28.15, 16.4, -1.0), (28.25, 16.4, -1.0)]
    occupied = set((_r(ic.get("x")), _r(ic.get("y"))) for i, ic in enumerate(icons) if i != idx)
    slot = next(((x, y, z) for (x, y, z) in candidates if (_r(x), _r(y)) not in occupied), candidates[0])
    # Capture the engine's EXTERNAL char id before mutating the icon (set_css_layout
    # round-trips the "fighter" field, so the placed icon keeps it).
    fighter_id = icons[idx].get("fighter")
    icons[idx] = {**icons[idx], "x": slot[0], "y": slot[1], "z": slot[2]}
    mex.set_css_layout(json.dumps({"template": layout.get("template"), "icons": icons}))
    return {"x": slot[0], "y": slot[1], "index": idx, "fighter": fighter_id}


def place_custom_stage_icon(mex, stage_name):
    """Move the new stage's SSS icon to a clear, reachable spot; return
    {page, x, y} (the page to R-switch to and the stage-cursor target)."""
    layout = mex.get_sss_layout()
    pages = layout.get("pages", []) or []
    if not pages:
        raise RuntimeError("SSS layout returned no pages")

    def icons_of(pg):
        return pg.get("icons") or pg.get("stageIcons") or []

    found = None
    for pi, pg in enumerate(pages):
        icons = icons_of(pg)
        ii = next((j for j, ic in enumerate(icons) if (ic.get("stageName") or "") == stage_name), -1)
        if ii < 0 and pi > 0:
            ii = next((j for j, ic in enumerate(icons) if _r(ic.get("x")) == 0 and _r(ic.get("y")) == 0), -1)
        if ii >= 0:
            found = (pi, ii)
            break
    if not found:
        raise RuntimeError(f"could not find the custom stage icon for '{stage_name}'")
    slot = (1.3, -9.1, 0.0)  # Battlefield's bottom-row position -- easy for the cursor
    icons = icons_of(pages[found[0]])
    # Capture the engine's INTERNAL stage id so the runner can force-select it
    # (no cursor / page navigation needed). Falls back to the placed coordinate if
    # absent or out of the signed-byte range.
    stage_id = icons[found[1]].get("stageID")
    icons[found[1]] = {**icons[found[1]], "x": slot[0], "y": slot[1], "z": slot[2]}
    mex.set_sss_layout(json.dumps({"pages": pages}))
    return {"page": found[0], "x": slot[0], "y": slot[1], "stageId": stage_id}


def _das_install_framework(files_dir, log=lambda m: None):
    """Port of projects/routes/das.py das_install: copy each vanilla stage to <code>/vanilla.dat
    and replace the root stage file with the DAS loader."""
    das_source = BASE_PATH / "utility" / "DynamicAlternateStages"
    if not das_source.exists():
        raise FileNotFoundError(f"DAS framework source not found at {das_source}")
    files_dir.mkdir(parents=True, exist_ok=True)
    for code in DAS_STAGES:
        root_ext = ".usd" if code == "GrPs" else ".dat"
        stage_folder = files_dir / code
        stage_folder.mkdir(exist_ok=True)
        original_stage = files_dir / f"{code}{root_ext}"
        loader_src = das_source / f"{code}{root_ext}"
        vanilla_in_folder = stage_folder / "vanilla.dat"
        if not vanilla_in_folder.exists() and original_stage.exists():
            shutil.copy2(original_stage, vanilla_in_folder)
        if not install_das_loader(code, files_dir, loader_dir=das_source):
            log(f"No DAS loader for {code}: {loader_src.name} is unavailable")
    log("DAS framework installed into the test project")


def _export(mex, out_iso, progress_cb, log):
    should_stop = STOP_CHECK.get()
    if should_stop and should_stop():
        from mexcli.project import MexExportCancelled
        raise MexExportCancelled("Test stopped before the ISO export started.")
    Path(out_iso).parent.mkdir(parents=True, exist_ok=True)
    # Bake Frame Speed Modifier data (fsm.txt) for installed custom
    # characters into the project's main.dol before the ISO is assembled.
    try:
        from projects.install.fsm_patcher import apply_project_fsm
        fsm_count = apply_project_fsm(mex.project_path, CUSTOM_CHARACTERS_PATH)
        if fsm_count:
            log(f"FSM: baked {fsm_count} frame-speed entries into main.dol")
    except Exception as e:
        log(f"FSM patching skipped: {e}")
    from vault.climbers import engine_code
    engine_code.ensure_for_export(mex.project_path)
    _step(progress_cb, log, BAR_EXPORT[0], "Exporting the test ISO…")
    mex.export_iso(str(out_iso), _band(progress_cb, *BAR_EXPORT), 1.0, False, False,
                   should_stop=should_stop)
    if not Path(out_iso).exists():
        raise RuntimeError("export did not produce an ISO")


# --------------------------------------------------------------------------- #
# Build functions -- each: fresh project -> install one mod -> export -> nuke.   #
# --------------------------------------------------------------------------- #
def build_single_costume_iso(vanilla_iso, character, skin_zip, out_iso,
                             nana_zip=None, progress_cb=None, log=lambda m: None):
    """Fresh project + the one costume (storage zip). Returns the in-game costume
    index (color slot) of the imported costume.

    `nana_zip`: an Ice Climbers skin is a Popo/Nana PAIR of zips -- `skin_zip`
    only re-skins Popo, so the caller passes the paired Nana zip and we import it
    to the separate Nana fighter (internal id 11; mexcli resolves a numeric id).
    Both imports append at the same slot index, which is how the engine pairs
    them in-game."""
    skin_zip = Path(skin_zip)
    if not skin_zip.exists():
        raise FileNotFoundError(f"Costume archive not found: {skin_zip}")
    proj_dir, proj = create_temp_project(vanilla_iso, log=log, progress_cb=progress_cb)
    try:
        mex = MexManager(str(MEXCLI_PATH), str(proj))
        _step(progress_cb, log, BAR_INSTALL, f"Importing the {character} costume…")
        imp = mex.import_costume(character, str(skin_zip))
        total = imp.get("totalCostumes")
        if total is None:
            fighter = mex.get_fighter_by_name(character)
            total = fighter.get("costumeCount") if fighter else None
        if not total:
            raise RuntimeError("could not determine the imported costume index")
        index = int(total) - 1
        if nana_zip:
            nana_zip = Path(nana_zip)
            if nana_zip.exists():
                log("Importing the paired Nana costume…")
                mex.import_costume("11", str(nana_zip))
            else:
                log(f"Paired Nana archive missing ({nana_zip}); testing Popo only")
        _export(mex, out_iso, progress_cb, log)
        return index
    finally:
        shutil.rmtree(proj_dir, ignore_errors=True)


def _pair_entry(slug):
    """The vault entry for slug if it is an Any Climbers pair, else None.

    A pair is stored as a recipe (two fighter names) rather than a baked
    fighter.zip, so a test build has to build one before it can add it.
    """
    try:
        from core.metadata import load_metadata
        data = load_metadata(default={}) or {}
        for entry in data.get("custom_characters", []):
            if entry.get("slug") == slug:
                return entry if entry.get("climbers") else None
    except Exception:
        logger.exception("could not read vault metadata for %s", slug)
    return None


def build_custom_character_iso(vanilla_iso, slug, out_iso, skin_zip=None,
                               costume_index=None, progress_cb=None, log=lambda m: None):
    """Fresh project + the one custom fighter (storage/custom_characters/<slug>/
    fighter.zip), placed into the CSS grid. Optionally targets a SPECIFIC skin:
    `skin_zip` (a vault custom-skin zip) is imported onto the fighter and its new
    slot selected, or `costume_index` picks one of the bundled costumes. Returns
    {name, cssIcon, colorIndex}."""
    zip_path = CUSTOM_CHARACTERS_PATH / slug / "fighter.zip"
    pair_entry = _pair_entry(slug)
    if not zip_path.exists() and pair_entry is None:
        raise FileNotFoundError(f"Custom character archive not found: {zip_path}")
    if skin_zip and not Path(skin_zip).exists():
        raise FileNotFoundError(f"Custom skin archive not found: {skin_zip}")
    proj_dir, proj = create_temp_project(vanilla_iso, log=log, progress_cb=progress_cb)
    try:
        if pair_entry is not None:
            # An Any Climbers pair is stored as a recipe, not a baked package --
            # only the install path materialized it, so testing one that had
            # never been installed died on the missing fighter.zip. Build it
            # against THIS temp project, and into the temp dir: the copy in the
            # vault (if any) was built against the user's real project and must
            # not be clobbered by a throwaway test build.
            from vault.climbers.pairs import materialize
            log("Building the Any Climbers pair…")
            zip_path = materialize(pair_entry, Path(proj_dir) / "_pair", proj)
        mex = MexManager(str(MEXCLI_PATH), str(proj))
        _step(progress_cb, log, BAR_INSTALL, f"Adding custom fighter '{slug}'…")
        res = mex._run_command("add-fighter", str(proj), str(zip_path))
        name = res.get("name") or slug
        color_index = int(costume_index or 0)
        if skin_zip:
            log("Importing the custom skin onto the fighter…")
            imp = mex.import_costume(name, str(skin_zip))
            total = imp.get("totalCostumes")
            if total is None:
                fighter = mex.get_fighter_by_name(name)
                total = fighter.get("costumeCount") if fighter else None
            if not total:
                raise RuntimeError("could not determine the imported costume index")
            color_index = int(total) - 1
        log(f"Placing {name} into the CSS grid…")
        css_icon = place_custom_fighter_icon(mex, name)
        _export(mex, out_iso, progress_cb, log)
        return {"name": name, "cssIcon": css_icon, "colorIndex": color_index}
    finally:
        shutil.rmtree(proj_dir, ignore_errors=True)


def build_custom_stage_iso(vanilla_iso, slug, out_iso, progress_cb=None, log=lambda m: None):
    """Fresh project + the one custom stage (storage/custom_stages/<slug>/
    stage.zip), placed on the SSS. Returns {name, sssIcon}."""
    zip_path = CUSTOM_STAGES_PATH / slug / "stage.zip"
    if not zip_path.exists():
        raise FileNotFoundError(f"Custom stage archive not found: {zip_path}")
    proj_dir, proj = create_temp_project(vanilla_iso, log=log, progress_cb=progress_cb)
    try:
        mex = MexManager(str(MEXCLI_PATH), str(proj))
        _step(progress_cb, log, BAR_INSTALL, f"Adding custom stage '{slug}'…")
        res = mex._run_command("add-stage", str(proj), str(zip_path))
        name = res.get("name") or slug
        log(f"Placing {name} on the stage-select screen…")
        sss_icon = place_custom_stage_icon(mex, name)
        _export(mex, out_iso, progress_cb, log)
        return {"name": name, "sssIcon": sss_icon}
    finally:
        shutil.rmtree(proj_dir, ignore_errors=True)


def build_stage_skin_iso(vanilla_iso, stage_code, stage_folder, variant_id, out_iso,
                         button="X", progress_cb=None, log=lambda m: None, *, default_variant=False):
    """Fresh project + the DAS framework + the one stage skin behind a HOLD button
    (storage/das/<stage_folder>/<variant_id>.zip). Returns {stage, button}.
    Manual previews use default_variant to load this skin without holding a
    button on the user's controller. Only the temporary project is changed.
    """
    if stage_code not in DAS_STAGES:
        raise ValueError(f"unknown DAS stage code: {stage_code}")
    variant_zip = DAS_STORAGE_PATH / stage_folder / f"{variant_id}.zip"
    if not variant_zip.exists():
        raise FileNotFoundError(f"Stage variant archive not found: {variant_zip}")
    button = (button or "X").upper()
    proj_dir, proj = create_temp_project(vanilla_iso, log=log, progress_cb=progress_cb)
    try:
        files_dir = proj_dir / "files"
        _step(progress_cb, log, BAR_INSTALL, "Installing the DAS framework…")
        _das_install_framework(files_dir, log=log)
        # Extract the variant's stage .dat and drop it in behind the hold button.
        with zipfile.ZipFile(variant_zip) as z:
            dat_name = next((n for n in z.namelist()
                             if n.lower().endswith(".dat") or n.lower().endswith(".usd")), None)
            if not dat_name:
                raise RuntimeError(f"no .dat/.usd inside {variant_zip}")
            data = z.read(dat_name)
        stage_dir = files_dir / stage_code
        stage_dir.mkdir(parents=True, exist_ok=True)
        target = 'vanilla.dat' if default_variant else f"NucleusTestSkin({button}).dat"
        file_retry.retry_locked((stage_dir / target).write_bytes, data)
        log(f"Placed the stage skin {'as the default' if default_variant else f'behind HOLD {button}'} "
            f"on {DAS_STAGES[stage_code][1]}")
        mex = MexManager(str(MEXCLI_PATH), str(proj))
        _export(mex, out_iso, progress_cb, log)
        return {"stage": DAS_STAGES[stage_code][1], "button": None if default_variant else button}
    finally:
        shutil.rmtree(proj_dir, ignore_errors=True)


def build_pause_mod_iso(vanilla_iso, mod_id, out_iso, progress_cb=None, log=lambda m: None):
    """Fresh project + ONE pause screen mod applied to GmPause.usd, for the
    in-game pause screenshot capture."""
    # Local import: the menus package owns the mod storage + the HSDRawViewer
    # spec plumbing (pause_install, its install engine -- not the route module).
    from vault.menus.pause_install import apply_pause_mod

    proj_dir, proj = create_temp_project(vanilla_iso, log=log, progress_cb=progress_cb)
    try:
        _step(progress_cb, log, BAR_INSTALL, "Applying the pause mod to GmPause.usd…")
        apply_pause_mod(mod_id, proj_dir / "files" / "GmPause.usd")
        mex = MexManager(str(MEXCLI_PATH), str(proj))
        _export(mex, out_iso, progress_cb, log)
    finally:
        shutil.rmtree(proj_dir, ignore_errors=True)


# Hold buttons that reliably trigger a DAS alternate during a memory-driven capture.
# VERIFIED over a 3-round stress test (each held button loads ITS OWN variant every
# round, all mutually distinct): X, Y, Z, L, R, B. R is safe even though it flips the
# SSS page in cursor mode -- force_stage_id is layout/page-independent, so the flip
# is a no-op. B is kept LAST (only the 6th variant in a stage uses it) since it's the
# "back out" button -- it tested clean but is the riskiest. EXCLUDED: A -- it's the
# stage-select confirm, so holding it triggers a cursor pick -> RANDOM alternate
# (measured flaky). So one ISO holds up to 6 variants of a base stage; a stage with
# more needs additional ISOs.
BATCH_BUTTONS = ["X", "Y", "Z", "L", "R", "B"]


def build_stage_skin_multibatch_iso(vanilla_iso, groups, out_iso,
                                    progress_cb=None, log=lambda m: None, buttons=None):
    """Fresh project + DAS framework + variants for one OR MORE base stages packed
    into a SINGLE ISO -- up to len(buttons or BATCH_BUTTONS) (=6) per stage, each
    behind its own hold button. The DAS framework installs a loader for ALL six
    base stages, so ONE boot can then screenshot every (stage, variant) combo (up
    to 6 x 6 = 36 per ISO) -- only one build + one boot for a whole selection,
    instead of an ISO per stage.

    `groups` is a list of {"stageCode", "stageFolder", "variantIds"} (each
    variantIds list trimmed to len(buttons) by the caller). Returns the placed
    list: [{"stageCode", "stageFolder", "variantId", "button"}]."""
    buttons = buttons or BATCH_BUTTONS
    proj_dir, proj = create_temp_project(vanilla_iso, log=log, progress_cb=progress_cb)
    placed = []
    try:
        files_dir = proj_dir / "files"
        _step(progress_cb, log, BAR_INSTALL, "Installing the DAS framework…")
        _das_install_framework(files_dir, log=log)
        for g in groups:
            stage_code, stage_folder = g["stageCode"], g["stageFolder"]
            if stage_code not in DAS_STAGES:
                log(f"skip unknown DAS stage {stage_code}")
                continue
            stage_dir = files_dir / stage_code
            stage_dir.mkdir(parents=True, exist_ok=True)
            for vid, button in zip(g.get("variantIds", []), buttons):
                variant_zip = DAS_STORAGE_PATH / stage_folder / f"{vid}.zip"
                if not variant_zip.exists():
                    log(f"skip missing variant {stage_folder}/{vid}")
                    continue
                with zipfile.ZipFile(variant_zip) as z:
                    dat_name = next((n for n in z.namelist()
                                     if n.lower().endswith((".dat", ".usd"))), None)
                    if not dat_name:
                        log(f"skip {vid}: no .dat/.usd in archive")
                        continue
                    data = z.read(dat_name)
                (stage_dir / f"NucleusTestSkin({button}).dat").write_bytes(data)
                placed.append({"stageCode": stage_code, "stageFolder": stage_folder,
                               "variantId": vid, "button": button})
                log(f"Placed {stage_folder}/{vid} behind HOLD {button}")
        if not placed:
            raise RuntimeError("no variants were placed into the ISO")
        mex = MexManager(str(MEXCLI_PATH), str(proj))
        _export(mex, out_iso, progress_cb, log)
        return placed
    finally:
        shutil.rmtree(proj_dir, ignore_errors=True)


