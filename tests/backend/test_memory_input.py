"""Portable input protocol, native stub and isolated-profile regressions."""
import struct

import pytest

from shared.ingame import boot
from shared.ingame import memory_input as mi


class RAM:
    def __init__(self, ack=True):
        self.data = bytearray(0x10000)
        self.writes = []
        self.ack = ack
        self.closed = False

    def bytes(self, addr, count):
        return bytes(self.data[addr & 0xFFFF:(addr & 0xFFFF) + count])

    def u32(self, addr):
        return struct.unpack(">I", self.bytes(addr, 4))[0]

    def write_bytes(self, addr, data):
        self.writes.append((addr, bytes(data)))
        self.data[addr & 0xFFFF:(addr & 0xFFFF) + len(data)] = data
        return True

    def write_u32(self, addr, value):
        self.write_bytes(addr, struct.pack(">I", value))
        if self.ack and addr == mi.PUBLISHED:
            self.write_bytes(mi.CONSUMED, struct.pack(">I", value))
        return True

    def alive(self):
        return True

    def close(self):
        self.closed = True


def test_atomic_publish_then_ack_and_alternating_buffers():
    d = RAM()
    p = mi.MemoryInput(d, 0, timeout=0)
    p.frame(["SET MAIN 1 .5", "PRESS B", "FLUSH"])
    assert d.writes[0] == (44, bytes.fromhex("02007f000000000000000000"))
    assert d.writes[1] == (mi.PUBLISHED, bytes.fromhex("00000001"))
    p.neutral()
    assert d.writes[3] == (32, bytes(12))
    assert d.u32(mi.PUBLISHED) == d.u32(mi.CONSUMED) == 2
    p.close()
    assert d.closed
    with pytest.raises(OSError, match="closed"):
        p.press("A")


def test_no_buffer_reuse_until_previous_read_completes():
    d = RAM(ack=False)
    p = mi.MemoryInput(d, 0, timeout=0)
    with pytest.raises(TimeoutError):
        p.press("A")
    writes = list(d.writes)
    with pytest.raises(TimeoutError):
        p.press("B")
    assert d.writes == writes  # cannot overwrite either buffer while unacked


@pytest.mark.parametrize("command", ["PRESS NOPE", "SET MAIN nan .5", "SET R inf", "BOGUS", "SET C .5"])
def test_bad_batch_has_no_partial_effect(command):
    d = RAM()
    p = mi.MemoryInput(d, 0)
    with pytest.raises(ValueError):
        p.frame(["PRESS A", command, "FLUSH"])
    assert not d.writes and not p._buttons


def test_axes_triggers_buttons_and_release():
    d = RAM()
    p = mi.MemoryInput(d, 0)
    p.frame(["SET MAIN .689 .311", "SET C 0 1", "SET L .5", "PRESS R", "PRESS X"])
    assert struct.unpack(">HbbbbBBBBbB", d.bytes(44, 12)) == (
        0x420, 48, -49, -127, 127, 64, 128, 0, 0, 0, 0)
    p.release("R")
    assert struct.unpack(">HbbbbBBBBbB", d.bytes(32, 12))[5:7] == (64, 0)


def test_failed_write_does_not_publish(monkeypatch):
    d = RAM()
    p = mi.MemoryInput(d, 0)
    monkeypatch.setattr(d, "write_bytes", lambda *a: False)
    with pytest.raises(OSError, match="sample write"):
        p.press("A")
    assert d.u32(mi.PUBLISHED) == 0


def _iso(tmp_path, site=mi.SITE, game=b"GALE01\x00\x02"):
    data = bytearray(0x700)
    data[:8] = game
    struct.pack_into(">I", data, 0x420, 0x500)
    struct.pack_into(">I", data, 0x500, 0x100)
    struct.pack_into(">I", data, 0x548, mi.HOOK - 8)
    struct.pack_into(">I", data, 0x590, len(site))
    data[0x600:0x600 + len(site)] = site
    path = tmp_path / "melee.iso"
    path.write_bytes(data)
    return path


@pytest.mark.parametrize("game,site", [(b"GALE01\x00\x01", mi.SITE), (b"GALJ01\x00\x02", mi.SITE), (b"GALE01\x00\x02", bytes(16))])
def test_rejects_wrong_revision_or_conflicting_site(tmp_path, game, site):
    with pytest.raises(ValueError):
        mi.validate_iso(_iso(tmp_path, game=game, site=site))


def test_memory_prepare_never_probes_global_pipes(tmp_path, monkeypatch):
    monkeypatch.setattr(boot, "resolve_dolphin", lambda _: ("fake.exe", None))
    monkeypatch.setattr(boot, "pick_pipe_index", lambda: pytest.fail("global pipe probe"))
    monkeypatch.setattr(boot, "ensure_fifo", lambda _: pytest.fail("FIFO creation"))
    instance = boot.DolphinBoot(str(_iso(tmp_path)), None, tmp_path / "runs", input_backend="memory")
    instance.prepare()
    game = (instance.user_dir / "GameSettings" / "GALE01.ini").read_text()
    assert "20376A28 2C1E0000" in game and "C2376A28 00000017" in game
    assert "[Gecko_Enabled]" in game
    assert "EnableCheats = True" in (instance.user_dir / "Config" / "Dolphin.ini").read_text()
    assert "Pipe/" not in (instance.user_dir / "Config" / "GCPadNew.ini").read_text()
    marker = object()
    instance._memory_input = marker
    assert instance.wait_for_pipe() and instance.open_pipe() is marker


