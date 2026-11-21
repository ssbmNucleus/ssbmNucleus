"""
palette.py -- server-side port of the Skin Creator's color palette tool
(frontend/src/vault/editors/colorUtils.js), vectorized with numpy.

Same semantics as the UI: pool every texture's opaque, non-gray, mid-lightness
pixels into 1-degree hue bins, merge adjacent bins (gap <= 25 degrees) into
color groups, fit to the requested group count (merge closest / split widest),
then apply per-group hue/saturation shifts back onto the ORIGINAL pixels.
Lightness is never touched, so shading survives recolors.
"""

import numpy as np

HUE_TOLERANCE = 25
MIN_GROUP_PIXELS = 100
# A pixel this faintly tinted (below the 15% hue floor) still belongs to the
# hued group that DOMINATES its texture when its hue falls in that group's
# range. Marth's tunic averages 20% saturation: 3,358 of its pixels sat at
# 3-15%, were left out, and stayed grey when the fabric was recoloured --
# the white blotches. Only textures a group covers at least half of claim
# them, so a whole-costume analysis never pulls near-white gloves into blue
# overalls.
FAINT_SATURATION = 3
DOMINANT_SHARE = 0.5


# --------------------------------------------------------------------------- #
# vectorized HSL <-> RGB (matches the JS math: h in [0,360), s/l in [0,100])   #
# --------------------------------------------------------------------------- #
def rgb_to_hsl(rgb):
    """rgb: float array (..., 3) in 0..255 -> (h, s, l) arrays."""
    r, g, b = rgb[..., 0] / 255.0, rgb[..., 1] / 255.0, rgb[..., 2] / 255.0
    cmax = np.maximum(np.maximum(r, g), b)
    cmin = np.minimum(np.minimum(r, g), b)
    l = (cmax + cmin) / 2.0
    d = cmax - cmin
    with np.errstate(divide='ignore', invalid='ignore'):
        s = np.where(d == 0, 0.0,
                     np.where(l > 0.5, d / (2.0 - cmax - cmin), d / (cmax + cmin)))
        h_r = ((g - b) / d + np.where(g < b, 6.0, 0.0)) / 6.0
        h_g = ((b - r) / d + 2.0) / 6.0
        h_b = ((r - g) / d + 4.0) / 6.0
    # JS switch picks the FIRST channel equal to max: r, then g, then b
    h = np.select([d == 0, cmax == r, cmax == g], [0.0, h_r, h_g], default=h_b)
    h = np.nan_to_num(h, nan=0.0)
    s = np.nan_to_num(s, nan=0.0)
    return h * 360.0, s * 100.0, l * 100.0


def hsl_to_rgb(h, s, l):
    """h in degrees, s/l in 0..100 -> uint8 array (..., 3)."""
    h = (h % 360.0) / 360.0
    s = np.clip(s, 0, 100) / 100.0
    l = np.clip(l, 0, 100) / 100.0

    def hue2rgb(p, q, t):
        t = np.mod(t, 1.0)
        return np.select(
            [t < 1 / 6, t < 1 / 2, t < 2 / 3],
            [p + (q - p) * 6 * t, q, p + (q - p) * (2 / 3 - t) * 6],
            default=p)

    q = np.where(l < 0.5, l * (1 + s), l + s - l * s)
    p = 2 * l - q
    r = np.where(s == 0, l, hue2rgb(p, q, h + 1 / 3))
    g = np.where(s == 0, l, hue2rgb(p, q, h))
    b = np.where(s == 0, l, hue2rgb(p, q, h - 1 / 3))
    return np.stack([np.round(r * 255), np.round(g * 255), np.round(b * 255)],
                    axis=-1).astype(np.uint8)


def _valid_mask(rgba):
    """The pixels the palette tool considers: opaque enough, not near
    black/white, not gray."""
    h, s, l = rgb_to_hsl(rgba[..., :3].astype(np.float64))
    mask = (rgba[..., 3] >= 128) & (l >= 10) & (l <= 90) & (s >= 15)
    return mask, h, s, l


