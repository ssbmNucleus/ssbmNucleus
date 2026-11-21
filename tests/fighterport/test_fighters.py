"""The one place a fighter is written into (`fighters.py`), and what is worked out when nothing is written.

The first tests need nothing but the code. The rest read the game's own skeletons where they are on the machine and
are skipped where they are not.
"""
import os
from pathlib import Path

import numpy as np
import pytest

from fighter_port import fighters, native_port
from fighter_port.compat.bone_lookup import SLOTS


# --------------------------------------------------------------------------------------------------- a made-up hand
def hand(digits, joints=2):
    """A wrist with digits fanned in its own x-y plane: {digit: degrees round from x}. -> (order, parent, world)"""
    order, parent, world = ['HandL'], {'HandL': None}, {'HandL': np.eye(4)}
    for d, angle in digits.items():
        a = np.radians(angle)
        for k in range(1, joints + 1):
            name = f'FingerL{d}{k}'
            order.append(name)
            parent[name] = 'HandL' if k == 1 else f'FingerL{d}{k - 1}'
            m = np.eye(4)
            m[:3, 3] = [k * np.cos(a), k * np.sin(a), 0.0]
            world[name] = m
    return order, parent, world


def test_the_thumb_is_the_digit_that_stands_off_the_rest_whatever_its_number():
    # four fingers side by side and one digit off to the side: that one, here numbered 5
    order, parent, world = hand({1: 0, 2: 12, 3: 24, 4: 36, 5: 90})
    which, apart = fighters.thumb(fighters.digits(order, parent, world, 'HandL'))
    assert which == 5 and apart == pytest.approx(54.0)
    # the same hand numbered the other way round: the measure follows the hand, not the number
    order, parent, world = hand({1: 90, 2: 36, 3: 24, 4: 12, 5: 0})
    assert fighters.thumb(fighters.digits(order, parent, world, 'HandL'))[0] == 1
    # digits all close together are a mitten: no thumb is guessed
    order, parent, world = hand({1: 0, 2: 8, 3: 16})
    assert fighters.thumb(fighters.digits(order, parent, world, 'HandL'))[0] is None
    assert fighters.thumb({}) == (None, None) and fighters.thumb({5: np.array([1.0, 0, 0])}) == (None, None)


def test_a_palm_bone_is_not_a_digit_and_a_digit_hung_from_one_still_counts():
    order, parent, world = hand({1: 0, 2: 12, 5: 80})
    order.insert(1, 'FingerL10')                        # the palm bone the digits hang from on some fighters
    parent['FingerL10'], world['FingerL10'] = 'HandL', np.eye(4)
    for d in (1, 2, 5):
        parent[f'FingerL{d}1'] = 'FingerL10'
    found = fighters.digits(order, parent, world, 'HandL')
    assert sorted(found) == [1, 2, 5] and fighters.thumb(found)[0] == 5
    # a finger of the other hand is not one of this hand's
    order.append('FingerR11')
    parent['FingerR11'], world['FingerR11'] = None, np.eye(4)
    assert sorted(fighters.digits(order, parent, world, 'HandL')) == [1, 2, 5]


def test_the_places_are_bound_by_the_games_own_bone_names():
    order, parent, world = hand({1: 0, 2: 12, 3: 24, 4: 36, 5: 90})
    order += ['Trans', 'Hip', 'Bust', 'Head', 'KneeL', 'HaveL', '__engine_Top']
    bound, notes = fighters.bindings_by_name(order, parent, world)
    assert set(bound) == set(SLOTS)
    assert bound['hip'] == 'Hip' and bound['headN'] == 'Head' and bound['lKnee'] == 'KneeL' and bound['top'] == '__engine_Top'
    assert bound['lThumb1'] == 'FingerL51' and bound['lThumb2'] == 'FingerL52'
    assert [bound[f'l{f}1'] for f in ('Index', 'Middle', 'Ring', 'Pinky')] == ['FingerL11', 'FingerL21', 'FingerL31', 'FingerL41']
    # what the fighter does not have stays empty, and what was decided is said
    assert bound['rKnee'] is None and bound['neckN'] is None and bound['rHave'] is None
    assert any('digit 5 is the thumb' in n for n in notes)
    # one hold bone, not a pair: Melee holds in the right hand
    order2 = [j for j in order if j != 'HaveL'] + ['Have']
    bound2, notes2 = fighters.bindings_by_name(order2, parent, world)
    assert bound2['rHave'] == 'Have' and bound2['lHave'] is None and any('one hold bone' in n for n in notes2)


