"""Recording forces the playback Dolphin to 4:3 (16:9 for widescreen), and the
watch options are one Gecko override file. The watch job owns each change with
what was there before, so its end puts exactly that back, also when the
recording fails, and a user's own override file comes back too."""
import itertools

import pytest

from core import jobs
from core import state as core_state
from tracker.replays import dolphin_config, playback, recording, watch_mods


@pytest.fixture(autouse=True)
def job_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "_root_override", tmp_path / "jobs")
    monkeypatch.setattr(jobs, "_jobs", {})
    monkeypatch.setattr(core_state, "get_socketio", lambda: None)
    return tmp_path / "jobs"


def _gfx(tmp_path, monkeypatch, value):
    user = tmp_path / "User"
    (user / "Config").mkdir(parents=True)
    ini = user / "Config" / "GFX.ini"
    ini.write_text(f"[Settings]\nAspectRatio = {value}\n", encoding="utf-8")
    for _mod in (dolphin_config, playback, recording):
        monkeypatch.setattr(_mod, "_playback_user_dir", lambda: str(user))
    return str(ini)


def _aspect(ini):
    return dolphin_config._read_ini_key(ini, *dolphin_config._ASPECT_KEY)


def test_restore_is_idempotent(tmp_path, monkeypatch):
    ini = _gfx(tmp_path, monkeypatch, "1")
    prior = _aspect(ini)
    dolphin_config._force_aspect(ini)
    assert _aspect(ini) == "2"
    # the job's end restores, and a later recovery may restore again
    dolphin_config._restore_aspect(ini, prior)
    dolphin_config._restore_aspect(ini, prior)
    assert _aspect(ini) == "1"


def test_an_absent_aspect_goes_back_to_auto(tmp_path, monkeypatch):
    ini = _gfx(tmp_path, monkeypatch, "1")
    with open(ini, "w", encoding="utf-8") as f:
        f.write("[Settings]\n")
    prior = _aspect(ini)
    assert prior is None
    dolphin_config._force_aspect(ini)
    dolphin_config._restore_aspect(ini, prior)
    assert _aspect(ini) == "0"


def test_widescreen_forces_16_9_and_restores(tmp_path, monkeypatch):
    ini = _gfx(tmp_path, monkeypatch, "0")
    dolphin_config._force_aspect(ini, widescreen=True)
    assert _aspect(ini) == "1"
    dolphin_config._restore_aspect(ini, "0")
    assert _aspect(ini) == "0"


def _overrides(tmp_path, monkeypatch):
    user = tmp_path / "User"
    user.mkdir()
    for _mod in (dolphin_config, playback, recording):
        monkeypatch.setattr(_mod, "_playback_user_dir", lambda: str(user))
    return user / "GameSettings"


def _section(text, name):
    lines = text.splitlines()
    start = lines.index(f"[{name}]") + 1
    out = []
    for line in lines[start:]:
        if line.startswith("["):
            break
        if line.strip():
            out.append(line.strip())
    return out


def test_widescreen_and_anonymize_share_one_override(tmp_path, monkeypatch):
    gs = _overrides(tmp_path, monkeypatch)
    dolphin_config.write_playback_overrides(str(gs), hide_names=True, widescreen=True)
    for gid in dolphin_config._PLAYBACK_GAME_IDS:
        text = (gs / f"{gid}.ini").read_text(encoding="utf-8")
        assert _section(text, "Gecko_Enabled") == ["$Optional: Widescreen 16:9"]
        assert _section(text, "Gecko_Disabled") == ["$Optional: Show Player Names"]
    dolphin_config.remove_playback_overrides(str(gs))
    assert not any(gs.iterdir())


def test_override_cleanup_keeps_user_files(tmp_path, monkeypatch):
    gs = _overrides(tmp_path, monkeypatch)
    gs.mkdir()
    (gs / "GALE01.ini").write_text("[Gecko_Enabled]\n$Mine\n", encoding="utf-8")
    dolphin_config.remove_playback_overrides(str(gs))
    assert (gs / "GALE01.ini").read_text(encoding="utf-8") == "[Gecko_Enabled]\n$Mine\n"


