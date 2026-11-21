"""
gen_char_move_states.py -- regenerate shared/ingame/char_move_states.py from the Melee
decomp.

Some fighters run their NORMALS and taunts through character-specific action
states (>= 0x155) instead of the shared ftCommon ones, so the move recogniser
in shared/ingame/moves.py can't confirm them from the common table alone:

    Peach  fsmash  -> AttackS4Club / Pan / Racket   (349-351)
    Ness   fsmash  -> AttackS4, usmash -> AttackHi4 (+Charge/Release) ...
    Link   taunt   -> AppealSR / AppealSL           (342/343)
    G&W    jab / dtilt / fsmash / nair / bair / uair

Rather than hand-maintain those ids, this reads them from the decomp:

  1. src/melee/ft/ftdata.c `ftData_CharacterStateTables[FTKIND_MAX]` gives the
     per-FighterKind motion-state table, in FighterKind order (the internal
     kind at fp+0x04, which is what Player.kind() reads).
  2. Each table is declared `MotionState ftXx_Init_MotionStateTable[ftYy_MS_SelfCount]`;
     the SelfCount prefix names the enum it is indexed by (clones reuse their
     original's: Young Link's table is sized by ftLk_MS_SelfCount).
  3. That enum (`ftYy_MS_First = ftCo_MS_Count, ...` in some forward.h) gives
     every state's name and id.
  4. The state NAME decides which harness move it belongs to (MOVE_PATTERNS).

Run from app/backend:  python devtools/gen_char_move_states.py [--check]
(--check exits 1 if the committed file is stale). The decomp is located like
the harness MCP's `decomp` tool: $MELEE_DECOMP, a sibling `melee/` of any parent
directory, or ~/projects/melee.
"""

import argparse
import os
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from shared.ingame.motion_states import CHAR_SPECIFIC_BASE  # noqa: E402

OUT = BACKEND / "shared" / "ingame" / "char_move_states.py"

# Harness move -> regex anchored at the start of the state name (the part after
# `ftXx_MS_`). Anchoring keeps Peach's FloatAttackAirN (a float-cancel aerial,
# not what the `nair` recipe produces) and Falcon's item SwordSwing4 out.
MOVE_PATTERNS = (
    ("jab", r"Attack11$"),
    ("ftilt", r"AttackS3"),
    ("utilt", r"AttackHi3"),
    ("dtilt", r"AttackLw3"),
    ("fsmash", r"AttackS4"),
    ("usmash", r"AttackHi4"),
    ("dsmash", r"AttackLw4"),
    ("dashattack", r"AttackDash"),
    ("nair", r"AttackAirN"),
    ("fair", r"AttackAirF"),
    ("bair", r"AttackAirB"),
    ("uair", r"AttackAirHi"),
    ("dair", r"AttackAirLw"),
    ("taunt", r"Appeal"),
    # HELD states (moves.HELD_MOVES): Yoshi shields in his own egg states
    # (ftYs_MS_GuardOn_0..GuardOn_1, 341-345), never the common Guard 178-182.
    ("shield", r"Guard"),
    ("crouch", r"Squat"),
)

# The playable FighterKinds 0x00-0x1A. The bosses/extras after them (Master and
# Crazy Hand, the wireframes, Giga Bowser, Sandbag) are never harness targets,
# and Crazy Hand's enum doesn't even start at ftCo_MS_Count.
FIGHTER_NAMES = (
    "Mario", "Fox", "Captain Falcon", "Donkey Kong", "Kirby", "Bowser", "Link",
    "Sheik", "Ness", "Peach", "Popo", "Nana", "Pikachu", "Samus", "Yoshi",
    "Jigglypuff", "Mewtwo", "Luigi", "Marth", "Zelda", "Young Link",
    "Dr. Mario", "Falco", "Pichu", "Mr. Game & Watch", "Ganondorf", "Roy",
)


def decomp_root():
    cands = [Path(p) for p in (os.environ.get("MELEE_DECOMP", ""),) if p]
    cands += [p / "melee" for p in BACKEND.resolve().parents]
    cands.append(Path.home() / "projects" / "melee")
    for c in cands:
        if (c / "src" / "melee" / "ft" / "ftdata.c").is_file():
            return c.resolve()
    raise SystemExit("melee decomp not found -- set MELEE_DECOMP to the repo "
                     "root (must contain src/melee/ft/ftdata.c)")


