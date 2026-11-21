"""C1-continuous integer-key Hermite reduction, with slope breaks only where earned.

Why this exists. `scalar_curves.reduce_track` fits each interval's two Hermite
slopes INDEPENDENTLY (`fit_interval` least-squares over 2 free slopes), so the
incoming and outgoing slope at a knot almost never agree. FigaCodec then has to
emit a slope-only opcode (HSD_A_OP_SLP) at that knot to express the break.
Measured on the shipped banks, that is where the size went:

    bank              keys/track   SLP share   bytes/key
    vanilla Popo            7.04       21.4%        4.15
    ours squirtle          14.04       44.3%        3.78
    vanilla Bowser          6.68       22.1%        3.95
    ours charizard         24.68       46.4%        3.77

Bytes per key are already at Nintendo parity, so the only lever is key count,
and ~45% of our keys are slope breaks Nintendo does not emit.

This module solves ONE slope per knot, shared by both adjacent intervals, by
least squares over every dense sample at once. C1 by construction, so the codec
emits no SLP. A C1 fit is less expressive than a broken one, so where an
interval genuinely cannot hold tolerance under a shared slope -- a real slope
discontinuity, e.g. a pose hold released into a swing -- that one interval is
refitted with independent slopes and pays for its own break. Everything else
stays continuous.

`reduce_track_c1` is a drop-in for `reduce_track`: same (times, values, ints,
tol) signature, same `Key` list out, same integer-key constraint.
"""
import numpy as np
from fighter_port.evaluation import Key


def _slope_basis(us, h):
    """Hermite tangent basis for samples at parameter `us` across an interval of width h."""
    return (us ** 3 - 2 * us ** 2 + us) * h, (us ** 3 - us ** 2) * h


def _value_base(v0, v1, us):
    return (2 * us ** 3 - 3 * us ** 2 + 1) * v0 + (-2 * us ** 3 + 3 * us ** 2) * v1


def _solve_slopes_dense(times, values, knots):
    """One slope per knot, least squares over every interior dense sample at once.

    `knots` are dense-sample indices, strictly increasing. C1 by construction:
    interval n and interval n+1 share the slope variable at knot n+1.
    """
    k = len(knots)
    blocks, targets = [], []
    for n in range(k - 1):
        i0, i1 = knots[n], knots[n + 1]
        h = times[i1] - times[i0]
        inner = slice(i0 + 1, i1)
        us = (times[inner] - times[i0]) / h
        if not len(us):
            continue
        b0, b1 = _slope_basis(us, h)
        block = np.zeros((len(us), k))
        block[:, n] = b0
        block[:, n + 1] = b1
        blocks.append(block)
        targets.append(values[inner] - _value_base(values[i0], values[i1], us))
    if not blocks:
        d = np.zeros(k)
        for n in range(k - 1):
            i0, i1 = knots[n], knots[n + 1]
            secant = (values[i1] - values[i0]) / (times[i1] - times[i0])
            d[n] = d[n + 1] = secant
        return d
    a = np.vstack(blocks)
    return np.linalg.lstsq(a, np.concatenate(targets), rcond=None)[0]


def _eval_interval(times, values, i0, i1, d0, d1):
    """Max |fit - sample| over the closed interval, and the dense index of the worst."""
    h = times[i1] - times[i0]
    seg = slice(i0, i1 + 1)
    us = (times[seg] - times[i0]) / h
    b0, b1 = _slope_basis(us, h)
    fit = _value_base(values[i0], values[i1], us) + b0 * d0 + b1 * d1
    diff = np.abs(fit - values[seg])
    j = int(np.argmax(diff))
    return float(diff[j]), i0 + j


def _fit_interval_free(times, values, i0, i1):
    """Independent slopes for one interval -- the incumbent reducer's per-interval fit."""
    h = times[i1] - times[i0]
    inner = slice(i0 + 1, i1)
    us = (times[inner] - times[i0]) / h
    if not len(us):
        d = (values[i1] - values[i0]) / h
        return d, d
    b0, b1 = _slope_basis(us, h)
    a = np.column_stack([b0, b1])
    d0, d1 = np.linalg.lstsq(a, values[inner] - _value_base(values[i0], values[i1], us), rcond=None)[0]
    return float(d0), float(d1)


