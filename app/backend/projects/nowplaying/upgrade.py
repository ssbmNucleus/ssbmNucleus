"""Move an existing project's Now Playing entry to the current code.

Projects keep the hex they were created with. Before every export MexCLI
compiles files/codes.ini into the build (`MexManager.export_iso` calls
`upgrade_project` first), so an entry whose hex is EXACTLY an earlier version
(previous_versions.py) gets the current hex there. Only that entry's hex lines
change: its header, so its enabled flag and name, its description and its
position stay, and every other byte of the file is kept as it was.

Left alone: an entry the user edited (hex that is no earlier version), a
project without Now Playing (nothing is ever added), and a build that already
draws the song name itself (the ACE Build's bgm_display.dat).

Imports no `core`: mexcli.project calls it, and that module must not.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

from projects.nowplaying import code as now_playing
from projects.nowplaying.previous_versions import PREVIOUS_SOURCES

logger = logging.getLogger(__name__)

_NEWLINE = re.compile(r'\r\n|\r|\n')     # what .NET's ReadLine splits on
_BOM = '﻿'


def _hex(line: str) -> str | None:
    """mexLib's Hex.TrimHexLine: drop a '#' comment and all whitespace; a code
    line is exactly 16 hex digits. Upper-cased, so case is no edit."""
    trimmed = re.sub(r'\s+', '', line.split('#', 1)[0])
    return trimmed.upper() if re.fullmatch(r'[0-9A-Fa-f]{16}', trimmed) else None


def _words(source: str) -> tuple[str, ...]:
    return tuple(h for h in map(_hex, _NEWLINE.split(source)) if h)


def _lines(text: str) -> list[tuple[str, str]]:
    """(body, line ending) per line; joined back they are `text` exactly."""
    out, pos = [], 0
    for m in _NEWLINE.finditer(text):
        out.append((text[pos:m.start()], m.group()))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], ''))
    return out


def upgrade_text(text: str, current: str | None = None,
                 previous=PREVIOUS_SOURCES) -> tuple[str, int]:
    """Return (text, entries upgraded). `current` defaults to the code's
    `source()`; tests pass their own. Same text back when nothing matched."""
    current = now_playing.source() if current is None else current
    new_words = _words(current)
    known = {_words(p) for p in previous} - {new_words}
    if not new_words or not known:
        return text, 0
    lines = _lines(text)
    starts = [i for i, (body, _) in enumerate(lines)
              if (body.lstrip(_BOM) if i == 0 else body).startswith('$')]
    replace = []                       # (first, last) hex line of each matching entry
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        hex_at = [i for i in range(start + 1, end)
                  if not lines[i][0].startswith('*') and _hex(lines[i][0])]
        if not hex_at or tuple(_hex(lines[i][0]) for i in hex_at) not in known:
            continue
        # A blank or comment line inside the block is a hand edit too.
        if hex_at[-1] - hex_at[0] + 1 != len(hex_at):
            continue
        replace.append((hex_at[0], hex_at[-1]))
    if not replace:
        return text, 0
    new_lines = [line for line in _NEWLINE.split(current) if _hex(line)]
    for first, last in reversed(replace):
        inner = lines[first][1] or '\r\n'
        block = [(body, inner) for body in new_lines]
        block[-1] = (block[-1][0], lines[last][1])   # the block ends as it did
        lines[first:last + 1] = block
    return ''.join(body + end for body, end in lines), len(replace)


def _draws_song_name_itself(files_dir: Path) -> bool:
    name = getattr(now_playing, 'CONFLICTING_FILE', 'bgm_display.dat')
    return next(files_dir.rglob(name), None) is not None


def upgrade_project(project_path, current: str | None = None) -> int:
    """Upgrade the Now Playing entry in `project_path`'s files/codes.ini (the
    .mexproj path). Returns the number of entries rewritten; 0 when there was
    nothing to do. Raises OSError when the file cannot be read or written."""
    files_dir = Path(project_path).parent / 'files'
    ini = files_dir / 'codes.ini'
    if not ini.is_file():
        return 0
    raw = ini.read_bytes()
    # surrogateescape round-trips any byte, so the rest of the file stays exact
    text = raw.decode('utf-8', errors='surrogateescape')
    upgraded, count = upgrade_text(text, current)
    if not count:
        return 0
    if _draws_song_name_itself(files_dir):
        logger.info(f'Now Playing: {ini} holds an older version, but the build draws '
                    f'the song name itself; left as it is')
        return 0
    fd, tmp = tempfile.mkstemp(prefix='codes.', suffix='.ini.tmp', dir=str(files_dir))
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(upgraded.encode('utf-8', errors='surrogateescape'))
        shutil.copymode(ini, tmp)
        os.replace(tmp, ini)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    logger.info(f'Now Playing: upgraded {count} codes.ini entr{"y" if count == 1 else "ies"} '
                f'from an earlier version to the current code ({ini})')
    return count
