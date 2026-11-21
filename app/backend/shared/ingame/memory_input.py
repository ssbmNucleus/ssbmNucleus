"""NTSC 1.02 pad input independent of Dolphin's global Windows named pipes.

An isolated Slippi Gecko C2 hook copies a double-buffered PADStatus into
HSD_PadRenewRawStatus's port-0 sample, immediately AFTER PADRead. The native
queue, clamping, normalization, press/release edges and game-frame snapshot
still run. Never race a Python writer against HSD_PadGameStatus renewal.

The hook and its mailbox live in Slippi's allocated code list, not a guessed
free RAM address. Install before boot/JIT via the throwaway GameSettings only.
See docs/dev/INGAME_TESTING.md for source references and compatibility limits.
"""
import math
import os
from pathlib import Path
import struct
import threading
import time

from .melee_pipe import Pipe

HOOK = 0x80376A28
ORIGINAL = 0x2C1E0000                 # cmpwi r30,0, immediately after PADRead
SITE = bytes.fromhex("3861002c 4bfd6fdd 2c1e0000 4182005c")
MAGIC = b"NUCLEUS-PAD-v1!!"           # 16 bytes, private mailbox version
MAILBOX_OFFSET = 32
PUBLISHED, CONSUMED, HEARTBEAT = 16, 20, 24
SAMPLES, SAMPLE_SIZE = 32, 12
CODE_NAME = "Nucleus harness memory input v1"
BUTTON_BITS = dict(zip(
    ("D_LEFT", "D_RIGHT", "D_DOWN", "D_UP", "Z", "R", "L", "A", "B", "X", "Y", "START"),
    (1, 2, 4, 8, 0x10, 0x20, 0x40, 0x100, 0x200, 0x400, 0x800, 0x1000)))


def select_backend(explicit=None):
    """Pipe remains the default. Explicit memory also permits one-slot QA."""
    backend = explicit or os.environ.get("NUCLEUS_DOLPHIN_INPUT", "pipe")
    if backend not in ("pipe", "memory"):
        raise ValueError("NUCLEUS_DOLPHIN_INPUT must be 'pipe' or 'memory'")
    if backend == "memory" and explicit is None:
        from .dolphin_lock import slot_count
        if slot_count() == 1:
            raise ValueError("Memory input via environment requires NUCLEUS_DOLPHIN_SLOTS > 1; "
                             "for single-Dolphin QA pass input_backend='memory' explicitly")
    return backend


def hook_words():
    """Auditable PPC stub; the final zero is filled by Gecko with the return b.

    At this site r1+0x2c is PADStatus now[4]. Preserve every register we use,
    including LR; the displaced cmpwi supplies the original CR0 result.
    Publish/ack sequence numbers prevent reusing a buffer while PPC copies it.
    """
    prefix = [
        0x9421FFE0,  # stwu r1,-0x20(r1)
        0x90010008,  # stw r0,8(r1)
        0x7C0802A6,  # mflr r0
        0x9001000C,  # stw r0,12(r1)
        0x90610010,  # stw r3,16(r1)
        0x90810014,  # stw r4,20(r1)
        0x90A10018,  # stw r5,24(r1)
        0x4800003D,  # bl over 56-byte mailbox; LR = mailbox address
    ]
    mailbox = MAGIC + bytes(16 + 2 * SAMPLE_SIZE)
    suffix = [
        0x7C6802A6,  # mflr r3
        0x80830010,  # lwz r4,16(r3): published sequence
        0x548507FE,  # clrlwi r5,r4,31: sequence & 1
        0x1CA5000C,  # mulli r5,r5,12
        0x7CA51A14,  # add r5,r5,r3
        0x80050020,  # lwz r0,32(r5): selected sample
        0x9001004C,  # stw r0,0x4c(r1): original r1+0x2c
        0x80050024,  # lwz r0,36(r5)
        0x90010050,  # stw r0,0x50(r1)
        0x80050028,  # lwz r0,40(r5)
        0x90010054,  # stw r0,0x54(r1)
        0x90830014,  # stw r4,20(r3): acknowledge AFTER copying
        0x80830018,  # lwz r4,24(r3): heartbeat counts raw polls, even frozen
        0x38840001,  # addi r4,r4,1
        0x90830018,  # stw r4,24(r3)
        0x80610010,  # lwz r3,16(r1)
        0x80810014,  # lwz r4,20(r1)
        0x80A10018,  # lwz r5,24(r1)
        0x8001000C,  # lwz r0,12(r1)
        0x7C0803A6,  # mtlr r0
        0x80010008,  # lwz r0,8(r1)
        0x38210020,  # addi r1,r1,0x20
        ORIGINAL,
        0x00000000,  # Gecko replaces with branch to HOOK+4
    ]
    return prefix + list(struct.unpack(">14I", mailbox)) + suffix


