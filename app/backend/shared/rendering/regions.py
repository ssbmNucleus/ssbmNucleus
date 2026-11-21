"""Connected regions of a 2D mask, their boxes, a box average and distances to a
region's edge, in numpy alone.

These replace the scipy.ndimage calls the backend made (label, find_objects,
uniform_filter, distance_transform_edt). scipy brought 82 compiled files into the
installer for them, and every unsigned compiled file is one Windows' Smart App
Control can refuse to load (bug report ee46f7d3, docs/dev/WINDOWS_SIGNING.md).
Results match scipy.ndimage: tests/backend/test_regions.py compares them while
scipy is still installed in a dev environment.
"""
import numpy as np


def label(mask, diagonal=False):
    """Number the connected True regions of a 2D mask, like `ndimage.label`.

    Pixels touch along edges, or also at corners with `diagonal` (scipy's
    `structure=np.ones((3, 3))`). Regions are numbered 1..count in the order a
    row-by-row scan first meets them. -> (labels as int32, count)"""
    mask = np.asarray(mask, bool)
    if mask.ndim != 2:
        raise ValueError('label needs a 2D mask')
    h, w = mask.shape
    labels = np.zeros((h, w), np.int32)
    if not mask.any():
        return labels, 0

    # Each row's runs of True: start column and end column (exclusive), in scan
    # order. In a row the changes alternate start, end, start, end...
    padded = np.zeros((h, w + 2), bool)
    padded[:, 1:-1] = mask
    change_row, change_col = np.nonzero(padded[:, 1:] != padded[:, :-1])
    run_row, run_start, run_end = change_row[0::2], change_col[0::2], change_col[1::2]
    n = len(run_row)

    # A run touches the runs in the row above whose columns overlap it (or meet it
    # at a corner, with `diagonal`). Row-major keys make one sorted search find,
    # for every run, the contiguous range of runs above it that it touches.
    stride = w + 3
    reach = 1 if diagonal else 0
    above = run_row - 1
    start_keys = run_row * stride + run_start
    end_keys = run_row * stride + run_end
    low = np.searchsorted(end_keys, above * stride + run_start - reach, side='right')
    high = np.searchsorted(start_keys, above * stride + run_end + reach, side='left')
    has = (high > low) & (run_row > 0)
    counts = np.where(has, high - low, 0)
    lower = np.repeat(np.arange(n), counts)
    upper = np.repeat(low, counts) + (np.arange(counts.sum()) - np.repeat(np.cumsum(counts) - counts, counts))

    # Join touching runs: hook each pair's roots onto the smaller one, then jump
    # every run straight to its root, until nothing changes.
    root = np.arange(n)
    if len(lower):
        while True:
            a, b = root[lower], root[upper]
            joined = root.copy()
            smaller = np.minimum(a, b)
            np.minimum.at(joined, a, smaller)
            np.minimum.at(joined, b, smaller)
            while True:
                jumped = joined[joined]
                if np.array_equal(jumped, joined):
                    break
                joined = jumped
            if np.array_equal(joined, root):
                break
            root = joined

    # Number regions by their first run in scan order. A root is its region's
    # smallest run index, which is that first run.
    roots = np.unique(root)
    number = np.zeros(n, np.int32)
    number[roots] = np.arange(1, len(roots) + 1, dtype=np.int32)
    run_label = number[root]

    lengths = run_end - run_start
    first = run_row * w + run_start
    offsets = np.cumsum(lengths) - lengths
    flat = np.repeat(first - offsets, lengths) + np.arange(int(lengths.sum()))
    labels.ravel()[flat] = np.repeat(run_label, lengths)
    return labels, len(roots)


def find_objects(labels):
    """Each label's bounding box, like `ndimage.find_objects`: a list whose item
    i is (row slice, column slice) for label i + 1, or None when that label is
    absent. Zero and negative labels are background."""
    labels = np.asarray(labels)
    if labels.ndim != 2:
        raise ValueError('find_objects needs a 2D label image')
    count = int(labels.max(initial=0))
    if count <= 0:
        return []
    h, w = labels.shape
    rows, cols = np.nonzero(labels > 0)
    values = labels[rows, cols].astype(np.intp)
    top = np.full(count + 1, h, np.intp)
    left = np.full(count + 1, w, np.intp)
    bottom = np.full(count + 1, -1, np.intp)
    right = np.full(count + 1, -1, np.intp)
    np.minimum.at(top, values, rows)
    np.minimum.at(left, values, cols)
    np.maximum.at(bottom, values, rows)
    np.maximum.at(right, values, cols)
    return [None if bottom[v] < 0 else (slice(int(top[v]), int(bottom[v]) + 1), slice(int(left[v]), int(right[v]) + 1))
            for v in range(1, count + 1)]


