"""
Gecko Codes endpoints, project side: the codes in the open project.

Reads <project>/files/codes.ini directly (trivial INI format, parsed by
core.gecko) and writes changes through `mexcli sync-codes`, which replaces the
code list and recompiles files/codes.gct without a full workspace save. Also
lists what the user's Slippi Dolphin applies at runtime.

These routes register on `codes_bp` from vault/routes/codes.py (the vault
Codes section), so URLs and endpoint names are unchanged; the vault catalog they
read is vault/catalog/codes.py.
"""

import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path
from flask import request, jsonify

from core.config import MEXCLI_PATH, get_subprocess_args
from core.state import get_current_project_path, get_project_files_dir, reload_mex_manager
from core.gecko import (
    header,
    parse_ini,
    serialize_ini,
    split_header,
    validate_source,
)
from projects.install.required_codes import REQUIRED_GECKO_CODES
from vault.catalog.codes import _entry_header, _load_catalog
from vault.routes.codes import codes_bp

logger = logging.getLogger(__name__)


# Default-on code headers (lowercased), from export.py's list (full
# "Name [Creator]" headers). They start enabled in every project, but the user
# may turn them off: Skip Slippi SSS is needed for Slippi Dolphin yet crashes
# some Slippi Nintendont setups at stage select (tracker #89). An off choice is
# persisted as a DISABLED entry in codes.ini, which export's idempotent
# `mexcli add-code` then leaves alone.
REQUIRED_HEADERS = {name.lower() for name, _ in REQUIRED_GECKO_CODES}


def _project_codes_ini():
    files_dir = get_project_files_dir()
    return Path(files_dir) / 'codes.ini'


