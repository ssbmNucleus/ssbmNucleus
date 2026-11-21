"""
moves.py -- community move names over the fighter action table.

The action table is keyed by motion symbols (AttackS3S, SpecialNStart ...).
Players, the UI and the copilot speak in community names: ftilt, usmash,
neutralb, dthrow. This module is that mapping, and it is the ONLY vocabulary
the op surface accepts -- action indices exist underneath for the harness's
sake but nobody should have to type one.

A `Move` groups one or more actions as named parts:
    ftilt    -> parts up / up_slight / mid / down_slight / down   (default mid)
    jab      -> parts 1 / 2 / 3                                    (default 1)
    neutralb -> parts start / loop / end ...  (character specific; default =
                the first part that carries a hitbox)
    nair     -> parts main / landing                               (default main)

Ids follow the in-game harness vocabulary (backend/shared/ingame) so a move name
means the same thing to the editor and to the thing that tests it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .commands import CREATE_HITBOX, THROW

# motion symbol -> (move id, part name or None)
STANDARD: dict[str, tuple[str, str | None]] = {
    "Attack11": ("jab", "1"), "Attack12": ("jab", "2"), "Attack13": ("jab", "3"),
    "Attack100Start": ("rapidjab", "start"), "Attack100Loop": ("rapidjab", "loop"),
    "Attack100End": ("rapidjab", "end"),
    "AttackDash": ("dashattack", None),
    "AttackS3Hi": ("ftilt", "up"), "AttackS3HiS": ("ftilt", "up_slight"),
    "AttackS3S": ("ftilt", "mid"), "AttackS3LwS": ("ftilt", "down_slight"),
    "AttackS3Lw": ("ftilt", "down"),
    "AttackHi3": ("utilt", None), "AttackLw3": ("dtilt", None),
    "AttackS4Hi": ("fsmash", "up"), "AttackS4HiS": ("fsmash", "up_slight"),
    "AttackS4S": ("fsmash", "mid"), "AttackS4LwS": ("fsmash", "down_slight"),
    "AttackS4Lw": ("fsmash", "down"),
    "AttackHi4": ("usmash", None), "AttackLw4": ("dsmash", None),
    "AttackAirN": ("nair", "main"), "AttackAirF": ("fair", "main"),
    "AttackAirB": ("bair", "main"), "AttackAirHi": ("uair", "main"),
    "AttackAirLw": ("dair", "main"),
    "LandingAirN": ("nair", "landing"), "LandingAirF": ("fair", "landing"),
    "LandingAirB": ("bair", "landing"), "LandingAirHi": ("uair", "landing"),
    "LandingAirLw": ("dair", "landing"),
    "Catch": ("grab", None), "CatchDash": ("dashgrab", None),
    "CatchAttack": ("pummel", None),
    "ThrowF": ("fthrow", None), "ThrowB": ("bthrow", None),
    "ThrowHi": ("uthrow", None), "ThrowLw": ("dthrow", None),
    "CliffAttackSlow": ("ledgeattack", "slow"), "CliffAttackQuick": ("ledgeattack", "fast"),
    "DownAttackU": ("getupattack", "faceup"), "DownAttackD": ("getupattack", "facedown"),
    "AppealS": ("taunt", None), "AppealSR": ("taunt", "right"), "AppealSL": ("taunt", "left"),
    "AppealR": ("taunt", "right"), "AppealL": ("taunt", "left"), "Appeal": ("taunt", None),
    # fighters without angled tilts/smashes, or with numbered hits
    "AttackS3": ("ftilt", "mid"), "AttackS31": ("ftilt", "mid"),
    "AttackS4": ("fsmash", "mid"), "AttackS41": ("fsmash", "mid"), "AttackS42": ("fsmash", "hit2"),
    # Samus: her neutral B has no N/S/Hi/Lw letter
    "Special": ("neutralb", "main"), "SpecialAir": ("airneutralb", "main"),
}

LABELS = {
    "jab": "Jab", "rapidjab": "Rapid Jab", "dashattack": "Dash Attack",
    "ftilt": "Forward Tilt", "utilt": "Up Tilt", "dtilt": "Down Tilt",
    "fsmash": "Forward Smash", "usmash": "Up Smash", "dsmash": "Down Smash",
    "nair": "Neutral Air", "fair": "Forward Air", "bair": "Back Air",
    "uair": "Up Air", "dair": "Down Air",
    "grab": "Grab", "dashgrab": "Dash Grab", "pummel": "Pummel",
    "fthrow": "Forward Throw", "bthrow": "Back Throw", "uthrow": "Up Throw",
    "dthrow": "Down Throw",
    "neutralb": "Neutral B", "sideb": "Side B", "upb": "Up B", "downb": "Down B",
    "airneutralb": "Neutral B (air)", "airsideb": "Side B (air)",
    "airupb": "Up B (air)", "airdownb": "Down B (air)",
    "ledgeattack": "Ledge Attack", "getupattack": "Getup Attack", "taunt": "Taunt",
}

CATEGORY = {
    "jab": "ground", "rapidjab": "ground", "dashattack": "ground", "ftilt": "ground",
    "utilt": "ground", "dtilt": "ground", "fsmash": "ground", "usmash": "ground",
    "dsmash": "ground",
    "nair": "aerial", "fair": "aerial", "bair": "aerial", "uair": "aerial", "dair": "aerial",
    "grab": "grab", "dashgrab": "grab", "pummel": "grab", "fthrow": "grab",
    "bthrow": "grab", "uthrow": "grab", "dthrow": "grab",
    "neutralb": "special", "sideb": "special", "upb": "special", "downb": "special",
    "airneutralb": "special", "airsideb": "special", "airupb": "special",
    "airdownb": "special",
    "ledgeattack": "misc", "getupattack": "misc", "taunt": "misc",
}

DEFAULT_PART = {"ftilt": "mid", "fsmash": "mid", "jab": "1", "rapidjab": "loop",
                "nair": "main", "fair": "main", "bair": "main", "uair": "main",
                "dair": "main", "ledgeattack": "fast", "getupattack": "faceup"}

# The order the UI lists moves in.
ORDER = ["jab", "rapidjab", "dashattack", "ftilt", "utilt", "dtilt",
         "fsmash", "usmash", "dsmash",
         "nair", "fair", "bair", "uair", "dair",
         "neutralb", "sideb", "upb", "downb",
         "airneutralb", "airsideb", "airupb", "airdownb",
         "grab", "dashgrab", "pummel", "fthrow", "bthrow", "uthrow", "dthrow",
         "ledgeattack", "getupattack", "taunt"]

_SPECIAL_RE = re.compile(r"^Special(Air)?(Hi|Lw|N|S)(.*)$")
_SPECIAL_ID = {"N": "neutralb", "S": "sideb", "Hi": "upb", "Lw": "downb"}

# Loose spellings the chat / a user may type -> canonical id.
ALIASES = {
    "forwardtilt": "ftilt", "sidetilt": "ftilt", "uptilt": "utilt", "downtilt": "dtilt",
    "forwardsmash": "fsmash", "sidesmash": "fsmash", "upsmash": "usmash",
    "downsmash": "dsmash", "neutralair": "nair", "neutralaerial": "nair",
    "forwardair": "fair", "forwardaerial": "fair", "backair": "bair",
    "backaerial": "bair", "upair": "uair", "upaerial": "uair", "downair": "dair",
    "downaerial": "dair", "dashatk": "dashattack", "da": "dashattack",
    "neutralspecial": "neutralb", "nb": "neutralb", "b": "neutralb",
    "sidespecial": "sideb", "forwardb": "sideb", "forwardspecial": "sideb",
    "upspecial": "upb", "downspecial": "downb",
    "forwardthrow": "fthrow", "backthrow": "bthrow", "upthrow": "uthrow",
    "downthrow": "dthrow", "jab1": ("jab", "1"), "jab2": ("jab", "2"),
    "jab3": ("jab", "3"), "rapidjabs": "rapidjab", "gentlemen": ("jab", "3"),
    "ledgeatk": "ledgeattack", "getup": "getupattack", "appeal": "taunt",
}


def normalize(name: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", str(name).lower())


def classify(motion: str | None, index: int) -> tuple[str, str | None]:
    """motion symbol -> (move id, part)."""
    if motion is None:
        return f"action{index}", None
    if motion in STANDARD:
        return STANDARD[motion]
    if motion.startswith("ThrowF") and len(motion) > 6:      # DK cargo carry
        return "fthrow", motion[6:].lower()
    if motion.startswith("AppealS") and len(motion) > 7:     # Fox/Falco taunt parts
        return "taunt", motion[7:].lower()
    m = _SPECIAL_RE.match(motion)
    if m:
        air, kind, rest = m.groups()
        mid = ("air" if air else "") + _SPECIAL_ID[kind]
        part = re.sub(r"[^0-9A-Za-z]+", "", rest).lower() or "main"
        return mid, part
    return motion.lower(), None


@dataclass
class Move:
    id: str
    label: str
    category: str
    parts: dict[str, int] = field(default_factory=dict)   # part -> action index
    default_part: str | None = None

    def action(self, part: str | None = None) -> int:
        if part is None:
            part = self.default_part
        if part is None or part not in self.parts:
            raise KeyError(f"{self.id}: unknown part {part!r} "
                           f"(parts: {list(self.parts)})")
        return self.parts[part]


class MoveTable:
    """All moves of one fighter, built from a FighterDat."""

    def __init__(self, fd):
        self.fd = fd
        self.moves: dict[str, Move] = {}
        for a in fd.actions:
            mid, part = classify(a.motion, a.index)
            mv = self.moves.get(mid)
            if mv is None:
                mv = Move(id=mid, label=LABELS.get(mid, a.motion or mid),
                          category=CATEGORY.get(mid, "other"))
                self.moves[mid] = mv
            key = part if part is not None else "main"
            # duplicate symbols (e.g. two SpecialNEnd rows) -> suffix the later
            if key in mv.parts:
                n = 2
                while f"{key}{n}" in mv.parts:
                    n += 1
                key = f"{key}{n}"
            mv.parts[key] = a.index
        for mv in self.moves.values():
            mv.default_part = self._default_part(mv)

    def _default_part(self, mv: Move) -> str | None:
        want = DEFAULT_PART.get(mv.id)
        if want in mv.parts:
            return want
        if len(mv.parts) == 1:
            return next(iter(mv.parts))
        # first part carrying a hitbox or throw, else the first part
        for part, idx in mv.parts.items():
            s = self.fd.script(idx)
            if s and (s.of_code(CREATE_HITBOX) or s.of_code(THROW)):
                return part
        return next(iter(mv.parts))

    # -- lookup -------------------------------------------------------------
    def resolve(self, move: str, part: str | None = None) -> tuple[Move, str]:
        """Loose name (+ optional part) -> (Move, part). Raises KeyError."""
        key = normalize(move)
        alias = ALIASES.get(key)
        if isinstance(alias, tuple):
            key, implied = alias
            part = part or implied
        elif alias:
            key = alias
        mv = self.moves.get(key)
        if mv is None:
            # allow a raw motion symbol or an action index as an escape hatch
            for cand in self.moves.values():
                if normalize(cand.label) == key:
                    mv = cand
                    break
        if mv is None and key.startswith("action") and key[6:].isdigit():
            idx = int(key[6:])
            for cand in self.moves.values():
                if idx in cand.parts.values():
                    mv = cand
                    part = part or next(p for p, i in cand.parts.items() if i == idx)
                    break
        if mv is None:
            raise KeyError(f"unknown move {move!r}")
        if part is None:
            part = mv.default_part
        else:
            part = normalize(part).replace("slight", "_slight") if "slight" in normalize(part) else normalize(part)
            if part not in mv.parts:
                # tolerate 'up'/'down' vs 'hi'/'lw'
                alt = {"hi": "up", "lw": "down", "high": "up", "low": "down"}.get(part, part)
                if alt not in mv.parts:
                    raise KeyError(f"{mv.id}: unknown part {part!r} (parts: {list(mv.parts)})")
                part = alt
        return mv, part

    def action_index(self, move: str, part: str | None = None) -> int:
        mv, part = self.resolve(move, part)
        return mv.parts[part]

    # -- listing ------------------------------------------------------------
    def listing(self, include_other: bool = False) -> list[dict]:
        """UI/JSON summary: every move with its parts and hitbox counts."""
        order = {m: i for i, m in enumerate(ORDER)}
        moves = sorted(self.moves.values(),
                       key=lambda m: (order.get(m.id, 10_000), m.id))
        out = []
        for mv in moves:
            if mv.category == "other" and not include_other:
                continue
            parts = []
            for part, idx in mv.parts.items():
                a = self.fd.actions[idx]
                hbs = self.fd.hitboxes(idx)
                parts.append({
                    "part": part, "action": idx, "motion": a.motion,
                    "hitboxes": len(hbs),
                    "throws": len(self.fd.throws(idx)),
                    "frames": _window(hbs),
                })
            out.append({"id": mv.id, "label": mv.label, "category": mv.category,
                        "default_part": mv.default_part, "parts": parts})
        return out


def _window(hbs: list[dict]) -> list[float] | None:
    if not hbs:
        return None
    start = min(h["frame_start"] for h in hbs)
    ends = [h["frame_end"] for h in hbs if h["frame_end"] is not None]
    return [start, max(ends) if ends else None]
