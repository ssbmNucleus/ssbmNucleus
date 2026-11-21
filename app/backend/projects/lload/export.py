"""Apply a project's L-load groups to its build: tuck the alternates' icons and
keep the generated Gecko code in step. Called on every export (inside the
export's MexCLI lock, like the Any Climbers code) and when groups are saved.

Best-effort like the other export-time code steps: a failure is logged and the
build goes on without L-load rather than failing.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from core.config import MEXCLI_PATH, get_subprocess_args
from core.gecko import parse_ini, serialize_ini
from mexcli.commands import parse_json
from projects.lload import code, groups as lload_groups, layout

logger = logging.getLogger(__name__)


def _mexcli(*args, stdin: str | None = None, timeout=120) -> dict:
    result = subprocess.run([str(MEXCLI_PATH), *map(str, args)], input=stdin,
                            capture_output=True, text=True, timeout=timeout,
                            **get_subprocess_args())
    out = parse_json(result.stdout)
    if result.returncode != 0 or out.get('success') is False:
        raise RuntimeError(f'mexcli {args[0]} failed: {out.get("error") or result.stderr or result.stdout}')
    return out


def get_layout(project_path) -> dict:
    return _mexcli('get-css-layout', project_path)


def set_icons(project_path, icons: list[dict]) -> None:
    _mexcli('set-css-layout', project_path, stdin=json.dumps({'icons': icons}))


def tuck_layout(project_path, name_groups: list[dict], current: dict):
    """Tuck `current`'s icons for the normalized `name_groups`, writing only on
    a change. Returns (resolved groups, {external id: icon index})."""
    resolved = lload_groups.resolve(name_groups, current['fighters'])
    icons, index = layout.tuck(current['icons'], resolved)
    if layout.changed(current['icons'], icons):
        set_icons(project_path, icons)
    return resolved, index


def _codes_ini(project_path) -> Path:
    return Path(project_path).parent / 'files' / 'codes.ini'


def _is_ours(c: dict) -> bool:
    return c['name'].strip().lower() == code.CODE_NAME.lower()


def _hex(src: str) -> str:
    return ' '.join(''.join(ch for ch in line.split('#', 1)[0] if ch in '0123456789abcdefABCDEF')
                    for line in src.splitlines() if line.split('#', 1)[0].strip()).upper()


def sync_code(project_path, source: str | None) -> bool:
    """Make the project's codes carry `source` as the L-load code (None = no
    code). Returns True if the codes were rewritten."""
    ini = _codes_ini(project_path)
    if not ini.exists():
        if source is None:
            return False
        _mexcli('add-code', project_path, code.CODE_HEADER, source)
        return True
    codes = parse_ini(ini.read_text(encoding='utf-8', errors='replace'))
    mine = [c for c in codes if _is_ours(c)]
    if source is None:
        if not mine:
            return False
        codes = [c for c in codes if not _is_ours(c)]
    elif mine and all(c['enabled'] and _hex(c['source']) == _hex(source) for c in mine) and len(mine) == 1:
        return False
    elif mine:
        codes = [c for c in codes if not _is_ours(c) or c is mine[0]]
        mine[0].update(source=source, enabled=True)
    else:
        codes.append({'name': code.CODE_NAME, 'creator': code.CODE_CREATOR,
                      'description': 'Tap L on the character select screen to scroll '
                                     'through a fighter\'s alternates (set in the CSS editor).',
                      'source': source, 'enabled': True})
    # sync-codes rewrites codes.ini AND codes.gct from a complete ini, carrying
    # every other code and its enabled flag over verbatim (add-code would skip
    # an existing name). On a project adopted from an m-ex build (e.g. ACE),
    # the source build's gct is the separate "m-ex core" and comes first, so
    # our hook at 0x80263334 replaces ACE's own L code there.
    desired = Path(tempfile.mkdtemp(prefix='lload_')) / 'codes.ini'
    desired.write_text(serialize_ini(codes), encoding='utf-8')
    try:
        _mexcli('sync-codes', project_path, desired)
        return True
    finally:
        shutil.rmtree(desired.parent, ignore_errors=True)


def ensure(project_path) -> list[str]:
    """The export step. Returns user-facing warnings for the export result:
    groups left out of the build, or the L code not being updated."""
    try:
        stored = lload_groups.load(project_path)
        if not stored:
            if sync_code(project_path, None):
                # The last group just went: give its alternates their icons back.
                tuck_layout(project_path, [], get_layout(project_path))
            return []
        current = get_layout(project_path)
        name_groups, problems = lload_groups.normalize(stored, current['fighters'], current['icons'])
        warnings = [f'L alternates: {p}; left out of this build' for p in problems]
        resolved, index = tuck_layout(project_path, name_groups, current)
        table = layout.table(resolved, index)
        sync_code(project_path, code.source(table) if table else None)
        if table:
            logger.info(f'L-load: {len(table)} group(s) baked into the build')
        return warnings
    except Exception as e:
        logger.warning(f'L-load step failed: {e}')
        return [f'L alternates were not updated in this build ({e}); '
                f'the select screen may still use the previous lists']


def repair_after_remove(project_path, before: dict, removed_name: str) -> None:
    """Restore the CSS icons after `remove-fighter` from a snapshot taken before.

    MexCLI's remove-fighter points the removed fighter's icons at external
    id 0 and then deletes the LAST icon whose fighter is 0 -- Captain Falcon's,
    whenever it comes later in the list or the removed fighter had no icon. The
    snapshot minus the removed fighter's icons, with higher ids shifted down
    (MexProject.RemoveFighter's own rule), is the layout it meant to leave.
    """
    match = [f for f in before['fighters'] if f['name'].strip().lower() == removed_name.strip().lower()]
    if not match:
        return
    gone = match[0]['externalId']
    icons = []
    for ic in before['icons']:
        if ic['fighter'] == gone:
            continue
        ic = layout.icon_fields(ic)
        if gone < ic['fighter'] < 255:
            ic['fighter'] -= 1
        icons.append(ic)
    set_icons(project_path, icons)
