"""Source silence must never hide a failed sound export."""
import json
from types import SimpleNamespace

import pytest

from echo_rivals2 import sounds
from fighter_port import verify


@pytest.mark.parametrize('missing_table,event_present,absent', [
    (False, False, True), (True, False, False), (False, True, False)])
def test_absent_reference_requires_both_tables_and_no_source_entry(tmp_path, monkeypatch,
                                                                  missing_table, event_present, absent):
    class Pak:
        def find(self, name, under):
            if missing_table and name == 'SFX_Universal':
                raise KeyError(name)
            return name

        def props(self, name):
            rows = ([dict(Key='Charge VO', Value=dict(bIsVoiceLine=True,
                     SoundEffect=dict(AssetPathName='/Game/FMOD/Events/charge.charge')))]
                    if event_present and name != 'SFX_Universal' else [])
            return [dict(Properties=dict(SoundEffectData=rows))]

        def run(self, *args):
            raise AssertionError('events replaced below')

    monkeypatch.setattr(sounds, 'events', lambda *a: {})
    receipt = sounds.write(tmp_path, 'fixture', 'Fixture', tmp_path, {'vc_fixture_charge_vo'}, pak=Pak(), log=lambda _: None)
    assert bool(receipt['references']) == absent
    assert 'vc_fixture_charge_vo' in receipt['silent']
    assert json.loads((tmp_path/'gamedata/fighter/fixture/sound/extraction.json').read_text()) == receipt
    data = dict(moves={'game_specialn': dict(sounds=[dict(name='vc_fixture_charge_vo')])})
    sounds.annotate(data, receipt)
    assert ('source_sound' in data['moves']['game_specialn']['sounds'][0]) == absent
    sounds.annotate(data, {})  # later source versions can supply the entry
    assert 'source_sound' not in data['moves']['game_specialn']['sounds'][0]


@pytest.mark.parametrize('exists,reason,verdict', [(False, 'no source entry', 'say'),
                                                (True, 'sample extraction failed', 'FAULT'),
                                                (False, '', 'FAULT')])
def test_verifier_distinguishes_an_absent_source_entry_from_export_failure(exists, reason, verdict):
    source = dict(bank='rivals2_sound_tables', exists=exists, reason=reason)
    event = dict(cmd='PLAY_SE', name='vc_fixture_charge_vo', real=15, source_sound=source)
    work = SimpleNamespace(game=dict(game='rivals2', fighter='fixture', moves={'game_specialn':dict(sounds=[event])}),
                           report=dict(own_sounds=[], donor='Marth', route='own skeleton'),
                           sound=dict(swapped=[], added=[], bank_bytes=1, left=[]))
    actual, why = verify.sounds_two_lists(work)
    assert actual == verdict, why
    if verdict == 'say':
        assert 'Source references without a playable sound entry' in why and reason in why
