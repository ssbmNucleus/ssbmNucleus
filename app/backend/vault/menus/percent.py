"""
Percent font / HUD (IfAll) mods: the catalog and each mod's categories (percent
digits, Ready/Go banners), the vanilla slot manifest, importing IfAll files or
glyph/word picture packs, and the stored glyph state the editor reads.
"""

import json
import shutil
import tempfile
import uuid
import zipfile
import logging
from pathlib import Path
from datetime import datetime
from core.hud_words import (WORD_KEYS, word_key_for_name, GLYPH_KEYS,
    group_slots as _group_slots, with_ordinals as _with_ordinals, word_slots as _word_slots)
from shared.vanilla_extract.menu_refs import hud_dir
from vault.menus.store import (
    PERCENT_METADATA, PERCENT_PATH, load_catalog, load_mod_json, save_catalog, save_mod_json)
from vault.menus.files import _find_screenshot, _safe_extract_zip
from vault.menus.hsd import _run_hsd_cli

logger = logging.getLogger(__name__)


IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg', '.webp')

# Vanilla IfAll slot manifests (--hud-textures export; a raw-buffer md5 per
# slot for diffing). Derived from the user's own project at first run
# (menu_refs) together with the glyph previews; until then the shipped
# manifests answer (no pictures ship). Resolve per call so a derivation that
# lands mid-session is picked up.
def VANILLA_MANIFEST_DIR():
    return hud_dir()

# Source formats that carry color; injecting them into a grayscale vanilla
# slot as "original" would discard the color, so they re-encode as RGB5A3.
COLOR_FORMATS = {'RGB5A3', 'RGB565', 'RGBA8', 'CMP', 'CI8', 'CI4', 'CI14X2'}

# WORD_KEYS / UNIQUE_WORD_DIMS, the filename rules, GLYPH_KEYS /
# WORD_MAT_ORDINALS and the vanilla slot grouping live in core/hud_words.py so
# the unified import classifier and the first-run glyph previews
# (shared/vanilla_extract/menu_refs.py) use the same rules without importing this
# blueprint.
ALL_EDIT_KEYS = GLYPH_KEYS + WORD_KEYS


def _load_vanilla_manifest(region):
    """region: 'usd' or 'dat'. Returns the texture entry list or []."""
    try:
        with open(VANILLA_MANIFEST_DIR() / f'manifest_{region}.json', 'r', encoding='utf-8') as f:
            return json.load(f).get('textures', [])
    except Exception as e:
        logger.warning(f'Vanilla HUD manifest ({region}) unavailable: {e}')
        return []


def _structure_seq(entries):
    # Only the slot skeleton — mods legitimately change texture formats
    # (grayscale → RGB5A3 for color) and occasionally dimensions.
    return [(e['root'], e['kind']) for e in entries]


def _detect_region(entries):
    """Match an exported mod's slot structure against the vanilla manifests.
    Returns ('usd'|'dat', vanilla_entries) or (None, None)."""
    seq = _structure_seq(entries)
    for region in ('usd', 'dat'):
        vanilla = _load_vanilla_manifest(region)
        if vanilla and _structure_seq(vanilla) == seq:
            return region, vanilla
    return None, None


def _mod_categories(mod):
    """Which HUD sub-categories a mod belongs to, derived from its slots:
    'percent' (damage digits / emblem) and/or 'readygo' (word banners).
    Empty custom mods fall back to the category they were created from."""
    vanilla = _load_vanilla_manifest('usd')
    word_keys = set()
    for word, entries in _word_slots(vanilla).items():
        for e in entries:
            word_keys.add((e['root'], e['kind'], e['ordinal']))

    cats = set()
    for s in mod.get('slots', []):
        if s['root'] in ('DmgNum_scene_models', 'DmgMrk_scene_models'):
            cats.add('percent')
        elif (s['root'], s['kind'], s['ordinal']) in word_keys:
            cats.add('readygo')
        else:
            # other HUD roots (timer, P badges...) ride along with percent
            cats.add('percent')
    if not cats and mod.get('origin_category'):
        cats.add(mod['origin_category'])
    return sorted(cats) or ['percent']


