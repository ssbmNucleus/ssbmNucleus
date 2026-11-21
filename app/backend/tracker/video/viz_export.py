"""viz_export — dump one game as a compact JSON "viz bundle" (Watch Lite's input).

The deep detectors (interactions.py) decide, frame by frame, who is converting on
whom; this exporter serialises both the raw per-frame motion AND what the detector
concluded, so a viewer can play the schematic back and show whether the analysis
is right.

    python -m tracker.video.viz_export "path/to/game.slp" > bundle.json

The bundle carries canonical Slippi frames, so a frame number in it equals the
frame you'd seek to in real Dolphin.
"""
import json
import os
import sys

from ..stats.analyzer import (ATTACK_NAMES, CHAR_NAMES, CHAR_STATE_MIN, DAMAGE_STATES,
                       DOWN_STATES, GRABBED, GUARD, SHIELDSTUN, STAGE_EDGE,
                       STAGE_NAMES, THROWN, TUMBLE)
from .interactions import detect_conversions

_CLIFF = set(range(252, 264))       # CliffCatch..CliffJump

# category codes the viewer colours dots by — a small, eyeball-able vocabulary
CAT_GROUND = 0     # neutral, grounded
CAT_AIR = 1        # neutral, airborne
CAT_ATTACK = 2     # committing an attack / special
CAT_SHIELD = 3     # shielding / shieldstun
CAT_CAPTURED = 4   # in hitstun / grabbed / thrown / tumble / knocked down (LOSING)
CAT_LEDGE = 5      # on the ledge
CAT_DEAD = 6       # dead / respawning


def _category(state, airborne):
    if state <= 10:                                  # Dead* / Rebirth
        return CAT_DEAD
    if (state in DAMAGE_STATES or state in GRABBED or state in THROWN
            or state in DOWN_STATES or state == TUMBLE):
        return CAT_CAPTURED
    if state in GUARD or state == SHIELDSTUN:
        return CAT_SHIELD
    if state in _CLIFF:
        return CAT_LEDGE
    if (44 <= state <= 74) or state >= CHAR_STATE_MIN:   # ground/aerial + specials
        return CAT_ATTACK
    return CAT_AIR if airborne else CAT_GROUND


def _round1(seq):
    return [round(float(v), 1) for v in seq]


def _round2(seq):
    return [round(float(v), 2) for v in seq]


def _ints(seq):
    return [int(v) for v in seq]


def _opt(seq, default):
    """Optional per-frame field (facing/stick may be absent on old peppi)."""
    return default if seq is None else seq


def _lightshield(trig):
    """Analog press depth as ints 0..100, the game's lightshield_amount
    (ftCo_Guard): L = (trigger - 0.3) / 0.7, and a trigger that slips below
    the deadzone HOLDS the previous frame's depth rather than dropping to
    zero — so this must be computed over the full history, never a slice.
    None (no trigger data) stays None; the renderer defaults to hard press."""
    if trig is None:
        return None
    out, last = [], 0.0
    for t in trig:
        v = ((t or 0.0) - 0.3) / 0.7
        if v < 0:
            v = last
        elif v > 1:
            v = 1.0
        last = v
        out.append(round(v * 100))
    return out


# Null-tolerant variants for follower (Nana) arrays — her rows are NULL on
# frames where she is dead/absent, and that null must survive to JSON so the
# renderer knows to skip her.
def _round1n(seq):
    return [None if v is None else round(float(v), 1) for v in seq]


def _intsn(seq):
    return [None if v is None else int(v) for v in seq]


# EXTERNAL (CSS) character id -> INTERNAL character id, for the fallback when a
# peppi build doesn't expose per-frame post.character. The renderer's animation
# maps are keyed by internal id (Fox=1, Sheik=7, Zelda=19, ICs Popo=10 ...).
_EXT_TO_INT = {0: 2, 1: 3, 2: 1, 3: 24, 4: 4, 5: 5, 6: 6, 7: 17, 8: 0, 9: 18,
               10: 16, 11: 8, 12: 9, 13: 12, 14: 10, 15: 15, 16: 13, 17: 14,
               18: 19, 19: 7, 20: 22, 21: 20, 22: 21, 23: 26, 24: 23, 25: 25}


def _ext2int(ext_char_id):
    return _EXT_TO_INT.get(ext_char_id, ext_char_id)


