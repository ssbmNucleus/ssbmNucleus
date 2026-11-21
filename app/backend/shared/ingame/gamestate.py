"""
gamestate.py -- typed read of a fighter's live state (the "what is the game
doing right now" half of the harness; framestep.py is the "when" half).

Pointer chain (NTSC 1.02, validated by fsm_crash_probe / the ingame README):
  slot = 0x80453080 + 0xE90*port
  active = u8(slot + 0x0C)                       # transformed physical index
  gobj = u32(slot + 0xB0 + 4*active)             # active fighter GObj
  ft   = u32(gobj + 0x2C)                        # Fighter struct ("user_data")
Fighter struct offsets from the decomp (ft/types.h):
  +0x10  action state id (u32)  -- ftCommon_MotionState / char-specific >= 0x155
  +0x2C  facing_dir (f32, +1 right / -1 left)
  +0xB0  cur_pos (Vec3 f32 x,y,z)
  +0xE0  ground_or_air (u32: 0 = ground, 1 = air)
  +0x894 cur_anim_frame (f32) -- NOTE: FSM-rescaled mods distort this; count
         stepped frames since the state transition for frame-data semantics.
"""

from .motion_states import MOTION_STATES, CHAR_SPECIFIC_BASE

STATIC_PLAYER = 0x80453080
STATIC_STRIDE = 0xE90

# Handy state ids (see motion_states.py for the full table)
WAIT = 14
KNEE_BEND = 24            # jumpsquat
JUMP_F, JUMP_B = 25, 26
SQUAT, SQUAT_WAIT = 39, 40
DASH, RUN = 20, 21
ATTACK_STATES = {
    "jab": {44},
    "ftilt": {51, 52, 53, 54, 55},
    "utilt": {56},
    "dtilt": {57},
    "fsmash": {58, 59, 60, 61, 62},
    "usmash": {63},
    "dsmash": {64},
    "dashattack": {50},
    "nair": {65},
    "fair": {66},
    "bair": {67},
    "uair": {68},
    "dair": {69},
    "grab": {212},
    "dashgrab": {214},
    # grab follow-ups: only reachable when the grab CONNECTS, so they need a
    # bag parked inside grab range (moves.py raises with that hint on a whiff)
    "pummel": {217},
    "fthrow": {219},
    "bthrow": {220},
    "uthrow": {221},
    "dthrow": {222},
}
# Catch (212) -> CatchPull (213) -> CatchWait (216) is the connected-grab chain;
# CatchDash/CatchDashPull (214/215) are the dash-grab entry to the same hold.
# A WHIFF never reaches 216 -- it falls out through CatchCut (218) to Wait.
CATCH_STATES = frozenset({212, 213, 214, 215})
CATCH_WAIT = 216
APPEAL_STATES = {i for i, n in MOTION_STATES.items() if n.startswith("Appeal")}

# Several fighters run some NORMALS or their taunt through char-specific motion
# states (>= CHAR_SPECIFIC_BASE) instead of the common ones above: Peach's
# fsmash is AttackS4Club/Pan/Racket (349-351), Ness's smashes are his own
# AttackS4 / AttackHi4(+Charge/Release) / AttackLw4 yo-yo states, Link and
# Young Link taunt through AppealSR/SL (342/343), G&W's jab/dtilt/fsmash/nair/
# bair/uair are 341-349. Without them a perfectly good capture is discarded as
# "never reached fsmash (state = CharSpecific_350)". The ids are GENERATED from
# the decomp's per-FighterKind motion-state tables
# (devtools/gen_char_move_states.py), keyed on the INTERNAL kind at fp+0x04.
from .char_move_states import CHAR_MOVE_STATES  # noqa: E402


