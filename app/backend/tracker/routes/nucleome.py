"""The Tracker blueprint: every /api/nucleome route except Combo Video.

``nucleome_bp`` (blueprint name "nucleome", so every endpoint is ``nucleome.<view>``)
is defined here with its release gates and the helpers more than one route module
reads. The routes live in one module per Tracker feature, each imported at the
bottom of this file so the blueprint is complete once this module has loaded:

  replays.py  identity, scanning the replay folder, the replay list
  stats.py    the Stats page: metadata stats and deep stats
  combos.py   the Combos page
  lite.py     Lite, the in-app 2D player
  watch.py    Watch with mods: Dolphin playback, playlists and recording
  icons.py    stage and stock icons, the ISO-derived sprites
  ranks.py    Slippi ranks for connect codes, the player's rank history
  cloud.py    the cloud vault behind Nucleus on your phone
  share.py    public replay and combo links

The Randall coach's /coach/* routes are on this blueprint as well; they live in
randall/routes/coach.py, which app.py imports before registering it.

All endpoints live under /api/nucleome. Scanning is USER-TRIGGERED only
(POST /replays/scan); nothing indexes automatically at startup.
"""
import functools
import re
import sqlite3

from flask import Blueprint, jsonify, request

from core import gates
from tracker.cloud import vault_jobs
from tracker.store import indexer


# Tracker (internally still "nucleome") shipped in 0.7.0. NUCLEUS_NUCLEOME is a
# kill switch, not a release hold: =0 refuses every route on this blueprint and
# skips the Watch Lite background fetch (headless/harness runs use it). The UI
# half of the switch lives in frontend/src/App.jsx.
NUCLEOME_ENABLED = gates.enabled('nucleome')

# The cloud vault (phone pairing + replay push, the Patreon offer) shipped in
# 0.7.2 and carries its own switch on top of NUCLEUS_NUCLEOME;
# tracker/cloud/vault_jobs.py reads the same variable to gate the launch
# autorun, which never passes through here.
VAULT_ENABLED = gates.enabled('vault')

nucleome_bp = Blueprint("nucleome", __name__, url_prefix="/api/nucleome")


@nucleome_bp.before_request
def _refuse_when_gated():
    if not NUCLEOME_ENABLED:
        return jsonify({"error": "Nucleus Stats is not available in this build"}), 404


def _requires_vault(view):
    """Refuse a vault route in a build where the feature is gated off.

    A decorator rather than another before_request hook: the blueprint's hook
    would have to match on request.path to tell vault routes from the rest of
    nucleOME, and a URL-prefix string is a poor place to keep a release gate.
    Reads the module global at call time so tests can flip it.
    """
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not VAULT_ENABLED:
            return jsonify({"error": "the vault is not available in this "
                                     "build"}), 404
        return view(*args, **kwargs)
    return wrapped


def _synced_game_ids(conn, game_ids):
    """The subset of game_ids already pushed to the cloud vault.

    Fail-soft: a library that has never synced has no vault_objects table at
    all, and that simply means nothing is synced — not an error. Empty when
    the vault is gated off, so no share affordance ever renders there.
    """
    if not VAULT_ENABLED or not game_ids:
        return set()
    marks = ",".join("?" for _ in game_ids)
    try:
        rows = conn.execute(
            f"SELECT game_id FROM vault_objects WHERE pushed_at IS NOT NULL "
            f"AND game_id IN ({marks})", list(game_ids)).fetchall()
    except sqlite3.OperationalError:
        return set()
    return {r["game_id"] for r in rows}


# The cloud vault's stored Patreon app token, read by the vault routes (cloud.py)
# and the share routes (share.py).

def _stored_token(conn):
    return indexer.kv_get(conn, vault_jobs.TOKEN_KEY) or None


def _token_or_error():
    """(token, None), or (None, response) when nothing is stored.

    400 not_configured rather than a 502: no token means the user has not
    linked Patreon yet, and the UI's remedy for that (send them to link it) is
    a different screen from the one it shows for an unreachable vault.
    """
    conn = indexer.connect()
    try:
        token = _stored_token(conn)
    finally:
        conn.close()
    if not token:
        return None, (jsonify({"error": "not_configured"}), 400)
    return token, None


_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _day_arg(name):
    """Optional YYYY-MM-DD query arg, or None. Raises ValueError when set
    but malformed, so the route's bad-filter handler answers 400."""
    val = request.args.get(name)
    if val in (None, ""):
        return None
    if not _DAY_RE.match(val):
        raise ValueError(name)
    return val


# Each feature module adds its routes to nucleome_bp when imported.
from tracker.routes import replays  # noqa: E402,F401
from tracker.routes import stats  # noqa: E402,F401
from tracker.routes import combos  # noqa: E402,F401
from tracker.routes import lite  # noqa: E402,F401
from tracker.routes import watch  # noqa: E402,F401
from tracker.routes import icons  # noqa: E402,F401
from tracker.routes import ranks  # noqa: E402,F401
from tracker.routes import cloud  # noqa: E402,F401
from tracker.routes import share  # noqa: E402,F401
