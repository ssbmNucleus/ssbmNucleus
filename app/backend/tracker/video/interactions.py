"""Interaction IR + single-game detectors — the deep layer of Randall's tools.

The corpus/aggregate tools answer "across all your games ..."; this layer answers
"in THIS one game, what actually happened, interaction by interaction?" It is also
the spine for user drag-drop analysis (analyze one dropped .slp) and, later, the
two-replay decision-fork compare.

Everything a detector finds is one **Interaction**: a single versioned event shape
so a downstream tool (or a future edgeguard / tech-chase / shield-pressure detector)
consumes the same fields no matter what produced them. Detectors read a cached
``GameTrace`` (see game_trace.py) — nobody re-parses the replay.

Three rules this module exists to enforce:

1. Time is seekable. Every Interaction carries the canonical ``TimeCoord`` (elapsed
   string a human reads *and* the raw ``slippi_frame`` a clip seeks to), so a
   timeline timestamp lines up with the frame ``queue_clips`` jumps to — closing the
   latent bug where a stamp was array-index/60, off by the ~123-frame Ready/GO
   countdown.

2. Openings don't merge silently. A conversion breaks the moment the defender turns
   it around on the attacker (a reversal). Without that, two separate neutral
   openings 45 frames apart fuse into one fake mega-conversion and poison damage
   totals, kill attribution, and opener counts at once — the single most dangerous
   confidently-wrong failure for this layer (flagged by the second-opinion review).

3. One game is one game. ``claim_scope`` stamps every deep result with how far the
   evidence licenses Randall to generalize. A single game may describe what happened
   (even "this happened repeatedly THIS game"); it may NOT license "usually / tends
   to / habit / leak / always" — that needs the corpus tools, not one game.
"""
from ..stats.analyzer import (ATTACK_NAMES, DAMAGE_STATES, DOWN_STATES, GRABBED,
                       STAGE_EDGE, THROWN, TUMBLE)

# Bump when the Interaction shape changes in a way a consumer must notice.
IR_VERSION = 1
_DETECTOR = {"name": "conversions", "version": 1}

# frames a defender must be free of any captured state before we call a
# conversion over on a timeout (matches analyzer.conversions_on's threshold).
_FREE_CLOSE = 45


def _is_captured(state):
    """Defender is under combat control this frame — the string a conversion
    lives inside. Includes THROWN/TUMBLE so throws and juggles don't survive only
    by accident through the timeout grace window."""
    return (state in DAMAGE_STATES or state in GRABBED or state in THROWN
            or state in DOWN_STATES or state == TUMBLE)


def _position(trace, port, i, edge_x):
    d = trace.data[port]
    return ("offstage" if abs(d["x"][i]) > edge_x + 3 or d["y"][i] < -6
            else "onstage")


def _classify_opener(trace, actor, target, start_i):
    """Contact type that OPENED this conversion — the honest neutral signal.

    Deliberately NOT the mislabelled corpus "neutral_wins_pct" (really a
    conversion share). We only claim what the frame evidence supports:
      grab   defender is grabbed/thrown at contact                 -> detected
      trade  defender AND attacker both take damage the SAME frame -> inferred
      hit    a clean opening hit                                   -> detected
    Same-frame is deliberately tight: a wider window turns every scramble into a
    "trade" (second-opinion note). start_i is always >= 1 (scan skips the countdown).
    """
    dstate = trace.data[target]["state"][start_i]
    if dstate in GRABBED or dstate in THROWN:
        return "grab", "detected"
    if dstate in DAMAGE_STATES or dstate == TUMBLE:
        a = trace.data[actor]
        both = a["pct"][start_i] - a["pct"][start_i - 1] > 0
        return ("trade", "inferred") if both else ("hit", "detected")
    if dstate in DOWN_STATES:
        return "knockdown_followup", "inferred"
    return "hit", "inferred"


