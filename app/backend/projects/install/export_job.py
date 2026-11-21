"""
The ISO export job: the one code path that turns a project into a playable ISO.

`run_export_job` is what the Build button runs (`projects/routes/export.py`,
`POST /api/mex/export/start`) and what Randall's delivery runs inline
(`randall/delivery/deliver_steps.py`), so both share one lock discipline and
one set of pre-export heals. Each export is an `iso_export` job (core/jobs.py)
whose id is the artifact id; its record carries the progress, the failure or
the finished artifact. Also here: `copy_artifact_to`, the Save button's
all-or-nothing publish of a finished artifact.
"""

import shutil
import subprocess
import time
import logging
import uuid
from datetime import datetime
from pathlib import Path

import file_retry
from core import critical_ops, jobs, playable_iso
from core.config import OUTPUT_PATH, STORAGE_PATH, MEXCLI_PATH, get_subprocess_args
from core.state import get_mex_manager, get_current_project_path, mexcli_lock
from core.path_safety import validate_path_segment
from shared.ingame.boot import slippi_user_dir
from projects.install.required_codes import REQUIRED_GECKO_CODES

logger = logging.getLogger(__name__)

# Each export job owns one immutable generated artifact, named by its job id. A
# filename is only a suggested save/download name and never identifies bytes.
EXPORT_KIND = 'iso_export'


def _clean_export(name, value):
    """Delete what an export still owned when it ended or Nucleus died
    (core/jobs.py): its half-written ISO and texture-pack mode's project copy."""
    path = Path(value)
    if name == 'staging' and path.name.endswith('.part.iso'):
        path.unlink(missing_ok=True)
    elif name == 'temp_project' and path.name.startswith('nucleus_texexport_') and path.exists():
        shutil.rmtree(path)
    return None


jobs.register_kind(EXPORT_KIND, label='ISO export', cleanup=_clean_export)


def export_job(artifact_id):
    """The export job record for an artifact id, or None."""
    record = jobs.get(artifact_id)
    return record if record and record.get('kind') == EXPORT_KIND else None


def _raise_if_export_failed(result, output_file):
    """MexCLI can fail without failing: an error JSON line alongside a 0 exit
    code, or a clean exit that never wrote the ISO. Both used to fall through
    to a finished export, so the UI offered a Save button pointing at a missing
    or half-written file (bugreport-968a8ba8)."""
    if isinstance(result, dict) and (
            result.get('success') is False or result.get('status') == 'error'):
        raise RuntimeError(result.get('error') or 'MexCLI reported an export error')
    if not output_file.is_file() or output_file.stat().st_size == 0:
        raise RuntimeError('Export finished but produced no ISO file')


def _validate_iso_filename(filename):
    validate_path_segment(filename, field='filename')
    if not filename.lower().endswith('.iso') or filename.lower() == '.iso':
        raise ValueError('filename must be a basename ending in .iso')
    return filename


def ensure_required_gecko_codes(project_path):
    """Inject REQUIRED_GECKO_CODES (default-on codes) into the project via
    `mexcli add-code` if missing; a disabled entry counts as present. Best-effort: logs and continues on failure rather than blocking
    export, matching the DAS folder-extension heal right above this call."""
    if not MEXCLI_PATH.exists():
        logger.warning(f"MexCLI not found at {MEXCLI_PATH}; skipping required Gecko codes")
        return
    for name, hex_source in REQUIRED_GECKO_CODES:
        try:
            cmd = [str(MEXCLI_PATH), 'add-code', str(project_path), name, hex_source]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60,
                **get_subprocess_args()
            )
            logger.info(f"add-code '{name}' exit={result.returncode} stdout={result.stdout[:300]}")
            if result.stderr:
                logger.info(f"add-code '{name}' stderr={result.stderr[:300]}")
        except Exception as e:
            logger.warning(f"Failed to add required Gecko code '{name}': {e}")


