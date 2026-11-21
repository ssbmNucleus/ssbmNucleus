"""Install captured or authored clips onto a fighter's (AJ, Pl) pair.

`install` is the one entry point: `oneshot.py` calls it for a whole moveset at
once. The September video-capture pipeline that used to live here was removed
in November 2026.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
import nucleus_root  # the repo root is on sys.path whenever fighter_port imports
BACKEND = nucleus_root.BACKEND  # the ssbmNucleus app backend, not this repo
REPO_ROOT = nucleus_root.HERE


def _fwd(p: Path | str) -> str:
    return str(p).replace("\\", "/")


def install(aj: Path, pl: Path, moves: list[dict], out_aj: Path, out_pl: Path,
            error: float = 0.0001, skip_unknown: bool = False,
            workdir: Path | None = None) -> dict:
    """Import clips onto moves of an (AJ, Pl) pair -- the same code path the echo
    package's `animations` field uses, so a clip that installs here also installs
    through `vault.echo.package.materialize`.

    moves: [{"move": "ftilt", "file": "x.anim", "part"?: "...", "error"?: 1e-4}, ...]
    A whole moveset goes in ONE call: every extra pass re-encodes the entire bank
    and slides every later clip's offset, so 25 chained single installs cost 25
    rewrites of a ~3 MB file for no reason.
    """
    sys.path.insert(0, str(BACKEND))
    from vault.echo import anim as echo_anim
    from .provenance import fingerprint, verify_bundle
    ovs = []
    runs = []
    for m in moves:
        if m.get("manifest"):
            _, artifacts = verify_bundle(Path(m["manifest"]))
            if fingerprint(m["file"])["sha256"] != fingerprint(artifacts["animation"])["sha256"]:
                raise ValueError(f"install: {m['move']} animation no longer matches its capture manifest")
            runs.append(fingerprint(m["manifest"]))
        ov = {"move": m["move"], "file": str(m["file"]), "error": float(m.get("error", error))}
        if m.get("part"):
            ov["part"] = m["part"]
        if m.get("engine_root"):
            ov["engine_root"] = m["engine_root"]
        ovs.append(ov)
    if not ovs:
        raise ValueError("install: no moves given")
    skipped = []
    if skip_unknown:
        # Movesets do not line up between fighters: Shulk jabs three times, Marth
        # twice, so jab/3 has nowhere to go. Dropping those and saying so beats
        # failing 22 good clips over one that has no slot.
        errs = echo_anim.validate_overrides(Path(pl).read_bytes(), ovs)
        bad = {int(e.split("[")[1].split("]")[0]) for e in errs if e.startswith("animation[")}
        skipped = [{"move": ovs[i]["move"], "part": ovs[i].get("part"),
                    "why": next(e.split(": ", 1)[-1] for e in errs
                                if e.startswith(f"animation[{i}]"))}
                   for i in sorted(bad)]
        ovs = [o for i, o in enumerate(ovs) if i not in bad]
        if not ovs:
            raise ValueError(f"install: every move was skipped ({skipped})")
    inputs = {"aj": fingerprint(aj), "pl": fingerprint(pl),
              "animations": [{**o, "artifact": fingerprint(o["file"])} for o in ovs]}
    # A worker can retain import intermediates in its own writable artifact tree.
    # Without an explicit directory, preserve the existing temporary-dir policy.
    workspace = {"workdir": workdir} if workdir is not None else {}
    new_aj, new_pl, report = echo_anim.apply_overrides(Path(aj).read_bytes(), Path(pl).read_bytes(), ovs, **workspace)
    # Imported durations can outlive a donor script's final absolute timer.
    # Guard those self-loops before they can spin forever in one game frame.
    from .moveset import guard_animation_loops, enable_engine_root
    from vault.echo.subactions import FighterDat
    symbols = {row['symbol'] for row in report}
    imported = [a.index for a in FighterDat(new_pl).actions if a.symbol in symbols]
    new_pl, loop_guards = guard_animation_loops(new_pl, imported)
    root_symbols = {echo_anim.action_symbol(new_pl, o['move'], o.get('part'))
                    for o in ovs if o.get('engine_root')}
    new_pl, root_flags = enable_engine_root(new_pl,
        [a.index for a in FighterDat(new_pl).actions if a.symbol in root_symbols])
    Path(out_aj).write_bytes(new_aj)
    Path(out_pl).write_bytes(new_pl)
    from core.config import HSDRAW_EXE
    install_record = Path(out_aj).with_suffix(".install.json")
    install_record.write_text(json.dumps({"schema": 1, "inputs": inputs, "capture_manifests": runs,
                             "outputs": {"aj": fingerprint(out_aj), "pl": fingerprint(out_pl)},
                             "hsdraw": fingerprint(HSDRAW_EXE), "report": report,
                             "loop_guards": loop_guards, "engine_root_flags": root_flags}, indent=2), encoding="utf-8")
    return {"aj": _fwd(out_aj), "pl": _fwd(out_pl), "manifest": _fwd(install_record),
            "moves": [o["move"] + ("/" + o["part"] if o.get("part") else "") for o in ovs],
            "skipped": skipped, "report": report}
