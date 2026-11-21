"""
commands.py -- the fighter subaction command spec (code -> name, bit-packed
parameter layout), loaded from the generated `_command_table.py`.

Source of truth is HSDRawViewer's Scripts/command_controls.yml +
command_fighter.yml (the exact spec its Script Editor compiles with).
Regenerate with `python -m vault.echo.gen_command_table` after upstream changes.

Every command's byte size is FIXED (6-bit opcode + the parameter bits, always
a multiple of 8), which is what makes in-place value edits safe: changing a
field never moves a byte.
"""
from __future__ import annotations

from dataclasses import dataclass

from ._command_table import COMMAND_TABLE


@dataclass(frozen=True)
class Param:
    key: str            # snake_case id used in ops / JSON
    name: str           # HSDRaw display name
    bits: int
    signed: bool
    hex: bool
    enums: tuple[str, ...] | None
    bit_offset: int     # from the start of the command (after the 6-bit opcode)

    @property
    def min(self) -> int:
        return -(1 << (self.bits - 1)) if self.signed else 0

    @property
    def max(self) -> int:
        return (1 << (self.bits - 1)) - 1 if self.signed else (1 << self.bits) - 1

    @property
    def is_padding(self) -> bool:
        return self.key.startswith("_pad")


@dataclass(frozen=True)
class Command:
    code: int
    key: str
    name: str
    bits: int
    params: tuple[Param, ...]

    @property
    def size(self) -> int:
        return self.bits // 8

    def param(self, key: str) -> Param:
        for p in self.params:
            if p.key == key:
                return p
        raise KeyError(f"{self.key} has no field {key!r} "
                       f"(fields: {[p.key for p in self.params]})")


def _build() -> dict[int, Command]:
    out = {}
    for c in COMMAND_TABLE:
        params = []
        off = 6
        for p in c["params"]:
            params.append(Param(p["key"], p["name"], p["bits"], p["signed"],
                                p["hex"], tuple(p["enums"]) if p["enums"] else None,
                                off))
            off += p["bits"]
        cmd = Command(c["code"], c["key"], c["name"], c["bits"], tuple(params))
        assert cmd.bits % 8 == 0, cmd
        out[cmd.code] = cmd
    return out


COMMANDS: dict[int, Command] = _build()
BY_KEY: dict[str, Command] = {c.key: c for c in COMMANDS.values()}

END_OF_SCRIPT = 0x00
SYNC_TIMER = 0x01
ASYNC_TIMER = 0x02
SET_LOOP = 0x03
EXECUTE_LOOP = 0x04
SUBROUTINE = 0x05
RETURN = 0x06
GO_TO = 0x07
CREATE_HITBOX = 0x0B
ADJUST_HITBOX_DAMAGE = 0x0C
ADJUST_HITBOX_SIZE = 0x0D
REMOVE_HITBOX = 0x0F
CLEAR_HITBOXES = 0x10
THROW = 0x22
SELF_DAMAGE = 0x33
START_SMASH_CHARGE = 0x38

# Commands whose 32-bit tail is a relocated pointer into the same DAT.
POINTER_COMMANDS = {SUBROUTINE, GO_TO}
