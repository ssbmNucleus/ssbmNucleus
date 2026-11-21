"""Frame analyzer — per-player frame-derived stats (vendored analyzer_v2).

VENDORED COPY of <monorepo>/tools/rank-baselines/analyzer_v2.py so the app can deep-mine the
user's own replays in place. Keep the two in sync (this file is a straight
copy plus this header), and bump ANALYZER_VERSION in deep_stats.py on any
stat-definition change so already-mined rows re-mine lazily. Requires
peppi-py (requirements.txt + mex_backend.spec hiddenimports).

Character-agnostic. For every player in a 1v1 game it emits one row with:

  v1 metrics      lc_rate, wd_per_min, apm, tech_rate, openings_per_min,
                  dmg_per_conv, one_hit_pct, kill_conv_pct, avg_death_pct,
                  deaths_per_min, dmg_taken_per_min
  deaths          [{pct, cause, f, by}] — cause in {sd, tech_chase, edgeguard,
                  failed_recovery, raw}, f = frame (clip anchor), by = the
                  killing move (last_attack_landed)
  kills           the offense mirror: the opponent's deaths (how YOU close
                  stocks — kill causes, kill %, kill moves)
  stage control   center_control / corner_pct / neutral_wins_pct
  tech context    hit/miss counts split by platform vs ground and after-throw
  recovery        offstage episodes begun after being hit -> made it back or died
  charstate_frames  frames spent in each character-specific action state
                  (id >= 341) so char stats like Falco lasers can be derived
                  at aggregation time without re-mining
  oos             out-of-shieldstun events [(option, dmg_swing, died), ...]
                  (ported from response_mining.py) — situation tables for any
                  tier x matchup fall out at aggregation time
  stage, vs, won  for per-stage / per-matchup slicing

Row size ~1-2 KB; a shard of ~10k games -> ~30 MB JSONL. Raw replays are never
needed again after mining unless a NEW stat definition is added.
"""
import statistics

CHAR_NAMES = {0: "CF", 1: "DK", 2: "Fox", 3: "G&W", 4: "Kirby", 5: "Bowser",
              6: "Link", 7: "Luigi", 8: "Mario", 9: "Marth", 10: "Mewtwo",
              11: "Ness", 12: "Peach", 13: "Pikachu", 14: "ICs", 15: "Puff",
              16: "Samus", 17: "Yoshi", 18: "Zelda", 19: "Sheik", 20: "Falco",
              21: "YLink", 22: "Doc", 23: "Roy", 24: "Pichu", 25: "Ganon"}

STAGE_NAMES = {2: "FoD", 3: "PS", 8: "YS", 28: "DL", 31: "BF", 32: "FD"}
# x coordinate of the stage edge, keyed by internal stage id
STAGE_EDGE = {2: 63.35, 3: 87.75, 8: 56.0, 28: 77.27, 31: 68.4, 32: 85.57}

DAMAGE_STATES = set(range(75, 92))
TUMBLE = 38            # DamageFall
SPECIAL_FALL = 35
GRABBED = set(range(223, 233))
THROWN = set(range(239, 244))   # ThrownF..ThrownlwWomen (233-238 are escapes/rebound!)
DOWN_STATES = set(range(183, 202))
TECH_STATES = {199, 200, 201}
MISSED_TECH = set(range(183, 192))
AIRDODGE = 236
LAND_FALL_SPECIAL = 43
CHAR_STATE_MIN = 341   # character-specific action states start here

GUARD = {178, 179, 180, 182}   # shield family (on/hold/release/reflect)
SHIELDSTUN = 181
OOS_HORIZON = 180              # 3s outcome window for OOS events

# cliff states (verified against the decomp ftCommon enum)
CLIFF_HANG = {252, 253}                    # CliffCatch, CliffWait
CLIFF_GETUP = {254, 255}                   # CliffClimbSlow/Quick
CLIFF_ATTACK = {256, 257}
CLIFF_ROLL = {258, 259}
CLIFF_JUMP = {260, 261, 262, 263}
DOWN_WAIT = {184, 192}                     # DownWaitU/D
DOWN_STAND = {186, 194}
DOWN_ATTACK = {187, 195}
DOWN_ROLL = {188, 189, 196, 197}           # DownFoward/BackU+D
DOWN_DAMAGE = {185, 193}

