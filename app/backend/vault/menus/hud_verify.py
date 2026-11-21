"""
Check the HUD typeface slots of "Currently in MEX" against the project file.

The Menus tab's record (nucleus_menus.json) only knows what Nucleus
installed. A project imported from an already-modded ISO said "Vanilla", and
an IfAll.usd edited outside the app kept showing the recorded mod. For the
two IfAll-backed slots (hud:percent_font = DmgNum/DmgMrk, hud:ready_go = the
ScInfCnt word banners) the project's IfAll.usd is decoded with
`HSDRawViewer --hud-textures export` (cached, menu_exports) and each slot of
the category is compared (menu_pixels, tolerant of re-encoding):

  * the recorded mod's pictures on its slots and vanilla everywhere else in
    the category -> the mod is there ("installed");
  * vanilla on every slot -> "vanilla";
  * otherwise -> "custom" (changed by something Nucleus did not record).

Vanilla comes from the user's vanilla disc IfAll.usd; without one only
byte-identical vanilla slots (the HUD manifest md5s) count as vanilla.
Installs also store the file's size/mtime, and the first check that sees the
file unchanged since then keeps the category's slot md5s as an exact
fingerprint, so a mod later edited in the vault is still recognized.

Anything that fails (tool missing, export error) leaves that slot out, so
the panel falls back to the record; this module never raises.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from .menu_exports import cached_export, file_sig
from .menu_pixels import same_picture

logger = logging.getLogger(__name__)

PERCENT_ROOTS = ('DmgNum_scene_models', 'DmgMrk_scene_models')
# Not typeface art: m-ex stock icons and series emblems live in IfAll too.
PROTECTED_ROOTS = ('Stc_scemdls', 'Eblm_matanim_joint')

# slot key -> the typeface category it shows
HUD_VERIFY_SLOTS = {'hud:percent_font': 'percent', 'hud:ready_go': 'readygo'}
CATEGORY_SLOT = {v: k for k, v in HUD_VERIFY_SLOTS.items()}

# record fields used here only; not sent to the frontend
INTERNAL_FIELDS = ('hud_fingerprint', 'file_stat')


def slot_key(entry):
    return f"{entry['root']}|{entry['kind']}|{entry['ordinal']}"


def _word_mat_keys():
    from core.hud_words import WORD_MAT_ORDINALS
    return {f'ScInfCnt_scene_models|mat|{o}'
            for ords in WORD_MAT_ORDINALS.values() for o in ords}


def slot_category(key):
    """'percent' / 'readygo' for a typeface slot key (as _mod_categories
    splits them: other HUD roots ride along with percent), None for roots
    that aren't typeface art."""
    root = key.split('|', 1)[0]
    if root in PROTECTED_ROOTS:
        return None
    if key in _word_mat_keys():
        return 'readygo'
    return 'percent'


def category_keys(category, keys):
    """The slot keys (out of `keys`) a category always covers."""
    if category == 'percent':
        return {k for k in keys if k.split('|', 1)[0] in PERCENT_ROOTS}
    return {k for k in _word_mat_keys() if k in keys}


def load_slots(path):
    """{slot key: {md5, format, index, file}} for an IfAll file, decoded via
    the cached export; None when it can't be read."""
    out_dir = cached_export('--hud-textures', path, timeout=300)
    if out_dir is None:
        return None
    try:
        from .percent import _with_ordinals
        entries = json.loads((out_dir / 'manifest.json').read_text(encoding='utf-8'))
        slots = {}
        for e in _with_ordinals(entries.get('textures', [])):
            slots[slot_key(e)] = {'md5': e.get('md5'), 'format': e.get('format'),
                                  'index': e.get('index'),
                                  'file': out_dir / e['filename']}
        return slots or None
    except Exception as e:
        logger.warning(f'HUD check: unreadable export of {Path(path).name}: {e}')
        return None


def vanilla_ifall_path():
    try:
        from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
        return ensure_vanilla_ref('IfAll.usd')
    except Exception:
        return None


def vanilla_slots():
    """Vanilla slots: decoded from the user's vanilla disc IfAll.usd, else
    md5-only from the HUD manifest (file None). None when neither exists."""
    ref = vanilla_ifall_path()
    if ref is not None:
        slots = load_slots(ref)
        if slots:
            return slots
    try:
        from .percent import _load_vanilla_manifest, _with_ordinals
        slots = {slot_key(e): {'md5': e.get('md5'), 'format': e.get('format'),
                               'index': e.get('index'), 'file': None}
                 for e in _with_ordinals(_load_vanilla_manifest('usd'))}
        return slots or None
    except Exception:
        return None


