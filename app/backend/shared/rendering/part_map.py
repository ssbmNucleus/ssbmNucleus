"""Named parts of a vanilla costume, looked up instead of rediscovered.

Randall used to learn "which texture is the overalls" from scratch every
session: texture_usage, a texture sheet, then highlight after highlight. In a
measured Aztec-Mario turn that exploration was ~26s of model thinking for 0.4s
of tool work, and the answer is the same every time, because a vanilla costume
is the same file for everybody.

So the answer is authored once (tools/part_map_labels.json), resolved into
every colour slot's own index space by tools/dev/part_map_build.py, and handed
over at `skin_lab_open` before the model has to ask anything.

Every match is checked against the costume's SIGNATURE -- each texture's size in
index order -- never just its texture count. Donkey Kong and Yoshi reorder their
textures between colour slots, so "same character, same count" would put a real
name on the wrong texture:

  * by ORIGIN -- open_vanilla_file records the costume code it copied; if the
    live layout matches that code's signature, it IS that costume;
  * by SIGNATURE -- a costume whose layout matches some vanilla slot of its
    character is almost always a retexture of it, so the names are offered as a
    `likely` hypothesis the model is told to confirm with one highlight.

Anything else -- a restructured mod, an unlabelled character -- gets None, and
with it today's behaviour.
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from core import config

# config.BACKEND_ASSETS_DIR, not __file__-relative: a frozen build bundles
# backend/assets at _MEIPASS/backend/assets while this module's __file__ sits at
# _MEIPASS/skinlab, so the relative guess missed and every costume read as
# "no part map" in the installed app.
DATA = Path(config.BACKEND_ASSETS_DIR) / 'vanilla_parts.json'
_cache = None


def _load():
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(DATA.read_text(encoding='utf-8')).get('costumes') or {}
        except (OSError, ValueError) as exc:
            logger.warning('[part_map] unreadable %s: %s', DATA, exc)
            _cache = {}
    return _cache


def reset():
    """Test hook: re-read the data file."""
    global _cache
    _cache = None


MATCH_TRIANGLES = .25      # same tolerances part_map_build uses across colour slots
MATCH_BOUNDS = .5
MATCH_SHARE = .8           # at least this share of the labelled textures must place


def _by_geometry(costumes, geometry, code, character):
    """(entry, {stored index: live index}) for the costume whose labelled
    textures all sit on the same geometry as this one, else (None, None)."""
    candidates = [costumes[code]] if code in costumes else []
    candidates += [e for name, e in costumes.items()
                   if name != code and character and e['character'] == character]
    live = [{'index': int(i), 'mapped_triangles': (row or {}).get('mapped_triangles') or 0,
             'bounds': (row or {}).get('bounds')} for i, row in geometry.items()]
    live = [row for row in live if row['mapped_triangles'] and row['bounds']]
    for entry in candidates:
        stored = [row for row in (_stored_row(i, value)
                                  for i, value in (entry.get('geometry') or {}).items()) if row]
        labelled = {i for indices in (*entry['groups'].values(),
                                      *(entry.get('masked') or {}).values()) for i in indices}
        if not stored or not labelled:
            continue
        mapping, used = {}, set()
        for row in sorted(stored, key=lambda r: -r['mapped_triangles']):
            near = [c for c in live if c['index'] not in used and _close(row, c)]
            if not near:
                continue
            best = min(near, key=lambda c: (_distance(row, c), c['index'] != row['index']))
            mapping[row['index']] = best['index']
            used.add(best['index'])
        placed = [i for i in labelled if i in mapping]
        if len(placed) >= MATCH_SHARE * len(labelled):
            return entry, mapping
    return None, None


def _stored_row(index, value):
    """One stored geometry line: "triangles minx,miny,minz maxx,maxy,maxz"."""
    try:
        triangles, low, high = str(value).split(' ')
        return {'index': int(index), 'mapped_triangles': int(triangles),
                'bounds': {'min': [float(v) for v in low.split(',')],
                           'max': [float(v) for v in high.split(',')]}}
    except (TypeError, ValueError):
        return None


def _corners(row):
    return list(row['bounds']['min']) + list(row['bounds']['max'])


def _close(a, b):
    if abs(a['mapped_triangles'] - b['mapped_triangles']) > MATCH_TRIANGLES * max(
            a['mapped_triangles'], b['mapped_triangles']):
        return False
    return _distance(a, b) <= MATCH_BOUNDS


def _distance(a, b):
    return max(abs(x - y) for x, y in zip(_corners(a), _corners(b)))


def signature(textures):
    """Must match part_map_build.signature: each texture's size, in index order."""
    return ' '.join(f"{t['width']}x{t['height']}" for t in sorted(textures, key=lambda t: t['index']))


