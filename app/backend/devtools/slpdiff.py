"""slpdiff.py -- the netrig desync oracle's forensic half.

Both rig clients record the SAME netplay game; their .slp files contain each
client's own finalized simulation. If the simulations agreed, the replays are
frame-identical; the first differing frame is the desync point.

Usage:  python devtools/slpdiff.py <a.slp> <b.slp> [--fields pos,percent,state]
Exit codes: 0 = identical overlap, 2 = divergence found.
"""

import argparse
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from peppi_py import read_slippi


def series(game, port_idx):
    """Per-frame arrays for one port: (x, y, percent, state)."""
    p = game.frames.ports[port_idx].leader
    post = p.post
    return (post.position.x.to_pylist(), post.position.y.to_pylist(),
            post.percent.to_pylist(), post.state.to_pylist())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slp_a")
    ap.add_argument("slp_b")
    ap.add_argument("--tol", type=float, default=0.0001,
                    help="position/percent tolerance (floats should be exact)")
    args = ap.parse_args()

    ga = read_slippi(args.slp_a)
    gb = read_slippi(args.slp_b)
    fa = ga.frames.id.to_pylist()
    fb = gb.frames.id.to_pylist()
    # Rollback can FINALIZE a frame twice -> duplicate frame ids in one
    # replay, which naive row-indexing misreads as a one-row phase shift
    # (a false "divergence"). Keep the LAST write of each id.
    ia = {fid: idx for idx, fid in enumerate(fa)}
    ib = {fid: idx for idx, fid in enumerate(fb)}
    common = sorted(set(ia) & set(ib))
    print(f"a: {len(fa)} rows ({len(ia)} unique frames)   "
          f"b: {len(fb)} rows ({len(ib)} unique frames)   "
          f"common {len(common)} ({common[0]}..{common[-1]})")

    ports = range(len(ga.frames.ports))
    sa = {i: series(ga, i) for i in ports}
    sb = {i: series(gb, i) for i in ports}

    first_div = None
    for fid in common:
        f, g = ia[fid], ib[fid]
        for i in ports:
            xa, ya, ca, ta = (sa[i][0][f], sa[i][1][f], sa[i][2][f],
                              sa[i][3][f])
            xb, yb, cb, tb = (sb[i][0][g], sb[i][1][g], sb[i][2][g],
                              sb[i][3][g])
            if None in (xa, xb, ya, yb):
                continue
            if (abs(xa - xb) > args.tol or abs(ya - yb) > args.tol
                    or abs((ca or 0) - (cb or 0)) > args.tol or ta != tb):
                first_div = (fid, i)
                break
        if first_div:
            break

    if not first_div:
        print(f"IDENTICAL over the {len(common)}-frame overlap")
        sys.exit(0)

    fid, port = first_div
    f, g = ia[fid], ib[fid]
    print(f"DIVERGENCE at frame {fid} (port {port + 1}) -- "
          f"game time ~{max(0, fid) / 60.0:.2f}s")
    for i in ports:
        for name, k in (("x", 0), ("y", 1), ("%", 2), ("state", 3)):
            va, vb = sa[i][k][f], sb[i][k][g]
            mark = "  <-- differs" if va != vb else ""
            print(f"  P{i+1} {name:5} a={va} b={vb}{mark}")
    idx = common.index(fid)
    print("context (port %d x):" % (port + 1))
    for j in common[max(0, idx - 3):idx + 4]:
        print(f"  frame {j}: a={sa[port][0][ia[j]]} b={sb[port][0][ib[j]]}"
              + ("   <-- first divergence" if j == fid else ""))
    sys.exit(2)


if __name__ == "__main__":
    main()
