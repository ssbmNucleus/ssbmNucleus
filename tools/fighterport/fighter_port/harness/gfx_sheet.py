"""Contact sheets of the effect catalogue: both pictures of each number side by side, one fixed crop for all."""
import sys, glob, re
from PIL import Image, ImageDraw
import numpy as np
folder, out, first, last, cols = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
files = {}
for f in glob.glob(folder + '/*.png'):
    m = re.search(r'-(\d+)([ab])\.png$', f)
    if m:
        files[(int(m[1]), m[2])] = f
# where things are: everything that differs from the plain background in any picture, above the HUD
box = None
ims = {}
for key, f in files.items():
    im = Image.open(f).convert('RGB')
    ims[key] = im
    a = np.asarray(im).astype(int)
    d = np.abs(a - 64).sum(2) > 40
    d[int(im.height * 0.70):] = False
    d[:40] = False
    ys, xs = np.where(d)
    if len(xs):
        b = (xs.min(), ys.min(), xs.max(), ys.max())
        box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
x0, y0, x1, y1 = box
x0, y0, x1, y1 = max(0, x0 - 10), max(0, y0 - 10), x1 + 10, y1 + 10
w, h = x1 - x0, y1 - y0
scale = 300 / w
tw, th = 300, int(h * scale)
numbers = [n for n in range(first, last + 1) if (n, 'a') in ims]
rows = -(-len(numbers) // cols)
sheet = Image.new('RGB', (cols * (2 * tw + 8), rows * (th + 4)), (20, 20, 20))
d = ImageDraw.Draw(sheet)
for i, n in enumerate(numbers):
    for j, s in enumerate('ab'):
        if (n, s) in ims:
            t = ims[(n, s)].crop((x0, y0, x1, y1)).resize((tw, th))
            sheet.paste(t, ((i % cols) * (2 * tw + 8) + j * tw, (i // cols) * (th + 4)))
    d.text(((i % cols) * (2 * tw + 8) + 4, (i // cols) * (th + 4) + 2), str(n), fill=(255, 255, 0))
sheet.save(out)
print(out, sheet.size, 'crop', (x0, y0, x1, y1))
