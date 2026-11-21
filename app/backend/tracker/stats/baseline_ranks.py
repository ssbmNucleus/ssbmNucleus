"""Per-stat rank-mapping for the Stats "baselines" panel.

For one of the player's characters, take each of their aggregate metrics and
answer: "what rank does this value look like?" — by comparing it against the
bundled per-tier population packs (platinum / diamond / master + the summit pro
corpus, all same character).

Two honest touches on top of the raw mapping:
  * polarity is DERIVED FROM THE DATA (if master's median > platinum's, the
    metric rises with skill) — no hardcoded per-metric "higher is better".
  * every metric carries a `signal` score (how cleanly the tiers separate,
    0..1). A flat/noisy metric that doesn't track rank gets a low score so the
    UI can grey it out instead of implying "you're bronze-tier, fix this" on a
    stat that doesn't actually predict rank. This is the Stats-only, no-BS
    philosophy applied to the comparison itself.

No AI here — this is a pure stats endpoint for the Stats tab.
"""
import json
import os
import sys

from . import deep_stats

# Bundled baseline packs — inside the PyInstaller bundle in frozen builds
# (mex_backend.spec ships backend/tracker/baselines), else on disk.
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.join(sys._MEIPASS, "backend", "tracker", "baselines")
else:
    # tracker/stats/ -> the packs stay at tracker/baselines (one level up)
    BASE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "baselines")

# Skill order (low → high) of the ranked ladder, plus the summit pro corpus as
# the ceiling anchor. summit is a tiny (n~80) different population, so it is
# shown on the ladder but kept OUT of the signal/monotonicity math.
LADDER = ["platinum", "diamond", "master"]
TIER_ORDER = LADDER + ["summit"]

# key, label, unit — order is a sensible default before signal-sort.
METRIC_META = [
    ("neutral_wins_pct", "Neutral wins", "%"),
    ("openings_per_min", "Openings", "/min"),
    ("dmg_per_conv", "Dmg / conversion", ""),
    ("kill_conv_pct", "Kill conversion", "%"),
    ("one_hit_pct", "One-hit convs", "%"),
    ("lc_rate", "L-cancel", "%"),
    ("tech_rate", "Tech rate", "%"),
    ("wd_per_min", "Wavedashes", "/min"),
    ("apm", "APM", ""),
    ("center_control", "Center control", "%"),
    ("corner_pct", "Time cornered", "%"),
    ("avg_death_pct", "Avg death %", "%"),
    ("deaths_per_min", "Deaths", "/min"),
    ("dmg_taken_per_min", "Dmg taken", "/min"),
]

GLOSSARY = {
    "lc_rate": "% of L-cancellable aerial landings successfully L-cancelled",
    "wd_per_min": "wavedashes per minute",
    "apm": "physical button presses per minute",
    "tech_rate": "% of knockdowns where a tech came out (ground+platform)",
    "openings_per_min": "conversions started on the opponent per minute",
    "dmg_per_conv": "average damage dealt per conversion",
    "one_hit_pct": "% of conversions that ended after a single hit",
    "kill_conv_pct": "% of conversions that ended in a kill",
    "avg_death_pct": "average percent at which you lose a stock",
    "deaths_per_min": "stocks lost per minute",
    "dmg_taken_per_min": "damage taken per minute",
    "center_control": "% of neutral time spent controlling centre stage",
    "corner_pct": "% of neutral time spent cornered (backed up)",
    "neutral_wins_pct": "% of neutral exchanges you win",
}


