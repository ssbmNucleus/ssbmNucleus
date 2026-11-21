"""
subactions.py -- decode + IN-PLACE encode of fighter subaction scripts.

A fighter DAT (Pl<XX>.dat) carries, under its `ftData<Name>` root:

  ftData @0x00 -> SBM_CommonFighterAttributes  (see attributes.py)
  ftData @0x0C -> FighterActionTable: N entries x 0x18
      0x00 SymbolName ptr   (Ply<Name>5K_Share_ACTION_<Motion>_figatree)
      0x04 animation offset (into Pl<XX>AJ.dat)
      0x08 animation size
      0x0C SubAction ptr    -> the bit-packed command stream
      0x10 / 0x14 flags

The command stream is walked exactly the way HSDRawViewer's
SubactionEvent.GetEvents does: fixed byte stride per opcode, over the whole
struct (a struct ends at the next relocation target, which is also how HSDRaw
segments the data section), with the 32-bit pointer of Subroutine / Go To
resolved through the relocation table.

Editing is a bit-field write into the same bytes -- no command ever changes
size, so nothing in the file moves and the relocation table stays valid. That
is the property the Echo tier stands on.

Frame numbers: `frame` on a command is the script timeline value when the
command executes (sum of Synchronous Timers, or the last Asynchronous Timer).
By the community convention (frame 1 = first frame of the action state) a
hitbox created at timeline t first connects on frame t + 1.
"""
from __future__ import annotations

import bisect
import struct
from dataclasses import dataclass, field
from pathlib import Path

from .commands import (
    COMMANDS, Command,
    END_OF_SCRIPT, SYNC_TIMER, ASYNC_TIMER, SET_LOOP, EXECUTE_LOOP,
    CREATE_HITBOX, REMOVE_HITBOX, CLEAR_HITBOXES, THROW, POINTER_COMMANDS,
)

HEADER_SIZE = 0x20
ACTION_SIZE = 0x18


# ---------------------------------------------------------------------------
# bit helpers (big-endian bit order, matching HSDRaw's Bitreader/BitWriter)
# ---------------------------------------------------------------------------
def read_bits(buf, bit_off: int, count: int) -> int:
    v = 0
    for j in range(count):
        i = bit_off + j
        v = (v << 1) | ((buf[i >> 3] >> (7 - (i & 7))) & 1)
    return v


def write_bits(buf: bytearray, bit_off: int, count: int, value: int) -> None:
    value &= (1 << count) - 1
    for j in range(count):
        i = bit_off + j
        bit = (value >> (count - 1 - j)) & 1
        byte = i >> 3
        mask = 1 << (7 - (i & 7))
        buf[byte] = (buf[byte] | mask) if bit else (buf[byte] & ~mask & 0xFF)


def to_signed(v: int, bits: int) -> int:
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


