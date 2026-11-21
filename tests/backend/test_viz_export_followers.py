"""frames.fol — Ice Climbers' Nana in the Watch Lite viz bundle.

Nana lives in a render-only `frames.fol` section, NOT in meta.players or the
main frame arrays: every 1v1 check downstream (`players.length === 2` in the
desktop HUD, mobile, and the deployed share worker) must keep seeing leaders
only. Her rows carry nulls on frames where she is dead/absent, and those nulls
must survive to JSON so the renderer knows to skip her.

Uses a hand-built stand-in trace (no .slp needed) shaped like GameTrace.
"""
import json

from tracker.video.viz_export import build_viz_bundle


class _FakeTrace:
    """Minimal GameTrace stand-in: 2 leaders + 1 follower over N frames."""

    def __init__(self, n=6):
        self.n = n
        self.path = "fake.slp"
        self.stage = 31
        self.is_teams = False
        self.start_frame = -123
        self.frame_ids = None
        self.players = [object(), object()]     # netplay access is try/excepted

        def port(char):
            return {
                "char": char, "team": None,
                "state": [14] * n, "pct": [0.0] * n, "stocks": [4] * n,
                "lcan": [0] * n, "buttons": [0] * n,
                "x": [float(i) for i in range(n)], "y": [0.0] * n,
                "air": [0] * n, "lastatk": [0] * n,
                "dir": [1] * n, "joy_x": [0.0] * n, "joy_y": [0.0] * n,
                "cstick_x": [0.0] * n, "cstick_y": [0.0] * n,
                "form": [10] * n, "state_age": [0.0] * n, "shield": [60.0] * n,
            }
        self.data = [port(14), port(20)]        # ICs vs Falco (external ids)
        # Nana: alive for 4 frames, then dead (nulls) for the rest
        alive = 4
        self.followers = [{
            "port": 0,
            "state": [14] * alive + [None] * (n - alive),
            "x": [10.0 + i for i in range(alive)] + [None] * (n - alive),
            "y": [0.0] * alive + [None] * (n - alive),
            "dir": [1] * alive + [None] * (n - alive),
            "form": [11] * alive + [None] * (n - alive),
            "state_age": [0.0] * alive + [None] * (n - alive),
            "shield": [60.0] * alive + [None] * (n - alive),
            "air": [0] * alive + [None] * (n - alive),
        }]

    def index_of_frame(self, slippi_frame):
        return max(0, min(slippi_frame - self.start_frame, self.n - 1))

    def form_series(self, i):
        return None

    def display_char(self, i):
        return "ICs" if i == 0 else "Falco"


def test_follower_rows_are_additive_and_null_safe():
    b = build_viz_bundle(_FakeTrace())

    # leaders untouched: 1v1 checks downstream keep working
    assert len(b["meta"]["players"]) == 2
    assert len(b["frames"]["x"]) == 2

    fol = b["frames"]["fol"]
    assert len(fol) == 1
    fo = fol[0]
    assert fo["of"] == 0
    assert set(fo) == {"of", "x", "y", "state", "cid", "age", "dir", "air",
                       "shield"}
    n = b["meta"]["n"]
    assert all(len(fo[k]) == n for k in fo if k != "of")
    assert fo["cid"][0] == 11                    # Nana's internal id
    assert fo["state"][4] is None and fo["x"][4] is None   # dead = null
    json.dumps(b)                                # nulls must be JSON-safe


def test_windowed_bundle_slices_follower_rows():
    b = build_viz_bundle(_FakeTrace(), lo=1, hi=3)
    fo = b["frames"]["fol"][0]
    assert len(fo["x"]) == 3
    assert fo["x"] == [11.0, 12.0, 13.0]


def test_no_followers_means_no_fol_key():
    t = _FakeTrace()
    t.followers = []
    assert "fol" not in build_viz_bundle(t)["frames"]
