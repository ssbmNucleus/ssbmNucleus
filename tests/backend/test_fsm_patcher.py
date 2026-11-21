from tests.paths import BACKEND
import json
import struct
import sys
from pathlib import Path

import pytest

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

from projects.install import fsm_patcher as fsm


GODMEWTWO_FSM = """\
10,0,128,11,2.0
10,0,128,18,2.0
10,9,128,41,3.0
10,25,129,49,0.4
10,0,129,49,0.8
"""


def _make_fake_dol(tmp_path):
    """A minimal file large enough to hold all patch regions, with the
    vanilla hook instruction and recognizable filler in the engine region."""
    size = fsm.TABLE_FILE_OFFSET + fsm.TABLE_REGION_SIZE + 0x1000
    data = bytearray(b"\xAA" * size)
    data[fsm.HOOK_FILE_OFFSET:fsm.HOOK_FILE_OFFSET + 4] = fsm.HOOK_VANILLA
    region = fsm.ENGINE_REGION_SIZE + fsm.TABLE_REGION_SIZE
    data[fsm.ENGINE_FILE_OFFSET:fsm.ENGINE_FILE_OFFSET + region] = b"\xBB" * region
    dol = tmp_path / "main.dol"
    dol.write_bytes(bytes(data))
    return dol


def test_parse_fsm_txt():
    entries = fsm.parse_fsm_txt(GODMEWTWO_FSM)
    assert len(entries) == 5
    assert entries[0] == (10, 0, 128, 11, 2.0)
    assert entries[3] == (10, 25, 129, 49, 0.4)


def test_parse_rejects_garbage():
    with pytest.raises(fsm.FsmError):
        fsm.parse_fsm_txt("10,0,128,11")
    with pytest.raises(fsm.FsmError):
        fsm.parse_fsm_txt("10,0,999,11,2.0")


def test_build_table_layout():
    entries = fsm.parse_fsm_txt("10,0,128,11,2.0")
    table = fsm.build_table(entries)
    assert len(table) == fsm.TABLE_REGION_SIZE
    assert table[:4] == bytes([10, 0, 128, 11])
    assert struct.unpack(">f", table[4:8])[0] == 2.0
    assert table[8:16] == b"\x00" * 8  # terminator


def test_build_table_cap():
    entries = [(0x1A, 0, 128, 11, 2.0)] * (fsm.MAX_ENTRIES + 1)
    with pytest.raises(fsm.FsmError):
        fsm.build_table(entries)


def test_retarget_entries():
    entries = fsm.parse_fsm_txt(GODMEWTWO_FSM)
    out = fsm.retarget_entries(entries, 0x1A)
    assert all(e[0] == 0x1A for e in out)
    assert [e[1:] for e in out] == [e[1:] for e in entries]


def test_apply_and_remove_roundtrip(tmp_path):
    dol = _make_fake_dol(tmp_path)
    original = dol.read_bytes()
    entries = fsm.retarget_entries(fsm.parse_fsm_txt(GODMEWTWO_FSM), 0x1A)

    fsm.apply_fsm_patch(dol, entries)
    assert fsm.get_patch_state(dol) == "patched"
    data = dol.read_bytes()
    assert data[fsm.ENGINE_FILE_OFFSET:fsm.ENGINE_FILE_OFFSET + len(fsm.ENGINE_CODE)] == fsm.ENGINE_CODE
    assert data[fsm.TABLE_FILE_OFFSET] == 0x1A
    assert data[fsm.HOOK_FILE_OFFSET:fsm.HOOK_FILE_OFFSET + 4] == fsm.HOOK_PATCHED

    # idempotent re-apply with different entries
    fsm.apply_fsm_patch(dol, fsm.retarget_entries(entries, 0x1B))
    data = dol.read_bytes()
    assert data[fsm.TABLE_FILE_OFFSET] == 0x1B

    # revert restores byte-identical dol
    assert fsm.remove_fsm_patch(dol) is True
    assert dol.read_bytes() == original
    assert fsm.get_patch_state(dol) == "vanilla"
    assert fsm.remove_fsm_patch(dol) is False


def test_apply_refuses_unknown_dol(tmp_path):
    dol = _make_fake_dol(tmp_path)
    with open(dol, "r+b") as f:
        f.seek(fsm.HOOK_FILE_OFFSET)
        f.write(b"\xDE\xAD\xBE\xEF")
    with pytest.raises(fsm.FsmError):
        fsm.apply_fsm_patch(dol, [(0x1A, 0, 128, 11, 2.0)])


