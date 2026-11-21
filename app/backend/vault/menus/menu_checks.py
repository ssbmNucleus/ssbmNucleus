"""
Read "Currently in MEX" from the project files for the non-typeface menu
slots (the HUD typefaces live in hud_verify.py).

Each check decodes what the slot shows in the project file, compares it
with the vanilla game (the user's vanilla disc file, via ensure_vanilla_ref)
and with the recorded mod, and answers like hud_verify:
{state: 'installed'|'vanilla'|'custom', stale?, unverified?}, or None when
the slot can't be checked (tool missing, no vanilla reference, export
failed), in which case the panel shows the record as before. Pictures are
compared with menu_pixels (tolerant of re-encoding); exports are cached per
file mtime/size (menu_exports).

  hud:pause_screen  GmPause.usd, --pause-screen export (11 textures)
  css:doors         MnSlChr.usd, --css-doors export (the 128x200 doors)
  css:icon_grid     the project's assets/ icon PNGs (MexCLI keeps them)
                    + --css-icons export of the vanilla MnSlChr
  css:background    MnSlChr.usd, --bg-textures export (geometry hash +
  sss:background    background textures); MnSlMap.usd for the SSS
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from .menu_exports import cached_export
from .menu_pixels import same_picture

logger = logging.getLogger(__name__)

SLOT_MENUS = {
    'hud': ('hud:pause_screen',),
    'css': ('css:icon_grid', 'css:doors', 'css:background'),
    'sss': ('sss:background',),
}


def classify(entry, matches_record, is_vanilla):
    """Shared verdict. matches_record: True/False, or None when the record's
    mod can't be compared (vault mod gone or edited since the install)."""
    if is_vanilla is None:
        return None
    if entry is None:
        return {'state': 'vanilla' if is_vanilla else 'custom', 'stale': False}
    if matches_record:
        return {'state': 'installed'}
    if is_vanilla:
        return {'state': 'vanilla', 'stale': True}
    if matches_record is None:
        return {'state': 'installed', 'unverified': True}
    return {'state': 'custom', 'stale': True}


def _edited_after_install(entry, mod_json_path):
    try:
        when = datetime.fromisoformat(str(entry.get('installed')))
        return datetime.fromtimestamp(Path(mod_json_path).stat().st_mtime) > when
    except Exception:
        return False


def _vanilla_ref(*names):
    try:
        from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
        for n in names:
            ref = ensure_vanilla_ref(n)
            if ref is not None:
                return ref
    except Exception:
        pass
    return None


def _manifest(out_dir):
    if out_dir is None:
        return None
    try:
        return json.loads((Path(out_dir) / 'manifest.json').read_text(encoding='utf-8'))
    except Exception:
        return None


def _all_same(pairs, kind='reencode'):
    """True when every (a, b) pair shows the same picture; None if any can't
    be compared."""
    for a, b in pairs:
        ok = same_picture(a, b, kind)
        if ok is None:
            return None
        if not ok:
            return False
    return True


# ── pause screen (GmPause.usd) ─────────────────────────────────────────────

def _pause_textures(path):
    out_dir = cached_export('--pause-screen', path, timeout=120)
    m = _manifest(out_dir)
    if not m or not m.get('textures'):
        return None
    return {e['index']: {**e, 'file': out_dir / e['filename']} for e in m['textures']}


