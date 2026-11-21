"""core/movie_stubs.py -- Free space stubs movies instead of deleting them
(Tracker #92, docs/MEX_BUILD_LIMITS.md). Deleting a vanilla Mv*.mth crashes the
build after every 1P clear, on the title attract loop, and in Data -> Movies,
because the game opens them by name with no missing-file check.

These tests build small synthetic MTH files by hand (real vanilla movies are
hundreds of MB and not in the repo) and check the stub writer produces a valid,
playable header/frame chain, and that file selection never touches anything but
the 28 explicit vanilla names.
"""
import io
import struct

import pytest

from core import movie_stubs


# ── synthetic MTH builder ────────────────────────────────────────────────────

def _frame(payload, next_size):
    """One MTH frame: [u32 size of the NEXT frame][payload], 32-aligned."""
    body = struct.pack('>I', next_size) + payload
    pad = (-len(body)) % movie_stubs._FRAME_ALIGN
    return body + b'\x00' * pad


def _make_mth(num_frames, payload=b'JPEGDATA'):
    """A synthetic MTH with `num_frames` identical frames, each carrying the
    size of the next (looping back to frame 0, like a real vanilla movie)."""
    frame_bytes = _frame(payload, 0)  # placeholder; every frame is the same size
    frame_size = len(frame_bytes)
    frames = b''
    for i in range(num_frames):
        frames += _frame(payload, frame_size)
    header = bytearray(movie_stubs.HEADER_SIZE)
    header[:4] = movie_stubs.MTH_MAGIC
    struct.pack_into('>10I', header, 4,
                      0x80000, 2, frame_size, 640, 480, 30, num_frames,
                      movie_stubs.HEADER_SIZE, 0, frame_size)
    return bytes(header) + frames


# ── parse_header ─────────────────────────────────────────────────────────────

def test_parse_header_rejects_bad_magic():
    with pytest.raises(movie_stubs.MthError):
        movie_stubs.parse_header(b'NOPE' + b'\x00' * 60)


def test_parse_header_reads_vanilla_like_fields():
    data = _make_mth(50)
    info = movie_stubs.parse_header(data[:movie_stubs.HEADER_SIZE])
    assert info['numFrames'] == 50
    assert info['width'] == 640 and info['height'] == 480
    assert info['isStub'] is False


# ── cut_stub_from_file ─────────────────────────────────────────────────────

def cut_stub(data, frames=movie_stubs.STUB_FRAMES):
    return movie_stubs.cut_stub_from_file(io.BytesIO(data), frames=frames)


def test_cut_stub_needs_minimum_frames():
    short = _make_mth(10)  # fewer than MIN_STUB_FRAMES
    with pytest.raises(movie_stubs.MthError):
        cut_stub(short)


def test_cut_stub_produces_a_valid_playable_header():
    movie = _make_mth(200)
    stub = cut_stub(movie, frames=movie_stubs.STUB_FRAMES)
    info = movie_stubs.parse_header(stub[:movie_stubs.HEADER_SIZE])
    assert info['numFrames'] == movie_stubs.STUB_FRAMES
    assert info['isStub'] is True
    assert info['firstFrame'] == movie_stubs.HEADER_SIZE
    # Stub is much smaller than the source movie it was cut from.
    assert len(stub) < len(movie)


def test_cut_stub_is_at_least_the_minimum_frame_count():
    # A movie shorter than STUB_FRAMES but still above the minimum: the stub
    # is capped to what the movie actually has, not padded or over-read.
    movie = _make_mth(35)
    stub = cut_stub(movie, frames=movie_stubs.STUB_FRAMES)
    info = movie_stubs.parse_header(stub[:movie_stubs.HEADER_SIZE])
    assert info['numFrames'] == 35


