"""Pack aggregation math (vendored from <monorepo>/tools/rank-baselines/build_packs_v2.py).

Turns analyzer rows into the pack shape the coach tools and Stats panel read:
metric medians/spreads, death-cause mix + death-% distribution, tech context,
recovery, per-matchup and per-stage slices, OOS option tables. Keep in sync
with build_packs_v2.py — the bundled baseline packs and the player's own
deep-stats packs must stay the same shape.
"""
import statistics

METRICS = ["lc_rate", "wd_per_min", "apm", "tech_rate", "openings_per_min",
           "dmg_per_conv", "one_hit_pct", "kill_conv_pct", "avg_death_pct",
           "deaths_per_min", "dmg_taken_per_min",
           "center_control", "corner_pct", "neutral_wins_pct"]
DEATH_CAUSES = ["raw", "edgeguard", "failed_recovery", "tech_chase", "sd"]
MIN_GAMES_MATCHUP = 20     # own-data slices publish at lower n than baselines
MIN_GAMES_STAGE = 15


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
    """events = [(option, swing, died)] -> option table (fixture shape).
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
