"""
HUD typeface (IfAll) install engine: write a stored percent font / Ready-Go mod
into an IfAll.usd on disk with HSDRawViewer --hud-textures import, putting the
slots its categories cover back to vanilla in the same write, and the "Currently
in MEX" slot bookkeeping for HUD installs.

No routes. Used by the project-side percent routes
(projects/routes/menus/percent.py: install, restore vanilla) and the installed
record (projects/routes/menus/installed.py).
"""

import json
import shutil
import tempfile
import logging
import file_retry
from pathlib import Path
from core.config import HSDRAW_EXE
from core.hud_words import with_ordinals as _with_ordinals
from vault.menus.store import PERCENT_PATH, load_mod_json
from vault.menus.hsd import _run_hsd_cli
from vault.menus.percent import _load_vanilla_manifest, _mod_categories

logger = logging.getLogger(__name__)


def _build_replacement_spec(mod, mod_dir, target_region='usd'):
    """Map a mod's stored (root, kind, ordinal) slots onto the target file's
    global texture indices. Returns the --hud-textures import replacement
    list; raises RuntimeError when payloads are missing."""
    vanilla = _with_ordinals(_load_vanilla_manifest(target_region))
    if not vanilla:
        raise RuntimeError('Vanilla HUD manifest unavailable')
    index_by_slot = {(e['root'], e['kind'], e['ordinal']): e['index'] for e in vanilla}

    replacements = []
    for slot in mod.get('slots', []):
        tex_path = mod_dir / 'textures' / slot['file']
        if not tex_path.exists():
            continue
        target_index = index_by_slot.get((slot['root'], slot['kind'], slot['ordinal']))
        if target_index is None:
            logger.warning(f"Slot {slot['root']}/{slot['kind']}/{slot['ordinal']} "
                           f'has no match in the {target_region} IfAll; skipping')
            continue
        fmt = 'rgb5a3' if slot.get('replaced') else 'original'
        replacements.append({'index': target_index, 'png': str(tex_path), 'format': fmt})
    if not replacements:
        raise RuntimeError('No textures stored for this mod')
    return replacements


def hud_reset_keys(categories, previous_mods=()):
    """Slot keys ("root|kind|ordinal") to put back to vanilla before a
    typeface of these categories goes in: every slot the categories cover
    (percent = DmgNum/DmgMrk, readygo = the word banners) plus whatever the
    previously installed mods of those categories wrote elsewhere (a timer
    glyph...). Never m-ex stock icons or series emblems."""
    from vault.menus import hud_verify
    universe = {hud_verify.slot_key(e)
                for e in _with_ordinals(_load_vanilla_manifest('usd'))}
    keys = set()
    for cat in categories or []:
        keys |= hud_verify.category_keys(cat, universe)
    for prev in previous_mods or []:
        for s in (prev or {}).get('slots', []):
            k = hud_verify.slot_key(s)
            if k in universe and hud_verify.slot_category(k) in (categories or []):
                keys.add(k)
    return keys


def _vanilla_reset_replacements(keys, target_region, skip_keys=()):
    """--hud-textures import entries that put `keys` back to the vanilla
    pictures of the user's vanilla disc IfAll.usd. Raises RuntimeError when
    no vanilla IfAll is available (or the target isn't the US file)."""
    from vault.menus import hud_verify
    keys = set(keys) - set(skip_keys)
    if not keys:
        return []
    if target_region != 'usd':
        raise RuntimeError('Vanilla HUD reset only supports IfAll.usd')
    ref = hud_verify.vanilla_ifall_path()
    vanilla = hud_verify.load_slots(ref) if ref is not None else None
    if not vanilla:
        raise RuntimeError('No vanilla HUD file is available -- set your vanilla '
                           'Melee ISO in Settings first.')
    index_by_key = {hud_verify.slot_key(e): e['index']
                    for e in _with_ordinals(_load_vanilla_manifest(target_region))}
    out = []
    for k in sorted(keys):
        v = vanilla.get(k)
        if k in index_by_key and v and v.get('file') and Path(v['file']).is_file():
            out.append({'index': index_by_key[k], 'png': str(v['file']), 'format': 'original'})
    return out


def _run_hud_import(ifall_path, replacements):
    # A scanner may still hold the output in here; scratch left behind must not fail the install.
    with tempfile.TemporaryDirectory(prefix='percent_install_', ignore_cleanup_errors=True) as tmp:
        spec_path = Path(tmp) / 'spec.json'
        with open(spec_path, 'w', encoding='utf-8') as f:
            json.dump({'replacements': replacements}, f)

        output = Path(tmp) / ifall_path.name
        result = _run_hsd_cli([
            '--hud-textures', 'import',
            str(ifall_path), str(spec_path), str(output)
        ], timeout=300)
        if result is None:
            raise RuntimeError('HSDRawViewer --hud-textures import failed')
        if not output.exists():
            raise RuntimeError('Import produced no output file')

        file_retry.retry_locked(shutil.copy, str(output), str(ifall_path))