# ---------------------------------------------------------------------------
# minimal mutable DAT container (header + reloc table + roots)
# ---------------------------------------------------------------------------
class Dat:
    def __init__(self, data: bytes):
        self.buf = bytearray(data)
        (self.file_size, self.data_size, self.reloc_count,
         self.root_count, self.ref_count) = struct.unpack_from(">IIIII", self.buf, 0)
        reloc_start = HEADER_SIZE + self.data_size
        self.relocs = set(struct.unpack_from(f">{self.reloc_count}I", self.buf, reloc_start))
        roots_start = reloc_start + self.reloc_count * 4
        strings_start = roots_start + (self.root_count + self.ref_count) * 8
        self.roots: list[tuple[str, int]] = []
        for i in range(self.root_count):
            data_off, str_off = struct.unpack_from(">II", self.buf, roots_start + i * 8)
            end = self.buf.index(b"\0", strings_start + str_off)
            name = self.buf[strings_start + str_off:end].decode("ascii", "replace")
            self.roots.append((name, data_off))
        # every struct boundary: reloc targets + roots (HSDRaw segments on both)
        targets = {self.u32(o) for o in self.relocs} | {o for _, o in self.roots}
        self._targets = sorted(targets)

    # data-section-relative primitives
    def u32(self, off):
        return struct.unpack_from(">I", self.buf, HEADER_SIZE + off)[0]

    def i32(self, off):
        return struct.unpack_from(">i", self.buf, HEADER_SIZE + off)[0]

    def f32(self, off):
        return struct.unpack_from(">f", self.buf, HEADER_SIZE + off)[0]

    def set_u32(self, off, v):
        struct.pack_into(">I", self.buf, HEADER_SIZE + off, v & 0xFFFFFFFF)

    def set_i32(self, off, v):
        struct.pack_into(">i", self.buf, HEADER_SIZE + off, int(v))

    def set_f32(self, off, v):
        struct.pack_into(">f", self.buf, HEADER_SIZE + off, float(v))

    def ptr(self, off):
        """Relocated pointer at `off`, or None when the field is a real NULL."""
        v = self.u32(off)
        if v == 0 and off not in self.relocs:
            return None
        return v

    def cstring(self, off) -> str:
        start = HEADER_SIZE + off
        end = self.buf.index(b"\0", start)
        return self.buf[start:end].decode("ascii", "replace")

    def struct_end(self, start: int) -> int:
        i = bisect.bisect_right(self._targets, start)
        return self._targets[i] if i < len(self._targets) else self.data_size

    def to_bytes(self) -> bytes:
        return bytes(self.buf)

    # -- growth (the ONLY way bytes move: everything existing keeps its offset)
    def _rebuild(self, data: bytes, relocs: set[int]) -> None:
        """Re-serialise with a new data section / reloc set. Roots, refs and
        the string table are carried over verbatim (data offsets are stable,
        so their entries stay valid)."""
        buf = self.buf
        roots_start = HEADER_SIZE + self.data_size + self.reloc_count * 4
        tail = bytes(buf[roots_start:])
        rl = sorted(relocs)
        body = data + struct.pack(f">{len(rl)}I", *rl) + tail
        hdr = bytearray(buf[:HEADER_SIZE])
        struct.pack_into(">IIIII", hdr, 0, HEADER_SIZE + len(body), len(data),
                         len(rl), self.root_count, self.ref_count)
        self.__init__(bytes(hdr) + body)

    def append_struct(self, blob: bytes, pointer_offsets=(), align: int = 0x20) -> int:
        """Append one new struct to the data section and return its data
        offset. `pointer_offsets` are offsets inside `blob` holding
        data-relative pointers; they join the relocation table. Existing
        structs never move, which is what keeps the in-place Echo edits and
        `datroot`-appended code roots valid."""
        base = (self.data_size + align - 1) // align * align
        data = bytes(self.buf[HEADER_SIZE:HEADER_SIZE + self.data_size])
        data += b"\0" * (base - self.data_size) + bytes(blob)
        self._rebuild(data, self.relocs | {base + o for o in pointer_offsets})
        return base

    def add_reloc(self, off: int) -> None:
        """Mark `off` as a pointer slot (a NULL slot that now points somewhere)."""
        if off in self.relocs:
            return
        data = bytes(self.buf[HEADER_SIZE:HEADER_SIZE + self.data_size])
        self._rebuild(data, self.relocs | {off})


# ---------------------------------------------------------------------------
# decoded model
# ---------------------------------------------------------------------------
@dataclass
class Cmd:
    index: int                 # position within the script
    offset: int                # data-section-relative byte offset
    code: int
    key: str
    name: str
    size: int
    fields: dict[str, int]     # param key -> raw int (signed already applied)
    pointer: int | None = None  # Subroutine / Go To target (data offset)
    frame: float = 0.0         # script timeline when this command runs
    in_loop: bool = False
    after_end: bool = False    # sits past the first End Of Script in the struct

    @property
    def spec(self) -> Command:
        return COMMANDS[self.code]


@dataclass
class Script:
    offset: int
    end: int
    commands: list[Cmd] = field(default_factory=list)
    unknown_code: int | None = None   # walk stopped on an opcode we don't know

    @property
    def length(self) -> int:
        return self.end - self.offset

    def of_code(self, code: int) -> list[Cmd]:
        return [c for c in self.commands if c.code == code and not c.after_end]