def _load_percent_catalog():
    return load_catalog(PERCENT_METADATA, '1.0')


def _update_catalog_categories(mod):
    """Refresh a mod's category tags in the catalog after its slots change
    (glyph/word edits can move a custom mod between HUD sub-categories)."""
    catalog = _load_percent_catalog()
    entry = next((m for m in catalog.get('mods', []) if m.get('id') == mod['id']), None)
    if entry is not None:
        entry['categories'] = _mod_categories(mod)
        _save_percent_catalog(catalog)


def _save_percent_catalog(data):
    save_catalog(PERCENT_METADATA, data)


def _attach_percent_urls(mod):
    out = dict(mod)
    if mod.get('id'):
        out['imageUrl'] = f"/api/mex/menus/percent/image/{mod['id']}"
    return out


def _find_ifall_files(directory):
    """All IfAll*.dat/.usd files in an extracted directory, sorted by name."""
    found = []
    for p in sorted(Path(directory).rglob('*')):
        if not p.is_file():
            continue
        name_lower = p.name.lower()
        if name_lower.startswith('ifall') and name_lower.endswith(('.dat', '.usd')):
            found.append(p)
    return found


def _find_glyph_images(directory):
    """Map glyph key → image path for loose glyph-pack files (`0zero.png`,
    `7.png`, `percent.png`, `HP.png`...). Ambiguous names are skipped;
    first match per glyph wins."""
    glyphs = {}
    for p in sorted(Path(directory).rglob('*')):
        if not p.is_file() or p.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        if '__MACOSX' in p.parts:
            continue
        stem = p.stem.lower().strip()
        key = None
        if stem and stem[0].isdigit() and (len(stem) == 1 or not stem[1].isdigit()):
            key = stem[0]
        elif 'percent' in stem or stem == '%':
            key = 'percent'
        elif stem == 'hp' or stem.startswith('hp'):
            key = 'hp'
        if key and key not in glyphs:
            glyphs[key] = p
    return glyphs


_word_key_for_name = word_key_for_name


def _find_word_images(directory):
    """Map word key → image path for loose word-banner files. First match
    per word wins (multi-variant packs keep their first folder)."""
    words = {}
    for p in sorted(Path(directory).rglob('*')):
        if not p.is_file() or p.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        if '__MACOSX' in p.parts:
            continue
        key = _word_key_for_name(p.name)
        if key and key not in words:
            words[key] = p
    return words