def _make_interaction(trace, kind, actor, target, start_i, active_end_i,
                      evidence, certainty):
    """Assemble one Interaction. start_frame/end_frame span the ACTIVE window
    (opening contact -> last contact) and are the *seekable* Slippi frames —
    hand them straight to queue_clips and the clip lands on the real moment, not
    on dead air after a timeout. The human ``elapsed_str`` is derived from the
    same TimeCoord, so the two never disagree."""
    start = trace.at(start_i)
    # Inside a rollback resimulation the stored frame ids rewind, so the
    # last row is not always the latest frame; end on the latest one.
    end = max((trace.at(i) for i in range(start_i, active_end_i + 1)),
              key=lambda t: t.slippi_frame)
    return {
        "id": f"{kind}-p{actor}-{start.slippi_frame}",
        "kind": kind,
        "ir_version": IR_VERSION,
        "detector": _DETECTOR,
        "roles": {"actor_port": actor, "target_port": target},
        "start": start.as_dict(),
        "end": end.as_dict(),
        "start_frame": start.slippi_frame,   # derived from start (single source)
        "end_frame": end.slippi_frame,
        "evidence": evidence,
        "certainty": certainty,   # "detected" (measured) | "inferred" (heuristic)
    }


def detect_conversions(trace, actor_port):
    """Every conversion ``actor_port`` performed ON the other port, as Interactions.

    A conversion is one continuous string of damage dealt while the target is in a
    captured state (hitstun / grabbed / thrown / tumble / knocked-down). It closes
    on the first of:
      stock_drop  target dies                          -> killed
      reversal    target damages/grabs the actor back  -> two openings, not one
      timeout     target free for _FREE_CLOSE frames    -> ends at LAST contact
      game_end    trace ends mid-conversion             -> truncated
    Ported from analyzer.conversions_on (frame-by-frame percent deltas), hardened
    per the second-opinion review with reversal breaks, active-vs-close separation,
    and honest opener/termination tagging.
    """
    target = 1 - actor_port
    d = trace.data[target]
    atk = trace.data[actor_port]
    edge_x = STAGE_EDGE.get(trace.stage, 70.0)
    n = trace.n
    start_scan = max(1, trace.index_of_frame(0))   # skip the -123..-1 countdown

    def actor_reversed(f):
        """Target turned it around on the actor this frame (new damage on the
        actor, or the actor got grabbed)."""
        return (atk["pct"][f] - atk["pct"][f - 1] > 0) or atk["state"][f] in GRABBED

    out = []
    cur = None          # {"start", "dmg", "hits", "last"}
    free = 0

    def _emit(interaction):
        if interaction is not None:
            out.append(interaction)

    def close(active_end_i, termination):
        # Damage while the actor never landed an attack (last_attack_landed stays
        # 0 the whole window) isn't a conversion — it's a stage hazard (Corneria
        # Arwings, Onett cars, ...) or self-damage that the percent-delta scan
        # would otherwise credit to the actor as a bogus combo.
        if not cur.get("actor_hit"):
            return None
        opener, opener_cert = _classify_opener(trace, actor_port, target, cur["start"])
        killed = termination == "stock_drop"
        ev = {
            "damage": round(cur["dmg"], 1),
            "hits": cur["hits"],
            "killed": killed,
            "opener": opener,
            "termination": termination,
            "position": _position(trace, target, cur["start"], edge_x),
            # the actual move sequence of the combo — each {move, dmg, frame}
            "moves": cur["moves"],
            "move_chain": " → ".join(m["move"] for m in cur["moves"]),
        }
        if killed:
            # finishing move from the LAST contact, not the death frame
            # (last_attack_landed can reset by the time the stock ticks down)
            mid = atk["lastatk"][cur["last"]]
            ev["kill_move"] = ATTACK_NAMES.get(mid, f"attack{mid}")
        flags = []
        if termination == "game_end":
            flags.append("truncated")
        if opener_cert == "inferred":
            flags.append("opener_inferred")
        if ev["hits"] == 1 and not killed:
            flags.append("single_hit")     # a lone neutral poke, not a combo
        ev["quality_flags"] = flags
        certainty = "inferred" if opener_cert == "inferred" or termination == "reversal" \
            else "detected"
        return _make_interaction(trace, "conversion", actor_port, target,
                                 cur["start"], active_end_i, ev, certainty)

    for f in range(start_scan, n):
        ddelta = d["pct"][f] - d["pct"][f - 1]
        in_cs = _is_captured(d["state"][f])
        if ddelta > 0 and in_cs:
            if cur is None:
                cur = {"start": f, "dmg": 0.0, "hits": 0, "last": f, "moves": [],
                       "actor_hit": False}
            cur["dmg"] += ddelta
            cur["hits"] += 1
            cur["last"] = f
            # did the ACTOR actually land an attack this frame? (vs hazard damage)
            if atk["lastatk"][f]:
                cur["actor_hit"] = True
            # which move dealt this hit (last_attack_landed on the actor). Group
            # consecutive same-move hits (rapid jabs / multi-hit) into one entry.
            mv = ATTACK_NAMES.get(atk["lastatk"][f])
            if mv and mv != "misc":
                if cur["moves"] and cur["moves"][-1]["move"] == mv:
                    cur["moves"][-1]["dmg"] = round(cur["moves"][-1]["dmg"] + ddelta, 1)
                else:
                    cur["moves"].append({"move": mv, "dmg": round(ddelta, 1),
                                         "frame": trace.at(f).slippi_frame})
            free = 0
        if cur is not None:
            if d["stocks"][f] < d["stocks"][f - 1]:
                _emit(close(f, "stock_drop")); cur, free = None, 0
                continue
            if in_cs:
                cur["last"] = f
                free = 0
            else:
                free += 1
                if actor_reversed(f):
                    _emit(close(cur["last"], "reversal")); cur, free = None, 0
                    continue
                if free > _FREE_CLOSE:
                    _emit(close(cur["last"], "timeout")); cur, free = None, 0
                    continue
    if cur is not None:
        _emit(close(cur["last"], "game_end"))
    return out


