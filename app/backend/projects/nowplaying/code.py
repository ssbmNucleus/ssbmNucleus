"""The Now Playing Gecko code: one C2 block built from the committed words of
`now_playing.s` (no assembler at create or export; see gen_code.py)."""
from __future__ import annotations

from projects.nowplaying.code_words import WORDS

HOOK = 0x802F3A60            # final blr of ifAll_802F390C, the in-match HUD setup
CODE_NAME = 'QOL | Now Playing (Song Name at Match Start)'
CODE_CREATOR = 'SSBM Nucleus'
CODE_HEADER = f'{CODE_NAME} [{CODE_CREATOR}]'
TITLE = 'Now Playing'
DESCRIPTION = ('Shows the song name in a banner that slides in at the top left '
               'for a few seconds when a match starts.')
# A build that already draws the song name (the ACE Build's display plugin)
# would show it twice with this code on.
CONFLICTING_FILE = 'bgm_display.dat'


def source() -> str:
    """The C2 block as Gecko hex lines (padded so the last word is 0)."""
    body = list(WORDS)
    body += [0x00000000] if len(body) % 2 else [0x60000000, 0x00000000]
    lines = [f'C2{HOOK & 0x01FFFFFF:06X} {len(body) // 2:08X}']
    lines += [f'{body[i]:08X} {body[i + 1]:08X}' for i in range(0, len(body), 2)]
    return '\n'.join(lines)
