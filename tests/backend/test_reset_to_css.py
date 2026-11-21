"""nav.reset_to_css returns when the character-select screen is RUNNING, not when
the scene bytes first name it. In between, the CSS is loading: the frame counter
stands at the match's last value, and the CSS's own loop then restarts it and
clears the loop-break flag, wiping a stage-select warp written in that window.
(Measured in a real Dolphin on 2026-11-10: about a quarter second; it cost a bulk
stage capture every variant after the first.) No Dolphin here: the game is a
stand-in driven by a fake clock."""
import types

from shared.ingame import nav
from shared.ingame.observe import FRAME_COUNTER

QUIT = 1.5      # seconds after the call at which the match's loop ends and the bytes name the CSS


class Game:
    def __init__(self, load=0.26, fps=60.0, leaves=True):
        self.now = 0.0
        self.load, self.fps, self.leaves = load, fps, leaves

    # the clock nav sees
    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    # the game
    def on_css(self):
        return self.leaves and self.now >= QUIT

    def css_running(self):
        return self.leaves and self.load is not None and self.now >= QUIT + self.load

    def u8(self, address):
        if address == nav.SCENE_MAJOR:
            return nav.VS_MAJOR
        assert address == nav.SCENE_MINOR
        return nav.CSS_MINOR if self.on_css() else 0x02

    def u32(self, address):
        assert address == FRAME_COUNTER
        if self.css_running():
            return int((self.now - QUIT - self.load) * self.fps)
        return 300 + int(min(self.now, QUIT) * self.fps)      # the match's counter, standing still once its loop ended


PAD = types.SimpleNamespace(tap=lambda *a, **k: None, frame=lambda *a, **k: None)


def quit_to_css(monkeypatch, game):
    monkeypatch.setattr(nav, 'time', game)
    return nav.reset_to_css(game, PAD)


def test_the_css_is_running_when_reset_returns(monkeypatch):
    game = Game()
    assert quit_to_css(monkeypatch, game)
    assert game.css_running()
    assert game.now < QUIT + game.load + 0.5        # and it did not wait out the timeout to say so


def test_a_slow_emulator_still_counts_as_running(monkeypatch):
    game = Game(load=0.6, fps=6.0)                  # the counter moves less often than it is polled
    assert quit_to_css(monkeypatch, game)
    assert game.css_running()
    assert game.now < 4.0


def test_a_match_that_never_ends_is_not_the_css(monkeypatch):
    game = Game(leaves=False)
    assert not quit_to_css(monkeypatch, game)


def test_a_css_whose_counter_cannot_be_seen_moving_still_passes_at_the_timeout(monkeypatch):
    game = Game(load=None)                          # the bytes name the CSS and the counter never moves
    assert quit_to_css(monkeypatch, game)
    assert game.now >= 8.0