def test_a_fighter_with_no_table_is_bound_by_name_and_an_entry_overrules_one_place(monkeypatch):
    order, parent, world = hand({1: 0, 5: 90})
    order += ['Hip', 'Head', 'Snout']
    bound, source, _notes = fighters.bindings('nobody', order, parent, world)
    assert source == 'by bone name' and bound['headN'] == 'Head'
    monkeypatch.setitem(fighters.FIGHTERS, 'nobody', dict(bindings={'headN': 'Snout'}))
    bound, source, _notes = fighters.bindings('nobody', order, parent, world)
    assert bound['headN'] == 'Snout' and 'overruled in fighters.py for headN' in source
    monkeypatch.setitem(fighters.FIGHTERS, 'nobody', dict(bindings={'tail': 'Snout'}))
    with pytest.raises(ValueError, match="places the engine does not have"):
        fighters.bindings('nobody', order, parent, world)
    # a fighter measured before this rule was written keeps its table as it is
    assert fighters.bindings('duckhunt', order, parent, world)[1].startswith('measured before')


def test_the_item_is_held_where_the_entry_says_else_at_the_right_hold_slot():
    assert fighters.item_hold('duckhunt', {'rHave': 'HaveR'}, {'Have', 'HaveR'}) == ('Have', 'fighters.py')
    assert fighters.item_hold('duckhunt', {'rHave': 'HaveR'}, {'HaveR'}) == (None, 'fighters.py')    # named, and not a bone
    assert fighters.item_hold('nobody', {'rHave': 'HaveR', 'lHave': 'HaveL'}, set()) == ('HaveR', 'the right hold slot')
    assert fighters.item_hold('nobody', {'rHave': None, 'lHave': 'HaveL'}, set()) == ('HaveL', 'the left hold slot')
    assert fighters.item_hold('nobody', {}, set()) == (None, None)


def test_every_stage_reads_its_per_fighter_table_from_the_one_place():
    from fighter_port import oneshot, own_data, own_faces, own_route, own_skeleton
    assert oneshot.TAUNT == fighters.column('taunt') and oneshot.TAUNT['duckhunt'] == 'appealsr'
    assert own_route.SHOTS == fighters.column('code_timed_hits') and own_route.SHOT_EFFECTS == fighters.column('code_timed_effects')
    assert own_faces.CODE_SHOWN == fighters.column('code_shown') and own_skeleton.ARTICLE_PARTS == fighters.column('article_parts')
    assert own_data.FIGHTER == {n: {'item_hold': j} for n, j in fighters.column('item_hold').items()}
    assert own_data.FIGHTER['duckhunt'] == {'item_hold': 'Have'}
    # nothing is written for a fighter that is not there, and every value an entry has is one a stage reads
    assert fighters.get('nobody', 'taunt') is None and fighters.get('nobody', 'taunt', 'x') == 'x'
    for name, entry in fighters.FIGHTERS.items():
        assert set(entry) <= set(fighters.VALUES), name