def _resolve_project_dat(files_dir, file_name):
    """Locate a costume's model DAT in a project's files/ dir.

    Handles region-resolved names: Red Falcon's costume fileName is 'PlCaRe.' --
    a trailing dot, no extension, because the game appends the REGION extension
    ('usd' for NTSC-U). For such names the file the US game actually loads is the
    '.usd', and that is where a patch (Animelee) put its modded costume -- the
    sibling 'PlCaRe.dat' is the untouched VANILLA model. So a trailing-dot name
    must prefer '.usd' (else the export rendered the vanilla Red Falcon, not the
    patch one). A normal name ('PlFxNrMod.dat') resolves directly and, failing
    that, still prefers '.dat'. Returns a Path or None.
    """
    from pathlib import Path
    if not file_name:
        return None
    files_dir = Path(files_dir)
    direct = files_dir / file_name
    if direct.is_file():
        return direct
    stem = file_name.rstrip('.')
    # region-resolved (trailing dot) -> the US game loads .usd, where the patch's
    # modded costume lives; otherwise the model is a plain .dat.
    exts = ('.usd', '.dat', '') if file_name.endswith('.') else ('.dat', '.usd', '')
    for ext in exts:
        cand = files_dir / f"{stem}{ext}"
        if cand.is_file():
            return cand
    return None


class ExportRequestError(ValueError):
    """A malformed export request. The caller got it wrong; nothing was built."""


