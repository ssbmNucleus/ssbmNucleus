"""
HUD word-banner and digit-glyph filename rules.

Shared by the percent-font importer (vault/menus/percent.py) and the
unified import classifier (vault/importing/unified/detection.py) so a
loose pack of "ready.png / go.png / game.png" or "0.png … 9.png" is
recognized the same way whether it is dropped on the Import button or
handed to the percent installer directly. Also holds the vanilla IfAll slot
grouping (which manifest slots show which glyph or word), shared by the
percent editor and the first-run glyph previews (shared/vanilla_extract/menu_refs.py).
Pure: no Flask, no IO.
"""
import re
from pathlib import Path

# READY / GO! / GAME! word banners (ScInfCnt material slots in vanilla IfAll).
WORD_KEYS = ['ready', 'go', 'game', 'time', 'sudden', 'death',
             'success', 'failure', 'complete']

# Words identifiable by texture dimensions alone -- lets Dolphin-hash-named
# packs (tex1_<w>x<h>_<hash>.png) map without semantic filenames. Sudden and
# Death share 448x124 and are excluded.
UNIQUE_WORD_DIMS = {
    (280, 84): 'ready',
    (376, 188): 'go',
    (528, 144): 'game',
    (528, 164): 'time',
    (532, 172): 'success',
    (464, 136): 'failure',
    (536, 184): 'complete',
}


def word_key_for_name(name):
    """Match an image filename to a word key: semantic stems with optional
    trailing digits ('ready3.png', 'go21.png'), or Dolphin-hash names
    (tex1_<w>x<h>_<hash>.png) whose dimensions identify the word."""
    stem = Path(name).stem.lower().strip()
    m = re.match(r'^tex1_(\d+)x(\d+)_', stem)
    if m:
        return UNIQUE_WORD_DIMS.get((int(m.group(1)), int(m.group(2))))
    base = re.sub(r'[\s_\-]*\d+$', '', stem).rstrip('!').strip()
    return base if base in WORD_KEYS else None


def digit_key_for_name(name):
    """'0' … '9' for a digit-glyph filename ('7.png', '0zero.png'), else None.
    A leading digit followed by another digit ('10.png', '2024.png') is not
    a glyph name."""
    stem = Path(name).stem.lower().strip()
    if stem and stem[0].isdigit() and (len(stem) == 1 or not stem[1].isdigit()):
        return stem[0]
    return None


# Digit / percent / HP glyph keys of the percent font (DmgNum slots).
GLYPH_KEYS = [str(d) for d in range(10)] + ['percent', 'hp']

# READY/GO!/GAME! word banners: ScInfCnt mat slot ordinals in vanilla IfAll
# (identified visually; "Time!" is stored three times, hash-identical).
WORD_MAT_ORDINALS = {
    'time': [0, 1, 2],
    'death': [3],
    'sudden': [4],
    'success': [8],
    'ready': [13],
    'go': [14],
    'game': [15],
    'failure': [16],
    'complete': [17],
}


def with_ordinals(entries):
    """Tag each entry with its ordinal position within its (root, kind) group —
    the region-independent slot key."""
    counters = {}
    out = []
    for e in entries:
        key = (e['root'], e['kind'])
        ordinal = counters.get(key, 0)
        counters[key] = ordinal + 1
        out.append({**e, 'ordinal': ordinal})
    return out


def glyph_slots(vanilla_entries):
    """Map glyph key ('0'..'9', 'percent', 'hp') → list of vanilla DmgNum
    slot entries (with ordinals) whose pixels show that glyph. Derived from
    the manifest itself: bank 1 frames 0-9 are digits 0-9 in order, and the
    32x24 frames alternate % / HP; mat slots are matched by md5."""
    entries = with_ordinals(vanilla_entries)
    dn = [e for e in entries if e['root'] == 'DmgNum_scene_models']
    anim36 = [e for e in dn if e['kind'] == 'anim' and e['height'] == 36]
    anim24 = [e for e in dn if e['kind'] == 'anim' and e['height'] == 24]
    if len(anim36) < 10 or len(anim24) < 2:
        return {}

    md5_to_glyph = {anim36[i]['md5']: str(i) for i in range(10)}
    md5_to_glyph.setdefault(anim24[0]['md5'], 'percent')
    md5_to_glyph.setdefault(anim24[1]['md5'], 'hp')

    groups = {}
    for e in dn:
        glyph = md5_to_glyph.get(e['md5'])
        if glyph:
            groups.setdefault(glyph, []).append(e)
    return groups


def word_slots(vanilla_entries):
    """Map word key ('ready', 'go', 'game', ...) → list of vanilla ScInfCnt
    slot entries (with ordinals). md5 expansion catches buffer-aliased
    duplicates (vanilla stores "Time!" three times as one shared buffer —
    a partial replace would leave stale copies on screen)."""
    entries = with_ordinals(vanilla_entries)
    mats = [e for e in entries
            if e['root'] == 'ScInfCnt_scene_models' and e['kind'] == 'mat']
    by_ordinal = {e['ordinal']: e for e in mats}

    groups = {}
    for word, ordinals in WORD_MAT_ORDINALS.items():
        md5s = {by_ordinal[o]['md5'] for o in ordinals if o in by_ordinal}
        group = [e for e in mats
                 if e['ordinal'] in ordinals or e['md5'] in md5s]
        if group:
            groups[word] = group
    return groups


def group_slots(vanilla_entries):
    """All editable slot groups: digit/percent glyphs + word banners."""
    groups = glyph_slots(vanilla_entries)
    groups.update(word_slots(vanilla_entries))
    return groups
