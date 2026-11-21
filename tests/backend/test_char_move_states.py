"""The move recogniser accepts the char-specific states a move really enters.

Peach's fsmash is AttackS4Club/Pan/Racket (349-351), Ness's smashes are his own
yo-yo/bat states, Link and Young Link taunt through AppealSR/SL (342/343). The
ids come from shared/ingame/char_move_states.py, generated from the Melee decomp.
"""

import pytest

from shared.ingame import framestep, moves
from shared.ingame.gamestate import ATTACK_STATES, APPEAL_STATES, attack_states
from shared.ingame.moves import MoveError, MoveRunner

MARIO, LINK, NESS, PEACH, YLINK, GW = 0, 6, 8, 9, 20, 24


@pytest.mark.parametrize("kind,move,ids", [
    (PEACH, "fsmash", {349, 350, 351}),
    (NESS, "fsmash", {341}),
    (NESS, "usmash", {342, 343, 344}),
    (NESS, "dsmash", {345, 346, 347}),
    (LINK, "fsmash", {341}),
    (LINK, "taunt", {342, 343}),
    (YLINK, "fsmash", {341}),
    (YLINK, "taunt", {342, 343}),
    (MARIO, "taunt", {341, 342}),
    # the old hand-kept G&W table, now derived -- must not drift
    (GW, "jab", {341}), (GW, "dtilt", {345}), (GW, "fsmash", {346}),
    (GW, "nair", {347}), (GW, "bair", {348}), (GW, "uair", {349}),
])
def test_char_specific_states_are_accepted(kind, move, ids):
    got = attack_states(move, kind)
    assert ids <= got
    # the shared states stay accepted too (Link's FIRST fsmash swing is the
    # common AttackS4S; only the follow-up is AttackS42)
    common = APPEAL_STATES if move == "taunt" else ATTACK_STATES[move]
    assert common <= got


def test_fighters_without_extras_keep_the_common_table():
    assert attack_states("fsmash", 2) == ATTACK_STATES["fsmash"]   # Falcon
    assert attack_states("taunt", PEACH) == APPEAL_STATES
    assert attack_states("fsmash", None) == ATTACK_STATES["fsmash"]
    assert attack_states("neutralb", PEACH) is None


def test_char_specific_ids_do_not_leak_across_fighters():
    # 349 is Peach's club fsmash but G&W's uair; neither may borrow the other's
    assert 349 not in attack_states("fsmash", GW)
    assert 349 not in attack_states("uair", PEACH)


# --- execute() against a scripted fighter ------------------------------------ #

class FakePipe:
    def __init__(self):
        self.sent = []

    def frame(self, lines):
        self.sent.append(list(lines))

    def neutral(self):
        pass


class ScriptedPlayer:
    """Wait until the first stepped frame after an input, then `path`."""

    def __init__(self, kind, path):
        self._kind, self.path, self.st = kind, list(path), moves.WAIT

    def advance(self):
        if self.path:
            self.st = self.path.pop(0)

    def state(self):
        return self.st

    def kind(self):
        return self._kind

    def facing(self):
        return 1.0

    def pos(self):
        return (0.0, 0.0)


def _runner(monkeypatch, kind, path):
    player = ScriptedPlayer(kind, path)

    def step(_d, n):
        for _ in range(n):
            player.advance()
        return n

    monkeypatch.setattr(framestep, "is_frozen", lambda _d: True)
    monkeypatch.setattr(framestep, "step", step)
    # _step reads a snapshot before/after each step as stall evidence
    monkeypatch.setattr(framestep, "snapshot", lambda _d: {})
    runner = MoveRunner(d=None, pipe=FakePipe())
    runner.player = player
    return runner


@pytest.mark.parametrize("kind,move,path", [
    (PEACH, "fsmash", [moves.WAIT, 350]),           # frying pan
    (NESS, "usmash", [moves.WAIT, 342, 344]),       # yo-yo start -> release
    (NESS, "fsmash", [341]),
    (LINK, "taunt", [342]),
    (YLINK, "taunt", [343]),
    (PEACH, "taunt", [264]),                        # common AppealSR
])
def test_execute_lands_on_frame_one_of_char_specific_move(monkeypatch, kind,
                                                           move, path):
    runner = _runner(monkeypatch, kind, path)
    first = next(s for s in path if s != moves.WAIT)
    assert runner.execute(move) == first


def test_execute_still_rejects_a_wrong_state(monkeypatch):
    # Peach's pan is not a taunt, and a Wait that never changes is not a move
    runner = _runner(monkeypatch, PEACH, [350] * 8)
    with pytest.raises(MoveError, match="never reached taunt"):
        runner.execute("taunt")


def test_generated_table_matches_the_decomp():
    gen = pytest.importorskip("devtools.gen_char_move_states")
    try:
        root = gen.decomp_root()
    except SystemExit:
        pytest.skip("melee decomp not available on this machine")
    assert gen.render(gen.derive(root)) == gen.OUT.read_text(encoding="utf-8")


# --- held moves (shield, crouch, run) ------------------------------------------

def test_held_states_are_per_fighter_and_yoshi_shields_in_his_egg():
    assert {'shield', 'crouch'} <= set(moves.MOVES) and {'shield', 'crouch', 'run'} <= set(moves.HELD_MOVES)
    assert moves.held_states('shield', 0) == frozenset(range(178, 183))
    # ftYs_MS_GuardOn_0..GuardOn_1: Yoshi never enters the common Guard states
    assert frozenset(range(341, 346)) <= moves.held_states('shield', 14)
    assert moves.held_states('crouch', 14) == frozenset({39, 40})
    assert moves.held_states('jab', 14) is None


class HeldPipe:
    def __init__(self):
        self.lines, self.neutrals = [], 0

    def frame(self, lines):
        self.lines.append(list(lines))

    def neutral(self):
        self.neutrals += 1


def held_runner(monkeypatch, kind, path):
    """A MoveRunner on a frozen fake game whose fighter walks `path` (one
    state per stepped frame, the last one repeating) once the input is in."""
    import shared.ingame.framestep as framestep
    monkeypatch.setattr(framestep, 'is_frozen', lambda d: True)
    runner = moves.MoveRunner(None, HeldPipe())
    states = list(path)

    class Player:
        def kind(self):
            return kind

        def state(self):
            return states[0]

        def pos(self):
            return (0.0, 0.0)

    runner.player = Player()

    def step(n=1):
        for _ in range(n):
            if len(states) > 1:
                states.pop(0)
        return n
    runner._step = step
    return runner


def test_shield_holds_until_the_fighters_own_guard_state(monkeypatch):
    # Yoshi: Wait -> GuardOn_0 (341) -> GuardHold (342); the common family alone
    # never matched, which was "never reached shield (Guard family) within 8 frames"
    runner = held_runner(monkeypatch, 14, [14, 14, 341, 341, 342])
    assert runner.execute('shield') == 341
    assert runner.p.lines[-1] == ['PRESS L', 'FLUSH'] and runner.p.neutrals == 1, \
        'only the entry settle neutrals: L stays held past return'
    runner = held_runner(monkeypatch, 0, [14, 39, 40])
    assert runner.execute('crouch') == 39 and runner.p.lines[-1] == ['SET MAIN 0.500 0.000', 'FLUSH']
    runner = held_runner(monkeypatch, 0, [14] * 40)
    with pytest.raises(moves.MoveError, match='crouch'):
        runner.execute('crouch')
