"""
Setup Blueprint - First-run setup and auto-detection.

Handles first-run setup process, auto-detection of Slippi/ISO paths, the logs
download and the in-app bug report (the logs zip and the worker settings are
the engine shared/diagnostics/bug_report.py).
"""

import os
import sys
import json
import shutil
import hashlib
import logging
from datetime import datetime
from pathlib import Path

import requests
from flask import Blueprint, request, jsonify, send_file

from core import jobs
from core.config import PROJECT_ROOT, MEXCLI_PATH, bugreport_channel
from core.constants import VANILLA_ISO_MD5
from shared.diagnostics.bug_report import (
    _BUGREPORT_DESCRIPTION_MAX, _BUGREPORT_URL, _BUGREPORT_ZIP_BUDGET,
    _build_logs_zip, _bugreport_auth_headers,
)
from shared.ingame.boot import parse_dolphin_ini_iso_path, slippi_user_dir
from shared.vanilla_extract.first_run_setup import FirstRunSetup
from shared.vanilla_extract.vanilla_refs import record_vanilla_iso

logger = logging.getLogger(__name__)

setup_bp = Blueprint('setup', __name__)

_iso_verification_cache = {}

SETUP_KIND = 'first_run_setup'


def _clean_setup(name, value):
    """Remove the temporary project (an extracted ISO) a setup still owned when
    it ended or Nucleus died (core/jobs.py)."""
    path = Path(value)
    if name == 'temp' and path.name.startswith('nucleus_setup_') and path.exists():
        shutil.rmtree(path)
    return None


jobs.register_kind(SETUP_KIND, label='First-time setup', cleanup=_clean_setup)


# Vanilla Melee 1.02 disc size in bytes.
VANILLA_ISO_EXPECTED_SIZE = 1459978240

# Cache a small number of recent ISO verifications so auto-detect and setup/start
# do not re-hash the same unchanged file back-to-back.
ISO_VERIFICATION_CACHE_LIMIT = 16


def _get_iso_cache_key(iso_path: str | Path) -> tuple[str, int, int, int]:
    """Build a cache key from the resolved path plus file metadata."""
    iso_file = Path(iso_path).resolve()
    stat = iso_file.stat()
    return (
        str(iso_file).lower(),
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
    )


def clear_iso_verification_cache():
    """Clear the in-memory ISO verification cache."""
    _iso_verification_cache.clear()


def verify_iso_file(iso_path: str | Path) -> dict:
    """Verify a Melee ISO, reusing cached results when the file is unchanged."""
    iso_file = Path(iso_path).resolve()
    cache_key = _get_iso_cache_key(iso_file)
    cached_result = _iso_verification_cache.get(cache_key)
    if cached_result is not None:
        logger.info(f"Using cached ISO verification: {iso_file}")
        return {
            **cached_result,
            'cached': True
        }

    logger.info(f"Calculating MD5 for: {iso_file}")
    md5_hash = hashlib.md5()

    with open(iso_file, 'rb') as f:
        for chunk in iter(lambda: f.read(8192 * 1024), b''):
            md5_hash.update(chunk)

    calculated_md5 = md5_hash.hexdigest()
    result = {
        'valid': calculated_md5.lower() == VANILLA_ISO_MD5.lower(),
        'md5': calculated_md5,
        'expected': VANILLA_ISO_MD5
    }

    _iso_verification_cache[cache_key] = result
    while len(_iso_verification_cache) > ISO_VERIFICATION_CACHE_LIMIT:
        _iso_verification_cache.pop(next(iter(_iso_verification_cache)))

    return {
        **result,
        'cached': False
    }


def verify_slippi_structure(slippi_path: str) -> bool:
    """Verify that a path has the expected Slippi Dolphin structure."""
    # slippi_user_dir, not <path>/User: Linux Dolphin keeps its tree in
    # ~/.config/SlippiOnline, so the literal check always failed there and
    # auto-detect silently reported "no Slippi found".
    user_dir = slippi_user_dir(slippi_path)

    # Must have a User folder
    if not user_dir.exists() or not user_dir.is_dir():
        return False

    # Should have Config folder (Dolphin creates this)
    config_dir = user_dir / 'Config'
    if not config_dir.exists():
        return False

    return True


