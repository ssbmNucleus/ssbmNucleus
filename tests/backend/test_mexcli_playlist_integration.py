"""
Integration tests for the REAL MexCLI playlist commands.

These exist because of a released bug the mocked-seam tests in
test_music_playlists.py could not see: MexPlaylistEntry.MusicID (C#)
silently ignores negative writes, so add-playlist-music's musicId:-1
placeholder was never replaced -- it read back as 0 and every uploaded
menu/stage song published as vanilla track 0, "All-Star Rest Area".
The Python-side mock implemented the *intended* placeholder contract,
so the suite stayed green while the shipped binary was wrong.

Runs mexcli.exe (dev Release build, same path core.config uses) against
a minimal copy of storage/test-base: project.mexproj + data/ + assets/
+ sys/ + the files/ subset workspace open/save actually reads (sound
banks, trophy/menu dats, banner, PlCo). ~50 MB per test copy instead of
the full 1.4 GB extracted ISO.

Skipped when the mexcli build or storage/test-base is missing.
"""
from tests.paths import BACKEND
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = BACKEND
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

NUCLEUS_DIR = BACKEND_DIR.parent
# core.config, not a hardcoded net6.0/mexcli.exe: on Linux the dev build lands
# in linux-x64/mexcli, and hardcoding the Windows path silently skipped this
# whole module there -- the exact "green suite, untested binary" hole the
# module was written to close.
from core.config import MEXCLI_PATH as MEXCLI  # noqa: E402
TEST_BASE = NUCLEUS_DIR / "storage" / "test-base"

pytestmark = [pytest.mark.skipif(
    not MEXCLI.exists() or not (TEST_BASE / "project.mexproj").exists(),
    reason="mexcli Release build or storage/test-base not present"), pytest.mark.slow]

# Everything MexWorkspace open + Save touches beyond the JSON workspace:
# sound banks (SmSt/sem/ssm), trophies (TyData*/SdToy*), banner, and the
# PlCo compile step. Discovered empirically by running add-playlist-music
# against a growing subset until it succeeded.
FILES_SUBSET = [
    "PlCo.dat", "SmSt.dat", "MxDt.dat",
    "TyDataf.dat", "TyDatai.usd", "SdToy.usd", "SdToyExp.usd",
    "MnSlChr.usd", "MnSlMap.usd", "opening.bnr",
]


def _run(args, stdin_json=None):
    """Run mexcli and return the trailing JSON object from stdout
    (mirrors mexcli.commands.parse_json)."""
    result = subprocess.run(
        [str(MEXCLI), *args],
        input=json.dumps(stdin_json) if stdin_json is not None else None,
        capture_output=True, text=True, timeout=300)
    s = (result.stdout or '').strip()
    idx = s.rfind('\n{')
    candidate = s[idx + 1:] if idx != -1 else (s if s.startswith('{') else None)
    assert candidate is not None, f"no JSON in mexcli output: {s[-400:]}"
    out = json.loads(candidate)
    out['_returncode'] = result.returncode
    return out


@pytest.fixture
def workspace(tmp_path):
    """A fresh minimal copy of the test-base workspace."""
    ws = tmp_path / "ws"
    (ws / "files" / "audio").mkdir(parents=True)
    shutil.copy2(TEST_BASE / "project.mexproj", ws / "project.mexproj")
    for tree in ("data", "assets", "sys"):
        shutil.copytree(TEST_BASE / tree, ws / tree)
    for name in FILES_SUBSET:
        shutil.copy2(TEST_BASE / "files" / name, ws / "files" / name)
    shutil.copytree(TEST_BASE / "files" / "audio" / "us",
                    ws / "files" / "audio" / "us")
    return ws


@pytest.fixture
def upload_hps(tmp_path):
    """A real HPS to add, from outside the workspace (like an upload)."""
    src = min((TEST_BASE / "files" / "audio").glob("*.hps"),
              key=lambda p: p.stat().st_size)
    dst = tmp_path / "uploaded_song.hps"
    shutil.copy2(src, dst)
    return dst


def _project(ws):
    return json.loads((ws / "project.mexproj").read_text(encoding="utf-8"))


def _music(ws):
    return json.loads((ws / "data" / "music.json").read_text(encoding="utf-8"))