# --------------------------------------------------------------------------- #
# analysis                                                                     #
# --------------------------------------------------------------------------- #
def analyze(textures, max_groups=8, pad=True):
    """textures: {index: HxWx4 uint8 array}. Returns (groups, pixel_maps):
    groups is a list of dicts (ordered by pixel count), pixel_maps maps each
    texture index to a flat uint8 array (255 = unassigned)."""
    bins_count = np.zeros(360, dtype=np.int64)
    bins_s = np.zeros(360, dtype=np.float64)
    bins_l = np.zeros(360, dtype=np.float64)

    faint = {}
    per_tex = {}
    for idx, rgba in textures.items():
        mask, h, s, l = _valid_mask(rgba)
        per_tex[idx] = (mask, h)
        opaque = (rgba[..., 3] >= 128).ravel()
        faint[idx] = (opaque, opaque & ~mask.ravel() & (s.ravel() >= FAINT_SATURATION)
                      & (l.ravel() >= 10) & (l.ravel() <= 90))
        hv = np.floor(h[mask]).astype(np.int64) % 360
        bins_count += np.bincount(hv, minlength=360)
        bins_s += np.bincount(hv, weights=s[mask], minlength=360)
        bins_l += np.bincount(hv, weights=l[mask], minlength=360)

    # merge adjacent occupied bins (gap <= tolerance) into raw groups
    raw = []
    current = None
    for hdeg in range(360):
        if bins_count[hdeg] > 0:
            if current is None:
                current = {'start': hdeg, 'end': hdeg, 'count': int(bins_count[hdeg]),
                           'total_s': float(bins_s[hdeg]), 'total_l': float(bins_l[hdeg])}
            elif hdeg - current['end'] <= HUE_TOLERANCE:
                current['end'] = hdeg
                current['count'] += int(bins_count[hdeg])
                current['total_s'] += float(bins_s[hdeg])
                current['total_l'] += float(bins_l[hdeg])
            else:
                if current['count'] >= MIN_GROUP_PIXELS:
                    raw.append(current)
                current = {'start': hdeg, 'end': hdeg, 'count': int(bins_count[hdeg]),
                           'total_s': float(bins_s[hdeg]), 'total_l': float(bins_l[hdeg])}
    if current and current['count'] >= MIN_GROUP_PIXELS:
        raw.append(current)

    # red wraps around 0/360
    if len(raw) >= 2:
        first, last = raw[0], raw[-1]
        if first['start'] < HUE_TOLERANCE and last['end'] > 360 - HUE_TOLERANCE:
            first['start'] = last['start'] - 360
            first['count'] += last['count']
            first['total_s'] += last['total_s']
            first['total_l'] += last['total_l']
            raw.pop()

    # merge closest pairs down to max_groups
    while len(raw) > max_groups:
        min_dist, mi, mj = float('inf'), 0, 1
        for i in range(len(raw)):
            for j in range(i + 1, len(raw)):
                h1 = ((raw[i]['start'] + raw[i]['end']) / 2 + 360) % 360
                h2 = ((raw[j]['start'] + raw[j]['end']) / 2 + 360) % 360
                dist = abs(h1 - h2)
                if dist > 180:
                    dist = 360 - dist
                if dist < min_dist:
                    min_dist, mi, mj = dist, i, j
        gi, gj = raw[mi], raw[mj]
        gi['start'] = min(gi['start'], gj['start'])
        gi['end'] = max(gi['end'], gj['end'])
        gi['count'] += gj['count']
        gi['total_s'] += gj['total_s']
        gi['total_l'] += gj['total_l']
        raw.pop(mj)

    # split widest groups up to max_groups. This is for the Skin Creator's
    # sliders, which want max_groups handles; the halves carry equal, invented
    # pixel counts, so callers that reason about groups pass pad=False.
    while pad and 0 < len(raw) < max_groups:
        widest = max(range(len(raw)), key=lambda i: raw[i]['end'] - raw[i]['start'])
        g = raw[widest]
        if g['end'] - g['start'] < 2:
            break
        mid = (g['start'] + g['end']) // 2
        g1 = {'start': g['start'], 'end': mid, 'count': g['count'] // 2,
              'total_s': g['total_s'] / 2, 'total_l': g['total_l'] / 2}
        g2 = {'start': mid + 1, 'end': g['end'], 'count': g['count'] - g['count'] // 2,
              'total_s': g['total_s'] / 2, 'total_l': g['total_l'] / 2}
        raw[widest:widest + 1] = [g1, g2]

    raw.sort(key=lambda g: -g['count'])

    groups = []
    for i, g in enumerate(raw):
        avg_s = g['total_s'] / g['count'] if g['count'] else 0
        avg_l = g['total_l'] / g['count'] if g['count'] else 0
        center = ((g['start'] + g['end']) / 2 + 360) % 360
        rgb = hsl_to_rgb(np.array([center]), np.array([avg_s]), np.array([avg_l]))[0]
        groups.append({
            'index': i,
            'centerHue': round(center, 1),
            'hueRange': [(g['start'] + 360) % 360, g['end'] % 360],
            'pixelCount': int(g['count']),
            'avgSaturation': round(avg_s, 1),
            'avgLightness': round(avg_l, 1),
            'displayColor': '#%02x%02x%02x' % tuple(int(v) for v in rgb),
        })

    # per-texture pixel -> group map (first matching group wins, like the UI)
    def in_range_of(g, flat_h):
        lo, hi = g['hueRange']
        if lo <= hi:
            return (flat_h >= lo - HUE_TOLERANCE) & (flat_h <= hi + HUE_TOLERANCE)
        return (flat_h >= lo - HUE_TOLERANCE) | (flat_h <= hi + HUE_TOLERANCE)  # wraps 0

    pixel_maps = {}
    for idx, (mask, h) in per_tex.items():
        flat_mask = mask.ravel()
        flat_h = h.ravel()
        gmap = np.full(flat_mask.shape, 255, dtype=np.uint8)
        unassigned = flat_mask.copy()
        for gi, g in enumerate(groups):
            sel = unassigned & in_range_of(g, flat_h)
            gmap[sel] = gi
            unassigned &= ~sel
        opaque, faintly = faint[idx]
        counts = np.bincount(gmap[gmap != 255], minlength=len(groups)) if groups else np.zeros(0, int)
        if len(counts) and opaque.any():
            dominant = int(counts.argmax())
            if counts[dominant] >= DOMINANT_SHARE * opaque.sum():
                claimed = faintly & in_range_of(groups[dominant], flat_h)
                gmap[claimed] = dominant
                groups[dominant]['pixelCount'] += int(claimed.sum())
        pixel_maps[idx] = gmap

    return groups, pixel_maps


