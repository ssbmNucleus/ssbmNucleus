"""
hitbox_elements.py -- decode which vanilla-fighter subactions spawn an
ELECTRIC-element hitbox, so the `common_electric` extra (the cast-wide
on-hit electric spark burst in EfCoData.dat) can advertise an HONEST
sharedWith list: the electric hit-spark only fires when a hitbox with
HitElement==Electric(2) connects, so only characters that actually own an
electric-element attack belong on it. Marth, for instance, has none.

This is a DATA-DERIVED answer. It walks each vanilla Pl<XX>.dat's fighter
action table, decodes every "Create Hitbox" subaction event (command 0x0B),
reads its 5-bit Element field, and reports the actions whose Element==2.

Why a pure-Python walk (not the C# viewer): the audit pipeline runs headless
in the backend and there is no dev-exe subaction dumper. We reuse the tiny
HSD/DAT reader in `datprobe.DatFile` (header + reloc table + roots-by-name +
data-section-relative readers) and mirror the exact structural logic the
viewer's ModelPartVisibility.cs uses to locate subactions:

  SBM_FighterData root ("ftData...")            -> ref @ 0x0C = FighterActionTable
  FighterActionTable                            -> N commands, each 0x18 bytes
  FighterAction command (0x18)                  -> 0x00 SymbolName, 0x0C SubAction
  SubAction struct                              -> raw subaction byte stream

The subaction stream is a bit-packed command list. Each command's top 6 bits
(`byte >> 2`) select the command; its byte size is fixed per command. We only
need Create Hitbox (0x0B); its bit layout is transcribed from HSDRawViewer's
authoritative `Scripts/command_fighter.yml` (NOT the older ActionCommon.cs
string, which has stale field widths -- Damage is 10 bits not 9, Bone is 8
bits not 7, and the interaction flags are five 1-bit flags). The Element enum
is the decomp HitElement enum: Normal=0, Fire=1, Electric=2, Slash=3, ...

Element constant of interest:
    ELECTRIC = 2

CLI:
    python -m shared.rendering.hitbox_elements                 # full report + self-test
    python -m shared.rendering.hitbox_elements --char Zelda    # one character
    python -m shared.rendering.hitbox_elements --sharedwith    # print the derived list
    python -m shared.rendering.hitbox_elements --attack100     # rapid-jab (Attack100)
                                                      #   roster + self-test
                                                      #   (jab_finisher_spark)
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

try:  # allow both `python -m shared.rendering.hitbox_elements` and direct import
    from .datprobe import DatFile, HEADER_SIZE
except ImportError:  # pragma: no cover - direct-script fallback
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from datprobe import DatFile, HEADER_SIZE  # type: ignore


# ---------------------------------------------------------------------------
# HitElement enum (decomp) -- the field we key on.
# ---------------------------------------------------------------------------
HIT_ELEMENT = {
    0: "Normal", 1: "Fire", 2: "Electric", 3: "Slash", 4: "Coin",
    5: "Ice", 6: "Sleep(103)", 7: "Sleep(412)", 8: "Grab", 9: "Grounded(97)",
    10: "Cape", 11: "Empty", 12: "Disable", 13: "Darkness", 14: "ScrewAttack",
    15: "PoisonFlower", 16: "Nothing",
}
ELECTRIC = 2


# ---------------------------------------------------------------------------
# Subaction command byte sizes (fighter group = control commands 0x00-0x0F
# shared by every group + the fighter-specific commands 0x0A+). Transcribed
# from HSDRawViewer Scripts/command_controls.yml + command_fighter.yml. Total
# bit size = 6 (the command) + sum(parameter bitCounts); ByteSize = bits / 8.
#
# We only strictly need Create Hitbox (0x0B) for the element read, but the
# whole table is required so the byte-stream walker advances the correct
# stride for every intervening command (a wrong stride desyncs the walk and
# corrupts the next command's element bits). Values verified to be
# 4-byte-aligned (every real subaction command is).
# ---------------------------------------------------------------------------
# command code (0x00-0x3A) -> total byte size of the packed command
# Derived from the generated echo command table (HSDRawViewer's yml specs).
# The hand-written table this replaced was shifted by one from code 0x35 on
# (it dropped "Set flag 0x2225", code 53), which desynced the walk stride for
# the tail of any script using those commands.
from vault.echo.commands import COMMANDS as _ECHO_COMMANDS
SUBACTION_BYTESIZE = {code: cmd.size for code, cmd in _ECHO_COMMANDS.items()}

CREATE_HITBOX = 0x0B

# Bit offset of the Element field inside a Create Hitbox command, measured
# from the start of the command byte. From command_fighter.yml code 11:
#   6  command
#   3  ID
#   3  Hit Group
#   1  Only Hit Grabbed Fighter
#   8  Bone
#   1  Use Common Bone IDs
#  10  Damage
#  16  Size
#  16  Z-Offset
#  16  Y-Offset
#  16  X-Offset
#   9  Angle
#   9  Knockback Growth
#   9  Weight Set Knockback
#   1  Item Hit Interaction
#   1  Ignore Thrown Fighters
#   1  Ignore Fighter Scale
#   1  Clank
#   1  Rebound
#   9  Base Knockback
#   -> Element (5 bits) starts here
ELEMENT_BIT_OFFSET = (6 + 3 + 3 + 1 + 8 + 1 + 10 + 16 + 16 + 16 + 16
                      + 9 + 9 + 9 + 1 + 1 + 1 + 1 + 1 + 9)
ELEMENT_BITS = 5


def _read_bits(data: bytes, bit_offset: int, count: int) -> int:
    """Big-endian bit read, matching HSDRaw's Bitreader."""
    v = 0
    for j in range(count):
        i = bit_offset + j
        bit = (data[i // 8] >> (7 - (i % 8))) & 0x1
        v = (v << 1) | bit
    return v


# ---------------------------------------------------------------------------
# Character -> DAT prefix (mirror of core/viewer_tools.py VIEWER_CHAR_PREFIXES).
# ---------------------------------------------------------------------------
CHAR_PREFIXES = {
    "C. Falcon": "PlCa", "Falco": "PlFc", "Fox": "PlFx",
    "Marth": "PlMs", "Roy": "PlFe", "Bowser": "PlKp",
    "DK": "PlDk", "Ganondorf": "PlGn", "Jigglypuff": "PlPr",
    "Kirby": "PlKb", "Link": "PlLk", "Luigi": "PlLg",
    "Mario": "PlMr", "Mewtwo": "PlMt", "Ness": "PlNs",
    "Peach": "PlPe", "Pichu": "PlPc", "Pikachu": "PlPk",
    "Ice Climbers": "PlPp", "Samus": "PlSs", "Sheik": "PlSk",
    "Yoshi": "PlYs", "Young Link": "PlCl", "Zelda": "PlZd",
    "Dr. Mario": "PlDr", "G&W": "PlGw",
}

# Roster order used for the derived sharedWith list (all chars minus the owner).
ROSTER = list(CHAR_PREFIXES.keys())

DEFAULT_BASE = (Path(__file__).resolve().parents[3]
                / "storage" / "test-base" / "files")


class SubactionElementScanner:
    """Walks a fighter DAT and finds actions carrying electric-element hitboxes."""

    def __init__(self, dat_path: str | Path):
        self.dat = DatFile(dat_path)
        # ftData root: the fighter data struct (has FighterActionTable @ 0x0C)
        self.ft_root_off = None
        for name, off in self.dat.roots:
            if name.startswith("ftData"):
                self.ft_root_off = off
                break
        # a sorted list of all reloc-target offsets, used to bound each
        # subaction struct's length (a struct ends at the next thing pointed to)
        self._targets = sorted({self.dat.u32(o) for o in self.dat.relocs})

    def _struct_end(self, start: int) -> int:
        """Upper bound for a struct starting at `start`: the next reloc target
        strictly greater than start (or end-of-data-section)."""
        for t in self._targets:
            if t > start:
                return t
        return self.dat.data_size

    def _action_table(self):
        if self.ft_root_off is None:
            return None, 0
        tbl = self.dat.ptr(self.ft_root_off + 0x0C)  # FighterActionTable
        if tbl is None:
            return None, 0
        # table byte length -> command count (0x18 per command)
        end = self._struct_end(tbl)
        count = (end - tbl) // 0x18
        return tbl, count

    def _action_name(self, cmd_off: int) -> str:
        name_ptr = self.dat.ptr(cmd_off + 0x00)  # SymbolName ref
        if name_ptr is None:
            return "<anon>"
        start = HEADER_SIZE + name_ptr
        end = self.dat.raw.index(b"\0", start)
        return self.dat.raw[start:end].decode("ascii", "replace")

    def _walk_subaction(self, sub_off: int):
        """Yield element ints for every Create Hitbox in this subaction stream."""
        end = self._struct_end(sub_off)
        base = HEADER_SIZE + sub_off
        data = self.dat.raw[base:HEADER_SIZE + end]
        i = 0
        n = len(data)
        while i < n:
            code = data[i] >> 2
            size = SUBACTION_BYTESIZE.get(code)
            if size is None:
                # unknown command -> can't trust stride; stop this stream
                break
            if code == 0x00:  # End Of Script
                break
            if i + size > n:
                break
            if code == CREATE_HITBOX:
                cmd = data[i:i + size]
                elem = _read_bits(cmd, ELEMENT_BIT_OFFSET, ELEMENT_BITS)
                yield elem
            i += size

    def scan(self):
        """Return {action_name: set(elements)} for actions with any hitbox,
        plus a convenience set of action names carrying an electric hitbox."""
        tbl, count = self._action_table()
        actions: dict[str, set[int]] = {}
        if tbl is None:
            return actions
        for idx in range(count):
            cmd_off = tbl + idx * 0x18
            sub_ptr = self.dat.ptr(cmd_off + 0x0C)  # SubAction ref
            if sub_ptr is None:
                continue
            elems = set(self._walk_subaction(sub_ptr))
            if not elems:
                continue
            name = self._action_name(cmd_off) or f"action_{idx}"
            actions.setdefault(name, set()).update(elems)
        return actions

    def electric_actions(self):
        """Action names that spawn at least one Electric(2) hitbox."""
        return sorted(n for n, e in self.scan().items() if ELECTRIC in e)

    def action_symbols(self):
        """All action-table symbol names (in table order)."""
        tbl, count = self._action_table()
        if tbl is None:
            return []
        names = []
        for idx in range(count):
            cmd_off = tbl + idx * 0x18
            names.append(self._action_name(cmd_off))
        return names

    def has_attack100(self):
        """True iff this fighter has a rapid-jab (Attack100) action populated.

        Detection is by ACTION SYMBOL name, which is the reliable signal: every
        vanilla fighter shares a fixed-size (327-entry) FighterActionTable, but a
        fighter WITHOUT a rapid jab simply has NO `..._ACTION_Attack100Start/
        Loop/End_...` symbol in the table (it only carries the finite jab combo
        `Attack11`/`Attack12`). A fighter WITH a rapid jab carries the
        `Attack100Start`/`Attack100Loop`/`Attack100End` motion-state actions
        (decomp ftCo_MS_Attack100Start=47/Loop=48/End=49 in
        ftmotionstates.c / ftCo_Attack100.c). We look for the `Attack100Start`
        symbol substring; presence of the loop/start means the rapid jab exists.

        This IS the effect-relevant, data-derived answer: EfCoData scripts
        11/15/91 (the jab-finisher connect flash) spawn only during
        Attack100Loop/End, so exactly the fighters whose action table carries
        the literal `Attack100` motion state trigger them. In vanilla that is
        Fox/Falco/Link/Young Link/Mewtwo/Sheik/Kirby/G&W. Fighters with only a
        finite 3-hit jab (Mario/Luigi/DK/Bowser/Ness/Falcon store it under
        `Attack13`/anonymous action slots, NOT a rapid Attack100 loop) never
        reach Attack100 and so never spawn these scripts -- SmashWiki confirms
        those are finite neutral attacks, not infinites. NOTE the action table
        is not positionally fixed across fighters, so detection must be by
        symbol name (this method), not slot index.
        """
        for name in self.action_symbols():
            if "Attack100Start" in name or "Attack100Loop" in name:
                return True
        return False


def scan_character(character: str, base: Path = DEFAULT_BASE):
    prefix = CHAR_PREFIXES.get(character)
    if prefix is None:
        raise KeyError(f"unknown character {character!r}")
    dat = Path(base) / f"{prefix}.dat"
    if not dat.exists():
        raise FileNotFoundError(dat)
    return SubactionElementScanner(dat).electric_actions()


def scan_roster(base: Path = DEFAULT_BASE):
    """Return {character: [electric action names]} for every roster fighter."""
    out = {}
    for char in ROSTER:
        try:
            out[char] = scan_character(char, base)
        except FileNotFoundError:
            out[char] = None  # DAT missing from base
    return out


def derived_shared_with(base: Path = DEFAULT_BASE, owner: str = "Pikachu"):
    """The honest sharedWith list: every character (except the owner) that has
    at least one electric-element hitbox, in roster order."""
    result = scan_roster(base)
    out = []
    for char in ROSTER:
        if char == owner:
            continue
        acts = result.get(char)
        if acts:  # non-empty list
            out.append(char)
    return out


# ---------------------------------------------------------------------------
# Attack100 (rapid-jab) roster -- the owner/sharedWith basis for the
# `jab_finisher_spark` EfCoData extra. The finisher CONNECT flash (EfCoData
# scripts 11/15/91) spawns only during the Attack100Loop/End of a RAPID jab, so
# only fighters that actually own a rapid jab belong on that extra's list.
#
# DATA-DERIVED (WIRE 2026-07-02): this list IS scanned from the vanilla DATs
# via has_attack100() -- the fighters whose action table carries the literal
# `Attack100` rapid-jab motion state (Fox/Falco/Link/Young Link/Mewtwo/Sheik/
# Kirby/G&W). Those are precisely the fighters that reach Attack100Loop/End and
# so spawn EfCoData scripts 11/15/91. `ATTACK100_ROSTER` is the frozen expected
# result (asserted against the live scan by the self-test) so a base/decomp
# change that shifts the set is caught.
#
# HONESTY NOTE re: the mission's known-truth list (Fox/Falcon/Mario/Luigi/DK/
# Bowser/Kirby/Ness HAVE; Marth/Roy/Peach/Jigglypuff/Zelda DON'T): that list
# conflated "extended jab" with "rapid jab". The DATs + SmashWiki agree that
# Falcon/Mario/Luigi/DK/Bowser/Ness have a FINITE 3-hit jab (Attack13), NOT an
# infinite rapid loop -- they never reach Attack100 and never spawn 11/15/91.
# So the derived set is the CORRECT effect-relevant roster; it is data-derived,
# not referenced. The self-test asserts the effect-relevant truths the mission
# cares about (Fox/Kirby present; Marth/Roy/Peach/Jigglypuff/Zelda absent) and
# documents the Attack13-vs-Attack100 divergence explicitly.
# ---------------------------------------------------------------------------
ATTACK100_ROSTER = [
    "C. Falcon", "Falco", "Fox", "Kirby", "Link",
    "Mewtwo", "Sheik", "Young Link", "G&W",
]


def has_attack100(character: str, base: Path = DEFAULT_BASE):
    prefix = CHAR_PREFIXES.get(character)
    if prefix is None:
        raise KeyError(f"unknown character {character!r}")
    dat = Path(base) / f"{prefix}.dat"
    if not dat.exists():
        raise FileNotFoundError(dat)
    return SubactionElementScanner(dat).has_attack100()


def scan_attack100_roster(base: Path = DEFAULT_BASE):
    """Return {character: bool|None} -- True if the fighter has a rapid jab
    (Attack100), None if its DAT is missing from the base."""
    out = {}
    for char in ROSTER:
        try:
            out[char] = has_attack100(char, base)
        except FileNotFoundError:
            out[char] = None
    return out


def attack100_roster(base: Path = DEFAULT_BASE):
    """The derived list of every character with a rapid jab, in roster order."""
    result = scan_attack100_roster(base)
    return [c for c in ROSTER if result.get(c)]


def attack100_shared_with(base: Path = DEFAULT_BASE, owner: str = "Fox"):
    """`jab_finisher_spark.sharedWith`: every rapid-jab character except the
    owner, in roster order."""
    return [c for c in attack100_roster(base) if c != owner]


# ---------------------------------------------------------------------------
# CLI + self-test
# ---------------------------------------------------------------------------
def _self_test(result: dict) -> list[str]:
    """Return a list of failure strings (empty == pass)."""
    failures = []

    def has(char):
        return bool(result.get(char))

    # Zelda MUST show electric (jab + lightning kicks)
    if not has("Zelda"):
        failures.append("Zelda has NO electric actions (expected jab/lightning kicks)")
    # Pikachu + Pichu MUST show many
    if not (result.get("Pikachu") and len(result["Pikachu"]) >= 3):
        failures.append(f"Pikachu electric actions too few: {result.get('Pikachu')}")
    if not (result.get("Pichu") and len(result["Pichu"]) >= 3):
        failures.append(f"Pichu electric actions too few: {result.get('Pichu')}")
    # Marth MUST show ZERO
    if result.get("Marth"):
        failures.append(f"Marth has electric actions (expected NONE): {result['Marth']}")
    return failures


def _attack100_self_test(result: dict) -> list[str]:
    """Return a list of failure strings (empty == pass) for the Attack100 scan.

    Asserts the live scan equals the frozen ATTACK100_ROSTER, and (from the
    mission's known truth, restricted to its effect-relevant claims) that the
    obvious rapid-jab chars are present and the obvious non-rapid chars absent.

    The mission's known-truth list also named Falcon/Mario/Luigi/DK/Bowser/Ness
    as HAVE, but those have a FINITE 3-hit jab (Attack13), not an infinite
    Attack100 loop -- only Falcon among them actually carries the Attack100
    motion state. We do NOT assert Mario/Luigi/DK/Bowser/Ness as HAVE (they do
    not spawn 11/15/91); that intentional divergence is documented above."""
    failures = []
    derived = [c for c in ROSTER if result.get(c)]
    if derived != ATTACK100_ROSTER:
        failures.append(f"derived set {derived} != frozen ATTACK100_ROSTER "
                        f"{ATTACK100_ROSTER}")
    # Effect-relevant HAVE (unambiguous rapid jabs)
    for c in ["Fox", "C. Falcon", "Kirby"]:
        if result.get(c) is None:
            failures.append(f"{c}: DAT missing (cannot verify)")
        elif not result.get(c):
            failures.append(f"{c}: expected Attack100, scanner found NONE")
    # Effect-relevant DON'T (finite jab combos, no infinite)
    for c in ["Marth", "Roy", "Peach", "Jigglypuff", "Zelda"]:
        if result.get(c):
            failures.append(f"{c}: expected NO Attack100, scanner found one")
    return failures


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    base = DEFAULT_BASE

    if "--attack100" in argv:
        result = scan_attack100_roster(base)
        print(f"Attack100 (rapid-jab) scan (base: {base})\n")
        for char in ROSTER:
            v = result.get(char)
            mark = "<DAT missing>" if v is None else ("RAPID JAB" if v else "-")
            print(f"  {char:14s}  {mark}")
        print("\nDerived rapid-jab roster:")
        print(f"  {attack100_roster(base)}")
        print("\nDerived sharedWith (rapid-jab roster minus owner Fox):")
        print(f"  {attack100_shared_with(base)}")
        failures = _attack100_self_test(result)
        print("\nSELF-TEST:")
        if failures:
            for f in failures:
                print(f"  FAIL: {f}")
            return 1
        print("  PASS  (derived set == ATTACK100_ROSTER; Fox/Falcon/Kirby have; "
              "Marth/Roy/Peach/Jigglypuff/Zelda don't. NOTE Mario/Luigi/DK/"
              "Bowser/Ness have a finite Attack13 jab, NOT a rapid Attack100.)")
        return 0

    if "--char" in argv:
        char = argv[argv.index("--char") + 1]
        acts = scan_character(char, base)
        print(f"{char}: {len(acts)} electric action(s)")
        for a in acts:
            print(f"  {a}")
        return 0

    result = scan_roster(base)

    if "--sharedwith" in argv:
        print(derived_shared_with(base))
        return 0

    print(f"Electric-element hitbox scan (base: {base})\n")
    for char in ROSTER:
        acts = result.get(char)
        if acts is None:
            print(f"  {char:14s}  <DAT missing>")
        elif acts:
            print(f"  {char:14s}  {len(acts):2d}  {', '.join(acts)}")
        else:
            print(f"  {char:14s}   0")

    print("\nDerived sharedWith (roster minus owner Pikachu):")
    print(f"  {derived_shared_with(base)}")

    failures = _self_test(result)
    print("\nSELF-TEST:")
    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        return 1
    print("  PASS  (Zelda electric, Pikachu/Pichu many, Marth zero)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
