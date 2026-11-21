"""
CSS icon grid mods: the character alias table, catalog, labelling icons by
character, and importing a pack (loose PNGs, a CSS DAT or a m-ex MxDt pack).
"""

import json
import re
import shutil
import tempfile
import uuid
import zipfile
import logging
from pathlib import Path
from datetime import datetime

from vault.menus.store import (ICON_GRID_PATH, ICON_GRID_METADATA, SCREENSHOT_CANDIDATES,
                               load_catalog, save_catalog, load_mod_json, save_mod_json)
from vault.menus.files import _safe_extract_zip, _find_screenshot
from vault.menus.hsd import _run_hsd_cli

logger = logging.getLogger(__name__)


# Canonical Melee character → list of accepted filename stems (lowercase).
CHARACTER_ALIASES = {
    'Mario':            ['mario', 'mr'],
    'Fox':              ['fox', 'fx'],
    'C. Falcon':        ['falcon', 'falc', 'cfalcon', 'captainfalcon', 'ca', 'capt'],
    'DK':               ['dk', 'donkey', 'donkeykong', 'dkong'],
    'Kirby':            ['kirby', 'kieby', 'kby', 'kb'],
    'Bowser':           ['bowser', 'bows', 'kp', 'koopa'],
    'Link':             ['link', 'lk'],
    'Sheik':            ['sheik', 'sk', 'shelda', 'shiek'],
    'Ness':             ['ness', 'ns'],
    'Peach':            ['peach', 'pe'],
    'Ice Climbers':     ['ics', 'iceclimbers', 'ic', 'popo', 'nana', 'pp', 'climbers'],
    'Pikachu':          ['pika', 'pikachu', 'pk'],
    'Samus':            ['samus', 'sams', 'ss'],
    'Yoshi':            ['yoshi', 'yosh', 'ys'],
    'Jigglypuff':       ['jiggly', 'jigglypuff', 'puff', 'pr'],
    'Mewtwo':           ['mewtwo', 'm2', 'mt'],
    'Luigi':            ['luigi', 'lugi', 'lg'],
    'Marth':            ['marth', 'mars', 'ms'],
    'Zelda':            ['zelda', 'zd'],
    'Young Link':       ['younglink', 'yink', 'ylink', 'cl', 'ylk'],
    'Dr. Mario':        ['drmario', 'doc', 'dr', 'docmario'],
    'Falco':            ['falco', 'fc'],
    'Pichu':            ['pichu', 'pc'],
    'Mr. Game & Watch': ['gw', 'gnw', 'mrgw', 'mrgameandwatch', 'gameandwatch', 'gamewatch'],
    'Ganondorf':        ['ganon', 'ganondorf', 'gn'],
    'Roy':              ['roy', 'fe'],
}
_ALIAS_TO_CHARACTER = {alias: char for char, aliases in CHARACTER_ALIASES.items() for alias in aliases}


def _stem_to_character(stem):
    """Map a filename stem (case-insensitive) to a canonical character, or None."""
    key = stem.lower().strip()
    if not key:
        return None
    if key in _ALIAS_TO_CHARACTER:
        return _ALIAS_TO_CHARACTER[key]
    stripped = re.sub(r'[\W_0-9]+$', '', key)
    if stripped and stripped != key and stripped in _ALIAS_TO_CHARACTER:
        return _ALIAS_TO_CHARACTER[stripped]
    return None


def _safe_filename(name):
    """Make a character name filesystem-safe (e.g. `Dr. Mario` → `Dr_Mario`)."""
    return re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_')


