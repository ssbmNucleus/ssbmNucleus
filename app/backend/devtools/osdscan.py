"""Scan a netrig framedump for the yellow in-game "Desync Risk" OSD.

Slippi's checksum-mismatch warning renders BOTTOM-RIGHT in yellow and is
invisible to host logs (game-side draw) -- the film is the only record.
Verified against the 2026-08-26 16:42 ICs run, where the OSD window aligned
with a real 2-frame sim divergence (slpdiff frame 2176).

Usage: python devtools/osdscan.py <dump.avi> [--step 1] [--thresh 60]
Exit code 1 if any OSD window found (usable as a verdict gate).
"""
import argparse
import io
import subprocess
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def frame_at(path, t):
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(t), "-i", path,
         "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
        capture_output=True)
    return p.stdout or None


def yellow_count(png_bytes):
    from PIL import Image
    im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    w, h = im.size
    crop = im.crop((int(w * 0.60), int(h * 0.85), w, h))
    px = crop.load()
    n = 0
    for y in range(0, crop.size[1], 2):
        for x in range(0, crop.size[0], 2):
            r, g, b = px[x, y]
            # OSD glyph yellow; FoD's gold stars live mid-frame, outside
            # this crop, but keep the green channel high to reject grass.
            if r > 200 and g > 160 and b < 100:
                n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("avi")
    ap.add_argument("--step", type=float, default=1.0)
    ap.add_argument("--thresh", type=int, default=60)
    args = ap.parse_args()
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", args.avi], capture_output=True,
        text=True).stdout.strip() or 0)
    windows, cur = [], None
    t = 0.0
    while t < dur:
        png = frame_at(args.avi, t)
        n = yellow_count(png) if png else 0
        if n >= args.thresh:
            if cur is None:
                cur = [t, t, n]
            else:
                cur[1], cur[2] = t, max(cur[2], n)
        elif cur is not None:
            windows.append(tuple(cur))
            cur = None
        t += args.step
    if cur is not None:
        windows.append(tuple(cur))
    for a, b, peak in windows:
        print(f"OSD window {a:.0f}s..{b:.0f}s (peak {peak} px)")
    if not windows:
        print("no Desync Risk OSD found")
    sys.exit(1 if windows else 0)


if __name__ == "__main__":
    main()
