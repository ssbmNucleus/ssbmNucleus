"""Recordings mux EVERY frame-dump segment, with the audio (tracker #85).

Dolphin starts a new framedump<N>.avi whenever its render size changes, and
the embedded playback window is resized as the watch modal lays out (the
launching -> playing switch at the very least). Only framedump0.avi used to be
muxed: the video (and, through -shortest, the audio) stopped at the first
resize, and a header-only first segment made ffmpeg fail, leaving a 0-byte
mp4 plus the silent raw AVI -- "no audio ... also creates a 0 byte mp4".
"""
import os
import array
import math
import shutil
import struct
import subprocess
import wave

import pytest

from core.media_tools import get_ffmpeg
from tracker.replays import dolphin_config, playback, recording, watch_mods

pytestmark = pytest.mark.slow


def _avi(path, width, height, frames=0, total_in_header=None):
    """A minimal AVI: RIFF/hdrl/avih + a movi list with ``frames`` chunks."""
    avih = struct.pack("<14I", 16666, 0, 0, 0,
                       frames if total_in_header is None else total_in_header,
                       0, 1, 0, width, height, 0, 0, 0, 0)
    hdrl = b"hdrl" + b"avih" + struct.pack("<I", len(avih)) + avih
    movi = b"movi" + b"".join(b"00dc" + struct.pack("<I", 4) + b"\0\0\0\0"
                              for _ in range(frames))
    body = (b"AVI " + b"LIST" + struct.pack("<I", len(hdrl)) + hdrl
            + b"LIST" + struct.pack("<I", len(movi)) + movi)
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return str(path)


@pytest.fixture
def dump(tmp_path, monkeypatch):
    user = tmp_path / "User"
    (user / "Dump" / "Frames").mkdir(parents=True)
    (user / "Dump" / "Audio").mkdir(parents=True)
    for _mod in (dolphin_config, playback, recording):
        monkeypatch.setattr(_mod, "_playback_user_dir", lambda: str(user))
    return user


def test_avi_info_reads_size_and_spots_header_only_files(tmp_path):
    assert _avi(tmp_path / "a.avi", 584, 480, frames=3)
    assert recording._avi_info(str(tmp_path / "a.avi")) == (584, 480, True)
    _avi(tmp_path / "e.avi", 640, 528, frames=0)
    assert recording._avi_info(str(tmp_path / "e.avi")) == (640, 528, False)
    # a dump ended by Terminate: header says 0 frames, but the data is there
    _avi(tmp_path / "t.avi", 728, 600, frames=5, total_in_header=0)
    assert recording._avi_info(str(tmp_path / "t.avi"))[2] is True


def test_segments_are_in_write_order_and_skip_empty_files(dump):
    frames = dump / "Dump" / "Frames"
    _avi(frames / "framedump0.avi", 640, 528, frames=0)   # pre-embed size
    for i in (1, 2, 10):
        _avi(frames / f"framedump{i}.avi", 848, 700, frames=2)
    got = [os.path.basename(p) for p in recording._frame_segments(str(dump))]
    assert got == ["framedump1.avi", "framedump2.avi", "framedump10.avi"]


