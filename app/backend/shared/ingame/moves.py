"""
moves.py -- execute a named move frame-exactly on a frozen game.

Every recipe runs with the game FROZEN (framestep.freeze) from a Wait/idle
fighter: inputs are set over the pipe, then single frames are stepped until the
fighter's action state confirms each phase. Because pad snapshots only renew on
frames that run, an input held while frozen registers as a fresh press on
exactly the next stepped frame -- so move start frames are deterministic.

`execute()` returns with the game frozen ON FRAME 1 of the move (the first
frame whose action state is the move's state, matching community frame-data
numbering). The caller steps further and screenshots.

Tilt vs smash gotcha -- THE PIPE SCALE (measured live 2026-07-31, fp+0x620):
Dolphin's named pipe maps `SET MAIN 0..1` onto the RAW GameCube axis byte
(0..255, 128 = center) and Melee then divides the offset from center by 80, the
physical max deflection of a real stick. So a pipe value is ~1.6x bigger in the
engine than it looks:

    in_game = (pipe * 255 - 128) / 80        pipe = (in_game * 80 + 128) / 255

`SET MAIN 0.800` -- which reads like "60 % deflection" -- is 0.95 in the engine,
OVER the 0.8 smash threshold (ftCommonData x3C). That is why the old ftilt /
dtilt / dashattack recipes silently produced AttackS4S / AttackLw4 / AttackS4S:
holding the stick longer never helped, because ftCo_AttackS4_8008C114 (the
dash-IASA path) and ftCo_AttackLw4_CheckInput look at the MAGNITUDE, and
ftCo_AttackS4's tilt timer only ever gated the from-idle case. Use stick() below
so every recipe states its intent in ENGINE units and stays inside the tilt
band. Specials read the stick the same frame as B, so those are sent as one
atomic pipe frame.
"""

import time

from . import framestep
from .gamestate import (
    Player, state_name, attack_states, ATTACK_STATES,
    DAMAGE_STATES, DOWNED_STATES, WAIT, KNEE_BEND, JUMP_F, JUMP_B, DASH, RUN,
    CATCH_STATES, CATCH_WAIT,
)

# Rapid-jab (Attack100) chain states, from motion_states.py:
#   Attack11=44 Attack12=45 Attack13=46 Attack100Start=47 Attack100Loop=48
ATTACK1_STATES = {44, 45, 46}       # the jab1/2/3 chain
ATTACK100START = 47
ATTACK100LOOP = 48
ATTACK100END = 49
from .motion_states import CHAR_SPECIFIC_BASE
from .char_move_states import CHAR_MOVE_STATES

SPECIALS = {"neutralb", "sideb", "upb", "downb"}
# Air variants of the specials (jump to apex, then B-move): used for aerial
# fortress (Bowser up-B), air thunder-jolt (Pikachu N-B), Firefox in-air, etc.
AIR_SPECIALS = {"airneutralb": "neutralb", "airsideb": "sideb",
                "airupb": "upb", "airdownb": "downb"}
