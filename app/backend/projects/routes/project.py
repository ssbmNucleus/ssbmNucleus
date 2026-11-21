"""
Project Blueprint - Project management routes.

Handles MEX project status, open, create, and fighter listing.
"""

import json
import os
import re
import subprocess
import logging
import shutil
from pathlib import Path
from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename

from core.config import (
    PROJECTS_PATH, MEXCLI_PATH, OUTPUT_PATH, VANILLA_ASSETS_DIR, get_subprocess_args
)
import mexcli.commands
from core.state import (
    get_mex_manager, set_project_path, get_current_project_path, clear_project_path,
    get_project_files_dir, reload_mex_manager, mexcli_lock, get_project_generation,
    project_check_exempt
)
from mexcli.project import MexManager
from core.constants import VANILLA_COSTUME_COUNT
from core.helpers import calculate_auto_compression
import file_retry
from core import movie_stubs
from shared.vanilla_extract.vanilla_refs import known_vanilla_iso
from projects.install.project_fighters import find_fighter_json_by_name

logger = logging.getLogger(__name__)

project_bp = Blueprint('project', __name__)

# Standard GameCube disc capacity (bytes). A build whose data exceeds this hangs at
# the character-select screen (see docs/dev/MEX_BUILD_LIMITS.md), so it's the hard
# ceiling for total costumes/stages/etc. "free" below is the real headroom for
# anything the user adds.
DISC_CAPACITY = 1_459_978_240
_AVG_SKIN_BYTES = 497 * 1024   # ~one added distinct costume in the ISO (model + csp + stock)
_CSP_BYTES = 25 * 1024         # CSP portrait portion (the only part HD/texture-pack mode saves)


def _disc_category(name):
    """Bucket an ISO file by name into a coarse category for the usage bar. The big
    *strippable* chunks (video, trophies) are split out so the bar shows where free
    space can come from — cutting Mv*.mth movies alone frees ~800 MB."""
    n = name.lower()
    if n.startswith('pl'):
        return 'costumes'          # PlFxNr.dat ... (player/costume files)
    if n.startswith('gr'):
        return 'stages'            # GrXX ... (stage files)
    if n.startswith('mv'):
        return 'video'             # Mv*.mth movies/cutscenes (~811 MB vanilla; the big cut)
    if n.startswith('ty'):
        return 'trophies'          # Ty*.dat trophies (~84 MB; also strippable)
    if n.endswith(('.ssm', '.sem', '.hps')):
        return 'audio'
    return 'other'                 # menus, CSP atlas, effects, items, main.dol, sys, ...


