"""fighter_port.code: the C source of a port's code file (compiling it needs MexTK, so only the text is checked here)."""
import importlib.util
import struct
from pathlib import Path

from fighter_port import code
from vault.echo.subactions import Dat

_spec = importlib.util.spec_from_file_location('weapon_files', Path(__file__).with_name('test_oneshot_weapons.py'))
files = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(files)

TRAIL = struct.pack('>ffBB4B4BBBiff', 0.2, 1.0, 255, 0, 0, 255, 255, 0, 255, 255, 255, 0, 0, 0, 75, 1.75, 9.63)


def test_the_donors_trail_is_read_from_its_special_attributes():
    attrs = bytearray(0x78) + TRAIL
    pl = files.dat([(bytearray(struct.pack('>II', 0, 1)), [4]), (attrs, [])], [(0, 'ftDataMars')])
    t = code.donor_trail(pl, 'Marth', Dat)
    assert (t['bone'], round(t['bottom'], 2), round(t['top'], 2)) == (75, 1.75, 9.63)
    assert t['in_col'] == [0, 255, 255, 0] and t['out_col'] == [255, 255, 255, 0] and t['start_alpha'] == 255
    assert code.donor_trail(pl, 'Mario', Dat) is None                 # a donor with no trail


def test_a_port_points_at_the_donors_trail_unless_given_its_own():
    text, provides = code.source('Marth')
    assert provides == ['sword trail data'] and 'special_attributes + 0x78' in text['fighter.c']
    own = dict(x0=0.2, x4=1.0, start_alpha=255, end_alpha=0, in_col=[252, 136, 98, 0], out_col=[255, 255, 255, 0],
               x12=0, x13=0, bone=75, bottom=0.877, top=15.35)
    text, provides = code.source('Marth', own)
    c = text['fighter.c']
    assert provides == ["the fighter's own sword trail"]
    assert '.in_col = {252, 136, 98, 0}' in c and '.bone_index = 75' in c and '.offset_top = 15.350' in c
    assert 'AfterImageDesc *GetTrailData(GOBJ *fighter)' in c and 'special_attributes' not in c
    assert code.source('Mario') == ({}, [])                           # nothing to provide: no code file


def test_no_toolkit_means_none(tmp_path, monkeypatch):
    monkeypatch.delenv('MEXTK_DIR', raising=False)
    assert code.toolkit(None) is None and code.toolkit(tmp_path) is None
    (tmp_path / 'MexTK.exe').write_bytes(b'')
    (tmp_path / 'mex.h').write_text('')
    assert code.toolkit(tmp_path) == tmp_path
