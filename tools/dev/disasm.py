"""Disassemble a live MEM1 address range out of a GameCube main.dol.

The Any Climbers engine patch hooks common CPU-AI code, so authoring it means
reading the real instructions at addresses the decomp only names.  DOL sections
are flat, so an address maps to a file offset by its owning section.

Dev-only (needs devkitPro's objdump); lives in tools/dev, not the shipped app tree.
Usage: python tools/dev/disasm.py <main.dol> <hex addr> [hex length]
"""
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

OBJDUMP = Path(r"C:/devkitPro/devkitPPC/bin/powerpc-eabi-objdump.exe")


def sections(dol: bytes):
    offs = struct.unpack('>18I', dol[0x00:0x48])
    addrs = struct.unpack('>18I', dol[0x48:0x90])
    sizes = struct.unpack('>18I', dol[0x90:0xD8])
    return [(o, a, s) for o, a, s in zip(offs, addrs, sizes) if s]


def to_file_offset(dol: bytes, addr: int):
    for off, base, size in sections(dol):
        if base <= addr < base + size:
            return off + (addr - base)
    raise ValueError(f"0x{addr:08X} is in no DOL section")


def disasm(dol_path, addr, length=0x80):
    dol = Path(dol_path).read_bytes()
    start = to_file_offset(dol, addr)
    blob = dol[start:start + length]
    with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as fh:
        fh.write(blob)
        tmp = fh.name
    try:
        out = subprocess.run(
            [str(OBJDUMP), '-D', '-b', 'binary', '-m', 'powerpc', '-EB',
             f'--adjust-vma=0x{addr:X}', tmp],
            capture_output=True, text=True, check=True)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return '\n'.join(l for l in out.stdout.splitlines()
                     if ':\t' in l or l.startswith('8'))


if __name__ == '__main__':
    dol = sys.argv[1]
    addr = int(sys.argv[2], 16)
    length = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x80
    print(disasm(dol, addr, length))
