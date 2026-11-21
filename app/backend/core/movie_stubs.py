"""
movie_stubs.py -- "Free space" for movies without breaking the game.

Melee's 28 vanilla movies (Mv*.mth, ~811 MiB) are most of the disc. Deleting
them is NOT safe: the game opens them by name with no missing-file check, so a
build without them crashes (devcom assert in lbMthp) after the credits of
every Classic / Adventure / All-Star clear (MvEnd<char>.mth), when the title
screen idles into the attract loop (MvOpen.mth, MvHowto.mth), and in
Data -> Movies. Tracker #92, docs/dev/MEX_BUILD_LIMITS.md.

Instead, each movie is replaced by a short, valid stand-in:

  * Every movie except MvOpen: its own first STUB_FRAMES frames. The player
    preloads 32 frames before it looks at the frame count, so a stub needs at
    least 33 frames; 40 is the verified size. The scenes that play these
    (ending movie, How to Play, the 15-minute special) move on when the movie
    ends, so they just play for ~1.3 s.
  * MvOpen: the opening scene (gm_Scene_Opening_OnFrame) only finishes once
    the movie's 60 Hz tick counter passes 5400, and the counter stops at the
    last frame. With the scene's rate table {1250x2, 394x1, rest x2} that is
    movie frame 2898, so a short stub freezes the title attract loop. It gets
    OPENING_STUB_FRAMES black frames instead: a tiny hand-built JPEG (custom
    one-symbol Huffman tables, ~2 KB a frame), repeated.

Only the explicit vanilla file names in VANILLA_MOVIES are ever touched --
never an added fighter's MvEnd<Name>.mth or any other file starting "mv".
Stubs carry STUB_MARKER in the header's unused padding, so re-running is a
no-op.

MTH layout (lbmthp.c, fn_8001EB14): a 0x40-byte header
  0x00 'MTHP'  0x04 ?  0x08 version  0x0C bufSize (largest frame, 32-aligned)
  0x10 width  0x14 height  0x18 fps  0x1C numFrames  0x20 firstFrameOffset
  0x24 frameOffsets (0)  0x28 firstFrameSize  0x2C..0x3F padding (unused)
then frames back to back; each frame is [u32 size of the NEXT frame][JPEG]
padded to a 32-byte multiple. The player reads frame i+1 at
offset(i) + size(i).
"""

import logging
import os
import struct
from pathlib import Path

import file_retry

logger = logging.getLogger(__name__)

# The 28 movies on a vanilla NTSC 1.02 disc (all at the root of files/).
VANILLA_END_MOVIES = (
    'MvEndCaptain.mth', 'MvEndClink.mth', 'MvEndDonkey.mth', 'MvEndDrmario.mth',
    'MvEndFalco.mth', 'MvEndFox.mth', 'MvEndGamewatch.mth', 'MvEndGanon.mth',
    'MvEndKirby.mth', 'MvEndKoopa.mth', 'MvEndLink.mth', 'MvEndLuigi.mth',
    'MvEndMario.mth', 'MvEndMarth.mth', 'MvEndMewtwo.mth', 'MvEndNess.mth',
    'MvEndPeach.mth', 'MvEndPichu.mth', 'MvEndPikachu.mth', 'MvEndPoponana.mth',
    'MvEndPurin.mth', 'MvEndRoy.mth', 'MvEndSamus.mth', 'MvEndYoshi.mth',
    'MvEndZelda.mth',
)
OPENING_MOVIE = 'MvOpen.mth'
VANILLA_MOVIES = VANILLA_END_MOVIES + ('MvHowto.mth', 'MvOmake15.mth', OPENING_MOVIE)

MTH_MAGIC = b'MTHP'
HEADER_SIZE = 0x40
# Written into the header's unused padding (0x30..0x3B) so a stub is
# recognisable and never re-stubbed. The player never reads these bytes.
STUB_MARKER = b'NUCLEUS-STUB'
_MARKER_OFFSET = 0x30

# >= 33 required (the player preloads 32 frames); 40 is what was verified in game.
STUB_FRAMES = 40
MIN_STUB_FRAMES = 33