def slot_is_vanilla(file_slot, vanilla_slot):
    if vanilla_slot is None:
        return None
    if file_slot.get('md5') and file_slot.get('md5') == vanilla_slot.get('md5'):
        return True
    if vanilla_slot.get('file') is None or file_slot.get('file') is None:
        return False
    return bool(same_picture(file_slot['file'], vanilla_slot['file'], 'reencode'))


def _mod_expectations(mod, mod_dir):
    """{slot key: (png, kind)} for a stored typeface mod."""
    out = {}
    for s in (mod or {}).get('slots', []):
        png = Path(mod_dir) / 'textures' / s.get('file', '')
        if png.is_file():
            out[slot_key(s)] = (png, 'source' if s.get('replaced') else 'reencode')
    return out


def _mod_matches(file_slots, vanilla, category, expected):
    """True/False: the category shows exactly this mod (its pictures on its
    slots, vanilla elsewhere). None when nothing could be compared."""
    keys = category_keys(category, file_slots.keys() & vanilla.keys())
    mine = {k: v for k, v in expected.items()
            if slot_category(k) == category and k in file_slots}
    if not mine:
        return None
    for k in keys | set(mine):
        if k in mine:
            png, kind = mine[k]
            ok = same_picture(file_slots[k]['file'], png, kind)
        else:
            ok = slot_is_vanilla(file_slots[k], vanilla.get(k))
        if ok is None:
            return None
        if not ok:
            return False
    return True


def _mod_changed_since(record, mod_dir):
    """The vault mod was edited after this install (its pictures may no
    longer be what was written)."""
    try:
        when = datetime.fromisoformat(str(record.get('installed')))
        mtime = datetime.fromtimestamp((Path(mod_dir) / 'mod.json').stat().st_mtime)
        return mtime > when
    except Exception:
        return False


def verify_hud_slots(installed, ifall_path):
    """Compare the HUD typeface slots with the project's IfAll.usd.

    Returns ({slot_key: {state, stale?, unverified?}}, {slot_key:
    fingerprint to store}). state: 'installed' (show the record), 'vanilla',
    or 'custom' (changed outside the record). `stale` = a record exists but
    the file no longer holds it. Slots that cannot be checked are left out."""
    verification, new_fingerprints = {}, {}
    try:
        ifall_path = Path(ifall_path)
        if not ifall_path.is_file():
            return verification, new_fingerprints
        file_slots = load_slots(ifall_path)
        if not file_slots:
            return verification, new_fingerprints
        vanilla = vanilla_slots()
        if not vanilla:
            return verification, new_fingerprints
        sig = file_sig(ifall_path)
        from .percent import PERCENT_PATH, load_mod_json

        for record_key, category in HUD_VERIFY_SLOTS.items():
            keys = category_keys(category, file_slots.keys() & vanilla.keys())
            if not keys:
                continue
            vanilla_by_key = {k: slot_is_vanilla(file_slots[k], vanilla[k]) for k in keys}
            all_vanilla = all(vanilla_by_key.values())

            entry = installed.get(record_key)
            entry = entry if isinstance(entry, dict) else None
            if entry is None:
                verification[record_key] = {'state': 'vanilla' if all_vanilla else 'custom',
                                            'stale': False}
                continue

            fingerprint = entry.get('hud_fingerprint')
            if not fingerprint and entry.get('file_stat') == sig:
                # untouched since this install: its slots are what it wrote
                fingerprint = {k: file_slots[k]['md5'] for k in keys if not vanilla_by_key[k]}
                if fingerprint:
                    new_fingerprints[record_key] = fingerprint
            if fingerprint:
                fp = {k: v for k, v in fingerprint.items() if k in file_slots}
                if fp and all(file_slots[k]['md5'] == v for k, v in fp.items()) \
                        and all(vanilla_by_key[k] for k in keys if k not in fp):
                    verification[record_key] = {'state': 'installed'}
                    continue

            match = None
            mod_dir = PERCENT_PATH / str(entry.get('id') or '')
            mod = load_mod_json(PERCENT_PATH, entry['id']) if entry.get('id') else None
            if mod:
                match = _mod_matches(file_slots, vanilla, category,
                                     _mod_expectations(mod, mod_dir))
            if match:
                verification[record_key] = {'state': 'installed'}
            elif all_vanilla:
                verification[record_key] = {'state': 'vanilla', 'stale': True}
            elif match is None or (not fingerprint and _mod_changed_since(entry, mod_dir)):
                # vault mod gone or edited since: can't tell it from other
                # edits, so trust the record
                verification[record_key] = {'state': 'installed', 'unverified': True}
            else:
                verification[record_key] = {'state': 'custom', 'stale': True}
    except Exception as e:
        logger.warning(f'HUD verify skipped: {e}')
        return {}, {}
    return verification, new_fingerprints