def apply_percent_mod(mod_id, ifall_path, reset_keys=None, notes=None):
    """Apply a stored percent mod to an IfAll.usd on disk (in place) via
    HSDRawViewer --hud-textures import. Raises on failure.

    `reset_keys` (hud_reset_keys): slots put back to vanilla in the same
    import, so the previous typeface leaves nothing behind where this one
    has no picture. When the reset can't run (no vanilla ISO) the mod is
    still applied and the reason is appended to `notes` (a list). Returns
    the mod."""
    mod = load_mod_json(PERCENT_PATH, mod_id)
    if not mod:
        raise RuntimeError('Mod not found')
    ifall_path = Path(ifall_path)
    if not ifall_path.exists():
        raise RuntimeError(f'IfAll file not found at {ifall_path}')
    if not HSDRAW_EXE.exists():
        raise RuntimeError(f'HSDRawViewer not found at {HSDRAW_EXE}')

    target_region = 'usd' if ifall_path.suffix.lower() == '.usd' else 'dat'
    replacements = _build_replacement_spec(mod, PERCENT_PATH / mod_id, target_region)

    if reset_keys:
        from vault.menus import hud_verify
        own = {hud_verify.slot_key(s) for s in mod.get('slots', [])}
        taken = {r['index'] for r in replacements}
        try:
            resets = [r for r in _vanilla_reset_replacements(reset_keys, target_region, own)
                      if r['index'] not in taken]
            replacements = resets + replacements
        except RuntimeError as e:
            if notes is not None:
                notes.append(str(e))
            logger.warning(f'  HUD reset skipped: {e}')

    _run_hud_import(ifall_path, replacements)
    return mod


# "Currently in MEX" slot keys (see installed.record_installed_menu_mod) for the
# two HUD sub-categories a typeface mod can cover.
HUD_SLOT_BY_CATEGORY = {'percent': 'hud:percent_font', 'readygo': 'hud:ready_go'}
_REQUESTED_SLOT_ALIASES = {
    'percent': 'hud:percent_font', 'percent_font': 'hud:percent_font',
    'hud:percent_font': 'hud:percent_font',
    'readygo': 'hud:ready_go', 'ready_go': 'hud:ready_go', 'hud:ready_go': 'hud:ready_go',
}


def _install_slot_keys(categories, requested=None):
    """Which "Currently in MEX" slots an install occupies. Installing writes
    EVERY stored slot of the mod, so a typeface covering digits and word
    banners lands in both; the tab the user installed from (`requested`) is
    always included and listed first."""
    keys = []
    req = _REQUESTED_SLOT_ALIASES.get(str(requested or '').strip().lower())
    if req:
        keys.append(req)
    for cat in categories or []:
        key = HUD_SLOT_BY_CATEGORY.get(cat)
        if key and key not in keys:
            keys.append(key)
    return keys or ['hud:percent_font']


def repair_hud_install_records(installed):
    """Fix records written before installs knew their slot: every HUD typeface
    install used to be filed under hud:percent_font, so a Ready/Go pack showed
    on the Percent Font tab (and Ready/Go showed Vanilla). Only touches legacy
    entries (no `categories` key); marks what it repairs so it runs once.
    Mutates `installed`; returns True when something changed."""
    entry = installed.get('hud:percent_font')
    if not isinstance(entry, dict) or 'categories' in entry or not entry.get('id'):
        return False
    full = load_mod_json(PERCENT_PATH, entry['id'])
    if not full:
        return False   # vault mod gone: nothing to tell the categories from
    categories = _mod_categories(full)
    # a preview snapshot file is per slot; never carry one across slots
    fixed = {k: v for k, v in entry.items() if k not in ('snapshot', 'snapshotUrl')}
    fixed['categories'] = categories
    if 'readygo' not in categories:
        installed['hud:percent_font'] = fixed
        return True
    other = installed.get('hud:ready_go')
    newer = not isinstance(other, dict) or         str(other.get('installed') or '') < str(entry.get('installed') or '')
    if newer:
        installed['hud:ready_go'] = {**fixed, 'kind': 'ready_go'}
    if 'percent' in categories:
        installed['hud:percent_font'] = fixed
    else:
        del installed['hud:percent_font']
    return True


def _recorded_hud_mods(categories):
    """Vault mods recorded in the "Currently in MEX" slots of these
    categories (whose leftovers a reset must also clear)."""
    try:
        from vault.menus.installed import load_installed_menu_mods
        installed = load_installed_menu_mods()
    except Exception:
        return []
    mods = []
    for cat in categories or []:
        entry = installed.get(HUD_SLOT_BY_CATEGORY.get(cat, ''))
        if isinstance(entry, dict) and entry.get('id'):
            full = load_mod_json(PERCENT_PATH, entry['id'])
            if full:
                mods.append(full)
    return mods
