"""
The "Currently in MEX" record: which menu mod occupies each slot of the open
project (<project>/nucleus_menus.json), with a preview snapshot copied into the
project so editing or deleting the vault mod does not change the record.
"""

import shutil
import re
import logging
from pathlib import Path
from core.config import STORAGE_PATH
from core.metadata import load_metadata, save_metadata

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Installed-menu-mod record (per project)
# ─────────────────────────────────────────────────────────────────────────────
#
# The ISO editor's Menus tab shows "Currently in MEX" for each slot. That used
# to live only in React state, so leaving the tab forgot every install and the
# panel fell back to "default" even though the project file had been patched.
# Each install route now records what it put in the project here, and the tab
# reads it back on entry. Slot keys are "<menu>:<submod>" exactly as the tab
# keys them: css:icon_grid, css:doors, css:background, sss:background,
# hud:pause_screen, hud:percent_font, hud:ready_go.

INSTALLED_MENUS_FILE = 'nucleus_menus.json'


def _installed_menus_path():
    from core.state import get_current_project_path
    project = get_current_project_path()
    if project is None:
        return None
    return Path(project).parent / INSTALLED_MENUS_FILE


def load_installed_menu_mods():
    """{slot_key: {id, name, kind, screenshotUrl|imageUrl, installed}} for the
    open project; {} when no project is open or nothing was recorded."""
    path = _installed_menus_path()
    if path is None or not path.exists():
        return {}
    data = load_metadata(default={}, path=path)
    return data.get('installed', {}) if isinstance(data, dict) else {}


def record_installed_menu_mod(slot_key, kind, mod):
    """Remember that `mod` (a list-shaped dict, URLs attached) now occupies
    `slot_key` in the open project. Returns the stored entry (None when
    nothing could be recorded). Best-effort: never raises."""
    try:
        path = _installed_menus_path()
        if path is None:
            return
        data = load_metadata(default={}, path=path) if path.exists() else {}
        if not isinstance(data, dict):
            data = {}
        installed = data.setdefault('installed', {})
        entry = {k: mod.get(k) for k in ('id', 'name', 'description', 'screenshotUrl',
                                        'imageUrl', 'icon_count', 'source', 'category',
                                        'categories', 'plan', 'icons_installed',
                                        'icons_total', 'file_stat')
                 if mod.get(k) is not None}
        entry['kind'] = kind
        from datetime import datetime as _dt
        now = _dt.now()
        entry['installed'] = now.isoformat(timespec='seconds')
        snapshot = _snapshot_preview(path.parent, slot_key, mod)
        if snapshot:
            menu, _, submod = slot_key.partition(':')
            entry['snapshot'] = snapshot
            entry['snapshotUrl'] = (f'/api/mex/menus/installed/preview/{menu}/{submod}'
                                    f'?v={now.strftime("%Y%m%d%H%M%S")}')
        installed[slot_key] = entry
        save_metadata(data, path=path)
        return entry
    except Exception as e:  # pragma: no cover - bookkeeping must not fail an install
        logger.warning(f'Could not record installed menu mod for {slot_key}: {e}')
    return None


def save_installed_menu_mods(installed):
    """Write back a whole {slot_key: mod} map (used by read-time repairs of
    old records). Best-effort: never raises."""
    try:
        path = _installed_menus_path()
        if path is None:
            return
        data = load_metadata(default={}, path=path) if path.exists() else {}
        if not isinstance(data, dict):
            data = {}
        data['installed'] = installed
        save_metadata(data, path=path)
    except Exception as e:  # pragma: no cover - bookkeeping must not fail a read
        logger.warning(f'Could not save installed menu mods: {e}')


def add_installed_menu_fields(updates):
    """Add fields to existing records: {slot_key: (id, installed, fields)}.
    A record replaced meanwhile (different id / install time) is left alone,
    so a slow check never overwrites a newer install. Best-effort."""
    try:
        path = _installed_menus_path()
        if path is None or not path.exists() or not updates:
            return
        data = load_metadata(default={}, path=path)
        installed = data.get('installed') if isinstance(data, dict) else None
        if not isinstance(installed, dict):
            return
        changed = False
        for slot_key, (mod_id, when, fields) in updates.items():
            entry = installed.get(slot_key)
            if isinstance(entry, dict) and entry.get('id') == mod_id \
                    and entry.get('installed') == when:
                entry.update(fields)
                changed = True
        if changed:
            save_metadata(data, path=path)
    except Exception as e:  # pragma: no cover - bookkeeping must not fail a read
        logger.warning(f'Could not update installed menu records: {e}')


