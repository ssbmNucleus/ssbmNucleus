"""
make_cover.py -- generate a themed cover PNG for a modpack bundle.

    python make_cover.py <out.png> <title> <subtitle> <contents_json>

contents_json: [{"type": "...", "label": "..."}] (the modpack contents). Renders a
dark neon card with the title, subtitle, and a colour-coded list of the mods.
"""

import json
import sys

from PIL import Image, ImageDraw, ImageFont

WIN_FONTS = "C:/Windows/Fonts/"


def font(name, size):
    for cand in (WIN_FONTS + name, name):
        try:
            return ImageFont.truetype(cand, size)
        except Exception:
            continue
    return ImageFont.load_default()


TYPE_COLOR = {
    "costume": (255, 120, 120),
    "character": (120, 255, 160),
    "stage": (120, 180, 255),
    "das": (255, 200, 90),
    "effect": (255, 120, 255),
    "menu": (120, 255, 255),
}


def main():
    out = sys.argv[1]
    title = sys.argv[2] if len(sys.argv) > 2 else "MODPACK"
    subtitle = sys.argv[3] if len(sys.argv) > 3 else ""
    contents = json.loads(sys.argv[4]) if len(sys.argv) > 4 else []

    W, H = 760, 440
    img = Image.new("RGB", (W, H), (10, 10, 18))
    d = ImageDraw.Draw(img)

    # vertical gradient (deep indigo -> near-black) + a diagonal glow
    for y in range(H):
        t = y / H
        r = int(26 * (1 - t) + 6 * t)
        g = int(14 * (1 - t) + 8 * t)
        b = int(54 * (1 - t) + 16 * t)
        d.line([(0, y), (W, y)], fill=(r, g, b))
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W - 360, -180, W + 120, 300], fill=(70, 40, 140))
    img = Image.blend(img, Image.composite(glow, img, glow.convert("L").point(lambda v: v // 2)), 0.5)
    d = ImageDraw.Draw(img)

    # neon edge bars
    d.rectangle([0, 0, W, 7], fill=(140, 90, 255))
    d.rectangle([0, H - 7, W, H], fill=(40, 210, 255))

    f_title = font("arialbd.ttf", 52)
    f_sub = font("arial.ttf", 22)
    f_label = font("arialbd.ttf", 19)
    f_item = font("arial.ttf", 23)
    f_foot = font("arial.ttf", 16)

    d.text((44, 38), title, font=f_title, fill=(244, 244, 255))
    if subtitle:
        d.text((46, 100), subtitle, font=f_sub, fill=(158, 176, 226))

    y = 158
    for c in contents:
        col = TYPE_COLOR.get(c.get("type"), (200, 200, 200))
        d.ellipse([48, y + 6, 66, y + 24], fill=col)
        d.text((84, y + 3), c.get("type", "").upper(), font=f_label, fill=col)
        d.text((242, y), c.get("label", ""), font=f_item, fill=(228, 228, 238))
        y += 40

    d.text((44, H - 32), "SSBM Nucleus  ·  assembled & verified by the mod harness",
           font=f_foot, fill=(120, 130, 165))

    img.save(out, format="PNG")
    print(out)


if __name__ == "__main__":
    main()