@dataclass
class Action:
    index: int
    symbol: str | None
    motion: str | None          # "AttackS3S" etc. parsed from the symbol
    script_offset: int | None
    anim_offset: int
    anim_size: int
    flags: int
    flags2: int


_SYMBOL_MARK = "_ACTION_"


def motion_from_symbol(symbol: str | None) -> str | None:
    """'PlyFalco5K_Share_ACTION_AttackS3S_figatree' -> 'AttackS3S'."""
    if not symbol or _SYMBOL_MARK not in symbol:
        return None
    m = symbol.split(_SYMBOL_MARK, 1)[1]
    if m.endswith("_figatree"):
        m = m[: -len("_figatree")]
    return m


def fighter_name_from_symbol(symbol: str | None) -> str | None:
    """'PlyFalco5K_Share_ACTION_...' -> 'Falco'."""
    if not symbol or not symbol.startswith("Ply") or "5K" not in symbol:
        return None
    return symbol[3:symbol.index("5K")]


# ---------------------------------------------------------------------------
# the fighter DAT
# ---------------------------------------------------------------------------
class FighterDat:
    """Decoded view of a Pl<XX>.dat with in-place field editing."""

    def __init__(self, data: bytes):
        self.dat = Dat(data)
        self.ft_root: int | None = None
        self.ft_root_name: str | None = None
        for name, off in self.dat.roots:
            if name.startswith("ftData"):
                self.ft_root, self.ft_root_name = off, name
                break
        if self.ft_root is None:
            raise ValueError("not a fighter DAT: no ftData root "
                             f"(roots: {[n for n, _ in self.dat.roots]})")
        self.actions: list[Action] = self._read_actions()
        self._scripts: dict[int, Script] = {}

    @classmethod
    def from_file(cls, path) -> "FighterDat":
        return cls(Path(path).read_bytes())

    def to_bytes(self) -> bytes:
        return self.dat.to_bytes()

    # -- action table -------------------------------------------------------
    @property
    def action_table(self) -> tuple[int | None, int]:
        tbl = self.dat.ptr(self.ft_root + 0x0C)
        if tbl is None:
            return None, 0
        return tbl, (self.dat.struct_end(tbl) - tbl) // ACTION_SIZE

    def _read_actions(self) -> list[Action]:
        tbl, count = self.action_table
        out = []
        if tbl is None:
            return out
        for i in range(count):
            a = tbl + i * ACTION_SIZE
            name_ptr = self.dat.ptr(a + 0x00)
            symbol = self.dat.cstring(name_ptr) if name_ptr is not None else None
            out.append(Action(
                index=i, symbol=symbol, motion=motion_from_symbol(symbol),
                script_offset=self.dat.ptr(a + 0x0C),
                anim_offset=self.dat.u32(a + 0x04), anim_size=self.dat.u32(a + 0x08),
                flags=self.dat.u32(a + 0x10), flags2=self.dat.u32(a + 0x14)))
        return out

    @property
    def fighter_name(self) -> str | None:
        for a in self.actions:
            n = fighter_name_from_symbol(a.symbol)
            if n:
                return n
        return None

    # -- scripts ------------------------------------------------------------
    def script(self, action_index: int) -> Script | None:
        a = self.actions[action_index]
        if a.script_offset is None:
            return None
        s = self._scripts.get(a.script_offset)
        if s is None:
            s = self.decode_script(a.script_offset)
            self._scripts[a.script_offset] = s
        return s

    def decode_script(self, offset: int) -> Script:
        dat = self.dat
        end = dat.struct_end(offset)
        script = Script(offset=offset, end=end)
        buf = dat.buf
        pos = offset
        t = 0.0
        loop_depth = 0
        ended = False
        idx = 0
        while pos < end:
            code = buf[HEADER_SIZE + pos] >> 2
            spec = COMMANDS.get(code)
            if spec is None:
                script.unknown_code = code
                break
            if pos + spec.size > end:
                break
            base_bit = (HEADER_SIZE + pos) * 8
            fields = {}
            for p in spec.params:
                raw = read_bits(buf, base_bit + p.bit_offset, p.bits)
                fields[p.key] = to_signed(raw, p.bits) if p.signed else raw
            pointer = None
            if code in POINTER_COMMANDS:
                # the 32-bit tail word is a relocated pointer
                pointer = dat.ptr(pos + spec.size - 4)
            cmd = Cmd(index=idx, offset=pos, code=code, key=spec.key, name=spec.name,
                      size=spec.size, fields=fields, pointer=pointer, frame=t,
                      in_loop=loop_depth > 0, after_end=ended)
            script.commands.append(cmd)
            idx += 1
            pos += spec.size
            if ended:
                continue
            if code == SYNC_TIMER:
                t += fields.get("frame", 0)
            elif code == ASYNC_TIMER:
                t = float(fields.get("frame", 0))
            elif code == SET_LOOP:
                loop_depth += 1
            elif code == EXECUTE_LOOP:
                loop_depth = max(0, loop_depth - 1)
            elif code == END_OF_SCRIPT:
                ended = True
        return script

    # -- hitboxes -----------------------------------------------------------
    def hitboxes(self, action_index: int) -> list[dict]:
        """Ordinal list of Create Hitbox commands in the action's script with
        their active window on the script timeline (frame_start is the first
        frame the hitbox can connect, community numbering)."""
        s = self.script(action_index)
        if s is None:
            return []
        out = []
        open_by_id: dict[int, dict] = {}
        for c in s.commands:
            if c.after_end:
                break
            if c.code == CREATE_HITBOX:
                h = {"ordinal": len(out), "command": c.index,
                     "frame_start": c.frame + 1, "frame_end": None,
                     "in_loop": c.in_loop, **c.fields}
                out.append(h)
                open_by_id[c.fields["id"]] = h
            elif c.code == REMOVE_HITBOX:
                h = open_by_id.pop(c.fields.get("index", -1), None)
                if h is not None and h["frame_end"] is None:
                    h["frame_end"] = c.frame
            elif c.code in (CLEAR_HITBOXES, END_OF_SCRIPT):
                for h in open_by_id.values():
                    if h["frame_end"] is None:
                        h["frame_end"] = c.frame
                open_by_id.clear()
        return out

    def throws(self, action_index: int) -> list[dict]:
        s = self.script(action_index)
        if s is None:
            return []
        return [{"ordinal": i, "command": c.index, "frame": c.frame, **c.fields}
                for i, c in enumerate(s.of_code(THROW))]

    # -- editing ------------------------------------------------------------
    def get_field(self, action_index: int, command_index: int, key: str) -> int:
        return self._cmd(action_index, command_index).fields[key]

    def set_field(self, action_index: int, command_index: int, key: str, value: int) -> dict:
        """Write one bit-field in place. Returns {before, after, offset}."""
        cmd = self._cmd(action_index, command_index)
        p = cmd.spec.param(key)
        if p.is_padding:
            raise ValueError(f"{cmd.key}.{key} is padding")
        value = int(value)
        if not (p.min <= value <= p.max):
            raise ValueError(f"{cmd.key}.{key}={value} out of range "
                             f"[{p.min}, {p.max}] ({p.bits} bits"
                             f"{', signed' if p.signed else ''})")
        before = cmd.fields[key]
        write_bits(self.dat.buf, (HEADER_SIZE + cmd.offset) * 8 + p.bit_offset,
                   p.bits, value)
        cmd.fields[key] = value
        return {"before": before, "after": value, "offset": cmd.offset,
                "bit_offset": p.bit_offset, "bits": p.bits}

    def _cmd(self, action_index: int, command_index: int) -> Cmd:
        s = self.script(action_index)
        if s is None:
            raise IndexError(f"action {action_index} has no script")
        try:
            return s.commands[command_index]
        except IndexError:
            raise IndexError(f"action {action_index}: command {command_index} "
                             f"out of range (script has {len(s.commands)})")

    # -- authoring: whole-script replacement --------------------------------
    # A script item is (code, fields, pointer): the same shape decode yields.
    # Growing a script in place is impossible (structs are packed), so an
    # authored script is APPENDED as a new struct and the action-table slot
    # is repointed; the old bytes stay where they were (dead, harmless).
    def script_items(self, action_index: int) -> list[tuple[int, dict, int | None]]:
        """The action's live commands (up to and including the first End Of
        Script) in the shape encode_script/replace_script take."""
        s = self.script(action_index)
        if s is None:
            return []
        items = []
        for c in s.commands:
            if c.after_end:
                break
            items.append((c.code, dict(c.fields), c.pointer))
        return items

    @staticmethod
    def encode_script(items) -> tuple[bytes, list[int]]:
        """Pack items into a command stream. Missing fields are 0; an End Of
        Script is appended when the list does not end with one. Returns the
        bytes and the blob-relative offsets of relocated pointer words."""
        out = bytearray()
        pointers: list[int] = []
        for code, fields, pointer in items:
            spec = COMMANDS.get(code)
            if spec is None:
                raise ValueError(f"unknown command code {code}")
            raw = bytearray(spec.size)
            write_bits(raw, 0, 6, code)
            for p in spec.params:
                v = int(fields.get(p.key, 0))
                if not (p.min <= v <= p.max):
                    raise ValueError(f"{spec.key}.{p.key}={v} out of range [{p.min}, {p.max}]")
                write_bits(raw, p.bit_offset, p.bits, v)
            if code in POINTER_COMMANDS:
                if pointer is None:
                    pointer = fields.get("pointer")
                if pointer is None:
                    raise ValueError(f"{spec.key} needs a pointer (data offset of the target script)")
                struct.pack_into(">I", raw, spec.size - 4, int(pointer))
                if int(pointer) != 0:   # a 0 word is a real NULL (vanilla has them), not a reloc
                    pointers.append(len(out) + spec.size - 4)
            out += raw
        if not items or items[-1][0] != END_OF_SCRIPT:
            out += bytes(COMMANDS[END_OF_SCRIPT].size)
        return bytes(out), pointers

    def replace_script(self, action_index: int, items) -> dict:
        """Give the action a freshly authored script (appended struct +
        repointed table slot). Returns {action, old_offset, new_offset, bytes}."""
        if not 0 <= action_index < len(self.actions):
            raise IndexError(f"action {action_index} out of range (0..{len(self.actions) - 1})")
        blob, pointers = self.encode_script(items)
        for off in pointers:
            target = struct.unpack_from(">I", blob, off)[0]
            if target >= self.dat.data_size:
                raise ValueError(f"pointer target 0x{target:X} is outside the data section")
        old = self.actions[action_index].script_offset
        new_off = self.dat.append_struct(blob, pointers)
        tbl, _ = self.action_table
        slot = tbl + action_index * ACTION_SIZE + 0x0C
        self.dat.set_u32(slot, new_off)
        self.dat.add_reloc(slot)
        self.actions = self._read_actions()
        self._scripts.clear()
        return {"action": action_index, "old_offset": old, "new_offset": new_off,
                "bytes": len(blob)}

    # -- verification -------------------------------------------------------
    def encode_command(self, cmd: Cmd) -> bytes:
        """Re-pack a decoded command from its fields (pointer word included
        verbatim). Used to prove the decode is exact."""
        spec = cmd.spec
        out = bytearray(spec.size)
        write_bits(out, 0, 6, cmd.code)
        for p in spec.params:
            write_bits(out, p.bit_offset, p.bits, cmd.fields[p.key])
        return bytes(out)

    def verify_roundtrip(self) -> list[str]:
        """Every command in every script must re-encode to its own bytes."""
        problems = []
        for a in self.actions:
            s = self.script(a.index)
            if s is None:
                continue
            for c in s.commands:
                raw = bytes(self.dat.buf[HEADER_SIZE + c.offset:HEADER_SIZE + c.offset + c.size])
                enc = self.encode_command(c)
                if raw != enc:
                    problems.append(f"action {a.index} {a.motion} cmd {c.index} "
                                    f"{c.key}: {raw.hex()} != {enc.hex()}")
            if s.unknown_code is not None:
                problems.append(f"action {a.index} {a.motion}: unknown opcode "
                                f"0x{s.unknown_code:02X} at walk stop")
        return problems