def test_external_id_mapping():
    # vanilla roster (33 fighters): Mewtwo internal 16 -> external 0x0A
    assert fsm.to_external_id(16, 33) == 0x0A
    # one added fighter: internal 27 -> external 0x1A, specials shift up
    assert fsm.to_external_id(27, 34) == 0x1A
    # two added fighters
    assert fsm.to_external_id(27, 35) == 0x1A
    assert fsm.to_external_id(28, 35) == 0x1B
    # vanilla ids unchanged with added fighters present
    assert fsm.to_external_id(16, 35) == 0x0A
    assert fsm.to_external_id(0, 35) == 0x08  # Mario
    # Popo special case
    assert fsm.to_external_id(11, 33) == 32


def _make_fake_project(tmp_path, fighter_names):
    proj_dir = tmp_path / "proj"
    (proj_dir / "data" / "fighters").mkdir(parents=True)
    (proj_dir / "sys").mkdir()
    file_paths = []
    for i, name in enumerate(fighter_names):
        fname = f"{i:03d}.json"
        (proj_dir / "data" / "fighters" / fname).write_text(json.dumps({"name": name}))
        file_paths.append(fname)
    proj_file = proj_dir / "project.mexproj"
    proj_file.write_text(json.dumps({"fighterSaveMap": {"filePaths": file_paths}}))
    return proj_file


VANILLA_INTERNAL_ORDER = [
    "Mario", "Fox", "C. Falcon", "DK", "Kirby", "Bowser", "Link",
    "Sheik", "Ness", "Peach", "Popo", "Nana", "Pikachu", "Samus",
    "Yoshi", "Jigglypuff", "Mewtwo", "Luigi", "Marth", "Zelda",
    "Young Link", "Dr. Mario", "Falco", "Pichu", "Mr. Game & Watch",
    "Ganondorf", "Roy",
]
SPECIALS = ["Master Hand", "Crazy Hand", "Wireframe Male", "Wireframe Female",
            "Giga Bowser", "Sandbag"]


def test_collect_fsm_entries(tmp_path):
    # roster with Deoxys inserted before the 6 specials (internal 27)
    names = VANILLA_INTERNAL_ORDER + ["Deoxys"] + SPECIALS
    proj_file = _make_fake_project(tmp_path, names)

    vault = tmp_path / "custom_characters"
    deoxys = vault / "deoxys"
    deoxys.mkdir(parents=True)
    (deoxys / "fighter.json").write_text(json.dumps({"name": "Deoxys"}))
    (deoxys / "fsm.txt").write_text(GODMEWTWO_FSM)
    # a vault char without fsm.txt is ignored
    other = vault / "toad"
    other.mkdir()
    (other / "fighter.json").write_text(json.dumps({"name": "Toad"}))

    entries = fsm.collect_fsm_entries(proj_file, vault)
    assert len(entries) == 5
    assert all(e[0] == 0x1A for e in entries)


def test_collect_no_fsm_chars(tmp_path):
    proj_file = _make_fake_project(tmp_path, VANILLA_INTERNAL_ORDER + SPECIALS)
    vault = tmp_path / "custom_characters"
    vault.mkdir()
    assert fsm.collect_fsm_entries(proj_file, vault) == []


def test_apply_project_fsm(tmp_path):
    names = VANILLA_INTERNAL_ORDER + ["Deoxys"] + SPECIALS
    proj_file = _make_fake_project(tmp_path, names)
    dol = _make_fake_dol(tmp_path)
    import shutil
    shutil.move(str(dol), str(proj_file.parent / "sys" / "main.dol"))

    vault = tmp_path / "custom_characters"
    deoxys = vault / "deoxys"
    deoxys.mkdir(parents=True)
    (deoxys / "fighter.json").write_text(json.dumps({"name": "Deoxys"}))
    (deoxys / "fsm.txt").write_text(GODMEWTWO_FSM)

    count = fsm.apply_project_fsm(proj_file, vault)
    assert count == 5
    assert fsm.get_patch_state(proj_file.parent / "sys" / "main.dol") == "patched"

    # uninstall: removing fsm.txt reverts the dol on next build
    (deoxys / "fsm.txt").unlink()
    count = fsm.apply_project_fsm(proj_file, vault)
    assert count == 0
    assert fsm.get_patch_state(proj_file.parent / "sys" / "main.dol") == "vanilla"
