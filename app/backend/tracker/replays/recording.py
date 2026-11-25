"""Turning the playback Dolphin's frame and audio dumps into a video: the recordings folder, the
full-quality mux, and the two-pass encode that fits Discord's upload cap."""

import glob
import ntpath
import os
import struct
import subprocess
import time

from core.config import OUTPUT_PATH
from core.child_env import child_environment
from core.media_tools import get_ffmpeg

from .dolphin_config import _playback_user_dir


DEFAULT_RECORDINGS_DIR = OUTPUT_PATH / "recordings"


def recording_dir():
    """Where finished recordings land — user-configurable (persisted in the
    index kv store), defaulting to output/recordings."""
    from ..store import indexer
    conn = indexer.connect()
    try:
        val = indexer.kv_get(conn, "recording_dir")
    finally:
        conn.close()
    return val or str(DEFAULT_RECORDINGS_DIR)


def set_recording_dir(path):
    """Persist the recording output folder. Returns the stored value (empty
    path clears back to the default)."""
    from ..store import indexer
    conn = indexer.connect()
    try:
        indexer.kv_set(conn, "recording_dir", (path or "").strip() or None)
    finally:
        conn.close()
    return recording_dir()


# Discord's default (non-Nitro) upload cap. Aim a hair under so muxing
# overhead / VBV slack never pushes the file over the line.
DISCORD_LIMIT_BYTES = 10 * 1024 * 1024
_COMPRESS_TARGET_BYTES = int(9.3 * 1024 * 1024)
_COMPRESS_AUDIO_KBPS = 96


def _NO_WINDOW():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _compress_plan(duration_s, has_audio=True):
    """(video_kbps, audio_kbps, height) for a Discord-sized encode of
    ``duration_s`` seconds, or None when the duration is unknown.

    The budget is fixed (_COMPRESS_TARGET_BYTES), so a long game gets fewer
    bits per second: audio drops to 64/32 kbps and the picture to 360p/240p
    before the video bitrate is squeezed below what that height can carry.
    A flat 120 kbps floor under 96 kbps audio overshot 10 MB for any game
    longer than about six minutes."""
    if not duration_s or duration_s <= 0:
        return None
    total_kbps = _COMPRESS_TARGET_BYTES * 8 / 1000 / duration_s
    if not has_audio:
        audio_kbps = 0
    elif total_kbps >= 700:
        audio_kbps = _COMPRESS_AUDIO_KBPS
    elif total_kbps >= 300:
        audio_kbps = 64
    else:
        audio_kbps = 32
    video_kbps = max(40, int(total_kbps - audio_kbps))
    height = 480 if video_kbps >= 450 else 360 if video_kbps >= 200 else 240
    return video_kbps, audio_kbps, height


def _limit_args(max_seconds):
    """ffmpeg output option that cuts the file at the game's last frame."""
    return ["-t", f"{max_seconds:.3f}"] if max_seconds else []


# --- frame-dump segments ------------------------------------------------------
# Dolphin starts a NEW framedump<N>.avi every time its render size changes.
# The playback window is embedded in the modal, which re-lays it out as the
# job moves launching -> playing (and on any app resize), so one recording is
# routinely several segments -- the first often a header-only file written at
# the pre-embed size. Muxing only framedump0.avi cut the video to that first
# segment (and -shortest cut the audio with it); a header-only first segment
# made ffmpeg fail outright ("Nothing was written into output file"), which
# left a 0-byte mp4 behind and saved the silent raw AVI instead (tracker #85).

def _natural_key(path):
    """framedump2.avi before framedump10.avi (a plain sort puts 10 first)."""
    import re
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", os.path.basename(path))]


