"""The bulk stage capture's two recovery steps (shared/ingame/capture.py), with a
stand-in game: no Dolphin. Both were seen going wrong in a real one on 2026-11-10:
the cursor path un-picked the fighter a match had left picked, and the quit combo
pressed on a menu backed out to the main menu, losing the rest of the boot."""
import types

import pytest

import shared.ingame.capture as cap


class Game:
    """Where the last variant left the game: 'match', 'css' or 'sss'."""

    def __init__(self, at, ready=True):
        self.at, self.ready = at, ready
        self.pressed, self.quit_combos = [], 0

    def tap(self, button, *_a, **_k):
        self.pressed.append(button)
        if button == "B" and self.at == "sss":
            self.at = "css"
        elif button == "START" and self.at == "css" and self.ready:
            self.at = "sss"

    def on_stage_select(self):
        return self.at == "sss"

    def wait_for_stage_select(self, timeout=8.0):
        return self.at == "sss"

    def quit_match(self, d, p, log=None):
        self.quit_combos += 1
        was_match, self.at = self.at == "match", "css" if self.at == "match" else "main menu"
        return was_match


@pytest.fixture
def game(monkeypatch):
    def make(at, ready=True):
        g = Game(at, ready)
        g.p = g                                             # StageCursor.p, the controller
        monkeypatch.setattr(cap.nav, "at_offline_css", lambda d: g.at == "css")
        monkeypatch.setattr(cap.nav, "wait_css_running", lambda d, p, timeout=8.0: g.at == "css")
        monkeypatch.setattr(cap.nav, "reset_to_css", g.quit_match)
        monkeypatch.setattr(cap, "time", types.SimpleNamespace(sleep=lambda s: None, time=lambda: 0.0))
        return g
    return make


def test_after_a_shot_the_match_is_quit(game):
    g = game("match")
    assert cap._back_to_css(None, g, g)
    assert g.quit_combos == 1 and g.pressed == []


def test_a_variant_skipped_on_the_css_is_not_answered_with_the_quit_combo(game):
    g = game("css")
    assert cap._back_to_css(None, g, g)
    assert g.quit_combos == 0 and g.pressed == []
    assert g.at == "css"


def test_a_variant_skipped_on_stage_select_is_backed_out_of_with_b(game):
    g = game("sss")
    assert cap._back_to_css(None, g, g)
    assert g.quit_combos == 0 and g.pressed == ["B"]
    assert g.at == "css"


def test_start_leaves_a_css_that_has_a_fighter_picked(game):
    g = game("css", ready=True)
    assert cap._start_if_ready(g)
    assert g.pressed == ["START"]


def test_start_does_not_leave_a_css_with_nothing_picked(game):
    g = game("css", ready=False)
    assert not cap._start_if_ready(g)
    assert g.pressed == ["START"] and g.at == "css"