NEUTRAL_MIN_PIXELS = 16


SURROUNDING_SHARE = 0.25


def surrounding(mask, share=SURROUNDING_SHARE):
    """The large surrounding field of a selection, without the islands in it.

    Mario's emblem texture paints the cap red AROUND the logo and a red M inside
    the white disc, in one hue. The texture holds half the emblem and is
    mirrored on the model, so the M touches the texture edge at the mirror seam:
    "touches the border" cannot tell them apart. Size can -- the field is 4,833
    px and reaches all four edges, the M is 793. Keep the largest region, plus
    any other border-touching region at least `share` of its size."""
    from shared.rendering.regions import label
    labels, count = label(mask)
    if not count:
        return mask
    sizes = np.bincount(labels.ravel())[1:]
    largest = sizes.max()
    border = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))) - {0}
    keep = [i + 1 for i, size in enumerate(sizes)
            if size == largest or (i + 1 in border and size >= share * largest)]
    return np.isin(labels, keep)


def _claim_extras(extras, groups, maps):
    """Add another texture's pixels to a part: those in one of the part's own
    hue groups AND in that colour's surrounding field (not an enclosed logo or
    iris). Pixels already claimed by the texture's own part are left alone."""
    hued = [g for g in groups if g.get('kind') != 'neutral']
    for index, rgba in extras.items():
        valid, h, _, _ = _valid_mask(rgba)
        flat_h = h.ravel()
        current = maps.get(index)
        if current is None:
            current = np.full(flat_h.shape, 255, dtype=np.uint8)
        claimed = np.zeros(flat_h.shape, dtype=bool)
        chosen = np.full(flat_h.shape, 255, dtype=np.int32)
        for g in hued:
            lo, hi = g['hueRange']
            inside = ((flat_h >= lo - HUE_TOLERANCE) & (flat_h <= hi + HUE_TOLERANCE) if lo <= hi
                      else (flat_h >= lo - HUE_TOLERANCE) | (flat_h <= hi + HUE_TOLERANCE))
            take = inside & valid.ravel() & ~claimed
            chosen[take] = g['index']
            claimed |= take
        keep = surrounding(claimed.reshape(rgba.shape[:2])).ravel() & (current == 255)
        if keep.any():
            current = current.copy()
            current[keep] = chosen[keep]
            maps[index] = current