def _avi_info(path):
    """(width, height, has_frames) from an AVI header. has_frames is False for
    the header-only file Dolphin leaves when it resizes before the first frame
    (nothing after the 'movi' list header). A dump cut short by Terminate has
    no index and a zero frame count in its header, but it does have data."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            head = f.read(65536)
    except OSError:
        return None, None, False
    w = h = None
    i = head.find(b"avih")
    if i >= 0 and len(head) >= i + 48:
        vals = struct.unpack("<10I", head[i + 8:i + 48])
        w, h = vals[8] or None, vals[9] or None
    movi = head.find(b"movi")
    has_frames = size > movi + 12 if movi >= 0 else size > len(head)
    return w, h, has_frames


def _frame_segments(user):
    """Every frame-dump segment of the last run that holds any video, in the
    order Dolphin wrote them."""
    paths = sorted(glob.glob(os.path.join(user, "Dump", "Frames", "framedump*.avi")),
                   key=_natural_key)
    return [p for p in paths if _avi_info(p)[2]]


def _video_args(segments, vf):
    """ffmpeg (inputs, video filter + map) for the frame dump.

    One segment keeps the plain `-vf` path. Several are each scaled to one
    canvas (the largest segment's size: they all hold the same forced-aspect
    picture, only rendered at different window sizes) and concatenated back
    into one stream. The audio input, if any, follows at index
    len(segments) and must then be mapped explicitly (_audio_map)."""
    if len(segments) == 1:
        return ["-i", segments[0]], ["-vf", vf]
    dims = [d for d in (_avi_info(s)[:2] for s in segments) if d[0] and d[1]]
    cw, ch = max(dims, key=lambda d: d[0] * d[1]) if dims else (640, 480)
    cw, ch = cw - cw % 2, ch - ch % 2
    inputs, parts = [], []
    for k, seg in enumerate(segments):
        inputs += ["-i", seg]
        parts.append(f"[{k}:v]scale={cw}:{ch},setsar=1[s{k}]")
    labels = "".join(f"[s{k}]" for k in range(len(segments)))
    graph = ";".join(parts) + f";{labels}concat=n={len(segments)}:v=1:a=0,{vf}[v]"
    return inputs, ["-filter_complex", graph, "-map", "[v]"]


def _audio_map(segments):
    return [] if len(segments) == 1 else ["-map", f"{len(segments)}:a"]


def _wav_seconds(path):
    """Length of a dspdump.wav from its sample bytes. Dolphin's header holds a
    placeholder length until the dump is closed cleanly, which Terminate
    never does. Locate the data chunk so an empty WAV with metadata/padding
    cannot be mistaken for audio merely because it is larger than 44 bytes."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            header = handle.read(12)
            if header[:4] != b"RIFF" or header[8:] != b"WAVE":
                return None
            while handle.tell() + 8 <= size:
                kind, length = struct.unpack("<4sI", handle.read(8))
                if kind == b"data":
                    return max(0.0, (size - handle.tell()) / AUDIO_BYTES_PER_SEC) or None
                handle.seek(length + length % 2, os.SEEK_CUR)
    except (OSError, struct.error):
        return None
    return None


def _discard(path):
    """ffmpeg creates its output before it knows the encode will fail; never
    leave that empty or partial file in the recording folder."""
    try:
        os.remove(path)
    except OSError:
        pass