# GameCube disc header: bytes 0x00-0x05 = 6-char game ID, byte 0x07 = disc
# version, 0x1C = the GameCube disc magic. Vanilla Melee NTSC 1.02 is "GALE01"
# with version byte 0x02. An NKit image keeps that header and tags 0x200.
MELEE_GAME_ID = b'GALE01'
MELEE_102_VERSION = 0x02
GAMECUBE_DISC_MAGIC = b'\xc2\x33\x9f\x3d'
NKIT_MAGIC = b'NKIT'

# Dolphin's compressed containers start with their own magic instead of a disc
# header: (magic, name, converts back to the original dump byte for byte).
_DISC_CONTAINERS = (
    (b'RVZ\x01', 'RVZ', True),
    (b'WIA\x01', 'WIA', True),
    (b'\x01\xc0\x0b\xb1', 'GCZ', True),
    (b'CISO', 'CISO', False),
)


def _disc_shape_problem(iso_file: Path) -> tuple[str, str] | None:
    """Why a file cannot be vanilla Melee NTSC 1.02, judged from its first
    bytes and its size, as (reason, message); None when the container, disc
    ID, revision and size all match (then only the MD5 can tell a modded
    build from the original).

    Reads 0x204 bytes, so it rejects other games and formats before any
    full-file MD5. A read failure raises OSError: an unreadable file must
    never be reported as "not Melee 1.02".
    """
    with open(iso_file, 'rb') as f:
        header = f.read(0x204)
    size = iso_file.stat().st_size

    for magic, name, lossless in _DISC_CONTAINERS:
        if header.startswith(magic):
            fix = ("Convert it back in Dolphin (right-click the game > Convert File..., "
                   "Format: ISO) and choose the new .iso." if lossless
                   else "Use a full, uncompressed 1.02 dump instead.")
            return 'compressed', (f"This is a compressed {name} image, not a plain ISO. "
                                  f"Nucleus needs the full, uncompressed Melee 1.02 ISO. {fix}")
    if header[0x200:0x204] == NKIT_MAGIC:
        return 'nkit', ("This is an NKit image: a shrunk dump that Dolphin and Slippi play "
                        "but Nucleus cannot use. Restore the full ISO with NKit's "
                        "ConvertToISO, or use a full 1.02 dump.")
    if header[0x1C:0x20] != GAMECUBE_DISC_MAGIC:
        return 'not_gamecube', "This file is not a GameCube disc image."
    if header[:6] != MELEE_GAME_ID:
        game_id = header[:6].decode('ascii', 'replace')
        what = 'another region of Melee' if header[:3] == b'GAL' else 'a different game'
        return 'wrong_game', (f"This is {what} (disc ID {game_id}). Nucleus needs the "
                              f"North American (NTSC) Melee disc, ID GALE01.")
    if header[7] != MELEE_102_VERSION:
        return 'wrong_version', (f"This is Melee NTSC 1.0{header[7]}, not 1.02. "
                                 f"Nucleus needs revision 1.02, the one Slippi uses.")
    if size != VANILLA_ISO_EXPECTED_SIZE:
        return 'trimmed', (f"This is Melee NTSC 1.02, but the file is {size:,} bytes "
                           f"instead of {VANILLA_ISO_EXPECTED_SIZE:,}: it was trimmed or "
                           f"shrunk. Use a full 1.02 dump.")
    return None


def _unreadable_problem(err: OSError, what: str = 'this file') -> tuple[str, str]:
    """The (reason, message) for a file or folder the OS refused to read."""
    message = f"Nucleus cannot read {what}: {err.strerror or err}."
    if isinstance(err, PermissionError):
        if sys.platform == 'darwin':
            # macOS privacy (TCC) gates Downloads/Documents/Desktop, iCloud
            # Drive and external drives per app. The backend's reads prompt in
            # the app's name (often at first launch, from auto-detect), and a
            # "Don't Allow" sticks: every later read fails with EPERM.
            message += (" macOS is blocking Nucleus from this folder. In System Settings > "
                        "Privacy & Security > Files and Folders (or Full Disk Access), allow "
                        "SSBM Nucleus, or move the ISO to a plain folder in your home folder "
                        "such as ~/Melee, then try again.")
        else:
            message += (" Check the file's permissions, or copy it to a folder you own, "
                        "then try again.")
    return 'unreadable', message


