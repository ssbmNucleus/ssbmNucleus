"""Pull the facts a vanilla part map needs, through Randall's own Skin Lab path.

The labels are authored once, offline, by a strong model looking at the sheets
this produces (tools/part_map_labels/, which part_map_build.py turns into
app/backend/assets/vanilla_parts.json). This half only gathers evidence, and it
deliberately goes through `skin_lab_open` + `texture_usage` rather than reading
the DAT directly: the map is keyed by LIVE SKIN LAB INDEX, and a map keyed in
any other index space is worse than no map at all.

    app/venv/Scripts/python.exe tools/dev/part_map_extract.py --character Mario
    app/venv/Scripts/python.exe tools/dev/part_map_extract.py --all

Writes <out>/<code>/usage.json and <out>/<code>/sheet_N.png.
"""
import argparse

import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / 'app' / 'backend'
sys.path.insert(0, str(BACKEND))

from shared import mod_files  # noqa: E402
from randall.recolor import skin_lab, texture_inspection, vanilla  # noqa: E402
from core.constants import VANILLA_CSS_COLOR_ORDER  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / 'app' / 'scratch' / 'part_map'

# Geometry the labeller should not have to re-derive from the sheet.
KEEP = ('index', 'width', 'height', 'format', 'geometry_texture_index',
        'mapped_triangles', 'animation_variants', 'bounds', 'needs_material_upscale')


def costume(character, color, out_dir):
    directory, code = vanilla._costume_dir(character, color)
    data = (directory / f'{code}.dat').read_bytes()
    file = mod_files.register(data, f'{code}.dat', origin={'character': character})
    opened = skin_lab.skin_lab_open(file['file_id'])
    session = opened['session_id']
    try:
        item = skin_lab._sessions[session]
        viewer = item['viewer']
        usage = texture_inspection.texture_usage(viewer)
        rows = [{k: row[k] for k in KEEP if k in row} for row in usage['textures']]
        target = out_dir / code
        target.mkdir(parents=True, exist_ok=True)
        pages = 0
        while True:
            try:
                sheet = texture_inspection.texture_sheet(viewer, pages)
            except ValueError:
                break
            # texture_sheet hands back a REGISTERED file, not raw bytes.
            source, _ = mod_files.resolve(sheet['files'][0]['file_id'])
            (target / f'sheet_{pages}.png').write_bytes(source.read_bytes())
            pages += 1
            if pages > 12:
                break
        (target / 'usage.json').write_text(json.dumps(
            {'character': character, 'color': color, 'costume_code': code,
             'textures': rows, 'sheets': pages}, indent=1), encoding='utf-8')
        return code, len(rows), pages
    finally:
        # Skin Lab has no public close; _close is what its expiry timer and its
        # atexit hook use, under the same lock.
        with skin_lab._lock:
            skin_lab._close(session)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--character')
    parser.add_argument('--color')
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--out', default=str(OUT))
    args = parser.parse_args()

    out_dir = Path(args.out)
    targets = []
    if args.all:
        for name in VANILLA_CSS_COLOR_ORDER:
            targets += [(name, c) for c in vanilla.available_colors(name)]
    elif args.character:
        colors = [args.color] if args.color else vanilla.available_colors(args.character)
        targets = [(args.character, c) for c in colors]
    else:
        parser.error('--character or --all')

    print(f'{len(targets)} costumes -> {out_dir}')
    for character, color in targets:
        tick = time.monotonic()
        try:
            code, textures, sheets = costume(character, color, out_dir)
            print(f'  {code:10s} {textures:4d} textures  {sheets} sheets  {time.monotonic() - tick:5.1f}s')
        except Exception as exc:  # noqa: BLE001 - one costume must not sink the run
            print(f'  {character}/{color}: FAILED {type(exc).__name__}: {exc}')


if __name__ == '__main__':
    main()
