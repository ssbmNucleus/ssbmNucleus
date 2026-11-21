"""GameTrace — parse one .slp ONCE into a cached, queryable frame trace.

Every deep single-game coach tool (the interaction/moment/positioning queries,
and dropped-replay analysis) reads a GameTrace instead of calling read_slippi
itself, so a multi-tool coaching turn parses each replay a single time. This is
the shared spine the second-opinion review asked for: detectors and summaries
consume a trace; nobody re-parses.

Canonical time (fixes a real latent bug): Slippi frames start at -123 — the
Ready/GO countdown — so array index 0 is NOT elapsed second 0. review_game
timestamps its timeline off the raw array index while queue_clips/combos seek
by Slippi frame, so a time Randall reads out today does not line up with the
frame a clip jumps to. A GameTrace maps every array index to all three bases
through one place:

    slippi_frame   raw Slippi frame stored at the row (frame_ids[index]; just
                   start_frame + index without rollback); the clip/combo basis
    elapsed        seconds since GO (max(0, slippi_frame) / 60) -> "2:31.6"
    countdown      match clock, only when the match length is known

Anything that emits a timestamp to Randall should carry .at(index) so the
number he says equals the frame we can seek.
"""
import os
import threading

# Slippi's first recorded frame (start of the Ready/GO countdown). Gameplay
# ("GO", players gain control) is frame 0. Used as a fallback when peppi does
# not hand us explicit frame ids.
DEFAULT_START_FRAME = -123

# extra per-frame fields beyond the analyzer's set — cheap to load, and they
# unlock the honest neutral/spacing/DI detectors later (facing + stick). Loaded
# defensively: a peppi build without one just omits it rather than breaking.
_OPTIONAL_FIELDS = (
    ("dir", lambda pre, post: post.direction),        # facing, -1 / +1
    ("joy_x", lambda pre, post: pre.joystick.x),      # main stick (DI/SDI)
    ("joy_y", lambda pre, post: pre.joystick.y),
    ("cstick_x", lambda pre, post: pre.cstick.x),
    ("cstick_y", lambda pre, post: pre.cstick.y),
    # INTERNAL character id, per frame — this is what makes the trace aware of
    # Zelda<->Sheik transforms: post.character follows the CURRENT form (Sheik=7,
    # Zelda=19 internal), unlike start.players.character which is the CSS pick.
    # It is ALSO the key the character renderer's animation maps are indexed by.
    ("form", lambda pre, post: post.character),
    # frames elapsed in the current action state = the animation frame index the
    # 2D character renderer plays (slippilab's actionStateFrameCounter).
    ("state_age", lambda pre, post: post.state_age),
    ("shield", lambda pre, post: post.shield),        # shield strength 0..60
    # logical trigger 0..1 = the game's processed press depth (input.x650),
    # which sizes the shield bubble (lightshield). Z-held light shields and
    # digital full-clicks both land in this value.
    ("trigger", lambda pre, post: pre.triggers),
)

# internal character ids for the one transforming pair
_INT_SHEIK, _INT_ZELDA = 7, 19


def _tolist(arr, n):
    return arr.to_pylist()[:n]


class TimeCoord:
    """One canonical timestamp in every basis a caller might need."""
    __slots__ = ("slippi_frame", "elapsed", "index")

    def __init__(self, index, start_frame, slippi_frame=None):
        self.index = index
        # the frame id actually stored at this row when known (rollback
        # re-emissions make it differ from start_frame + index)
        self.slippi_frame = (start_frame + index if slippi_frame is None
                             else slippi_frame)
        self.elapsed = max(0, self.slippi_frame) / 60.0

    @staticmethod
    def fmt_elapsed(seconds):
        # round to tenths BEFORE splitting off the minutes, or 59.95s renders
        # as "0:60.0" instead of rolling over to "1:00.0"
        seconds = round(max(0.0, seconds), 1)
        m = int(seconds) // 60
        s = seconds - 60 * m
        return f"{m}:{s:04.1f}"

    def as_dict(self, match_frames=None):
        out = {"slippi_frame": self.slippi_frame,
               "elapsed": round(self.elapsed, 1),
               "elapsed_str": self.fmt_elapsed(self.elapsed)}
        if match_frames:
            remaining = max(0, (match_frames - max(0, self.slippi_frame)) / 60.0)
            out["countdown_str"] = self.fmt_elapsed(remaining)
        return out


