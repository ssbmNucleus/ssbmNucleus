"""
Menu background mods, project side: install a vault background into the open
project's CSS (MnSlChr.usd, together with the code that stops the hardcoded
CSS background animation) or SSS (MnSlMap.usd), report whether the CSS
background is custom, and restore the vanilla one.

Registers on `menus_bp` (vault/routes/menus/). The shared background pool,
import and editing are vault/routes/menus/backgrounds.py.
"""

import shutil
import subprocess
import tempfile
import logging
from pathlib import Path
from flask import jsonify

import file_retry
from core.config import HSDRAW_EXE, MEXCLI_PATH, get_subprocess_args
from core.state import get_project_files_dir, get_current_project_path

from vault.routes.menus import menus_bp
from vault.menus.store import BG_PATH
from vault.menus.hsd import _run_hsd_cli
from vault.menus.backgrounds import _attach_bg_urls, _load_bg_mod_json

logger = logging.getLogger(__name__)


@menus_bp.route('/api/mex/menus/css/background/install/<mod_id>', methods=['POST'])
def install_bg_to_mex(mod_id):
    """Install a CSS background mod into the currently loaded MEX project.

    1. Runs HSDRawViewer --css-bg import to swap the background in MnSlChr.usd
    2. Runs mexcli add-code to inject the Gecko code that disables the hardcoded
       CSS background animation, so the custom one is visible.
    """
    try:
        mod = _load_bg_mod_json(mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404

        project_path = get_current_project_path()
        if project_path is None:
            return jsonify({'success': False, 'error': 'No MEX project loaded'}), 400

        files_dir = get_project_files_dir()
        if files_dir is None:
            return jsonify({'success': False, 'error': 'No project files directory'}), 400

        mnslchr_usd = Path(files_dir) / 'MnSlChr.usd'
        if not mnslchr_usd.exists():
            return jsonify({'success': False, 'error': f'MnSlChr.usd not found at {mnslchr_usd}'}), 400

        bg_dat = BG_PATH / mod_id / 'background.dat'
        if not bg_dat.exists():
            return jsonify({'success': False, 'error': 'background.dat missing from mod'}), 400

        if not HSDRAW_EXE.exists():
            return jsonify({'success': False, 'error': f'HSDRawViewer not found at {HSDRAW_EXE}'}), 500

        # One transaction, one lock, one journal. Before this the route copied
        # MnSlChr.usd into the project and then TRIED to add the Gecko code,
        # logging a warning if that failed -- a build with the new backdrop and
        # without the code it needs, reported as a success. Now both land
        # together or neither does, through the same build-access service
        # nucleus_api.builds.commit_change uses. The merge rules are core's
        # (core/gecko_codes.py), which nucleus_api.codes re-exports.
        from core import build_access
        from core.gecko import parse_ini, serialize_ini
        from core import gecko_codes as codes_api

        build_dir = Path(project_path).parent
        required = [{'name': 'Disable Hardcoded CSS BG Anim',
                     'source': '04263384 48000010',
                     'origin': 'required by every CSS background replacement'}]
        try:
            with build_access.build_session(build_dir) as session:
                # A scanner may still hold the output in here; scratch left behind must not fail the install.
                with tempfile.TemporaryDirectory(prefix='cssbg_install_', ignore_cleanup_errors=True) as tmp:
                    output_usd = Path(tmp) / 'MnSlChr.usd'
                    hsd_args = ['--css-bg', 'import',
                                str(mnslchr_usd), str(bg_dat), str(output_usd)]
                    if mod.get('includeScene'):
                        hsd_args.append('--include-scene')
                    if _run_hsd_cli(hsd_args) is None:
                        return jsonify({'success': False,
                                        'error': 'HSDRawViewer --css-bg import failed'}), 500
                    if not output_usd.exists() or not output_usd.stat().st_size:
                        return jsonify({'success': False,
                                        'error': 'Import produced no output file'}), 500

                    ini_path = Path(files_dir) / 'codes.ini'
                    existing = parse_ini(ini_path.read_text(encoding='utf-8', errors='replace'))                         if ini_path.exists() else []
                    merge = codes_api.merge(existing, required, enable_disabled=True)
                    if merge['conflicts']:
                        return jsonify({'success': False,
                                        'error': f'This build already carries a different '
                                                 f'version of the code this background needs: '
                                                 f'{merge["conflicts"]!r}'}), 409
                    session.apply(
                        [{'relpath': 'files/MnSlChr.usd', 'source': str(output_usd),
                          'sha256': None}],
                        label=f'css background {mod_id}',
                        code_ini=serialize_ini(merge['merged']))
        except build_access.BuildBusyError as busy:
            return jsonify({'success': False, 'error': str(busy)}), 409
        except build_access.TransactionError as failed:
            logger.error('CSS background install rolled back: %s', failed)
            return jsonify({'success': False, 'error': str(failed)}), 500

        from vault.menus.installed import record_installed_menu_mod
        record_installed_menu_mod('css:background', 'css_background', _attach_bg_urls(mod))
        msg = f'Installed background "{mod["name"]}". Rebuild ISO to apply.'
        logger.info(f'[OK] Installed CSS background mod {mod_id}')
        return jsonify({'success': True, 'message': msg})

    except Exception as e:
        logger.error(f'Install bg mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# Name of the Gecko code a CSS background install adds (see install above).
CSS_BG_ANIM_CODE = 'Disable Hardcoded CSS BG Anim'


def _project_codes_ini(project_path):
    return Path(project_path).parent / 'files' / 'codes.ini'


def _is_css_bg_code(code):
    return code['name'].strip().lower() == CSS_BG_ANIM_CODE.lower()


def _project_has_css_bg_code(project_path):
    """True when the project carries the code every CSS background install
    adds. Installs from before the per-project record existed are only
    detectable this way."""
    ini = _project_codes_ini(project_path)
    if not ini.exists():
        return False
    from core.gecko import parse_ini
    codes = parse_ini(ini.read_text(encoding='utf-8', errors='replace'))
    return any(_is_css_bg_code(c) for c in codes)


def _drop_css_bg_code(project_path):
    """Remove the 'disable hardcoded BG anim' code so the vanilla backdrop
    animates again. `sync-codes` rewrites codes.ini + codes.gct from the full
    list, so every other code (and its enabled flag) is kept. Returns True
    when the code is gone afterwards."""
    if not _project_has_css_bg_code(project_path):
        return True
    if not MEXCLI_PATH.exists():
        logger.warning(f'  MexCLI not found at {MEXCLI_PATH}; cannot remove {CSS_BG_ANIM_CODE!r}')
        return False
    from core.gecko import parse_ini, serialize_ini
    ini = _project_codes_ini(project_path)
    codes = [c for c in parse_ini(ini.read_text(encoding='utf-8', errors='replace'))
             if not _is_css_bg_code(c)]
    with tempfile.TemporaryDirectory(prefix='cssbg_codes_') as tmp:
        desired = Path(tmp) / 'codes.ini'
        desired.write_text(serialize_ini(codes), encoding='utf-8')
        result = subprocess.run(
            [str(MEXCLI_PATH), 'sync-codes', str(project_path), str(desired)],
            capture_output=True, text=True, timeout=120, **get_subprocess_args())
    if result.returncode != 0:
        logger.warning(f'  sync-codes failed: {result.stdout or result.stderr}')
        return False
    return True


@menus_bp.route('/api/mex/menus/css/background/status', methods=['GET'])
def css_bg_status():
    """Whether the open project's CSS background looks custom: installed
    through the app (per-project record) or carrying the code every install
    adds. Drives the "Restore Vanilla Background" button."""
    try:
        project_path = get_current_project_path()
        if project_path is None:
            return jsonify({'success': True, 'custom': False})
        from vault.menus.installed import load_installed_menu_mods
        custom = ('css:background' in load_installed_menu_mods()
                  or _project_has_css_bg_code(project_path))
        return jsonify({'success': True, 'custom': bool(custom)})
    except Exception as e:
        logger.error(f'CSS bg status error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/css/background/restore-vanilla', methods=['POST'])
def restore_vanilla_css_bg():
    """Put the vanilla CSS background back into the open project.

    Installing a background rewrites only the background model/animation
    (and optionally scene) inside the project's MnSlChr.usd, with no backup.
    So the vanilla background is exported from the vanilla MnSlChr.usd
    (pulled from the user's vanilla ISO) and imported back the same way,
    scene included. The rest of MnSlChr (icons, doors, m-ex fighter slots)
    and everything outside the CSS is untouched. The install's Gecko code is
    dropped so the vanilla backdrop animates again.
    """
    try:
        project_path = get_current_project_path()
        if project_path is None:
            return jsonify({'success': False, 'error': 'No MEX project loaded'}), 400
        files_dir = get_project_files_dir()
        if files_dir is None:
            return jsonify({'success': False, 'error': 'No project files directory'}), 400
        mnslchr_usd = Path(files_dir) / 'MnSlChr.usd'
        if not mnslchr_usd.exists():
            return jsonify({'success': False, 'error': f'MnSlChr.usd not found at {mnslchr_usd}'}), 400
        if not HSDRAW_EXE.exists():
            return jsonify({'success': False, 'error': f'HSDRawViewer not found at {HSDRAW_EXE}'}), 500

        from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
        vanilla = ensure_vanilla_ref('MnSlChr.usd') or ensure_vanilla_ref('MnSlChr.dat')
        if vanilla is None:
            return jsonify({'success': False, 'error': (
                'No vanilla character select screen is available -- set your '
                'vanilla Melee ISO in Settings first.')}), 400

        # A scanner may still hold the output in here; scratch left behind must not fail the install.
        with tempfile.TemporaryDirectory(prefix='cssbg_vanilla_', ignore_cleanup_errors=True) as tmp:
            export_dir = Path(tmp) / 'export'
            export_dir.mkdir()
            bg_dat = export_dir / 'background.dat'
            if (_run_hsd_cli(['--css-bg', 'export', str(vanilla), str(export_dir)]) is None
                    or not bg_dat.exists()):
                return jsonify({'success': False, 'error': 'Could not read the vanilla background'}), 500

            output_usd = Path(tmp) / 'MnSlChr.usd'
            result = _run_hsd_cli(['--css-bg', 'import', str(mnslchr_usd), str(bg_dat),
                                   str(output_usd), '--include-scene'])
            if result is None or not output_usd.exists():
                return jsonify({'success': False, 'error': 'HSDRawViewer --css-bg import failed'}), 500
            file_retry.retry_locked(shutil.copy, str(output_usd), str(mnslchr_usd))

        code_removed = _drop_css_bg_code(project_path)

        from vault.menus.installed import clear_installed_menu_mod
        clear_installed_menu_mod('css:background')

        msg = 'Restored the vanilla CSS background. Rebuild ISO to apply.'
        if not code_removed:
            msg += (f' Could not remove the "{CSS_BG_ANIM_CODE}" code; '
                    'turn it off in Codes so the background animates.')
        logger.info('[OK] Restored vanilla CSS background')
        return jsonify({'success': True, 'message': msg, 'codeRemoved': code_removed})
    except Exception as e:
        logger.error(f'Restore vanilla CSS bg error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/sss/background/install/<mod_id>', methods=['POST'])
def install_sss_bg_to_mex(mod_id):
    """Install a background mod into the SSS (MnSlMap.usd) of the loaded MEX project.

    Uses HSDRawViewer --sss-bg import to swap the background in MnSlMap.usd.
    """
    try:
        mod = _load_bg_mod_json(mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404

        project_path = get_current_project_path()
        if project_path is None:
            return jsonify({'success': False, 'error': 'No MEX project loaded'}), 400

        files_dir = get_project_files_dir()
        if files_dir is None:
            return jsonify({'success': False, 'error': 'No project files directory'}), 400

        mnslmap_usd = Path(files_dir) / 'MnSlMap.usd'
        if not mnslmap_usd.exists():
            return jsonify({'success': False, 'error': f'MnSlMap.usd not found at {mnslmap_usd}'}), 400

        bg_dat = BG_PATH / mod_id / 'background.dat'
        if not bg_dat.exists():
            return jsonify({'success': False, 'error': 'background.dat missing from mod'}), 400

        if not HSDRAW_EXE.exists():
            return jsonify({'success': False, 'error': f'HSDRawViewer not found at {HSDRAW_EXE}'}), 500

        # Same lock, same journal: the SSS menu file is a file the played build
        # boots from too, and it is replaced as one recoverable step.
        from core import build_access
        build_dir = Path(project_path).parent
        try:
            with build_access.build_session(build_dir) as session:
                # A scanner may still hold the output in here; scratch left behind must not fail the install.
                with tempfile.TemporaryDirectory(prefix='sssbg_install_', ignore_cleanup_errors=True) as tmp:
                    output_usd = Path(tmp) / 'MnSlMap.usd'
                    hsd_args = ['--sss-bg', 'import',
                                str(mnslmap_usd), str(bg_dat), str(output_usd)]
                    if mod.get('includeScene'):
                        hsd_args.append('--include-scene')
                    if _run_hsd_cli(hsd_args) is None:
                        return jsonify({'success': False,
                                        'error': 'HSDRawViewer --sss-bg import failed'}), 500
                    if not output_usd.exists() or not output_usd.stat().st_size:
                        return jsonify({'success': False,
                                        'error': 'Import produced no output file'}), 500
                    session.replace_file('files/MnSlMap.usd', output_usd,
                                         label=f'sss background {mod_id}')
        except build_access.BuildBusyError as busy:
            return jsonify({'success': False, 'error': str(busy)}), 409
        except build_access.TransactionError as failed:
            logger.error('SSS background install rolled back: %s', failed)
            return jsonify({'success': False, 'error': str(failed)}), 500

        from vault.menus.installed import record_installed_menu_mod
        record_installed_menu_mod('sss:background', 'sss_background', _attach_bg_urls(mod))
        msg = f'Installed background "{mod["name"]}" to SSS. Rebuild ISO to apply.'
        logger.info(f'[OK] Installed SSS background mod {mod_id}')
        return jsonify({'success': True, 'message': msg})

    except Exception as e:
        logger.error(f'Install SSS bg mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