def test_one_segment_keeps_the_plain_mux(tmp_path):
    seg = _avi(tmp_path / "framedump0.avi", 584, 480, frames=2)
    audio = tmp_path / "dspdump.wav"
    audio.write_bytes(b"\0" * 64)
    cmd = recording._mux_command("ffmpeg", [seg], str(audio), "out.mp4",
                                 max_seconds=5)
    assert cmd == ["ffmpeg", "-y", "-i", seg, "-i", str(audio),
                   "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2,setdar=4/3", "-c:v", "libx264", "-crf", "18",
                   "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                   "-t", "5.000", "out.mp4"]


def test_several_segments_are_concatenated_and_the_audio_is_mapped(tmp_path):
    segs = [_avi(tmp_path / "framedump1.avi", 608, 500, frames=2),
            _avi(tmp_path / "framedump2.avi", 849, 700, frames=2)]
    audio = tmp_path / "dspdump.wav"
    audio.write_bytes(b"\0" * 64)
    cmd = recording._mux_command("ffmpeg", segs, str(audio), "out.mp4",
                                 widescreen=True)
    assert cmd[cmd.index("-i", 3) + 1] == segs[1]
    graph = cmd[cmd.index("-filter_complex") + 1]
    # one even canvas (the largest segment), then concat, then the aspect tag
    assert "[0:v]scale=848:700,setsar=1[s0]" in graph
    assert "[1:v]scale=848:700,setsar=1[s1]" in graph
    assert graph.endswith("[s0][s1]concat=n=2:v=1:a=0,pad=ceil(iw/2)*2:ceil(ih/2)*2,setdar=16/9[v]")
    assert cmd[cmd.index("-i", cmd.index(segs[1])) + 1] == str(audio)
    maps = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-map"]
    assert maps == ["[v]", "2:a"]
    assert "-vf" not in cmd


def test_a_failed_mux_leaves_no_empty_mp4(dump, tmp_path, monkeypatch):
    frames = dump / "Dump" / "Frames"
    _avi(frames / "framedump0.avi", 584, 480, frames=2)
    _avi(frames / "framedump1.avi", 848, 700, frames=9)
    with wave.open(str(dump / "Dump" / "Audio" / "dspdump.wav"), "wb") as wav:
        wav.setparams((2, 2, 32000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\0" * 128)
    out_dir = tmp_path / "rec"

    def failing_ffmpeg(cmd, **kw):
        open(cmd[-1], "wb").close()        # ffmpeg creates it, then fails
        return subprocess.CompletedProcess(cmd, 1, "", "Conversion failed!")

    monkeypatch.setattr(recording, "get_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(watch_mods.subprocess, "run", failing_ffmpeg)
    with pytest.raises(RuntimeError, match="Conversion failed"):
        recording._collect_recording("g.slp", name="g", out_dir=str(out_dir))
    assert os.listdir(out_dir) == []


# ---------------------------------------------------------------------------
# real ffmpeg: a resized dump still becomes one full-length video WITH audio
# ---------------------------------------------------------------------------

def _find_ffmpeg():
    """The first ffmpeg that actually runs -- the bundled one first (python
    tools/build/fetch_ffmpeg.py). One on PATH can be present but unusable
    (a wrong-architecture build fails with WinError 216)."""
    candidates = [get_ffmpeg(), shutil.which("ffmpeg")]
    try:
        import imageio_ffmpeg
        candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:  # noqa: BLE001
        pass
    for exe in filter(None, candidates):
        try:
            if subprocess.run([exe, "-version"], capture_output=True, timeout=20).returncode == 0:
                return exe
        except (OSError, subprocess.SubprocessError):
            continue
    return None


FFMPEG = _find_ffmpeg()


def _probe(path):
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", path],
                       capture_output=True, text=True)
    return r.stderr


@pytest.mark.skipif(not FFMPEG, reason="no working ffmpeg on this machine")
@pytest.mark.parametrize("compress", [False, True])
@pytest.mark.parametrize("widescreen", [False, True])
def test_resized_dump_records_the_whole_game_with_audio(dump, tmp_path,
                                                        monkeypatch, compress, widescreen):
    frames = dump / "Dump" / "Frames"
    _avi(frames / "framedump0.avi", 640, 528, frames=0)   # header-only
    for i, (w, h, secs) in enumerate([(584, 480, 1), (848, 700, 2)], 1):
        subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i",
                        f"testsrc=size={w}x{h}:rate=60:duration={secs}",
                        "-c:v", "mjpeg", str(frames / f"framedump{i}.avi")],
                       check=True)
    wav = dump / "Dump" / "Audio" / "dspdump.wav"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=32000:duration=3",
                    "-ac", "2", "-c:a", "pcm_s16le", str(wav)], check=True)
    monkeypatch.setattr(recording, "get_ffmpeg", lambda: FFMPEG)
    out_dir = tmp_path / "rec"
    saved = recording._collect_recording("g.slp", compress=compress, name="g",
                                         max_seconds=3.0, widescreen=widescreen,
                                         out_dir=str(out_dir))
    assert saved and saved.endswith(".mp4"), saved
    assert os.listdir(out_dir) == [os.path.basename(saved)]
    info = _probe(saved)
    assert "Audio: aac" in info
    assert ("DAR 16:9" if widescreen else "DAR 4:3") in info
    dur = info.split("Duration: ")[1].split(",")[0]
    h, m, s = dur.split(":")
    assert float(s) + 60 * int(m) > 2.8, info   # not cut at the first segment
    # An audio stream alone is not evidence of audible samples. Decode what
    # a player receives and check every quarter second, including the join.
    decoded = subprocess.run([FFMPEG, "-v", "error", "-i", saved, "-vn",
                              "-ac", "1", "-ar", "32000", "-f", "f32le", "-"],
                             capture_output=True, check=True).stdout
    samples = array.array("f", decoded)
    assert 2.98 < len(samples) / 32000 < 3.05
    for offset in range(0, 96000, 8000):
        chunk = samples[offset:offset + 8000]
        assert math.sqrt(sum(s * s for s in chunk) / len(chunk)) > 0.02