def clear_installed_menu_mod(slot_key):
    """Forget what occupies `slot_key` (the slot is back on vanilla).
    Best-effort: never raises."""
    try:
        path = _installed_menus_path()
        if path is None or not path.exists():
            return
        data = load_metadata(default={}, path=path)
        if isinstance(data, dict) and slot_key in data.get('installed', {}):
            del data['installed'][slot_key]
            save_metadata(data, path=path)
        _remove_preview_snapshots(path.parent, slot_key)
    except Exception as e:  # pragma: no cover - bookkeeping must not fail a restore
        logger.warning(f'Could not clear installed menu mod for {slot_key}: {e}')


# The panel's picture of an installed mod is copied into the project at
# install time: the stored URL points at the live vault item, so editing or
# deleting that mod used to change or break "Currently in MEX".
INSTALLED_PREVIEWS_DIR = 'nucleus_menus_previews'
_SNAPSHOT_MAX_SIDE = 640
_SNAPSHOT_MAX_BYTES = 32 * 1024 * 1024


def _slot_file_stem(slot_key):
    return re.sub(r'[^A-Za-z0-9]+', '_', str(slot_key)).strip('_')


def _vault_file_for_url(url):
    """The vault file a mod's preview URL serves, or None. Knows the /storage
    static route and the menu image routes (percent, pause, doors)."""
    if not isinstance(url, str) or not url:
        return None
    url = url.split('?', 1)[0]
    if url.startswith('/storage/'):
        root = Path(STORAGE_PATH).resolve()
        target = (root / url[len('/storage/'):]).resolve()
        if root in target.parents and target.is_file():
            return target
        return None
    m = re.fullmatch(r'/api/mex/menus/(percent|pause)/image/([\w-]+)', url)
    if m:
        if m.group(1) == 'percent':
            from .percent import percent_preview_path as resolve
        else:
            from .pause import pause_preview_path as resolve
        return resolve(m.group(2))
    m = re.fullmatch(r'/api/mex/menus/css/doors/image/([\w-]+)', url)
    if m:
        from . import doors
        target = doors.DOORS_PATH / m.group(1) / 'door.png'
        return target if target.is_file() else None
    return None


def _remove_preview_snapshots(project_dir, slot_key):
    folder = Path(project_dir) / INSTALLED_PREVIEWS_DIR
    if folder.is_dir():
        for old in folder.glob(f'{_slot_file_stem(slot_key)}.*'):
            old.unlink(missing_ok=True)


def _snapshot_preview(project_dir, slot_key, mod):
    """Copy the mod's preview into <project>/nucleus_menus_previews/ (downscaled
    PNG; raw copy if it can't be decoded). Returns the file name or None.
    Best-effort: never raises."""
    try:
        src = None
        for url in (mod.get('screenshotUrl'), mod.get('imageUrl')):
            src = _vault_file_for_url(url)
            if src is not None:
                break
        _remove_preview_snapshots(project_dir, slot_key)
        if src is None or src.stat().st_size > _SNAPSHOT_MAX_BYTES:
            return None
        folder = Path(project_dir) / INSTALLED_PREVIEWS_DIR
        folder.mkdir(parents=True, exist_ok=True)
        stem = _slot_file_stem(slot_key)
        try:
            from PIL import Image
            with Image.open(src) as im:
                im.load()
                pic = im if im.mode in ('RGB', 'RGBA') else im.convert('RGBA')
                pic.thumbnail((_SNAPSHOT_MAX_SIDE, _SNAPSHOT_MAX_SIDE))
                out = folder / f'{stem}.png'
                pic.save(out, format='PNG')
        except Exception:
            out = folder / f'{stem}{src.suffix.lower() or ".png"}'
            shutil.copyfile(src, out)
        return out.name
    except Exception as e:
        logger.warning(f'Could not snapshot the preview for {slot_key}: {e}')
        return None


def installed_preview_file(slot_key):
    """The snapshot file recorded for `slot_key` in the open project, or None."""
    path = _installed_menus_path()
    if path is None:
        return None
    entry = load_installed_menu_mods().get(slot_key)
    name = entry.get('snapshot') if isinstance(entry, dict) else None
    if (not isinstance(name, str) or Path(name).name != name
            or Path(name).stem != _slot_file_stem(slot_key)):
        return None
    target = path.parent / INSTALLED_PREVIEWS_DIR / name
    return target if target.is_file() else None
