"""Response mining: when my shield gets hit (shieldstun), what option do I pick
out of shield, and what's the outcome? Situation-conditioned option/outcome table."""
import sys, os, json, statistics, collections
from concurrent.futures import ProcessPoolExecutor

# the corpus lives at the repo root, one level up from this package
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")

GUARD = {178, 179, 180, 182}      # shield family (on/hold/release/reflect)
SHIELDSTUN = 181
DAMAGE_STATES = set(range(75, 92))
HORIZON = 180                      # 3s outcome window

def classify_option(state, pos_x, f, n, opp_x):
    """First meaningful action after leaving shieldstun at frame f."""
    j = f
    while j < min(f + 40, n):
        s = state[j]
        if s == SHIELDSTUN:
            return None, j                      # re-stunned: multi-hit pressure, skip
        if s in DAMAGE_STATES:
            return "hit before acting", j
        if 223 <= s <= 232:
            return "grabbed", j
        if s in (212, 214):
            return "grab OOS", j
        if s in (233, 234):
            toward = (pos_x[min(j+20, n-1)] - pos_x[j]) * (opp_x[j] - pos_x[j]) > 0
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
                if sk >= 341: return "shine OOS", k
                if 65 <= sk <= 70: return "aerial OOS", k
                if sk == 63: return "upsmash OOS", k
                if sk in DAMAGE_STATES: return "hit before acting", k
            return "jump away", j
        if 44 <= s <= 64:
            return "ground attack", j
        if s not in GUARD and s != SHIELDSTUN:
            if s in (14, 15, 16, 17, 18, 19, 20, 21, 22, 23):  # wait/walk/dash/turn
                return "drop shield & move", j
            return "other", j
        j += 1
    return "held shield", min(f + 40, n - 1)

def mine_game(args):
    fn, my_port = args
    from peppi_py import read_slippi
    try:
        g = read_slippi(fn)
    except Exception:
        return []
    if len(g.start.players) != 2:
        return []
    me, opp = g.frames.ports[my_port], g.frames.ports[1 - my_port]
    n = min(len(me.leader.post.state), len(opp.leader.post.state))
    st = me.leader.post.state.to_pylist()[:n]
    mypct = me.leader.post.percent.to_pylist()[:n]
    mystk = me.leader.post.stocks.to_pylist()[:n]
    opct = opp.leader.post.percent.to_pylist()[:n]
    mypos = me.leader.post.position.x.to_pylist()[:n]
    opos = opp.leader.post.position.x.to_pylist()[:n]

    events = []
    f = 1
    while f < n - HORIZON:
        if st[f] == SHIELDSTUN and st[f-1] != SHIELDSTUN:
            # find end of this stun
            e = f
            while e < n - HORIZON and st[e] == SHIELDSTUN:
                e += 1
            opt, act_f = classify_option(st, mypos, e, n, opos)
            if opt is not None:
                end = min(act_f + HORIZON, n - 1)
                swing = (opct[end] - opct[act_f]) - (mypct[end] - mypct[act_f])
                died = mystk[end] < mystk[act_f]
                if died: swing = -150
                events.append((opt, swing, died))
            f = e
        f += 1
    return events

def report(events, label):
    by = collections.defaultdict(list)
    for opt, swing, died in events:
        by[opt].append((swing, died))
    print(f"\n=== {label}: {len(events)} shield-hit situations ===")
    print(f"{'option':22s} {'freq':>6s} {'avg swing':>10s} {'death%':>7s}")
    for opt, rows in sorted(by.items(), key=lambda kv: -len(kv[1])):
        n = len(rows)
        swings = [r[0] for r in rows]
        deaths = sum(1 for r in rows if r[1])
        print(f"{opt:22s} {100.0*n/len(events):5.1f}% {statistics.mean(swings):+9.1f}% {100.0*deaths/n:6.1f}%")

if __name__ == "__main__":
    # my falco-vs-marth games from corpus index
    ME = os.environ.get("MINE_CONNECT_CODE", "ABCD#123")  # your own connect code
    jobs = []
    for line in open(os.path.join(DATA, "corpus_index.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        if "error" in r or (r.get("frames") or 0) < 3600: continue
        memb = next((p for p in r["players"] if p["code"] == ME), None)
        oppp = next((p for p in r["players"] if p["code"] != ME), None)
        if memb and oppp and "22" in memb["chars"] and oppp["chars"] == ["18"]:
            jobs.append((r["file"], memb["port"]))
    print(f"my Falco vs Marth games: {len(jobs)}")

    with ProcessPoolExecutor(max_workers=8) as ex:
        mine = [e for evs in ex.map(mine_game, jobs, chunksize=4) for e in evs]
    report(mine, "MY FALCO vs Marth — out-of-shieldstun options")

    # summit falcos vs marth (any 2p game w/ falco; use falco port)
    summit = json.load(open(os.path.join(DATA, "summit11_falco.json")))
    XMARTH, XFALCO = 9, 20
    pjobs = []
    for gm in summit:
        if len(gm["players"]) != 2: continue
        chars = {p[0]: p[1] for p in gm["players"]}
        ports = sorted(chars)
        if sorted(chars.values()) == ["Falco", "Marth"]:
            fport = [p for p in ports if chars[p] == "Falco"][0]
            pjobs.append((gm["file"], ports.index(fport)))
    with ProcessPoolExecutor(max_workers=8) as ex:
        pro = [e for evs in ex.map(mine_game, pjobs, chunksize=2) for e in evs]
    report(pro, f"SUMMIT FALCOS vs Marth ({len(pjobs)} games)")
