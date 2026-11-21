"""Shared core for source-native Ultimate -> Melee character ports.

See ULTIMATE_PORT_PIPELINE.md. This module holds the parts that are genuinely
character-agnostic so a second or third port is configuration, not a fork of
the first one's scripts.

WHY EVERY OWNED ROW NEEDS A NATIVE CLIP
---------------------------------------
On the DONOR route an unmapped action simply keeps the donor's figatree, which
was authored on the donor's own skeleton -- correct, just not ported. On the
SOURCE-NATIVE route that is not safe, because `ftAnim` binds a figatree's node
array POSITIONALLY to `fp->parts[i]` (`ftanim.c:607-636`: `while (*cur_node !=
-1) { ... i++; }`). There is no name binding. A 76-node donor figatree loaded
against a 104-node native rig therefore drives the first 76 parts -- entirely
different bones.

So the catalog is not "the rows we chose to port". It is EVERY owned row, each
with an explicit disposition:

    CONVERT     a genuine source counterpart exists -> convert it
    RETIME      same, but the engine depends on the donor's exact duration,
                so the source motion is resampled into the donor frame count
    SYNTHESIZE  no counterpart -> emit a native-domain clip holding a chosen
                pose for the donor's frame count (node-correct, timing-exact)
    RESERVED    owned by another system (the PT transform); still synthesized,
                because the node count must be right either way, but flagged
                so nobody "improves" it later

`SYNTHESIZE` is not a nice-to-have. Without it an unported row is a garbage
pose, not a donor pose.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import numpy as np

from .rigmap import euler_xyz
from . import rotation_charts, scale_helpers

CONVERT, RETIME, SYNTHESIZE, RESERVED = "CONVERT", "RETIME", "SYNTHESIZE", "RESERVED"
EXTRA_MOTION = "__engine_ExtraMotion"


@dataclass(frozen=True)
class Donor:
    root: str            # ftData root name
    pl: str              # vanilla Pl file
    aj: str              # vanilla AJ file
    symbol_prefix: str   # PlyKoopa5K_Share
    joints: int          # measured costume joint count


@dataclass(frozen=True)
class Species:
    name: str
    ultimate: str        # source fighter directory (plizardon, ...)
    donor: Donor
    # Melee motion -> source stem, for pairs the name rule cannot reach.
    overrides: dict = field(default_factory=dict)
    # Melee motions whose duration the engine depends on. `moves.c` splits the
    # PT dodge at CYCLE_SWAP_FRAME to drive the transform, so a different-length
    # Escape clip moves the swap; the locomotion cycles are rate-driven against
    # ground speed, so a 4x-long Run reads as slow motion.
    retime: frozenset = frozenset()
    # Melee motions owned by another system; never convert, always flag.
    reserved: frozenset = frozenset()


BOWSER = Donor("ftDataKoopa", "PlKp.dat", "PlKpAJ.dat", "PlyKoopa5K_Share", 76)
POPO = Donor("ftDataPopo", "PlPp.dat", "PlPpAJ.dat", "PlyPopo5K_Share", 49)
MARTH = Donor("ftDataMars", "PlMs.dat", "PlMsAJ.dat", "PlyMars5K_Share", 90)

# The PT transform is driven by `src/moves.c`, which splits the donor's dodge at
# CYCLE_SWAP_FRAME (14) and owns down-B outright. Both are RESERVED for all
# three Pokemon, not just the one the note was originally written about.
#
# CANDIDATE IMPROVEMENT, deliberately not taken: all three source sets DO ship
# the Pokemon-Change animation (`d03speciallwin` / `d03speciallwout` and their
# aerial pair). Because every row is retimed to the donor's duration, converting
# them would preserve the total length `moves.c` depends on -- but not its
# internal beats, and CYCLE_SWAP_FRAME is an internal beat. Someone has to read
# moves.c and decide; until then these hold a pose, which is node-correct and
# visually dull rather than node-wrong and broken.
_PT_RESERVED = frozenset({"SpecialLw", "SpecialAirLw", "SpecialLwLanding"})
_PT_RETIME = frozenset({"EscapeN", "EscapeF", "EscapeB", "EscapeAir",
                        "WalkSlow", "WalkMiddle", "WalkFast", "Run", "Dash",
                        "Turn", "TurnRun", "RunBrake", "WalkBrake"})
# Melee loops these states against ground speed, so the row holds exactly ONE
# gait cycle. Ultimate's clip may hold several: Charizard's `a02run` is 81
# frames and recurs EXACTLY (quaternion similarity 1.0000) at frame 40 -- two
# cycles. Resampling 81 -> Melee's 20 both merges the cycles and doubles the
# angular rate, which is the single worst sub-frame error in the bank (13.14).
CYCLIC = frozenset({"Run", "WalkSlow", "WalkMiddle", "WalkFast", "Dash"})

SPECIES = {
    "charizard": Species(
        "charizard", "plizardon", BOWSER,
        overrides={
            "HeavyWalk1": "h03heavywalk", "HeavyWalk2": "h03heavywalk",
            "ItemScrewAir": "h07itemscrewfall",
            "SpecialSEndB": "d01specialsend", "SpecialSEndF": "d01specialsend",
            "SpecialAirSEndB": "d01specialairsend", "SpecialAirSEndF": "d01specialairsend",
            "SpecialSHit": "d01specialsblown", "SpecialAirSHit": "d01specialairsblown",
            "Wait1": "a00wait1", "Wait2": "a00wait2",
            "RunBrake": "a02runbraker", "JumpAerialB": "a03jumpaerialf2",
        },
        retime=_PT_RETIME, reserved=_PT_RESERVED),
    # Popo splits several states Ultimate keeps whole (angled tilts, and the
    # Ice Climbers' multi-phase specials). Melee's split rows take the same
    # parent clip -- the alternative is leaving two thirds of a move on a
    # 49-node donor clip, which on a native rig is garbage, not a fallback.
    "ivysaur": Species(
        "ivysaur", "pfushigisou", POPO,
        overrides={
            "HeavyWalk1": "h03heavywalk", "HeavyWalk2": "h03heavywalk",
            "AttackS3HiS": "c01attacks3s", "AttackS3LwS": "c01attacks3s",
            "SpecialHiStart": "d02specialhi", "SpecialHiThrow": "d02specialhi",
            "SpecialHiThrow2": "d02specialhi",
            "SpecialAirHiStart": "d02specialairhi", "SpecialAirHiThrow": "d02specialairhi",
            "SpecialAirHiThrow2": "d02specialairhi",
            "SpecialS1": "d01specials", "SpecialS2": "d01specials",
            "SpecialAirS1": "d01specialairs", "SpecialAirS2": "d01specialairs",
            "ItemScrewAir": "h07itemscrewfall",
        },
        retime=_PT_RETIME, reserved=_PT_RESERVED),
    "squirtle": Species(
        "squirtle", "pzenigame", POPO,
        overrides={
            "HeavyWalk1": "h03heavywalk", "HeavyWalk2": "h03heavywalk",
            "AttackS3HiS": "c01attacks3hi", "AttackS3LwS": "c01attacks3lw",
            # Squirtle's neutral-B is a charge/shot pair; Melee's SpecialN is
            # one row, so it takes the SHOT.
            "SpecialN": "d00specialnshot", "SpecialAirN": "d00specialairnshot",
            "SpecialHiStart": "d02specialhi", "SpecialHiThrow": "d02specialhi",
            "SpecialHiThrow2": "d02specialhi",
            "SpecialAirHiStart": "d02specialairhi", "SpecialAirHiThrow": "d02specialairhi",
            "SpecialAirHiThrow2": "d02specialairhi",
            "SpecialS1": "d01specials", "SpecialS2": "d01specials",
            # Squirtle has no plain `d01specialairs`; his aerial side-B is
            # start/end/hit phases. The catalog's absent-clip check caught this.
            "SpecialAirS1": "d01specialairsstart", "SpecialAirS2": "d01specialairsend",
            "ItemScrewAir": "h07itemscrewfall",
        },
        retime=_PT_RETIME, reserved=_PT_RESERVED),
}

# Duck Hunt (2026-11): the first fighter with a body no Melee fighter has, so the first to take its own skeleton by
# the one-shot driver's rules rather than a campaign's. Marth gives the states and the tables; nothing is retimed to
# his clips (the driver writes every script from the source's own frames) and nothing is reserved.
SPECIES["duckhunt"] = Species("duckhunt", "duckhunt", MARTH)
# (A fighter on its own skeleton needs no row here: `own_bank.default_jobs` takes one that has none as itself on
# Marth, with no exceptions. Wolf, the second such fighter, has none.)

# ---------------------------------------------------------------------------
# Slot bindings. `None` = this fighter genuinely has no such bone, which the
# parts table stores as FTPART_INVALID (0xFF). Legal in joint_to_part,
# CONDITIONAL in part_to_joint (NATIVE_SKELETON_CONSUMERS.md): every None needs
# its consumers shown unreachable or guarded before stage 4 installs the table.
#
# DIGIT NUMBERING IS NOT A UNIVERSAL CONVENTION. `digits.py` measures each
# digit's root direction in the parent hand's frame and picks the one whose
# MINIMUM separation from the others is largest. Measured:
#     Charizard  digits 1/2/5, thumb = 5   (33.9 deg vs 29.9)   <- matches the
#                                                                  recorded rule
#     Squirtle   digits 1/2/3, thumb = 1   (49.2 deg vs 39.5)   <- BREAKS it
#     Ivysaur    one digit per hand (Finger?51); nothing to compare, so the
#                digit-5 name and its perpendicular offset are the only evidence
# Do not carry "digit 5 is the thumb" to a new fighter without re-measuring.
#
# A NEW FIGHTER NEEDS NO TABLE HERE. `fighters.bindings` binds one that has none
# by the game's own bone names and measures the thumb the way `digits.py` did
# (`fighters.thumb`); on the rest poses of the game's own skeletons that gives
# every table below exactly, and Wolf's, which the cold trial wrote by hand
# (tests/test_fighters.py). These stay as what was measured before, and are
# used as they are for their fighters.
# ---------------------------------------------------------------------------
_EMPTY = {s: None for s in (
    "lLegA lLeg lKnee lFootA lFoot rLegA rLeg rKnee rFootA rFoot waistB bust "
    "lClavicle lShoulderA lShoulder lArm lHand lIndex1 lIndex2 lMiddle1 lMiddle2 "
    "lRing1 lRing2 lPinky1 lPinky2 lHave lThumb1 lThumb2 neckN headN "
    "rClavicle rShoulderA rShoulder rArm rHand rIndex1 rIndex2 rMiddle1 rMiddle2 "
    "rRing1 rRing2 rPinky1 rPinky2 rHave rThumb1 rThumb2 throw").split()}

_ROOTS = dict(top="__engine_Top", trans="Trans", xRot="__engine_XRot",
              yRot="__engine_YRot", hip="Hip", waist="Waist", extra=EXTRA_MOTION)

BINDINGS = {
    "charizard": {**_EMPTY, **_ROOTS,
        "bust": "Bust", "neckN": "Neck", "headN": "Head", "throw": "Throw",
        "lLeg": "LegL", "lKnee": "KneeL", "lFoot": "FootL",
        "rLeg": "LegR", "rKnee": "KneeR", "rFoot": "FootR",
        "lClavicle": "ClavicleL", "lShoulder": "ShoulderL", "lArm": "ArmL", "lHand": "HandL",
        "rClavicle": "ClavicleR", "rShoulder": "ShoulderR", "rArm": "ArmR", "rHand": "HandR",
        "lIndex1": "FingerL11", "lIndex2": "FingerL12",
        "lMiddle1": "FingerL21", "lMiddle2": "FingerL22",
        "lThumb1": "FingerL51", "lThumb2": "FingerL52", "lHave": "HaveL",
        "rIndex1": "FingerR11", "rIndex2": "FingerR12",
        "rMiddle1": "FingerR21", "rMiddle2": "FingerR22",
        "rThumb1": "FingerR51", "rThumb2": "FingerR52", "rHave": "HaveR"},
    "ivysaur": {**_EMPTY, **_ROOTS,
        "bust": "Bust", "neckN": "Neck", "headN": "Head", "throw": "Throw",
        "lLeg": "LegL", "lKnee": "KneeL", "lFoot": "FootL",
        "rLeg": "LegR", "rKnee": "KneeR", "rFoot": "FootR",
        "lClavicle": "ClavicleL", "lShoulder": "ShoulderL", "lArm": "ArmL", "lHand": "HandL",
        "rClavicle": "ClavicleR", "rShoulder": "ShoulderR", "rArm": "ArmR", "rHand": "HandR",
        "lThumb1": "FingerL51", "rThumb1": "FingerR51",
        # Ivysaur has ONE item-hold bone, not a pair. Melee holds items in the
        # right hand, so `Have` takes rHave and lHave stays null.
        "rHave": "Have"},
    "squirtle": {**_EMPTY, **_ROOTS,
        "bust": "Bust", "neckN": "Neck", "headN": "Head", "throw": "Throw",
        "lLeg": "LegL", "lKnee": "KneeL", "lFoot": "FootL",
        "rLeg": "LegR", "rKnee": "KneeR", "rFoot": "FootR",
        "lClavicle": "ClavicleL", "lShoulder": "ShoulderL", "lArm": "ArmL", "lHand": "HandL",
        "rClavicle": "ClavicleR", "rShoulder": "ShoulderR", "rArm": "ArmR", "rHand": "HandR",
        # MEASURED: digit 1 is the thumb on this fighter, not digit 5.
        "lThumb1": "FingerL11", "lIndex1": "FingerL21", "lMiddle1": "FingerL31",
        "rThumb1": "FingerR11", "rIndex1": "FingerR21", "rMiddle1": "FingerR31",
        "lHave": "HaveL", "rHave": "HaveR"},
}

# A dog: paws, no fingers. Its front legs are the arms' slots and its hind legs the legs'; an item is held at the
# right front paw. (The duck's own bones are bound to no slot: nothing in the engine asks for a second body.)
BINDINGS["duckhunt"] = {**_EMPTY, **_ROOTS,
    "bust": "Bust", "neckN": "Neck", "headN": "Head", "throw": "Throw",
    "lLeg": "LegL", "lKnee": "KneeL", "lFoot": "FootL",
    "rLeg": "LegR", "rKnee": "KneeR", "rFoot": "FootR",
    "lClavicle": "ClavicleL", "lShoulder": "ShoulderL", "lArm": "ArmL", "lHand": "HandL",
    "rClavicle": "ClavicleR", "rShoulder": "ShoulderR", "rArm": "ArmR", "rHand": "HandR",
    "lHave": "HaveL", "rHave": "HaveR"}


# Ultimate's root chain is Trans -> Rot -> Hip on every skeleton surveyed.
ENGINE_PARENTS = {"Trans": ["__engine_Top"], "Rot": ["__engine_XRot", "__engine_YRot"]}
# Slots common code ROTATES, not just reads (ftCo_0C35.c:67,79; ftCo_Lift.c:147,160;
# ftCo_HammerTurn.c:45; ftCo_Damage.c:262,1190). None may sit under a chart helper.
ENGINE_WRITTEN = {"top": "__engine_Top", "trans": "Trans", "xRot": "__engine_XRot"}

VANILLA_POOL = 32768
PATCHED_POOL = 131040

# Explicit acceptance thresholds, declared BEFORE measuring, as the pipeline's
# falsifier section requires. Units are rig units; the Pokemon rigs are ~20 tall,
# so 0.05 is roughly a quarter of one percent of body height.
ACCEPTANCE = dict(
    integer_pivot=0.05,      # at the frames Melee normally plays
    fine_pivot=0.50,         # between frames, on the independent 1/16 grid
    basis=0.05,
    bytes=PATCHED_POOL,
)

# ...but an ABSOLUTE distance is not comparable across characters. Measured rig
# heights: Charizard 20.58 units, Ivysaur 9.44, Squirtle 8.25. The same 0.05 is
# 0.24% of Charizard and 0.61% of Squirtle. Report error as a fraction of
# stature as well, and prefer these when comparing characters.
RELATIVE_ACCEPTANCE = dict(integer_pivot=0.0025, fine_pivot=0.025, basis=0.05)


def rig_height(rig):
    ys = np.array([rig.world[j][1, 3] for j in rig.order])
    return float(ys.max() - ys.min())


def relative_acceptance(height):
    """Absolute thresholds for one rig, from the stature-relative fractions."""
    if not np.isfinite(height) or height <= 0:
        raise ValueError("Positive finite rig height required")
    out = {k: v * height for k, v in RELATIVE_ACCEPTANCE.items() if k != "basis"}
    out["basis"] = RELATIVE_ACCEPTANCE["basis"]      # dimensionless already
    out["bytes"] = PATCHED_POOL
    return out


def source_acceptance(height, *, capacity, skin_fraction):
    """Explicit target capacity and caller-declared source skin tolerance.

    relative_acceptance is retained for historical Trainer recipes. New source
    builders must not inherit its PATCHED_POOL default or guess a skin budget.
    """
    if type(capacity) is not int or capacity not in (32768,65504,131040):
        raise ValueError('Explicit supported animation capacity required')
    if type(height) not in (int,float) or not np.isfinite(height) or height<=0:
        raise ValueError('Positive finite rig height required')
    if type(skin_fraction) not in (int,float) or not np.isfinite(skin_fraction) or skin_fraction<=0:
        raise ValueError('Explicit positive source skin fraction required')
    base=relative_acceptance(height)
    return dict(integer_pivot=base['integer_pivot'],fine_pivot=base['fine_pivot'],basis=base['basis'],
                integer_skin=skin_fraction*height,fine_skin=skin_fraction*height,bytes=capacity)


# HSD renders an animated JObj scale below this as if it were this value, so
# anything under it is unrepresentable no matter what we encode.
HSD_SCALE_FLOOR = 1e-3


def sanitize_scale(raw, floor=HSD_SCALE_FLOOR):
    """Remove sub-floor and NEGATIVE source scale, in place, with a receipt.

    Ivysaur's `c01attacks3s` squashes `LeafL1`/`LeafR1` on Y through zero and
    slightly past it (min -0.019). That is ease-curve overshoot on a flattening
    leaf, not authored mirroring -- but a negative scale makes the joint's local
    rotation a REFLECTION, and `rotation_charts.choose` refuses those outright
    ("Chart selection requires shear-free local rotations"), so one clip blocked
    the whole rig freeze.

    Clamping |s| to the HSD floor is not a fudge: the engine cannot draw the
    sub-floor region either, so the frames in question render identically
    whichever sign they carry. What IS lost is a genuine mirror, if a fighter
    ever authors one -- hence the receipt, and the refusal to clamp anything
    whose magnitude is large enough to be real.
    """
    changed = {}
    for name, track in raw.tracks.items():
        s = np.asarray(track.s, dtype=float)
        negative = s < 0
        subfloor = np.abs(s) < floor
        if not negative.any() and not subfloor.any():
            continue
        # Distinguishing overshoot from an authored mirror is NOT a magnitude
        # test against the floor -- Ivysaur's overshoot reaches -0.019, which is
        # comfortably above it. The distinction is shape: overshoot dips through
        # zero on a track that is otherwise positive, a mirror is negative for
        # essentially the whole track. Test per axis.
        for axis in range(3):
            col = s[:, axis]
            if not (col < 0).any():
                continue
            positive_peak = float(col.max())
            dip = float(-col.min())
            starts_positive = col[0] > 0
            if not starts_positive or positive_peak <= 0 or dip > 0.05 * positive_peak:
                raise ValueError(
                    f"{name}.{'XYZ'[axis]}: scale runs to {col.min():.4f} against a "
                    f"positive peak of {positive_peak:.4f} -- that is an authored "
                    "mirror, not ease overshoot. Clamping would change the pose; "
                    "handle it explicitly.")
        track.s = np.clip(np.abs(s), floor, None)
        changed[name] = dict(samples=int((negative | subfloor).any(axis=1).sum()),
                             most_negative=float(s.min()),
                             axes=sorted({"XYZ"[k] for k in np.where(
                                 (negative | subfloor).any(axis=0))[0]}))
    return changed


# The gait chain. A locomotion cycle is defined by the LEGS: Melee loops these
# states against ground speed, so the legs are what must line up. Measuring
# whole-body similarity instead finds only the point where the clip returns to
# its start pose -- Charizard's wings and tail do not share the gait period, so
# a whole-body test reports "no cycle" on a run that repeats exactly at 40.
GAIT = ("Leg", "Knee", "Foot", "Toe")


def detect_cycle(raw, minimum=8, tolerance=0.01, joints=GAIT):
    """Fundamental GAIT period of a looping clip, in source frames, or None.

    Quaternion similarity against frame 0 over the leg chain only. The period
    is the first frame after the pose has actually departed (so a clip that
    barely moves cannot report period 1) at which the legs return.
    """
    joints = [tr.q for name, tr in raw.tracks.items()
              if len(tr.q) == raw.end + 1
              and any(name.startswith(pre) for pre in joints)]
    if not joints or raw.end + 1 < 2 * minimum:
        return None
    sim = np.min([np.abs(q @ q[0]) for q in joints], axis=0)
    departed = np.where(sim < 1 - 5 * tolerance)[0]
    if not len(departed):
        return None
    for f in range(max(minimum, int(departed[0]) + 1), raw.end + 1):
        if sim[f] >= 1 - tolerance:
            return f
    return None


def author_dense(rig, times, worlds, tau, *, project_shear=False, subframe=False, reducer=None):
    """`rig_benchmark.author`, but keys may land BETWEEN integer frames.

    `scalar_curves.reduce_track` takes its key-candidate indices as an argument
    and `rig_benchmark.author` always hands it the integer frames only -- which
    is why a tau ladder on a fast rotation flattens out: error is evaluated on
    every sample but no key can be placed where the error actually is. Measured
    on Charizard `c02attackhi3`, tightening tau 25x moved the worst pivot from
    1.38650 to 1.38706 while the UNREDUCED control sat at 4.9e-14.

    Editor key objects store floating point times, but packed FOBJ deltas are
    integers. Fractional evaluation is required to measure interpolation;
    fractional key locations need a separately validated playback clock.
    Changing slope-key ordering alone cannot add fractional packed timing.
    subframe=True is only an offline fitting experiment. The preserved
    FigaCodec explicitly rejects such keys rather than truncating their times.
    """
    from . import rig_benchmark as bench
    from .scalar_curves import reduce_track
    reducer=reduce_track if reducer is None else reducer
    if not callable(reducer):raise ValueError('Callable scalar reducer required')
    vectors = bench.local_vectors(rig, worlds, project_shear=project_shear)
    times = np.asarray(times, dtype=float)
    integers = [i for i, v in enumerate(times) if float(v).is_integer()]
    if len(worlds) != len(times) or len(integers) < 2:
        raise ValueError("Complete integer frame domain required")
    if not np.array_equal(times[integers], np.arange(int(times[-1]) + 1)):
        raise ValueError("Complete integer frame domain required")
    candidates = list(range(len(times))) if subframe else integers
    channels = {}
    for j in rig.order:
        rest = np.r_[rig.rest[j]["r"], rig.rest[j]["t"], rig.rest[j]["s"]]
        for col, typ in enumerate(bench.TYPES):
            values = vectors[j][:, col]
            if np.max(np.abs(values - rest[col])) <= 1e-10:
                continue
            tol = tau if typ in (1, 2, 3) else (tau * 2 if typ in (5, 6, 7) else 5e-5)
            channels[(j, typ)] = reducer(times, values, candidates, tol)
    return channels


def rig_from_meta(meta):
    rig = SimpleNamespace(**{k: meta[k] for k in ("order", "parent", "rest")},
                          local={}, world={})
    for j in rig.order:
        r = rig.rest[j]
        m = np.eye(4)
        m[:3, :3] = euler_xyz(r["r"]) * np.array(r["s"])
        m[:3, 3] = r["t"]
        rig.local[j] = m
        rig.world[j] = rig.world[rig.parent[j]] @ m if rig.parent[j] is not None else m
    return rig


def rebuild_helpers(frozen, source):
    """Reconstruct stage 1's intermediate scaled/charted rigs from the FROZEN file.

    Chart rotations are read back out of the frozen helpers' own rest
    orientations rather than re-derived from the catalog, so this cannot
    silently disagree with the file every later index is written against.
    """
    scaled = scale_helpers.extend_rig(source, sorted(frozen["provenance"]["scale_helpers"]))
    charts = {j: dict(rotation=euler_xyz(frozen["rest"]["__chart_before_" + j]["r"]).tolist(),
                      before=None, after=None)
              for j in frozen["provenance"]["chart_helpers"]}
    return scaled, rotation_charts.extend_rig(scaled, charts)


def owned_motions(fighter_dat, symbol_prefix):
    """Every action motion this fighter OWNS an animation for, with its
    vanilla figatree frame count -- the denominator a catalog must cover."""
    out = {}
    for action in fighter_dat.actions:
        if not action.anim_size or not action.symbol:
            continue
        if not action.symbol.startswith(symbol_prefix):
            continue          # e.g. PlyTaro (Giga Bowser) rides in the same bank
        out.setdefault(action.motion, action)
    return out


def build_catalog(species, owned, source_stems, existing_map):
    """Assign every owned row a disposition. Never silently drops one."""
    by_suffix = {stem[3:]: stem for stem in source_stems}
    rows = {}
    for motion in sorted(owned):
        if motion in species.reserved:
            rows[motion] = dict(tier=RESERVED, clip=None,
                                reason="owned by the PT transform (src/moves.c); "
                                       "synthesized on the native domain so the node "
                                       "count is right, but not an animation port")
            continue
        clip = (species.overrides.get(motion)
                or existing_map.get(motion)
                or by_suffix.get(motion.lower()))
        if clip is None:
            rows[motion] = dict(tier=SYNTHESIZE, clip=None,
                                reason="no source counterpart in this fighter's motion set")
        elif motion in species.retime:
            rows[motion] = dict(tier=RETIME, clip=clip,
                                reason="engine depends on this row's duration")
        else:
            rows[motion] = dict(tier=CONVERT, clip=clip, reason="direct counterpart")
    # Rows in the inherited map that are not owned rows at all.
    orphans = sorted(set(existing_map) - set(owned))
    return rows, orphans