def _team(v):
    """Team as a plain int (or None). Some peppi builds hand back a Team ENUM
    here, which json.dumps refuses — that single enum silently poisoned every
    doubles game in a vault sync."""
    if v is None:
        return None
    try:
        return int(getattr(v, "value", v))
    except (TypeError, ValueError):
        return None


def build_viz_bundle(trace, lo=None, hi=None, path=None):
    """A JSON-safe dict describing one game (or a [lo,hi] index window) for the
    viewer / clip renderer. A window keeps only that slice of frames and the
    conversions overlapping it, so an inline clip payload stays small.

    v2 adds `items` (projectile/item tracks — lasers, needles, turnips, Shy
    Guys) and `stage_state` (FoD platform heights, Stadium transformations),
    both read from the raw .slp event stream since peppi's high-level API does
    not expose them. `path` defaults to the trace's own source file; a trace
    without one (or a pre-3.0 replay with no item events) just yields a bundle
    without those sections — same shape the viewer already tolerates."""
    n_full = trace.n
    lo = 0 if lo is None else max(0, lo)
    hi = n_full - 1 if hi is None else min(n_full - 1, hi)
    n = hi - lo + 1

    def sl(a):
        return a[lo:hi + 1]

    # 1v1 or doubles/FFA — render every port present (2..4).
    PORTS = range(len(trace.data))

    # per-frame form string ("Z"/"S") for a transforming Zelda/Sheik port, else
    # None — lets the viewer relabel the HUD live as the player transforms.
    forms = []
    for i in PORTS:
        fs = trace.form_series(i)
        forms.append("".join("S" if x == "Sheik" else "Z" if x == "Zelda"
                             else "." for x in fs)[lo:hi + 1] if fs else None)

    players = []
    for i in PORTS:
        p = trace.players[i]
        try:
            code = getattr(p.netplay, "code", None) or None
            tag = getattr(p.netplay, "name", None) or None
        except Exception:
            code, tag = None, None
        cid = trace.data[i]["char"]
        players.append({
            "port_index": i,
            "char": cid,
            "char_name": trace.display_char(i),        # dominant in-game form
            "css_char": CHAR_NAMES.get(cid, f"ext{cid}"),
            "costume": getattr(p, "costume", 0) or 0,  # color-accurate stock icons
            "transforms": forms[i] is not None,
            "team": _team(trace.data[i].get("team")),  # 0/1/2 in a teams game
            "code": code, "tag": tag,
        })

    ext_int = [_ext2int(trace.data[i]["char"]) for i in PORTS]
    frames = {
        "x": [sl(_round1(trace.data[i]["x"])) for i in PORTS],
        "y": [sl(_round1(trace.data[i]["y"])) for i in PORTS],
        "pct": [sl(_round1(trace.data[i]["pct"])) for i in PORTS],
        "stk": [sl(_ints(trace.data[i]["stocks"])) for i in PORTS],
        "cat": [[_category(trace.data[i]["state"][f], trace.data[i]["air"][f])
                 for f in range(lo, hi + 1)] for i in PORTS],
        # airborne flag — lets the viewer mark the ground under grounded
        # fighters on stages with no authored geometry (scrolling stages).
        "air": [sl(_ints(trace.data[i]["air"])) for i in PORTS],
        "form": forms,                                  # "ZZZ...SSS" or null
        # full per-frame X-ray of what the analysis reads each frame:
        "state": [sl(_ints(trace.data[i]["state"])) for i in PORTS],
        "move": [sl(_ints(trace.data[i]["lastatk"])) for i in PORTS],
        "dir": [sl(_ints(_opt(trace.data[i]["dir"], [1] * n_full))) for i in PORTS],
        "joyx": [sl(_round2(_opt(trace.data[i]["joy_x"], [0.0] * n_full))) for i in PORTS],
        "joyy": [sl(_round2(_opt(trace.data[i]["joy_y"], [0.0] * n_full))) for i in PORTS],
        "cstickx": [sl(_round2(_opt(trace.data[i]["cstick_x"], [0.0] * n_full))) for i in PORTS],
        "csticky": [sl(_round2(_opt(trace.data[i]["cstick_y"], [0.0] * n_full))) for i in PORTS],
        "btn": [sl(_ints(trace.data[i]["buttons"])) for i in PORTS],  # physical buttons bitmask
        "shield": [sl(_round1(_opt(trace.data[i]["shield"], [0.0] * n_full))) for i in PORTS],
        # analog press depth 0..100 for shield-bubble sizing (null per port on
        # peppi builds without pre.triggers)
        "lt": [None if (v := _lightshield(trace.data[i].get("trigger"))) is None
               else sl(v) for i in PORTS],
        # inputs to the 2D character renderer:
        "cid": [sl(_ints(_opt(trace.data[i]["form"], [ext_int[i]] * n_full)))
                for i in PORTS],                        # per-frame INTERNAL char id
        "age": [sl(_round1(_opt(trace.data[i]["state_age"], [0.0] * n_full)))
                for i in PORTS],                        # animation frame index
    }
    # Ice Climbers: Nana rides along as render-only follower rows. Additive —
    # every `meta.players.length === 2` check downstream (desktop HUD, mobile,
    # the share worker) keeps seeing leaders only; old consumers just don't
    # draw her. Null entries = frames where she is dead/absent.
    fol = []
    for fd in getattr(trace, "followers", []):
        fol.append({
            "of": fd["port"],                           # leader's player index
            "x": sl(_round1n(fd["x"])),
            "y": sl(_round1n(fd["y"])),
            "state": sl(_intsn(fd["state"])),
            "cid": sl(_intsn(_opt(fd.get("form"), [11] * n_full))),
            "age": sl(_round1n(_opt(fd.get("state_age"), [0.0] * n_full))),
            "dir": sl(_intsn(_opt(fd.get("dir"), [1] * n_full))),
            "air": sl(_intsn(_opt(fd.get("air"), [0] * n_full))),
            "shield": sl(_round1n(_opt(fd.get("shield"), [0.0] * n_full))),
        })
    if fol:
        frames["fol"] = fol
    # detector output; on a window keep only conversions overlapping the slice.
    # Conversions are a 1v1 notion (actor vs the single opponent) — a doubles
    # game just renders the fighters, no conversion overlay.
    conversions = {}
    if len(trace.data) == 2:
        start_sf = trace.start_frame + lo
        end_sf = trace.start_frame + hi
        for i in (0, 1):
            convs = detect_conversions(trace, i)
            if lo > 0 or hi < n_full - 1:
                convs = [c for c in convs
                         if c["end_frame"] >= start_sf and c["start_frame"] <= end_sf]
            conversions[str(i)] = convs

    bundle = {
        "meta": {
            "v": 2,                                     # bundle schema version
            "file": os.path.basename(trace.path),
            "stage": trace.stage,
            "stage_name": STAGE_NAMES.get(trace.stage, f"stage {trace.stage}"),
            "stage_edge": STAGE_EDGE.get(trace.stage, 70.0),
            "start_frame": trace.start_frame + lo,      # window's first Slippi frame
            "n": n,
            "fps": 60,
            "players": players,
            "teams": bool(getattr(trace, "is_teams", False)),
            "attack_names": {str(k): v for k, v in ATTACK_NAMES.items()},
        },
        "frames": frames,
        "conversions": conversions,
    }

    # v2: projectiles/items + dynamic stage state, from the raw event stream.
    # Windowed like everything above: `frames` indexes are window-relative, so
    # item/stage frame numbers convert through the window's first Slippi frame
    # (meta.start_frame == trace.start_frame + lo).
    path = path or getattr(trace, "path", None)
    if path:
        items, stage_state = _viz_items(trace, path, lo, hi)
        bundle["items"] = items
        if stage_state:
            bundle["stage_state"] = stage_state
    return bundle


