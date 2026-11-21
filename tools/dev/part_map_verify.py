"""Check a character's draft part labels on the actual model, in one image.

A label read off a texture sheet is a guess: a dark red blob could be the cap or
the mouth (on Mario it was the mouth), and the sheet cannot say. This paints
every authored group its own flat colour, renders the model from the front and
the back, and puts a legend beside it. Anything still showing its ORIGINAL
texture is unlabelled; anything in the wrong colour is mislabelled.

    app/venv/Scripts/python.exe tools/dev/part_map_verify.py --source PlFxNr
    app/venv/Scripts/python.exe tools/dev/part_map_verify.py --source PlFxNr --probe 19 25 31

--probe paints only the listed indices, each its own colour, to settle doubts.
Reads the DRAFT labels in part_map_labels/<source>.json, so this runs before
building.
Writes <out>/<code>/partmap.png.
"""
import argparse
import colorsys
import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

BACKEND = Path(__file__).resolve().parents[2] / 'app' / 'backend'
sys.path.insert(0, str(BACKEND))

from shared import mod_files  # noqa: E402
from randall.recolor import skin_lab, vanilla  # noqa: E402
from randall.recolor.skin_lab import _png  # noqa: E402
from core.constants import CHAR_PREFIXES  # noqa: E402

LABELS = Path(__file__).resolve().parents[1] / 'part_map_labels'
OUT = Path(__file__).resolve().parents[2] / 'app' / 'scratch' / 'part_map'
COLORS = [(230, 25, 75), (60, 180, 75), (255, 225, 25), (0, 130, 200), (245, 130, 48),
          (145, 30, 180), (70, 240, 240), (240, 50, 230), (210, 245, 60), (250, 190, 212),
          (0, 128, 128), (220, 190, 255), (170, 110, 40), (255, 250, 200), (128, 0, 0),
          (170, 255, 195), (128, 128, 0), (255, 215, 180), (0, 0, 128), (128, 128, 128)]


def frame(viewer, **camera):
    if camera:
        viewer.set_camera(**camera)
    source, _ = mod_files.resolve(skin_lab._file(viewer.grab_frame(), 'frame.png')['file_id'])
    return Image.open(io.BytesIO(source.read_bytes())).convert('RGB')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, help='vanilla costume code, e.g. PlFxNr')
    parser.add_argument('--probe', type=int, nargs='*', help='paint only these indices')
    parser.add_argument('--scale', type=float, default=0.8, help='camera zoom; lower pulls back')
    parser.add_argument('--pan-y', type=float, default=None,
                        help="camera aim height in the VIEWER's units (default: its own framing)")
    parser.add_argument('--pitch', type=float, default=None, help='camera tilt in degrees')
    parser.add_argument('--out', default=str(OUT))
    args = parser.parse_args()

    path = LABELS / f'{args.source}.json'
    entry = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None
    if args.probe:
        groups = {f'#{i}': [i] for i in args.probe}
    elif entry:
        groups = entry['groups']
    else:
        sys.exit(f'No {path.name} yet; use --probe.')
    character = (entry or {}).get('character') or next(
        (name for name, prefix in CHAR_PREFIXES.items() if args.source[2:-2] == prefix), None)
    if not character:
        sys.exit(f'Unknown costume code {args.source}.')
    color = args.source[-2:]
    args.character = character

    directory, code = vanilla._costume_dir(args.character, color)
    file = mod_files.register((directory / f'{code}.dat').read_bytes(), f'{code}.dat',
                              origin={'character': args.character, 'vanilla_color': color})
    session = skin_lab.skin_lab_open(file['file_id'])['session_id']
    try:
        item = skin_lab._sessions[session]
        viewer = item['viewer']
        live = {t['index'] for t in viewer.textures}
        chosen = {i for indices in groups.values() for i in indices if i in live}
        before = {i: viewer.get_full_texture(i) for i in sorted(chosen)}
        legend = []
        try:
            for n, (name, indices) in enumerate(groups.items()):
                # Past the fixed palette, spread extra groups round the hue wheel
                # so no two groups ever share a colour (Ganondorf has 21).
                paint = COLORS[n] if n < len(COLORS) else tuple(
                    int(v * 255) for v in colorsys.hsv_to_rgb((n * 0.618) % 1, 0.75, 0.95))
                legend.append((name, paint, [i for i in indices if i in live]))
                for index in indices:
                    if index not in live:
                        continue
                    with Image.open(io.BytesIO(before[index])) as image:
                        pixels = np.array(image.convert('RGBA'))
                    pixels[..., :3] = paint
                    viewer.update_texture(index, _png(pixels))
            # The default camera is portrait framing and crops tall fighters. An
            # automatic centre from model bounds was tried and is WRONG: the
            # camera's y is not a height in model units (it moved Marth the wrong
            # way), so framing is explicit. Pull back with --scale; move the aim
            # with --pan-y and tilt with --pitch until the feet are in frame.
            # The viewer REPORTS rotX/rotY but TAKES rot_x/rot_y.
            start = viewer.camera or {}
            heading = start.get('rotY', 0)
            aim = {'scale': args.scale}
            if args.pan_y is not None:
                aim['y'] = args.pan_y
            if args.pitch is not None:
                aim['rot_x'] = args.pitch
            front = frame(viewer, rot_y=heading, **aim)
            back = frame(viewer, rot_y=(heading + 180) % 360, **aim)
        finally:
            for index, raw in before.items():
                viewer.update_texture(index, raw)
    finally:
        skin_lab._close(session)

    unlabelled = sorted(live - chosen)
    width = front.width + back.width + 360
    sheet = Image.new('RGB', (width, max(front.height, 40 + 26 * (len(legend) + 2))), (24, 28, 34))
    sheet.paste(front, (0, 0))
    sheet.paste(back, (front.width, 0))
    draw = ImageDraw.Draw(sheet)
    x, y = front.width + back.width + 14, 14
    for name, paint, indices in legend:
        draw.rectangle([x, y, x + 18, y + 18], fill=paint)
        draw.text((x + 26, y + 3), f'{name}  {indices}', fill=(235, 235, 235))
        y += 26
    draw.text((x, y + 8), f'unlabelled: {unlabelled}', fill=(255, 120, 120))
    target = Path(args.out) / code
    target.mkdir(parents=True, exist_ok=True)
    name = 'probe_' + '_'.join(map(str, args.probe)) + '.png' if args.probe else 'partmap.png'
    sheet.save(target / name)
    print(f'{code}: {len(chosen)} labelled, unlabelled={unlabelled} -> {target / name}')


if __name__ == '__main__':
    main()
