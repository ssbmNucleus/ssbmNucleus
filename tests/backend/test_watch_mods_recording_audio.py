"""A recording must never report a silent fallback as a successful export."""
import subprocess
import struct
import wave
from pathlib import Path

import pytest

from tracker.replays import recording


@pytest.fixture
def audio_dump(tmp_path, monkeypatch):
    user = tmp_path / "User"
    frames = user / "Dump" / "Frames"
    frames.mkdir(parents=True)
    avi = frames / "framedump0.avi"
    avi.write_bytes(b"fake video")
    audio = user / "Dump" / "Audio" / "dspdump.wav"
    audio.parent.mkdir()
    with wave.open(str(audio), "wb") as wav:
        wav.setparams((2, 2, 32000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\x01\x00" * 6400)
    monkeypatch.setattr(recording, "_playback_user_dir", lambda: str(user))
    monkeypatch.setattr(recording, "_frame_segments", lambda _user: [str(avi)])
    monkeypatch.setattr(recording, "get_ffmpeg", lambda: "ffmpeg")
    return audio, tmp_path / "recordings"


@pytest.mark.parametrize("compress", [False, True])
@pytest.mark.parametrize("state", ["missing", "empty", "header_only", "metadata_only", "invalid"])
def test_missing_audio_is_an_error(audio_dump, monkeypatch, compress, state):
    audio, out_dir = audio_dump
    if state == "missing":
        audio.unlink()
    elif state == "empty":
        audio.write_bytes(b"")
    elif state == "invalid":
        audio.write_bytes(b"invalid" * 100)
    else:
        with wave.open(str(audio), "wb") as wav:
            wav.setparams((2, 2, 32000, 0, "NONE", "not compressed"))
        if state == "metadata_only":
            header = audio.read_bytes()
            audio.write_bytes(header[:36] + b"JUNK" + struct.pack("<I", 64)
                              + b"\0" * 64 + header[36:])

    def success(cmd, **_kwargs):
        if cmd[-1] != recording.os.devnull:
            Path(cmd[-1]).write_bytes(b"silent mp4")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(recording.subprocess, "run", success)
    with pytest.raises(RuntimeError, match="audio"):
        recording._collect_recording("g.slp", compress=compress, name="g",
                                     max_seconds=1, out_dir=str(out_dir))
    assert not out_dir.exists() or not list(out_dir.iterdir())


@pytest.mark.parametrize("compress", [False, True])
@pytest.mark.parametrize("failure", ["exit", "timeout", "launch"])
def test_encoder_errors_surface_without_partial_or_silent_files(
        audio_dump, monkeypatch, compress, failure):
    _audio, out_dir = audio_dump

    def fail(cmd, **_kwargs):
        if "-passlogfile" in cmd:
            Path(cmd[cmd.index("-passlogfile") + 1] + "-0.log").write_text("partial pass")
        if cmd[-1] != recording.os.devnull:
            Path(cmd[-1]).write_bytes(b"partial mp4")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(cmd, 1800)
        if failure == "launch":
            raise OSError("encoder unavailable")
        return subprocess.CompletedProcess(cmd, 1, "", "Conversion failed!")

    monkeypatch.setattr(recording.subprocess, "run", fail)
    with pytest.raises(RuntimeError, match="[Ee]ncod"):
        recording._collect_recording("g.slp", compress=compress, name="g",
                                     max_seconds=1, out_dir=str(out_dir))
    assert not list(out_dir.iterdir())


def test_missing_ffmpeg_does_not_save_silent_avi(audio_dump, monkeypatch):
    _audio, out_dir = audio_dump
    monkeypatch.setattr(recording, "get_ffmpeg", lambda: None)
    with pytest.raises(RuntimeError, match="ffmpeg"):
        recording._collect_recording("g.slp", name="g", out_dir=str(out_dir))
    assert not out_dir.exists() or not list(out_dir.iterdir())


def test_unclosed_dolphin_header_does_not_hide_real_samples(audio_dump):
    audio, _out_dir = audio_dump
    data = bytearray(audio.read_bytes())
    struct.pack_into("<I", data, 4, 0)
    struct.pack_into("<I", data, 40, 0)
    audio.write_bytes(data)
    assert recording._wav_seconds(audio) == pytest.approx(.1)


def test_second_pass_failure_cleans_output_and_pass_logs(audio_dump, monkeypatch):
    _audio, out_dir = audio_dump
    passes = []

    def encode(cmd, **_kwargs):
        which_pass = cmd[cmd.index("-pass") + 1]
        passes.append(which_pass)
        Path(cmd[cmd.index("-passlogfile") + 1] + "-0.log").write_text("pass log")
        if which_pass == "2":
            Path(cmd[-1]).write_bytes(b"incomplete mp4")
            return subprocess.CompletedProcess(cmd, 1, "", "audio encoding failed")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(recording.subprocess, "run", encode)
    with pytest.raises(RuntimeError, match="audio encoding failed"):
        recording._collect_recording("g.slp", compress=True, name="g",
                                     max_seconds=1, out_dir=str(out_dir))
    assert passes == ["1", "2"]
    assert not list(out_dir.iterdir())


@pytest.mark.parametrize("compress", [False, True])
def test_empty_successful_encode_is_an_error(audio_dump, monkeypatch, compress):
    _audio, out_dir = audio_dump
    monkeypatch.setattr(recording.subprocess, "run",
                        lambda cmd, **_kw: subprocess.CompletedProcess(cmd, 0, "", ""))
    with pytest.raises(RuntimeError, match="produced no video"):
        recording._collect_recording("g.slp", compress=compress, name="g",
                                     max_seconds=1, out_dir=str(out_dir))
    assert not list(out_dir.iterdir())


def test_stopped_game_compresses_by_its_audio_length_with_ffmpeg_only(audio_dump, monkeypatch):
    """A stopped game has no max_seconds, and the installer ships no ffprobe
    (it could not read a terminated dump's length anyway). The Discord encode
    is still the size-targeted two-pass, budgeted over the audio dump, and
    nothing but ffmpeg runs."""
    audio, out_dir = audio_dump
    runs = []

    def encode(cmd, **_kwargs):
        runs.append(cmd)
        if cmd[-1] != recording.os.devnull:
            Path(cmd[-1]).write_bytes(b"small mp4")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(recording.subprocess, "run", encode)
    saved = recording._collect_recording("g.slp", compress=True, name="g", out_dir=str(out_dir))
    assert saved == str(out_dir / "g_discord.mp4")
    assert {cmd[0] for cmd in runs} == {"ffmpeg"}
    video_kbps, _audio_kbps, _height = recording._compress_plan(recording._wav_seconds(audio))
    assert [cmd[cmd.index("-pass") + 1] for cmd in runs] == ["1", "2"]
    assert all(cmd[cmd.index("-b:v") + 1] == f"{video_kbps}k" for cmd in runs)
    assert not any("-crf" in cmd or "-t" in cmd for cmd in runs)   # not the fallback, not cut


@pytest.mark.parametrize("widescreen,dar", [(False, "4/3"), (True, "16/9")])
def test_full_quality_mux_pads_to_an_even_size(tmp_path, widescreen, dar):
    """libx264/yuv420p refuses an odd frame size, and Dolphin dumps at the
    window's size (bug 11-19). The real encode is checked in the slow set
    (test_watch_mods_dump_segments.py)."""
    cmd = recording._mux_command("ffmpeg", [str(tmp_path / "framedump0.avi")],
                                 str(tmp_path / "dspdump.wav"), str(tmp_path / "out.mp4"),
                                 widescreen=widescreen)
    assert cmd[cmd.index("-vf") + 1] == f"pad=ceil(iw/2)*2:ceil(ih/2)*2,setdar={dar}"