def attack_states(move, kind=None):
    """Expected state id(s) for `move` on a fighter of internal `kind`: the
    shared ftCommon state(s) plus any char-specific ones the decomp says that
    fighter's version of the move enters. None if the move has no table."""
    common = APPEAL_STATES if move == "taunt" else ATTACK_STATES.get(move)
    extra = CHAR_MOVE_STATES.get(kind, {}).get(move)
    if not extra:
        return common
    return frozenset(common or ()) | extra


def state_name(state_id):
    if state_id is None:
        return "?"
    if state_id >= CHAR_SPECIFIC_BASE:
        return f"CharSpecific_{state_id}"
    return MOTION_STATES.get(state_id, f"Unknown_{state_id}")


class Player:
    """Reader for one port's fighter. Resolve after the match is in-game."""

    def __init__(self, d, port=0):
        self.d = d
        self.port = port
        self.ft = None

    def resolve(self):
        """(Re)walk the pointer chain. Returns the ft address or None."""
        slot = STATIC_PLAYER + STATIC_STRIDE * self.port
        # Player_GetEntity maps logical entity zero through transformed[0].
        # A Trainer/Sheik transform can change both this index and the entity.
        physical = self.d.u8(slot + 0x0C)
        if physical not in (0, 1):
            self.ft = None
            return None
        gobj = self.d.u32(slot + 0xB0 + 4 * physical)
        self.ft = self.d.u32(gobj + 0x2C) if gobj else None
        return self.ft

    def _ft(self):
        return self.ft if self.ft else self.resolve()

    def state(self):
        ft = self._ft()
        return self.d.u32(ft + 0x10) if ft else None

    def kind(self):
        """Internal FighterKind (fp+0x04): Sheik 7, Popo 10, Nana 11, Zelda 19,
        G&W 24. NOT the external/CSS id used to pick the character."""
        ft = self._ft()
        return self.d.u32(ft + 0x04) if ft else None

    def costume_id(self):
        """The COSTUME SLOT the engine actually loaded for this port.

        `Fighter.x619_costume_id` (decomp src/melee/ft/types.h, fp+0x619). This
        is read back from the live fighter, not from the player block we wrote,
        which is the only way to tell "the build put the costume in slot 4" from
        "the match is wearing slot 0" -- a confusion that has been graded as
        evidence before.
        """
        ft = self._ft()
        return self.d.u8(ft + 0x619) if ft else None

    def identity(self):
        """Who is actually in the match: internal FighterKind + costume slot.

        Raw readings only; it issues no verdict. A caller comparing these with
        what it requested owns the comparison and its thresholds.
        """
        return {"kind": self.kind(), "costume_id": self.costume_id(),
                "port": self.port, "ft": self._ft(),
                "schema": "gale01-fighter-identity-v1"}

    def anim_frame(self):
        ft = self._ft()
        return self.d.f32(ft + 0x894) if ft else None

    def facing(self):
        ft = self._ft()
        return self.d.f32(ft + 0x2C) if ft else None

    def pos(self):
        ft = self._ft()
        if not ft:
            return None
        return (self.d.f32(ft + 0xB0), self.d.f32(ft + 0xB4))

    def airborne(self):
        ft = self._ft()
        v = self.d.u32(ft + 0xE0) if ft else None
        return None if v is None else v == 1

    def percent(self):
        ft = self._ft()
        return self.d.f32(ft + 0x1830) if ft else None

    def set_percent(self, pct):
        """Set between-trial damage percent and clear pending damage.

        +0x1838 is dmg.x1838_percentTemp, consumed as NEW damage by
        Fighter_UnkTakeDamage_8006CC30, not a HUD copy. Writing pct there
        would add it again on the next engine tick. Zeroing between reps keeps
        knockback minimal so it never gets launched off / knocked down across
        a long batch."""
        ft = self._ft()
        if not ft:
            return False
        ok = self.d.write_f32(ft + 0x1830, float(pct))
        cleared = self.d.write_f32(ft + 0x1838, 0.0)
        return ok and cleared

    def set_pos(self, x, y):
        """Teleport (writes cur_pos like the classic teleport codes do); the
        next stepped frame re-runs collision, so land on/above ground."""
        ft = self._ft()
        if not ft:
            return False
        return (self.d.write_f32(ft + 0xB0, float(x))
                and self.d.write_f32(ft + 0xB4, float(y)))

    def pose(self, joint_count, *, secondary=False):
        """Read full rig evidence while frozen; count comes from the costume."""
        from .pose import capture_pose
        return capture_pose(self.d, self._ft(), joint_count, secondary=secondary)

    def visibility(self, *, expected_count=None):
        """Read model-part selection/DObj flags, without a visibility verdict."""
        from .pose import capture_visibility
        return capture_visibility(self.d, self._ft(), expected_count=expected_count)

    def snapshot(self):
        st = self.state()
        af = self.anim_frame()
        pos = self.pos() or (None, None)
        return {
            "state": st,
            "state_name": state_name(st),
            "anim_frame": None if af is None else round(af, 2),
            "facing": self.facing(),
            "x": pos[0],
            "y": pos[1],
            "airborne": self.airborne(),
        }