# Normalize MEX NameText values (which vary between projects) to our canonical
# character names (matching CHARACTER_ALIASES keys / ROSTER_ORDER).
NAMETEXT_NORMALIZE = {
    'c. falcon': 'C. Falcon',
    'cfalcon': 'C. Falcon',
    'captain falcon': 'C. Falcon',
    'dk': 'DK',
    'donkey kong': 'DK',
    'ice climbers': 'Ice Climbers',
    'iceclimbers': 'Ice Climbers',
    'popo': 'Ice Climbers',
    'nana': 'Ice Climbers',
    'jigglypuff': 'Jigglypuff',
    'puff': 'Jigglypuff',
    'mr. game & watch': 'Mr. Game & Watch',
    'mr. game and watch': 'Mr. Game & Watch',
    'mr game and watch': 'Mr. Game & Watch',
    'game and watch': 'Mr. Game & Watch',
    'game & watch': 'Mr. Game & Watch',
    'g&w': 'Mr. Game & Watch',
    'gw': 'Mr. Game & Watch',
    'dr. mario': 'Dr. Mario',
    'dr mario': 'Dr. Mario',
    'doc': 'Dr. Mario',
    'young link': 'Young Link',
    'ylink': 'Young Link',
    'mario': 'Mario',
    'fox': 'Fox',
    'kirby': 'Kirby',
    'bowser': 'Bowser',
    'link': 'Link',
    'sheik': 'Sheik',
    'ness': 'Ness',
    'peach': 'Peach',
    'pikachu': 'Pikachu',
    'samus': 'Samus',
    'yoshi': 'Yoshi',
    'mewtwo': 'Mewtwo',
    'luigi': 'Luigi',
    'marth': 'Marth',
    'zelda': 'Zelda',
    'falco': 'Falco',
    'pichu': 'Pichu',
    'ganondorf': 'Ganondorf',
    'ganon': 'Ganondorf',
    'roy': 'Roy',
}


def _normalize_mex_name(raw):
    """Map a MEX NameText string to a canonical character name. Returns the
    canonical name when recognized, otherwise the trimmed raw string (so custom
    fighters like 'Wolf' or 'Diddy Kong' keep their MEX-defined names)."""
    if not raw:
        return None
    trimmed = raw.strip()
    if not trimmed:
        return None
    return NAMETEXT_NORMALIZE.get(trimmed.lower(), trimmed)


# Standard Melee External Char ID → canonical character name (fallback when
# MEX NameText isn't available, e.g. mexSelectChr.dat without a sibling MxDt.dat).
EXTERNAL_ID_TO_CHARACTER = {
    0x00: 'C. Falcon',
    0x01: 'DK',
    0x02: 'Fox',
    0x03: 'Mr. Game & Watch',
    0x04: 'Kirby',
    0x05: 'Bowser',
    0x06: 'Link',
    0x07: 'Luigi',
    0x08: 'Mario',
    0x09: 'Marth',
    0x0A: 'Mewtwo',
    0x0B: 'Ness',
    0x0C: 'Peach',
    0x0D: 'Pikachu',
    0x0E: 'Ice Climbers',
    0x0F: 'Jigglypuff',
    0x10: 'Samus',
    0x11: 'Yoshi',
    0x12: 'Zelda',
    0x13: 'Sheik',
    0x14: 'Falco',
    0x15: 'Young Link',
    0x16: 'Dr. Mario',
    0x17: 'Roy',
    0x18: 'Pichu',
    0x19: 'Ganondorf',
}

# m-ex's stock MEX_CSSIcon table: IconModel child N → external char id. Every
# m-ex build converted from vanilla starts with these 25 slots (custom fighters
# are appended after them). Used only when a mexSelectChr.dat arrives WITHOUT
# its MxDt.dat -- the table that normally labels each slot.
DEFAULT_MEX_ICON_SLOT_EXTIDS = [
    0x16, 0x08, 0x07, 0x05, 0x0C, 0x11, 0x01, 0x00, 0x19, 0x14, 0x02, 0x0B, 0x0E,
    0x04, 0x10, 0x12, 0x06, 0x15, 0x18, 0x0D, 0x0F, 0x0A, 0x03, 0x09, 0x17,
]

# Label for a CSS icon we keep but can't name (a custom fighter's slot with no
# NameText). The user relabels it in the icon grid editor; install skips it.
EXTRA_ICON_PREFIX = 'Extra Icon '

ROSTER_ORDER = [
    'Dr. Mario', 'Mario', 'Luigi', 'Bowser', 'Peach', 'Yoshi', 'DK', 'C. Falcon',
    'Ganondorf', 'Falco', 'Fox', 'Ness', 'Ice Climbers', 'Kirby', 'Samus', 'Zelda',
    'Sheik', 'Link', 'Young Link', 'Pichu', 'Pikachu', 'Jigglypuff', 'Mewtwo',
    'Mr. Game & Watch', 'Marth', 'Roy',
]

