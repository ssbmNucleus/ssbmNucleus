"""
Launching the Slippi playback Dolphin: the video backend, and noticing when it
did not start.

A user hit "Failed to initialize Direct3D. Make sure your video card supports
D3D 10.0" on Watch combo. Two separate defects sat behind that one screenshot:

  1. Dolphin's video backend lives in Dolphin.ini [Core] GFXBackend (NOT in
     GFX.ini). With that key absent or EMPTY, Dolphin falls back to its
     compiled-in Windows default of D3D11. Nucleus does not choose D3D -- but
     _force_render_window() CREATES Dolphin.ini when it is missing, so for
     anyone who installed the playback build and never launched it, we author
     the file that has no backend in it.

  2. The job announced "playing" on the line after Popen and never looked at
     the exit code, so a Dolphin that died on startup left the modal claiming
     to be playing over a black window.

The empty-string case is the subtle one and has its own test: _read_ini_key
returns "" for `GFXBackend = `, which is a real state in the wild (it is what
the netplay build ships with), so an `is not None` guard would skip exactly
the machines that need the fix.
"""
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tracker.replays import dolphin_config, playback, recording


@pytest.fixture
def playback_user(tmp_path, monkeypatch):
    """A stand-in playback User dir, with the real INI helpers left alone."""
    user = tmp_path / "User"
    (user / "Config").mkdir(parents=True)
    for _mod in (dolphin_config, playback, recording):
        monkeypatch.setattr(_mod, "_playback_user_dir", lambda: str(user))
    return user


def ini_of(user):
    return user / "Config" / "Dolphin.ini"


def read_backend(user):
    return dolphin_config._read_ini_key(str(ini_of(user)), "Core", "GFXBackend")


# ---------------------------------------------------------------------------
# the backend seed
# ---------------------------------------------------------------------------

def test_seeds_ogl_when_the_file_does_not_exist(playback_user):
    """The cohort we actually create this problem for."""
    dolphin_config._force_render_window()          # this is what creates the file
    dolphin_config._ensure_video_backend()
    assert read_backend(playback_user) == "OGL"


def test_seeds_ogl_when_the_key_is_absent(playback_user):
    ini_of(playback_user).write_text(
        "[Core]\nSomethingElse = 1\n", encoding="utf-8")
    dolphin_config._ensure_video_backend()
    assert read_backend(playback_user) == "OGL"


def test_seeds_ogl_when_the_key_is_EMPTY(playback_user):
    """`GFXBackend = ` behaves exactly like an absent key -- Dolphin falls back
    to D3D11 -- and it is what the netplay build ships with, so this is the
    case most likely to be live on a real machine."""
    ini_of(playback_user).write_text(
        "[Core]\nGFXBackend = \nOtherKey = 2\n", encoding="utf-8")
    dolphin_config._ensure_video_backend()
    assert read_backend(playback_user) == "OGL"


@pytest.mark.parametrize("chosen", ["D3D", "Vulkan", "OGL", "Null"])
def test_never_overwrites_a_deliberate_choice(playback_user, chosen):
    """Silently rewriting someone's graphics config generates its own bug
    reports. Even D3D -- if they set it, they keep it."""
    ini_of(playback_user).write_text(
        f"[Core]\nGFXBackend = {chosen}\n", encoding="utf-8")
    dolphin_config._ensure_video_backend()
    assert read_backend(playback_user) == chosen


def test_preserves_the_rest_of_the_file(playback_user):
    """A line-preserving edit: Dolphin.ini holds the user's whole config and
    we are touching one key in it."""
    original = textwrap.dedent("""\
        [General]
        LastFilename = /some/path.iso

        [Core]
        SlippiReplayDir = D:\\replays

        [Display]
        Fullscreen = True
        """)
    ini_of(playback_user).write_text(original, encoding="utf-8")
    dolphin_config._ensure_video_backend()
    after = ini_of(playback_user).read_text(encoding="utf-8")
    for line in ("LastFilename = /some/path.iso",
                 "SlippiReplayDir = D:\\replays",
                 "Fullscreen = True"):
        assert line in after
    assert read_backend(playback_user) == "OGL"


def test_no_user_dir_is_survivable(monkeypatch):
    """A config nicety must never be the reason playback fails."""
    for _mod in (dolphin_config, playback, recording):
        monkeypatch.setattr(_mod, "_playback_user_dir", lambda: None)
    dolphin_config._ensure_video_backend()      # must not raise


def test_unwritable_config_is_survivable(playback_user, monkeypatch):
    def boom(*a, **k):
        raise OSError("read-only")
    monkeypatch.setattr(dolphin_config, "_set_ini_keys", boom)
    dolphin_config._ensure_video_backend()      # must not raise


# ---------------------------------------------------------------------------
# noticing a Dolphin that never started
# ---------------------------------------------------------------------------

def spawn(code, sleep_s=0):
    src = f"import sys,time; time.sleep({sleep_s}); sys.exit({code})"
    return subprocess.Popen([sys.executable, "-c", src],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def test_early_exit_is_detected():
    proc = spawn(1)
    assert playback._early_exit(proc, grace_s=10) == 1


def test_a_process_that_keeps_running_is_not_a_failure():
    """The normal case: Dolphin is alive and playing, so the grace period
    elapses and the job goes on to say 'playing'."""
    proc = spawn(0, sleep_s=30)
    try:
        assert playback._early_exit(proc, grace_s=1.0) is None
    finally:
        proc.kill()
        proc.wait()


def test_stderr_tail_is_captured_and_bounded():
    src = ("import sys\n"
           "for i in range(500): print('line %d' % i, file=sys.stderr)\n")
    proc = subprocess.Popen([sys.executable, "-c", src],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    tail = playback._drain_stderr(proc)
    proc.wait(timeout=30)
    # The pump is a thread; give it a moment to finish the last lines.
    for _ in range(50):
        if len(tail) >= playback._STDERR_TAIL_LINES:
            break
        import time as _t
        _t.sleep(0.05)
    assert len(tail) <= playback._STDERR_TAIL_LINES, 'tail must stay bounded'
    assert "line 499" in list(tail)[-1], 'must keep the LAST lines, not the first'


def test_a_noisy_process_does_not_deadlock():
    """The reason the tail is drained in a thread at all: an unread stderr
    pipe fills, the child blocks writing to it, and playback hangs with no
    visible cause. 200KB is far more than a pipe buffer."""
    src = ("import sys\n"
           "sys.stderr.write('x' * 200000)\n"
           "sys.stderr.flush()\n")
    proc = subprocess.Popen([sys.executable, "-c", src],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    playback._drain_stderr(proc)
    assert proc.wait(timeout=30) == 0


def test_failure_message_names_the_file_to_edit():
    msg = playback._launch_failure_message(
        1, ["Failed to initialize Direct3D."])
    assert "GFXBackend" in msg
    assert "OGL" in msg
    assert "Direct3D" in msg          # the user's own words are echoed back
    # The playback/netplay config split is the thing that misleads people.
    assert "netplay" in msg.lower()


def test_failure_message_with_no_output_still_advises():
    """Dolphin can die having written nothing useful; the advice is still the
    best guess available and costs nothing to try."""
    msg = playback._launch_failure_message(3, [])
    assert "GFXBackend" in msg
    assert "code 3" in msg