# Damage / hitstun action states (ftCommon), so the harness can confirm the
# bag actually took a hit -- the on-hit verification signal. From the melee
# decomp motion-state enum: DamageHi1..DamageFlyRoll span 0x4B..0x5B.
DAMAGE_STATES = set(range(0x4B, 0x5C))   # 75..91: DamageHi1 ... DamageFlyRoll
# 183..204: DownBoundU ... PassiveCeil -- knocked to the floor and getting up.
# A body lying here is NOT in hitstun (so DAMAGE_STATES misses it) but it also
# cannot be grabbed, which silently fails every grab recipe after the first
# throw of a batch. park_bag waits these out too.
DOWNED_STATES = set(range(183, 205))


# --- the sub-character (Nana) ------------------------------------------------- #
# StaticPlayer.player_entity[2] (decomp src/melee/pl/player.h): +0xB0 is the
# fighter's own GObj, +0xB4 is its FOLLOWER -- "used for followers, such as
# Nana". Ice Climbers spawn Nana coincident with Popo (measured: x within 0.1,
# z -3.8), so an Ice Climbers capture is two bodies in the same space and
# neither is judgeable: at rest Nana hides exactly behind Popo, and the moment
# anything moves she smears across him.
FOLLOWER_ENTITY = 0xB4
NANA_KIND = 11          # FTKIND_NANA (fp+0x04)

# HSD_GObj.hsd_obj (+0x28) is the fighter's root HSD_JObj; HSD_JObj.flags is at
# +0x14 (sysdolphin baselib/jobj.h). HSD_JObjDispAll draws a node's OWN DObj
# when `flags & (trsp << 0x12)` and recurses into its children when
# `flags & (trsp << 0x1C)`, for trsp = OPA / XLU / TEXEDGE. Clearing both
# triples takes the whole model out of every render pass.
#
# Both halves are needed and the reason is instructive: a fighter is an
# ENVELOPE_MODEL, so the SKINNED BODY is the root's own DObj (bit 18) while the
# rigid props hang off children (bit 28). Clearing only the child bits removes
# Nana's mallet and leaves her standing there.
JOBJ_FLAGS = 0x14
JOBJ_ROOT_OBJ = 0x28
JOBJ_DISP_MASK = 0x701C0000     # (OPA|XLU|TEXEDGE) << 18  |  ... << 28