# Vanilla MenuModel JOBJ index → character name. The icon-grid tiles (64x56)
# are static textures on these joints (DOBJ 1 = foreground icon). This mapping
# is a fixed constant for all vanilla-format CSS dats — it's the hardcoded
# layout of MnSlChr.dat's MenuModel.
VANILLA_ICON_JOINT_TO_CHARACTER = {
    4:  'Dr. Mario',
    6:  'Ganondorf',
    8:  'Falco',
    10: 'Young Link',
    12: 'Pichu',
    14: 'Roy',
    16: 'Mario',
    17: 'Luigi',
    18: 'Bowser',
    19: 'Peach',
    20: 'Yoshi',
    21: 'DK',
    22: 'C. Falcon',
    23: 'Fox',
    24: 'Ness',
    25: 'Ice Climbers',
    26: 'Kirby',
    27: 'Samus',
    28: 'Sheik',
    29: 'Link',
    30: 'Pikachu',
    31: 'Jigglypuff',
    32: 'Mewtwo',
    33: 'Mr. Game & Watch',
    34: 'Marth',
}


# ─────────────────────────────────────────────────────────────────────────────
# Catalog persistence (parameterized helpers live in store.py)
# ─────────────────────────────────────────────────────────────────────────────

def _load_catalog():
    return load_catalog(ICON_GRID_METADATA, version='2.0')


def _save_catalog(data):
    save_catalog(ICON_GRID_METADATA, data)


def _catalog_entry(mod_full):
    """Trim a mod.json to the fields the catalog needs (list view)."""
    return {
        'id': mod_full['id'],
        'name': mod_full['name'],
        'description': mod_full.get('description', ''),
        'screenshot': mod_full.get('screenshot'),
        'icon_count': len(mod_full.get('icons', [])),
        'created': mod_full.get('created'),
    }


def _attach_urls(mod):
    """Add screenshot/icon URLs (absolute under /storage) to a mod dict."""
    out = dict(mod)
    mod_id = mod.get('id')
    if not mod_id:
        return out
    base = f'/storage/menus/css/icon_grid/{mod_id}'
    if mod.get('screenshot'):
        out['screenshotUrl'] = f"{base}/{mod['screenshot']}"
    icons_out = []
    for entry in mod.get('icons', []):
        e = dict(entry)
        if e.get('icon'):
            e['iconUrl'] = f"{base}/icons/{e['icon']}"
        icons_out.append(e)
    out['icons'] = icons_out
    return out


def _load_mod_json(mod_id):
    return load_mod_json(ICON_GRID_PATH, mod_id)


def _save_mod_json(mod_id, mod):
    save_mod_json(ICON_GRID_PATH, mod_id, mod)


# ─────────────────────────────────────────────────────────────────────────────
# Zip detection
# ─────────────────────────────────────────────────────────────────────────────

def looks_like_icon_grid_zip(zip_path):
    """Returns True if zip looks like a CSS icon grid mod (loose PNGs or compiled DAT)."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            names = [n for n in zf.namelist() if not n.startswith('__MACOSX')]
        equals_pngs = [n for n in names if Path(n).name.startswith('=') and n.lower().endswith('.png')]
        if len(equals_pngs) >= 2:
            return True
        for n in names:
            base = Path(n).name.lower()
            if base.startswith('mnslchr') or base == 'mexselectchr.dat':
                return True
        return False
    except zipfile.BadZipFile:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# HSDRawViewer CLI wrappers
# ─────────────────────────────────────────────────────────────────────────────

def _dump_dat_icons(dat_path, out_dir):
    """Returns parsed CSS icons manifest dict or None."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if _run_hsd_cli(['--css-icons', 'export', str(dat_path), str(out_dir)]) is None:
        return None
    manifest_path = out_dir / 'manifest.json'
    if not manifest_path.exists():
        return None
    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f'Failed to parse css-icons manifest: {e}')
        return None