def _viz_items(trace, path, lo, hi):
    """(items, stage_state) sections for build_viz_bundle, clipped to the
    [lo,hi] index window. read_items_and_stage never raises, so neither do we
    — a file that has moved since the trace was cached just yields ([], {}).

    Alignment matters here: the fighter arrays keep rollback RE-EMITTED frames
    as extra rows, so `frame - start_frame` drifts EARLY by the number of
    re-emissions so far (one netplay game measured 729 of them ≈ 18s of drift
    late-game). Items/stage events come from the raw stream in true Slippi
    frames, so they must map through trace.frame_ids — the same row the
    fighters' own data for that frame landed on (last occurrence wins: the
    corrected row is the canonical one).
    """
    from .stage_items import read_items_and_stage
    tracks, stage_ev = read_items_and_stage(path)

    fids = getattr(trace, "frame_ids", None)
    if fids:
        fids = fids[:trace.n]
        last_index = {}                          # slippi frame -> last row
        for j, fr in enumerate(fids):
            last_index[fr] = j
        first_frame, last_frame = fids[0], fids[-1]

        def index_of(frame):
            """Slippi frame -> canonical array index, or None outside the game."""
            if frame in last_index:
                return last_index[frame]
            if frame < first_frame or frame > last_frame:
                return None
            # a frame absent from the ids (shouldn't happen; frames are dense)
            return min(max(frame - first_frame, 0), trace.n - 1)
    else:
        def index_of(frame):
            j = frame - trace.start_frame
            return j if 0 <= j < trace.n else None

    items = []
    for tr in tracks.values():
        s = tr["start"]
        life = len(tr["x"])
        # Resample the track onto the bundle's row timeline: walk the rows the
        # track's life maps to and pick the track sample for each row's frame.
        # Across a rollback re-emission the same sample repeats — exactly what
        # the duplicated fighter rows do, so everything stays in step.
        j0 = index_of(s)
        j1 = index_of(s + life - 1)
        if j0 is None and j1 is None:
            continue
        j0 = 0 if j0 is None else j0
        j1 = trace.n - 1 if j1 is None else j1
        a = max(j0, lo)
        b = min(j1, hi)
        if b < a:
            continue                             # life entirely outside window
        xs, ys, ds, ss_ = [], [], [], []
        for j in range(a, b + 1):
            fr = fids[j] if fids else trace.start_frame + j
            k = fr - s
            if k < 0 or k >= life:
                k = 0 if k < 0 else life - 1     # clamp at life edges
            xs.append(tr["x"][k])
            ys.append(tr["y"][k])
            ds.append(tr["dir"][k])
            ss_.append(tr["state"][k])
        items.append({
            "t": tr["type"],                     # melee ItemKind id
            "o": tr["owner"],                    # port index, -1 = none/unknown
            "f": a - lo,                         # first window-relative index
            "x": xs,
            "y": ys,
            "d": ds,                             # facing -1/0/+1
            "s": ss_,                            # item action state (u8)
        })
    items.sort(key=lambda t: t["f"])

    stage_state = {}
    # Stage events are deltas, so a window must carry IN the last event before
    # its start (clamped to index 0) or a mid-game clip would render FoD
    # platforms at default height / Stadium untransformed until the next event.
    fod = []
    baseline = {}                                # platform -> pre-window event
    for frame, plat, height in stage_ev["fod"]:
        j = index_of(frame)
        idx = None if j is None else j - lo
        if idx is None or idx < 0:
            baseline[plat] = [0, plat, height]
        elif idx <= hi - lo:
            fod.append([idx, plat, height])
    fod = [baseline[p] for p in sorted(baseline)] + fod
    if fod:
        stage_state["fod"] = fod

    stadium = []
    carry = None
    for frame, ev, tid in stage_ev["stadium"]:
        j = index_of(frame)
        idx = None if j is None else j - lo
        if idx is None or idx < 0:
            carry = [0, ev, tid]
        elif idx <= hi - lo:
            stadium.append([idx, ev, tid])
    if carry is not None:
        stadium.insert(0, carry)
    if stadium:
        stage_state["stadium"] = stadium
    return items, stage_state