def test_cut_stub_frame_chain_is_internally_consistent():
    """Walk the stub's own frame chain (the player's read pattern) and check it
    never reads past the stub's end and visits exactly numFrames frames."""
    movie = _make_mth(200)
    stub = cut_stub(movie, frames=movie_stubs.STUB_FRAMES)
    info = movie_stubs.parse_header(stub[:movie_stubs.HEADER_SIZE])
    off, size, n = info['firstFrame'], info['firstFrameSize'], 0
    while n < info['numFrames']:
        assert off + size <= len(stub)
        frame = stub[off:off + size]
        next_size = struct.unpack('>I', frame[:4])[0]
        off += size
        size = next_size
        n += 1
    assert n == movie_stubs.STUB_FRAMES


def test_cut_stub_below_minimum_frames_raises():
    movie = _make_mth(200)
    with pytest.raises(movie_stubs.MthError):
        cut_stub(movie, frames=movie_stubs.MIN_STUB_FRAMES - 1)


# ── black_stub (MvOpen) ──────────────────────────────────────────────────────

def test_black_stub_reaches_the_frame_the_opening_scene_waits_for():
    stub = movie_stubs.black_stub()
    info = movie_stubs.parse_header(stub[:movie_stubs.HEADER_SIZE])
    assert info['numFrames'] >= movie_stubs.OPENING_MIN_FRAMES
    assert info['isStub'] is True


def test_black_stub_frame_chain_is_valid_and_matches_declared_size():
    stub = movie_stubs.black_stub(frames=50)  # small for a fast test
    info = movie_stubs.parse_header(stub[:movie_stubs.HEADER_SIZE])
    off, size, n = info['firstFrame'], info['firstFrameSize'], 0
    while n < info['numFrames']:
        assert off + size <= len(stub)
        frame = stub[off:off + size]
        assert frame[4:6] == b'\xff\xd8'   # JPEG SOI marker right after the size prefix
        off += size
        size = struct.unpack('>I', frame[:4])[0]
        n += 1
    assert n == 50


def test_black_stub_rejects_too_few_frames():
    with pytest.raises(ValueError):
        movie_stubs.black_stub(frames=movie_stubs.MIN_STUB_FRAMES - 1)


def test_black_stub_size_matches_actual_output_length():
    stub = movie_stubs.black_stub(frames=64)
    assert movie_stubs.black_stub_size(frames=64) == len(stub)


def test_black_jpeg_has_no_ff_byte_in_the_scan_data():
    # THP's baseline decoder in Melee doesn't unstuff 0xFF bytes in scan data;
    # the hand-built Huffman tables must never emit one.
    jpeg = movie_stubs._black_jpeg(640, 480)
    assert jpeg[:2] == b'\xff\xd8'
    assert jpeg[-2:] == b'\xff\xd9'
    # scan is between SOS and EOI
    sos = jpeg.index(b'\xff\xda')
    scan = jpeg[sos:-2]
    # strip the SOS marker/segment header itself before checking for 0xFF
    seg_len = struct.unpack('>H', scan[2:4])[0]
    body = scan[2 + seg_len:]
    assert b'\xff' not in body


# ── vanilla-only file selection ─────────────────────────────────────────────


def test_vanilla_movies_list_has_the_28_vanilla_names():
    assert len(movie_stubs.VANILLA_MOVIES) == 28
    assert movie_stubs.OPENING_MOVIE in movie_stubs.VANILLA_MOVIES
    assert 'MvHowto.mth' in movie_stubs.VANILLA_MOVIES
    assert 'MvOmake15.mth' in movie_stubs.VANILLA_MOVIES