def _run_encode(cmd):
    """An encoder failure must reach the recording job, not a silent AVI."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800,
                                creationflags=_NO_WINDOW(), env=child_environment())
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Recording encoder timed out. Try a shorter recording.") from exc
    except OSError as exc:
        raise RuntimeError(f"Recording encoder could not start: {exc}") from exc
    if result.returncode:
        detail = " | ".join((result.stderr or "").splitlines()[-4:])[-1500:]
        raise RuntimeError(f"Recording encoding failed (ffmpeg {result.returncode})."
                           + (f" {detail}" if detail else ""))
    return result


def _encode_compressed(ffmpeg, segments, audio, out, widescreen=False,
                       max_seconds=None):
    """Two-pass, size-targeted encode that lands under Discord's 10 MB cap.
    Derives the bitrate (and, for long games, a lower resolution and audio
    rate) from the clip duration so even a full match fits. ``max_seconds``
    is both the cut point and the duration the budget is spread over: it is
    known exactly for a whole game. A stopped game is spread over its audio
    dump's length, which every recording has (_collect_recording refuses one
    without) and -shortest never lets the video outlast. Its frame dump is
    no help: Terminate leaves no length in the AVI header (ffmpeg and
    ffprobe both read N/A), and ffprobe is not shipped anyway.
    Falls back to a heavy single-pass CRF when the duration is unknown. One
    retry at 80% bitrate if the result still lands over the cap.
    ``segments``: the frame-dump files (see _frame_segments). Returns True
    on success."""
    has_audio = os.path.exists(audio)
    duration = max_seconds or (_wav_seconds(audio) if has_audio else None)
    dar = "16/9" if widescreen else "4/3"
    # setdar is a safety net for dumps made before the 4:3 fix (or if a Dolphin
    # build still dumps at window aspect): it tags the display aspect rather than
    # resampling, so a squished frame plays back correctly at no quality cost.
    plan = _compress_plan(duration, has_audio)
    limit = _limit_args(max_seconds)
    if plan:
        video_kbps, audio_kbps, height = plan
        v_in, v_args = _video_args(segments, f"scale=-2:{height},setdar={dar}")
        # ffmpeg drops a passlog next to cwd; keep it beside the output
        passlog = os.path.splitext(out)[0] + "_ff2pass"
        ok = False
        for _attempt in range(2):
            base = [ffmpeg, "-y", *v_in, *v_args,
                    "-c:v", "libx264", "-b:v", f"{video_kbps}k",
                    "-pix_fmt", "yuv420p", "-passlogfile", passlog]
            p1 = _run_encode(base + ["-pass", "1", "-an", *limit, "-f", "mp4",
                                     os.devnull])
            cmd2 = [ffmpeg, "-y", *v_in]
            if has_audio:
                cmd2 += ["-i", audio]
            cmd2 += [*v_args, "-c:v", "libx264", "-b:v", f"{video_kbps}k",
                     "-pix_fmt", "yuv420p", "-passlogfile", passlog, "-pass", "2"]
            if has_audio:
                cmd2 += [*_audio_map(segments),
                         "-c:a", "aac", "-b:a", f"{audio_kbps}k", "-shortest"]
            cmd2 += [*limit, out]
            p2 = _run_encode(cmd2)
            ok = (p1.returncode == 0 and p2.returncode == 0
                  and os.path.exists(out) and os.path.getsize(out) > 0)
            if not ok or os.path.getsize(out) < DISCORD_LIMIT_BYTES:
                break
            video_kbps = max(30, int(video_kbps * 0.8))
        for leftover in glob.glob(passlog + "*"):
            try:
                os.remove(leftover)
            except OSError:
                pass
        if not ok:
            _discard(out)
        return ok
    # duration unknown: best-effort single pass, heavy CRF + downscale
    v_in, v_args = _video_args(segments, f"scale=-2:480,setdar={dar}")
    cmd = [ffmpeg, "-y", *v_in]
    if has_audio:
        cmd += ["-i", audio]
    cmd += [*v_args, "-c:v", "libx264", "-crf", "30",
            "-preset", "slower", "-pix_fmt", "yuv420p"]
    if has_audio:
        cmd += [*_audio_map(segments),
                "-c:a", "aac", "-b:a", f"{_COMPRESS_AUDIO_KBPS}k", "-shortest"]
    cmd += [out]
    r = _run_encode(cmd)
    ok = r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0
    if not ok:
        _discard(out)
    return ok


# libx264 with yuv420p needs an even width and height. Dolphin dumps frames at
# the window's size, which can be odd (641x481), and the encode then failed and
# saved nothing (bug 11-19). One border pixel on the right/bottom fixes it and
# keeps every source pixel; even sizes pass through unchanged.
EVEN_PAD = "pad=ceil(iw/2)*2:ceil(ih/2)*2"


def _mux_command(ffmpeg, segments, audio, out, widescreen=False,
                 max_seconds=None):
    """The full-quality (non-Discord) mux of every frame-dump segment plus
    the audio dump."""
    has_audio = os.path.exists(audio)
    v_in, v_args = _video_args(segments,
                               f"{EVEN_PAD},setdar={'16/9' if widescreen else '4/3'}")
    cmd = [ffmpeg, "-y", *v_in]
    if has_audio:
        cmd += ["-i", audio]
    cmd += [*v_args, "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p"]
    if has_audio:
        cmd += [*_audio_map(segments), "-c:a", "aac", "-shortest"]
    return cmd + [*_limit_args(max_seconds), out]


def _collect_recording(replay_path, compress=False, widescreen=False,
                       name=None, max_seconds=None, out_dir=None):
    """Mux the playback Dolphin's frame + audio dumps into an mp4 in the
    recording folder. Missing audio or encoding failures fail the job;
    a video-only AVI is not a successful recording.
    When compress=True, encode a size-targeted file that fits Discord's
    10 MB upload cap.

    name: the file name without extension (default: replay stem + timestamp).
    max_seconds: cut the video there (a whole game's exact length; the dump
    runs a hair past the last frame before Dolphin is stopped).
    out_dir: the folder chosen when the job started (default: the configured
    recording folder). Returns the saved path or None."""
    user = _playback_user_dir()
    if not user:
        return None
    frames = _frame_segments(user)
    if not frames:
        return None
    audio = os.path.join(user, "Dump", "Audio", "dspdump.wav")
    # A terminated Dolphin has placeholder lengths in its WAV header. Inspect
    # actual sample bytes, not the advertised frame count. A valid all-zero
    # recording is allowed (a silent moment); no samples at all is an error.
    if not _wav_seconds(audio):
        raise RuntimeError("Dolphin recorded no audio (dspdump.wav is missing or empty). "
                           "Try recording again after checking playback audio.")
    ffmpeg = get_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("Recording needs ffmpeg to combine video and audio. "
                           "Install ffmpeg or repair the Nucleus installation.")
    from pathlib import Path
    out_dir = Path(out_dir or recording_dir())
    out_dir.mkdir(parents=True, exist_ok=True)
    if not name:
        stem = os.path.splitext(ntpath.basename(replay_path))[0]
        name = f"{stem}_{time.strftime('%Y%m%d-%H%M%S')}"
    suffix = "_discord" if compress else ""
    out = str(out_dir / f"{name}{suffix}.mp4")
    saved = False
    try:
        if compress:
            saved = _encode_compressed(ffmpeg, frames, audio, out,
                                       widescreen=widescreen, max_seconds=max_seconds)
        else:
            cmd = _mux_command(ffmpeg, frames, audio, out, widescreen=widescreen,
                               max_seconds=max_seconds)
            _run_encode(cmd)
            saved = os.path.exists(out) and os.path.getsize(out) > 0
        if not saved:
            raise RuntimeError("Recording encoder produced no video. Try recording again.")
        return out
    finally:
        if not saved:
            _discard(out)
        # Also clean pass logs after a launch error/timeout in either pass.
        for leftover in glob.glob(os.path.splitext(out)[0] + "_ff2pass*"):
            _discard(leftover)


AUDIO_BYTES_PER_SEC = 128000       # dspdump.wav: 32 kHz s16 stereo