# gm_803DBFB4, MvOpen's rate table: 1250 frames x 2 ticks, 394 x 1, then x 2.
# The opening scene needs the tick counter to exceed 5400:
#   frame(5401) = 1250 + 394 + (5401 - 2894) // 2 = 2897, so >= 2898 frames.
# A little margin on top costs ~2 KB a frame.
OPENING_MIN_FRAMES = 2898
OPENING_STUB_FRAMES = 2910
OPENING_WIDTH, OPENING_HEIGHT = 640, 480

_FRAME_ALIGN = 32
# Largest frame buffer any vanilla movie declares is 0xEEE0; refuse anything
# absurd so a corrupt header can't make us read gigabytes.
_MAX_FRAME_SIZE = 4 * 1024 * 1024


class MthError(ValueError):
    """Not a usable MTH movie."""


def _align(n, a=_FRAME_ALIGN):
    return (n + a - 1) // a * a


def parse_header(data):
    """Decode a 0x40-byte MTH header. Raises MthError if it isn't one."""
    if len(data) < HEADER_SIZE or data[:4] != MTH_MAGIC:
        raise MthError('not an MTH movie (bad magic)')
    (unk04, version, buf_size, width, height, fps, num_frames, first_frame,
     frame_offsets, first_frame_size) = struct.unpack('>10I', data[4:44])
    if not (0 < first_frame_size <= _MAX_FRAME_SIZE) or first_frame < HEADER_SIZE:
        raise MthError('implausible MTH header')
    return {
        'unk04': unk04, 'version': version, 'bufSize': buf_size,
        'width': width, 'height': height, 'fps': fps, 'numFrames': num_frames,
        'firstFrame': first_frame, 'frameOffsets': frame_offsets,
        'firstFrameSize': first_frame_size,
        'isStub': data[_MARKER_OFFSET:_MARKER_OFFSET + len(STUB_MARKER)] == STUB_MARKER,
    }


def _mark(header):
    h = bytearray(header[:HEADER_SIZE])
    h[_MARKER_OFFSET:_MARKER_OFFSET + len(STUB_MARKER)] = STUB_MARKER
    return h


# ── stub from a movie's own opening frames ──────────────────────────────────

def _read_cut(read_at, length, frames):
    """Core of the cut stub. `read_at(offset, size)` reads from the movie,
    whose total length is `length`. Returns the stub bytes."""
    header = read_at(0, HEADER_SIZE)
    info = parse_header(header)
    total = info['numFrames']
    if total < MIN_STUB_FRAMES:
        raise MthError(f'movie has only {total} frames')
    k = min(frames, total)
    if k < MIN_STUB_FRAMES:
        raise MthError(f'stub needs at least {MIN_STUB_FRAMES} frames')
    off, size = info['firstFrame'], info['firstFrameSize']
    body = bytearray()
    last_frame_at = None
    for _ in range(k):
        if size <= 4 or size > _MAX_FRAME_SIZE or off + size > length:
            raise MthError('frame chain runs past the end of the movie')
        frame = read_at(off, size)
        if len(frame) != size:
            raise MthError('truncated frame')
        last_frame_at = len(body)
        body += frame
        off += size
        size = struct.unpack('>I', frame[:4])[0]
    # The last frame's "next size" points back at frame 0, as in a real loop,
    # so nothing ever tries to read past the end of the stub.
    struct.pack_into('>I', body, last_frame_at, info['firstFrameSize'])
    h = _mark(header)
    struct.pack_into('>I', h, 0x1C, k)                    # numFrames
    struct.pack_into('>I', h, 0x20, HEADER_SIZE)          # frames follow the header
    struct.pack_into('>I', h, 0x24, 0)                    # no frame-offset table
    return bytes(h) + bytes(body)


def cut_stub_from_file(fh, base=0, length=None, frames=STUB_FRAMES):
    """Stub made of the first `frames` frames of a movie, reading only what it
    needs from an open binary file (a movie file, or a movie inside a disc
    image at `base`)."""
    if length is None:
        fh.seek(0, os.SEEK_END)
        length = fh.tell() - base

    def read_at(o, n):
        fh.seek(base + o)
        return fh.read(n)

    return _read_cut(read_at, length, frames)


# ── long black stub for MvOpen ──────────────────────────────────────────────