class GameTrace:
    """Parsed, per-port frame arrays for one 1v1 game + canonical time.

    Ports are indexed 0/1 in array order (same as analyze_game's `port`). Each
    port dict carries the analyzer's frame arrays (state/pct/stocks/lcan/
    buttons/x/y/air/lastatk) plus optional facing + stick when peppi exposes
    them. `n` is the truncated common frame count.
    """

    def __init__(self, path, game):
        self.path = path
        start = game.start
        self.stage = start.stage
        self.players = start.players
        self.is_teams = bool(getattr(start, "is_teams", False))
        ports = game.frames.ports
        self.n = min(len(p.leader.post.state) for p in ports)

        # explicit frame ids when peppi provides them; else the -123 fallback.
        # The FULL id array is kept: rollback netplay RE-EMITS corrected frames
        # as extra rows, so array index != (frame - start_frame) — anything
        # aligning raw-stream data (items, stage events) to these arrays must
        # map through frame_ids, or its timing drifts by the number of
        # re-emissions so far (measured up to ~18s late-game).
        self.start_frame = DEFAULT_START_FRAME
        self.frame_ids = None
        try:
            ids = game.frames.id.to_pylist()
            if ids:
                self.start_frame = int(ids[0])
                self.frame_ids = [int(v) for v in ids]
        except Exception:
            pass

        self.data = []
        for i in range(len(ports)):
            post = ports[i].leader.post
            pre = ports[i].leader.pre
            n = self.n
            d = {
                "char": self.players[i].character,
                "team": getattr(self.players[i], "team", None),
                "state": _tolist(post.state, n),
                "pct": _tolist(post.percent, n),
                "stocks": _tolist(post.stocks, n),
                "lcan": _tolist(post.l_cancel, n),
                "buttons": _tolist(pre.buttons_physical, n),
                "x": _tolist(post.position.x, n),
                "y": _tolist(post.position.y, n),
                "air": _tolist(post.airborne, n),
                "lastatk": _tolist(post.last_attack_landed, n),
            }
            for key, getter in _OPTIONAL_FIELDS:
                try:
                    d[key] = _tolist(getter(pre, post), n)
                except Exception:
                    d[key] = None
            self.data.append(d)

        # Ice Climbers: peppi carries Nana as the port's `follower` (same array
        # shape as the leader, with NULL rows on frames where she is dead).
        # Kept OUT of self.data so every analyzer/coach tool keeps its 0/1 port
        # indexing — only the viz bundle reads these, as render-only rows.
        self.followers = []
        for i in range(len(ports)):
            fol = getattr(ports[i], "follower", None)
            if fol is None:
                continue
            post, pre = fol.post, fol.pre
            n = self.n
            d = {
                "port": i,
                "state": _tolist(post.state, n),
                "x": _tolist(post.position.x, n),
                "y": _tolist(post.position.y, n),
            }
            # render-only extras, same defensive loading as the leader's
            for key, getter in _OPTIONAL_FIELDS:
                if key not in ("dir", "form", "state_age", "shield"):
                    continue
                try:
                    d[key] = _tolist(getter(pre, post), n)
                except Exception:
                    d[key] = None
            try:
                d["air"] = _tolist(post.airborne, n)
            except Exception:
                d["air"] = None
            self.followers.append(d)

    # -- time -----------------------------------------------------------
    def at(self, index):
        """Canonical timestamp for an array index (clamped to the game).

        Reads the frame id stored at that row when peppi provided them:
        rollback re-emits corrected frames as extra rows, so start_frame +
        index runs LATE by the re-emissions so far and would not invert
        index_of_frame."""
        i = max(0, min(index, self.n - 1))
        fids = self.frame_ids
        return TimeCoord(i, self.start_frame,
                         fids[i] if fids is not None and i < len(fids) else None)

    def index_of_frame(self, slippi_frame):
        """Inverse: Slippi frame -> array index (clamped).

        Maps through frame_ids when peppi provided them: rollback re-emits
        corrected frames as extra rows, so the naive subtraction lands
        earlier and earlier as re-emissions accumulate (the items/stage-event
        alignment learned this first — viz_export maps those the same way).
        LAST occurrence wins: that is the corrected row, the one a viewer of
        the arrays visually lands on."""
        if self.frame_ids is not None:
            row_of = getattr(self, "_row_of_frame", None)
            if row_of is None:
                row_of = {fid: i for i, fid in enumerate(self.frame_ids)}
                self._row_of_frame = row_of
                self._sorted_fids = sorted(row_of)
            idx = row_of.get(slippi_frame)
            if idx is None:
                # Absent id (a padded window boundary past the last frame, or
                # inside an incomplete final resimulation): nearest existing
                # id at or below. Mixing exact and naive mapping produced
                # INVERTED windows (lo > hi) on real rollback files — the
                # fallback must stay in the same (row) coordinate system.
                import bisect
                fids = self._sorted_fids
                j = bisect.bisect_right(fids, slippi_frame) - 1
                idx = row_of[fids[j]] if j >= 0 else 0
            return max(0, min(idx, self.n - 1))
        return max(0, min(slippi_frame - self.start_frame, self.n - 1))

    # -- ports ----------------------------------------------------------
    def port_of_code(self, codes):
        """Array index (0/1) of the player whose connect code is in `codes`,
        or None. `codes` is an iterable of upper-cased connect codes."""
        wanted = {c.upper() for c in codes if c}
        for i, p in enumerate(self.players):
            try:
                code = (p.netplay.code or "").upper()
            except Exception:
                code = ""
            if code and code in wanted:
                return i
        return None

    def describe_ports(self):
        """Lightweight port cards for a drag-drop pick UI — no frame data."""
        from ..stats.analyzer import CHAR_NAMES
        out = []
        for i, p in enumerate(self.players):
            try:
                netplay = p.netplay
                code = getattr(netplay, "code", None) or None
                name = getattr(netplay, "name", None) or None
            except Exception:
                code, name = None, None
            out.append({
                "port_index": i,
                "character": self.display_char(i),
                "code": code, "tag": name})
        return out

    # -- Zelda/Sheik transform awareness -------------------------------------
    def form_series(self, i):
        """Per-frame form name ("Sheik"/"Zelda") if this port is a transforming
        Zelda/Sheik player, else None. Reads the per-frame internal character id,
        which follows the current form rather than the CSS pick."""
        f = self.data[i].get("form")
        if not f:
            return None
        s = set(f)
        if _INT_SHEIK in s and _INT_ZELDA in s:
            return ["Sheik" if c == _INT_SHEIK else
                    ("Zelda" if c == _INT_ZELDA else None) for c in f]
        return None

    def display_char(self, i):
        """Character name for a port — the dominant IN-GAME form for a
        transforming Zelda/Sheik player, else the CSS-selected character."""
        from collections import Counter
        from ..stats.analyzer import CHAR_NAMES
        forms = self.form_series(i)
        if forms:
            named = [x for x in forms if x]
            if named:
                return Counter(named).most_common(1)[0][0]
        cid = self.data[i]["char"]
        return CHAR_NAMES.get(cid, f"ext{cid}")