def test_a_fighters_specials_are_found_by_the_name_of_its_module():
    from fighter_port import own, own_template
    assert fighters.specials('template') is own_template
    assert fighters.specials('nobody') is None and fighters.specials_name('falco') == 'own_falco'
    # the route's own modules of the same spelling are not fighters (own_data and own_bank have a `build` of their own)
    for not_a_fighter in ('data', 'bank', 'route', 'skeleton', 'faces', 'effects'):
        assert fighters.specials(not_a_fighter) is None, not_a_fighter
    # ... and the tables the driver reads answer for any fighter that has a module, with nothing registered
    assert 'template' in own.BUILD and 'cloud' in own.BUILD and 'nobody' not in own.BUILD and 'wolf' not in own.BUILD
    assert own.OWN_CLIPS['template'] == own_template.CLIPS and own.OWN_CLIPS.get('nobody', {}) == {}
    assert own.SPECIAL_HITS.get('template') == tuple(own_template.HIT_ACTIONS)
    assert own.code_sounds('template') == [] and own.names('nobody') == []
    assert own.code_effects('template') == {}
    assert own.build('nobody', {}) == (None, None)


def test_the_donor_is_not_a_choice_yet_and_the_refusal_says_what_a_second_one_takes():
    assert fighters.donors() == ['Marth'] and fighters.donor_problem('Marth') is None
    why = fighters.donor_problem('Fox')
    assert "'Fox'" in why and 'own_data.DONOR' in why and 'own_skeleton.DONOR' in why and '--donor Marth' in why


def test_every_per_fighter_table_of_the_donor_route_is_listed():
    """The tables a fighter on the DONOR's skeleton is written into stay beside the code that reads them; the list of
    them is what preflight prints on that route, so a table added to the driver and not to the list fails here."""
    import re
    from fighter_port import oneshot, own
    listed = {(module, name) for module, name, _what in fighters.ON_THE_DONOR}
    known = set(own.BUILD) | set(fighters.FIGHTERS) | {'shulk'}                 # the fighters ported so far
    found = set()
    for module in (oneshot, own):
        text = Path(module.__file__).read_text('utf-8')
        for name in re.findall(r'^([A-Z][A-Z_]+) = ', text, re.M):
            table = getattr(module, name, None)
            keys = set(table) if isinstance(table, (dict, set, frozenset)) else set()
            if keys and all(isinstance(k, str) for k in keys) and keys <= known:
                found.add((module.__name__.rsplit('.', 1)[1], name))
    # (the ones gathered in fighters.py are read from it and are not this route's alone)
    gathered = {('oneshot', 'TAUNT')}
    assert found - gathered <= listed, sorted(found - gathered - listed)
    assert [name for _m, name, _w in fighters.written_on_the_donor('ike')] == ['CHARGE_GAME', 'COUNTER_GAME', 'CLIPS', 'BUILD']
    assert ('own', 'CHAIN_NEEDS_HIT') in [(m, n) for m, n, _w in fighters.written_on_the_donor('cloud')]
    assert fighters.written_on_the_donor('nobody') == []


# ---------------------------------------------------------------------------------------- the game's own skeletons
ROOT = Path(os.environ.get('ULTIMATE_DUMP') or Path.home() / 'shulk-calibration-20260904')
# what the cold trial bound for Wolf by hand, measuring his digits: the rule must give it with nothing written
WOLF = dict(native_port._EMPTY, **native_port._ROOTS, **{
    'bust': 'Bust', 'neckN': 'Neck', 'headN': 'Head', 'throw': 'Throw',
    'lLeg': 'LegL', 'lKnee': 'KneeL', 'lFoot': 'FootL', 'rLeg': 'LegR', 'rKnee': 'KneeR', 'rFoot': 'FootR',
    'lClavicle': 'ClavicleL', 'lShoulder': 'ShoulderL', 'lArm': 'ArmL', 'lHand': 'HandL',
    'rClavicle': 'ClavicleR', 'rShoulder': 'ShoulderR', 'rArm': 'ArmR', 'rHand': 'HandR',
    'lIndex1': 'FingerL11', 'lIndex2': 'FingerL12', 'lMiddle1': 'FingerL21', 'lMiddle2': 'FingerL22',
    'lRing1': 'FingerL31', 'lRing2': 'FingerL32', 'lPinky1': 'FingerL41', 'lPinky2': 'FingerL42',
    'lThumb1': 'FingerL51', 'lThumb2': 'FingerL52', 'lHave': 'HaveL',
    'rIndex1': 'FingerR11', 'rIndex2': 'FingerR12', 'rMiddle1': 'FingerR21', 'rMiddle2': 'FingerR22',
    'rRing1': 'FingerR31', 'rRing2': 'FingerR32', 'rPinky1': 'FingerR41', 'rPinky2': 'FingerR42',
    'rThumb1': 'FingerR51', 'rThumb2': 'FingerR52', 'rHave': 'HaveR'})


