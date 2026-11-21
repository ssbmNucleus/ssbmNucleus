"""The Maya .anim writer `HSDRawViewer --anim import` reads.

`write_anim` is what the fighter-port authors (`retarget.py`, `author.py`,
`moveset.py`, `ultimate.py`) write clips with. The BVH converter that gave this
file its name was removed in November 2026; the name stays because the
retargeters fingerprint this module by basename into their capture manifests.
"""
from __future__ import annotations

from pathlib import Path


def write_anim(path, end_frame: int, channels: dict[str, dict[str, dict[int, float]]], order: list[str]):
    lines = ["animVersion 1.1;", "mayaVersion 2015;", "timeUnit ntscf;", "linearUnit cm;",
             "angularUnit rad;", "startTime 0;", f"endTime {end_frame};"]
    row = 0
    for jobj in order:
        chans = channels.get(jobj) or {}
        if not chans:
            lines.append(f"anim {jobj} 0 {row} 0;")
            row += 1
            continue
        for ch, keys in chans.items():
            attr = "translate" if ch.startswith("translate") else ("rotate" if ch.startswith("rotate") else "scale")
            lines.append(f"anim {attr}.{ch} {ch} {jobj} 0 {row} 0;")
            lines.append("animData {")
            lines.append(" input time;")
            lines.append(" output " + ("angular" if attr == "rotate" else "linear") + ";")
            lines.append(" weighted 0;")
            lines.append(" preInfinity constant;")
            lines.append(" postInfinity constant;")
            lines.append(" keys {")
            for f in sorted(keys):
                lines.append(f" {f} {keys[f]:.6f} linear linear 1 1 0;")
            lines.append(" }")
            lines.append("}")
            row += 1
    Path(path).write_text("\n".join(lines) + "\n")