AERIALS = {"nair", "fair", "bair", "uair", "dair"}
# rapidjab: hold A continuously through the jab chain into the Attack100 loop
# (the rapid-jab finisher), so on-hit finisher effects (EfCoData s11/s15/s91)
# can be probed. Not in ATTACK_STATES because it targets Attack100Loop (48),
# not a single frame-1 state.
RAPIDJAB = "rapidjab"
# bombthrow: Link down-B pulls a bomb into his hand, then toss it FORWARD (A
# with the stick held forward, item light-throw) so it flies + detonates on the
# pinned bag -- for probing the bomb-explosion effect. LightThrow* states 94-103
# / *4 variants 108-119 are the item-toss states.
BOMBTHROW = "bombthrow"
LIGHT_THROW_STATES = set(range(94, 104)) | set(range(108, 120))
# shield: raise and HOLD the shield bubble (GuardOn 178 -> Guard 179) so the
# EfCoData bubble texture is capturable. The L press is deliberately left held
# when execute() returns -- releasing it would drop the bubble before the
# caller's capture frames; the next reset()'s neutral() drops it.
PUMMEL = "pummel"
THROWS = ("fthrow", "bthrow", "uthrow", "dthrow")
# every recipe that must first CONNECT a grab (needs a bag in range)
GRAB_FOLLOWUPS = frozenset(THROWS + (PUMMEL,))
SHIELD = "shield"
# Guard family 178-182 (GuardOn/Guard/GuardOff/GuardSetOff/GuardReflect).
# A digital L press on the frozen-step pipe lands in GuardReflect (182) --
# the powershield window state -- before settling into Guard; the bubble is
# up in all of them, so the recipe accepts the whole family.
GUARD_STATES = frozenset(range(178, 183))
# run: hold forward through the Dash (20) lunge into the RUN cycle (21) and KEEP
# holding, like SHIELD -- the caller's capture frames must land while the run
# animation is still playing, and the next reset()'s settle_to_wait() releases
# it. This is the only recipe whose captures contain real LOCOMOTION: every
# other capturable frame is a standing/attacking pose, which is how a port whose
# skeleton doesn't move with the fighter ("the mon stays SITTING while the
# fighter runs") sails through a grading sweep.
RUN_MOVE = "run"
# crouch: hold the stick fully down (Squat 39 -> SquatWait 40). Full down from
# Wait with no A is a crouch, never a dsmash (that needs A or the C-stick).
CROUCH = "crouch"
SQUAT_STATES = frozenset({39, 40})
# HELD moves: the pose exists only while the input stays held (a shield drops
# to GuardOff the frame L is released, a crouch stands up). execute() presses
# the input, steps until the fighter is in the move's state family and returns
# with the input STILL HELD; the caller steps to its frame, captures, then
# lets go (the pipe's neutral(); reset() also releases). The family is per
# fighter: Yoshi shields in his own egg states (ftYs_MS_GuardOn_0..GuardOn_1,
# 341-345), never the common Guard 178-182 -- see held_states().
HELD_MOVES = {
    SHIELD: dict(press=("PRESS L",), states=GUARD_STATES, what="shield (Guard family)"),
    CROUCH: dict(press=("SET MAIN 0.500 0.000",), states=SQUAT_STATES,
                 what="crouch (Squat/SquatWait)"),
    RUN_MOVE: dict(press=None, states=frozenset({RUN}), what="Run (21)"),
}
HELD_REACH = 12     # frames to enter a held state (Yoshi's GuardOn_0 is slower)
MOVES = (sorted(ATTACK_STATES) + sorted(SPECIALS)
         + sorted(AIR_SPECIALS)
         + [RAPIDJAB, BOMBTHROW, SHIELD, CROUCH, RUN_MOVE, "taunt"])


def held_states(move, kind=None):
    """The action states a HELD move's pose is shown in, for fighter `kind`
    (common family + the fighter's own, from char_move_states); None when
    `move` is not a held move."""
    held = HELD_MOVES.get(move)
    if held is None:
        return None
    return frozenset(held["states"]) | (CHAR_MOVE_STATES.get(kind, {}).get(move) or frozenset())


# --- stick geometry (ftCommonData, read live from p_ftCommonData 0x804D6554) ---
# x3C  = 0.8     smash threshold, X  -> AttackS4 (from idle AND from dash IASA)
# xD4  = -0.6625 smash threshold, Y down -> AttackLw4;  xCC 0.6625 = up (+tap jump)
# x98  = 0.25    AttackS3 (ftilt) threshold;  xB0 = -0.25 AttackLw3 (dtilt)
# x50  = 0.625   the deflection a Dash/Run needs to keep going
# A Dash can only be STARTED at >= 0.8 (ftCo_Dash_CheckInput), so `dashattack`
# deflects fully, then eases back into the band below.
SMASH_X, SMASH_Y = 0.8, 0.6625
TILT_HOLD = 0.60      # ftilt/utilt/dtilt: >> 0.25 tilt gate, << both smash gates
DASH_HOLD = 0.70      # after the dash starts: > 0.625 keep-running, < 0.8 smash