def run_export_job(options, *, background=True, project_path=None, mex_manager=None,
                   build_guard=None):
    """Run the ISO export the Build button runs -- as a plain function.

    The Build button's route (projects/routes/export.py) and Randall's delivery
    workflow both enter here, so there is exactly one code path that turns a
    project into a playable ISO, with one lock discipline and one set of
    pre-export heals.

    Args:
        options: the request body (see `start_export` in projects/routes/export.py).
        background: True (the UI) starts the export job and returns at once.
            False runs the job on the calling thread and returns after the
            artifact is complete or failed -- the only way a caller can truthfully
            say "installed". Either way the outcome is the job record
            (`export_job(artifactId)`).
        project_path / mex_manager: export a NAMED build instead of whichever
            project the UI has open. A delivery must never silently retarget.
        build_guard: an OPEN `core.build_access.BuildSession` for that build.
            The build's cross-process lock is a file lock on a fresh handle, so
            a caller that already holds one cannot let this function take a
            second: an operation that installs and then exports passes its one
            session through instead of nesting two.

    Returns:
        The same payload the route sends back, as a dict.

    Raises:
        ExportRequestError: the options are malformed (HTTP 400 at the route).
    """
    data = dict(options or {})
    filename = data.get('filename', f'game_{datetime.now().strftime("%Y%m%d_%H%M%S")}.iso')
    csp_compression = data.get('cspCompression', 1.0)
    use_color_smash = data.get('useColorSmash', False)
    texture_pack_mode = data.get('texturePackMode', False)
    slippi_dolphin_path = data.get('slippiDolphinPath')

    try:
        _validate_iso_filename(filename)
    except ValueError as exc:
        raise ExportRequestError(str(exc)) from exc

    # Validate compression range
    if not isinstance(csp_compression, (int, float)) or csp_compression < 0.1 or csp_compression > 1.0:
        raise ExportRequestError('cspCompression must be a number between 0.1 and 1.0')

    # Validate useColorSmash
    if not isinstance(use_color_smash, bool):
        raise ExportRequestError('useColorSmash must be a boolean')

    # Validate texture pack mode requirements
    if texture_pack_mode:
        if not slippi_dolphin_path:
            raise ExportRequestError('slippiDolphinPath is required when texturePackMode is enabled')

    # Bind the queued job to the project selected at request time. The UI
    # may open another project before the background worker takes its lock.
    with mexcli_lock:
        export_project_path = project_path or get_current_project_path()
        export_manager = mex_manager if mex_manager is not None else get_mex_manager()

    # A passed-in session must be the session for THIS build, and it must be
    # usable from the thread that will export. Neither is checkable later:
    #
    #  * a guard on another build would let the export run while the build it
    #    actually reads is unlocked -- the failure a caller-supplied lock is
    #    supposed to prevent, arriving silently;
    #  * `mexcli_lock` is an RLock, so it is re-entrant on the OWNING thread
    #    only. A background export runs on a worker thread and would block on
    #    the lock its own caller is still holding.
    if build_guard is not None:
        wanted = Path(export_project_path).parent
        require = getattr(build_guard, 'require_usable_for', None)
        if require is None:
            raise ExportRequestError(
                'The build_guard given is not a build session. A session is what proves '
                'the build is held; an object with the right attribute is not.')
        try:
            require(wanted, what='This export')
        except Exception as exc:                                # noqa: BLE001
            # A closed session, one from another thread, or one for a different
            # build would all have skipped lock acquisition entirely.
            raise ExportRequestError(str(exc)) from None
        if background:
            raise ExportRequestError(
                'A caller-held build session cannot be handed to a background export: the '
                'worker thread would wait for the lock its own caller is holding. Run this '
                'export with background=False, which is what a caller that has to know the '
                'ISO exists does anyway.')

    build_id = f"build_{uuid.uuid4().hex}"
    artifact_dir = OUTPUT_PATH / 'artifacts'
    artifact_dir.mkdir(parents=True, exist_ok=True)
    staging_file = artifact_dir / f'{build_id}.part.iso'
    output_file = artifact_dir / f'{build_id}.iso'

    logger.info(f"=== ISO EXPORT START ===")
    logger.info(f"Filename: {filename}")
    logger.info(f"CSP Compression: {csp_compression}")
    logger.info(f"Use Color Smash: {use_color_smash}")
    logger.info(f"Texture Pack Mode: {texture_pack_mode}")

    def export_with_progress(job):
        """The export job (core/jobs.py): build the ISO, return its artifact."""
        from pathlib import Path
        import tempfile
        mapping = None
        temp_root = None   # isolated temp copy of the project (texture-pack mode)
        current_project_path = export_project_path

        # Hold the workspace lock for the entire export so a background
        # costume reorder (optimistic UI, applied asynchronously) can't run a
        # second MexCLI process on the project mid-build. If a reorder is
        # still in flight, this blocks until it finishes — i.e. the export
        # waits for pending order changes to settle first.
        #
        # The job is critical: closing the app window mid-build must not
        # os._exit the process under MexCLI — shutdown defers until it drains.
        # The build lock on top of mexcli_lock: a second Nucleus process
        # writing the project mid-export produces a disc built from two
        # different states of it. Entering the session also finishes or undoes
        # whatever a crash left half-applied, so an export never bakes a
        # partial menu install into the ISO. A busy build or a failed import
        # here fails the job like any other export error.
        owns_guard = build_guard is None
        guard = build_guard
        guard_cm = None
        from core import build_access
        mexcli_lock.acquire()
        try:
            if owns_guard:
                # Keep BOTH: the context manager is what closes the session,
                # and the session is what `guard` has to be from here on
                # (a caller that hands its session to another export is checked
                # against `guard.directory`, which the wrapper does not have).
                guard_cm = build_access.build_session(
                    Path(export_project_path).parent, timeout=600.0)
                guard = guard_cm.__enter__()
        except BaseException:
            mexcli_lock.release()
            raise
        try:
            def progress_callback(percentage, message):
                job.progress(percentage / 100, message)

            mex = export_manager
            work_mex = mex   # what we export from; a TEMP copy in texture-pack mode

            # Heal legacy DAS folders on the LIVE project before any temp copy:
            # older versions wrote Pokemon Stadium alts as .usd, which the m-ex
            # loader rejects -> "no valid alts found" assert (dynamicAlts.c) and
            # a crash at stage load. Renaming them to .dat fixes this build and
            # the on-disk project permanently. Idempotent (no-op once clean).
            from projects.install.das import (
                migrate_das_folder_extensions,
                migrate_stadium_variant_stems,
            )
            try:
                das_heal = migrate_das_folder_extensions(
                    Path(current_project_path).parent / 'files')
                if das_heal['renamed'] or das_heal['removed']:
                    logger.info(
                        f"DAS folder heal: renamed {len(das_heal['renamed'])} "
                        f"+ removed {len(das_heal['removed'])} legacy .usd alt(s)")
            except Exception as e:
                logger.warning(f"DAS extension migration skipped: {e}")

            # Unlike the legacy-extension cleanup, this is fail-closed:
            # exporting after a failed stem move can produce a Stadium
            # build that loads normally and freezes on transformation.
            try:
                stem_heal = migrate_stadium_variant_stems(
                    Path(current_project_path).parent / 'files')
            except Exception as e:
                raise RuntimeError(
                    'Could not make Pokemon Stadium variant filenames '
                    f'runtime-safe: {e}') from e
            if stem_heal['renamed']:
                logger.info(
                    f"Stadium filename heal: shortened "
                    f"{len(stem_heal['renamed'])} unsafe variant stem(s)")

            # Bake in the Gecko codes every m-ex build needs regardless of user
            # toggles (see REQUIRED_GECKO_CODES) -- e.g. without "Skip Slippi
            # SSS", Slippi's own SSS injection crashes the stage-select screen
            # on any m-ex build. Idempotent, so safe on every export.
            ensure_required_gecko_codes(current_project_path)

            # Only projects that actually contain a pair get the Any Climbers
            # engine code.
            from vault.climbers import engine_code
            engine_code.ensure_for_export(current_project_path)

            # L-load groups: tuck each alternate's icon behind its base and
            # bake the group table into the L code (or drop the code when the
            # project has no groups). Best-effort; its warnings join the export's.
            from projects.lload import export as lload_export
            lload_warnings = lload_export.ensure(current_project_path)

            # Texture-pack mode does ALL its work (placeholder swap, recompile,
            # export) on an isolated COPY of the project, so a crash — even an
            # OOM kill mid-export — can NEVER leave the real project full of
            # placeholder CSPs. The live project is read-only here.
            if texture_pack_mode:
                from projects.install.texture_pack import (
                    save_encoded_placeholder,
                    TexturePackMapping,
                    CostumeMapping,
                    find_hd_csp_by_hash,
                )
                from shared.rendering.hd_csp_cache import (
                    get_or_render_hd, hash_dat, get_cached, effective_key_hash)
                from shared.rendering.csp_concurrency import csp_workers
                from shared.rendering.csp_pool import active_pool
                from concurrent.futures import ThreadPoolExecutor, as_completed
                from mexcli.project import MexManager
                from core.config import MEXCLI_PATH

                # Clear the DUMP folder to prevent old placeholders from confusing the scanner
                if slippi_dolphin_path:
                    dump_path = slippi_user_dir(slippi_dolphin_path) / "Dump" / "Textures" / "GALE01"
                    if dump_path.exists():
                        shutil.rmtree(dump_path)
                        dump_path.mkdir(parents=True)
                        logger.info(f"Cleared dump folder: {dump_path}")

                # Copy the live project into a throwaway temp dir and run everything
                # against that copy via its own MexManager.
                progress_callback(1, 'Preparing an isolated copy of the project…')
                live_project_dir = current_project_path.parent
                temp_root = Path(tempfile.mkdtemp(prefix='nucleus_texexport_'))
                job.own('temp_project', str(temp_root))
                temp_project_dir = temp_root / live_project_dir.name
                shutil.copytree(live_project_dir, temp_project_dir)
                temp_mexproj = temp_project_dir / current_project_path.name
                work_mex = MexManager(cli_path=str(MEXCLI_PATH), project_path=str(temp_mexproj))
                logger.info(f"Texture-pack export isolated to temp project: {temp_project_dir}")

                live_csp_dir = live_project_dir / "assets" / "csp"   # originals (untouched)
                temp_csp_dir = temp_project_dir / "assets" / "csp"   # placeholders go here

                # Create mapping. Its textures go in Load/.../<build_id>, one
                # folder per export: two builds given the same file name must
                # not place portraits into each other's pack.
                mapping = TexturePackMapping(
                    build_id=build_id,
                    build_name=build_id,
                    created_at=datetime.now().isoformat()
                )

                temp_files_dir = temp_project_dir / "files"

                # Pass 1: enumerate every costume slot that has a CSP, so HD
                # render progress can be reported against a known total.
                fighters = work_mex.list_fighters()
                slots = []  # ordered; global index = position in this list
                for fighter in fighters:
                    try:
                        result = work_mex._run_command("get-costumes", str(work_mex.project_path), fighter['name'])
                    except Exception as e:
                        logger.warning(f"Error listing costumes for {fighter['name']}: {e}")
                        continue
                    for costume_idx, costume in enumerate(result.get('costumes', [])):
                        if not costume.get('csp'):
                            continue
                        csp_ref = costume['csp'].replace('\\', '/')
                        csp_name = f"{csp_ref.split('/')[-1]}.png"
                        if not (temp_csp_dir / csp_name).exists():
                            continue
                        slots.append({
                            'character': fighter['name'],
                            'costume_index': costume_idx,
                            'skin_id': costume.get('name', f"costume_{costume_idx}"),
                            'csp_name': csp_name,
                            'file_name': costume.get('fileName') or '',
                        })

                total_slots = len(slots)
                logger.info(f"Texture-pack: {total_slots} costume CSP slots to process")

                # G&W: per-slot fill/outline from the project's GawColors
                # table (added color-mod slots have arbitrary colors that
                # color_index can't express). None -> color_index fallback.
                from core.gaw_colors import load_project_gaw_colors
                project_gaw_colors = load_project_gaw_colors(temp_project_dir)

                # Pass 2: resolve each slot's HD CSP, then swap in the 16x16
                # placeholder. HD priority per slot: the user's vault HD CSP,
                # then the DAT-hash cache, then a fresh 4x render (patch costumes
                # are custom art with no vault/vanilla match -> render once, cached
                # by DAT hash so every later export is instant). A failed render
                # leaves hd_csp_path=None -> SD fallback (never breaks a build).
                # Renders are the slow part and independent per slot, so resolve
                # them in parallel (worker count auto-sized to the machine); the
                # mapping + placeholder write is cheap and done serially after.
                def _resolve_slot_hd(slot):
                    """Resolve (hd_csp_path, dat_hash, was_miss) for one slot.
                    Thread-safe: only reads shared inputs and renders via
                    get_or_render_hd (own temp dir + atomic cache publish +
                    staggered launch)."""
                    live_sd = str(live_csp_dir / slot['csp_name'])
                    try:
                        vault_hd = find_hd_csp_by_hash(STORAGE_PATH, live_sd, slot['character'])
                    except Exception:
                        vault_hd = None
                    if vault_hd:
                        return str(vault_hd), None, False
                    dat_path = _resolve_project_dat(temp_files_dir, slot['file_name'])
                    if dat_path is None:
                        return None, None, False
                    dat_hash = hash_dat(dat_path)

                    # Ice Climbers: composite Nana onto Popo so the HD portrait
                    # matches the in-game both-climbers CSP. For a Nana-primary
                    # slot generate_csp renders nothing and we fall back to SD.
                    paired_dat_path = None
                    if dat_path.name[:4].lower() in ('plpp', 'plnn'):
                        try:
                            from generate_csp import find_ice_climbers_pair
                            _ct, pair_path, _pc, _nc = find_ice_climbers_pair(str(dat_path))
                            if pair_path:
                                paired_dat_path = pair_path
                        except Exception as e:
                            logger.warning(f"ICs pair lookup failed for {dat_path.name}: {e}")

                    # Mr. Game & Watch: his slots all share one PlGwNr.dat and
                    # get their flat color from the m-ex GawColors table by
                    # costume position, not the DAT bytes. Pass the slot's
                    # actual colors (covers added color-mod slots with
                    # arbitrary RGB); fall back to the vanilla color_index if
                    # the project table couldn't be read. Either way each
                    # slot renders + caches its own color instead of all
                    # colliding on the shared DAT hash.
                    color_index = None
                    gw_colors = None
                    if slot['character'] in ('Mr. Game & Watch', 'G&W'):
                        idx = slot.get('costume_index', 0)
                        if project_gaw_colors and idx < len(project_gaw_colors):
                            gw_colors = project_gaw_colors[idx]
                        else:
                            color_index = idx

                    eff_hash = effective_key_hash(
                        dat_path, paired_dat_path=paired_dat_path,
                        dat_hash=dat_hash, color_index=color_index,
                        gw_colors=gw_colors)
                    was_miss = bool(eff_hash) and get_cached(eff_hash) is None
                    hd = get_or_render_hd(
                        dat_path, dat_hash=dat_hash, paired_dat_path=paired_dat_path,
                        color_index=color_index, gw_colors=gw_colors)
                    return (str(hd) if hd else None), dat_hash, was_miss

                rendered = 0
                hd_by_index = {}  # global_index -> (hd_csp_path, dat_hash)
                workers = csp_workers()
                done = 0
                progress_callback(
                    1, f"Rendering HD portraits (0/{total_slots}, ×{workers} workers)…")
                # Reuse persistent --csp-server workers across all HD portraits
                # instead of a fresh process per slot (~9x); one-shot fallback
                # per slot on any failure. Kill switch: MEX_CSP_SERVER=0.
                with active_pool(workers=workers), \
                        ThreadPoolExecutor(max_workers=workers) as pool:
                    futs = {pool.submit(_resolve_slot_hd, s): i
                            for i, s in enumerate(slots)}
                    for fut in as_completed(futs):
                        gi = futs[fut]
                        try:
                            hd_csp_path, dat_hash, was_miss = fut.result()
                        except Exception as e:
                            logger.warning(
                                f"HD resolve failed for slot {gi} "
                                f"({slots[gi]['character']}/{slots[gi]['skin_id']}): {e}")
                            hd_csp_path, dat_hash, was_miss = None, None, False
                        hd_by_index[gi] = (hd_csp_path, dat_hash)
                        if was_miss and hd_csp_path:
                            rendered += 1
                        done += 1
                        if done % 4 == 0 or done == total_slots:
                            pct = 1 + int(4 * done / max(1, total_slots))
                            progress_callback(
                                pct,
                                f"Rendering HD portraits "
                                f"({done}/{total_slots}, ×{workers} workers)…")

                # Assemble the mapping + placeholders in slot order (cheap, ordered).
                for global_index, slot in enumerate(slots):
                    hd_csp_path, dat_hash = hd_by_index.get(global_index, (None, None))
                    live_sd_csp = str(live_csp_dir / slot['csp_name'])
                    mapping.add_costume(CostumeMapping(
                        index=global_index,
                        character=slot['character'],
                        costume_index=slot['costume_index'],
                        skin_id=slot['skin_id'],
                        real_csp_path=live_sd_csp,
                        hd_csp_path=hd_csp_path,
                        dat_hash=dat_hash,
                    ))
                    # Replace the COPY's CSP with the encoded placeholder (16x16)
                    save_encoded_placeholder(global_index, temp_csp_dir / slot['csp_name'])

                global_index = total_slots
                logger.info(
                    f"Created {global_index} placeholder CSPs (in temp copy); "
                    f"{rendered} HD portraits rendered this export")

                # Save a debug sample so user can verify the placeholder format
                debug_placeholder = OUTPUT_PATH / "debug_placeholder_sample.png"
                save_encoded_placeholder(12345, debug_placeholder)  # Test index to verify encoding

                # Save mapping
                mapping_file = OUTPUT_PATH / f"{build_id}_texture_mapping.json"
                mapping.save(mapping_file)
                logger.info(f"Saved texture mapping to {mapping_file}")

                # Recompile the COPY's CSPs from the placeholder PNGs (regenerates
                # its .tex files so the export uses the placeholders, not cached tex).
                logger.info("Recompiling CSPs from placeholder PNGs (temp copy)...")
                recompile_result = work_mex.recompile_csps()
                logger.info(f"CSP recompile complete: {recompile_result.get('message', 'done')}")

            # Note: Extras are patched immediately on import, not at export time

            # Note: character sound packs are installed per-project from
            # the Sounds menu (character_sounds.py), not at export time

            # Bake Frame Speed Modifier data (fsm.txt) for installed custom
            # characters into the project's main.dol. In texture-pack mode bake
            # into the TEMP copy so the live project's dol isn't modified.
            try:
                from projects.install.fsm_patcher import apply_project_fsm
                from core.config import CUSTOM_CHARACTERS_PATH
                fsm_project_path = Path(work_mex.project_path) if texture_pack_mode else current_project_path
                fsm_count = apply_project_fsm(fsm_project_path, CUSTOM_CHARACTERS_PATH)
                if fsm_count:
                    logger.info(f"FSM: baked {fsm_count} frame-speed entries into main.dol")
                    progress_callback(2, f"Baked {fsm_count} frame-speed (FSM) entries into the game")
            except Exception as e:
                logger.warning(f"FSM patching skipped: {e}")

            # Repair any vanilla movie a pre-0.8.11 Free space already deleted
            # (that build crashed after every 1P clear / title idle / Data ->
            # Movies -- Tracker #92). Regenerates a stub from the recorded
            # vanilla ISO if one is known; no-op when every movie is already
            # present (stub or full), which is the common case.
            try:
                from core import movie_stubs
                from shared.vanilla_extract.vanilla_refs import known_vanilla_iso
                movie_repair_project_path = (
                    Path(work_mex.project_path) if texture_pack_mode else current_project_path)
                export_files_dir = movie_repair_project_path.parent / "files"
                repair = movie_stubs.restore_missing_movies(
                    export_files_dir, vanilla_iso=known_vanilla_iso())
                if repair['restored']:
                    logger.info(f"Export: regenerated {len(repair['restored'])} "
                                f"missing vanilla movie stub(s): {repair['restored']}")
                if repair['unresolved']:
                    logger.warning(
                        f"Export: {len(repair['unresolved'])} vanilla movie(s) missing "
                        f"and no vanilla ISO on record to rebuild them from: "
                        f"{repair['unresolved']}")
            except Exception as e:
                logger.warning(f"Movie stub repair skipped: {e}")

            # Run the actual export from the working project (the temp copy in
            # texture-pack mode). When using texture pack mode, skip compression
            # entirely because placeholders must stay at fixed 16x16 size.
            skip_compression = texture_pack_mode
            job.own('staging', str(staging_file))
            result = work_mex.export_iso(str(staging_file), progress_callback, csp_compression, use_color_smash, skip_compression)
            _raise_if_export_failed(result, staging_file)
            file_retry.replace(staging_file, output_file)
            job.release('staging')

            # No CSP restore needed: the live project was never modified — all
            # placeholder work happened in the temp copy (the job's cleanup
            # deletes it, and a failed export's staging file, when it ends).

            # MexCLI's export may have had to act on the build to keep it
            # bootable (the character-select heap guard compresses portraits
            # when MnSlChr + mexSelectChr would overflow the CSS scene heap);
            # tell the user what happened and the portrait quality that shipped.
            export_warnings = lload_warnings + list((result or {}).get('warnings') or [])
            effective_csp = (result or {}).get('cspCompression', csp_compression)
            for w in export_warnings:
                logger.warning(f"Export warning: {w}")

            job.progress(1.0, 'Export complete')
            return {
                'filename': filename,
                'path': str(output_file),
                'texturePackMode': texture_pack_mode,
                'buildId': build_id if texture_pack_mode else None,
                'totalCostumes': len(mapping.costumes) if mapping else 0,
                'warnings': export_warnings,
                'cspCompression': effective_csp,
                'cssBytes': (result or {}).get('cssBytes'),
                'costumeCount': (result or {}).get('costumeCount'),
            }
        finally:
            try:
                if guard_cm is not None:
                    guard_cm.__exit__(None, None, None)
            finally:
                mexcli_lock.release()

    job_options = dict(
        label='ISO export', job_id=build_id, critical=True,
        project=str(export_project_path) if export_project_path else None,
        params={'filename': filename, 'texturePackMode': texture_pack_mode,
                'buildId': build_id if texture_pack_mode else None})
    if background:
        # The UI's Build button: return at once; the window follows the job.
        jobs.start(EXPORT_KIND, export_with_progress, **job_options)
    else:
        # A caller that has to KNOW whether the playable ISO exists before it
        # reports anything (delivery.deliver) runs the same job inline and then
        # reads export_job(artifact_id). mexcli_lock is an RLock, so a caller
        # already holding the build's lock re-enters it here.
        jobs.run_inline(EXPORT_KIND, export_with_progress, **job_options)

    return {
        'success': True,
        'message': 'Export started',
        'filename': filename,
        'artifactId': build_id,
        'buildId': build_id if texture_pack_mode else None
    }


