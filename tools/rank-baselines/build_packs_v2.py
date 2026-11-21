"""Aggregate analyzer_v2 rows into baseline packs for the in-app coach.

Inputs
  $MELEE_MINE_ROWS/<CHAR>_<tier>-<tier>_aN.jsonl     ranked-shard rows (default ~/melee-mine/rows)
  data/v2_rows_summit.jsonl                            summit corpus rows
  data/{diamond,master}_falco_marth_events.json        tier OOS tables (v1 mining)

Output packs (default --out app/backend/tracker/baselines):
  manifest.json                     tiers/chars available + provenance
  <tier>/<Char>.json                population pack per tier x character

Incremental: re-run any time; aggregates whatever row files exist so far.
"""
import argparse
import glob
import json
import os
import statistics

# three levels up: this script lives at <repo>/tools/rank-baselines/, and REPO must
# be the repo (data/ is the untracked corpus at the repo root).
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(REPO, "data")
ROWS_DIR = os.environ.get("MELEE_MINE_ROWS") or os.path.join(os.path.expanduser("~"), "melee-mine", "rows")

METRICS = ["lc_rate", "wd_per_min", "apm", "tech_rate", "openings_per_min",
           "dmg_per_conv", "one_hit_pct", "kill_conv_pct", "avg_death_pct",
           "deaths_per_min", "dmg_taken_per_min",
           "center_control", "corner_pct", "neutral_wins_pct"]
DEATH_CAUSES = ["raw", "edgeguard", "failed_recovery", "tech_chase", "sd"]
MIN_GAMES_CHAR = 150      # only publish a tier x char pack above this
MIN_GAMES_CHAR_SUMMIT = 30  # the summit corpus is small but precious
MIN_GAMES_MATCHUP = 75
MIN_GAMES_STAGE = 40


def q(vals, p):
    if not vals:
        return None
    vs = sorted(vals)
    k = (len(vs) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(vs) - 1)
    return round(vs[lo] + (vs[hi] - vs[lo]) * (k - lo), 2)


def metric_summary(rows):
    out = {}
    for k in METRICS:
        vals = [r[k] for r in rows if r.get(k) is not None]
        if vals:
            out[k] = {"median": round(statistics.median(vals), 2),
                      "mean": round(statistics.mean(vals), 2),
                      "p25": q(vals, 0.25), "p75": q(vals, 0.75)}
    return out