def check_vanilla_iso(iso_path: str | Path) -> dict:
    """MD5-verify a user-chosen ISO and say why when it is not usable.

    Returns verify_iso_file's result, plus 'reason', 'message' and an HTTP
    'status' when it fails. A missing or unreadable file has no 'md5': it was
    never verified, and is reported as such rather than as "not vanilla".
    """
    iso_file = Path(iso_path)
    try:
        verification = verify_iso_file(iso_file)
        if verification['valid']:
            return {**verification, 'status': 200}
        reason, message = _disc_shape_problem(iso_file) or ('modified', (
            f"This is a Melee NTSC 1.02 disc of the right size, but its contents differ "
            f"from the original (MD5 {verification['md5']}, expected {VANILLA_ISO_MD5}): "
            f"a modded build or a scrubbed dump. Slippi accepts some scrubbed dumps; "
            f"Nucleus needs the unmodified 1.02 dump."))
        status = 400
    except FileNotFoundError:
        verification, reason, message, status = {}, 'not_found', 'ISO file not found', 404
    except OSError as e:
        verification = {}
        reason, message = _unreadable_problem(e)
        status = 403 if isinstance(e, PermissionError) else 500
    logger.warning(f"ISO rejected ({reason}): {iso_file}: {message}")
    return {**verification, 'valid': False, 'reason': reason, 'message': message,
            'status': status}


# Filename hints. Vanilla dumps are usually named plainly (Melee / SSBM /
# vanilla / 1.02); mod builds carry a tell in the name (20XX, m-ex, Akaneia,
# Ace, training, etc.). We can't tell vanilla from a mod by the disc header
# (both are GALE01 v1.02, same size), so we MD5 — but ordering candidates by
# these hints means the real vanilla is almost always hashed FIRST and we
# early-exit, instead of hashing a modded build (e.g. acebuild.iso) first.
_VANILLA_NAME_HINTS = ('vanilla', 'melee', 'ssbm', 'smashmelee', '1.02', 'v1.02',
                       'ntsc', 'gale01')
_MOD_NAME_HINTS = ('mod', 'ace', '20xx', 'mex', 'm-ex', 'akaneia', 'training',
                   'tournament', 'beyond', 'diet', 'widescreen', 'netplay',
                   'build', 'mango', 'uncle', 'hax', 'crazy', 'summit', 'slippi')


def _vanilla_name_score(iso_path: Path) -> int:
    """Higher = more likely to be the plain vanilla dump (hash it sooner)."""
    name = iso_path.stem.lower()
    score = 0
    if name in ('melee', 'vanilla', 'ssbm', 'ssbm melee', 'super smash bros melee'):
        score += 100
    for hint in _VANILLA_NAME_HINTS:
        if hint in name:
            score += 10
    for hint in _MOD_NAME_HINTS:
        if hint in name:
            score -= 25
    # plain/short names (e.g. "Melee.iso") lean vanilla; long descriptive names
    # are usually mods ("z20XX 4.05 Corona Beginnings").
    score -= len(name) // 12
    return score


