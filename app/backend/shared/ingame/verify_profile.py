"""
The versioned capture profile of the costume verification (verify_costume.py)
and the version of the manifest it writes:
which moves and frames are captured, resolved against the move names the
capture engine accepts, and the frameshot shot specs for them.
"""

from __future__ import annotations


MANIFEST_SCHEMA = "game-verification-v1"
PROFILE_VERSION = "costume_verification_v1"

# --- the versioned capture profile ------------------------------------------- #
# The move NAMES are resolved against the engine's own catalog at run time (see
# resolve_profile); they are never trusted from this table. The frame numbers
# follow community frame-data convention, which is what the capture engine
# steps to (frame 1 = the first frame in the move's action state).
#
# The CAMERA IS PART OF THE PROFILE. Changing any of these numbers is a new
# profile version, because every extent measurement below is relative to them.
_PROFILES = {
    PROFILE_VERSION: {
        "version": PROFILE_VERSION,
        "stage": "finaldestination",
        "camera": {
            "closeup": True,
            "plain_bg": "404040",
            "fixed": True,              # never re-framed after seeing a result
            "cam_dist": 42.0,
            "cam_fov": 35.0,
            "cam_height": 8.0,
            "cam_side": 1.0,
            "cam_pitch": 0.0,
            "width": 1280,
        },
        "entries": [
            {"id": "idle", "label": "idle", "move": "idle", "frames": [1]},
            {"id": "run", "label": "run", "move": "run", "frames": [5, 15]},
            {"id": "jab", "label": "jab", "move": "jab", "frames": [1, 2, 3]},
            {"id": "fsmash", "label": "forward smash", "move": "fsmash",
             "frames": [10]},
            {"id": "upb", "label": "up special", "move": "upb", "frames": [5]},
            {"id": "dashattack", "label": "dash attack", "move": "dashattack",
             "frames": [6]},
            {"id": "grab", "label": "grab", "move": "grab", "frames": [3]},
        ],
        "appearance": {
            # Everything below is a fraction of the RENDERED AREA, not of the
            # captured window: PrintWindow grabs the pillarbox bars too.
            # Below `min` the actor is NOT DRAWN (an empty cell is not evidence
            # of anything); above `max` it has grossly overflowed the framing.
            "min_actor_frac": 0.0015,
            "max_actor_frac": 0.55,
            # How close to the rendered boundary the actor may come. Contact is
            # clipping: the frame cannot show whether the silhouette stops at
            # the edge or continues, and the camera may not be widened to find
            # out.
            "clip_edge_px": 2,
            # Above this share of the rendered area covered by effects, the
            # actor cannot be separated from them -> `unknown`, not a pass.
            "max_effects_share": 0.35,
            # How much of the measured actor may be absent from the DELIVERED
            # frame before the measurement and the saved image are treated as
            # different captures.
            "max_composition_drift": 0.02,
            "background": "404040",
        },
    },
}


# --- profile resolution ------------------------------------------------------- #

def engine_catalog():
    """The move names the capture engine itself accepts, read from the engine.

    `idle` is a frameshot shot that is not an attack state, so it is not in
    `moves.MOVES`; everything else comes straight from the recipe table. A
    hand-copied list is how a documented profile ends up asking for a move the
    engine rejects.
    """
    from .moves import MOVES
    return ("idle",) + tuple(MOVES)


def resolve_profile(version=PROFILE_VERSION, catalog=None):
    """Resolve a capture profile against the engine's move catalog.

    Every entry is returned. An entry whose move the engine does not accept is
    marked ``status='unsupported'`` and makes the whole profile INCOMPLETE; it
    is never silently omitted, because a shorter sheet that nobody notices is
    how a missing measurement becomes a pass.
    """
    try:
        spec = _PROFILES[version]
    except KeyError:
        raise ValueError(f"Unknown capture profile {version!r}. "
                         f"Known: {', '.join(sorted(_PROFILES))}.")
    known = tuple(catalog) if catalog is not None else engine_catalog()
    entries, expected, unsupported = [], [], []
    for entry in spec["entries"]:
        row = dict(entry)
        if entry["move"] in known:
            row["status"] = "supported"
            row["reason"] = ""
            for frame in entry["frames"]:
                expected.append({"entry_id": entry["id"], "move": entry["move"],
                                 "frame": int(frame)})
        else:
            row["status"] = "unsupported"
            row["reason"] = (f"the capture engine does not accept the move "
                             f"{entry['move']!r}")
            unsupported.append(entry["id"])
        entries.append(row)
    return {
        "profile_version": spec["version"],
        "stage": spec["stage"],
        "camera": dict(spec["camera"]),
        "appearance": dict(spec["appearance"]),
        "entries": entries,
        "expected_captures": expected,
        "unsupported": unsupported,
        "complete": not unsupported,
        "catalog_size": len(known),
    }


def shot_specs(resolved):
    """frameshot `--shot move:frames` strings for the SUPPORTED entries."""
    out = []
    for entry in resolved["entries"]:
        if entry["status"] != "supported":
            continue
        out.append(f"{entry['move']}:{','.join(str(f) for f in entry['frames'])}")
    return out
