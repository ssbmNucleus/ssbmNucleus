"""A port's alternate costumes from Ultimate's own recolors.

Ultimate ships each fighter's costumes as folders c00..c07 of the same texture
names. A costume folder with the same names as c00 wears the same model in other
colours (Byleth: c00, c02, c04, c06; the odd ones are the other body). So:

  * the ported costume's textures are matched back to c00's colour textures by
    looking (the body importer resizes them, sometimes out of shape, so each
    source is resized to the costume texture's size and compared);
  * for another costume folder, every matched texture whose source differs from
    c00's is replaced by that folder's, resized the same way.

Only colour textures (`*_col`) are used; a texture the body import dropped (an
iris layer, say) cannot be recoloured this way.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

MATCH = 8.0        # mean colour difference (0..255) under which a costume texture is that source, resized
CLEAR = 3.0        # ... and the runner-up must be at least this many times worse
SMALL = 16         # textures this small are placeholders


def own_model(dump_root, fighter, folder, base='c00'):
    """True when a costume folder's model is not the first's (another mesh file on the disk under the same
    pictures' names: a game written out by its own reader, Slap City's other outfits). Ultimate's folders that share
    the pictures' names share the model."""
    root = Path(dump_root) / 'gamedata' / 'fighter' / fighter / 'model' / 'body'
    mine, first = root / folder / 'model.numshb', root / base / 'model.numshb'
    return mine.is_file() and first.is_file() and mine.read_bytes() != first.read_bytes()


def costume_folders(dump_root, fighter, base='c00'):
    """{folder: sorted colour texture names} for the costumes that use the texture names of `base`
    (c00's unless told: a fighter with a second body has its costumes under the next folder's names)."""
    pre = f'fighter/{fighter}/model/body/c'
    names = {}
    listing = Path(dump_root) / 'Hashes_FullPath'
    if listing.is_file():
        with open(listing, encoding='utf-8', errors='replace') as f:
            for line in f:
                p = line.strip()
                if p.startswith(pre) and p.endswith('_col.nutexb'):
                    folder, name = p[len(pre) - 1:].split('/', 1)
                    names.setdefault(folder, set()).add(name[:-len('.nutexb')])
    else:
        # a game written out in Ultimate's shapes by its own reader (source_game): its folders are on the disk
        for path in sorted((Path(dump_root) / 'gamedata' / pre).parent.glob('c*/*_col.nutexb')):
            names.setdefault(path.parent.name, set()).add(path.stem)
    if base not in names:
        raise ValueError(f'{fighter}: no {base} costume in the path list')
    return {c: sorted(n) for c, n in sorted(names.items()) if n == names[base]}


def sources(dump_root, fighter, folder, names):
    """{name: RGBA image} of a costume folder's colour textures, extracted from the archive when not yet on disk."""
    from echo_ultimate import nutexb
    from echo_ultimate.gamedata import arc
    root = Path(dump_root)
    rel = [f'fighter/{fighter}/model/body/{folder}/{n}.nutexb' for n in names]
    missing = [r for r in rel if not (root / 'gamedata' / r).exists()]
    if missing:
        arc.extract(root, root / 'gamedata', missing)
    return {n: nutexb.read(root / 'gamedata' / r)[0] for n, r in zip(names, rel)}


def _rgb(image, size=None):
    from PIL import Image
    image = image.convert('RGB')
    return np.asarray(image if size is None or image.size == size else image.resize(size, Image.LANCZOS), float)


def match(texture_files, base):
    """Which source each costume texture is: {index: name}. `texture_files` are the
    model tool's `tex_<index>.png` exports; `base` is c00's {name: image}."""
    from PIL import Image
    out = {}
    for path in texture_files:
        image = Image.open(path)
        if min(image.size) <= SMALL:
            continue
        mine = _rgb(image)
        if mine.max() - mine.min() < 4:
            continue                                    # one flat colour: could be anything
        scores = sorted((float(np.abs(mine - _rgb(src, image.size)).mean()), name) for name, src in base.items())
        if scores[0][0] <= MATCH and (len(scores) == 1 or scores[1][0] >= CLEAR * max(scores[0][0], 1.0)):
            out[int(re.search(r'(\d+)', path.stem)[1])] = scores[0][1]
    return out