class Follower(Player):
    """A port's sub-character (Nana). Same reads as Player, resolved through
    StaticPlayer.player_entity[1] instead of [0]."""

    def _gobj(self):
        return self.d.u32(STATIC_PLAYER + STATIC_STRIDE * self.port
                          + FOLLOWER_ENTITY)

    def resolve(self):
        gobj = self._gobj()
        self.ft = self.d.u32(gobj + 0x2C) if gobj else None
        return self.ft

    def hide(self):
        """Take the follower out of every render pass, leaving the SIMULATION
        untouched -- she still exists, still follows, still lets Popo's moves
        behave normally; she simply isn't drawn.

        Why not just move her out of shot: `cur_pos` is engine-owned for a
        follower. Measured 2026-07-31 -- a z of -5000 written to Nana is back
        to -3.8 after ONE stepped frame, because her follow logic re-derives
        her position from Popo's every frame. And a position write with no
        frame after it does nothing at all on screen: the render loop (which
        keeps running while the game is debug-frozen) redraws from matrices
        that were baked during the last fighter UPDATE. That combination is
        how a "Nana is hidden" fix can look like it works -- she is normally
        COINCIDENT with Popo, so the failure is invisible until a move
        separates them. A render flag has neither problem: nothing rewrites
        it (verified across 25 stepped frames of running) and it takes effect
        on the very next presented frame, with no stepped frame required."""
        gobj = self._gobj()
        if not gobj:
            return False
        jobj = self.d.u32(gobj + JOBJ_ROOT_OBJ)
        if not jobj:
            return False
        flags = self.d.u32(jobj + JOBJ_FLAGS)
        if flags is None:
            return False
        return self.d.write_u32(jobj + JOBJ_FLAGS, flags & ~JOBJ_DISP_MASK)


def nana_of(d, port=0):
    """The port's Nana, or None when this fighter has no follower. Kind-checked
    (FTKIND_NANA) so nothing else that ever lands in player_entity[1] -- a
    dormant Zelda/Sheik twin, a future m-ex partner -- gets hidden by
    mistake."""
    f = Follower(d, port)
    if f.resolve() and f.kind() == NANA_KIND:
        return f
    return None


class Bag(Player):
    """The punching-bag second fighter (a HUMAN port with no controller). Same
    reader as Player, plus helpers to park it in front of the attacker so each
    move connects, and to confirm it entered a damage state (proof of a hit)."""

    def in_damage(self):
        st = self.state()
        return st is not None and st in DAMAGE_STATES

    def park_in_front(self, attacker, dx=8.0, dy=0.0):
        """Teleport the bag `dx` units in front of `attacker` (in the direction
        the attacker faces) at height `dy`. Call while frozen, before the move;
        the next stepped frame re-runs collision so keep dy >= 0 for ground."""
        apos = attacker.pos()
        if not apos or apos[0] is None:
            return False
        facing = attacker.facing() or 1.0
        bx = apos[0] + (dx if facing > 0 else -dx)
        self._pin_x = bx
        self._pin_y = (apos[1] or 0.0) + dy
        return self.set_pos(bx, self._pin_y)

    def pin(self):
        """Suppress knockback so the bag STAYS IN RANGE for rapid-jab / command
        -grab finishers (Attack100, Gerudo). Zero every velocity field the
        engine integrates -- self_vel (fp+0x80), kb_vel (fp+0x8C, the launch
        velocity), atk_shield_kb (fp+0x98), the ground velocity fp+0xEC/0xF0 --
        AND re-pin cur_pos to the last park spot, so a single hard hit can't
        push the bag out from under the attacker between frozen steps. Call once
        per stepped frame while a --bag-pin move is running. Percent zeroing
        alone is NOT enough: knockback = f(percent, damage, weight, ...) still
        has a base component at 0%, enough to knock a light bag airborne on the
        first jab (efcodata jab-finisher block). Returns True if written."""
        ft = self._ft()
        if not ft:
            return False
        for off in (0x80, 0x84, 0x88,      # self_vel x,y,z
                    0x8C, 0x90, 0x94,      # kb_vel x,y,z
                    0x98, 0x9C, 0xA0,      # atk_shield_kb x,y,z
                    0xEC, 0xF0, 0xF4):     # ground vel / ground kb vel
            self.d.write_f32(ft + off, 0.0)
        px = getattr(self, "_pin_x", None)
        if px is not None:
            self.set_pos(px, getattr(self, "_pin_y", 0.0))
        return True