def test_a_user_file_the_watch_replaced_comes_back_byte_for_byte(tmp_path, monkeypatch):
    gs = _overrides(tmp_path, monkeypatch)
    gs.mkdir()
    mine = b"[Gecko_Enabled]\r\n$Mine \xe9\r\n"
    (gs / "GALE01r2.ini").write_bytes(mine)
    prior = dolphin_config._user_overrides(str(gs))
    assert list(prior) == ["GALE01r2"]
    dolphin_config.write_playback_overrides(str(gs), no_music=True)
    assert b"SSBM Nucleus" in (gs / "GALE01r2.ini").read_bytes()
    # our own file is never mistaken for the user's
    assert dolphin_config._user_overrides(str(gs)) == {}
    for _ in range(2):
        dolphin_config.remove_playback_overrides(str(gs), prior)
        assert (gs / "GALE01r2.ini").read_bytes() == mine
        assert not (gs / "GALE01.ini").exists()


# ---------------------------------------------------------------------------
# No music: a third code in the same override file
# ---------------------------------------------------------------------------

_WS = "$Optional: Widescreen 16:9"
_MUSIC_OFF = "$Optional: Game Music OFF"
_NAMES = "$Optional: Show Player Names"


def test_no_music_code_is_the_one_slippi_ships():
    # the playback Dolphin's Sys GameSettings lists it as
    # "$Optional: Game Music OFF [UnclePunch]"; Dolphin matches the name
    # without the author bracket, like the widescreen code.
    assert dolphin_config._NO_MUSIC_CODE == _MUSIC_OFF


@pytest.mark.parametrize("hide_names,widescreen,no_music",
                         list(itertools.product([False, True], repeat=3)))
def test_every_option_combination_writes_one_override(tmp_path, monkeypatch,
                                                      hide_names, widescreen,
                                                      no_music):
    gs = _overrides(tmp_path, monkeypatch)
    seen = {}

    def run(job):
        watch_mods._override_playback(job, record=False, widescreen=widescreen,
                                      anonymize=hide_names, no_music=no_music)
        seen["owned"] = sorted(job.owned)
        seen["files"] = {p.name: p.read_text(encoding="utf-8")
                         for p in (gs.iterdir() if gs.exists() else [])}

    record = jobs.run_inline(watch_mods.WATCH_KIND, run)
    if not (hide_names or widescreen or no_music):
        assert seen["files"] == {} and "overrides" not in seen["owned"]
    else:
        assert "overrides" in seen["owned"]
        for gid in dolphin_config._PLAYBACK_GAME_IDS:
            text = seen["files"][f"{gid}.ini"]
            assert "SSBM Nucleus" in text.splitlines()[0]
            assert _section(text, "Gecko_Enabled") == (
                ([_WS] if widescreen else []) + ([_MUSIC_OFF] if no_music else []))
            assert _section(text, "Gecko_Disabled") == ([_NAMES] if hide_names else [])
    # the job's end removes our files
    assert record["status"] == "done" and record["owned"] == {}
    assert not gs.exists() or not any(gs.iterdir())


# ---------------------------------------------------------------------------
# the job puts everything back, also when it fails
# ---------------------------------------------------------------------------

def _job_env(tmp_path, monkeypatch):
    user = tmp_path / "User"
    (user / "Config").mkdir(parents=True)
    gfx = user / "Config" / "GFX.ini"
    gfx.write_text("[Settings]\nAspectRatio = 3\n", encoding="utf-8")
    for _mod in (dolphin_config, playback, recording):
        monkeypatch.setattr(_mod, "_playback_user_dir", lambda: str(user))
    for _mod in (watch_mods, dolphin_config):
        monkeypatch.setattr(_mod, "playback_dolphin_path", lambda: "dolphin.exe")
    for _mod in (watch_mods, dolphin_config):
        monkeypatch.setattr(_mod, "_force_render_window", lambda: None)
    monkeypatch.setattr(watch_mods, "_ensure_video_backend", lambda: None)
    for _mod in (playback, watch_mods, dolphin_config):
        monkeypatch.setattr(_mod, "_clear_old_dumps", lambda: None)
    return user, gfx