def _strip_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def kind_tables(ft):
    """[table name or None] indexed by FighterKind."""
    src = _strip_comments((ft / "ftdata.c").read_text(encoding="utf-8"))
    m = re.search(r"ftData_CharacterStateTables\s*\[[^\]]*\]\s*=\s*\{(.*?)\};",
                  src, re.S)
    if not m:
        raise SystemExit("ftData_CharacterStateTables not found in ftdata.c")
    return [None if e == "NULL" else e
            for e in (s.strip() for s in m.group(1).split(",")) if e]


def table_enums(ft):
    """table name -> enum prefix it is sized by (`ftLk` for ftLk_MS_SelfCount)."""
    decl = re.compile(r"^MotionState\s+(\w+_Init_MotionStateTable)\s*"
                      r"\[\s*(ft\w+?)_MS_SelfCount\s*\]", re.M)
    out = {}
    for path in ft.rglob("*.c"):
        for m in decl.finditer(path.read_text(encoding="utf-8", errors="replace")):
            out[m.group(1)] = m.group(2)
    return out


def enum_states(ft, prefix):
    """{id: name} of the `<prefix>_MS_*` enum that starts at ftCo_MS_Count."""
    head = re.compile(rf"\b{prefix}_MS_\w+\s*=\s*ftCo_MS_Count\b")
    for path in ft.rglob("*.h"):
        src = _strip_comments(path.read_text(encoding="utf-8", errors="replace"))
        m = head.search(src)
        if not m:
            continue
        body = src[m.start():src.index("}", m.start())]
        states, value = {}, CHAR_SPECIFIC_BASE - 1
        for item in (s.strip() for s in body.split(",")):
            if not item:
                continue
            name, _, expr = (p.strip() for p in item.partition("="))
            if not name.startswith(f"{prefix}_MS_"):
                continue
            short = name[len(prefix) + 4:]
            if short in ("Count", "SelfCount"):
                break
            if expr == "ftCo_MS_Count":
                value = CHAR_SPECIFIC_BASE
            elif expr:
                value = int(expr, 0)
            else:
                value += 1
            states[value] = short
        return states
    raise SystemExit(f"no {prefix}_MS_* enum starting at ftCo_MS_Count")


def derive(root):
    """{kind: (table, {move: [(id, name), ...]})} for every kind whose table
    has at least one state a harness move recognises."""
    ft = root / "src" / "melee" / "ft"
    enums = table_enums(ft)
    cache, out = {}, {}
    for kind, table in enumerate(kind_tables(ft)[:len(FIGHTER_NAMES)]):
        if table is None:
            continue
        prefix = enums.get(table)
        if prefix is None:
            raise SystemExit(f"no declaration found for {table}")
        if prefix not in cache:
            cache[prefix] = enum_states(ft, prefix)
        moves = {}
        for sid, name in sorted(cache[prefix].items()):
            for move, pat in MOVE_PATTERNS:
                if re.match(pat, name):
                    moves.setdefault(move, []).append((sid, name))
                    break
        if moves:
            out[kind] = (table, moves)
    return out


def render(derived):
    lines = [
        '"""',
        "char_move_states.py -- GENERATED by devtools/gen_char_move_states.py from",
        "the Melee decomp (ftData_CharacterStateTables + each table's MS enum).",
        "Do not edit by hand; re-run the generator.",
        "",
        "FighterKind (fp+0x04) -> harness move -> the character-specific action",
        "states (>= 0x155) that move legitimately enters, IN ADDITION to the shared",
        "ftCommon states in gamestate.ATTACK_STATES / APPEAL_STATES (and, for the",
        "held moves, moves.HELD_MOVES).",
        '"""',
        "",
        "CHAR_MOVE_STATES = {",
    ]
    for kind, (table, moves) in sorted(derived.items()):
        lines.append(f"    {kind}: {{  # {FIGHTER_NAMES[kind]} ({table})")
        for move, _pat in MOVE_PATTERNS:
            if move not in moves:
                continue
            ids = ", ".join(str(s) for s, _ in moves[move])
            names = ", ".join(n for _, n in moves[move])
            lines.append(f'        "{move}": frozenset({{{ids}}}),  # {names}')
        lines.append("    },")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the committed table is stale")
    args = ap.parse_args()
    text = render(derive(decomp_root()))
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"{OUT.name} is stale -- re-run {Path(__file__).name}")
            return 1
        print(f"{OUT.name} is up to date")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