# real combos are a few seconds; cap the window so a pathological "combo"
# (jab-lock / offstage stalemate spanning thousands of frames) can't produce a
# giant, unplayable clip / huge GIF. ~25s from the opener is plenty.
MAX_CLIP_FRAMES = 1500


def build_clip_bundle(trace, start_frame, end_frame, pad=45):
    """A small windowed bundle around a moment (Slippi frames), padded so the
    action has lead-in/out. Feeds an inline looping clip — no Dolphin. The
    window is capped from the opener so an absurdly long conversion stays
    watchable (it shows the opening ~25s, not the whole stall)."""
    end_frame = min(end_frame, start_frame + MAX_CLIP_FRAMES)
    lo = trace.index_of_frame(start_frame - pad)
    hi = trace.index_of_frame(end_frame + pad)
    # Last-occurrence row order is not perfectly monotonic in frame id at a
    # partial rollback tail (seen in ~0.3% of real files) — never hand
    # build_viz_bundle an inverted window.
    if hi < lo:
        hi = lo
    return build_viz_bundle(trace, lo, hi)


def main(argv=None):
    from ..store.game_trace import load_trace
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: python -m tracker.video.viz_export <game.slp> "
              "> bundle.json", file=sys.stderr)
        return 2
    trace = load_trace(argv[0])
    if trace is None:
        print(f"could not frame-parse {argv[0]!r} (too short, corrupt, or not "
              "a 1v1)", file=sys.stderr)
        return 1
    json.dump(build_viz_bundle(trace), sys.stdout, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
