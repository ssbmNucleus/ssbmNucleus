"""Rotation helpers the fighter-port retargeters share, and the landmark bone map.

Pure numpy. The SMPL video-capture converter that gave this file its name was
removed in November 2026; the name stays because `retarget.py`, `author.py` and
`moveset.py` fingerprint this module by basename into their capture manifests.
"""
from __future__ import annotations

import math

import numpy as np

# each landmark's representative child: the bone whose direction defines the
# joint's orientation on both skeletons
BONE_CHILD = {"pelvis": "spine", "spine": "chest", "chest": "neck", "neck": "head",
              "l_collar": "l_shoulder", "l_shoulder": "l_elbow", "l_elbow": "l_wrist",
              "r_collar": "r_shoulder", "r_shoulder": "r_elbow", "r_elbow": "r_wrist",
              "l_hip": "l_knee", "l_knee": "l_ankle", "l_ankle": "l_toe",
              "r_hip": "r_knee", "r_knee": "r_ankle", "r_ankle": "r_toe"}


def rodrigues(v: np.ndarray) -> np.ndarray:
    theta = float(np.linalg.norm(v))
    if theta < 1e-9:
        return np.eye(3)
    k = v / theta
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(theta) * K + (1 - math.cos(theta)) * (K @ K)


def orthonormalize(M: np.ndarray) -> np.ndarray:
    u, _, vt = np.linalg.svd(M)
    R = u @ vt
    if np.linalg.det(R) < 0:
        u[:, -1] *= -1
        R = u @ vt
    return R


def min_rot(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Smallest rotation taking unit vector a to unit vector b."""
    a, b = a / (np.linalg.norm(a) + 1e-12), b / (np.linalg.norm(b) + 1e-12)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if np.linalg.norm(v) < 1e-9:
        if c > 0:
            return np.eye(3)
        axis = np.array([1.0, 0, 0]) if abs(a[0]) < 0.9 else np.array([0, 1.0, 0])
        v = np.cross(a, axis)
        return rodrigues(v / np.linalg.norm(v) * math.pi)
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + K + K @ K / (1 + c)


def to_hsd_euler(R: np.ndarray):
    """R = Rz * Ry * Rx  ->  (x, y, z) radians."""
    sy = max(-1.0, min(1.0, -R[2, 0]))
    y = math.asin(sy)
    if abs(math.cos(y)) > 1e-6:
        return math.atan2(R[2, 1], R[2, 2]), y, math.atan2(R[1, 0], R[0, 0])
    return math.atan2(-R[1, 2], R[1, 1]), y, 0.0


def unwrap(prev, v):
    if prev is None:
        return v
    while v - prev > math.pi:
        v -= 2 * math.pi
    while v - prev < -math.pi:
        v += 2 * math.pi
    return v


def quats(G: np.ndarray) -> np.ndarray:
    """[T,3,3] -> [T,4] sign-continuous quaternions (w, x, y, z).

    q and -q are the same rotation; without the sign pass a filter would average
    a rotation with its own negation and collapse it."""
    T = len(G)
    Q = np.empty((T, 4))
    for f in range(T):
        R = G[f]
        tr = R[0, 0] + R[1, 1] + R[2, 2]
        if tr > 0:
            sq = math.sqrt(tr + 1.0) * 2
            q = [0.25 * sq, (R[2, 1] - R[1, 2]) / sq, (R[0, 2] - R[2, 0]) / sq, (R[1, 0] - R[0, 1]) / sq]
        elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
            sq = math.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
            q = [(R[2, 1] - R[1, 2]) / sq, 0.25 * sq, (R[0, 1] + R[1, 0]) / sq, (R[0, 2] + R[2, 0]) / sq]
        elif R[1, 1] > R[2, 2]:
            sq = math.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
            q = [(R[0, 2] - R[2, 0]) / sq, (R[0, 1] + R[1, 0]) / sq, 0.25 * sq, (R[1, 2] + R[2, 1]) / sq]
        else:
            sq = math.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
            q = [(R[1, 0] - R[0, 1]) / sq, (R[0, 2] + R[2, 0]) / sq, (R[1, 2] + R[2, 1]) / sq, 0.25 * sq]
        v = np.array(q)
        v /= np.linalg.norm(v)
        if f and np.dot(v, Q[f - 1]) < 0:
            v = -v
        Q[f] = v
    return Q


def quat_to_mat(q: np.ndarray) -> np.ndarray:
    w, x, y, z = q / np.linalg.norm(q)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])