@codes_bp.route('/api/mex/codes/project', methods=['GET'])
def get_project_codes():
    """List the codes currently in the open project's codes.ini."""
    try:
        if get_current_project_path() is None:
            return jsonify({'success': False, 'error': 'No MEX project loaded'}), 400

        ini = _project_codes_ini()
        raw = ini.read_text(encoding='utf-8', errors='replace') if ini.exists() else ''
        parsed = parse_ini(raw)

        # Collapse exact duplicates (same header AND same hex) — the historical
        # add-code dedupe bug appended identical required codes on every export.
        seen = {}
        duplicates = 0
        for c in parsed:
            key = (header(c['name'], c['creator']).lower(),
                   ''.join(c['source'].split()).lower())
            if key in seen:
                duplicates += 1
                # keep it enabled if any copy was enabled
                seen[key]['enabled'] = seen[key]['enabled'] or c['enabled']
            else:
                seen[key] = c

        vault_by_header = {}
        try:
            for e in _load_catalog():
                vault_by_header[_entry_header(e).lower()] = e
        except Exception:
            logger.warning('vault codes catalog unreadable; inVault flags skipped')

        codes = []
        for c in seen.values():
            h = header(c['name'], c['creator'])
            vault_entry = vault_by_header.get(h.lower())
            codes.append({
                'name': c['name'],
                'creator': c['creator'],
                'description': c['description'],
                'source': c['source'],
                'enabled': c['enabled'],
                'default': h.lower() in REQUIRED_HEADERS,
                'inVault': vault_entry is not None,
                'vaultId': vault_entry['id'] if vault_entry else None,
            })

        # Default codes land (enabled) in every exported ISO unless codes.ini
        # already carries them — export.py adds them via `mexcli add-code`.
        # A never-exported project's codes.ini simply hasn't caught up —
        # surface them anyway so "In this build" tells the truth instead of
        # "No codes in this build yet".
        present = {header(c['name'], c['creator']).lower() for c in seen.values()}
        for full_header, source in REQUIRED_GECKO_CODES:
            if full_header.lower() in present:
                continue
            name, creator = split_header(full_header)
            codes.append({
                'name': name,
                'creator': creator,
                'description': None,
                'source': source,
                'enabled': True,
                'default': True,
                'inVault': False,
                'vaultId': None,
            })

        return jsonify({
            'success': True,
            'codes': codes,
            'duplicatesCollapsed': duplicates,
        })
    except Exception as e:
        logger.error(f'Get project codes error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@codes_bp.route('/api/mex/codes/nucleus', methods=['GET'])
def nucleus_codes():
    """The codes SSBM Nucleus makes itself, offered to any build in the Codes
    modal's code list (first in their category). New projects already start with them
    (required_codes.new_project_gecko_codes); this is how an existing build
    gets one. `iniName` + `creator` is the header it takes in codes.ini.
    `conflict` says why a build should not take it (Now Playing on a build
    that already draws the song name would draw it twice)."""
    from projects.nowplaying import code as now_playing
    try:
        conflict = None
        files_dir = get_project_files_dir() if get_current_project_path() is not None else None
        if files_dir and next(Path(files_dir).rglob(now_playing.CONFLICTING_FILE), None):
            conflict = 'This build already shows the song name, so this would show it twice.'
        name, creator = split_header(now_playing.CODE_HEADER)
        return jsonify({'success': True, 'codes': [{
            'id': 'nucleus-now-playing',
            'title': now_playing.TITLE,
            'iniName': name,
            'creator': creator,
            'description': now_playing.DESCRIPTION,
            'source': now_playing.source(),
            'conflict': conflict,
        }]})
    except Exception as e:
        logger.error(f'Nucleus codes error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@codes_bp.route('/api/mex/codes/project/sync', methods=['POST'])
def sync_project_codes():
    """Replace the project's code list with the FULL desired state.
    Body: {codes: [{name, creator, description, source, enabled}]}."""
    try:
        if get_current_project_path() is None:
            return jsonify({'success': False, 'error': 'No MEX project loaded'}), 400
        if not MEXCLI_PATH.exists():
            return jsonify({'success': False, 'error': f'MexCLI not found at {MEXCLI_PATH}'}), 500

        payload = request.get_json(silent=True) or {}
        desired = payload.get('codes')
        if desired is None:
            return jsonify({'success': False, 'error': 'codes list missing'}), 400

        # Pre-validate everything before touching the project.
        errors = []
        cleaned = []
        for c in desired:
            name = (c.get('name') or '').strip()
            if not name:
                errors.append({'name': '', 'error': 'missing name'})
                continue
            check = validate_source(c.get('source') or '')
            if not check['ok']:
                errors.append({'name': name, 'error': check['error']})
                continue
            cleaned.append({
                'name': name,
                'creator': (c.get('creator') or '').strip(),
                'description': c.get('description') or '',
                'source': c['source'],
                'enabled': bool(c.get('enabled')),
            })
        if errors:
            return jsonify({'success': False, 'error': 'invalid codes', 'codes': errors}), 400

        # Default codes honour the user's enabled flag. One missing from the
        # desired list is kept as a DISABLED entry rather than dropped: export
        # adds any default code codes.ini lacks, so dropping it would silently
        # re-enable it on the next export. The disabled entry is the persisted
        # per-project "off" choice.
        present = {header(c['name'], c['creator']).lower() for c in cleaned}
        for req_header, req_source in REQUIRED_GECKO_CODES:
            if req_header.lower() not in present:
                req_name, req_creator = split_header(req_header)
                cleaned.append({
                    'name': req_name,
                    'creator': req_creator,
                    'description': '',
                    'source': req_source,
                    'enabled': False,
                })

        project_path = get_current_project_path()
        ini_text = serialize_ini(cleaned)

        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.ini', prefix='sync_codes_', delete=False, encoding='utf-8')
        try:
            tmp.write(ini_text)
            tmp.close()
            # sync-codes rewrites codes.ini AND codes.gct. mexcli_lock alone
            # only serialises writers in THIS process; the build lock covers a
            # second Nucleus backend too, and recovers an interrupted change
            # before this one writes over it.
            from core import build_access
            with build_access.build_session(Path(project_path).parent,
                                            timeout=120.0) as session:
                # sync-codes rewrites codes.ini AND codes.gct in one pass. It
                # cannot be undone file by file, so it is bracketed: a death in
                # the middle quarantines the build rather than leaving a code
                # list and a compiled list that disagree.
                with session.external_save('mexcli sync-codes'):
                    result = subprocess.run(
                        [str(MEXCLI_PATH), 'sync-codes', str(project_path), tmp.name],
                        capture_output=True, text=True, timeout=60,
                        **get_subprocess_args()
                    )
                    reload_mex_manager()
                    if result.returncode != 0:
                        # Carry MexCLI's own words: the bracket exists to catch
                        # a half-written save, not to replace the reason.
                        try:
                            reported = (json.loads(result.stdout or '{}') or {}).get('error')
                        except json.JSONDecodeError:
                            reported = None
                        raise build_access.TransactionError(
                            'code_sync_failed',
                            reported or result.stderr or result.stdout
                            or f'mexcli sync-codes exited {result.returncode}')
        finally:
            try:
                Path(tmp.name).unlink()
            except OSError:
                pass

        try:
            out = json.loads(result.stdout or '{}')
        except json.JSONDecodeError:
            out = {}
        if result.returncode != 0 or not out.get('success'):
            err = out.get('error') or result.stderr or result.stdout or 'sync-codes failed'
            logger.error(f'sync-codes failed: {err}')
            return jsonify({'success': False, 'error': err}), 500

        return jsonify({
            'success': True,
            'applied': out.get('count'),
            'enabled': out.get('enabled'),
            'gctBytes': out.get('gctBytes'),
        })
    except Exception as e:
        logger.error(f'Sync project codes error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# ------------------------------------------------- Slippi-applied (runtime)

def _dolphin_gecko_names(ini_path):
    """Gecko code names from a Dolphin GameSettings/Sys INI, as
    (defined, enabled, disabled) name sets.

    Dolphin's per-game INI format: [Gecko] holds full $Name definitions
    (default-off), [Gecko_Enabled]/[Gecko_Disabled] hold bare $Name lines."""
    defined, enabled, disabled = set(), set(), set()
    try:
        text = ini_path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return defined, enabled, disabled
    section = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith('[') and s.endswith(']'):
            section = s[1:-1].lower()
        elif s.startswith('$'):
            name = s[1:].strip()
            if not name:
                continue
            if section == 'gecko':
                defined.add(name)
            elif section == 'gecko_enabled':
                enabled.add(name)
            elif section == 'gecko_disabled':
                disabled.add(name)
    return defined, enabled, disabled


@codes_bp.route('/api/mex/codes/dolphin', methods=['GET'])
def dolphin_applied_codes():
    """Best-effort list of the gecko codes the user's Slippi Dolphin applies at
    RUNTIME — its own Sys defaults plus any user GameSettings overrides. These
    are injected when Dolphin launches the game, layered over whatever the
    exported ISO carries; the UI lists them so "In this build" tells the whole
    story. ?slippiPath = the configured Slippi install (same convention as the
    other slippi endpoints).

    Never errors: when nothing is readable (no Slippi configured, or the
    Dolphin lives inside an AppImage where Sys/ is not on disk) it answers
    available:false and the UI shows a generic note instead."""
    slippi_path = request.args.get('slippiPath') or None
    sys_defined = sys_enabled = set()
    user_layers = []
    try:
        from shared.ingame.boot import resolve_dolphin, slippi_user_dir
        exe = None
        try:
            exe, _tpl = resolve_dolphin(slippi_path)
        except FileNotFoundError:
            pass
        if exe:
            sys_ini = Path(exe).parent / 'Sys' / 'GameSettings' / 'GALE01r2.ini'
            sys_defined, sys_enabled, _ = _dolphin_gecko_names(sys_ini)
        if slippi_path:
            gs_dir = Path(slippi_user_dir(slippi_path)) / 'GameSettings'
            for name in ('GALE01r2.ini', 'GALE01.ini'):
                user_layers.append(_dolphin_gecko_names(gs_dir / name))
    except Exception as e:
        logger.warning(f'dolphin codes probe failed: {e}')

    enabled = set(sys_enabled)
    for _defined, u_enabled, u_disabled in user_layers:
        enabled |= u_enabled
        enabled -= u_disabled
    # Codes defined in Sys but not enabled anywhere are user-toggleable in
    # Dolphin itself; only surface what actually runs.
    if not enabled:
        return jsonify({'success': True, 'available': False, 'codes': []})

    def entry(name):
        # "Name [Creator]" → split for display, same shape as vault codes
        m = re.match(r'^(.*?)\s*\[([^\]]+)\]\s*$', name)
        return ({'name': m.group(1), 'creator': m.group(2)} if m
                else {'name': name, 'creator': None})

    return jsonify({
        'success': True,
        'available': True,
        'codes': [entry(n) for n in sorted(enabled, key=str.lower)],
    })