def stick(v):
    """Pipe axis value (0..1) that produces IN-GAME stick value `v` (-1..1).
    See the module docstring: the pipe is raw-byte scale, the engine is /80."""
    return max(0.0, min(1.0, (v * 80.0 + 128.0) / 255.0))


def park_bag(runner, bag, dx=8.0, dy=0.0):
    """Between-reps punching-bag maintenance + placement. Call after
    runner.reset() (game frozen, attacker idle at center): zero the bag's
    percent (minimal knockback -- an uncontrolled human port can never tech or
    get up, so keep it from ever being launched/knocked down), ride out any
    leftover hitstun/airborne frames from the previous rep, then teleport it
    `dx` units in front of the attacker (RebirthWait lesson 9 applies to both
    bodies: both get re-centered every rep)."""
    bag.resolve()
    bag.set_percent(0)
    for _ in range(180):     # ride out leftover hitstun / knockback flight
        st = bag.state()
        if st in (12, 13):   # Rebirth/RebirthWait: KO'd -- teleport from the
            break            # halo; the fall + land settles on the next rep
        # DOWNED_STATES as well as hitstun: a bag knocked to the floor by the
        # previous rep is out of hitstun long before it is grabbable again, and
        # parking it while it lies there makes the NEXT grab recipe whiff on a
        # body that is right in front of the attacker (hit while testing throws
        # back to back, 2026-09-03).
        if (st is not None and st not in DAMAGE_STATES
                and st not in DOWNED_STATES and bag.airborne() is False):
            break
        runner._step(1)
    if bag.state() in DOWNED_STATES:
        # An uncontrolled human port NEVER gets up: DownWaitU/D wait for a
        # button that nobody presses, so the loop above just times out and the
        # next grab whiffs on a body lying at the attacker's feet. Drop it from
        # just above the ground instead -- Fall -> Land -> Wait is a guaranteed
        # chain out of any grounded stuck-state (the same trick reset() uses).
        bag.park_in_front(runner.player, dx=dx, dy=dy + 8.0)
        for _ in range(90):
            runner._step(1)
            if bag.state() == WAIT:
                break
    bag.park_in_front(runner.player, dx=dx, dy=dy)
    runner._step(2)          # let ground collision re-snap the teleport


class MoveError(RuntimeError):
    pass


def _noop(*_a, **_k):
    pass