def _black_jpeg(width, height):
    """A baseline 4:2:0 JPEG of a black frame, laid out like the frames in
    Melee's own movies (2x DQT, SOF0 with ids 1/2/3, 4x DHT, SOS) but with
    one- and two-symbol Huffman tables: every block after the first costs 2
    bits (DC diff 0 = '0', EOB = '0'), so a 640x480 frame is ~2 KB. No 0xFF
    byte can occur in the scan, so no byte stuffing is needed (THP's decoder
    doesn't unstuff)."""
    if width % 16 or height % 16:
        raise ValueError('frame size must be a multiple of 16')

    def seg(marker, payload):
        return bytes([0xFF, marker]) + struct.pack('>H', len(payload) + 2) + payload

    # Y black = 16: pixel = 128 + DC * q / 8, q = 16 -> DC = -56 (category 6).
    q = bytes([16] * 64)
    dqt = seg(0xDB, b'\x00' + q) + seg(0xDB, b'\x01' + q)
    sof = seg(0xC0, struct.pack('>BHHB', 8, height, width, 3)
              + bytes([1, 0x22, 0, 2, 0x11, 1, 3, 0x11, 1]))

    def dht(tc_th, counts, symbols):
        bits = bytes(counts) + bytes(16 - len(counts))
        return seg(0xC4, bytes([tc_th]) + bits + bytes(symbols))

    tables = (dht(0x00, [1, 1], [0, 6])     # luma DC: '0' = diff 0, '10' = category 6
              + dht(0x10, [1], [0x00])      # luma AC: '0' = EOB
              + dht(0x01, [1], [0])         # chroma DC: '0' = diff 0
              + dht(0x11, [1], [0x00]))     # chroma AC: '0' = EOB
    sos = seg(0xDA, bytes([3, 1, 0x00, 2, 0x11, 3, 0x11, 0, 0x3F, 0]))

    mcus = (width // 16) * (height // 16)
    # First Y block: '10' + 6 magnitude bits of -56 ((1<<6)-1-56 = 7 -> 000111)
    # + EOB '0'. Every other block (3 more Y, U, V; then 6 per MCU): '0' '0'.
    bits = '10' + '000111' + '0' + '00' * 5 + '00' * 6 * (mcus - 1)
    bits += '1' * (-len(bits) % 8)                        # pad with 1s
    scan = int(bits, 2).to_bytes(len(bits) // 8, 'big')
    assert b'\xff' not in scan
    return b'\xFF\xD8' + dqt + sof + tables + sos + scan + b'\xFF\xD9'


def black_stub(frames=OPENING_STUB_FRAMES, width=OPENING_WIDTH, height=OPENING_HEIGHT):
    """An MTH of `frames` identical black frames."""
    if frames < MIN_STUB_FRAMES:
        raise ValueError(f'stub needs at least {MIN_STUB_FRAMES} frames')
    jpeg = _black_jpeg(width, height)
    rec = _align(4 + len(jpeg))
    frame = struct.pack('>I', rec) + jpeg
    frame += b'\x00' * (rec - len(frame))
    h = bytearray(HEADER_SIZE)
    h[:4] = MTH_MAGIC
    # 0x00080000 and version 2 as in every vanilla movie; fps field 30.
    struct.pack_into('>10I', h, 4, 0x80000, 2, rec, width, height, 30, frames,
                     HEADER_SIZE, 0, rec)
    h = _mark(h)
    return bytes(h) + frame * frames


def black_stub_size(frames=OPENING_STUB_FRAMES, width=OPENING_WIDTH, height=OPENING_HEIGHT):
    return HEADER_SIZE + _align(4 + len(_black_jpeg(width, height))) * frames


# ── project files/ ──────────────────────────────────────────────────────────

def _find_vanilla_movies(files_dir):
    """{canonical vanilla name: existing Path or None}. Vanilla movies live at
    the root of files/; the match is case-insensitive (Windows projects)."""
    files_dir = Path(files_dir)
    present = {}
    if files_dir.is_dir():
        for p in files_dir.iterdir():
            if p.is_file():
                present[p.name.lower()] = p
    return {name: present.get(name.lower()) for name in VANILLA_MOVIES}


def _stub_size_of_file(path, name):
    """Size the stub of the movie at `path` would have (reads only headers)."""
    if name == OPENING_MOVIE:
        return black_stub_size()
    with open(path, 'rb') as f:
        header = f.read(HEADER_SIZE)
        info = parse_header(header)
        k = min(STUB_FRAMES, info['numFrames'])
        off, size, total = info['firstFrame'], info['firstFrameSize'], HEADER_SIZE
        for _ in range(k):
            total += size
            f.seek(off)
            nxt = f.read(4)
            if len(nxt) != 4:
                raise MthError('truncated frame')
            off += size
            size = struct.unpack('>I', nxt)[0]
        return total


def movie_status(files_dir):
    """What Free space would do to this project's movies, without writing.
    Returns {'reclaimableBytes', 'full': [...], 'stubbed': [...],
    'missing': [...], 'unreadable': [...]} (vanilla names only)."""
    out = {'reclaimableBytes': 0, 'full': [], 'stubbed': [], 'missing': [], 'unreadable': []}
    for name, path in _find_vanilla_movies(files_dir).items():
        if path is None:
            out['missing'].append(name)
            continue
        try:
            with open(path, 'rb') as f:
                info = parse_header(f.read(HEADER_SIZE))
            if info['isStub']:
                out['stubbed'].append(name)
                continue
            gain = path.stat().st_size - _stub_size_of_file(path, name)
            out['full'].append(name)
            out['reclaimableBytes'] += max(0, gain)
        except (OSError, MthError) as e:
            logger.debug(f'[movie_stubs] {name} unreadable: {e}')
            out['unreadable'].append(name)
    return out


def _write_atomic(path, data):
    path = Path(path)
    tmp = path.with_name(path.name + '.stub.tmp')
    tmp.write_bytes(data)
    file_retry.replace(tmp, path)


def _stub_from_iso(iso_path, name):
    """Cut `name`'s stub straight out of a vanilla disc image, reading only
    the header and the first frames (not the whole movie)."""
    from shared.vanilla_extract.vanilla_refs import list_files_in_iso
    entry = next((e for e in list_files_in_iso(iso_path, contains=name)
                  if e['name'].lower() == name.lower()), None)
    if entry is None:
        raise MthError(f'{name} is not on {iso_path}')
    with open(iso_path, 'rb') as f:
        return cut_stub_from_file(f, base=entry['offset'], length=entry['size'])


def replace_movies_with_stubs(files_dir, vanilla_iso=None, restore_missing=True,
                              stub_existing=True):
    """Free space. For each vanilla movie name:
      * full movie present (and stub_existing) -> replaced by its stub;
      * already a stub -> left alone (idempotent);
      * missing (e.g. deleted by the old Free space) and restore_missing ->
        stub regenerated: MvOpen needs no source, the others are cut from
        `vanilla_iso` (skipped with a warning when no ISO is known).
    Files that aren't valid MTH movies are left untouched.
    Returns {'stubbed', 'restored', 'unresolved', 'skipped', 'freedBytes'}."""
    result = {'stubbed': [], 'restored': [], 'unresolved': [], 'skipped': [], 'freedBytes': 0}
    files_dir = Path(files_dir)
    for name, path in _find_vanilla_movies(files_dir).items():
        try:
            if path is None:
                if not restore_missing:
                    continue
                if name == OPENING_MOVIE:
                    data = black_stub()
                elif vanilla_iso:
                    data = _stub_from_iso(vanilla_iso, name)
                else:
                    result['unresolved'].append(name)
                    continue
                files_dir.mkdir(parents=True, exist_ok=True)
                _write_atomic(files_dir / name, data)
                result['restored'].append(name)
                continue

            with open(path, 'rb') as f:
                info = parse_header(f.read(HEADER_SIZE))
                if info['isStub'] or not stub_existing:
                    result['skipped'].append(name)
                    continue
                old = path.stat().st_size
                data = black_stub() if name == OPENING_MOVIE else cut_stub_from_file(f)
            if len(data) >= old:
                result['skipped'].append(name)
                continue
            _write_atomic(path, data)
            result['stubbed'].append(name)
            result['freedBytes'] += old - len(data)
        except (OSError, MthError) as e:
            logger.warning(f'[movie_stubs] {name}: {e}')
            if path is None:
                result['unresolved'].append(name)
            else:
                result['skipped'].append(name)
    return result


def restore_missing_movies(files_dir, vanilla_iso=None):
    """Export-time repair: put a stub back for every vanilla movie that is
    missing from files/ (projects stripped by the old Free space crash after
    every 1P clear and on title idle). Never touches movies that exist."""
    return replace_movies_with_stubs(files_dir, vanilla_iso,
                                     restore_missing=True, stub_existing=False)