def check_pause(entry, files_dir):
    from . import pause
    project = _pause_textures(Path(files_dir) / 'GmPause.usd')
    ref = _vanilla_ref('GmPause.usd')
    vanilla = _pause_textures(ref) if ref is not None else None
    if not project or not vanilla or set(project) != set(vanilla):
        return None
    is_vanilla = _all_same((project[i]['file'], vanilla[i]['file']) for i in project)

    matches = None
    if entry and entry.get('id'):
        mod = pause.load_mod_json(pause.PAUSE_PATH, entry['id'])
        mod_dir = pause.PAUSE_PATH / entry['id']
        if mod and not _edited_after_install(entry, mod_dir / 'mod.json'):
            expected = {}   # index -> (png, kind)
            if mod.get('textures'):
                for t in mod['textures']:
                    png = mod_dir / 'textures' / t.get('file', '')
                    if png.is_file():
                        expected[t['index']] = (png, 'source' if t.get('replaced') else 'reencode')
            elif mod.get('source') == 'image' and (mod_dir / 'picture.png').is_file():
                for i, t in project.items():
                    if t.get('width') == 88 and t.get('height') == 72:
                        expected[i] = (mod_dir / 'picture.png', 'source')
            if expected:
                matches = True
                for i, t in project.items():
                    png, kind = expected.get(i, (vanilla[i]['file'], 'reencode'))
                    ok = same_picture(t['file'], png, kind)
                    if ok is None:
                        matches = None
                        break
                    if not ok:
                        matches = False
                        break
    return classify(entry, matches, is_vanilla)


# ── CSS doors (MnSlChr.usd) ────────────────────────────────────────────────

def _door_textures(path):
    out_dir = cached_export('--css-doors', path, timeout=120)
    if out_dir is None:
        return None
    doors = sorted(out_dir.glob('*_128x200_*.png'))
    return doors or None


def _door_pair(door_png, file_door):
    """(file door, the mod's door as the importer writes it) to compare: the
    picture stretched to the door size under the file's alpha mask. Where
    the mod picture itself is (nearly) transparent the importer's color is
    undefined (resampler-dependent), so those pixels are left out of both."""
    from PIL import Image
    with Image.open(file_door) as f:
        f = f.convert('RGBA')
    with Image.open(door_png) as d:
        exp = d.convert('RGBA').resize(f.size, Image.BICUBIC)
    keep = exp.getchannel('A').point(lambda a: 255 if a >= 128 else 0)
    if keep.getbbox() is None:
        return None     # a fully transparent door picture: nothing to compare
    mask = Image.new('L', f.size, 0)
    mask.paste(f.getchannel('A'), (0, 0), keep)
    exp.putalpha(mask)
    f.putalpha(mask)
    return f, exp


def check_doors(entry, files_dir):
    from . import doors
    project = _door_textures(Path(files_dir) / 'MnSlChr.usd')
    ref = _vanilla_ref('MnSlChr.usd', 'MnSlChr.dat')
    vanilla = _door_textures(ref) if ref is not None else None
    if not project or not vanilla:
        return None
    is_vanilla = _all_same((p, vanilla[0]) for p in project)

    matches = None
    if entry and entry.get('id'):
        door_png = doors.DOORS_PATH / entry['id'] / 'door.png'
        if door_png.is_file() and not _edited_after_install(entry, door_png):
            try:
                pairs = [_door_pair(door_png, p) for p in project]
                matches = None if any(x is None for x in pairs) else _all_same(pairs, 'source')
            except Exception:
                matches = None
    return classify(entry, matches, is_vanilla)


# ── CSS icon grid (project assets) ─────────────────────────────────────────

def _project_icons(project_dir):
    """{fighter name: icon png} from the project's data/fighters/*.json."""
    out = {}
    from mexcli.project import fighter_files
    for f in fighter_files(project_dir):
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            continue
        rel = (d.get('assets') or {}).get('cssIcon')
        name = d.get('name')
        if not rel or not name:
            continue
        png = Path(project_dir) / 'assets' / (str(rel).replace('\\', '/') + '.png')
        if png.is_file():
            out[name] = png
    return out


def _vanilla_icons():
    from .icons import VANILLA_ICON_JOINT_TO_CHARACTER
    ref = _vanilla_ref('MnSlChr.usd', 'MnSlChr.dat')
    if ref is None:
        return None
    out_dir = cached_export('--css-icons', ref, timeout=180)
    m = _manifest(out_dir)
    if not m or m.get('format') not in (None, 'vanilla'):
        return None
    out = {}
    for e in m.get('icons', []):
        c = VANILLA_ICON_JOINT_TO_CHARACTER.get(e.get('joint_index'))
        if c and e.get('filename') and (out_dir / e['filename']).is_file():
            out[c] = out_dir / e['filename']
    return out or None