class MoveRunner:
    def __init__(self, d, pipe, port=0, log=_noop, camera_pan=True):
        self.d = d
        self.p = pipe
        self.player = Player(d, port)
        self.log = log
        # `camera_pan` = spend 60 stepped frames after a recenter letting the
        # GAME camera pan back to the fighter. Set it False when the caller
        # parks the DEBUG_FREE camera itself for every capture (frameshot
        # --closeup): the game camera is then never photographed, so the pan is
        # 60 x 33 ms = ~2.0 s of pure waste per recentering move. Measured
        # 2026-07-30: a stepped frame costs 32.6 ms (2x real time), which makes
        # this the single most expensive thing in run_shots after the load.
        self.camera_pan = camera_pan

    # --- primitives ---------------------------------------------------------
    def _step(self, n=1):
        """Advance n frames; returns the REAL count (rarely n+1 on a late
        request-clear -- callers track position by the return value)."""
        def evidence():
            result=framestep.snapshot(self.d)
            mailbox=getattr(getattr(self,'p',None),'mailbox',None)
            if mailbox is not None:
                from .memory_input import PUBLISHED,CONSUMED,HEARTBEAT
                result['input']={}
                for name,offset in [('published',PUBLISHED),('consumed',CONSUMED),('heartbeat',HEARTBEAT)]:
                    try:result['input'][name]=self.d.u32(mailbox+offset)
                    except Exception as exc:result['input'][name]=type(exc).__name__
            return result
        started=time.monotonic()
        before=evidence()
        got = framestep.step(self.d, n)
        after=evidence() if got<n else None
        if got < n:
            raise MoveError(f"frame step stalled ({got}/{n} frames ran); before={before}; "
                            f"after={after}; elapsed={time.monotonic()-started:.3f}s")
        return got

    def _step_until(self, pred, max_steps, what):
        """Step one frame at a time until pred(state). Returns steps taken."""
        for i in range(1, max_steps + 1):
            self._step(1)
            st = self.player.state()
            if st is not None and pred(st):
                return i
        st = self.player.state()
        pos = self.player.pos() or (None, None)
        raise MoveError(f"never reached {what} within {max_steps} frames "
                        f"(state = {state_name(st)}, pos = {pos})")

    def _fwd(self):
        """Main/C-stick x for 'toward facing' (pipe: x=1 right, y=0 up)."""
        f = self.player.facing()
        return 1.0 if (f or 1.0) > 0 else 0.0

    def _back(self):
        return 1.0 - self._fwd()

    def _fwd_stick(self, mag):
        """Pipe x for an IN-GAME deflection of `mag` toward the facing dir."""
        sign = 1.0 if (self.player.facing() or 1.0) > 0 else -1.0
        return stick(sign * mag)

    def settle_to_wait(self, max_steps=300):
        """From wherever the fighter is (landing, READY-GO idle...), neutral
        inputs and step until Wait so every recipe starts identically."""
        self.p.neutral()
        if self.player.state() == WAIT:
            return
        self._step_until(lambda s: s == WAIT, max_steps, "Wait (idle)")

    def reset(self, recenter=True, center_x=0.0, ground_y=0.0):
        """Recover a clean idle between moves so ONE boot can run many recipes:
        ride out the previous move (fall, land, landing lag) back to Wait, then
        teleport to center stage so drift from dash attacks / side-Bs can't
        walk the fighter off an edge across a long batch."""
        try:
            self.settle_to_wait()
        except MoveError:
            # Teeter (OttottoWait) holds forever on neutral input, and on some
            # stages (e.g. Dreamland) the spawn point itself is a platform lip.
            # A grounded set_pos doesn't reliably exit the state either, so
            # drop the fighter from just above center: Fall -> Land -> Wait is
            # a guaranteed state chain out of any grounded stuck-state.
            if not recenter:
                raise
            # RebirthWait (the respawn platform, seen on m-ex stage spawns)
            # ignores repositioning and only exits on stick input: nudge down
            # to drop off before relocating (harmless from other stuck-states)
            self.p.frame(["SET MAIN 0.500 1.000", "FLUSH"])
            self._step(8)
            self.p.neutral()
            self.player.set_pos(center_x, ground_y + 8.0)
            self._step(2)
            self.settle_to_wait()
        if recenter:
            pos = self.player.pos()
            if pos and pos[0] is not None and abs(pos[0] - center_x) > 1.0:
                self.player.set_pos(center_x, ground_y + 8.0)
                self._step(2)          # let ground collision re-snap
                npos = self.player.pos() or (None, None)
                if npos[0] is not None and abs(npos[0] - center_x) > 2.0:
                    # a grounded set_pos doesn't stick: the engine re-derives
                    # an attached fighter's position from its ground line (seen
                    # on Dreamland, where the solo spawn is a platform lip that
                    # then teeters forever). Walk inward instead -- off the
                    # platform if there is one -- and settle through the fall.
                    inward = 1.0 if npos[0] < center_x else 0.0
                    self.p.frame([f"SET MAIN {inward:.3f} 0.500", "FLUSH"])
                    self._step(30)
                    self.p.neutral()
                    # walking off a platform breaks the ground attachment; an
                    # airborne fighter CAN be teleported -- place it above the
                    # target so it falls and lands there instead of wherever
                    # the walk-off drops it (Green Hill's rebirth platform
                    # hangs over a pit: uncorrected, walking off = death loop)
                    if self.player.airborne():
                        self.player.set_pos(center_x, ground_y + 12.0)
                        self._step(2)
                self.settle_to_wait(max_steps=150)
                # the camera doesn't teleport with the fighter -- it pans back
                # over real frames, and stepped frames advance it too. Without
                # this, captures right after a big-displacement move (side-B,
                # Firefox) frame the fighter from across the stage.
                # (Skipped when the caller parks its own DEBUG_FREE camera --
                # see camera_pan in __init__.)
                if self.camera_pan:
                    self._step(60)

    def _to_air(self, rise=10):
        """Full hop and rise `rise` frames above the jumpsquat."""
        self.p.frame(["PRESS Y", "FLUSH"])
        self._step_until(lambda s: s == KNEE_BEND, 4, "jumpsquat")
        self._step_until(lambda s: s in (JUMP_F, JUMP_B), 12, "liftoff")
        self.p.frame(["RELEASE Y", "FLUSH"])
        if rise:
            self._step(rise)

    def _trigger(self, lines, expected, what, max_steps=6):
        self.p.frame(list(lines) + ["FLUSH"])
        steps = self._step_until(lambda s: s in expected, max_steps, what)
        self.p.neutral()   # nothing can interrupt the move; stop all inputs
        return steps

    def execute(self, move, rise=10):
        """Run `move`; returns the fighter's state id with the game frozen on
        the move's FRAME 1."""
        if not framestep.is_frozen(self.d):
            raise MoveError("execute() requires the game to be frozen")
        self.settle_to_wait()
        # per-fighter expectation: G&W's jab/dtilt/fsmash/nair/bair/uair are
        # char-specific state ids, not the common ones (gamestate.py)
        exp = attack_states(move, self.player.kind())

        if move in AERIALS:
            self._to_air(rise=rise)
            # pipe y convention: 1.0 = UP, 0.0 = DOWN (melee_pipe.py docstring)
            c = {"nair": None,
                 "fair": (self._fwd(), 0.5),
                 "bair": (self._back(), 0.5),
                 "uair": (0.5, 1.0),
                 "dair": (0.5, 0.0)}[move]
            if c is None:
                self._trigger(["PRESS A"], exp, move)
            else:
                self._trigger([f"SET C {c[0]:.3f} {c[1]:.3f}"], exp, move)

        elif move == RAPIDJAB:
            # Reach the Attack100 rapid-jab LOOP (state 48) -- the finisher that
            # spawns EfCoData s11/s15/s91 -- so on-hit finisher effects can be
            # probed. Chain path: Attack11(44)->Attack12(45)->Attack100Start(47)
            # ->Attack100Loop(48). Decomp (ftCo_Attack1.c/ftCo_Attack100.c): each
            # jab's subaction opens a small input window (hitlag_mul frames) with
            # a jab-combo/rapid gate (x2218_b1/b2); checkAttack12/13 chain when A
            # is seen there, and ftCo_Attack_800D6A50 accumulates x1A54 per A-held
            # frame until >= rapid_jab_window -> Attack100Start.
            #
            # THE INPUT FIX (2026-07-02): neither MASHING (the old
            # efcodata_fox_probe's timed press/release pairs, which reset the
            # chain to jab1 and never accumulated x1A54) NOR a CONTINUOUS hold
            # (jab1 played its full 17f then dropped straight to Wait) chains on
            # the frozen-step pipe. What works is a 1-frame-ON / 1-frame-OFF A
            # TOGGLE: it presents a FRESH A-press edge inside every jab's IASA
            # window regardless of the exact per-jab frame counts, so the chain
            # advances every window. Verified on Fox: Attack11->Attack12->
            # Attack100Start->Attack100Loop, s11/s15/s91 recolor the finisher
            # connect spark (red poke). The bag must be PINNED (dx~6, pin:true)
            # so it stays in range through the rapid loop + finisher launch.
            reached = None
            seen = []
            for i in range(160):
                a_on = (i % 2 == 0)
                self.p.frame([("PRESS A" if a_on else "RELEASE A"), "FLUSH"])
                self._step(1)
                st = self.player.state()
                if not seen or seen[-1] != st:
                    seen.append(st)
                if st == ATTACK100LOOP:
                    reached = st
                    break
                if st == WAIT and i > 4 and len(seen) > 1:
                    break
            self.log(f"rapidjab state path: "
                     f"{[state_name(s) for s in seen]}")
            if reached != ATTACK100LOOP:
                self.p.neutral()
                raise MoveError(
                    f"rapidjab never reached Attack100Loop "
                    f"(last state = {state_name(self.player.state())})")
            # NOTE: execute() returns frozen on Attack100Loop frame ~1; the
            # caller's capture loop steps further (into Attack100End, the big
            # finisher burst) with the pipe's last toggle input. The loop's
            # per-iteration sparks + the End burst both spawn s11/s15/s91.
            return self.player.state()
        elif move == BOMBTHROW:
            # Link down-B pulls a bomb into his hand, THEN toss it forward so it
            # flies + detonates on the (pinned) bag. Two phases:
            #  1) down-B: PRESS B with stick down -> Link enters his SpecialLw
            #     pull (a CharSpecific state), ending with the bomb in hand
            #     (fighter returns toward Wait/hold while holding the item).
            #  2) toss forward: hold the stick forward + PRESS A -> item
            #     LightThrowF (94). Z is swallowed by the pipe (lesson 15), and
            #     an item toss is A (not grab), so A+forward is the throw.
            # The bomb then arcs forward and explodes on contact.
            self.p.frame(["SET MAIN 0.500 0.000", "PRESS B", "FLUSH"])
            # reach the pull (char-specific special-lw), then ride it out until
            # Link is holding the bomb (back near Wait / a non-special state).
            try:
                self._step_until(lambda s: s >= CHAR_SPECIFIC_BASE, 8,
                                 "bomb-pull SpecialLw")
            except MoveError:
                pass
            self.p.neutral()
            # ride the pull animation until Link settles holding the bomb
            for _ in range(60):
                self._step(1)
                st = self.player.state()
                if st is not None and st < CHAR_SPECIFIC_BASE and st == WAIT:
                    break
            # toss forward: stick forward a few frames, then A (light throw F)
            self.p.frame([f"SET MAIN {self._fwd():.3f} 0.500", "FLUSH"])
            self._step(2)
            reached = None
            self.p.frame([f"SET MAIN {self._fwd():.3f} 0.500", "PRESS A",
                          "FLUSH"])
            for _ in range(10):
                self._step(1)
                st = self.player.state()
                if st in LIGHT_THROW_STATES:
                    reached = st
                    break
            self.p.neutral()
            self.log(f"bombthrow: throw state = {state_name(self.player.state())}")
            if reached is None:
                raise MoveError(
                    f"bombthrow never reached a LightThrow state "
                    f"(last = {state_name(self.player.state())})")
            return self.player.state()
        elif move == "jab":
            self._trigger(["PRESS A"], exp, move)
        elif move == "ftilt":
            # in-game 0.60: above the 0.25 AttackS3 gate, below the 0.8 smash
            # gate. The OLD value (pipe 0.800) was 0.95 in the engine and always
            # produced AttackS4S -- see the pipe-scale note in the docstring.
            self.p.frame([f"SET MAIN {self._fwd_stick(TILT_HOLD):.3f} 0.500",
                          "FLUSH"])
            self._step(3)  # let it settle into a walk; A now gives a TILT
            self._trigger(["PRESS A"], exp, move)
        elif move == "utilt":
            # in-game 0.60 up: under 0.6625, so no usmash and no tap-jump.
            # (pipe 0.700 was 0.63 -- it worked, but by 0.03 of headroom.)
            self.p.frame([f"SET MAIN 0.500 {stick(TILT_HOLD):.3f}", "FLUSH"])
            self._step(3)
            self._trigger(["PRESS A"], exp, move)
        elif move == "dtilt":
            # in-game -0.60 down: past the -0.25 AttackLw3 gate, short of the
            # -0.6625 dsmash gate. Deliberately NOT a full crouch -- full down
            # is a dsmash input on the pipe (the old recipe's AttackLw4), and
            # AttackLw3 does not require Squat, only stick-down + A.
            self.p.frame([f"SET MAIN 0.500 {stick(-TILT_HOLD):.3f}", "FLUSH"])
            self._step(3)
            self._trigger(["PRESS A"], exp, move)
        elif move == "fsmash":
            self._trigger([f"SET C {self._fwd():.3f} 0.500"], exp, move)
        elif move == "usmash":
            # pipe y convention: 1.0 = UP (these two were swapped until the
            # Mewtwo usmash audit 2026-07: 'usmash' produced AttackLw4)
            self._trigger(["SET C 0.500 1.000"], exp, move)
        elif move == "dsmash":
            self._trigger(["SET C 0.500 0.000"], exp, move)
        elif move == "dashattack":
            # THREE phases, because a dash needs a stick a dash attack can't
            # tolerate. A Dash only starts at >= 0.8 (ftCo_Dash_CheckInput), but
            # Dash's IASA runs ftCo_AttackS4_8008C114 FIRST and that turns A
            # into a forward SMASH whenever the stick is still >= 0.8 -- which
            # is exactly what the old recipe did (AttackS4S every time). It also
            # only offers AttackDash after anim frame 4 (ftCommonData x44), so:
            #   1) full deflection -> Dash
            #   2) ease back to 0.70 (> 0.625 so the dash keeps going,
            #      < 0.8 so the smash branch declines)
            #   3) ride past dash anim frame 4, then A -> AttackDash
            self.p.frame([f"SET MAIN {self._fwd_stick(1.0):.3f} 0.500", "FLUSH"])
            self._step_until(lambda s: s in (DASH, RUN), 8, "dash")
            self.p.frame([f"SET MAIN {self._fwd_stick(DASH_HOLD):.3f} 0.500",
                          "FLUSH"])
            self._step(5)
            self._trigger(["PRESS A"], exp, move)
        elif move == RUN_MOVE:
            # No _trigger and no neutral(): the run must still be PLAYING when
            # the caller steps and captures. Dash (20) comes first and lasts
            # ~11-15 frames, so wait for RUN (21) specifically or every capture
            # lands on the dash lunge instead of the run cycle.
            self.p.frame([f"SET MAIN {self._fwd_stick(1.0):.3f} 0.500", "FLUSH"])
            self._step_until(lambda s: s == RUN, 40, "Run (21)")
            return self.player.state()
        elif move in HELD_MOVES:
            # No _trigger: it neutral()s on entry, which would drop the pose
            # (the shield bubble / egg, the crouch). Hold past return; the
            # caller captures, then lets go (neutral(), or the next reset()).
            held = HELD_MOVES[move]
            family = held_states(move, self.player.kind())
            self.p.frame(list(held["press"]) + ["FLUSH"])
            self._step_until(lambda s: s in family, HELD_REACH, held["what"])
            return self.player.state()
        elif move == "grab":
            # Use L(shield)+A, NOT raw Z: a bare "PRESS Z" is SWALLOWED by the
            # Slippi named-pipe controller and produces NO grab (15f of held Z
            # from Wait stays in Wait -- verified 2026-07-02, Link hookshot
            # re-probe). Shield+A grabs reliably: L press -> A -> Catch (212),
            # and for Link the tether follows into CapturePulled/CaptureWait
            # (226/227). This corrects the earlier "grab window too short"
            # misdiagnosis (research/docs-research/effect-maps/efcodata.md §6b): the
            # window was never the blocker, Z-on-pipe was. max_steps=14 keeps
            # room for Link's slow tether startup.
            self.p.frame(["PRESS L", "FLUSH"])
            self._step(3)   # raise shield so A becomes a grab, not a jab
            self._trigger(["PRESS A"], exp, move, max_steps=14)
        elif move in GRAB_FOLLOWUPS:
            # A throw or pummel only exists while an opponent is HELD, so this
            # is the one family of recipes that cannot run solo: it needs a bag
            # parked inside grab range (boot_match bag=<char> bag_pos="6,0").
            # Chain: L+A grab (Z is swallowed by the pipe -- see `grab`) ->
            # Catch -> CatchPull -> CatchWait, and only a CONNECTED grab reaches
            # CatchWait; a whiff drops out through CatchCut to Wait.
            self.p.frame(["PRESS L", "FLUSH"])
            self._step(3)
            self.p.frame(["PRESS A", "FLUSH"])
            self._step_until(lambda s: s in CATCH_STATES, 14, "Catch")
            self.p.neutral()
            try:
                self._step_until(lambda s: s == CATCH_WAIT, 30, "CatchWait")
            except MoveError:
                raise MoveError(
                    f"{move}: the grab did not connect (state = "
                    f"{state_name(self.player.state())}). A throw needs a bag "
                    f"inside grab range -- boot with bag=<char> bag_pos=\"6,0\"."
                ) from None
            if move == PUMMEL:
                self._trigger(["PRESS A"], exp, move)
            else:
                # a throw is a stick DIRECTION while holding -- no attack button
                xy = {"fthrow": (self._fwd(), 0.5), "bthrow": (self._back(), 0.5),
                      "uthrow": (0.5, 1.0), "dthrow": (0.5, 0.0)}[move]
                self._trigger([f"SET MAIN {xy[0]:.3f} {xy[1]:.3f}"], exp, move,
                              max_steps=10)
        elif move == "dashgrab":
            self.p.frame([f"SET MAIN {self._fwd():.3f} 0.500", "FLUSH"])
            self._step_until(lambda s: s in (DASH, RUN), 8, "dash")
            # boost-grab -> CatchDash (214), Link's HOOKSHOT tether grab. Z is
            # swallowed on the pipe; L-before-A during a run rolls (EscapeF);
            # A-before-L on the SAME frame (stick still held forward) is the
            # only combo that grabs -- verified 2026-07-02, Link hookshot probe.
            self._trigger(["PRESS A", "PRESS L"], exp, move, max_steps=14)
        elif move == "taunt":
            self._trigger(["PRESS D_UP"], exp, move)

        elif move in SPECIALS or move in AIR_SPECIALS:
            base = AIR_SPECIALS.get(move, move)
            if move in AIR_SPECIALS:
                # rise to apex first, then fire the B-move in the air. `rise`
                # controls how high above jumpsquat we are when it fires (a
                # bigger rise = more airspace for up-B fortress / Firefox).
                self._to_air(rise=rise)
            # (named stick_xy, not `stick`: the module-level stick() converter
            # is called elsewhere in this same function)
            stick_xy = {"neutralb": None,
                        "sideb": (self._fwd(), 0.5),
                        "upb": (0.5, 1.0),
                        "downb": (0.5, 0.0)}[base]
            lines = ["PRESS B"]
            if stick_xy:
                lines = [f"SET MAIN {stick_xy[0]:.3f} {stick_xy[1]:.3f}",
                         "PRESS B"]
            self.p.frame(lines + ["FLUSH"])
            self._step_until(lambda s: s >= CHAR_SPECIFIC_BASE, 6, move)
            self.p.neutral()
        else:
            raise MoveError(f"unknown move '{move}' (known: {', '.join(MOVES)})")

        return self.player.state()