@project_bp.route('/api/mex/project/disc-usage', methods=['GET'])
def project_disc_usage():
    """Disc-space breakdown for the build-capacity indicator. Sums the project's
    files/ (+sys/) by category and compares to the GameCube disc size. The build
    hangs once it exceeds the disc, so `free` is the usable headroom and
    `skinsRemaining` estimates how many more average costumes fit."""
    try:
        files_dir = get_project_files_dir()
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    try:
        breakdown = {'costumes': 0, 'stages': 0, 'video': 0, 'trophies': 0, 'audio': 0, 'other': 0}
        if files_dir.exists():
            for p in files_dir.rglob('*'):
                if not p.is_file():
                    continue
                parts = p.relative_to(files_dir).parts
                cat = 'audio' if (parts and parts[0].lower() == 'audio') else _disc_category(p.name)
                breakdown[cat] += p.stat().st_size
        # sys/ (apploader, boot.bin, bi2.bin) also goes into the ISO
        proj = get_current_project_path()
        sys_dir = proj.parent / 'sys' if proj else None
        if sys_dir and sys_dir.exists():
            for p in sys_dir.rglob('*'):
                if p.is_file():
                    breakdown['other'] += p.stat().st_size

        used = sum(breakdown.values())
        free = max(0, DISC_CAPACITY - used)

        # How much the video category would actually shrink by. Free space no
        # longer deletes movies (that breaks 1P, see movie_stubs.py) -- it stubs
        # them, so the real gain is the file minus its stub, not the whole
        # category. Best-effort: an unreadable files/ dir just reports 0.
        try:
            video_status = movie_stubs.movie_status(files_dir)
            video_reclaimable = video_status['reclaimableBytes']
        except Exception:
            video_reclaimable = 0

        return jsonify({
            'success': True,
            'capacity': DISC_CAPACITY,
            'used': used,
            'free': free,
            'overCapacity': used > DISC_CAPACITY,
            'breakdown': breakdown,
            'reclaimable': {'video': video_reclaimable},
            'avgSkinBytes': _AVG_SKIN_BYTES,
            'skinsRemaining': int(free // _AVG_SKIN_BYTES),
            'skinsRemainingHd': int(free // max(1, _AVG_SKIN_BYTES - _CSP_BYTES)),
        })
    except Exception as e:
        logger.error(f"disc-usage failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@project_bp.route('/api/mex/project/strip', methods=['POST'])
def project_strip():
    """Free disc space from the vanilla MOVIE files (Mv*.mth, ~810 MB full).

    This does NOT delete them -- deleting a movie the game opens by name with no
    missing-file check crashes the build after every 1P clear, on the title
    attract loop, and in Data -> Movies (Tracker #92, core/movie_stubs.py). Each
    vanilla movie is instead replaced with a short valid stub cut from its own
    opening frames (MvOpen gets a long low-detail stub, since its scene can't
    finish on a short one); the game still plays every scene that opens a movie,
    just briefly.

    Only the 28 explicit vanilla file names are ever touched -- never an added
    fighter's MvEnd<Name>.mth or any other file starting "mv". Idempotent: an
    already-stubbed movie is left alone. Also regenerates a stub for any vanilla
    movie a PRE-0.8.11 Nucleus build already deleted, from the recorded vanilla
    ISO if one is known (same repair export does automatically).

    Body: {"targets": ["video"]}.

    Only 'video' is supported: trophy files (Ty*) are parsed by MexManager's
    TrophyLoader when the workspace opens, so deleting them makes the project fail
    to open -- they must NOT be stripped this way."""
    data = request.get_json(silent=True) or {}
    targets = set(t for t in data.get('targets', []) if t in ('video',))
    if not targets:
        return jsonify({'success': False, 'error': 'no valid targets (video)'}), 400
    try:
        files_dir = get_project_files_dir()
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    try:
        # Hold the project lock: this rewrites the workspace's files/ dir, so it
        # must not run while a background reorder / export has the project open.
        with mexcli_lock:
            vanilla_iso = known_vanilla_iso()
            result = movie_stubs.replace_movies_with_stubs(files_dir, vanilla_iso=vanilla_iso)
            reload_mex_manager()  # next export/status re-reads files/ from disk
        logger.info(
            f"strip video: stubbed {len(result['stubbed'])}, "
            f"restored {len(result['restored'])} missing, "
            f"skipped {len(result['skipped'])}, unresolved {len(result['unresolved'])}, "
            f"freed {result['freedBytes']} bytes")
        return jsonify({
            'success': True,
            'removed': len(result['stubbed']),  # legacy field name; now "stubbed" count
            'freedBytes': result['freedBytes'],
            'targets': sorted(targets),
            'stubbed': result['stubbed'],
            'restored': result['restored'],
            'unresolved': result['unresolved'],
        })
    except Exception as e:
        logger.error(f"strip failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


def get_next_project_directory(requested_name=None):
    """Pick a unique subdirectory under the app-managed projects folder."""
    base_name = secure_filename((requested_name or '').strip()) or 'MexProject'
    candidate = PROJECTS_PATH / base_name
    suffix = 2

    while candidate.exists():
        candidate = PROJECTS_PATH / f"{base_name}-{suffix}"
        suffix += 1

    return candidate


def is_managed_project_directory(project_dir):
    """Return True when a project directory lives under the managed projects root."""
    try:
        Path(project_dir).resolve().relative_to(PROJECTS_PATH.resolve())
        return True
    except ValueError:
        return False


def cleanup_failed_project_directory(proj_dir):
    """Remove a partially-created project directory after a failed create."""
    if not proj_dir.exists() or not is_managed_project_directory(proj_dir):
        return
    try:
        shutil.rmtree(proj_dir)
        logger.info(f"Removed partial project directory: {proj_dir}")
    except OSError as cleanup_error:
        logger.warning(f"Could not remove partial project directory: {cleanup_error}")


def build_project_response(project_path, info):
    """Build consistent project metadata for API responses."""
    project_file = Path(project_path)
    project_dir = project_file.parent

    return {
        'name': info['build']['name'],
        'version': f"{info['build']['majorVersion']}.{info['build']['minorVersion']}.{info['build']['patchVersion']}",
        'path': str(project_file),
        'projectDirectory': str(project_dir),
        'isManagedProject': is_managed_project_directory(project_dir)
    }


def build_project_listing_entry(project_file, current_project_path=None):
    """Build lightweight metadata for a managed project without opening it."""
    project_file = Path(project_file)
    project_dir = project_file.parent

    try:
        last_modified_at = int(project_file.stat().st_mtime)
    except OSError:
        last_modified_at = 0

    is_current_project = False
    if current_project_path is not None:
        try:
            is_current_project = current_project_path.resolve() == project_file.resolve()
        except OSError:
            is_current_project = False

    return {
        'name': project_dir.name,
        'path': str(project_file),
        'projectDirectory': str(project_dir),
        'isManagedProject': True,
        'isCurrentProject': is_current_project,
        'lastModifiedAt': last_modified_at
    }


@project_bp.route('/api/mex/recommended-compression', methods=['GET'])
def get_recommended_compression():
    """Get recommended CSP compression based on added costume count."""
    try:
        with mexcli_lock:
            mex = get_mex_manager()
            fighters = mex.list_fighters()

        # Sum costumeCount from list-fighters (already included, no extra API calls)
        total_costumes = sum(f.get('costumeCount', 0) for f in fighters)

        # Calculate added costumes (can't be negative)
        added_costumes = max(0, total_costumes - VANILLA_COSTUME_COUNT)

        ratio = calculate_auto_compression(added_costumes)

        return jsonify({
            'success': True,
            'totalCostumes': total_costumes,
            'vanillaCostumes': VANILLA_COSTUME_COUNT,
            'addedCostumes': added_costumes,
            'ratio': round(ratio, 2)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'totalCostumes': 0,
            'vanillaCostumes': VANILLA_COSTUME_COUNT,
            'addedCostumes': 0,
            'ratio': 1.0
        }), 500


@project_bp.route('/api/mex/status', methods=['GET'])
@project_check_exempt
def get_status():
    """Get MEX project status"""
    # The path and the info below come from the same pinned project, even if a
    # switch publishes another one while this waits for the lock.
    current_project_path = get_current_project_path()
    generation = get_project_generation()

    # Check if a project is loaded
    if current_project_path is None:
        return jsonify({
            'success': True,
            'connected': True,
            'projectLoaded': False,
            'generation': generation,
            'message': 'No project loaded'
        })

    try:
        with mexcli_lock:
            mex = get_mex_manager()
            info = mex.get_info()

        return jsonify({
            'success': True,
            'connected': True,
            'projectLoaded': True,
            'generation': generation,
            'project': build_project_response(current_project_path, info),
            'counts': info['counts']
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'connected': False,
            'projectLoaded': False,
            'error': str(e)
        }), 500


@project_bp.route('/api/mex/project/open', methods=['POST'])
@project_check_exempt
def open_project():
    """Open a MEX project from a given path.

    The project is checked first (recovery, then MexCLI reading it) and only
    then published. A project that fails either check is never selected, so
    the one that was open stays open and the window stays right about it.
    """
    try:
        data = request.json
        project_path = data.get('projectPath')

        if not project_path:
            return jsonify({
                'success': False,
                'error': 'No project path provided'
            }), 400

        project_file = Path(project_path)

        # Validate the path
        if not project_file.exists():
            return jsonify({
                'success': False,
                'error': f'Project file not found: {project_path}'
            }), 404

        if not project_file.suffix == '.mexproj':
            return jsonify({
                'success': False,
                'error': 'File must be a .mexproj file'
            }), 400

        # Opening a build is the moment to repair one: if a menu/code change
        # died mid-write, its originals go back -- or, if it was already
        # written and verified, its receipt is written out -- BEFORE anything
        # reads this project.
        from core import build_access
        health = build_access.recover_on_open(Path(project_file).parent)
        if health['status'] in ('quarantined', 'error'):
            # A build whose last operation cannot be accounted for is not
            # opened silently. Swallowing this is how a half-written project
            # becomes "it just stopped working".
            logger.error(f"Refusing to open {project_path}: {health['message']}")
            return jsonify({'success': False, 'error': health['message'],
                            'code': health['status'],
                            'problems': health['problems']}), 409
        if health['status'] == 'busy':
            # Recovery never ran, so the build is unchecked. Opening it anyway
            # (as this used to) could present a half-written project as fine.
            logger.warning(f"Not opening {project_path}: {health['message']}")
            return jsonify({'success': False, 'code': 'busy',
                            'error': 'This project is busy (an export or save is still running). '
                                     'Try again when it finishes.'}), 409
        if health['actions']:
            logger.warning(f"Recovered {len(health['actions'])} interrupted build "
                           f"change(s) in {project_path}: {health['actions']}")

        # MexCLI must read it before it is published, under the same lock a
        # workspace writer holds, so no request ever sees an unchecked project.
        with mexcli_lock:
            mex = MexManager(cli_path=str(MEXCLI_PATH), project_path=str(project_file))
            info = mex.get_info()
            generation = set_project_path(project_path, manager=mex)

        logger.info(f"[OK] Opened MEX project: {project_path}")

        return jsonify({
            'success': True,
            'message': 'Project opened successfully',
            'generation': generation,
            'project': build_project_response(project_path, info)
        })
    except Exception as e:
        logger.error(f"Failed to open project: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@project_bp.route('/api/mex/project/list', methods=['GET'])
@project_check_exempt
def list_projects():
    """List all app-managed MEX projects."""
    try:
        current_project_path = get_current_project_path()
        projects = []

        if PROJECTS_PATH.exists():
            for project_dir in PROJECTS_PATH.iterdir():
                if not project_dir.is_dir():
                    continue

                default_project_file = project_dir / 'project.mexproj'
                if default_project_file.exists():
                    project_file = default_project_file
                else:
                    mexproj_files = sorted(project_dir.glob('*.mexproj'))
                    if not mexproj_files:
                        continue
                    project_file = mexproj_files[0]

                projects.append(build_project_listing_entry(project_file, current_project_path))

        projects.sort(key=lambda project: (
            not project.get('isCurrentProject', False),
            -project.get('lastModifiedAt', 0),
            project.get('name', '').lower()
        ))

        return jsonify({
            'success': True,
            'projects': projects,
            'projectsDirectory': str(PROJECTS_PATH)
        })
    except Exception as e:
        logger.error(f"List projects error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@project_bp.route('/api/mex/project/close', methods=['POST'])
@project_check_exempt
def close_project():
    """Close the currently loaded MEX project without deleting it."""
    try:
        current_project_path = get_current_project_path()

        if current_project_path is None:
            return jsonify({
                'success': True,
                'closed': False,
                'generation': get_project_generation(),
                'message': 'No project is currently loaded'
            })

        closed_project_path = str(current_project_path)
        generation = clear_project_path()
        logger.info(f"[OK] Closed MEX project: {closed_project_path}")

        return jsonify({
            'success': True,
            'closed': True,
            'generation': generation,
            'message': 'Project closed successfully',
            'projectPath': closed_project_path
        })
    except Exception as e:
        logger.error(f"Close project error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


_PL_COSTUME_RE = re.compile(r'^Pl([A-Z][a-z])([A-Z][a-z])\.dat$')


def _diet_repair_project_files(files_dir: Path) -> int:
    """Repair Diet-authored costume DATs extracted into a fresh project
    (promote low-poly art, re-align blink anims — the same transform the
    ISO scan applies). The pack's forced-low-poly display lived in its
    hacked main.dol, which project creation replaces with the vanilla DOL;
    without this pass every costume would render near-vanilla. Per-file
    failures keep the original file. Returns the repaired count."""
    from concurrent.futures import ThreadPoolExecutor
    from shared.rendering import lowpoly_promote as lp
    from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
    from core.constants import CHAR_PREFIXES

    prefix_to_char = {v: k for k, v in CHAR_PREFIXES.items()}
    targets = []
    for f in sorted(Path(files_dir).glob('Pl*.dat')):
        m = _PL_COSTUME_RE.match(f.name)
        if m:
            targets.append((f, m.group(1), m.group(2)))

    def repair(entry):
        f, prefix, color = entry
        try:
            van = ensure_vanilla_ref(f.name)
            ftdata = Path(files_dir) / f'Pl{prefix}.dat'
            if not van or not ftdata.exists():
                return 0
            slot = lp.costume_slot_for_code(prefix_to_char.get(prefix, ''), color)
            plan = lp.plan_diet_fix(f, van, ftdata,
                                    costume_slot=slot, diet_source=True)
            if not plan.promote:
                logger.info(f"[create][diet] {f.name}: no repair ({plan.reason})")
                return 0
            tmp = f.with_suffix('.dietfix')
            lp.apply_diet_fix(f, tmp, plan)
            file_retry.replace(tmp, f)
            logger.info(f"[create][diet] repaired {f.name}: {plan.reason}")
            return 1
        except Exception as e:
            logger.warning(f"[create][diet] {f.name} repair failed, keeping original: {e}")
            try:
                f.with_suffix('.dietfix').unlink(missing_ok=True)
            except OSError:
                pass
            return 0

    with ThreadPoolExecutor(max_workers=6) as pool:
        return sum(pool.map(repair, targets))


def _diet_apply_pack_stock_icons(proj_dir: Path, patched_iso: Path) -> int:
    """Overwrite the project's stock-icon assets with the pack's own icons.
    The m-ex install extracts the costume CSPs from the pack's MnSlChr (so
    those already carry its art, like any patched source) but reads stock
    icons from IfAll.dat — which Diet-family packs leave vanilla; their
    icons live in IfAll.usd. Returns the number of icons written."""
    from vault.importing.iso_slot_art import _build_stock_map_for_iso
    from shared.vanilla_extract.vanilla_refs import extract_file_from_iso

    files_dir = proj_dir / 'files'
    assets_dir = proj_dir / 'assets'
    project_file = proj_dir / 'project.mexproj'

    # the pack's stock icons, from ITS IfAll + DOL (extracted to a temp dir)
    stock_map: dict = {}
    stock_tmp = proj_dir / '.diet_portraits_tmp'
    try:
        shutil.rmtree(stock_tmp, ignore_errors=True)
        stock_tmp.mkdir(parents=True, exist_ok=True)
        # native FST reader — wit chokes on the shrunken discs these packs
        # patch into. main.dol is a system file (not in the FST); the stock
        # extractor only reads icon TABLE offsets from it, so the project's
        # own (vanilla) DOL serves.
        for name in ('IfAll.usd', 'IfAll.dat'):
            extract_file_from_iso(patched_iso, name, stock_tmp / name)
        shutil.copyfile(proj_dir / 'sys' / 'main.dol', stock_tmp / 'main.dol')
        stock_map = _build_stock_map_for_iso(stock_tmp, stock_tmp / 'stocks')
    except Exception as e:
        logger.warning(f"[create][diet] stock icon extraction failed: {e}")

    # collect every fighter's in-ISO costumes (internal ids 0-25)
    stocks = 0
    for fid in range(26):
        result = mexcli.commands.run_json(['get-costumes', str(project_file), str(fid)],
                                 first_brace=True, returncode=False)
        if not result.get('success'):
            continue
        for c in result.get('costumes', []):
            icon = c.get('icon')
            stem = Path((c.get('fileName') or '').rstrip('.')).stem
            stock_png = stock_map.get(stem.lower())
            if icon and stock_png and os.path.exists(stock_png):
                try:
                    target = assets_dir / f"{icon}.png"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(stock_png, target)
                    stocks += 1
                except Exception as e:
                    logger.warning(f"[create][diet] stock copy failed for "
                                   f"{stem}: {e}")

    try:
        shutil.rmtree(stock_tmp, ignore_errors=True)
    except OSError:
        pass
    return stocks


@project_bp.route('/api/mex/project/create', methods=['POST'])
def create_project():
    """Create a new MEX project from a vanilla ISO.

    Optionally accepts a vault xdelta patchId: the patch is applied to the
    vanilla ISO first and the project is created from the patched ISO.
    `starterCodes: true` (sent by the Projects page) also adds the codes a
    user's new project starts with (required_codes.new_project_gecko_codes).
    """
    temp_patched_iso = None
    try:
        data = request.json or {}
        iso_path = data.get('isoPath')
        patch_id = data.get('patchId')
        starter_codes = data.get('starterCodes') is True
        requested_project_name = (data.get('projectName') or '').strip()
        proj_dir = get_next_project_directory(requested_project_name)
        project_name = requested_project_name or proj_dir.name

        logger.info(f"=== CREATE PROJECT REQUEST ===")
        logger.info(f"ISO Path: {iso_path}")
        logger.info(f"Patch ID: {patch_id or '(none, vanilla)'}")
        logger.info(f"Projects Root: {PROJECTS_PATH}")
        logger.info(f"Project Dir: {proj_dir}")
        logger.info(f"Project Name: {project_name}")

        if not iso_path:
            return jsonify({
                'success': False,
                'error': 'Missing isoPath parameter'
            }), 400

        # Validate ISO exists
        iso_file = Path(iso_path)
        if not iso_file.exists():
            return jsonify({
                'success': False,
                'error': f'ISO file not found: {iso_path}'
            }), 404

        # Apply a vault xdelta patch on top of the vanilla ISO first if requested
        if patch_id:
            from projects.install.xdelta import XDELTA_PATH, require_xdelta_exe, load_xdelta_metadata

            patch = next((p for p in load_xdelta_metadata() if p['id'] == patch_id), None)
            if not patch:
                return jsonify({
                    'success': False,
                    'error': f'Patch not found in vault: {patch_id}'
                }), 404

            xdelta_file = XDELTA_PATH / f"{patch_id}.xdelta"
            if not xdelta_file.exists():
                return jsonify({
                    'success': False,
                    'error': f'Patch file missing from vault: {patch["name"]}'
                }), 404

            temp_patched_iso = OUTPUT_PATH / f"create_{proj_dir.name}_{patch_id}.iso"
            patch_cmd = [
                str(require_xdelta_exe()), '-d', '-f',
                '-s', str(iso_file),
                str(xdelta_file),
                str(temp_patched_iso)
            ]

            logger.info(f"Applying patch '{patch['name']}' before project creation")
            logger.info(f"Running command: {' '.join(patch_cmd)}")

            patch_result = subprocess.run(
                patch_cmd,
                capture_output=True,
                text=True,
                **get_subprocess_args()
            )

            if patch_result.returncode != 0:
                error_message = patch_result.stderr or patch_result.stdout or 'Unknown xdelta error'
                logger.error(f"xdelta3 failed: {error_message}")
                return jsonify({
                    'success': False,
                    'error': f'Failed to apply patch "{patch["name"]}": {error_message}'
                }), 500

            logger.info(f"[OK] Patched ISO ready: {temp_patched_iso}")
            iso_file = temp_patched_iso

        # Existing m-ex builds (MxDt.dat in the FST, e.g. the Ace build) are
        # ADOPTED by MexCLI — their DOL, codes.gct and MxDt tables are kept, so
        # neither the vanilla-DOL substitution nor the diet repair applies.
        # Diet-family packs (hacked DOL entry, no m-ex) get special handling:
        # MexCLI substitutes the vanilla DOL (the m-ex patch can't apply to
        # theirs) and the extracted costumes get the diet repair pass afterward.
        diet_source = False
        mex_source = False
        if patch_id:
            try:
                from shared.vanilla_extract.vanilla_refs import list_files_in_iso
                mex_source = any(e['name'].lower() == 'mxdt.dat'
                                 for e in list_files_in_iso(iso_file, contains='MxDt'))
            except Exception as e:
                logger.warning(f"[create][mex] m-ex fingerprint check failed: {e}")
            if mex_source:
                logger.info("[create][mex] patched ISO is an existing m-ex build — "
                            "MexCLI will adopt its engine (DOL, codes.gct, MxDt)")
            else:
                try:
                    from shared.rendering.lowpoly_promote import dol_entry_hacked
                    diet_source = dol_entry_hacked(iso_file)
                    if diet_source:
                        logger.info("[create][diet] patched ISO has a custom-engine DOL — "
                                    "vanilla DOL will be substituted and costumes repaired")
                except Exception as e:
                    logger.warning(f"[create][diet] DOL fingerprint check failed: {e}")

        # Call MexCLI create command
        args = ['create', str(iso_file), str(proj_dir), project_name]
        if patch_id:
            # pass the vanilla ISO so MexCLI can backfill CSS icons the
            # patched ISO's menu files couldn't provide
            args.append(str(iso_path))

        logger.info(f"Running command: {' '.join([str(MEXCLI_PATH), *args])}")

        result = mexcli.commands.run(args, check=False)

        logger.info(f"MexCLI stdout:\n{result.stdout}")
        logger.info(f"MexCLI stderr:\n{result.stderr}")
        logger.info(f"MexCLI return code: {result.returncode}")

        if result.returncode != 0:
            error_message = result.stderr or result.stdout or 'Unknown error'
            logger.error(f"MexCLI create failed: {error_message}")
            cleanup_failed_project_directory(proj_dir)
            return jsonify({
                'success': False,
                'error': f'Failed to create project: {error_message}'
            }), 500

        # The created project file should be at projectDir/project.mexproj
        created_project_path = proj_dir / "project.mexproj"

        if not created_project_path.exists():
            logger.error(f"Project file not found after creation: {created_project_path}")
            cleanup_failed_project_directory(proj_dir)
            return jsonify({
                'success': False,
                'error': 'Project was created but .mexproj file not found'
            }), 500

        if diet_source:
            # MexCLI already restored the shared engine files (fighter data,
            # PlCo, EfCoData, HUD, menus) from the vanilla ISO BEFORE the m-ex
            # install, so its edits land on vanilla structures. Here only the
            # costumes need the diet repair, planned against that vanilla data.
            repaired = _diet_repair_project_files(proj_dir / 'files')
            logger.info(f"[create][diet] repaired {repaired} costume DAT(s) in the new project")
            stocks = _diet_apply_pack_stock_icons(proj_dir, iso_file)
            logger.info(f"[create][diet] applied {stocks} pack stock icons")

        # Codes a user's new project starts with (enabled; added only here, never
        # by export, so existing projects are untouched). Opt-in, so the
        # throwaway projects other features create (replay playback, combo
        # videos, test builds) stay plain. Best-effort.
        if starter_codes:
            from projects.install.required_codes import add_new_project_gecko_codes
            add_new_project_gecko_codes(created_project_path,
                                        source_iso=iso_file if patch_id else None)

        logger.info(f"[OK] Project created successfully: {created_project_path}")
        logger.info(f"=== CREATE PROJECT COMPLETE ===")

        return jsonify({
            'success': True,
            'message': 'Project created successfully',
            'projectPath': str(created_project_path),
            'projectDirectory': str(proj_dir),
            'projectsDirectory': str(PROJECTS_PATH),
            'isManagedProject': True
        })

    except Exception as e:
        logger.error(f"Create project error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        if temp_patched_iso is not None and temp_patched_iso.exists():
            try:
                temp_patched_iso.unlink()
                logger.info(f"Deleted temporary patched ISO: {temp_patched_iso}")
            except OSError as cleanup_error:
                logger.warning(f"Could not delete temporary patched ISO: {cleanup_error}")


@project_bp.route('/api/mex/project/delete', methods=['POST'])
@project_check_exempt
def delete_project():
    """Delete an app-managed MEX project directory."""
    try:
        data = request.json or {}
        project_path = data.get('projectPath')

        if not project_path:
            return jsonify({
                'success': False,
                'error': 'No project path provided'
            }), 400

        project_file = Path(project_path)
        if project_file.suffix != '.mexproj':
            return jsonify({
                'success': False,
                'error': 'File must be a .mexproj file'
            }), 400

        project_dir = project_file.parent
        if not is_managed_project_directory(project_dir):
            return jsonify({
                'success': False,
                'error': 'Only app-managed projects can be deleted from Nucleus.'
            }), 403

        managed_root = PROJECTS_PATH.resolve()
        resolved_project_dir = project_dir.resolve()
        if resolved_project_dir == managed_root:
            return jsonify({
                'success': False,
                'error': 'Refusing to delete the managed projects root.'
            }), 400

        current_project_closed = False
        # Under the workspace lock, so a write already running on this project
        # finishes before its directory goes away.
        with mexcli_lock:
            current_project_path = get_current_project_path()
            if current_project_path is not None:
                current_project_closed = current_project_path.resolve() == project_file.resolve()
                if current_project_closed:
                    clear_project_path()
            try:
                if resolved_project_dir.exists():
                    shutil.rmtree(resolved_project_dir)
                    logger.info(f"[OK] Deleted managed project directory: {resolved_project_dir}")
                else:
                    logger.info(f"Managed project directory already missing: {resolved_project_dir}")
            except Exception as e:
                # The close above already happened: say so, or the window keeps
                # showing a project the backend has dropped.
                logger.error(f"Delete project error: {str(e)}", exc_info=True)
                return jsonify({
                    'success': False,
                    'error': str(e),
                    'currentProjectClosed': current_project_closed,
                    'generation': get_project_generation()
                }), 500

        return jsonify({
            'success': True,
            'message': 'Project deleted successfully',
            'deleted': True,
            'projectPath': str(project_file),
            'projectDirectory': str(resolved_project_dir),
            'currentProjectClosed': current_project_closed,
            'generation': get_project_generation()
        })

    except Exception as e:
        logger.error(f"Delete project error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@project_bp.route('/api/mex/fighters', methods=['GET'])
def list_fighters():
    """List all fighters in MEX project"""
    try:
        with mexcli_lock:
            mex = get_mex_manager()
            fighters = mex.list_fighters()

        # Add default stock icon URL for each fighter
        project_path = get_current_project_path()
        project_dir = project_path.parent if project_path else None

        for fighter in fighters:
            name = fighter['name']
            # Find the Normal costume folder (ends with 'Nr') in vanilla assets
            vanilla_dir = VANILLA_ASSETS_DIR / name
            if vanilla_dir.exists():
                for folder in vanilla_dir.iterdir():
                    if folder.is_dir() and folder.name.endswith('Nr'):
                        fighter['defaultStockUrl'] = f"/vanilla/{name}/{folder.name}/stock.png"
                        break

            # Fallback for custom fighters: read stock icon from project assets
            if 'defaultStockUrl' not in fighter and project_dir and fighter.get('isMexFighter'):
                fighter_json = project_dir / 'data' / 'fighters' / f"{fighter['internalId']:03d}.json"
                if fighter_json.exists():
                    import json as _json
                    fdata = _json.load(open(fighter_json))
                    costumes = fdata.get('costumes', [])
                    if costumes:
                        icon_ref = costumes[0].get('icon', '')
                        if icon_ref:
                            fighter['defaultStockUrl'] = f"/assets/{icon_ref.replace(chr(92), '/')}.png"

        return jsonify({
            'success': True,
            'fighters': fighters
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@project_bp.route('/api/mex/fighters/<fighter_name>/costumes', methods=['GET'])
def get_fighter_costumes(fighter_name):
    """Get costumes for a specific fighter"""
    try:
        # get-costumes spawns a MexCLI process that OPENS the workspace. Two
        # concurrent MexCLI processes on one project make one of them fail, and a
        # read racing a reorder/import Save can see a half-written project -- so
        # this read takes the same workspace lock every writer does.
        with mexcli_lock:
            mex = get_mex_manager()
            result = mex._run_command("get-costumes", str(mex.project_path), fighter_name)

        # Add asset URLs to each costume (relative to /api/mex since frontend adds API_URL)
        # URLs carry the file mtime so the browser refetches when an asset is
        # replaced in place (e.g. by the apply-pose flow)
        project_dir = get_current_project_path().parent if get_current_project_path() else None

        def _asset_url(ref):
            rel = ref.replace('\\', '/')
            version = ''
            if project_dir is not None:
                asset_file = project_dir / 'assets' / f"{rel}.png"
                if asset_file.exists():
                    version = f"?v={int(asset_file.stat().st_mtime)}"
            return f"/assets/{rel}.png{version}"

        costumes = result.get('costumes', [])
        from projects.install.project_fighters import vanilla_replacement_target
        for costume in costumes:
            costume['vanillaTarget'] = vanilla_replacement_target(fighter_name, costume)
            if costume.get('csp'):
                costume['cspUrl'] = _asset_url(costume['csp'])
            if costume.get('icon'):
                costume['iconUrl'] = _asset_url(costume['icon'])

        return jsonify({
            'success': True,
            'fighter': result.get('fighter'),
            'costumes': costumes
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@project_bp.route('/api/mex/fighters/<fighter_name>/team-colors', methods=['GET'])
def get_team_colors(fighter_name):
    """Get team color costume indices for a fighter"""
    try:
        current_project_path = get_current_project_path()
        if current_project_path is None:
            return jsonify({'success': False, 'error': 'No project loaded'}), 400

        # Find fighter JSON by scanning files (avoids MexCLI call)
        fighter_json_path, fighter_data = find_fighter_json_by_name(fighter_name)
        if fighter_json_path is None:
            return jsonify({'success': False, 'error': f'Fighter not found: {fighter_name}'}), 404

        return jsonify({
            'success': True,
            'fighter': fighter_name,
            'red': fighter_data.get('redCostumeIndex'),
            'blue': fighter_data.get('blueCostumeIndex'),
            'green': fighter_data.get('greenCostumeIndex')
        })
    except Exception as e:
        logger.error(f"Error getting team colors for {fighter_name}: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@project_bp.route('/api/mex/fighters/<fighter_name>/team-colors', methods=['POST'])
def set_team_color(fighter_name):
    """Set a team color costume index for a fighter"""
    try:
        current_project_path = get_current_project_path()
        if current_project_path is None:
            return jsonify({'success': False, 'error': 'No project loaded'}), 400

        data = request.json
        color = data.get('color')  # 'red', 'blue', or 'green'
        costume_index = data.get('costumeIndex')

        if color not in ('red', 'blue', 'green'):
            return jsonify({'success': False, 'error': f'Invalid color: {color}'}), 400

        if costume_index is None:
            return jsonify({'success': False, 'error': 'costumeIndex is required'}), 400

        # Find fighter JSON by scanning files (avoids MexCLI call)
        fighter_json_path, fighter_data = find_fighter_json_by_name(fighter_name)
        if fighter_json_path is None:
            return jsonify({'success': False, 'error': f'Fighter not found: {fighter_name}'}), 404

        # Validate costume index is within range
        costume_count = len(fighter_data.get('costumes', []))
        if costume_index < 0 or costume_index >= costume_count:
            return jsonify({'success': False, 'error': f'Costume index {costume_index} out of range (0-{costume_count-1})'}), 400

        # Update the team color field
        field_name = f'{color}CostumeIndex'
        fighter_data[field_name] = costume_index

        # Write back to file. Take the workspace lock so this fighter-JSON write
        # can't land in the middle of a background reorder's workspace save
        # (which rewrites the same fighter JSONs).
        with mexcli_lock:
            with file_retry.retry_locked(open, fighter_json_path, 'w', encoding='utf-8') as f:
                json.dump(fighter_data, f, indent=2)

        logger.info(f"Set {color} team color for {fighter_name} to costume index {costume_index}")

        return jsonify({
            'success': True,
            'fighter': fighter_name,
            'color': color,
            'costumeIndex': costume_index
        })
    except Exception as e:
        logger.error(f"Error setting team color for {fighter_name}: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@project_bp.route('/api/mex/project/build', methods=['GET'])
def get_build_info():
    """Get the disc-banner metadata (title/creator/description) + image preview."""
    try:
        current_project_path = get_current_project_path()
        if current_project_path is None:
            return jsonify({'success': False, 'error': 'No project loaded'}), 400

        with mexcli_lock:
            return jsonify(get_mex_manager().get_build())
    except Exception as e:
        logger.error(f"Error getting build info: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@project_bp.route('/api/mex/project/build', methods=['POST'])
def set_build_info():
    """Set disc-banner fields and (optionally) the 96x32 banner image.

    Body: any of shortName, longName, shortMaker, longMaker, description,
    bannerPngBase64 (base64-encoded PNG).
    """
    try:
        current_project_path = get_current_project_path()
        if current_project_path is None:
            return jsonify({'success': False, 'error': 'No project loaded'}), 400

        data = request.json or {}
        allowed = ('shortName', 'longName', 'shortMaker', 'longMaker',
                   'description', 'bannerPngBase64')
        payload = {k: data[k] for k in allowed if k in data}

        if not payload:
            return jsonify({'success': False, 'error': 'No fields to update'}), 400

        with mexcli_lock:
            result = get_mex_manager().set_build(payload)
        logger.info("Updated disc banner info: %s",
                    [k for k in payload if k != 'bannerPngBase64'])
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error setting build info: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


def _exit_now():
    """End the backend at once (the shutdown route), after removing the 3D viewer's
    folders this backend made (0.9.0 smoke tests: they were left behind)."""
    try:
        from shared.routes.viewer import remove_own_viewer_folders
        remove_own_viewer_folders()
    except Exception:  # noqa: BLE001 - leftovers are swept at the next start; never block the exit
        logger.warning('Shutdown: viewer folders not removed', exc_info=True)
    os._exit(0)


@project_bp.route('/api/mex/shutdown', methods=['POST'])
def shutdown():
    """Shutdown the Flask server -- unless a critical operation is in flight.

    os._exit() kills every in-flight request and worker with the process, and
    the Electron shell calls this the moment the user closes the window. That
    combination truncated ISO downloads mid-stream (a partial ISO boots to a
    black screen), so while anything registered in core.critical_ops is still
    running this DEFERS: 409 + the operation names. The Electron 'before-quit'
    handler polls until it drains (bounded there, not here).
    """
    import threading
    from core import critical_ops

    ops = critical_ops.active_ops()
    if ops:
        logger.info(f"Shutdown deferred; operations in flight: {ops}")
        return jsonify({'success': False, 'deferred': True, 'operations': ops}), 409

    logger.info("Shutdown request received")
    # Exit AFTER this response is sent (the old code exited inside the
    # handler, so the caller always saw a dropped connection). os._exit runs no
    # atexit handler, so what this backend leaves behind goes first.
    threading.Timer(0.25, _exit_now).start()
    return jsonify({'success': True, 'message': 'Server shutting down...'})