def reduce_track_c1(times, values, ints, tol, *, allow_breaks=True, linear_tail=False,
                    max_iterations=None):
    """Integer-key Hermite reduction with one shared slope per key.

    times/values are the dense samples; `ints` are the dense indices that are
    legal key positions (packed FOBJ delta times are integers); `tol` is the
    per-sample bound the fit must hold.

    Refines by splitting the worst over-tolerance interval that can still be
    split, then -- if `allow_breaks` -- lets intervals that still miss tolerance
    take independent slopes, so a genuine slope discontinuity pays for one SLP
    instead of every knot in the track paying for one.
    """
    if float(np.ptp(values)) <= tol:
        return [Key(0., float(np.mean(values)), 'linear', 0., 0.)]
    limit = max_iterations or len(ints)
    keep = {0, len(ints) - 1}
    for _ in range(limit):
        order = sorted(keep)
        knots = [ints[i] for i in order]
        slopes = solve_slopes(times, values, knots)
        candidates = []
        for n in range(len(knots) - 1):
            if order[n + 1] - order[n] < 2:
                continue  # already adjacent on the integer grid; cannot subdivide
            err, dense = _eval_interval(times, values, knots[n], knots[n + 1], slopes[n], slopes[n + 1])
            if err > tol:
                candidates.append((err, dense, n))
        if not candidates:
            break
        err, dense, n = max(candidates)
        lo, hi = order[n], order[n + 1]
        mid = min(range(lo + 1, hi), key=lambda i: abs(times[ints[i]] - times[dense]))
        keep.add(mid)          # strictly between two adjacent kept knots, so always new
        if len(keep) >= len(ints):
            break

    order = sorted(keep)
    knots = [ints[i] for i in order]
    slopes = solve_slopes(times, values, knots)
    incoming = list(map(float, slopes))
    outgoing = list(map(float, slopes))
    breaks = 0
    if allow_breaks:
        for n in range(len(knots) - 1):
            err, _ = _eval_interval(times, values, knots[n], knots[n + 1], outgoing[n], incoming[n + 1])
            if err <= tol:
                continue
            d0, d1 = _fit_interval_free(times, values, knots[n], knots[n + 1])
            free_err, _ = _eval_interval(times, values, knots[n], knots[n + 1], d0, d1)
            if free_err < err:
                outgoing[n], incoming[n + 1] = d0, d1
                breaks += 1

    keys = [Key(float(times[i]), float(values[i]), 'fixed', incoming[n], outgoing[n])
            for n, i in enumerate(knots)]
    # A 'linear' tail makes FigaCodec inject one incoming-slope opcode per track
    # (its `lin && prev=="fixed"` rule), i.e. one extra key on every channel in
    # the bank. FOBJ holds its last value past the end regardless, so the tail
    # is left cubic unless a caller asks otherwise.
    if linear_tail:
        keys[-1] = Key(keys[-1].time, keys[-1].value, 'linear', keys[-1].in_slope, 0.)
        while len(keys) > 1 and keys[-2].outgoing == 'linear' and abs(keys[-2].value - keys[-1].value) < 1e-9:
            keys.pop()
    reduce_track_c1.last_breaks = breaks
    return keys


def solve_slopes(times, values, knots):
    """Same least-squares fit using tridiagonal normal equations where nonsingular."""
    from scipy.linalg import solveh_banded
    n=len(knots);diagonal=np.zeros(n);off=np.zeros(n-1);rhs=np.zeros(n)
    for k,(lo,hi) in enumerate(zip(knots,knots[1:])):
        h=times[hi]-times[lo];u=(times[lo+1:hi]-times[lo])/h
        a,b=_slope_basis(u,h)
        y=values[lo+1:hi]-_value_base(values[lo],values[hi],u)
        diagonal[k]+=a@a;diagonal[k+1]+=b@b;off[k]=a@b;rhs[k]+=a@y;rhs[k+1]+=b@y
    if np.any(diagonal==0):return _solve_slopes_dense(times,values,knots)
    band=np.zeros((2,n));band[0]=diagonal;band[1,:-1]=off
    try:return solveh_banded(band,rhs,lower=True,check_finite=False)
    except np.linalg.LinAlgError:return _solve_slopes_dense(times,values,knots)
