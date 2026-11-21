"""Shared integer-key Hermite reduction, extracted from the reviewed grab encoder.

Tolerance is scalar; full FK and packed geometry remain mandatory.
"""
import numpy as np
from .evaluation import Key


def hermite_matrix(us, h):
    return np.c_[(us ** 3 - 2 * us ** 2 + us) * h, (us ** 3 - us ** 2) * h]


def hermite_eval(v0, v1, d0, d1, us, h):
    return (2 * us ** 3 - 3 * us ** 2 + 1) * v0 + (-2 * us ** 3 + 3 * us ** 2) * v1 + hermite_matrix(us, h) @ np.array([d0, d1])


def fit_interval(times, values, i0, i1):
    """Independent Hermite slopes for dense samples between integer keys i0,i1 (dense indices)."""
    t0, t1 = times[i0], times[i1]; h = t1 - t0; inner = slice(i0 + 1, i1)
    us = (times[inner] - t0) / h; v0, v1 = values[i0], values[i1]
    if len(us) == 0:
        d = (v1 - v0) / h; return d, d, 0.
    base = (2 * us ** 3 - 3 * us ** 2 + 1) * v0 + (-2 * us ** 3 + 3 * us ** 2) * v1
    slopes = np.linalg.lstsq(hermite_matrix(us, h), values[inner] - base, rcond=None)[0]
    err = float(np.max(np.abs(hermite_eval(v0, v1, slopes[0], slopes[1], us, h) - values[inner])))
    return float(slopes[0]), float(slopes[1]), err


def reduce_track(times, values, ints, tol):
    """Bounded reduction: integer keys only, split where the Hermite fit exceeds tol."""
    if float(np.ptp(values)) <= tol:
        return [Key(0., float(np.mean(values)), 'linear', 0., 0.)]
    keep = {0, len(ints) - 1}; stack = [(0, len(ints) - 1)]
    while stack:
        lo, hi = stack.pop()
        if hi - lo < 2: continue
        i0, i1 = ints[lo], ints[hi]; d0, d1, err = fit_interval(times, values, i0, i1)
        if err > tol:
            seg = values[i0:i1 + 1]; fit = hermite_eval(values[i0], values[i1], d0, d1, (times[i0:i1 + 1] - times[i0]) / (times[i1] - times[i0]), times[i1] - times[i0])
            worst = times[i0 + int(np.argmax(np.abs(fit - seg)))]
            mid = min(range(lo + 1, hi), key=lambda i: abs(times[ints[i]] - worst))
            keep.add(mid); stack.extend([(lo, mid), (mid, hi)])
    kept = sorted(keep); keys = []
    for n, ki in enumerate(kept):
        i = ints[ki]; keys.append(Key(float(times[i]), float(values[i]), 'fixed', 0., 0.))
    for n in range(len(kept) - 1):
        i0, i1 = ints[kept[n]], ints[kept[n + 1]]; d0, d1, err = fit_interval(times, values, i0, i1)
        lin = np.abs(np.interp(times[i0:i1 + 1], [times[i0], times[i1]], [values[i0], values[i1]]) - values[i0:i1 + 1]).max() <= tol
        a, b = keys[n], keys[n + 1]
        keys[n] = Key(a.time, a.value, 'linear' if lin else 'fixed', a.in_slope, 0. if lin else d0)
        keys[n + 1] = Key(b.time, b.value, b.outgoing, 0. if lin else d1, b.out_slope)
    keys[-1] = Key(keys[-1].time, keys[-1].value, 'linear', keys[-1].in_slope, 0.)
    # FOBJ holds its last value; a trailing linear hold key is redundant.
    while len(keys) > 1 and keys[-2].outgoing == 'linear' and abs(keys[-2].value - keys[-1].value) < 1e-9:
        keys.pop()
    return keys

