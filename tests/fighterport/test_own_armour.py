from echo_rivals2.gamedata import armour_windows
from fighter_port.own_route import armour_spans


def test_rivals_armor_reaches_all_played_actions_without_pair_unpacking():
    # Kragg's side-special source windows use positive dictionary armor.
    windows = [(1, dict(WindowLengthFrames=16, AdvancedProperties=dict(WindowArmor=255))),
               (17, dict(WindowLengthFrames=18, AdvancedProperties=dict(WindowArmor=-1))),
               (35, dict(WindowLengthFrames=10, AdvancedProperties=dict(WindowArmor=0)))]
    moves = {'game_specials': {'armour': armour_windows(windows)}}
    got = armour_spans({300:'specials',301:'specialairs'}, moves, lambda *_:'game_specials')
    assert got == [dict(actions=[300,301], first=1,last=16,source_armour=255,adaptation='native superarmor'),
                   dict(actions=[300,301], first=17,last=34,source_armour=255,adaptation='native superarmor')]


def test_legacy_exclusive_windows_and_inactive_source_values():
    moves = {'game_test': {'armour': [[3,9],dict(first=10,last=12,armour=0),
                                     dict(first=13,last=20,armour=-1)]}}
    assert armour_spans({4:'test',5:None}, moves, lambda *_:'game_test') == [
        dict(actions=[4],first=3,last=8)]
    assert armour_windows([(1,dict(WindowLengthFrames=10,AdvancedProperties=dict(WindowArmor=-1)))]) == []