def _read_mxdt_icon_info(mxdt_path, out_dir):
    """Returns parsed {icons: [{joint_id, external_char_id, ...}]} or None."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / 'mxdt_info.json'
    if _run_hsd_cli(['--mex-css-info', 'export', str(mxdt_path), str(out_json)]) is None:
        return None
    try:
        with open(out_json, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f'Failed to parse mxdt info: {e}')
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Source extraction → labeled icons (the work)
# ─────────────────────────────────────────────────────────────────────────────

def _find_css_dat(directory):
    """Pick the best CSS data file to feed to --css-icons. Returns Path or None."""
    candidates = list(Path(directory).rglob('*'))
    for p in candidates:
        if p.is_file() and p.name.lower() == 'mexselectchr.dat':
            return p
    for p in candidates:
        if p.is_file() and p.name.lower().startswith('mnslchr') and p.suffix.lower() == '.usd':
            return p
    for p in candidates:
        if p.is_file() and p.name.lower().startswith('mnslchr') and p.suffix.lower() == '.dat':
            return p
    return None


def _find_mxdt(directory):
    for p in Path(directory).rglob('*'):
        if p.is_file() and p.name.lower() == 'mxdt.dat':
            return p
    return None


def _custom_icon_label(stem):
    """Display name for a non-vanilla '=name.png' icon: `wolf` -> `Wolf`,
    `diddy_kong` -> `Diddy Kong`; already-cased stems keep their casing."""
    words = re.sub(r'[_\-\s]+', ' ', stem).strip()
    if not words:
        return None
    return words.title() if words == words.lower() else words


def _label_loose_png(temp_dir):
    """Walk PNGs in temp_dir, alias-match to characters, return one or more packs.

    A "pack" is a list of {character, icon_path} dicts. When a zip contains
    multiple icons per character (e.g. `mario.png` AND `=mario.png`), each
    distinct candidate becomes its own pack. Pack ordering follows the sorted
    file order, so e.g. `=`-prefixed names land in pack 0 (lexicographically
    earlier).
    """
    by_char = {}  # character → list[Path]
    for path in sorted(Path(temp_dir).rglob('*')):
        if not path.is_file() or path.suffix.lower() != '.png':
            continue
        if path.name.lower() in (n.lower() for n in SCREENSHOT_CANDIDATES):
            continue
        stem = path.stem.lstrip('=')
        character = _stem_to_character(stem)
        if not character and path.name.startswith('='):
            # '=name.png' is the icon-pack convention itself, so an '=' icon
            # whose name isn't a vanilla fighter is a CUSTOM fighter's icon
            # (=wolf.png, =goku.png). These used to be dropped silently.
            character = _custom_icon_label(stem)
        if not character:
            continue
        by_char.setdefault(character, []).append(path)

    if not by_char:
        return []

    pack_count = max(len(paths) for paths in by_char.values())
    packs = []
    for pack_idx in range(pack_count):
        pack = []
        for character, paths in by_char.items():
            if pack_idx < len(paths):
                pack.append({'character': character, 'icon_path': paths[pack_idx]})
        if pack:
            packs.append(pack)
    return packs


def _label_dat_mod(temp_dir, work_dir):
    """Run HSDRawViewer to extract icons from a CSS dat, returning labeled-icon list.

    work_dir is a scratch directory we can write extraction output into.
    Returns same shape as _label_loose_png: list of {character, icon_path}.
    Discards unlabeled icons.
    """
    dat = _find_css_dat(temp_dir)
    if dat is None:
        return [], None

    css_dump_dir = Path(work_dir) / 'css_dump'
    manifest = _dump_dat_icons(dat, css_dump_dir)
    if not manifest:
        return [], None

    fmt = manifest.get('format')
    by_char = {}

    if fmt == 'mex':
        # MxDt.dat's MEX_CSSIcon[] is positional: entry N corresponds to
        # IconModel child N. Use its external_char_id to label the slot,
        # preferring the project's own NameText table when present (catches
        # custom MEX fighters like Wolf with their MEX-defined display names).
        slot_external_ids = []
        ext_id_to_name = {}  # external_char_id → display name (from MEX project)
        mxdt = _find_mxdt(temp_dir)
        if mxdt is not None:
            mxdt_info = _read_mxdt_icon_info(mxdt, work_dir)
            if mxdt_info:
                for entry in mxdt_info.get('icons', []):
                    eid = entry.get('external_char_id')
                    slot_external_ids.append(int(eid) if eid is not None else None)
                # NameText is indexed by external_char_id in the MEX project.
                for f in mxdt_info.get('fighters', []):
                    ext_id = f.get('internal_id')  # array position == ext_id for NameText
                    name = _normalize_mex_name(f.get('name'))
                    if ext_id is not None and name:
                        ext_id_to_name[int(ext_id)] = name

        # Repair pass: some MEX mods (e.g. Diamond) ship a MxDt with duplicate
        # ext_ids and missing-but-visually-present vanilla characters. When the
        # number of duplicates exactly matches the number of missing vanilla
        # ext_ids, reassign each duplicate to a missing id (in slot order).
        # We skip Sheik (0x13) because she typically shares Zelda's slot.
        VANILLA_EXTIDS = set(range(0x00, 0x1A))  # 0x00..0x19
        seen_first = {}
        dup_slots = []
        for i, eid in enumerate(slot_external_ids):
            if eid is None or eid not in VANILLA_EXTIDS:
                continue
            if eid in seen_first:
                dup_slots.append(i)
            else:
                seen_first[eid] = i
        missing_ids = sorted((VANILLA_EXTIDS - {0x13}) - set(seen_first.keys()))
        if dup_slots and len(dup_slots) == len(missing_ids):
            logger.info(
                f"  MEX: MxDt has {len(dup_slots)} duplicate vanilla ext_id(s); "
                f"reassigning to missing {[hex(x) for x in missing_ids]}"
            )
            for slot_idx, new_eid in zip(dup_slots, missing_ids):
                slot_external_ids[slot_idx] = new_eid

        if not slot_external_ids:
            # A bare mexSelectChr.dat (no MxDt.dat beside it) has no slot
            # table. It used to label NOTHING -- "No recognizable icons" --
            # so the icons never reached the vault. Assume m-ex's stock slot
            # order for the vanilla 25; anything after is kept as an extra.
            logger.info('  MEX: no MxDt.dat -- assuming the stock m-ex icon slot order')
            slot_external_ids = list(DEFAULT_MEX_ICON_SLOT_EXTIDS)

        extra_n = 0
        for entry in sorted(manifest.get('icons', []), key=lambda e: e.get('index') or 0):
            slot_index = entry.get('index')
            if slot_index is None:
                continue
            fg = entry.get('foreground')
            if not fg:
                continue
            src = css_dump_dir / fg
            if not src.exists():
                continue
            external_id = (slot_external_ids[slot_index]
                           if slot_index < len(slot_external_ids) else None)
            # Prefer the MEX project's NameText (catches custom fighters like
            # Wolf); fall back to the standard vanilla ext_id table.
            character = None
            if external_id is not None:
                character = (ext_id_to_name.get(external_id)
                             or EXTERNAL_ID_TO_CHARACTER.get(external_id))
            if not character or character in by_char:
                # An icon we can't name (a custom fighter's slot with no
                # NameText) or a second icon for a name already taken: keep it
                # under a placeholder the user can relabel instead of silently
                # dropping it -- these are exactly the custom fighters' icons.
                extra_n += 1
                character = f'{EXTRA_ICON_PREFIX}{extra_n}'
                while character in by_char:
                    extra_n += 1
                    character = f'{EXTRA_ICON_PREFIX}{extra_n}'
            by_char[character] = src

    elif fmt == 'vanilla':
        # Vanilla icon grid: 64x56 static textures on fixed MenuModel joints.
        # The manifest's `icons` bucket contains these (one per joint), and
        # joint_index maps to a character via VANILLA_ICON_JOINT_TO_CHARACTER.
        for entry in manifest.get('icons', []):
            ji = entry.get('joint_index')
            if ji is None:
                continue
            character = VANILLA_ICON_JOINT_TO_CHARACTER.get(ji)
            if not character:
                continue
            filename = entry.get('filename')
            if not filename:
                continue
            src = css_dump_dir / filename
            if not src.exists():
                continue
            by_char[character] = src
        logger.info(f'  vanilla: matched {len(by_char)} characters via joint table')

    icons = [{'character': c, 'icon_path': p} for c, p in by_char.items()]
    return icons, fmt


# ─────────────────────────────────────────────────────────────────────────────
# Install (normalized output)
# ─────────────────────────────────────────────────────────────────────────────

def install_icon_grid_mod(zip_path, name=None, description=''):
    """Import an icon grid mod from a zip, persisting only the normalized payload.

    Returns a list of mod metadata dicts (with URLs attached). Most zips
    produce one mod, but zips bundling multiple packs (e.g. `name.png` and
    `=name.png` sets) produce one mod per pack.
    Raises on critical failure (bad zip, no icons extracted).
    """
    zip_path = Path(zip_path)
    if not zip_path.exists():
        raise FileNotFoundError(f'Zip not found: {zip_path}')

    default_name = zip_path.stem
    base_name = (name or default_name).strip() or default_name

    with tempfile.TemporaryDirectory(prefix='icongrid_') as tmp:
        temp_root = Path(tmp)
        extract_dir = temp_root / 'extracted'
        extract_dir.mkdir()
        work_dir = temp_root / 'work'
        work_dir.mkdir()

        _safe_extract_zip(zip_path, extract_dir)

        source_format = None
        packs = []  # list[list[{character, icon_path}]]

        # Loose-PNG first; falls back to DAT pipeline.
        packs = _label_loose_png(extract_dir)
        if packs:
            source_format = 'loose_png'
        else:
            dat_pack, fmt = _label_dat_mod(extract_dir, work_dir)
            if dat_pack:
                packs = [dat_pack]
                source_format = f'dat_{fmt}' if fmt else 'dat'

        if not packs:
            raise RuntimeError('No recognizable icons found in archive')

        screenshot_src = _find_screenshot(extract_dir)
        multi = len(packs) > 1

        def _sort_key(e):
            try:
                return (0, ROSTER_ORDER.index(e['character']))
            except ValueError:
                return (1, e['character'])

        installed = []
        catalog = _load_catalog()

        for pack_idx, pack in enumerate(packs):
            mod_id = str(uuid.uuid4())[:8]
            mod_dir = ICON_GRID_PATH / mod_id
            icons_dir = mod_dir / 'icons'
            icons_dir.mkdir(parents=True, exist_ok=True)

            # Copy screenshot (shared across all packs from this zip)
            screenshot_filename = None
            if screenshot_src is not None:
                screenshot_filename = f'screenshot{screenshot_src.suffix.lower()}'
                shutil.copy(str(screenshot_src), str(mod_dir / screenshot_filename))

            icon_entries = []
            for entry in pack:
                character = entry['character']
                src = entry.get('icon_path')
                if src is None:
                    continue
                icon_name = f'{_safe_filename(character)}.png'
                shutil.copy(str(src), str(icons_dir / icon_name))
                icon_entries.append({'character': character, 'icon': icon_name})
            icon_entries.sort(key=_sort_key)

            final_name = f"{base_name} ({pack_idx + 1})" if multi else base_name

            mod = {
                'id': mod_id,
                'name': final_name,
                'description': description or '',
                'screenshot': screenshot_filename,
                'source_format': source_format,
                'icons': icon_entries,
                'created': datetime.now().isoformat(),
            }
            _save_mod_json(mod_id, mod)
            catalog.setdefault('mods', []).append(_catalog_entry(mod))

            logger.info(
                f"[OK] Imported icon grid mod: {final_name} ({mod_id}) — "
                f"{len(icon_entries)} labeled icons ({source_format})"
            )
            installed.append(_attach_urls(mod))

        _save_catalog(catalog)
        return installed


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

def create_icon_grid_from_vanilla(name='New Icon Grid'):
    """Seed a new icon grid with the vanilla CSS icons so the per-icon editor
    (relabel / replace / add / delete) has a full roster to start from --
    the icon-grid twin of the pause / percent "create from vanilla" drafts.
    Returns the mod dict (with URLs). Raises RuntimeError when no vanilla
    MnSlChr is available (no ISO recorded) or extraction fails."""
    from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
    source = ensure_vanilla_ref('MnSlChr.usd') or ensure_vanilla_ref('MnSlChr.dat')
    if source is None:
        raise RuntimeError('No vanilla character select screen is available yet -- '
                           'run first-time setup with your Melee ISO first.')
    with tempfile.TemporaryDirectory(prefix='icongrid_new_') as tmp:
        zip_path = Path(tmp) / 'vanilla.zip'
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.write(str(source), source.name)
        mods = install_icon_grid_mod(zip_path, name=name)
    if not mods:
        raise RuntimeError('Could not extract the vanilla icons')
    return mods[0]