def find_vanilla_melee_iso(folder: str, deep_verify: bool = True) -> str:
    """Scan a folder for a vanilla Melee 1.02 ISO.

    Filters to .iso/.gcm files whose disc header and size match GALE01 v1.02
    (`_disc_shape_problem`), then — because a modded 1.02 build shares both —
    confirms by MD5.
    Candidates are tried in filename-likelihood order (`_vanilla_name_score`) so
    the genuine vanilla dump is normally the FIRST (and only) file hashed; we
    early-exit on the first MD5 match. Results are cached, so /setup/start's
    re-verify is then instant.

    ``deep_verify=False`` returns the best-named size+header candidate WITHOUT
    hashing (used only where a cheap guess is acceptable). Auto-detect uses the
    default (True): an earlier header-only shortcut wrongly picked a modded
    acebuild.iso because it can't be distinguished from vanilla without the MD5.

    A folder the OS refuses to list raises OSError (macOS privacy blocks
    ~/Downloads and friends): `glob` swallowed that and reported an empty
    folder, so a blocked folder read as "no ISO here".
    """
    folder_path = Path(folder)
    if not folder_path.is_dir():
        return None

    iso_files = [f for f in folder_path.iterdir() if f.suffix.lower() in ('.iso', '.gcm')]

    # First narrow to real Melee-1.02 candidates by the cheap header + size
    # check (rejects other games, other revisions and compressed images
    # without hashing them).
    candidates = []
    for iso_file in iso_files:
        try:
            problem = _disc_shape_problem(iso_file)
        except OSError as e:
            problem = _unreadable_problem(e)
        if problem:
            logger.info(f"Skipping {iso_file} ({problem[0]}): {problem[1]}")
            continue
        candidates.append(iso_file)

    if not candidates:
        return None

    # A modded build (acebuild.iso, 20XX, …) has the SAME header + size as
    # vanilla, so hash to confirm — but try the most vanilla-looking name first
    # so the genuine dump is normally the only file hashed (early-exit below).
    candidates.sort(key=_vanilla_name_score, reverse=True)

    if not deep_verify:
        logger.info(f"Best-named vanilla candidate (no hash): {candidates[0]}")
        return str(candidates[0])

    for iso_file in candidates:
        try:
            logger.info(f"Checking ISO: {iso_file}")
            if verify_iso_file(iso_file)['valid']:
                logger.info(f"Found vanilla Melee ISO: {iso_file}")
                return str(iso_file)
            logger.info(f"Not vanilla (modded build?): {iso_file}")
        except Exception as e:
            logger.warning(f"Error hashing ISO {iso_file}: {e}")
            continue

    return None


