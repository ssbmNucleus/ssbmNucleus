"""Humanoid landmarks of a Melee fighter skeleton, found from rest GEOMETRY.

Why not just read the bone names? Because they lie. Marth's rig kit calls his
left ELBOW `LHandN` and his left WRIST `L1stNa` -- only 51 of his 90 JOBJs carry
a name at all, and the named ones drift off the joints they describe once the
arms start. Names also differ per fighter, and imported/custom characters have
none worth trusting. Rest positions never lie: the two lowest leaves are feet,
the joint that fans out into fingers is a wrist, the branch that owns both arms
is the chest.

    from fighter_port.rigmap import Rig
    rig = Rig(Path("Marth.joints.json"))
    rig.landmarks["l_knee"]     # -> "JOBJ_7"

Landmarks are named for the body part, NOT for the JOBJ that fills them, so
every consumer (the retargeter, selftest's per-joint table) speaks anatomy.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

LANDMARKS = ["pelvis", "spine", "chest", "neck", "head",
             "l_collar", "l_shoulder", "l_elbow", "l_wrist",
             "r_collar", "r_shoulder", "r_elbow", "r_wrist",
             "l_hip", "l_knee", "l_ankle", "l_toe",
             "r_hip", "r_knee", "r_ankle", "r_toe"]

def euler_xyz(r) -> np.ndarray:
    """HSD local rotation (x, y, z radians, M = Rz*Ry*Rx) -> 3x3."""
    cx, sx = math.cos(r[0]), math.sin(r[0])
    cy, sy = math.cos(r[1]), math.sin(r[1])
    cz, sz = math.cos(r[2]), math.sin(r[2])
    Rx = np.array([[1.0, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1.0, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1.0]])
    return Rz @ Ry @ Rx


class Rig:
    """A rig kit's joints json, its rest-pose forward kinematics, and the
    landmark map derived from that geometry."""

    def __init__(self, joints_json):
        meta = joints_json if isinstance(joints_json, dict) else \
            json.loads(Path(joints_json).read_text(encoding="utf-8"))
        self.meta = meta
        self.order: list[str] = meta["order"]
        self.parent: dict = meta["parent"]
        self.rename: dict = meta["rename"]
        self.rest: dict = meta["rest"]
        self.local: dict = {}
        self.world: dict = {}
        for j in self.order:
            e = self.rest[j]
            L = np.eye(4)
            L[:3, :3] = euler_xyz(e["r"]) * np.array(e["s"])
            L[:3, 3] = e["t"]
            self.local[j] = L
            p = self.parent[j]
            self.world[j] = (self.world[p] @ L) if p else L
        self.kids: dict = {}
        for j in self.order:
            self.kids.setdefault(self.parent[j], []).append(j)
        self.pos = {j: self.world[j][:3, 3] for j in self.order}
        if 'landmarks' in meta:
            landmarks = meta['landmarks']
            if (not isinstance(landmarks, dict) or not landmarks or 'pelvis' not in landmarks
                    or any(not isinstance(j, str) or j not in self.order for j in landmarks.values())):
                raise ValueError('explicit landmarks must name existing joints and include pelvis')
            self.landmarks = dict(landmarks)
        else:
            self.landmarks = self._find()

    # -- tree helpers -------------------------------------------------------
    def _ancestors(self, j):
        out, cur = [], j
        while cur:
            out.append(cur)
            cur = self.parent[cur]
        return out

    def _lca(self, a, b):
        anc = set(self._ancestors(b))
        for j in self._ancestors(a):
            if j in anc:
                return j
        return self.order[0]

    def _path(self, top, leaf):
        chain, cur = [], leaf
        while cur and cur != top:
            chain.append(cur)
            cur = self.parent[cur]
        chain.append(top)
        return list(reversed(chain))

    def _distinct(self, chain, eps=1e-3):
        """Collapse runs of coincident joints, keeping the DEEPEST of each run.

        Melee skeletons interleave `*JA` adjust joints sitting exactly on their
        parent (LLegJA on LLegJ, LShoulderJ on LArmJ). Vanilla animation keys the
        deeper one, and rotating it moves only the limb below it."""
        out = []
        for j in chain:
            if out and np.linalg.norm(self.pos[j] - self.pos[out[-1]]) < eps:
                out[-1] = j
            else:
                out.append(j)
        return out

    def _leaves(self):
        return [j for j in self.order if not self.kids.get(j)]

    def _subtree(self, j):
        out, stack = [], [j]
        while stack:
            k = stack.pop()
            out.append(k)
            stack.extend(self.kids.get(k, []))
        return out

    # -- landmark discovery -------------------------------------------------
    def _find(self):
        pos, lm = self.pos, {}
        leaves = self._leaves()
        ys = [p[1] for p in pos.values()]
        top_y, low_y = max(ys), min(ys)
        span = max(top_y - low_y, 1e-6)

        # Feet: the lowest leaf on each side, restricted to the bottom quarter of
        # the body so a hanging cape or a lowered sword tip cannot pose as one.
        floor = low_y + 0.25 * span
        foot_leaves = [j for j in leaves if pos[j][1] <= floor]
        if len(foot_leaves) < 2:
            foot_leaves = sorted(leaves, key=lambda j: pos[j][1])[:2]
        left = [j for j in foot_leaves if pos[j][0] > 0] or foot_leaves
        right = [j for j in foot_leaves if pos[j][0] < 0] or foot_leaves
        l_toe = min(left, key=lambda j: pos[j][1])
        r_toe = min(right, key=lambda j: pos[j][1])
        lm["pelvis"] = pelvis = self._lca(l_toe, r_toe)

        for side, toe in (("l", l_toe), ("r", r_toe)):
            nodes = self._distinct(self._path(pelvis, toe))
            drop = pos[pelvis][1] - pos[toe][1]
            hip = nodes[1] if len(nodes) > 1 else pelvis
            ankle = next((j for j in nodes[1:] if pos[j][1] <= pos[pelvis][1] - 0.8 * drop), nodes[-1])
            mid = 0.5 * (pos[hip][1] + pos[ankle][1])
            lo, hi = nodes.index(hip), nodes.index(ankle)
            between = nodes[lo + 1:hi]
            knee = min(between, key=lambda j: abs(pos[j][1] - mid)) if between else ankle
            lm[side + "_hip"], lm[side + "_knee"], lm[side + "_ankle"] = hip, knee, ankle
            lm[side + "_toe"] = nodes[-1]

        # Hands: the joint that fans out into fingers. Falls back to the chain to
        # the outermost leaf when a fighter has no separate finger joints.
        wrists = {}
        for side, sign in (("l", 1), ("r", -1)):
            cand = [j for j in leaves if sign * pos[j][0] > 0] or leaves
            tip = max(cand, key=lambda j: sign * pos[j][0])
            chain = self._path(self.order[0], tip)
            fan = [j for j in chain if len(self.kids.get(j, [])) >= 3]
            wrists[side] = fan[-1] if fan else self._distinct(chain)[-1]
        lm["chest"] = chest = self._lca(wrists["l"], wrists["r"])

        for side in ("l", "r"):
            nodes = self._distinct(self._path(chest, wrists[side]))

            def nth(k, nodes=nodes):
                return nodes[k] if len(nodes) >= -k else nodes[0]

            lm[side + "_wrist"] = nodes[-1]
            lm[side + "_elbow"] = nth(-2)
            lm[side + "_shoulder"] = nth(-3)
            lm[side + "_collar"] = nth(-4)

        spine_nodes = self._distinct(self._path(pelvis, chest))
        lm["spine"] = spine_nodes[1] if len(spine_nodes) > 2 else pelvis

        # Head: the branch off the chest that is neither arm, walked to its top.
        arm_sets = set()
        for s in ("l", "r"):
            arm_sets.update(self._subtree(lm[s + "_collar"]))
        head_kids = [k for k in self.kids.get(chest, []) if k not in arm_sets]
        if head_kids:
            branch = max(head_kids, key=lambda k: max(pos[j][1] for j in self._subtree(k)))
            top = max(self._subtree(branch), key=lambda j: pos[j][1])
            nodes = self._distinct(self._path(branch, top))
            lm["neck"] = nodes[0]
            lm["head"] = nodes[1] if len(nodes) > 1 else nodes[0]
        else:
            lm["neck"] = lm["head"] = chest
        return lm

    # -- consumers ----------------------------------------------------------
    def describe(self):
        """Landmarks with the JOBJ, its (lying) name and its rest position --
        what to eyeball the first time a new fighter is mapped."""
        return {k: {"jobj": j, "name": self.rename.get(j, j),
                    "pos": [round(float(v), 2) for v in self.pos[j]]}
                for k, j in self.landmarks.items()}


def main():
    import argparse
    ap = argparse.ArgumentParser(description="landmark map of a rig kit's joints json")
    ap.add_argument("joints_json")
    a = ap.parse_args()
    print(json.dumps(Rig(a.joints_json).describe(), indent=1))


if __name__ == "__main__":
    main()