def test_pipe_default_does_not_validate_or_install_hook(tmp_path, monkeypatch):
    monkeypatch.delenv("NUCLEUS_DOLPHIN_INPUT", raising=False)
    monkeypatch.setattr(mi, "prepare", lambda *a: pytest.fail("unexpected memory hook"))
    monkeypatch.setattr(boot, "resolve_dolphin", lambda _: ("fake.exe", None))
    instance = boot.DolphinBoot("any.iso", None, tmp_path, pipe_index=2).prepare()
    assert instance.input_backend == "pipe"
    assert not (instance.user_dir / "GameSettings").exists()
    monkeypatch.setenv("NUCLEUS_DOLPHIN_INPUT", "typo")
    with pytest.raises(ValueError):
        boot.DolphinBoot("any.iso", None, tmp_path)
    with pytest.raises(ValueError, match="playable previews"):
        boot.DolphinBoot("any.iso", None, tmp_path, input_backend="memory", interactive=True)


def test_memory_environment_requires_multiple_slots_but_explicit_qa_does_not(monkeypatch):
    monkeypatch.setenv("NUCLEUS_DOLPHIN_INPUT", "memory")
    monkeypatch.setenv("NUCLEUS_DOLPHIN_SLOTS", "1")
    with pytest.raises(ValueError, match="single-Dolphin QA"):
        mi.select_backend()
    assert mi.select_backend("memory") == "memory"
    monkeypatch.setenv("NUCLEUS_DOLPHIN_SLOTS", "6")
    assert mi.select_backend() == "memory"
    assert mi.select_backend("pipe") == "pipe"


def test_stub_executes_native_copy_preserves_registers_and_returns():
    # Execute the actual emitted instructions with a tiny PPC integer subset.
    # This checks encodings, LR-relative data, stack offsets and displaced cmp,
    # independently of the Python command serializer. No game file is needed.
    d = RAM()
    target = 0x80005000
    words = mi.hook_words()
    returning = mi.HOOK + 4
    words[-1] = 0x48000000 | ((returning - (target + 4 * (len(words) - 1))) & 0x03FFFFFC)
    d.write_bytes(target, struct.pack(f">{len(words)}I", *words))
    d.write_u32(mi.HOOK, 0x48000000 | ((target - mi.HOOK) & 0x03FFFFFC))
    mailbox = mi.mailbox_address(d)
    assert mailbox == target + 32
    d.write_u32(mailbox + mi.PUBLISHED, 7)
    sample = bytes.fromhex("01404cfb7f810080ffff0000")
    d.write_bytes(mailbox + 44, sample)
    regs = [0x100 + i for i in range(32)]
    regs[1] = 0x8000A000
    before = list(regs)
    lr, pc, cr = 0x80004000, target, None
    signed = lambda value, bits: value - (1 << bits) if value & (1 << (bits - 1)) else value
    for _ in range(100):
        if pc == returning:
            break
        op = d.u32(pc)
        pc += 4
        rt, ra, rb = (op >> 21) & 31, (op >> 16) & 31, (op >> 11) & 31
        imm, primary = signed(op & 0xFFFF, 16), op >> 26
        addr = ((regs[ra] if ra else 0) + imm) & 0xFFFFFFFF
        if primary == 37:  # stwu
            d.write_u32(addr, regs[rt]); regs[ra] = addr
        elif primary == 36:
            d.write_u32(addr, regs[rt])
        elif primary == 32:
            regs[rt] = d.u32(addr)
        elif primary == 14:
            regs[rt] = addr
        elif primary == 7:
            regs[rt] = (regs[ra] * imm) & 0xFFFFFFFF
        elif primary == 18:
            if op & 1:
                lr = pc
            pc = pc - 4 + signed(op & 0x03FFFFFC, 26)
        elif primary == 21:
            assert (op & 0xFFFF) == 0x07FE  # rotate 0, mask bit 31
            regs[ra] = regs[rt] & 1
        elif primary == 31:
            xo = (op >> 1) & 0x3FF
            if xo == 339:
                regs[rt] = lr
            elif xo == 467:
                lr = regs[rt]
            elif xo == 266:
                regs[rt] = (regs[ra] + regs[rb]) & 0xFFFFFFFF
            else:
                pytest.fail(f"unsupported XO {xo}")
        elif primary == 11:
            cr = signed(regs[ra], 32) - imm
        else:
            pytest.fail(f"unsupported opcode {op:08x}")
    assert pc == returning and regs == before and lr == 0x80004000
    assert cr == before[30]
    assert d.bytes(before[1] + 0x2C, 12) == sample
    assert d.bytes(before[1] + 0x38, 36) == bytes(36)  # other pads untouched
    assert d.u32(mailbox + mi.CONSUMED) == 7 and d.u32(mailbox + mi.HEARTBEAT) == 1
    d.write_u32(target + 88, 0)
    assert mi.mailbox_address(d) is None  # refuse mismatched installed code