def check_icon_grid(entry, project_dir):
    from . import icons
    project = _project_icons(project_dir)
    vanilla = _vanilla_icons()
    if not project or not vanilla:
        return None
    shared = [c for c in vanilla if c in project]
    if not shared:
        return None
    is_vanilla = _all_same((project[c], vanilla[c]) for c in shared)

    matches = None
    if entry and entry.get('id'):
        mod_dir = icons.ICON_GRID_PATH / entry['id']
        mod = icons.load_mod_json(icons.ICON_GRID_PATH, entry['id'])
        if mod and not _edited_after_install(entry, mod_dir / 'mod.json'):
            by_char = {i.get('character'): mod_dir / 'icons' / i.get('icon', '')
                       for i in mod.get('icons', []) if i.get('character') and i.get('icon')}
            if 'Zelda' in by_char and 'Sheik' not in by_char:
                by_char['Sheik'] = by_char['Zelda']
            wanted = entry.get('icons_installed') or list(by_char)
            pairs = [(project[c], by_char[c]) for c in wanted
                     if c in project and c in by_char and by_char[c].is_file()]
            # Only the icons this grid installed: fighters it has no icon for
            # keep whatever they had, which isn't this mod's to answer for.
            matches = _all_same(pairs, 'source') if pairs else None
    return classify(entry, matches, is_vanilla)


# ── CSS / SSS background ───────────────────────────────────────────────────

def _bg(path):
    out_dir = cached_export('--bg-textures', path, timeout=120)
    m = _manifest(out_dir)
    if not m or 'model_md5' not in m:
        return None
    m['_dir'] = out_dir
    return m


def _same_bg(a, b):
    if a['model_md5'] != b['model_md5'] or len(a['textures']) != len(b['textures']):
        return False
    pairs = []
    for x, y in zip(a['textures'], b['textures']):
        if x.get('md5') and x.get('md5') == y.get('md5'):
            continue
        pairs.append((a['_dir'] / x['filename'], b['_dir'] / y['filename']))
    return _all_same(pairs) if pairs else True


def check_background(entry, files_dir, screen):
    from . import backgrounds
    names = ('MnSlChr.usd', 'MnSlChr.dat') if screen == 'css' else ('MnSlMap.usd', 'MnSlMap.dat')
    project = _bg(Path(files_dir) / names[0])
    ref = _vanilla_ref(*names)
    vanilla = _bg(ref) if ref is not None else None
    if not project or not vanilla:
        return None
    is_vanilla = _same_bg(project, vanilla)

    matches = None
    if entry and entry.get('id'):
        bundle = backgrounds.BG_PATH / entry['id'] / 'background.dat'
        mod = _bg(bundle) if bundle.is_file() else None
        if mod is not None:
            matches = _same_bg(project, mod)
    return classify(entry, matches, is_vanilla)


def verify_menu_slots(menus, installed, project_dir):
    """{slot_key: verdict} for the requested menus ('hud', 'css', 'sss');
    slots that can't be checked are left out. Never raises."""
    out = {}
    project_dir = Path(project_dir)
    files_dir = project_dir / 'files'
    checks = {
        'hud:pause_screen': lambda e: check_pause(e, files_dir),
        'css:doors': lambda e: check_doors(e, files_dir),
        'css:icon_grid': lambda e: check_icon_grid(e, project_dir),
        'css:background': lambda e: check_background(e, files_dir, 'css'),
        'sss:background': lambda e: check_background(e, files_dir, 'sss'),
    }
    for menu in menus:
        for slot in SLOT_MENUS.get(menu, ()):
            entry = installed.get(slot)
            entry = entry if isinstance(entry, dict) else None
            try:
                verdict = checks[slot](entry)
            except Exception as e:
                logger.warning(f'Menu check {slot} skipped: {e}')
                verdict = None
            if verdict is not None:
                out[slot] = verdict
    return out