def _add_neutral_group(textures, groups, maps):
    """Give a part's white, grey and black pixels a group of their own.

    Hue clustering skips them (no hue to measure), so a near-white shirt came
    back with ZERO groups and could not be recolored at all -- a measured run
    fell back to generating a solid-black swatch instead, for ten minutes. Hue
    shifts still cannot move these pixels; set_hue/set_saturation with
    lightness_scale colorizes them (white -> black is saturation 0 with a low
    lightness_scale)."""
    opaque = {i: (rgba[..., 3] >= 128).ravel() for i, rgba in textures.items()}
    loose = {i: opaque[i] & (maps[i] == 255) for i in textures}
    count = int(sum(m.sum() for m in loose.values()))
    if count < NEUTRAL_MIN_PIXELS:
        return
    index = len(groups)
    lightness = []
    for i, rgba in textures.items():
        if loose[i].any():
            _, _, l = rgb_to_hsl(rgba.reshape(-1, 4)[loose[i], :3].astype(np.float64))
            lightness.append(l)
            maps[i] = maps[i].copy()
            maps[i][loose[i]] = index
    avg_l = float(np.concatenate(lightness).mean())
    grey = int(round(avg_l * 2.55))
    groups.append({'index': index, 'kind': 'neutral', 'centerHue': None, 'hueRange': None,
                   'pixelCount': count, 'avgSaturation': 0.0, 'avgLightness': round(avg_l, 1),
                   'displayColor': '#%02x%02x%02x' % (grey, grey, grey),
                   'note': 'white/grey/black pixels: only set_hue/set_saturation (+ lightness_scale) change them'})