def validate_iso(iso):
    """Refuse another revision or an already changed injection site pre-boot."""
    with open(iso, "rb") as f:
        header = f.read(0x440)
        if len(header) != 0x440 or header[:6] != b"GALE01" or header[7] != 2:
            raise ValueError("Memory input requires an uncompressed GALE01 NTSC 1.02 ISO")
        dol = struct.unpack_from(">I", header, 0x420)[0]
        f.seek(dol)
        header = f.read(0x100)
        if len(header) == 0x100:
            for i in range(7):          # executable DOL sections only
                offset = struct.unpack_from(">I", header, i * 4)[0]
                address = struct.unpack_from(">I", header, 0x48 + i * 4)[0]
                size = struct.unpack_from(">I", header, 0x90 + i * 4)[0]
                if address <= HOOK - 8 and HOOK + 8 <= address + size:
                    f.seek(dol + offset + HOOK - 8 - address)
                    if f.read(len(SITE)) == SITE:
                        return
        raise ValueError("Memory input: HSD_PadRenewRawStatus injection site differs from NTSC 1.02")


def prepare(user_dir, iso):
    """Install only in the disposable profile; no ISO or real config writes."""
    from .boot import _write_ini
    validate_iso(iso)
    words = hook_words()
    lines = ["[Gecko]", f"${CODE_NAME}",
             # Guard the exact overwritten instruction against another mod.
             f"{0x20000000 | (HOOK & 0x1FFFFFF):08X} {ORIGINAL:08X}",
             f"{0xC2000000 | (HOOK & 0x1FFFFFF):08X} {len(words) // 2:08X}"]
    lines += [f"{words[i]:08X} {words[i+1]:08X}" for i in range(0, len(words), 2)]
    lines += ["E0000000 80008000", "", "[Gecko_Enabled]", f"${CODE_NAME}", ""]
    game_ini = Path(user_dir) / "GameSettings" / "GALE01.ini"
    game_ini.parent.mkdir(exist_ok=True)
    # DolphinBoot does not copy GameSettings. Refuse overwriting a custom file.
    with game_ini.open("x", encoding="ascii") as f:
        f.write("\n".join(lines))
    _write_ini(str(Path(user_dir) / "Config" / "Dolphin.ini"),
               lambda upsert, _: upsert("Core", "EnableCheats", "True"))
    _write_ini(str(Path(user_dir) / "Config" / "GCPadNew.ini"),
               lambda upsert, _: upsert("GCPad1", "Device", ""))


def _read(d, address, size):
    result = d.bytes(address, size)
    if result is None or len(result) != size:
        raise OSError(f"Memory input: short read at {address:#x}")
    return result


def mailbox_address(d):
    """Follow the installed hook, validating its code and version, never scan."""
    instruction = d.u32(HOOK)
    if instruction is None or instruction & 0xFC000003 != 0x48000000:
        return None
    displacement = instruction & 0x03FFFFFC
    if displacement & 0x02000000:
        displacement -= 0x04000000
    target = HOOK + displacement
    words = hook_words()
    if not 0x80003000 <= target < 0x81800000 - len(words) * 4:
        return None
    prefix = struct.pack(">8I", *words[:8])
    if _read(d, target, len(prefix) + len(MAGIC)) != prefix + MAGIC:
        return None
    # The data changes, but every instruction must be our installed stub.
    suffix = struct.pack(">23I", *words[22:-1])
    if _read(d, target + 88, len(suffix)) != suffix:
        return None
    return_site = target + (len(words) - 1) * 4
    expected_return = 0x48000000 | ((HOOK + 4 - return_site) & 0x03FFFFFC)
    if d.u32(return_site) != expected_return:
        return None
    return target + MAILBOX_OFFSET