def _watch(**kwargs):
    return jobs.run_inline(watch_mods.WATCH_KIND, lambda job: watch_mods._run_job(
        job, "g1.slp", "vanilla.iso", [], **kwargs))


@pytest.mark.parametrize("anonymize,widescreen", [(False, False), (True, True)])
def test_no_music_is_live_during_playback_and_restored_on_error(
        tmp_path, monkeypatch, anonymize, widescreen):
    user, gfx = _job_env(tmp_path, monkeypatch)
    seen = {}

    def fake_launch(dolphin, comm, iso, job=None):
        text = (user / "GameSettings" / "GALE01r2.ini").read_text(encoding="utf-8")
        seen["enabled"] = _section(text, "Gecko_Enabled")
        seen["disabled"] = _section(text, "Gecko_Disabled")
        raise RuntimeError("dolphin fell over")

    for _mod in (playback, watch_mods):
        monkeypatch.setattr(_mod, "_launch_playback", fake_launch)
    record = _watch(record=True, anonymize=anonymize, widescreen=widescreen, no_music=True)
    assert seen["enabled"] == ([_WS] if widescreen else []) + [_MUSIC_OFF]
    assert seen["disabled"] == ([_NAMES] if anonymize else [])
    # the failure still restores every override and the user's aspect
    assert record["status"] == "failed"
    assert "dolphin fell over" in record["error"]
    assert record["owned"] == {}
    assert not any((user / "GameSettings").iterdir())
    assert _aspect(str(gfx)) == "3"


def test_watch_without_options_changes_nothing(tmp_path, monkeypatch):
    user, gfx = _job_env(tmp_path, monkeypatch)
    seen = {}

    class _Done:
        def wait(self):
            return 0

    def fake_launch(dolphin, comm, iso, job=None):
        seen["ini"] = (user / "GameSettings" / "GALE01r2.ini").exists()
        seen["owned"] = dict(job.owned)
        return _Done()

    for _mod in (playback, watch_mods):
        monkeypatch.setattr(_mod, "_launch_playback", fake_launch)
    record = _watch()
    assert seen == {"ini": False, "owned": {}}
    assert record["status"] == "done"
    assert record["result"] == {"last_recording": None, "recordings": []}
    assert _aspect(str(gfx)) == "3"
    assert not (user / "Config" / "Dolphin.ini").exists()


def test_encoder_failure_reaches_job_and_restores_recording_settings(tmp_path, monkeypatch):
    user, gfx = _job_env(tmp_path, monkeypatch)
    gs = user / "GameSettings"
    gs.mkdir()
    (gs / "GALE01.ini").write_text("[Gecko_Enabled]\n$Mine\n", encoding="utf-8")

    class Done:
        def wait(self):
            return 0

    monkeypatch.setattr(watch_mods, "_launch_playback", lambda *args: Done())

    def fail_encode(*args, **kwargs):
        raise RuntimeError("Recording encoding failed: controlled failure")

    monkeypatch.setattr(watch_mods, "_collect_recording", fail_encode)
    record = _watch(record=True, no_music=True, widescreen=True, anonymize=True)
    assert record["status"] == "failed"
    assert "controlled failure" in record["error"]
    assert record["result"] is None
    assert _aspect(str(gfx)) == "3"
    ini = str(user / "Config" / "Dolphin.ini")
    assert dolphin_config._read_ini_key(ini, "Movie", "DumpFrames") == "False"
    assert dolphin_config._read_ini_key(ini, "DSP", "DumpAudio") == "False"
    assert sorted(p.name for p in gs.iterdir()) == ["GALE01.ini"]
    assert (gs / "GALE01.ini").read_text(encoding="utf-8") == "[Gecko_Enabled]\n$Mine\n"