@setup_bp.route('/api/mex/setup/status', methods=['GET'])
def check_setup_status():
    """Check if first-run setup is needed."""
    try:
        setup = FirstRunSetup(PROJECT_ROOT, MEXCLI_PATH)
        status = setup.check_setup_needed()
        logger.info(f"[Setup Status] complete={status.get('complete')}, reason={status.get('reason')}, details={status.get('details')}")
        return jsonify({
            'success': True,
            **status,
        })
    except Exception as e:
        logger.error(f"Setup status check error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@setup_bp.route('/api/mex/setup/health', methods=['POST'])
def setup_health():
    """Boot-time setup health check.

    Unlike /setup/status (vanilla assets only), this also validates the saved
    vanilla ISO path the viewer keeps client-side (localStorage) — so the app
    can surface a "re-run first-run setup" notice when the assets look fine but
    the ISO was never configured in this profile, or has since moved/changed.
    ISO checks are cheap (exists + size + 8-byte GALE01 header): no hashing at
    boot.
    """
    try:
        data = request.json or {}
        iso_path = (data.get('isoPath') or '').strip()

        problems = []

        setup = FirstRunSetup(PROJECT_ROOT, MEXCLI_PATH)
        status = setup.check_setup_needed()
        if not status.get('complete'):
            problems.append({
                'id': f"assets_{status.get('reason', 'incomplete')}",
                'message': f"Vanilla assets are incomplete: {status.get('details', 'unknown problem')}."
            })

        if not iso_path:
            problems.append({
                'id': 'iso_not_configured',
                'message': 'No vanilla Melee ISO is saved. Features that build '
                           'projects or extract assets will ask for one.'
            })
        else:
            iso_file = Path(iso_path)
            try:
                missing = not iso_file.is_file()
                problem = None if missing else _disc_shape_problem(iso_file)
            except OSError as e:
                missing, problem = False, _unreadable_problem(e)
            if missing:
                problems.append({
                    'id': 'iso_missing',
                    'message': f'The saved vanilla ISO no longer exists: {iso_path}'
                })
            else:
                if problem:
                    reason, message = problem
                    problems.append({
                        'id': 'iso_unreadable' if reason == 'unreadable' else 'iso_invalid',
                        'message': f'The saved vanilla ISO ({iso_path}) can no longer '
                                   f'be used. {message}'
                    })
                else:
                    # Remember the ISO backend-side so features that need
                    # vanilla bytes outside a request that carries the path
                    # (extras vanilla references) can find it. Runs on every
                    # boot, so existing installs pick it up after updating.
                    record_vanilla_iso(iso_file)

        if problems:
            logger.info(f"[Setup Health] {len(problems)} problem(s): "
                        + " | ".join(f"{p['id']}: {p['message']}" for p in problems))

        return jsonify({'success': True, 'problems': problems})
    except Exception as e:
        logger.error(f"Setup health check error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def _run_setup(job, iso_path):
    """The first-run setup job: verify the ISO, then extract and copy the vanilla
    assets. Returns ``{message, characters, stages, isoPath}``; a rejected ISO or
    a failed step fails the job with its message."""
    iso_file = Path(iso_path)
    # Verify ISO hash first. This reuses the cached result from auto-detect
    # or /verify-iso when the file metadata has not changed. A rejection
    # carries its reason (not found, unreadable, compressed, NKit, wrong
    # disc/revision, trimmed, modified) so the user sees what to fix.
    job.progress(0, 'Verifying ISO…', phase='verifying')
    logger.info(f"Verifying ISO before setup: {iso_path}")
    verification = check_vanilla_iso(iso_file)
    if not verification['valid']:
        job.progress(reason=verification['reason'], md5=verification.get('md5'))
        raise ValueError(verification['message'])

    # The ISO just MD5-verified as vanilla 1.02 -- the strongest record
    # signal we ever get (setup/health only checks size + header).
    record_vanilla_iso(iso_file)

    def progress(phase, percentage, message, completed, total):
        job.progress((percentage or 0) / 100, message, phase=phase,
                     completed=completed, total=total)

    # The job owns the temporary project, so one Nucleus died in is removed at
    # the next start (_clean_setup).
    result = FirstRunSetup(PROJECT_ROOT, MEXCLI_PATH).run_setup(
        iso_path, progress, on_temp_dir=lambda path: job.own('temp', str(path)))
    if not result['success']:
        raise RuntimeError(result.get('error') or 'Unknown error')
    return {
        'message': result.get('message', 'Setup complete'),
        'characters': result.get('characters', 0),
        'stages': result.get('stages', 0),
        'isoPath': iso_path,
    }


@setup_bp.route('/api/mex/setup/start', methods=['POST'])
def start_first_run_setup():
    """Start first-run setup as a job (core/jobs.py) and return its id at once.

    The job verifies the ISO, then extracts the assets; the wizard follows it
    from the job store, so leaving the wizard never loses it. A second start
    while one runs gets 409 with the running job's id.
    """
    data = request.get_json(silent=True) or {}
    iso_path = data.get('isoPath')
    if not iso_path or not isinstance(iso_path, str):
        return jsonify({'success': False, 'error': 'No ISO path provided'}), 400
    try:
        job_id = jobs.start(SETUP_KIND, lambda job: _run_setup(job, iso_path),
                            label='First-time setup', params={'isoPath': iso_path}, single=True)
    except jobs.JobBusy as busy:
        return jsonify({'success': False, 'error': 'Setup already in progress',
                        'jobId': busy.job_id}), 409
    except Exception as e:
        logger.error(f"Start setup error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True, 'message': 'Setup started', 'jobId': job_id})


@setup_bp.route('/api/mex/setup/auto-detect', methods=['GET'])
def auto_detect_paths():
    """Auto-detect Slippi Dolphin path and vanilla Melee ISO."""
    result = {
        'slippiPath': None,
        'isoPath': None,
        'isoFolderPath': None,
        'isoProblem': None,
    }

    try:
        # 1. Check default Slippi path. Off Windows the Slippi Launcher drops
        # the same netplay/ layout under ~/.config -- returning early on a
        # missing APPDATA skipped BOTH Slippi and (below) ISO auto-detection,
        # so Linux first-run setup always came up empty.
        appdata = os.environ.get('APPDATA', '')
        if appdata:
            default_slippi = os.path.join(appdata, 'Slippi Launcher', 'netplay')
        elif sys.platform == 'darwin':
            # macOS keeps it under Application Support, not XDG.
            default_slippi = os.path.join(
                os.path.expanduser('~'), 'Library', 'Application Support',
                'Slippi Launcher', 'netplay')
        else:
            default_slippi = os.path.join(
                os.path.expanduser('~'), '.config', 'Slippi Launcher', 'netplay')
        logger.info(f"Checking default Slippi path: {default_slippi}")

        if os.path.isdir(default_slippi):
            if verify_slippi_structure(default_slippi):
                result['slippiPath'] = default_slippi
                logger.info(f"Found valid Slippi installation: {default_slippi}")
            else:
                logger.info(f"Path exists but structure invalid: {default_slippi}")
        else:
            logger.info(f"Default Slippi path not found: {default_slippi}")

        # 2. Parse dolphin.ini for ISO path
        if result['slippiPath']:
            dolphin_ini = str(slippi_user_dir(result['slippiPath']) / 'Config' / 'Dolphin.ini')
            logger.info(f"Checking Dolphin.ini: {dolphin_ini}")

            if os.path.isfile(dolphin_ini):
                iso_dir = parse_dolphin_ini_iso_path(dolphin_ini)
                if iso_dir:
                    result['isoFolderPath'] = iso_dir
                    logger.info(f"Found ISO folder: {iso_dir}")

                    # 3. Scan folder for the vanilla Melee ISO. Hash-confirmed
                    # (a modded build shares vanilla's header+size), but tried in
                    # filename-likelihood order so the real dump is normally the
                    # only file hashed — fast in the common case, correct always.
                    try:
                        vanilla_iso = find_vanilla_melee_iso(iso_dir)
                    except OSError as e:
                        vanilla_iso = None
                        result['isoProblem'] = _unreadable_problem(
                            e, f'your Dolphin ISO folder {iso_dir}')[1]
                        logger.warning(f"ISO folder unreadable: {result['isoProblem']}")
                    if vanilla_iso:
                        result['isoPath'] = vanilla_iso
                        logger.info(f"Found vanilla Melee ISO: {vanilla_iso}")
                    else:
                        logger.info(f"No vanilla Melee ISO found in: {iso_dir}")
                else:
                    logger.info("No ISO directory found in Dolphin.ini")
            else:
                logger.info(f"Dolphin.ini not found: {dolphin_ini}")

        return jsonify({'success': True, **result})

    except Exception as e:
        logger.error(f"Auto-detect error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@setup_bp.route('/api/mex/verify-iso', methods=['POST'])
def verify_vanilla_iso():
    """Verify that an ISO file is a valid vanilla Melee 1.02 ISO."""
    try:
        data = request.json or {}
        iso_path = data.get('isoPath')

        if not iso_path:
            return jsonify({
                'success': False,
                'error': 'No ISO path provided'
            }), 400

        verification = check_vanilla_iso(iso_path)
        if 'md5' not in verification:
            # Missing or unreadable: never verified, so not "invalid" either.
            return jsonify({
                'success': False,
                'error': verification['message'],
                'reason': verification['reason'],
            }), verification['status']
        logger.info(f"ISO MD5: {verification['md5']} (valid: {verification['valid']}, cached: {verification['cached']})")

        return jsonify({
            'success': True,
            'valid': verification['valid'],
            'md5': verification['md5'],
            'expected': verification['expected'],
            'reason': verification.get('reason'),
            'message': verification.get('message'),
        })
    except Exception as e:
        logger.error(f"Verify ISO error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@setup_bp.route('/api/mex/logs/download', methods=['GET'])
def download_logs_zip():
    """Bundle the app's log files into a single zip the user can attach to a bug
    report. Built in-memory and streamed as a timestamped download. Includes a
    diagnostics.txt with basic system info. Safe even if the logs folder is empty
    (the zip still carries the diagnostics).

    If a `slippiPath` query param is given (the user's Slippi Dolphin folder), the
    zip also gathers Slippi Dolphin's own logs + crash dumps under slippi-dolphin/
    — so a crash playing a Nucleus-built ISO in their Slippi Dolphin is debuggable
    too, not just issues inside our app."""
    try:
        slippi_path = (request.args.get('slippiPath') or '').strip()
        buf, added, slippi_added, _ = _build_logs_zip(slippi_path)
        name = f"nucleus-logs-{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        logger.info(f"Built logs zip '{name}' ({added} app log(s), {slippi_added} Slippi log(s))")
        return send_file(buf, mimetype='application/zip',
                         as_attachment=True, download_name=name)
    except Exception as e:
        logger.error(f"Logs zip error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------------------------------------------------------------------------
# In-app bug reports (the worker URL, budget and Discord bearer are in
# shared/diagnostics/bug_report.py, which the Randall report routes share)
# ---------------------------------------------------------------------------

@setup_bp.route('/api/mex/bugreport', methods=['POST'])
def submit_bug_report():
    """Send a bug report: description + the same logs zip as /logs/download,
    uploaded privately to the bugreport worker (R2 + private Discord channel).

    Passes the worker's version gate through: an outdated client gets HTTP 426
    with {error: 'update_required', latest, url} so the UI can say "update
    first" — that gate is also enforced client-side before the form shows."""
    try:
        body = request.get_json(silent=True) or {}
        description = (body.get('description') or '').strip()
        if not description:
            return jsonify({'success': False, 'error': 'A description is required'}), 400
        if len(description) > _BUGREPORT_DESCRIPTION_MAX:
            description = description[:_BUGREPORT_DESCRIPTION_MAX]
        contact = (body.get('contact') or '').strip()[:200]
        slippi_path = (body.get('slippiPath') or '').strip()
        app_version = (os.environ.get('NUCLEUS_APP_VERSION')
                       or (body.get('app_version') or '').strip())
        if not app_version:
            return jsonify({'success': False, 'error': 'App version unknown'}), 400
        channel = bugreport_channel()
        electron = body.get('electron') if isinstance(body.get('electron'), dict) else None
        renderer_errors = body.get('renderer_errors')
        if not isinstance(renderer_errors, list):
            renderer_errors = []
        renderer_errors = renderer_errors[:50]

        # The zip is self-describing even if the worker-side meta is ever lost.
        extra = {
            'report.json': json.dumps({
                'description': description,
                'contact': contact,
                'app_version': app_version,
                'platform': channel,
                'submitted': datetime.now().isoformat(),
            }, indent=2),
        }
        if electron:
            extra['electron-diagnostics.json'] = json.dumps(electron, indent=2)
        if renderer_errors:
            extra['renderer-errors.json'] = json.dumps(renderer_errors, indent=2)

        buf, added, slippi_added, truncated = _build_logs_zip(
            slippi_path, extra_files=extra, budget_bytes=_BUGREPORT_ZIP_BUDGET)
        zip_bytes = buf.getvalue()

        meta = {
            'app_version': app_version,
            'platform': channel,
            'description': description,
            'contact': contact,
            'zip_size': len(zip_bytes),
            'electron': electron,
            'renderer_errors': renderer_errors,
            'truncated': truncated,
        }
        resp = requests.post(_BUGREPORT_URL, json=meta,
                             headers=_bugreport_auth_headers(), timeout=15)
        if resp.status_code in (426, 429):
            payload = {}
            try:
                payload = resp.json() or {}
            except ValueError:
                pass
            error = 'update_required' if resp.status_code == 426 else 'rate_limited'
            out = {'success': False, 'error': error}
            for key in ('latest', 'url', 'notes', 'retry_after'):
                if payload.get(key) is not None:
                    out[key] = payload[key]
            return jsonify(out), resp.status_code
        if not resp.ok:
            raise RuntimeError(f'Report server refused the report (HTTP {resp.status_code})')
        report_id = (resp.json() or {}).get('id')
        if not report_id:
            raise RuntimeError('Report server returned no id')

        upload = requests.put(f'{_BUGREPORT_URL}/{report_id}/zip', data=zip_bytes,
                              headers={'Content-Type': 'application/zip'}, timeout=180)
        if not upload.ok:
            raise RuntimeError(f'Log upload failed (HTTP {upload.status_code})')
        notified = False
        try:
            notified = bool((upload.json() or {}).get('notified'))
        except ValueError:
            pass
        logger.info(f"Bug report {report_id} sent ({len(zip_bytes)} bytes, "
                    f"{added} app log(s), {slippi_added} Slippi log(s), notified={notified})")
        return jsonify({'success': True, 'id': report_id, 'notified': notified,
                        'size': len(zip_bytes), 'truncated': truncated})
    except requests.RequestException as e:
        logger.error(f"Bug report network error: {e}")
        return jsonify({'success': False, 'error': 'Could not reach the report server'}), 502
    except Exception as e:
        logger.error(f"Bug report error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
