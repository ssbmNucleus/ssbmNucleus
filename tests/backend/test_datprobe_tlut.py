"""shared.rendering.datprobe reads the HSD_Tlut colour count at 0x0C.

HSD_Tlut (decomp sysdolphin/baselib/tobj.h; HSDRaw HSD_Tlut) is
``lut*`` 0x00, ``fmt`` 0x04, ``tlut_name`` 0x08, ``u16 n_entries`` 0x0C; 0x0E
is padding. Reading 0x0E gave every palette-format texture an empty palette.
"""
from tests.paths import BACKEND
import struct
import sys
from pathlib import Path

import pytest

BACKEND_DIR = BACKEND
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from shared.rendering import datprobe as dp                                  # noqa: E402


def _dat_with_tlut(tmp_path, colors):
    """Minimal DAT: a palette at data 0x00, one HSD_Tlut struct after it."""
    palette = b''.join(struct.pack('>H', c) for c in colors)
    palette += b'\0' * (-len(palette) % 0x20)
    tlut_off = len(palette)
    # data*, fmt (1 = RGB565), gx tlut name, u16 count, u16 pad
    tlut = struct.pack('>IIIHH', 0, 1, 0, len(colors), 0)
    data = palette + tlut + b'\0' * 0x10
    relocs = [tlut_off]                     # the data pointer (value 0) is real
    body = data + struct.pack(f'>{len(relocs)}I', *relocs)
    header = struct.pack('>IIIII', 0x20 + len(body), len(data), len(relocs),
                         0, 0) + b'\0' * 12
    path = tmp_path / 'tlut.dat'
    path.write_bytes(header + body)
    return path, tlut_off


def test_tlut_count_is_read_at_0x0c(tmp_path):
    colors = [0xF800, 0x07E0, 0x001F, 0xFFFF]
    path, off = _dat_with_tlut(tmp_path, colors)
    tlut = dp.DatFile(path).tlut_at(off)
    assert tlut.format == 1
    assert tlut.count == len(colors)
    assert tlut.data == b''.join(struct.pack('>H', c) for c in colors)


def test_vanilla_mario_eye_track_has_full_ci8_palette():
    try:
        from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
        path = ensure_vanilla_ref('PlMrNr.dat')
    except Exception:                       # pragma: no cover - env dependent
        path = None
    if not path or not Path(path).exists():
        pytest.skip('no vanilla ISO / PlMrNr.dat available')
    d = dp.DatFile(path)
    roots = d.find_roots('matanim_joint')
    assert roots
    anims = [a for _, off in roots for a in d.matanim_texanims(off)]
    ci8 = [(img, tl) for a in anims for img, tl in zip(a.images, a.tluts)
           if img.format == 9]
    assert ci8, 'Mario eye track should hold CI8 frames'
    for image, tlut in ci8:
        assert tlut.count == 256
        assert len(tlut.data) == 512
        rows = dp.decode_image(image, tlut)
        assert any(px[3] for row in rows for px in row)


def test_palette_shorter_than_the_indices_decodes_transparent():
    """A CI8 image indexing past its palette's count does not raise."""
    image = dp.Image(0, 0, 8, 4, 9, bytes(range(32)))
    tlut = dp.Tlut(0, 0, 1, 2, struct.pack('>HH', 0xF800, 0x07E0))
    rows = dp.decode_image(image, tlut)
    assert rows[0][0] == (255, 0, 0, 255)
    assert rows[0][1] == (0, 255, 0, 255)
    assert rows[0][2] == (0, 0, 0, 0)


def test_vendored_processor_copy_matches_skinlab():
    """utility/tools/processor/datprobe.py is the standalone build's copy."""
    vendored = BACKEND_DIR.parent / 'utility' / 'tools' / 'processor' / 'datprobe.py'
    own = BACKEND_DIR / 'shared' / 'rendering' / 'datprobe.py'
    norm = lambda p: p.read_bytes().replace(b'\r\n', b'\n')  # noqa: E731
    assert norm(vendored) == norm(own)