def _menu_entries(ws):
    return _project(ws)["menuPlaylist"]["entries"]


def test_add_menu_track_publishes_the_added_track(workspace, upload_hps):
    """The exact gahtto repro: the published playlist must reference the
    NEW track, not silently degrade the -1 placeholder to music id 0
    (All-Star Rest Area)."""
    before = _menu_entries(workspace)
    new_id_expected = len(_music(workspace))
    entries = ([{"musicId": e["musicID"], "chance": 20} for e in before]
               + [{"musicId": -1, "chance": 60}])

    out = _run(["add-playlist-music", str(workspace / "project.mexproj"),
                str(upload_hps), "Uploaded Menu Song", "menu"],
               stdin_json=entries)

    assert out.get("success"), out
    assert out["musicId"] == new_id_expected
    assert out["existed"] is False
    # the CLI's reported playlist contains the new track...
    assert [e["musicId"] for e in out["entries"]].count(new_id_expected) == 1
    assert 0 not in [e["musicId"] for e in out["entries"]]
    # ...and so does the saved workspace
    saved = _menu_entries(workspace)
    assert [e["musicID"] for e in saved] == [e["musicId"] for e in entries[:-1]] + [new_id_expected]
    # the music pool grew by one and the HPS landed in files/audio
    music = _music(workspace)
    assert len(music) == new_id_expected + 1
    assert music[new_id_expected]["name"] == "Uploaded Menu Song"
    assert (workspace / "files" / "audio" / music[new_id_expected]["fileName"]).is_file()


def test_add_stage_track_publishes_the_added_track(workspace, upload_hps):
    """Same placeholder contract for the stage target."""
    new_id_expected = len(_music(workspace))

    out = _run(["add-playlist-music", str(workspace / "project.mexproj"),
                str(upload_hps), "Uploaded Stage Song", "stage", "Battlefield"],
               stdin_json=[{"musicId": -1, "chance": 100}])

    assert out.get("success"), out
    assert out["musicId"] == new_id_expected
    assert out["stage"] == "Battlefield"
    assert [e["musicId"] for e in out["entries"]] == [new_id_expected]

    # find Battlefield's saved stage json (LAST name match, like the CLI)
    stages_dir = workspace / "data" / "stages"
    found = None
    for rel in _project(workspace)["stageSaveMap"]["filePaths"]:
        data = json.loads((stages_dir / rel).read_text(encoding="utf-8"))
        if (data.get("name") or "").strip().lower() == "battlefield":
            found = data
    assert found is not None
    assert [e["musicID"] for e in found["playlist"]["entries"]] == [new_id_expected]


def test_add_playlist_music_requires_exactly_one_placeholder(workspace, upload_hps):
    before_project = (workspace / "project.mexproj").read_bytes()
    out = _run(["add-playlist-music", str(workspace / "project.mexproj"),
                str(upload_hps), "No Placeholder", "menu"],
               stdin_json=[{"musicId": 52, "chance": 100}])
    assert not out.get("success")
    assert "placeholder" in out.get("error", "").lower()
    assert (workspace / "project.mexproj").read_bytes() == before_project


def test_set_menu_playlist_rejects_negative_music_id(workspace):
    """A negative id must fail loudly -- before the fix it silently became
    track 0 (the MusicID setter ignores negative writes) and PASSED the
    range check, publishing All-Star Rest Area."""
    before_project = (workspace / "project.mexproj").read_bytes()
    out = _run(["set-menu-playlist", str(workspace / "project.mexproj")],
               stdin_json=[{"musicId": -1, "chance": 100}])
    assert not out.get("success")
    assert ">= 0" in out.get("error", "")
    assert (workspace / "project.mexproj").read_bytes() == before_project


def test_set_stage_playlist_rejects_negative_music_id(workspace):
    before_project = (workspace / "project.mexproj").read_bytes()
    out = _run(["set-stage-playlist", str(workspace / "project.mexproj"),
                "Battlefield"],
               stdin_json=[{"musicId": -1, "chance": 100}])
    assert not out.get("success")
    assert ">= 0" in out.get("error", "")
    assert (workspace / "project.mexproj").read_bytes() == before_project