def test_replace_movies_with_stubs_never_touches_an_added_fighters_movie(tmp_path):
    files_dir = tmp_path / 'files'
    files_dir.mkdir()
    vanilla = _make_mth(200)
    (files_dir / 'MvEndMario.mth').write_bytes(vanilla)
    # An added fighter's own end movie -- same "Mv*.mth" naming pattern, but
    # NOT a vanilla name. Free space must never touch this file.
    added_fighter_movie = _make_mth(200, payload=b'WOLFDATA')
    (files_dir / 'MvEndWolf.mth').write_bytes(added_fighter_movie)
    # Also plant an unrelated file that happens to start with "mv" (lowercase
    # bucketing in the disc-usage category) to make sure it's untouched too.
    (files_dir / 'mvSomethingElse.dat').write_bytes(b'not a movie at all')

    result = movie_stubs.replace_movies_with_stubs(files_dir)

    assert result['stubbed'] == ['MvEndMario.mth']
    assert (files_dir / 'MvEndWolf.mth').read_bytes() == added_fighter_movie
    assert (files_dir / 'mvSomethingElse.dat').read_bytes() == b'not a movie at all'
    stubbed = (files_dir / 'MvEndMario.mth').read_bytes()
    assert len(stubbed) < len(vanilla)
    info = movie_stubs.parse_header(stubbed[:movie_stubs.HEADER_SIZE])
    assert info['isStub'] is True


def test_replace_movies_with_stubs_is_idempotent(tmp_path):
    files_dir = tmp_path / 'files'
    files_dir.mkdir()
    (files_dir / 'MvEndMario.mth').write_bytes(_make_mth(200))

    first = movie_stubs.replace_movies_with_stubs(files_dir)
    assert first['stubbed'] == ['MvEndMario.mth']
    after_first = (files_dir / 'MvEndMario.mth').read_bytes()

    second = movie_stubs.replace_movies_with_stubs(files_dir)
    assert second['stubbed'] == []
    # MvOpen was auto-restored (as a black stub) by the first call, since
    # restore_missing defaults to True; the second call finds it's already a
    # stub too and skips it right alongside MvEndMario.
    assert 'MvEndMario.mth' in second['skipped']
    assert (files_dir / 'MvEndMario.mth').read_bytes() == after_first


def test_replace_movies_with_stubs_writes_mvopen_as_black_stub(tmp_path):
    files_dir = tmp_path / 'files'
    files_dir.mkdir()
    # Big enough that the black stub (~6 MB for the default frame count) is
    # still a net size win, like the real 121 MiB vanilla MvOpen.mth.
    (files_dir / 'MvOpen.mth').write_bytes(_make_mth(6000, payload=b'X' * 5000))

    result = movie_stubs.replace_movies_with_stubs(files_dir)

    assert result['stubbed'] == ['MvOpen.mth']
    data = (files_dir / 'MvOpen.mth').read_bytes()
    info = movie_stubs.parse_header(data[:movie_stubs.HEADER_SIZE])
    assert info['numFrames'] >= movie_stubs.OPENING_MIN_FRAMES
    assert info['isStub'] is True


def test_restore_missing_movies_only_touches_missing_files(tmp_path):
    files_dir = tmp_path / 'files'
    files_dir.mkdir()
    present = _make_mth(200)
    (files_dir / 'MvEndMario.mth').write_bytes(present)
    # MvOpen missing (simulates a pre-0.8.11 project the old Free space deleted
    # movies from) -- restorable with no vanilla ISO because it's synthetic.
    result = movie_stubs.restore_missing_movies(files_dir)

    assert 'MvOpen.mth' in result['restored']
    # The already-present movie was left completely alone (not re-stubbed).
    assert (files_dir / 'MvEndMario.mth').read_bytes() == present
    assert result['stubbed'] == []
    # Every other missing vanilla movie needs a vanilla ISO we didn't give it.
    assert 'MvEndLuigi.mth' in result['unresolved']


def test_movie_status_reports_full_stubbed_and_missing(tmp_path):
    files_dir = tmp_path / 'files'
    files_dir.mkdir()
    (files_dir / 'MvEndMario.mth').write_bytes(_make_mth(200))
    stub = cut_stub(_make_mth(200))
    (files_dir / 'MvEndLuigi.mth').write_bytes(stub)

    status = movie_stubs.movie_status(files_dir)

    assert 'MvEndMario.mth' in status['full']
    assert 'MvEndLuigi.mth' in status['stubbed']
    assert 'MvOpen.mth' in status['missing']
    assert status['reclaimableBytes'] > 0