def game_rig(folder):
    ssbh = pytest.importorskip('ssbh_data_py')
    from fighter_port.ultimate import skeleton_metadata
    path = ROOT / 'gamedata' / 'fighter' / folder / 'model' / 'body' / 'c00' / 'model.nusktb'
    if not path.exists():
        pytest.skip(f"the game's skeleton of {folder} is not on this machine")
    rig = native_port.rig_from_meta(skeleton_metadata(ssbh.skel_data.read_skel(str(path))))
    # (the rig a port is built on adds the engine's own joints to the game's)
    return list(rig.order) + ['__engine_Top', '__engine_XRot', '__engine_YRot', native_port.EXTRA_MOTION], rig


@pytest.mark.parametrize('fighter, folder, expect', [
    ('wolf', 'wolf', WOLF),                                         # written by hand in the cold trial
    ('duckhunt', 'duckhunt', native_port.BINDINGS['duckhunt']),     # a dog: no fingers
    ('charizard', 'plizardon', native_port.BINDINGS['charizard']),  # three digits, the thumb numbered 5
    ('squirtle', 'pzenigame', native_port.BINDINGS['squirtle']),    # three digits, the thumb numbered 1
    ('ivysaur', 'pfushigisou', native_port.BINDINGS['ivysaur']),    # one digit a hand, one hold bone
])
def test_the_rule_gives_every_table_that_was_measured_by_hand(fighter, folder, expect):
    order, rig = game_rig(folder)
    bound, notes = fighters.bindings_by_name(order, rig.parent, rig.world)
    assert bound == expect, {k: (expect[k], bound[k]) for k in expect if expect[k] != bound[k]}


def test_wolf_needs_no_table_of_his_own():
    order, rig = game_rig('wolf')
    assert 'wolf' not in native_port.BINDINGS and 'wolf' not in native_port.SPECIES
    bound, source, notes = fighters.bindings('wolf', order, rig.parent, rig.world)
    assert bound == WOLF and source == 'by bone name' and not [s for s in fighters.NEEDED if not bound[s]]
    assert any('HandL' in n and 'digit 5 is the thumb' in n for n in notes)


def test_item_hold_falls_back_to_semantic_hand_without_overriding_real_hold_slots(monkeypatch):
    assert fighters.item_hold('nobody', {'rHand':'HandR'}, {'HandR'}) == ('HandR','right-hand fallback (no hold bone)')
    assert fighters.item_hold('nobody', {'lHand':'HandL'}, {'HandL'}) == ('HandL','left-hand fallback (no hold bone)')
    assert fighters.item_hold('nobody', {'rHand':'missing'}, {'HandL'}) == (None,None)
    assert fighters.item_hold('nobody', {'lHave':'HaveL','rHand':'HandR'}, {'HaveL','HandR'}) == ('HaveL','the left hold slot')
    monkeypatch.setitem(fighters.FIGHTERS,'testhand',dict(item_hold='Beak'))
    assert fighters.item_hold('testhand', {'rHand':'HandR'}, {'HandR'}) == (None,'fighters.py')
