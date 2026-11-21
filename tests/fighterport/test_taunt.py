"""Melee has one taunt and the source game three: which one a fighter gets, and that it is heard."""
import importlib.util
from pathlib import Path

from fighter_port import oneshot, voice

_spec = importlib.util.spec_from_file_location('port_finish_helpers', Path(__file__).with_name('test_port_finish.py'))
helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(helpers)


def test_a_fighter_known_for_another_taunt_gets_that_clip():
    table = {'j01appeallwr': [{'target_motion': 'Appeal', 'category': 'normal', 'body_scale': 'rigid'}],
             'a00wait1': [{'target_motion': 'Wait1', 'category': 'normal'}]}
    stems = ['a00wait1', 'j01appealhir', 'j01appeallwr', 'j01appealsr']
    got = oneshot.taunt_row({k: list(v) for k, v in table.items()}, 'duckhunt', stems)
    assert 'j01appeallwr' not in got and got['j01appealsr'] == table['j01appeallwr'] and got['a00wait1'] == table['a00wait1']
    # a fighter with no word on it keeps the table's; so does one whose named clip is not among its clips
    assert oneshot.taunt_row({k: list(v) for k, v in table.items()}, 'cloud', stems) == table
    assert oneshot.taunt_row({k: list(v) for k, v in table.items()}, 'duckhunt', stems[:3]) == table
    # a table with no taunt at all still gets one
    assert oneshot.taunt_row({}, 'duckhunt', stems)['j01appealsr'][0]['target_motion'] == 'Appeal'


def test_the_taunts_sounds_take_the_voice_slots_nothing_plays_any_more(tmp_path):
    one = helpers.idsp([helpers.adpcm([1] * 14)], count=14)
    for rel, entries in (('fighter/se_test', {'se_test_appeal_s01': one, 'se_test_appeal_s02': one}),
                         ('fighter_voice/vc_test', {'vc_test_attack01': one}),
                         ('fighter_voice/vc_test_cheer', {'vc_test_cheer': one})):
        path = tmp_path / 'gamedata' / 'sound' / 'bank' / (rel + '.nus3audio')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(helpers.bank(entries))
    samples = ['v_mars_atk1', 'v_mars_miteite', 'v_mars_count1', 'v_mars_jump']
    taunt = {'game_appealsr': {'sounds': [{'cmd': 'PLAY_SE', 'name': 'se_test_appeal_s01'},
                                          {'cmd': 'PLAY_SE', 'name': 'se_test_appeal_s02'}], 'port_plays': True}}
    chosen, left = voice.choose('Marth', 'test', tmp_path, samples, taunt, route='own skeleton')
    names = {k: v[0] for k, v in chosen.items()}
    # the donor's taunt line and a special's line are played by nothing on this route: they hold the taunt's sounds
    assert {names['v_mars_miteite'], names['v_mars_count1']} == {'se_test_appeal_s01', 'se_test_appeal_s02'}
    # a line the engine still plays on its own occasion (a jump) is silent, never room
    assert names['v_mars_jump'] == voice.SILENCE
    # on a route that keeps the donor's scripts, both stay silent (the taunt's sounds can only be samples the bank gains)
    chosen, left = voice.choose('Marth', 'test', tmp_path, samples, taunt)
    assert {chosen[k][0] for k in ('v_mars_miteite', 'v_mars_count1', 'v_mars_jump')} == {voice.SILENCE}
    # a script the port does not write does not ask for places
    chosen, left = voice.choose('Marth', 'test', tmp_path, samples,
                                {'game_appealsr': dict(taunt['game_appealsr'], port_plays=False)}, route='own skeleton')
    assert not any(v[0].startswith('se_test_appeal') for v in chosen.values())