def changed(base, other):
    """Names whose image in `other` is not c00's."""
    return [n for n in base if n in other and (other[n].size != base[n].size
            or np.abs(np.asarray(other[n], int) - np.asarray(base[n], int)).max() > 2)]


def recolor(run, costume: Path, node: str, textures: dict, base, other, out: Path, work: Path):
    """Write `out`: `costume` with each matched texture that differs in `other` replaced.
    `run(args, output)` runs the model tool; `textures` is {index: (source name, (w, h))}.
    -> names replaced"""
    from PIL import Image
    work.mkdir(parents=True, exist_ok=True)
    differs, current, done = set(changed(base, other)), costume, []
    for index, (name, size) in sorted(textures.items()):
        if name not in differs:
            continue
        png = work / f'{out.stem}-{index}.png'
        other[name].resize(size, Image.LANCZOS).save(png)
        step = work / f'{out.stem}-step-{index}.dat'
        run(['--texture', 'import', current, node, index, png, step], step)
        current = step
        done.append(name)
    out.write_bytes(Path(current).read_bytes())
    return sorted(set(done))


def tone(images, names):
    """Mean colour of the saturated pixels of the named textures: what the costume "is", to pick team colours by."""
    total, count = np.zeros(3), 0
    for n in names:
        a = np.asarray(images[n].convert('RGB'), float).reshape(-1, 3)
        strong = a[(a.max(1) - a.min(1)) > 40]
        total += strong.sum(0)
        count += len(strong)
    return [round(float(v), 1) for v in (total / count if count else total)]


def tone_of_changes(costumes, which, names, least=24):
    """Mean colour, in costume `which`, of the saturated pixels that are not the same in every costume: what the
    costume "is" when its pictures also hold what never changes (skin and hair on one sheet with the clothes).
    `costumes`: {costume: {name: image}}."""
    total, count = np.zeros(3), 0
    for n in names:
        mine = _rgb(costumes[which][n])
        differs = np.zeros(mine.shape[:2], bool)
        for k, other in costumes.items():
            if k != which and n in other and other[n].size == costumes[which][n].size:
                differs |= np.abs(_rgb(other[n]) - mine).max(2) > least
        a = mine[differs]
        strong = a[(a.max(1) - a.min(1)) > 40] if len(a) else a
        total += strong.sum(0) if len(strong) else 0
        count += len(strong)
    return [round(float(v), 1) for v in (total / count if count else total)]


TEAM_HUES = {'red': 0.0, 'green': 120.0, 'blue': 230.0}


def team_shares(costumes, which, names, least=24, within=40.0):
    """How much of what changes from costume to costume is, in costume `which`, each team's colour: the share of
    those pixels (the coloured ones) whose hue is within `within` degrees of the team's. -> {'red', 'green', 'blue'}"""
    hits, count = {t: 0 for t in TEAM_HUES}, 0
    for n in names:
        mine = _rgb(costumes[which][n])
        differs = np.zeros(mine.shape[:2], bool)
        for k, other in costumes.items():
            if k != which and n in other and other[n].size == costumes[which][n].size:
                differs |= np.abs(_rgb(other[n]) - mine).max(2) > least
        a = mine[differs]
        if not len(a):
            continue
        count += len(a)
        high, low = a.max(1), a.min(1)
        spread = np.where(high - low == 0, 1.0, high - low)
        r, g, b = a[:, 0], a[:, 1], a[:, 2]
        hue = np.where(high == r, (g - b) / spread % 6, np.where(high == g, (b - r) / spread + 2, (r - g) / spread + 4)) * 60.0
        coloured = (high - low) > 40
        for team, want in TEAM_HUES.items():
            hits[team] += int((coloured & (np.abs((hue - want + 180.0) % 360.0 - 180.0) < within)).sum())
    return {t: round(v / count, 3) if count else 0.0 for t, v in hits.items()}
