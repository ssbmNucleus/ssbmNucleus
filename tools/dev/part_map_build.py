"""Resolve the authored part labels into every vanilla colour slot.

Labels are authored once per SOURCE costume, one file each in
part_map_labels/ (so several people or agents can label in parallel without
sharing a file). Characters whose accessory slots add textures -- Pikachu's
hats, Jigglypuff's bows -- get a label file per such slot. Labels cannot simply
be reused by index in the other
slots: for 18 of 27 characters every slot shares the layout, but Donkey Kong
and Yoshi REORDER their textures between slots, so the same index is a
different texture. Reusing indices there would name the wrong part with total
confidence.

So each slot is resolved by GEOMETRY. A recolour changes pixels, not which
triangles a texture covers, so (triangle count, bounds) identifies a texture
across slots even when its index and resolution move (Bowser's index 35 is
256x256 in one slot and 128x128 in the rest). A slot where any source texture
cannot be placed is left out entirely -- no entry is safer than a wrong one.

    app/venv/Scripts/python.exe tools/dev/part_map_build.py

Reads scratch/part_map/<code>/usage.json (from part_map_extract.py).
Writes backend/assets/vanilla_parts.json.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APP = REPO / 'app'
LABELS = REPO / 'tools' / 'part_map_labels'
EXTRACT = APP / 'scratch' / 'part_map'
OUT = APP / 'backend' / 'assets' / 'vanilla_parts.json'


# Two textures are "the same" across slots when they cover about the same
# triangles in about the same place. Exact equality is too strict: Captain
# Falcon's alternate suits move a bound by 0.08, Ness's alternates re-mesh a
# part (120 vs 126 triangles), and Link's Blue tunic unmaps a 14-triangle piece.
BOUNDS_TOLERANCE = 0.5
TRIANGLE_TOLERANCE = 0.25


def _close(a, b):
    ta, tb = a.get('mapped_triangles') or 0, b.get('mapped_triangles') or 0
    if not ta or not tb or not a.get('bounds') or not b.get('bounds'):
        return False
    if abs(ta - tb) > TRIANGLE_TOLERANCE * max(ta, tb):
        return False
    corners = lambda r: r['bounds']['min'] + r['bounds']['max']
    return max(abs(x - y) for x, y in zip(corners(a), corners(b))) <= BOUNDS_TOLERANCE


def _distance(a, b):
    corners = lambda r: r['bounds']['min'] + r['bounds']['max']
    return max(abs(x - y) for x, y in zip(corners(a), corners(b)))


def signature(rows):
    """Each texture's size, in index order: what a retexture of this slot keeps."""
    return ' '.join(f"{r['width']}x{r['height']}" for r in sorted(rows, key=lambda r: r['index']))


def _swapped(source_rows, slot_rows):
    """Same sizes at every index, yet some texture sits closer to ANOTHER index's
    geometry than to its own -- two same-sized textures traded places."""
    slot = {r['index']: r for r in slot_rows}
    for row in source_rows:
        own = slot.get(row['index'])
        if own is None or _close(row, own) or not row.get('bounds'):
            continue
        if any(_close(row, other) for i, other in slot.items()
               if i != row['index'] and (other['width'], other['height']) == (row['width'], row['height'])):
            return True
    return False


def resolve(source_rows, slot_rows):
    """{source index: slot index}, or None if any source texture is unplaceable."""
    if len(source_rows) == len(slot_rows) and signature(source_rows) == signature(slot_rows):
        if not _swapped(source_rows, slot_rows):
            return {r['index']: r['index'] for r in source_rows}
    # Reordered slots (DK, Yoshi): place every mapped texture by nearest geometry.
    mapping, used = {}, set()
    for row in sorted(source_rows, key=lambda r: -(r.get('mapped_triangles') or 0)):
        if not row.get('mapped_triangles') or not row.get('bounds'):
            continue
        near = [c for c in slot_rows if c['index'] not in used and _close(row, c)]
        if not near:
            return None
        best = min(near, key=lambda c: (_distance(row, c), c['index'] != row['index']))
        mapping[row['index']] = best['index']
        used.add(best['index'])
    # Unmapped textures carry no geometry; pair the leftovers in order, but only
    # when the counts agree -- otherwise there is nothing to anchor the guess.
    left_src = sorted(r['index'] for r in source_rows if r['index'] not in mapping)
    left_slot = sorted(r['index'] for r in slot_rows if r['index'] not in used)
    if len(left_src) != len(left_slot):
        return None
    mapping.update(zip(left_src, left_slot))
    return mapping


