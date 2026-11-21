"""clip_refs — opaque, un-fabricatable references for Randall's inline clips.

Randall writes clip tokens as free text. When it typed raw frame numbers
(`[[clip:<game>:<start>:<end>]]`) it could hallucinate a window that doesn't
exist in the game (observed: frames beyond the end of the replay → a single
frozen frame that "won't play"). Raw numbers are guessable; a ref is not.

A ref is the sha1 of the REAL (game_id, start_frame, end_frame) a tool computed,
stored in the `clip_refs` table when the tool mints it. The model can only copy
refs it was handed — it cannot compute a valid sha1 for invented frames, so a
fabricated token resolves to nothing and the UI shows an honest "unavailable"
instead of the wrong (or a frozen) clip.
"""
import hashlib
import time

from ..store import indexer


def ref_id(game_id, start_frame, end_frame):
    """Deterministic ref for a window (same window -> same ref, idempotent)."""
    h = hashlib.sha1(f"{int(game_id)}:{int(start_frame)}:{int(end_frame)}"
                     .encode()).hexdigest()
    return "c" + h[:11]


def mint(game_id, start_frame, end_frame, label=None, conn=None):
    """Register a real clip window and return its opaque ref. Idempotent."""
    ref = ref_id(game_id, start_frame, end_frame)
    own = conn is None
    conn = conn or indexer.connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO clip_refs"
            "(ref, game_id, start_frame, end_frame, label, created) "
            "VALUES (?,?,?,?,?,?)",
            (ref, int(game_id), int(start_frame), int(end_frame), label,
             time.time()))
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()
    return ref


def resolve(ref, conn=None):
    """(game_id, start_frame, end_frame, label) for a ref, or None if unknown
    (fabricated / never minted)."""
    own = conn is None
    conn = conn or indexer.connect()
    try:
        r = conn.execute(
            "SELECT game_id, start_frame, end_frame, label "
            "FROM clip_refs WHERE ref=?", (ref,)).fetchone()
    finally:
        if own:
            conn.close()
    if r is None:
        return None
    return r["game_id"], r["start_frame"], r["end_frame"], r["label"]


def _recover_clip_window(conn, game_id):
    """Best real combo window (start,end Slippi frames) for a game, or None.

    Randall writes clip tokens in free text and can hallucinate frame numbers
    that don't exist in the game (observed: an out-of-range window collapses to a
    single frozen frame). When a requested window falls outside the game we snap
    to the game's highest-damage combo — the model was almost always reaching for
    "the best combo" anyway, so this shows the right moment instead of a freeze."""
    r = conn.execute(
        "SELECT start_frame, end_frame FROM combos WHERE game_id=? "
        "ORDER BY damage DESC LIMIT 1", (game_id,)).fetchone()
    return (r["start_frame"], r["end_frame"]) if r else None