# A stopped game has no max_seconds, and the installer ships no ffprobe: the
# Discord encode must still be the size-targeted two-pass, budgeted over the
# audio dump's length, not the heavy CRF fallback that can miss 10 MB.
@pytest.mark.skipif(not FFMPEG, reason="no working ffmpeg on this machine")
def test_stopped_game_compresses_by_its_audio_length(dump, tmp_path, monkeypatch):
    frames = dump / "Dump" / "Frames"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=640x480:rate=60:duration=4",
                    "-c:v", "ffv1", str(frames / "framedump0.avi")], check=True)
    wav = dump / "Dump" / "Audio" / "dspdump.wav"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=32000:duration=4",
                    "-ac", "2", "-c:a", "pcm_s16le", str(wav)], check=True)
    monkeypatch.setattr(recording, "get_ffmpeg", lambda: FFMPEG)
    budgets, plan = [], recording._compress_plan
    monkeypatch.setattr(recording, "_compress_plan",
                        lambda seconds, *a: budgets.append(seconds) or plan(seconds, *a))
    saved = recording._collect_recording("g.slp", compress=True, name="g",
                                         out_dir=str(tmp_path / "rec"))
    assert saved and saved.endswith("g_discord.mp4"), saved
    assert budgets == [pytest.approx(4.0, abs=0.01)]
    assert 0 < os.path.getsize(saved) < recording.DISCORD_LIMIT_BYTES
    assert "Audio: aac" in _probe(saved)


# An odd-sized dump (Dolphin dumps at the window's size) used to fail the normal
# export -- libx264/yuv420p needs even sizes -- and save nothing (bug 11-19).
@pytest.mark.skipif(not FFMPEG, reason="no working ffmpeg on this machine")
@pytest.mark.parametrize("width,height", [(640, 480), (641, 481), (640, 481), (641, 480)])
@pytest.mark.parametrize("widescreen", [False, True])
def test_odd_sized_dump_records_with_even_size(dump, tmp_path, monkeypatch, width, height, widescreen):
    import re

    frames = dump / "Dump" / "Frames"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"testsrc=size={width}x{height}:rate=30:duration=1",
                    "-c:v", "ffv1", str(frames / "framedump0.avi")], check=True)
    wav = dump / "Dump" / "Audio" / "dspdump.wav"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=32000:duration=1",
                    "-ac", "2", "-c:a", "pcm_s16le", str(wav)], check=True)
    monkeypatch.setattr(recording, "get_ffmpeg", lambda: FFMPEG)
    out_dir = tmp_path / "rec"
    saved = recording._collect_recording("g.slp", name="g", max_seconds=1.0,
                                         widescreen=widescreen, out_dir=str(out_dir))
    assert saved and os.path.getsize(saved) > 0
    info = _probe(saved)
    video = next(line for line in info.splitlines() if "Video: h264" in line)
    w, h = map(int, re.search(r", (\d{2,5})x(\d{2,5})[ ,]", video).groups())
    # one border pixel at most, never a cropped source pixel
    assert (w, h) == (width + width % 2, height + height % 2), video
    assert ("DAR 16:9" if widescreen else "DAR 4:3") in video
    assert "Audio: aac" in info
    dur = info.split("Duration: ")[1].split(",")[0]
    hours, minutes, seconds = dur.split(":")
    assert float(seconds) + 60 * int(minutes) + 3600 * int(hours) > 0.5, info