MIN_FRAMES = 3600      # skip games under 60s

# last_attack_landed ids -> human names (slippi attack enum; unknowns fall
# back to "attackNN")
# Canonical Slippi/melee attack-kind ids. The original table here was shifted
# one down across 1-20 (2026-07-14 fix): the corpus id histogram proved it --
# "jab2" ids outnumbered "jab" 8:1 (impossible) and unmapped id 21 (canonical
# down-B, i.e. SHINE for spacies) was 13% of Falco openers. Throws/getups
# (50+) were always correct. Rows mined before this fix carry the old names;
# in-app rows re-mine via the ANALYZER_VERSION bump, shard-mined rows are
# remapped at pack build (build_packs_v2 OLD_MOVE_NAME_FIX).
ATTACK_NAMES = {1: "misc", 2: "jab", 3: "jab2", 4: "jab3", 5: "rapid jabs",
                6: "dash attack", 7: "ftilt", 8: "utilt", 9: "dtilt",
                10: "fsmash", 11: "usmash", 12: "dsmash", 13: "nair",
                14: "fair", 15: "bair", 16: "uair", 17: "dair",
                18: "neutral-B", 19: "side-B", 20: "up-B", 21: "down-B",
                50: "getup attack", 51: "getup attack", 52: "pummel",
                53: "fthrow", 54: "bthrow", 55: "uthrow", 56: "dthrow",
                61: "ledge attack", 62: "ledge attack"}


def _classify_oos_option(state, pos_x, f, n, opp_x):
    """First meaningful action after leaving shieldstun at frame f.
    Verbatim port of response_mining.classify_option."""
    j = f
    while j < min(f + 40, n):
        s = state[j]
        if s == SHIELDSTUN:
            return None, j                      # re-stunned: multi-hit pressure
        if s in DAMAGE_STATES:
            return "hit before acting", j
        if 223 <= s <= 232:
            return "grabbed", j
        if s in (212, 214):
            return "grab OOS", j
        if s in (233, 234):
            toward = (pos_x[min(j + 20, n - 1)] - pos_x[j]) * (opp_x[j] - pos_x[j]) > 0
            return ("roll toward opp" if toward else "roll away"), j
        if s == 235:
            return "spotdodge", j
        if s == 236:
            for k in range(j, min(j + 12, n)):
                if state[k] == 43:
                    return "wavedash OOS", j
            return "airdodge OOS", j
        if s == 24:                              # kneebend: jump-cancel something
            for k in range(j + 1, min(j + 18, n)):
                sk = state[k]
                if sk >= CHAR_STATE_MIN:
                    return "shine OOS", k
                if 65 <= sk <= 70:
                    return "aerial OOS", k
                if sk == 63:
                    return "upsmash OOS", k
                if sk in DAMAGE_STATES:
                    return "hit before acting", k
            return "jump away", j
        if 44 <= s <= 64:
            return "ground attack", j
        if s not in GUARD and s != SHIELDSTUN:
            if s in (14, 15, 16, 17, 18, 19, 20, 21, 22, 23):  # wait/walk/dash/turn
                return "drop shield & move", j
            return "other", j
        j += 1
    return "held shield", min(f + 40, n - 1)