def _load_pack(tier, char):
    path = os.path.join(BASE_DIR, tier, char.replace("&", "and") + ".json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _pct_in_tier(val, m):
    """Percentile (fraction below, 0..100) of `val` within a tier whose
    distribution is summarised by median/p25/p75. Piecewise-linear through the
    three knots, extrapolated on the nearest slope, clamped to [2, 98]."""
    p25, med, p75 = m.get("p25"), m.get("median"), m.get("p75")
    if p25 is None or med is None or p75 is None or p75 <= p25:
        return 50.0
    if val <= med:
        span = med - p25
        pct = 50 + (val - med) / span * 25 if span else 50
    else:
        span = p75 - med
        pct = 50 + (val - med) / span * 25 if span else 50
    return round(max(2.0, min(98.0, pct)), 0)


def _interp_pos(val, knots):
    """Map `val` to a fractional tier index given (index, median) knots sorted
    by median ascending. Clamped to [first, last] index."""
    if len(knots) == 1:
        return float(knots[0][0])
    # knots sorted by median asc; find bracketing pair
    if val <= knots[0][1]:
        return float(knots[0][0])
    if val >= knots[-1][1]:
        return float(knots[-1][0])
    for (i0, m0), (i1, m1) in zip(knots, knots[1:]):
        if m0 <= val <= m1:
            frac = 0 if m1 == m0 else (val - m0) / (m1 - m0)
            return i0 + frac * (i1 - i0)
    return float(knots[-1][0])


def _signal(ladder_metrics):
    """0..1 how cleanly the ranked ladder separates for this metric, plus the
    skill direction. `ladder_metrics` = [(tier, {median,p25,p75}), ...] in
    LADDER order. Returns (signal, direction) or (None, 0) if <2 tiers."""
    pts = [(t, m) for t, m in ladder_metrics if m and m.get("median") is not None]
    if len(pts) < 2:
        return None, 0
    lo_med = pts[0][1]["median"]
    hi_med = pts[-1][1]["median"]
    direction = 1 if hi_med >= lo_med else -1
    spread = abs(hi_med - lo_med)
    iqrs = [m["p75"] - m["p25"] for _, m in pts
            if m.get("p75") is not None and m.get("p25") is not None
            and m["p75"] > m["p25"]]
    typ_iqr = (sum(iqrs) / len(iqrs)) if iqrs else 0
    if typ_iqr <= 0:
        return 0.0, direction
    # separation across the ladder measured in within-tier IQRs; ~1 IQR = strong
    separation = min(1.0, spread / typ_iqr)
    # monotonicity: penalise medians that go the wrong way between rungs
    meds = [m["median"] for _, m in pts]
    steps = [(b - a) * direction for a, b in zip(meds, meds[1:])]
    inversions = sum(1 for s in steps if s < 0)
    mono = max(0.0, 1 - inversions / max(1, len(steps)))
    return round(separation * mono, 3), direction


def baseline_ranking(character):
    """character = external char id. Returns the panel payload, or None if the
    player has no mined deep stats for this character yet."""
    user = deep_stats.build_player_pack(character)
    if not user:
        return None
    char = user["char"]
    umetrics = user.get("metrics") or {}

    tier_packs = {t: _load_pack(t, char) for t in TIER_ORDER}
    present = [t for t in TIER_ORDER if tier_packs.get(t)]
    if len(present) < 2:
        return {"char": char, "n_games": user.get("n_games"),
                "tiers": present, "metrics": [],
                "note": "not enough tier baselines for this character"}

    out = []
    for key, label, unit in METRIC_META:
        um = umetrics.get(key)
        if not um or um.get("median") is None:
            continue
        uval = um["median"]

        tiers = []
        for t in present:
            tm = (tier_packs[t].get("metrics") or {}).get(key)
            if tm and tm.get("median") is not None:
                tiers.append({
                    "tier": t,
                    "median": tm["median"], "p25": tm.get("p25"),
                    "p75": tm.get("p75"), "n": tier_packs[t].get("n_games"),
                })
        if len(tiers) < 2:
            continue

        ladder_metrics = [(t, (tier_packs[t].get("metrics") or {}).get(key))
                          for t in LADDER if tier_packs.get(t)]
        signal, direction = _signal(ladder_metrics)

        # map the player's value onto the tier axis (by median), then read the
        # percentile inside whichever tier they land nearest.
        knots = sorted([(TIER_ORDER.index(x["tier"]), x["median"]) for x in tiers],
                       key=lambda k: k[1])
        pos = _interp_pos(uval, knots)
        nearest = min(tiers, key=lambda x: abs(TIER_ORDER.index(x["tier"]) - pos))
        pct = _pct_in_tier(uval, nearest)

        out.append({
            "key": key, "label": label, "unit": unit,
            "glossary": GLOSSARY.get(key, ""),
            "user": round(uval, 2),
            "direction": direction,
            "signal": signal,
            "mapped_tier": nearest["tier"],
            "mapped_pos": round(pos, 2),
            "percentile": pct,
            "tiers": tiers,
        })

    # strongest signal first; unknown-signal metrics sink to the bottom
    out.sort(key=lambda m: (m["signal"] is None, -(m["signal"] or 0)))
    return {"char": char, "n_games": user.get("n_games"),
            "tiers": present, "metrics": out}