def describe(textures, origin=None, geometry=None):
    """Named parts for this costume, or None when nothing is known about it.

    `textures` is the live texture list. `origin` is the registered file's
    origin dict (character, and costume_code for a vanilla copy). `geometry`,
    when given, is {index: {'mapped_triangles': n, 'bounds': {...}}} from
    texture_usage, which recognises a costume whose textures were resized.
    """
    origin = origin or {}
    costumes = _load()
    live = signature(textures)
    code = origin.get('costume_code')
    entry, exact, mapping = None, False, None
    if code in costumes and costumes[code]['signature'] == live:
        entry, exact = costumes[code], True
    elif origin.get('character'):
        entry = next((e for e in costumes.values()
                      if e['character'] == origin['character'] and e['signature'] == live), None)
    if entry is None and geometry:
        # Sizes change when a costume is upscaled or a texture is replaced;
        # which triangles a texture covers does not. A user's upscaled Falcon
        # matched no signature, so a lava recolour was aimed by eye and put
        # lava on the gauntlets while calling them arms.
        entry, mapping = _by_geometry(costumes, geometry, code, origin.get('character'))
    if entry is None:
        return None
    known = {t['index'] for t in textures}
    if mapping is not None:
        groups = {name: sorted({mapping[i] for i in indices if i in mapping})
                  for name, indices in entry['groups'].items()}
    else:
        groups = {name: [i for i in indices if i in known] for name, indices in entry['groups'].items()}
    groups = {name: indices for name, indices in groups.items() if indices}
    if not groups:
        return None
    character = entry['character']
    masked_source = (entry.get('masked') or {})
    if mapping is not None:
        masked = {name: sorted({mapping[i] for i in indices if i in mapping})
                  for name, indices in masked_source.items()}
    else:
        masked = {name: [i for i in indices if i in known] for name, indices in masked_source.items()}
    masked = {name: indices for name, indices in masked.items() if indices}
    # Labelling all 25 fighters found the same trap on most of them: detail is
    # painted into a neighbour's texture (eyes carry the face skin around them,
    # Mario's emblem carries the cap red around the M).
    shared = ('A part\'s textures can carry neighbouring detail -- "eyes" usually include '
              'the surrounding face skin. analyze_palette with parts splits those colours, '
              'so recolour only the groups you mean. masked_parts lists textures that ALSO '
              'carry a part\'s colour beside other detail; analyze_palette with parts adds '
              'those pixels automatically -- do not list them in parts yourself. For '
              'skin_material, include them in that part\'s '
              'preview with a colour mask for the part\'s colour and mask.surrounding=true, '
              'which leaves detail inside it (the M on the emblem, the iris) untouched.')
    # A verified vanilla label file leaves out hidden low-poly/alternate models
    # and faint secondary blend layers. A lava-Bowser run painted two hidden
    # ones, saw no change, decided the render was stale and spent 20 rounds
    # (17 cents) re-checking. Renders are live (measured: the next frame).
    named = {i for indices in (*groups.values(), *masked.values()) for i in indices}
    unlisted = sorted(known - named) if exact else []
    if unlisted:
        shared += (' unlisted textures are hidden models, highlight/blend layers or viewer-only artifacts, never '
                   'where a visible colour lives: do not edit them to fix a part. If a visible area '
                   'did not change, it belongs to a listed part -- renders are always current, never stale.')
    return {
        'parts': groups,
        **({'masked_parts': masked} if masked else {}),
        **({'unlisted': unlisted} if unlisted else {}),
        'source': 'vanilla' if exact else 'likely',
        'note': ('Named parts of this vanilla costume, by live texture index. Use them '
                 'directly as texture_indices; there is no need to explore the model to '
                 'find a part that is listed here. ' if exact else
                 'This costume has the same texture layout as vanilla '
                 f'{character}, so these names are a starting guess. Confirm the part '
                 'you are about to edit with ONE highlight before editing it. ') + shared,
    }
