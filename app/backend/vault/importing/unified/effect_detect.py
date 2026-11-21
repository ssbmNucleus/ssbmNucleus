"""
Effect (extras) auto-detection for the unified importer.

An effect mod is a whole game file -- EfFxData.dat, EfCoData.dat, PlFx.dat
-- and nothing in its name says WHICH editable effect it changes: one
EfFxData.dat might recolor the laser, the shine, both, or carry an image
shine. This module answers that by reading the file through the same
offset system the extras editors use (derive_modifications_from_dat,
texture_region.read_region) for every extra type that targets the file,
and comparing each reading against the vanilla reference DAT:

    candidate_effects(dat_bytes, 'EfFxDataBRAT.dat')
    -> [{'character': 'Fox', 'extra_type': 'shine', 'name': 'Shine Color',
         'differs': True}, {'character': 'Fox', 'extra_type': 'laser', ...,
         'differs': False}, ...]

`differs` is None when no vanilla reference is available (no ISO recorded
yet) -- the caller then asks the user instead of guessing. Pure with respect
to the vault: reads temp files only, never writes metadata.
"""

import logging
import os
import tempfile
from pathlib import Path

from core.extra_types import EXTRA_TYPES

logger = logging.getLogger(__name__)


def _target_index():
    """{target stem (lower): [(owner character, type config), ...]}"""
    index = {}
    for owner, extras in EXTRA_TYPES.items():
        for cfg in extras:
            target = cfg.get('target_file')
            if not target:
                continue
            index.setdefault(Path(target).stem.lower(), []).append((owner, cfg))
    return index


def match_target(basename):
    """(target_file, [(owner, cfg), ...]) for a DAT filename, or (None, []).

    Ef*Data targets accept any decoration after the stem ('EfFxDataBRAT.dat',
    'EfCoData rainbow fire.dat'). Pl* targets only accept a non-letter
    decoration ('PlFx.dat', 'PlFx (v2).dat'): 'PlFxNr.dat' is a costume.
    """
    stem = Path(basename).stem.lower().strip()
    if not stem:
        return None, []
    best = None
    for tstem, entries in _target_index().items():
        if stem == tstem:
            hit = True
        elif stem.startswith(tstem):
            rest = stem[len(tstem):]
            hit = tstem.startswith('ef') or not rest[0].isalpha()
        else:
            hit = False
        if hit and (best is None or len(tstem) > len(best[0])):
            best = (tstem, entries)
    if best is None:
        return None, []
    _, entries = best
    return entries[0][1]['target_file'], entries


def _signature(dat_path, cfg):
    """What this extra type reads out of the DAT, in a comparable form:
    ('colors', {...}) / ('image', None) / ('region', bytes) / ('model', None),
    or None when the type cannot read the file (not importable as this type)."""
    fmt = cfg.get('format')
    if fmt == 'texture_region':
        from vault.extras import texture_region as tr
        try:
            return ('region', tr.read_region(dat_path, cfg))
        except Exception:
            return None
    if cfg.get('type') == 'model':
        # A replacement model (gun) has no cheap byte-level tell.
        return ('model', None)
    from vault.extras.derive import derive_modifications_from_dat
    try:
        mods = derive_modifications_from_dat(dat_path, cfg['id'], cfg)
    except Exception as e:
        logger.debug(f'[effect_detect] {cfg["id"]} derive failed: {e}')
        return None
    if not mods:
        return None
    if 'image' in mods:
        return ('image', None)
    if 'sideb_model' in mods:
        return ('afterimage', mods['sideb_model']['sha256'])
    return ('colors', mods)


def _vanilla_ref(target_file):
    try:
        from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
        return ensure_vanilla_ref(target_file)
    except Exception as e:
        logger.debug(f'[effect_detect] vanilla ref for {target_file} unavailable: {e}')
        return None


def candidate_effects(dat_bytes, basename):
    """Every extra type that can read this DAT, tagged with whether its
    editable layers differ from vanilla. Sorted: differing first, then
    undecidable (no vanilla reference), then unchanged."""
    target, entries = match_target(basename)
    if not entries:
        return []

    vanilla = _vanilla_ref(target)
    vanilla_sigs = {}

    with tempfile.NamedTemporaryFile(suffix='.dat', delete=False) as tmp:
        tmp.write(dat_bytes)
        tmp_path = tmp.name
    try:
        found = []
        for owner, cfg in entries:
            sig = _signature(tmp_path, cfg)
            if sig is None:
                continue
            differs = None
            if sig[0] in ('image', 'afterimage', 'model'):
                # An image effect is by definition not vanilla; a model swap
                # cannot be judged here (left for the user to confirm).
                differs = True if sig[0] in ('image', 'afterimage') else None
            elif vanilla is not None:
                if cfg['id'] not in vanilla_sigs:
                    vanilla_sigs[cfg['id']] = _signature(vanilla, cfg)
                vsig = vanilla_sigs[cfg['id']]
                differs = (sig != vsig) if vsig is not None else None
            found.append({
                'character': owner,
                'extra_type': cfg['id'],
                'name': cfg.get('name', cfg['id']),
                'differs': differs,
            })
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    order = {True: 0, None: 1, False: 2}
    found.sort(key=lambda c: order[c['differs']])
    return found