class MemoryInput(Pipe):
    """Pipe's public commands, delivered through the owned Dolphin's MEM1.

    There is no pipe handle, keyboard input, focus activation, or writer thread.
    Commands hold until replaced, including during retail debug frame stepping.
    """
    def __init__(self, d, mailbox, *, timeout=3.0, alive=None):
        self.d, self.mailbox = d, mailbox
        self.timeout, self._alive = timeout, alive or d.alive
        self._closed = False
        self._lock = threading.Lock()
        self._sequence = d.u32(mailbox + PUBLISHED)
        self._buttons = set()
        self._axes = {"MAIN": (0.5, 0.5), "C": (0.5, 0.5), "L": 0.0, "R": 0.0}

    def _ack(self, sequence):
        deadline = time.monotonic() + self.timeout
        while self.d.u32(self.mailbox + CONSUMED) != sequence:
            if not self._alive():
                raise OSError("Memory input: Dolphin exited")
            if time.monotonic() >= deadline:
                raise TimeoutError("Memory input: pad hook stopped acknowledging input")
            time.sleep(0.002)

    @staticmethod
    def _number(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError("Input axes must be finite")
        return max(0.0, min(1.0, value))

    @staticmethod
    def _sample(buttons, axes):
        # GCPadEmu: center 128 + normalized axis * 127, truncate to u8;
        # PADRead subtracts 128. Match Dolphin before HSD clamps/scales it.
        sticks = [int(128 + (v - 0.5) * 2 * 127) - 128
                  for name in ("MAIN", "C") for v in axes[name]]
        # Pipe SET L/R maps v to (v/2 + .5); FullAnalogSurface starts at
        # .5, so SDK origin calibration subtracts 127. Digital L/R goes to
        # 255 before that subtraction. Preserve the existing pipe behavior
        # (full press = 128), rather than silently strengthening shields.
        triggers = [128 if name in buttons else int((axes[name] / 2 + .5) * 255) - 127
                    for name in ("L", "R")]
        bits = sum(BUTTON_BITS[name] for name in buttons)
        # SDK SI analog mode 3 carries sticks/triggers, not analog A/B.
        return struct.pack(">HbbbbBBBBbB", bits, *sticks, *triggers,
                           0, 0, 0, 0)

    def frame(self, lines):
        with self._lock:
            if self._closed:
                raise OSError("Memory input is closed")
            buttons, axes = set(self._buttons), dict(self._axes)
            for line in lines:
                tokens = line.split()
                if tokens == ["FLUSH"]:
                    continue
                if (len(tokens) == 2 and tokens[0] in ("PRESS", "RELEASE")
                        and tokens[1] in BUTTON_BITS):
                    (buttons.add if tokens[0] == "PRESS" else buttons.discard)(tokens[1])
                elif tokens[:1] == ["SET"] and len(tokens) == 4 and tokens[1] in ("MAIN", "C"):
                    axes[tokens[1]] = tuple(self._number(x) for x in tokens[2:])
                elif tokens[:1] == ["SET"] and len(tokens) == 3 and tokens[1] in ("L", "R"):
                    axes[tokens[1]] = self._number(tokens[2])
                else:
                    raise ValueError(f"Unsupported memory input command: {line!r}")
            sample = self._sample(buttons, axes)
            self._ack(self._sequence)       # previous reader finished its copy
            sequence = (self._sequence + 1) & 0xFFFFFFFF
            address = self.mailbox + SAMPLES + (sequence & 1) * SAMPLE_SIZE
            if not self.d.write_bytes(address, sample):
                raise OSError("Memory input: sample write failed")
            if not self.d.write_u32(self.mailbox + PUBLISHED, sequence):
                raise OSError("Memory input: publish failed")
            self._sequence, self._buttons, self._axes = sequence, buttons, axes
            self._ack(sequence)             # fail loudly on a dead/hung hook

    def close(self):
        if not self._closed:
            try:
                if self._alive():
                    self.neutral()
            finally:
                self._closed = True
                self.d.close()