def analyze_game(fn, min_frames=MIN_FRAMES):
    """Return a list of per-player stat rows for a 1v1 game (both players)."""
    from peppi_py import read_slippi
    try:
        g = read_slippi(fn)
    except Exception:
        return []
    except BaseException as e:
        # corrupt/ancient .slp files can make peppi PANIC (pyo3
        # PanicException derives from BaseException, so a bare
        # `except Exception` misses it and kills the calling thread);
        # pyo3_runtime is not importable, so match it by name
        if type(e).__name__ != "PanicException":
            raise
        return []
    players = g.start.players
    if len(players) != 2:
        return []
    ports = g.frames.ports
    n = min(len(p.leader.post.state) for p in ports)
    if n < min_frames:
        return []
    # slp < 2.0.0 (2018-era) records no airborne / l_cancel; peppi hands back
    # None for them and the stats below index those arrays
    if any(getattr(p.leader.post, "airborne", None) is None
           or getattr(p.leader.post, "l_cancel", None) is None
           for p in ports):
        return []
    stage = g.start.stage
    edge_x = STAGE_EDGE.get(stage, 70.0)

    # ranked-dataset replays are anonymized but stamp each player's RANK into
    # the netplay name ("Master Player" / "Platinum Player") — recording it
    # makes rows self-describing and lets cross-tier games be attributed
    # exactly (the higher-rank side is labeled, no inference needed)
    def rank_of(i):
        try:
            name = (players[i].netplay.name or "").lower()
        except Exception:
            return None
        for r in ("platinum", "diamond", "master"):
            if name.startswith(r):
                return r
        return None

    data = []
    for i in range(2):
        post = ports[i].leader.post
        pre = ports[i].leader.pre
        data.append({
            "char": players[i].character,
            "state": post.state.to_pylist()[:n],
            "pct": post.percent.to_pylist()[:n],
            "stocks": post.stocks.to_pylist()[:n],
            "lcan": post.l_cancel.to_pylist()[:n],
            "buttons": pre.buttons_physical.to_pylist()[:n],
            "x": post.position.x.to_pylist()[:n],
            "y": post.position.y.to_pylist()[:n],
            "air": post.airborne.to_pylist()[:n],
            "lastatk": post.last_attack_landed.to_pylist()[:n],
        })

    def conversions_on(defender):
        """Conversions performed ON defender; also defender's self-damage."""
        d = data[defender]
        convs, cur, free, self_dmg = [], None, 0, 0.0
        for f in range(1, n):
            delta = d["pct"][f] - d["pct"][f - 1]
            in_cs = (d["state"][f] in DAMAGE_STATES or d["state"][f] in GRABBED
                     or d["state"][f] in DOWN_STATES)
            if delta > 0:
                if in_cs:
                    if cur is None:
                        cur = [f, 0.0, 0]
                    cur[1] += delta
                    cur[2] += 1
                    free = 0
                else:
                    self_dmg += delta
            if cur is not None:
                free = 0 if in_cs else free + 1
                if d["stocks"][f] < d["stocks"][f - 1]:
                    cur.append(True); convs.append(cur); cur = None; free = 0
                elif free > 45:
                    cur.append(False); convs.append(cur); cur = None
        if cur is not None:
            cur.append(False); convs.append(cur)
        return convs, self_dmg

    def last_contact_frames(i):
        """For player i: per-frame index of the most recent frame of combat
        contact — in hitstun/tumble/grabbed/thrown/downed, or taking combat
        damage. -99999 before any contact. Distinguishes 'flying from a hit /
        being chased' from genuinely untouched (SD detection)."""
        d = data[i]
        out = [-99999] * n
        last = -99999
        for f in range(1, n):
            s = d["state"][f]
            in_contact = (s in DAMAGE_STATES or s == TUMBLE or s in GRABBED
                          or s in THROWN or s in DOWN_STATES)
            if in_contact:
                last = f
            out[f] = last
        return out

    def offstage(i, f):
        d = data[i]
        return abs(d["x"][f]) > edge_x + 3 or d["y"][f] < -6

    rows = []
    for i in range(2):
        d = data[i]
        lc_hit = sum(1 for v in d["lcan"] if v == 1)
        lc_miss = sum(1 for v in d["lcan"] if v == 2)

        # --- state-transition scans: techs (with context), wavedash, char states
        techs = missed = wd = 0
        tech_ctx = {"ground_hit": 0, "ground_miss": 0, "plat_hit": 0,
                    "plat_miss": 0, "throw_hit": 0, "throw_miss": 0}
        charstate_frames = {}
        prev, since_ad, since_grab = None, 999, 99999
        for f in range(n):
            s = d["state"][f]
            if s >= CHAR_STATE_MIN:
                charstate_frames[s] = charstate_frames.get(s, 0) + 1
            if s in GRABBED or s in THROWN:
                since_grab = 0
            if s != prev:
                is_tech = s in TECH_STATES and prev not in TECH_STATES
                is_miss = s in MISSED_TECH and prev not in MISSED_TECH
                if is_tech or is_miss:
                    kind = "hit" if is_tech else "miss"
                    if is_tech:
                        techs += 1
                    else:
                        missed += 1
                    on_plat = d["y"][f] > 5
                    tech_ctx[("plat_" if on_plat else "ground_") + kind] += 1
                    if since_grab < 90:
                        tech_ctx["throw_" + kind] += 1
                if s == AIRDODGE:
                    since_ad = 0
                if s == LAND_FALL_SPECIAL and since_ad <= 10:
                    wd += 1
                prev = s
            since_ad += 1
            since_grab += 1

        my_convs, _ = conversions_on(1 - i)
        taken, self_dmg = conversions_on(i)
        contact = last_contact_frames(i)

        # --- one pass: recovery attempts + death classification.
        # Death causes hinge on WHERE the last damaging hit landed and how
        # long before death it was:
        #   sd              no hit within 240f of death (untouched suicide)
        #   tech_chase      was in missed-tech/down states within 120f
        #   edgeguard       last hit landed while the victim was OFFSTAGE
        #   failed_recovery died offstage >90f after an onstage-taken hit
        #                   (had time to act, never made it back — gimps,
        #                   burned/misinput recoveries)
        #   raw             killed by the knockback of an onstage-taken hit
        # Recovery attempts (separate stat) = offstage sequences after combat
        # contact where the player got to act; success = regained the stage.
        rec_episodes = rec_success = 0
        seq = acted = False
        deaths = []
        last_hit_f, last_hit_off = -99999, False
        for f in range(1, n):
            s = d["state"][f]
            off = offstage(i, f)
            in_kb = s in DAMAGE_STATES or s == TUMBLE or s in THROWN
            delta = d["pct"][f] - d["pct"][f - 1]
            if delta > 0 and (in_kb or s in GRABBED or s in DOWN_STATES):
                last_hit_f = f
                last_hit_off = offstage(i, f - 1)
            if not seq:
                if (off and d["air"][f] and d["pct"][f] > 0
                        and (in_kb or f - contact[f] < 120)):
                    seq = True
                    acted = not in_kb
            else:
                if off and not in_kb:
                    acted = True
                if not d["air"][f] and not off and s not in DOWN_STATES:
                    if acted:
                        rec_episodes += 1
                        rec_success += 1
                    seq = acted = False
            if d["stocks"][f] < d["stocks"][f - 1]:
                pct = d["pct"][f - 1]
                recent_down = any(d["state"][k] in MISSED_TECH
                                  for k in range(max(0, f - 120), f))
                if seq and acted:
                    rec_episodes += 1        # a recovery attempt that failed
                if seq:
                    # contact put them offstage — never an SD, even if the
                    # opponent finished the job without touching them again
                    if recent_down:
                        cause = "tech_chase"
                    elif last_hit_off:
                        cause = "edgeguard"
                    elif f - last_hit_f > 90:
                        cause = "failed_recovery"
                    else:
                        cause = "raw"
                elif f - last_hit_f > 240:
                    cause = "sd"
                elif recent_down:
                    cause = "tech_chase"
                else:
                    cause = "raw"
                death = {"pct": round(pct, 1), "cause": cause, "f": f}
                if cause != "sd":
                    move_id = data[1 - i]["lastatk"][f - 1]
                    death["by"] = ATTACK_NAMES.get(move_id, f"attack{move_id}")
                deaths.append(death)
                seq = acted = False

        def _swing_outcome(act_f):
            """(damage swing, died) over the standard 3s horizon from act_f."""
            end = min(act_f + OOS_HORIZON, n - 1)
            swing = ((data[1 - i]["pct"][end] - data[1 - i]["pct"][act_f])
                     - (d["pct"][end] - d["pct"][act_f]))
            died = d["stocks"][end] < d["stocks"][act_f]
            return (-150.0 if died else round(swing, 1)), died

        def _toward(j):
            k = min(j + 20, n - 1)
            opp_x = data[1 - i]["x"][j]
            return (d["x"][k] - d["x"][j]) * (opp_x - d["x"][j]) > 0

        # --- ledge option events: what happens out of CliffWait
        ledge_events = []
        f = 1
        while f < n - OOS_HORIZON:
            if d["state"][f] in CLIFF_HANG and d["state"][f - 1] not in CLIFF_HANG:
                j = f
                while j < n - OOS_HORIZON and d["state"][j] in CLIFF_HANG:
                    j += 1
                s = d["state"][j]
                if s in CLIFF_GETUP:
                    opt = "ledge getup"
                elif s in CLIFF_ATTACK:
                    opt = "ledge attack"
                elif s in CLIFF_ROLL:
                    opt = "ledge roll"
                elif s in CLIFF_JUMP:
                    opt = "ledge jump"
                elif s in DAMAGE_STATES or s == TUMBLE:
                    opt = "hit on ledge"
                else:
                    # dropped from the ledge: refine by the next action
                    opt = "ledge drop"
                    for k in range(j, min(j + 25, n)):
                        sk = d["state"][k]
                        if sk == AIRDODGE:
                            opt = "ledgedash attempt"
                            break
                        if 65 <= sk <= 70:
                            opt = "ledge drop aerial"
                            break
                        if sk in DAMAGE_STATES:
                            opt = "hit on ledge"
                            break
                swing, died = _swing_outcome(j)
                ledge_events.append((opt, swing, died))
                f = j
            f += 1

        # --- tech decision + knockdown follow-up events
        tech_events = []
        knockdown_events = []
        f = 1
        while f < n - OOS_HORIZON:
            s = d["state"][f]
            prev_s = d["state"][f - 1]
            if s in TECH_STATES and prev_s not in TECH_STATES:
                if s == 199:
                    opt = "tech in place"
                else:
                    opt = "tech roll toward" if _toward(f) else "tech roll away"
                swing, died = _swing_outcome(f)
                tech_events.append((opt, swing, died))
            elif s in MISSED_TECH and prev_s not in MISSED_TECH:
                swing, died = _swing_outcome(f)
                tech_events.append(("missed tech", swing, died))
                # follow-up: first choice made from the ground
                j = f
                opt = None
                while j < n - OOS_HORIZON and j < f + 300:
                    sj = d["state"][j]
                    if sj in DOWN_STAND:
                        opt = "getup"
                    elif sj in DOWN_ATTACK:
                        opt = "getup attack"
                    elif sj in DOWN_ROLL:
                        opt = "roll toward" if _toward(j) else "roll away"
                    elif sj in DOWN_DAMAGE:
                        opt = "hit on ground"
                    elif sj in DOWN_WAIT and j - f > 90:
                        opt = "stay down"
                    if opt:
                        break
                    j += 1
                if opt:
                    swing, died = _swing_outcome(j)
                    knockdown_events.append((opt, swing, died))
                f = j
            f += 1

        # --- out-of-shieldstun events (situation mining, response_mining port)
        opp = data[1 - i]
        oos_events = []
        f = 1
        while f < n - OOS_HORIZON:
            if d["state"][f] == SHIELDSTUN and d["state"][f - 1] != SHIELDSTUN:
                e = f
                while e < n - OOS_HORIZON and d["state"][e] == SHIELDSTUN:
                    e += 1
                opt, act_f = _classify_oos_option(d["state"], d["x"], e, n, opp["x"])
                if opt is not None:
                    end = min(act_f + OOS_HORIZON, n - 1)
                    swing = ((opp["pct"][end] - opp["pct"][act_f])
                             - (d["pct"][end] - d["pct"][act_f]))
                    died = d["stocks"][end] < d["stocks"][act_f]
                    if died:
                        swing = -150
                    oos_events.append((opt, round(swing, 1), died))
                f = e
            f += 1

        presses = sum(1 for f in range(1, n)
                      if d["buttons"][f] != d["buttons"][f - 1] and d["buttons"][f])
        minutes = n / 3600.0
        kills = sum(1 for c in my_convs if c[3])
        death_pcts = [dd["pct"] for dd in deaths]

        # --- stage control: position is the fundamental resource. 0..1
        # distance-from-center normalized by the edge; cornered = outer 25%.
        rel = [min(abs(x) / edge_x, 1.5) for x in d["x"]]
        center_control = round(100.0 * (1 - min(sum(rel) / n, 1.0)), 1)
        corner_pct = round(100.0 * sum(1 for r in rel if r > 0.75) / n, 1)
        # neutral win share: my openings vs openings taken
        total_open = len(my_convs) + len(taken)
        neutral_wins_pct = round(100.0 * len(my_convs) / total_open, 1) \
            if total_open else None

        # true 1-based slippi port (peppi Port enum is 0-based; the ports
        # array only holds OCCUPIED ports, so index != port number)
        try:
            slp_port = int(players[i].port) + 1
        except (TypeError, ValueError):
            slp_port = getattr(players[i].port, "value", i) + 1
        rows.append({
            "file": fn.replace("\\", "/").rsplit("/", 1)[-1],
            "port": i,
            "slp_port": slp_port,
            "rank": rank_of(i),
            "vs_rank": rank_of(1 - i),
            "char": CHAR_NAMES.get(d["char"], f"ext{d['char']}"),
            "vs": CHAR_NAMES.get(data[1 - i]["char"], f"ext{data[1 - i]['char']}"),
            "stage": STAGE_NAMES.get(stage, f"st{stage}"),
            "minutes": round(minutes, 2),
            "won": d["stocks"][n - 1] > data[1 - i]["stocks"][n - 1],
            "lc_rate": round(100.0 * lc_hit / (lc_hit + lc_miss), 2) if lc_hit + lc_miss else None,
            "lc_n": lc_hit + lc_miss,
            "wd_per_min": round(wd / minutes, 2),
            "apm": round(presses / minutes, 1),
            "tech_rate": round(100.0 * techs / (techs + missed), 2) if techs + missed else None,
            "openings_per_min": round(len(my_convs) / minutes, 2),
            "dmg_per_conv": round(sum(c[1] for c in my_convs) / len(my_convs), 2) if my_convs else None,
            "one_hit_pct": round(100.0 * sum(1 for c in my_convs if c[2] == 1) / len(my_convs), 2) if my_convs else None,
            "kill_conv_pct": round(100.0 * kills / len(my_convs), 2) if my_convs else None,
            "avg_death_pct": round(statistics.mean(death_pcts), 1) if death_pcts else None,
            "deaths_per_min": round(len(deaths) / minutes, 2),
            "dmg_taken_per_min": round(sum(c[1] for c in taken) / minutes, 1),
            "center_control": center_control,
            "corner_pct": corner_pct,
            "neutral_wins_pct": neutral_wins_pct,
            "deaths": deaths,
            "tech_ctx": tech_ctx,
            "recovery": {"episodes": rec_episodes, "success": rec_success},
            "charstate_frames": charstate_frames,
            "oos": oos_events,
            "ledge": ledge_events,
            "tech_opt": tech_events,
            "knockdown": knockdown_events,
        })

    # the offense mirror: my kills = the opponent's deaths (same taxonomy, so
    # packs get "how do you CLOSE stocks" — kill causes, kill %, kill moves)
    if len(rows) == 2:
        rows[0]["kills"] = rows[1]["deaths"]
        rows[1]["kills"] = rows[0]["deaths"]
    return rows


if __name__ == "__main__":
    import sys, json
    for r in analyze_game(sys.argv[1]):
        print(json.dumps(r, indent=1))
