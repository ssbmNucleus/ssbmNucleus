#!/usr/bin/env python3
"""Turn raw captures into the guide's images: crop, then draw red rings/boxes/arrows.

capture.mjs writes `img/_raw/<id>.png` plus `img/<id>.json` describing what to
highlight (element boxes measured from the live DOM). This script produces
`img/<id>.png`, which is what the Markdown references. Annotations therefore
move with the UI instead of being hand-drawn, and re-running is idempotent.

Sidecar format:
  {
    "viewport": {"w": 1600, "h": 900, "dpr": 1},
    "marks": [
      {"kind": "ring",  "box": {"x":..,"y":..,"w":..,"h":..}, "pad": 10},
      {"kind": "box",   "box": {...}, "pad": 8},
      {"kind": "arrow", "from": [x,y], "to": [x,y]}
    ],
    "crop": {"x":..,"y":..,"w":..,"h":..}      # optional, CSS px
  }

Usage (from the repo root):  app\\venv\\Scripts\\python docs\\guide\\scripts\\annotate.py [img-dir]
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

RED = (232, 44, 44, 255)
WIDTH = 5


def ring(draw: ImageDraw.ImageDraw, box: dict, pad: float, scale: float) -> None:
    x, y, w, h = (box[k] * scale for k in ("x", "y", "w", "h"))
    pad *= scale
    bx0, by0 = x - pad - w * 0.08, y - pad - h * 0.18
    bx1, by1 = x + w + pad + w * 0.08, y + h + pad + h * 0.18
    for i in range(WIDTH):
        draw.ellipse([bx0 + i, by0 + i, bx1 - i, by1 - i], outline=RED)


def rect(draw: ImageDraw.ImageDraw, box: dict, pad: float, scale: float) -> None:
    x, y, w, h = (box[k] * scale for k in ("x", "y", "w", "h"))
    pad *= scale
    draw.rounded_rectangle([x - pad, y - pad, x + w + pad, y + h + pad], radius=8, outline=RED, width=WIDTH)


def arrow(draw: ImageDraw.ImageDraw, a: list, b: list, scale: float) -> None:
    (x0, y0), (x1, y1) = ((v * scale for v in a), (v * scale for v in b))
    draw.line([x0, y0, x1, y1], fill=RED, width=WIDTH)
    ang = math.atan2(y1 - y0, x1 - x0)
    size = 18 * scale
    left = (x1 - size * math.cos(ang - 0.45), y1 - size * math.sin(ang - 0.45))
    right = (x1 - size * math.cos(ang + 0.45), y1 - size * math.sin(ang + 0.45))
    draw.polygon([(x1, y1), left, right], fill=RED)


def annotate(img_dir: Path) -> int:
    raw_dir = img_dir / "_raw"
    done = 0
    for sidecar in sorted(img_dir.glob("*.json")):
        raw = raw_dir / (sidecar.stem + ".png")
        if not raw.exists():
            print(f"[annotate] no raw capture for {sidecar.stem}", file=sys.stderr)
            continue
        spec = json.loads(sidecar.read_text(encoding="utf-8"))
        im = Image.open(raw).convert("RGBA")
        vp = spec.get("viewport") or {}
        scale = im.width / vp["w"] if vp.get("w") else 1.0  # CSS px -> image px
        ox = oy = 0.0
        crop_spec = spec.get("crop")
        if isinstance(crop_spec, dict) and all(k in crop_spec for k in ("x", "y", "w", "h")):
            c = crop_spec
            left, top = int(round(c["x"] * scale)), int(round(c["y"] * scale))
            right, bottom = int(round((c["x"] + c["w"]) * scale)), int(round((c["y"] + c["h"]) * scale))
            im = im.crop((left, top, min(right, im.width), min(bottom, im.height)))
            ox, oy = c["x"], c["y"]
        # blur (pixelate) marks first so rings can sit on top of them
        for m in spec.get("marks", []):
            if m.get("kind") != "blur":
                continue
            b = m["box"]
            x0, y0 = int((b["x"] - ox) * scale), int((b["y"] - oy) * scale)
            x1, y1 = int((b["x"] - ox + b["w"]) * scale), int((b["y"] - oy + b["h"]) * scale)
            x0, y0, x1, y1 = max(0, x0), max(0, y0), min(im.width, x1), min(im.height, y1)
            if x1 - x0 < 2 or y1 - y0 < 2:
                continue
            region = im.crop((x0, y0, x1, y1))
            small = region.resize((max(1, (x1 - x0) // 12), max(1, (y1 - y0) // 12)), Image.BILINEAR)
            im.paste(small.resize(region.size, Image.NEAREST), (x0, y0))
        draw = ImageDraw.Draw(im)
        for m in spec.get("marks", []):
            kind = m.get("kind", "ring")
            if kind in ("ring", "box"):
                box = dict(m["box"]); box["x"] -= ox; box["y"] -= oy
                (ring if kind == "ring" else rect)(draw, box, m.get("pad", 10), scale)
            elif kind == "arrow":
                arrow(draw, [m["from"][0] - ox, m["from"][1] - oy], [m["to"][0] - ox, m["to"][1] - oy], scale)
        out = img_dir / (sidecar.stem + ".png")
        for attempt in range(4):
            # Windows occasionally refuses the open with EINVAL while a scanner
            # (or the previous write) still holds the file; a short retry clears it.
            try:
                im.convert("RGB").save(out, optimize=True)
                break
            except OSError:
                if attempt == 3:
                    raise
                import time
                time.sleep(0.6)
        done += 1
    print(f"[annotate] {done} image(s) written to {img_dir}")
    return done


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "img"
    annotate(target)
