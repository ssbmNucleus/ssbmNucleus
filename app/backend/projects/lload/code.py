"""The per-project L-load Gecko code: the fixed words from `lload.s` with this
project's group table spliced in (no assembler at export; see gen_code.py)."""
from __future__ import annotations

from projects.lload.code_words import BODY, PREFIX

HOOK = 0x80263334            # fn_80262F44 epilogue, a CSS proc that runs every frame
CODE_NAME = 'MENU | L-Load Alternate Fighters'
CODE_CREATOR = 'SSBM Nucleus'
CODE_HEADER = f'{CODE_NAME} [{CODE_CREATOR}]'


def table_bytes(groups: list[list[tuple[int, int]]]) -> bytes:
    """count (base + alternates), count x {external id, icon}; a count of 0 ends it."""
    out = bytearray()
    for members in groups:
        out.append(len(members))
        for ext, icon in members:
            if not (0 <= ext <= 0xFF and 0 <= icon <= 0xFF):
                raise ValueError(f'fighter {ext} / icon {icon} does not fit the table')
            out += bytes((ext, icon))
    out.append(0)
    while len(out) % 4:
        out.append(0)
    return bytes(out)


def words(groups: list[list[tuple[int, int]]]) -> list[int]:
    table = table_bytes(groups)
    bl = 0x48000001 | (4 + len(table))          # bl over the table to its end
    return ([*PREFIX, bl]
            + [int.from_bytes(table[i:i + 4], 'big') for i in range(0, len(table), 4)]
            + list(BODY))


def source(groups: list[list[tuple[int, int]]]) -> str:
    """The C2 block as Gecko hex lines (padded so the last word is 0)."""
    body = words(groups)
    body += [0x00000000] if len(body) % 2 else [0x60000000, 0x00000000]
    lines = [f'C2{HOOK & 0x01FFFFFF:06X} {len(body) // 2:08X}']
    lines += [f'{body[i]:08X} {body[i + 1]:08X}' for i in range(0, len(body), 2)]
    return '\n'.join(lines)