def analyze_parts(parts, max_groups=8, extras=None):
    """Cluster each named part on its own, as ONE analysis.

    parts: {name: {index: HxWx4 uint8}} with disjoint texture indices. Returns
    (groups, pixel_maps) in the same shape as `analyze`, except every group is
    tagged with its `part` and group indices run across all parts.

    Clustering the whole costume at once merges any two parts that share a hue
    (Mario's cap and shirt are the same red), so they could never be recolored
    differently; the model's only way round that was one analysis per part, and
    since a session holds one analysis at a time, one analyze-then-recolor round
    trip per part. Clustering per part keeps them apart while still returning a
    single analysis, so a single recolor can move every part in one call.
    """
    groups, pixel_maps, seen = [], {}, set()
    extras = extras or {}
    for name, textures in parts.items():
        overlap = seen & set(textures)
        if overlap:
            raise ValueError(f'Texture {min(overlap)} is in more than one part.')
        seen.update(textures)
        # No padding: a single-color part is one group, not max_groups equal
        # slices of it that a model would then have to deliberate over.
        part_groups, part_maps = analyze(textures, max_groups, pad=False)
        _add_neutral_group(textures, part_groups, part_maps)
        offset = len(groups)
        if offset + len(part_groups) >= 255:   # 255 marks "unassigned" in a map
            raise ValueError('Too many color groups; analyze fewer parts or ask for fewer groups.')
        for group in part_groups:
            groups.append({**group, 'index': group['index'] + offset, 'part': name})
        for index, gmap in part_maps.items():
            pixel_maps[index] = np.where(gmap == 255, 255, gmap.astype(np.int32) + offset).astype(np.uint8)
        # A texture named as a part of its own keeps it; only the rest are
        # borrowed, through this part's (already offset) hue groups.
        borrowed = {i: rgba for i, rgba in extras.get(name, {}).items()
                    if not any(i in t for t in parts.values())}
        _claim_extras(borrowed, [g for g in groups if g['part'] == name], pixel_maps)
    return groups, pixel_maps


SET_MODES = ('set', 'set_hue', 'set_saturation')     # a value that sets something changes even at 0


def apply_adjustments(original_rgba, pixel_map, adjustments):
    """Apply per-group adjustments to a texture's ORIGINAL pixels.

    A group's value is either ``(hue_shift, sat_shift)`` -- rotate the hue the
    pixels already have -- or ``(hue, saturation, 'set')`` to colorize them
    outright; ``'set_hue'`` sets the hue and shifts the saturation the pixels have,
    ``'set_saturation'`` shifts the hue and sets the saturation. An optional fourth
    element scales original lightness (default 1), retaining relative shading while
    allowing pale colors to become dark.

    Rotation cannot touch whites or greys: they have no hue to rotate, so a
    shift of any size leaves them white. Setting is the only way to take, say,
    a white jacket to olive drab. Returns a new HxWx4 uint8 array, or None if
    nothing changed.
    """
    active = {gi: value for gi, value in adjustments.items()
              if (len(value) > 2 and value[2] in SET_MODES) or value[0] or value[1]
              or (len(value) > 3 and value[3] != 1)}
    if not active:
        return None
    out = original_rgba.copy()
    flat = out.reshape(-1, 4)
    changed = False
    for gi, value in active.items():
        sel = pixel_map == gi
        if not sel.any():
            continue
        changed = True
        px = flat[sel]
        h, s, l = rgb_to_hsl(px[:, :3].astype(np.float64))
        mode = value[2] if len(value) > 2 else 'shift'
        h = (np.full(h.shape, float(value[0]) % 360.0) if mode in ('set', 'set_hue')
             else (h + value[0]) % 360.0)
        s = (np.full(s.shape, float(np.clip(value[1], 0, 100))) if mode in ('set', 'set_saturation')
             else np.clip(s + value[1], 0, 100))
        if len(value) > 3:
            new_l = np.clip(l * value[3], 0, 100)
            if mode not in ('set', 'set_saturation'):
                # HSL saturation is relative to lightness: Link's pale blue-grey
                # chainmail (L~85) kept S when darkened to L~47 and came out
                # neon cyan -- three times the colour, from "darker and grimier".
                # Scaling lightness must never ADD colour, so cap the chroma at
                # what the pixel had. An explicit set_saturation is left as asked.
                room_old = 1 - np.abs(2 * l / 100 - 1)
                room_new = 1 - np.abs(2 * new_l / 100 - 1)
                ratio = np.divide(room_old, room_new, out=np.ones_like(room_old), where=room_new > 1e-6)
                s = np.clip(s * np.minimum(1.0, ratio), 0, 100)
            l = new_l
        px[:, :3] = hsl_to_rgb(h, s, l)
        flat[sel] = px
    return out if changed else None