def death_summary(rows, field="deaths"):
    """Aggregate a death-event list field — 'deaths' (how you die) or its
    offense mirror 'kills' (how you close stocks)."""
    pcts, causes, moves = [], {c: 0 for c in DEATH_CAUSES}, {}
    for r in rows:
        for d in r.get(field) or []:
            pcts.append(d["pct"])
            causes[d.get("cause", "raw")] = causes.get(d.get("cause", "raw"), 0) + 1
            if d.get("by"):
                moves[d["by"]] = moves.get(d["by"], 0) + 1
    n = len(pcts)
    if not n:
        return None
    buckets = {}
    for p in pcts:
        b = min(int(p // 20) * 20, 180)
        key = f"{b}-{b+19}" if b < 180 else "180+"
        buckets[key] = buckets.get(key, 0) + 1
    order = [f"{b}-{b+19}" for b in range(0, 180, 20)] + ["180+"]
    top_moves = dict(sorted(moves.items(), key=lambda kv: -kv[1])[:10])
    return {
        "n_deaths": n,
        "percent_distribution": {k: round(100.0 * buckets.get(k, 0) / n, 1)
                                 for k in order if buckets.get(k)},
        "percentiles": {"p10": q(pcts, 0.10), "p25": q(pcts, 0.25),
                        "median": q(pcts, 0.50), "p75": q(pcts, 0.75),
                        "p90": q(pcts, 0.90)},
        "causes_pct": {c: round(100.0 * causes[c] / n, 1) for c in DEATH_CAUSES},
        "by_move_pct": {m: round(100.0 * c / n, 1) for m, c in top_moves.items()},
    }


def tech_summary(rows):
    tot = {k: 0 for k in ("ground_hit", "ground_miss", "plat_hit", "plat_miss",
                          "throw_hit", "throw_miss")}
    for r in rows:
        for k, v in (r.get("tech_ctx") or {}).items():
            tot[k] = tot.get(k, 0) + v

    def rate(hit, miss):
        return round(100.0 * tot[hit] / (tot[hit] + tot[miss]), 1) \
            if tot[hit] + tot[miss] else None
    n_all = sum(tot.values()) - tot["throw_hit"] - tot["throw_miss"]
    hit_all = tot["ground_hit"] + tot["plat_hit"]
    return {
        "overall_rate": round(100.0 * hit_all / n_all, 1) if n_all else None,
        "ground_rate": rate("ground_hit", "ground_miss"),
        "platform_rate": rate("plat_hit", "plat_miss"),
        "after_throw_rate": rate("throw_hit", "throw_miss"),
        "n_situations": n_all,
    }


def recovery_summary(rows):
    ep = sum(r["recovery"]["episodes"] for r in rows if r.get("recovery"))
    ok = sum(r["recovery"]["success"] for r in rows if r.get("recovery"))
    if not ep:
        return None
    return {"success_pct": round(100.0 * ok / ep, 1),
            "attempts_per_game": round(ep / len(rows), 2)}


def slice_summary(rows):
    """Small metric set for per-stage / per-matchup slices."""
    out = {"n_games": len(rows),
           "win_pct": round(100.0 * sum(1 for r in rows if r.get("won")) / len(rows), 1)}
    for k in ("openings_per_min", "dmg_per_conv", "kill_conv_pct",
              "avg_death_pct", "deaths_per_min", "tech_rate", "lc_rate"):
        vals = [r[k] for r in rows if r.get(k) is not None]
        if vals:
            out[k] = round(statistics.median(vals), 2)
    d = death_summary(rows)
    if d:
        out["death_causes_pct"] = d["causes_pct"]
    return out


def build_pack(rows, tier, char):
    pack = {
        "tier": tier,
        "char": char,
        "n_games": len(rows),
        "minutes": round(sum(r["minutes"] for r in rows), 0),
        "metrics": metric_summary(rows),
        "deaths": death_summary(rows),
        "kills": death_summary(rows, field="kills"),
        "tech": tech_summary(rows),
        "recovery": recovery_summary(rows),
        "per_matchup": {}, "per_stage": {},
    }
    by_mu, by_stage = {}, {}
    for r in rows:
        by_mu.setdefault(r["vs"], []).append(r)
        by_stage.setdefault(r["stage"], []).append(r)
    for mu, rs in sorted(by_mu.items(), key=lambda kv: -len(kv[1])):
        if len(rs) >= MIN_GAMES_MATCHUP:
            pack["per_matchup"][mu] = slice_summary(rs)
    for st, rs in sorted(by_stage.items(), key=lambda kv: -len(kv[1])):
        if len(rs) >= MIN_GAMES_STAGE:
            pack["per_stage"][st] = slice_summary(rs)
    return pack


def oos_table(events):
    """events = [(option, swing, died)] -> option table like the v1 fixture.
    predictability = 100 * (1 - normalized entropy of the option mix): 0 =
    perfectly mixed, 100 = always the same option (exploitable)."""
    import math
    by = {}
    for opt, swing, died in events:
        by.setdefault(opt, []).append((swing, died))
    n = len(events)
    table = {}
    for opt, rows in sorted(by.items(), key=lambda kv: -len(kv[1])):
        swings = [r[0] for r in rows]
        deaths = sum(1 for r in rows if r[1])
        table[opt] = {"freq_pct": round(100.0 * len(rows) / n, 1),
                      "avg_swing": round(statistics.mean(swings), 1),
                      "death_pct": round(100.0 * deaths / len(rows), 1),
                      "n": len(rows)}
    predict = None
    if len(by) > 1:
        ps = [len(rows) / n for rows in by.values()]
        h = -sum(p * math.log(p) for p in ps if p > 0)
        predict = round(100.0 * (1 - h / math.log(len(by))), 1)
    return {"n_situations": n, "options": table,
            "predictability": predict}


# Rows mined before the 2026-07-14 ATTACK_NAMES fix carry move names from a
# table that was shifted one id down across ids 1-20 (see analyzer_v2.py).
# The stored (wrong) name still identifies the original id uniquely, so
# translate to the canonical name at load time. Throws/getups were always
# correct and pass through. When the rows archive is ever RE-MINED with the
# fixed analyzer, delete this remap — applying it to already-correct names
# would shift them again.
OLD_MOVE_NAME_FIX = {
    "jab": "misc", "jab2": "jab", "jab3": "jab2", "rapid jabs": "jab3",
    "dash attack": "rapid jabs", "ftilt": "dash attack", "utilt": "ftilt",
    "dtilt": "utilt", "fsmash": "dtilt", "usmash": "fsmash",
    "dsmash": "usmash", "nair": "dsmash", "fair": "nair", "bair": "fair",
    "uair": "bair", "dair": "uair", "neutral-B": "dair", "side-B": "neutral-B",
    "up-B": "side-B", "down-B": "up-B", "attack21": "down-B",
}


def _fix_move_names(row):
    for field in ("deaths", "kills"):
        for d in row.get(field) or []:
            by = d.get("by")
            if by in OLD_MOVE_NAME_FIX:
                d["by"] = OLD_MOVE_NAME_FIX[by]
    return row


def load_rows(path, seen=None):
    """Load a rows JSONL. `seen` (a shared set of (file, port) keys) dedupes
    across ALL loaded files: shard filenames are dataset-unique hashes, so
    duplicate rows — e.g. from the Modal warm-container accumulation bug, or
    the same shard mined by two lanes — collapse to one copy."""
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue          # tolerate a mid-write tail line
            if seen is not None:
                key = (row.get("file"), row.get("port"))
                if key in seen:
                    continue
                seen.add(key)
            rows.append(_fix_move_names(row))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(
        REPO, "app", "backend", "tracker", "baselines"))
    ap.add_argument("--date", default=None, help="generated-on stamp for manifest")
    args = ap.parse_args()

    # ---- gather rows per tier (all mined character folders).
    # SAME-TIER shards only: a cross-tier row (e.g. a master farming
    # platinums) has inflated outcome stats and would poison the tier
    # baseline. Cross-tier rows are a separate future study.
    tier_rows = {}
    shard_files = []
    seen = set()          # global (file, port) dedup across every shard file
    dropped_rank = 0
    for p in sorted(glob.glob(os.path.join(ROWS_DIR, "*_a*.jsonl"))):
        base = os.path.basename(p)
        pair = base.split("_")[1].split("-")         # ["diamond","diamond"]
        if len(pair) != 2 or pair[0] != pair[1]:
            continue
        shard_files.append(p)
        tier = pair[0]
        kept = []
        for r in load_rows(p, seen):
            # rows stamp the player's rank from the netplay name; a mismatch
            # with the file's tier means cross-shard contamination — drop it
            if r.get("rank") and r["rank"] != tier:
                dropped_rank += 1
                continue
            kept.append(r)
        tier_rows.setdefault(tier, []).extend(kept)
    if dropped_rank:
        print(f"dropped {dropped_rank} rows with rank/tier mismatch "
              f"(cross-shard contamination guard)", flush=True)
    summit_path = os.path.join(DATA, "v2_rows_summit.jsonl")
    if os.path.exists(summit_path):
        tier_rows["summit"] = load_rows(summit_path)

    os.makedirs(args.out, exist_ok=True)
    manifest = {"version": 2, "generated": args.date,
                "source": "erickfm/melee-ranked-replays (MIT) + summit11 corpus",
                "tiers": {}, "shards_aggregated": [os.path.basename(p) for p in shard_files]}

    for tier, rows in tier_rows.items():
        by_char = {}
        for r in rows:
            by_char.setdefault(r["char"], []).append(r)
        tdir = os.path.join(args.out, tier)
        os.makedirs(tdir, exist_ok=True)
        published = {}
        min_games = MIN_GAMES_CHAR_SUMMIT if tier == "summit" else MIN_GAMES_CHAR
        for char, crows in sorted(by_char.items(), key=lambda kv: -len(kv[1])):
            if len(crows) < min_games:
                continue
            pack = build_pack(crows, tier, char)
            fn = char.replace("&", "and")
            json.dump(pack, open(os.path.join(tdir, fn + ".json"), "w"), indent=1)
            published[char] = len(crows)
        manifest["tiers"][tier] = {"chars": published,
                                   "total_rows": len(rows)}
        print(f"{tier}: {len(rows)} rows -> {len(published)} char packs "
              f"({', '.join(f'{c}:{n}' for c, n in list(published.items())[:6])}...)",
              flush=True)

    # ---- tier situation tables per matchup, from the rows' embedded events.
    # OOS uses Falco rows only (the option classifier is Falco-tuned: "shine
    # OOS"); ledge/tech/knockdown options are universal mechanics, so those
    # tables also publish per character later if wanted — for now they too
    # aggregate Falco rows so every table answers "what do <tier> Falcos do".
    # Legacy v1 OOS event files seed diamond/master vs Marth as a fallback.
    MIN_SIT_EVENTS = 300
    SITUATION_FIELDS = {"out_of_shieldstun": "oos", "ledge": "ledge",
                        "tech": "tech_opt", "knockdown": "knockdown"}
    situations = {s: {} for s in SITUATION_FIELDS}
    for tier, fn in (("diamond", "diamond_falco_marth_events.json"),
                     ("master", "master_falco_marth_events.json")):
        p = os.path.join(DATA, fn)
        if os.path.exists(p):
            events = [tuple(e) for e in json.load(open(p))]
            situations["out_of_shieldstun"].setdefault(tier, {})["Marth"] = {
                "situation": "out_of_shieldstun", "matchup": "Marth",
                "tier": tier, **oos_table(events)}
    for tier, rows in tier_rows.items():
        for sit, field in SITUATION_FIELDS.items():
            per_mu, n_games_mu = {}, {}
            for r in rows:
                if r["char"] != "Falco" or not r.get(field):
                    continue
                per_mu.setdefault(r["vs"], []).extend(tuple(e) for e in r[field])
                n_games_mu[r["vs"]] = n_games_mu.get(r["vs"], 0) + 1
            for mu, evs in per_mu.items():
                if len(evs) >= MIN_SIT_EVENTS:
                    situations[sit].setdefault(tier, {})[mu] = {
                        "situation": sit, "matchup": mu, "tier": tier,
                        "n_games": n_games_mu[mu], **oos_table(evs)}
    situations = {s: t for s, t in situations.items() if t}
    if situations:
        json.dump(situations, open(os.path.join(args.out, "situations.json"), "w"),
                  indent=1)
        for sit, tiers in situations.items():
            for tier, mus in tiers.items():
                print(f"situations/{sit}/{tier}: vs {len(mus)} matchups", flush=True)

    json.dump(manifest, open(os.path.join(args.out, "manifest.json"), "w"), indent=1)
    print("PACKS BUILT ->", args.out, flush=True)


if __name__ == "__main__":
    main()