def looks_like_percent_zip(zip_path):
    """True if the zip contains an IfAll dat/usd, a full digit glyph pack,
    or a Ready/Go/Game word pack (3+ recognizable banners)."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            digit_stems = set()
            word_keys = set()
            for n in zf.namelist():
                if n.startswith('__MACOSX'):
                    continue
                base = Path(n).name.lower()
                if base.startswith('ifall') and base.endswith(('.dat', '.usd')):
                    return True
                if not base.endswith(IMAGE_SUFFIXES):
                    continue
                stem = Path(base).stem
                if stem and stem[0].isdigit() and (len(stem) == 1 or not stem[1].isdigit()):
                    digit_stems.add(stem[0])
                key = _word_key_for_name(base)
                if key:
                    word_keys.add(key)
            return len(digit_stems) == 10 or len(word_keys) >= 3
    except zipfile.BadZipFile:
        return False


def _variant_label(dat_path, base_name):
    """`IfAll(white).dat` → `<base_name> (white)`; bare names keep base_name."""
    stem = dat_path.stem
    suffix = stem[len('ifall'):].strip(' _-()') if stem.lower().startswith('ifall') else stem
    return f'{base_name} ({suffix})' if suffix else base_name


def _store_slots(mod_dir, slot_sources):
    """Copy slot source PNGs into <mod_dir>/textures/s<n>.png. slot_sources is
    a list of (vanilla_entry_with_ordinal, src_path, replaced[, glyph_key]).
    Returns the mod.json slot list."""
    tex_dir = mod_dir / 'textures'
    tex_dir.mkdir(parents=True, exist_ok=True)
    slots = []
    for n, source in enumerate(slot_sources):
        entry, src, replaced = source[:3]
        glyph = source[3] if len(source) > 3 else None
        fname = f's{n}.png'
        shutil.copy(str(src), str(tex_dir / fname))
        slot = {
            'root': entry['root'],
            'kind': entry['kind'],
            'ordinal': entry['ordinal'],
            'width': entry['width'],
            'height': entry['height'],
            'format': entry['format'],
            'file': fname,
            'replaced': bool(replaced),
        }
        if glyph:
            # lets the glyph/word editor revert pack-imported slots
            slot['glyph'] = glyph
        slots.append(slot)
    return slots


def _compose_preview(mod_dir, slots):
    """Compose a 0-9 + % glyph strip from the mod's stored DmgNum textures.
    Best-effort: returns True if preview.png was written."""
    try:
        from PIL import Image
    except ImportError:
        return False

    # vanilla bank 1: anim ordinals 0..9 are digits 0..9, the first 32x24
    # anim ordinal is the % sign
    wanted = [('anim', 36, i) for i in range(10)]
    by_key = {}
    digit_seen = {}
    for s in slots:
        if s['root'] != 'DmgNum_scene_models':
            continue
        key = (s['kind'], s['height'], s['ordinal'])
        by_key[key] = s
    # locate % slot: smallest 32x24 anim ordinal stored
    pct = sorted([s for s in slots if s['root'] == 'DmgNum_scene_models'
                  and s['kind'] == 'anim' and s['height'] == 24],
                 key=lambda s: s['ordinal'])
    picks = [by_key.get(k) for k in wanted]
    picks.append(pct[0] if pct else None)
    picks = [p for p in picks if p]
    if len(picks) < 3:
        return False

    images = []
    for s in picks:
        p = mod_dir / 'textures' / s['file']
        if p.exists():
            images.append(Image.open(p).convert('RGBA'))
    if len(images) < 3:
        return False

    w = sum(im.width for im in images)
    h = max(im.height for im in images)
    strip = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    x = 0
    for im in images:
        strip.paste(im, (x, h - im.height), im)
        x += im.width
    strip = strip.resize((w * 3, h * 3), Image.NEAREST)
    strip.save(mod_dir / 'preview.png')
    return True


def _import_percent_dat(dat_path, name, description, screenshot_src, catalog):
    """Diff a compiled IfAll against vanilla and store the changed slots as a
    new mod. Returns the mod dict (without URLs) or raises RuntimeError."""
    with tempfile.TemporaryDirectory(prefix='percent_export_') as tmp:
        export_dir = Path(tmp) / 'dump'
        export_dir.mkdir()
        result = _run_hsd_cli(['--hud-textures', 'export', str(dat_path), str(export_dir)],
                              timeout=300)
        if result is None:
            raise RuntimeError(f'Failed to extract textures from {dat_path.name}')

        manifest_path = export_dir / 'manifest.json'
        if not manifest_path.exists():
            raise RuntimeError('HSDRawViewer did not produce a texture manifest')
        with open(manifest_path, 'r', encoding='utf-8') as f:
            mod_entries = json.load(f).get('textures', [])
        if not mod_entries:
            raise RuntimeError(f'No textures found in {dat_path.name}')

        region, vanilla = _detect_region(mod_entries)
        if region is None:
            raise RuntimeError(f'{dat_path.name} does not match the vanilla IfAll '
                               'structure (not an IfAll file, or heavily restructured)')

        mod_entries = _with_ordinals(mod_entries)
        vanilla = _with_ordinals(vanilla)
        # Modders often build a "JP" IfAll.dat from US textures (or vice
        # versa); slots that are stock art from EITHER region are
        # localization noise, not edits — e.g. the US "Time!"/"Game!"
        # banners showing up as diffs against the JP baseline.
        other_region = 'dat' if region == 'usd' else 'usd'
        other_md5 = {(e['root'], e['kind'], e['ordinal']): e['md5']
                     for e in _with_ordinals(_load_vanilla_manifest(other_region))}
        slot_sources = []
        for me, ve in zip(mod_entries, vanilla):
            if me['md5'] == ve['md5']:
                continue
            if me['md5'] == other_md5.get((ve['root'], ve['kind'], ve['ordinal'])):
                continue
            # Colored source pixels need a color format in the (grayscale)
            # target slot; matching formats reinject as the target original.
            replaced = me['format'] != ve['format'] and me['format'] in COLOR_FORMATS
            slot_sources.append((ve, export_dir / me['filename'], replaced))

        if not slot_sources:
            raise RuntimeError(f'{dat_path.name} is identical to vanilla — nothing to import')

        mod_id = str(uuid.uuid4())[:8]
        mod_dir = PERCENT_PATH / mod_id
        slots = _store_slots(mod_dir, slot_sources)

        screenshot_filename = None
        if screenshot_src is not None and screenshot_src.exists():
            screenshot_filename = f'screenshot{screenshot_src.suffix.lower()}'
            shutil.copy(str(screenshot_src), str(mod_dir / screenshot_filename))
        _compose_preview(mod_dir, slots)

        mod = {
            'id': mod_id,
            'name': name,
            'description': description,
            'source': 'dat',
            'region': region,
            'screenshot': screenshot_filename,
            'slots': slots,
            'created': datetime.now().isoformat(),
        }
        save_mod_json(PERCENT_PATH, mod_id, mod)
        catalog.setdefault('mods', []).append({
            'id': mod_id,
            'name': name,
            'description': description,
            'source': 'dat',
            'categories': _mod_categories(mod),
            'created': mod['created'],
        })
        logger.info(f'[OK] Imported percent font mod: {name} ({mod_id}) — '
                    f'{len(slots)} changed slots from {dat_path.name} [{region}]')
        return mod


def _import_glyph_pack(glyphs, name, description, screenshot_src, catalog):
    """Build a mod from loose glyph/word images: each image lands on every
    slot showing that glyph (digits/percent/HP) or word banner (READY/GO!/
    GAME!...). Returns the mod dict or raises."""
    vanilla = _load_vanilla_manifest('usd')
    groups = _group_slots(vanilla)
    if not groups:
        raise RuntimeError('Vanilla HUD manifest unavailable; cannot import glyph packs')

    slot_sources = []
    for key, img_path in glyphs.items():
        for entry in groups.get(key, []):
            slot_sources.append((entry, img_path, True, key))
    if not slot_sources:
        raise RuntimeError('No recognizable glyph (0-9, percent, HP) or word '
                           '(ready/go/game/...) images found')

    mod_id = str(uuid.uuid4())[:8]
    mod_dir = PERCENT_PATH / mod_id
    slots = _store_slots(mod_dir, slot_sources)

    screenshot_filename = None
    if screenshot_src is not None and screenshot_src.exists():
        screenshot_filename = f'screenshot{screenshot_src.suffix.lower()}'
        shutil.copy(str(screenshot_src), str(mod_dir / screenshot_filename))
    _compose_preview(mod_dir, slots)

    mod = {
        'id': mod_id,
        'name': name,
        'description': description,
        'source': 'glyphs',
        'region': 'usd',
        'screenshot': screenshot_filename,
        'slots': slots,
        'created': datetime.now().isoformat(),
    }
    save_mod_json(PERCENT_PATH, mod_id, mod)
    catalog.setdefault('mods', []).append({
        'id': mod_id,
        'name': name,
        'description': description,
        'source': 'glyphs',
        'categories': _mod_categories(mod),
        'created': mod['created'],
    })
    logger.info(f'[OK] Imported percent glyph pack: {name} ({mod_id}) — '
                f'{len(glyphs)} glyphs over {len(slots)} slots')
    return mod


def install_percent_mods_from_zip(zip_path, name=None, description=''):
    """Import every IfAll variant (or a glyph pack) from a zip. Returns list of
    mod dicts with URLs attached. Raises RuntimeError when nothing is found."""
    zip_path = Path(zip_path)
    base_name = (name or zip_path.stem).strip() or zip_path.stem

    with tempfile.TemporaryDirectory(prefix='percent_import_') as tmp:
        extract_dir = Path(tmp) / 'extracted'
        extract_dir.mkdir()
        _safe_extract_zip(zip_path, extract_dir)

        dats = _find_ifall_files(extract_dir)
        screenshot_src = _find_screenshot(extract_dir)
        catalog = _load_percent_catalog()
        installed = []
        dat_errors = []

        multi = len(dats) > 1
        for dat in dats:
            mod_name = _variant_label(dat, base_name) if multi else base_name
            try:
                mod = _import_percent_dat(dat, mod_name, description, screenshot_src, catalog)
                installed.append(_attach_percent_urls(mod))
            except RuntimeError as e:
                dat_errors.append(str(e))

        if not installed:
            # No usable compiled IfAll — some archives ship a non-vanilla dat
            # (e.g. SD Remix IfAl1 renamed) alongside perfectly good glyph PNGs.
            glyphs = _find_glyph_images(extract_dir)
            if len([k for k in glyphs if k.isdigit()]) < 10:
                glyphs = {}   # partial digit sets are too ambiguous to trust
            words = _find_word_images(extract_dir)
            pack = {**glyphs, **words}
            if pack:
                mod = _import_glyph_pack(pack, base_name, description, screenshot_src, catalog)
                installed.append(_attach_percent_urls(mod))
            elif dat_errors:
                raise RuntimeError('; '.join(dat_errors))
            else:
                raise RuntimeError('No IfAll .dat/.usd, digit glyph pack (0-9), or '
                                   'Ready/Go/Game word pack found in archive')

        _save_percent_catalog(catalog)
        return installed


def catalog_mods_with_categories():
    """Every catalog entry with its `categories` tag filled in (older entries
    predate the tag; it is derived from the mod's slots and persisted once).
    Shared by the list route and the vault-wide menus summary."""
    catalog = _load_percent_catalog()
    dirty = False
    mods = []
    for m in catalog.get('mods', []):
        if not m.get('id'):
            continue
        if 'categories' not in m:
            full = load_mod_json(PERCENT_PATH, m['id'])
            m['categories'] = _mod_categories(full or {})
            dirty = True
        mods.append(m)
    if dirty:
        _save_percent_catalog(catalog)
    return mods


def percent_preview_path(mod_id, mod=None):
    """The file get_percent_image serves for a mod (zip screenshot, composed
    glyph strip, or the largest stored texture), or None."""
    mod = mod if mod is not None else load_mod_json(PERCENT_PATH, mod_id)
    if not mod:
        return None
    mod_dir = PERCENT_PATH / mod_id
    candidates = []
    if mod.get('screenshot'):
        candidates.append(mod_dir / mod['screenshot'])
    candidates.append(mod_dir / 'preview.png')
    for slot in sorted(mod.get('slots', []),
                       key=lambda s: s.get('width', 0) * s.get('height', 0),
                       reverse=True):
        candidates.append(mod_dir / 'textures' / slot['file'])
    return next((p for p in candidates if p.exists()), None)


def _mod_glyph_state(mod):
    """Per-glyph/word editor state for a mod: which keys have a stored
    texture. Returns {key: slot} using the first stored slot of each key's
    vanilla group (all slots in a group carry the same image)."""
    vanilla = _load_vanilla_manifest('usd')
    groups = _group_slots(vanilla)
    slot_index = {(s['root'], s['kind'], s['ordinal']): s for s in mod.get('slots', [])}
    state = {}
    for key, entries in groups.items():
        for e in entries:
            s = slot_index.get((e['root'], e['kind'], e['ordinal']))
            if s is not None:
                state[key] = s
                break
    return state


def _glyph_listing(mod_id, mod, keys):
    state = _mod_glyph_state(mod)
    out = []
    for key in keys:
        slot = state.get(key)
        out.append({
            'key': key,
            'replaced': bool(slot and slot.get('replaced')),
            'overridden': slot is not None,
            'url': f'/api/mex/menus/percent/glyph/{mod_id}/{key}',
        })
    return out
