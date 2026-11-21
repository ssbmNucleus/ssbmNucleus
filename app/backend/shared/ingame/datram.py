"""
datram.py -- locate a loaded DAT file inside Melee's emulated RAM and poke
file offsets LIVE, without rebuilding the ISO or rebooting Dolphin.

Why: the extras audit's experiment loop was "patch DAT -> MexCLI export
(~2 min) -> boot (~2 min) -> look". For byte->visual mapping work (which
color record drives which flame?) that is brutally slow. Melee loads DAT
files (Pl*.dat, Ef*Data.dat, ...) into MEM1 as a contiguous file image and
relocates only the pointer fields in place -- colors, CF/07-records, ptcl
tables and texture data stay byte-identical to the file on disk. So we can
find the loaded image by matching byte windows sampled from the file, then
write test colors straight into the live game and simply redo the move.

    d = Dolphin(pid)                       # shared.ingame.melee_mem
    dat = DatRam(d, "storage/test-base/files/EfFxData.dat")
    dat.locate()                           # -> [0x81xxxxxx, ...] image bases
    dat.poke(0x1A884, b"\xff\x00\xff")     # live: next effect spawn shows it
    dat.restore(0x1A884, 3)                # back to vanilla bytes

Gotchas:
- locate() AFTER the match has loaded (the file isn't resident on the CSS
  for most Ef*Data files). Re-locate after any scene change.
- Windows containing relocated pointers won't match the disk bytes; locate()
  majority-votes across many sampled windows so this doesn't matter.
- If several copies of the image are resident (heap + cache), poke() writes
  ALL of them so the visible one is always covered.
- Pokes do not survive a re-load of the file (new match/scene). This tool is
  for MAPPING bytes to visuals; ship the finding as a normal extras patch and
  verify once through the real build path.
"""
import struct
from pathlib import Path

from .melee_mem import GC_BASE, MEM1_VALID


class DatRam:
    """A DAT file on disk located inside the live game's RAM."""

    def __init__(self, dolphin, file_path):
        self.d = dolphin
        self.path = Path(file_path)
        self.data = self.path.read_bytes()
        self.bases = []          # GC addresses where the file image starts

    # -- locating -----------------------------------------------------------

    def _windows(self, count=12, size=32):
        """Sample evenly spaced high-entropy byte windows from the file."""
        n = len(self.data)
        wins = []
        for i in range(count):
            off = 0x20 + (n - 0x20 - size) * i // max(1, count - 1)
            w = self.data[off:off + size]
            if len(w) == size and len(set(w)) >= 6:   # skip flat/low-entropy
                wins.append((off, w))
        return wins

    def locate(self, mem=None, min_votes=None):
        """Find every resident copy of the file image. Returns GC bases."""
        if mem is None:
            mem = self.d.snapshot(MEM1_VALID)
        if not mem:
            raise RuntimeError("could not snapshot MEM1")
        windows = self._windows()
        if not windows:
            raise RuntimeError(f"{self.path.name}: no usable signature windows")
        votes = {}
        for off, win in windows:
            start = 0
            while True:
                i = mem.find(win, start)
                if i < 0:
                    break
                base = i - off
                if base >= 0:
                    votes[base] = votes.get(base, 0) + 1
                start = i + 1
        need = min_votes or max(2, len(windows) // 2)
        good = sorted(b for b, v in votes.items() if v >= need)
        self.bases = [GC_BASE + b for b in good]
        # soft sanity signal: a DAT header starts with the file size
        for gc in self.bases:
            hdr = struct.unpack(">I", mem[gc - GC_BASE: gc - GC_BASE + 4])[0]
            if hdr != len(self.data):
                # header can legitimately differ (some loaders stomp it);
                # the majority vote is the real evidence
                pass
        return self.bases

    def find(self, needle, mem=None):
        """Targeted search: every MEM1 GC address where `needle` occurs.
        Use with a data-only byte string sampled from the file to pinpoint
        live copies that locate()'s window vote may under-count (heavily
        relocated / runtime-modified images)."""
        if mem is None:
            mem = self.d.snapshot(MEM1_VALID)
        hits, start = [], 0
        while True:
            i = mem.find(needle, start)
            if i < 0:
                break
            hits.append(GC_BASE + i)
            start = i + 1
        return hits

    # -- access -------------------------------------------------------------

    def _need_base(self):
        if not self.bases:
            raise RuntimeError(f"{self.path.name}: not located (call locate())")

    def read(self, file_off, size, copy=0):
        self._need_base()
        return self.d.bytes(self.bases[copy] + file_off, size)

    def poke(self, file_off, data):
        """Write bytes at a file offset in EVERY resident copy."""
        self._need_base()
        ok = True
        for gc in self.bases:
            ok = self.d.write_bytes(gc + file_off, bytes(data)) and ok
        return ok

    def restore(self, file_off, size):
        """Put the original file bytes back."""
        return self.poke(file_off, self.data[file_off:file_off + size])

    def poke_rgb_table(self, start, end, stride, rgb):
        """Recolor a table of records: write 3 RGB bytes at each stride step,
        leaving the record's other bytes untouched (the community-mod pattern
        seen in e.g. EfFxData 0x1A884)."""
        rgb = bytes(rgb)
        assert len(rgb) == 3
        for off in range(start, end, stride):
            if not self.poke(off, rgb):
                return False
        return True

    def restore_range(self, start, end):
        return self.restore(start, end - start)
