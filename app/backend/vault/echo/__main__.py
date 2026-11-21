"""
python -m vault.echo -- the Echo op surface from the command line (cold JSON in,
JSON out). Every verb is a thin wrapper over vault.echo.ops so a script, the Flask
API and a copilot all hit the same code.

    python -m vault.echo describe  PlFc.dat                     # moves + attributes
    python -m vault.echo inspect   PlFc.dat ftilt [--part up]   # one move part
    python -m vault.echo plan      PlFc.dat ops.json            # validate only
    python -m vault.echo apply     PlFc.dat ops.json out.dat    # write the patched DAT
    python -m vault.echo diff      PlFc.dat edited.dat          # recover ops
    python -m vault.echo verify    PlFc.dat                     # codec round-trip

ops.json is either a JSON list of ops or {"ops": [...]}.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import ops
from .subactions import FighterDat


def _load_ops(path: str) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8")) if path != "-" else json.load(sys.stdin)
    if isinstance(data, dict):
        data = data.get("ops", [])
    if not isinstance(data, list):
        raise SystemExit("ops file must be a JSON list or {\"ops\": [...]}")
    return data


def _out(obj) -> None:
    print(json.dumps(obj, indent=2))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m vault.echo")
    sub = ap.add_subparsers(dest="verb", required=True)

    d = sub.add_parser("describe"); d.add_argument("dat"); d.add_argument("--all", action="store_true")
    i = sub.add_parser("inspect"); i.add_argument("dat"); i.add_argument("move")
    i.add_argument("--part"); i.add_argument("--donor")
    p = sub.add_parser("plan"); p.add_argument("dat"); p.add_argument("ops")
    a = sub.add_parser("apply"); a.add_argument("dat"); a.add_argument("ops"); a.add_argument("out")
    f = sub.add_parser("diff"); f.add_argument("dat"); f.add_argument("edited")
    v = sub.add_parser("verify"); v.add_argument("dat")

    ns = ap.parse_args(argv)
    donor = Path(ns.dat).read_bytes()

    if ns.verb == "describe":
        _out(ops.describe(donor, include_other=ns.all))
    elif ns.verb == "inspect":
        ref = Path(ns.donor).read_bytes() if ns.donor else None
        _out(ops.inspect_move(donor, ns.move, ns.part, donor_ref=ref))
    elif ns.verb == "plan":
        pl = ops.plan(donor, _load_ops(ns.ops))
        _out({"ok": pl.ok, "steps": [s.as_dict() for s in pl.steps], "errors": pl.errors})
        return 0 if pl.ok else 1
    elif ns.verb == "apply":
        try:
            r = ops.apply(donor, _load_ops(ns.ops))
        except ops.OpError as e:
            _out({"ok": False, "error": str(e)})
            return 1
        Path(ns.out).write_bytes(r.data)
        _out({**r.as_dict(), "out": ns.out, "bytes": len(r.data)})
    elif ns.verb == "diff":
        _out({"ops": ops.diff(donor, Path(ns.edited).read_bytes())})
    elif ns.verb == "verify":
        fd = FighterDat(donor)
        probs = fd.verify_roundtrip()
        _out({"ok": not probs, "fighter": fd.fighter_name, "actions": len(fd.actions),
              "commands": sum(len(fd.script(x.index).commands) for x in fd.actions if fd.script(x.index)),
              "problems": probs[:20]})
        return 0 if not probs else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