def box_count(mask, size):
    """How many True pixels the size x size window centred on each pixel holds,
    counting outside the image as False. It is `size * size` times
    `ndimage.uniform_filter(mask, size, mode='constant')`, in exact integers.
    -> int32 array"""
    mask = np.asarray(mask, bool)
    before, after = size // 2, size - 1 - size // 2
    total = np.pad(mask, ((before + 1, after), (before + 1, after))).cumsum(0, dtype=np.int32).cumsum(1, dtype=np.int32)
    return total[size:, size:] - total[:-size, size:] - total[size:, :-size] + total[:-size, :-size]


def distance_inside(mask):
    """Exact Euclidean distance from each True pixel to the nearest False pixel
    (0 on False pixels), like `ndimage.distance_transform_edt(mask)`.

    Felzenszwalb and Huttenlocher's two passes: down each column, then the lower
    envelope of parabolas along every row at once."""
    mask = np.asarray(mask, bool)
    if mask.ndim != 2:
        raise ValueError('distance_inside needs a 2D mask')
    h, w = mask.shape
    if not mask.any():
        return np.zeros((h, w))
    if mask.all():
        return np.full((h, w), np.inf)

    # Down each column: rows to the nearest False pixel in that column.
    row = np.arange(h)[:, None]
    gap = h + w + 1
    before = np.maximum.accumulate(np.where(mask, -gap, row), axis=0)
    after = np.minimum.accumulate(np.where(mask, h + gap, row)[::-1], axis=0)[::-1]
    column = np.minimum(row - before, after - row).astype(np.float64)
    f = np.minimum(column * column, float(gap * gap))  # a column with no False pixel never wins

    # Along each row: d2[y, x] = min over q of (x - q)^2 + f[y, q].
    every = np.arange(h)
    apex = np.zeros((h, w), np.intp)
    bound = np.full((h, w + 1), np.inf)
    bound[:, 0] = -np.inf
    k = np.zeros(h, np.intp)
    for q in range(1, w):
        fq = f[:, q] + q * q
        while True:
            v = apex[every, k]
            cross = (fq - (f[every, v] + v * v)) / (2.0 * (q - v))
            drop = cross <= bound[every, k]
            if not drop.any():
                break
            k[drop] -= 1
        k += 1
        apex[every, k] = q
        bound[every, k] = cross
        bound[every, k + 1] = np.inf
    squared = np.empty((h, w))
    k[:] = 0
    for x in range(w):
        while True:
            step = bound[every, k + 1] < x
            if not step.any():
                break
            k[step] += 1
        v = apex[every, k]
        squared[:, x] = (x - v) ** 2 + f[every, v]
    return np.sqrt(squared)


def nearest_known(unknown, radius):
    """For each True ("unknown") pixel, the nearest False pixel no further than
    `radius` (Euclidean). Of equally near ones, the first by row, then column
    offset. -> (reached, rows, cols): `reached` marks the unknown pixels that
    found one; `rows`/`cols` give that pixel's position (meaningful only where
    reached)."""
    unknown = np.asarray(unknown, bool)
    h, w = unknown.shape
    r = int(radius)
    offsets = sorted((dy * dy + dx * dx, dy, dx)
                     for dy in range(-r, r + 1) for dx in range(-r, r + 1)
                     if 0 < dy * dy + dx * dx <= radius * radius)
    known = np.pad(~unknown, r)
    rows = np.repeat(np.arange(h)[:, None], w, axis=1)
    cols = np.repeat(np.arange(w)[None, :], h, axis=0)
    reached = np.zeros((h, w), bool)
    for _, dy, dx in offsets:
        take = unknown & ~reached & known[r + dy:r + dy + h, r + dx:r + dx + w]
        rows[take] += dy
        cols[take] += dx
        reached |= take
    return reached, rows, cols