# --- claim scope ------------------------------------------------------------
# Every deep result carries this so Randall knows how far ONE game lets him go.
# NOTE: this is guidance IN the payload, not enforcement. A hard guardrail (a
# post-generation lint that rejects "usually/habit/tends to" when games==1) is
# the stronger lever and is tracked as a follow-up; see docs.
_BANNED_LANGUAGE = ["usually", "tends to", "tendency", "habit", "leak",
                    "always", "every time", "often", "generally", "consistently"]


def claim_scope(opportunities, certainty_counts):
    """The generalization envelope for a single-game result.

    Ladder by within-game sample size: any occurrence is a game_observation; >=3
    rises to within_game_repetition ("this happened repeatedly THIS game"). Nothing
    here ever reaches a cross-game tendency — that needs the corpus tools. The
    ceiling is named for repetition, not "pattern", so it can't be read as a trait.
    """
    if opportunities >= 3:
        ceiling = "within_game_repetition"
    elif opportunities >= 1:
        ceiling = "game_observation"
    else:
        ceiling = "none"
    return {
        "claim_scope": "single_game",
        "games": 1,
        "events": opportunities,
        "opportunities": opportunities,
        "detector_certainty": certainty_counts,
        "allowed_language": {
            "ceiling": ceiling,
            "ok": (["in this game", "this game", "repeatedly this game (Nx)"]
                   if opportunities >= 3 else ["in this game", "once this game"]),
            "banned": _BANNED_LANGUAGE,
            "note": ("Single game (games=1). Describe what happened THIS game, "
                     "with exact counts ('this happened 3 times this game'); at "
                     ">=3 you may flag it as a candidate to CHECK across the "
                     "corpus — but never state it as a cross-game habit/leak/"
                     "tendency, even hedged."),
        },
    }


def certainty_mix(interactions):
    """Count detected vs inferred across a list of Interactions."""
    counts = {"detected": 0, "inferred": 0}
    for it in interactions:
        counts[it["certainty"]] = counts.get(it["certainty"], 0) + 1
    return counts