# ---------------------------------------------------------------------------
# Cache: parse each file once. Keyed by (abspath, mtime, size) so an edited or
# replaced file re-parses. Small LRU — a coaching turn touches 1-2 games.
# ---------------------------------------------------------------------------
_CACHE = {}
_CACHE_ORDER = []
_CACHE_MAX = 6
_CACHE_LOCK = threading.Lock()


def _cache_key(path):
    st = os.stat(path)
    return (os.path.abspath(path), int(st.st_mtime), st.st_size)


def load_trace(path):
    """Return a cached GameTrace for `path`, or None if it can't be parsed as
    a 1v1 game (corrupt, missing, or not two human ports)."""
    if not path or not os.path.exists(path):
        return None
    try:
        key = _cache_key(path)
    except OSError:
        return None
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit is not None:
            _CACHE_ORDER.remove(key)
            _CACHE_ORDER.append(key)
            return hit

    trace = _parse(path)
    if trace is None:
        return None
    with _CACHE_LOCK:
        _CACHE[key] = trace
        _CACHE_ORDER.append(key)
        while len(_CACHE_ORDER) > _CACHE_MAX:
            _CACHE.pop(_CACHE_ORDER.pop(0), None)
    return trace


def _parse(path):
    from peppi_py import read_slippi
    try:
        game = read_slippi(path)
    except Exception:
        return None
    except BaseException as e:
        # a corrupt .slp can make peppi (Rust via pyo3) PANIC, surfacing as
        # pyo3_runtime.PanicException -- BaseException-derived, and
        # pyo3_runtime is not importable, so match it by name
        if type(e).__name__ != "PanicException":
            raise
        return None
    # 1v1 for analysis; up to 4 ports so doubles/FFA can still be watched in
    # Watch Lite (the renderer just draws whoever's present).
    if not 2 <= len(game.start.players) <= 4:
        return None
    if min(len(p.leader.post.state) for p in game.frames.ports) < 1:
        return None
    # slp < 2.0.0 (2018-era) records no airborne / l_cancel; peppi hands back
    # None for them and every trace consumer indexes those arrays
    if any(getattr(p.leader.post, "airborne", None) is None
           or getattr(p.leader.post, "l_cancel", None) is None
           for p in game.frames.ports):
        return None
    return GameTrace(path, game)


if __name__ == "__main__":
    import sys
    t = load_trace(sys.argv[1])
    if t is None:
        print("could not parse")
        raise SystemExit(1)
    print(f"frames={t.n} start_frame={t.start_frame} stage={t.stage}")
    print("ports:", t.describe_ports())
    for idx in (0, t.n // 2, t.n - 1):
        print(idx, "->", t.at(idx).as_dict(match_frames=8 * 60 * 60))