def main():
    sources = {}
    for path in sorted(LABELS.glob('*.json')):
        entry = json.loads(path.read_text(encoding='utf-8'))
        sources.setdefault(entry['character'], []).append(entry)
    usage = {}
    for directory in sorted(EXTRACT.iterdir()):
        path = directory / 'usage.json'
        if path.is_file():
            data = json.loads(path.read_text(encoding='utf-8'))
            usage[data['costume_code']] = data

    costumes, skipped = {}, []
    for character, entries in sorted(sources.items()):
        entries = [e for e in entries if e['source'] in usage]
        by_source = {e['source']: e for e in entries}
        slots = sorted(code for code, data in usage.items() if data['character'] == character)
        for code in slots:
            rows = usage[code]['textures']
            # A slot with its own labels uses them; any other slot borrows from
            # the first source whose geometry places every one of its textures.
            if code in by_source:
                entry, mapping = by_source[code], {r['index']: r['index'] for r in rows}
            else:
                entry, mapping = None, None
                for candidate in entries:
                    mapping = resolve(usage[candidate['source']]['textures'], rows)
                    if mapping is not None:
                        entry = candidate
                        break
            if entry is None:
                skipped.append(f'{code}: no label source resolves its layout')
                continue
            groups = {name: sorted(mapping[i] for i in indices if i in mapping)
                      for name, indices in entry['groups'].items()}
            # Textures that ALSO carry another part's colour next to their own
            # detail: authored ones (Mario's emblem holds the cap red around the
            # M), plus eye textures, which hold the face skin around the eye on
            # most fighters. Edits take only matching, edge-connected pixels.
            masked = {name: list(indices) for name, indices in (entry.get('masked') or {}).items()}
            if 'eyes' in entry['groups'] and 'skin' in entry['groups']:
                masked.setdefault('skin', [])
                masked['skin'] += [i for i in entry['groups']['eyes'] if i not in masked['skin']]
            masked = {name: sorted(mapping[i] for i in indices if i in mapping)
                      for name, indices in masked.items()}
            costumes[code] = {
                'character': character,
                'verified': bool(entry.get('verified')) and code == entry['source'],
                'inherited_from': None if code == entry['source'] else entry['source'],
                'signature': signature(rows),
                # Geometry per texture, so a costume whose textures were
                # upscaled or resized is still recognised (sizes alone are not
                # stable: an upscaled vanilla Falcon reports 256x256 where the
                # stock file has 128x128, and its parts went unnamed).
                # "triangles minx,miny,minz maxx,maxy,maxz" -- one short line per
                # texture, because an indented array per number turned a rebuild
                # of this file into a 64k-line diff.
                'geometry': {str(r['index']): ' '.join([str(r.get('mapped_triangles') or 0),
                                                        ','.join(str(v) for v in r['bounds']['min']),
                                                        ','.join(str(v) for v in r['bounds']['max'])])
                             for r in rows if r.get('mapped_triangles') and r.get('bounds')},
                'groups': {n: g for n, g in groups.items() if g},
                **({'masked': {n: m for n, m in masked.items() if m}} if any(masked.values()) else {}),
            }

    OUT.write_text(json.dumps({
        'version': 2,
        'note': 'BUILT by tools/dev/part_map_build.py from tools/part_map_labels/ -- do not edit. '
                'Per vanilla costume code: which live Skin Lab texture indices make up each named part. '
                'Contains no game data, only our names for index numbers.',
        'costumes': costumes}, indent=1) + '\n', encoding='utf-8')
    print(f'{len(costumes)} costumes written -> {OUT}')
    for line in skipped:
        print(f'  skipped {line}')


if __name__ == '__main__':
    sys.exit(main())