def _resolve_completed_artifact(artifact_id):
    """Return the immutable artifact of a finished export job, or None. Startup
    cleanup empties output/artifacts, so an older run's record finds no file."""
    record = export_job(artifact_id)
    path = ((record or {}).get('result') or {}).get('path')
    if not record or record.get('status') != 'done' or not path:
        return None
    file_path = Path(path).resolve()
    artifact_root = (Path(OUTPUT_PATH) / 'artifacts').resolve()
    if file_path.parent != artifact_root or not file_path.is_file():
        return None
    return file_path


def copy_artifact_to(file_path, dest):
    """Publish a completed export onto `dest`, all-or-nothing. Returns the error.

    Goes through `core.playable_iso.publish`, which is the ONE place allowed to
    write a disc image someone plays. That means the Save button obeys the same
    rule the delivery workflow does: the clean Melee ISO is never written, the
    file Slippi Launcher opens is never written unless it is one of ours, and an
    existing file without a valid Nucleus marker is refused rather than replaced.
    A successful save writes that marker, so saving over your own build again
    keeps working.

    Publication also stages beside the destination, hashes the staged bytes
    against the build before the atomic replace, hard-links the previous copy
    aside so the path is never empty, and re-checks ownership immediately
    before the write.

    Returns None on success, or the exception to report (`ProtectedPath` for a
    refusal the user can act on, OSError for a write that failed).
    """
    with critical_ops.critical_op('ISO save'):
        # Two attempts: bugreport-968a8ba8 shows the destination write failing
        # with FileNotFoundError in a folder that exists, then the identical
        # save succeeding 23s later (antivirus / Controlled Folder Access
        # shaped) -- a short-delay retry absorbs that. A refusal is never
        # retried: it will not become allowed.
        for attempt in (1, 2):
            try:
                playable_iso.publish(
                    file_path, dest,
                    marker={'source': 'export_save',
                            'artifact': Path(file_path).name})
                return None
            except playable_iso.ProtectedPath as refusal:
                logger.warning(f"ISO save refused: {refusal}")
                return refusal
            except OSError as e:
                logger.warning(f"ISO save attempt {attempt} failed: {e}")
                if attempt == 1:
                    time.sleep(1.0)
                else:
                    return e
