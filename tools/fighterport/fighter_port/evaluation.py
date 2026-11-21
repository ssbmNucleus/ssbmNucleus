"""Frame-aligned sampling of fighter-port/HSDRaw Maya animations.

Supports the unweighted, constant-infinity subset written by bvh_to_anim and
HSDRawViewer/Converters/Animation/MayaAnim.cs. Tangent angles in HSDRaw's rad
exports are in DEGREES (atan(slope) * 180/pi), not radians. Reject unsupported
curves rather than silently producing reassuring but incorrect measurements.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import math
from pathlib import Path

import numpy as np

from .rigmap import Rig, euler_xyz


@dataclass(frozen=True)
class Key:
    time: float
    value: float
    outgoing: str
    in_slope: float = 0.0
    out_slope: float = 0.0


def sample(keys: list[Key], time: float) -> float:
    i = bisect_right([k.time for k in keys], time) - 1
    if i < 0:
        return keys[0].value
    a = keys[i]
    if i == len(keys) - 1 or a.outgoing == "step":
        return a.value
    b = keys[i + 1]
    dt = b.time - a.time
    u = (time - a.time) / dt
    if a.outgoing in ("linear", "auto"):
        return a.value + u * (b.value - a.value)
    # Cubic Hermite with endpoint derivatives, matching unweighted HSD curves.
    return ((2*u**3 - 3*u**2 + 1)*a.value + (u**3 - 2*u**2 + u)*dt*a.out_slope
            + (-2*u**3 + 3*u**2)*b.value + (u**3 - u**2)*dt*b.in_slope)


class Animation:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.channels: dict[str, dict[str, list[Key]]] = {}
        self.start, self.end = 0.0, None
        current, in_keys = None, False
        for line in self.path.read_text(encoding="utf-8-sig").splitlines():
            words = line.strip().rstrip(";").split()
            if not words:
                continue
            tag = words[0]
            if tag in ("angularUnit", "linearUnit", "timeUnit"):
                allowed = {"angularUnit": "rad", "linearUnit": "cm", "timeUnit": "ntscf"}
                if words[1] != allowed[tag]:
                    raise ValueError(f"{path}: unsupported {tag} {words[1]}")
            elif tag == "startTime":
                self.start = float(words[1])
            elif tag == "endTime":
                self.end = float(words[1])
            elif tag == "anim":
                current, in_keys = None, False
                if len(words) >= 7:
                    channel = words[2]
                    if channel not in [kind + axis for kind in ("rotate", "translate", "scale") for axis in "XYZ"]:
                        raise ValueError(f"{path}: unsupported channel {channel}")
                    current = self.channels.setdefault(words[3], {}).setdefault(channel, [])
            elif tag == "weighted" and words[1] != "0":
                raise ValueError(f"{path}: weighted curves are not supported")
            elif tag in ("preInfinity", "postInfinity") and words[1] != "constant":
                raise ValueError(f"{path}: nonconstant infinity is not supported")
            elif tag == "keys":
                in_keys = True
            elif tag == "}":
                in_keys = False
            elif in_keys and current is not None:
                time, value = float(words[0]), float(words[1])
                incoming, outgoing = words[2:4]
                if outgoing not in ("linear", "auto", "step", "spline", "fixed"):
                    raise ValueError(f"{path}: unsupported tangent {outgoing}")
                tails = iter(words[7:])
                slopes = []
                for tangent in (incoming, outgoing):
                    slope = 0.0
                    if tangent in ("spline", "fixed", "auto"):
                        angle = next(tails, None)
                        weight = next(tails, None)
                        if angle is None and tangent != "auto":
                            raise ValueError(f"{path}: missing explicit {tangent} tangent")
                        if angle is not None:
                            if weight is None:
                                raise ValueError(f"{path}: incomplete tangent")
                            slope = math.tan(math.radians(float(angle)))
                    slopes.append(slope)
                if not all(math.isfinite(v) for v in (time, value, *slopes)):
                    raise ValueError(f"{path}: non-finite key")
                if current and time <= current[-1].time:
                    raise ValueError(f"{path}: keys must be strictly increasing")
                current.append(Key(time, value, outgoing, *slopes))
        if self.end is None or not math.isfinite(self.start) or not math.isfinite(self.end) or self.end < self.start:
            raise ValueError(f"{path}: invalid animation interval")
        if any(not keys for channels in self.channels.values() for keys in channels.values()):
            raise ValueError(f"{path}: empty curve")

    def times(self) -> list[float]:
        return sorted({self.start, self.end, *range(math.ceil(self.start), math.floor(self.end) + 1)})

    def world(self, rig: Rig, time: float) -> dict:
        if not math.isfinite(time) or time < self.start - 1e-6 or time > self.end + 1e-6:
            raise ValueError(f"{self.path}: frame {time} outside [{self.start}, {self.end}]")
        unknown = self.channels.keys() - rig.rest.keys()
        if unknown:
            raise ValueError(f"animation joints absent from rig: {sorted(unknown)}")
        result = {}
        for joint in rig.order:
            rest = rig.rest[joint]
            channels = self.channels.get(joint, {})
            def values(kind, default):
                return [sample(channels[kind + axis], time) if kind + axis in channels else rest[default][i]
                        for i, axis in enumerate("XYZ")]
            local = np.eye(4)
            local[:3, :3] = euler_xyz(values("rotate", "r")) * np.array(values("scale", "s"))
            local[:3, 3] = values("translate", "t")
            parent = rig.parent[joint]
            result[joint] = result[parent] @ local if parent else local
        return result
