"""Compact data/rngInputTails.json (the full, documented table: every action,
nulls for unproven entries, provenance in `special`) into the runtime file the
viewer imports. stageSim/rng.js only ever adds a POSITIVE fixed count; null and
0 both mean "add nothing", so the runtime keeps just the non-zero entries."""
import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "app/frontend/src/tracker/replays/data"
full = json.loads((DATA / "rngInputTails.json").read_text(encoding="utf-8"))
tails = {cid: {st: n for st, n in rows.items() if isinstance(n, int) and n > 0}
         for cid, rows in full["tails"].items()}
tails = {cid: rows for cid, rows in tails.items() if rows}
out = {"schema": full.get("schema", 1), "source": "rngInputTails.json (non-zero fixed counts only)",
       "tails": tails}
(DATA / "rngInputTails.runtime.json").write_text(json.dumps(out, separators=(",", ":"), sort_keys=True) + "\n",
                                                 encoding="utf-8")
print(sum(len(r) for r in tails.values()), "entries")
