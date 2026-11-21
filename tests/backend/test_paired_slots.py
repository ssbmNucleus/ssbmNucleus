"""Zelda and Sheik share costume slots: growing one side pads the other."""
from tests.paths import BACKEND
import sys
from pathlib import Path

TOOLS = BACKEND
sys.path.insert(0, str(TOOLS))

import mexcli.project  # noqa: E402


class _Fake(mexcli.project.MexManager):
    def __init__(self, counts):
        self.project_path = Path('project.mexproj')
        self.counts = dict(counts)
        self.calls = []

    def _run_command(self, *args):
        self.calls.append(args)
        if args[0] == 'list-fighters':
            return {'fighters': [{'name': n, 'costumeCount': c} for n, c in self.counts.items()]}
        if args[0] == 'import-costume':
            self.counts[args[2]] = self.counts.get(args[2], 0) + 1
            return {'success': True}
        return {}


def _vanilla(monkeypatch, tmp_path):
    dat = tmp_path / 'PlSkNr.dat'
    dat.write_bytes(b'dat')
    import shared.vanilla_extract.vanilla_refs as refs
    monkeypatch.setattr(refs, 'ensure_vanilla_ref', lambda name: dat)


def test_a_new_zelda_slot_gets_a_matching_sheik(monkeypatch, tmp_path):
    _vanilla(monkeypatch, tmp_path)
    zip_path = tmp_path / 'costume.zip'
    zip_path.write_bytes(b'zip')
    mex = _Fake({'Zelda': 5, 'Sheik': 5})
    result = mex.import_costume('Zelda', zip_path)
    assert mex.counts == {'Zelda': 6, 'Sheik': 6}
    assert result['pairedSlotsPadded'] == [{'fighter': 'Sheik', 'costume': 'PlSkNr.dat', 'pairs_with': 'Zelda'}]


def test_other_fighters_are_left_alone(monkeypatch, tmp_path):
    _vanilla(monkeypatch, tmp_path)
    mex = _Fake({'Fox': 4, 'Zelda': 5, 'Sheik': 5})
    assert mex.pad_paired_slots(['Fox']) == []
    assert not any(c[0] == 'list-fighters' for c in mex.calls)


def test_already_matching_slots_are_not_padded(monkeypatch, tmp_path):
    _vanilla(monkeypatch, tmp_path)
    mex = _Fake({'Zelda': 6, 'Sheik': 6})
    assert mex.pad_paired_slots(['Zelda', 'Sheik']) == []
