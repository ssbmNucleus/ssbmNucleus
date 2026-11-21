"""L-load: groups by name, tucked icons, the generated code, the export step.

The mechanism and its in-game proof are in docs/dev/L_LOAD.md; these are the
fast synthetic checks of the pieces Nucleus owns.
"""
import json

import pytest

from core.gecko import parse_ini, serialize_ini
from projects.lload import code, export as lload_export, groups, layout
from projects.lload.code_words import BODY, PREFIX

VANILLA = ['Mario', 'Fox', 'C. Falcon', 'DK', 'Kirby', 'Bowser', 'Link', 'Sheik', 'Ness',
           'Peach', 'Ice Climbers', 'Popo', 'Pikachu', 'Samus', 'Yoshi', 'Jigglypuff',
           'Mewtwo', 'Luigi', 'Marth', 'Zelda', 'Young Link', 'Dr. Mario', 'Falco', 'Pichu',
           'Mr. Game & Watch', 'Ganondorf', 'Roy']
EXTERNAL = {'Mario': 8, 'Fox': 2, 'C. Falcon': 0, 'DK': 1, 'Kirby': 4, 'Bowser': 5, 'Link': 6,
            'Sheik': 19, 'Ness': 11, 'Peach': 12, 'Ice Climbers': 14, 'Pikachu': 13,
            'Samus': 16, 'Yoshi': 17, 'Jigglypuff': 15, 'Mewtwo': 10, 'Luigi': 7, 'Marth': 9,
            'Zelda': 18, 'Young Link': 21, 'Dr. Mario': 22, 'Falco': 20, 'Pichu': 24,
            'Mr. Game & Watch': 3, 'Ganondorf': 25, 'Roy': 23}
CUSTOM = ['Metal Mario', 'Luigi & Boo', 'Dr. Luigi', 'Giga Bowser']
SPECIALS = ['Master Hand', 'Crazy Hand', 'Wireframe Male', 'Wireframe Female', 'Giga Bowser',
            'Sandbag']


def fighters():
    """An m-ex roster: vanilla, four added fighters (external 0x1A+), specials."""
    out = [{'internalId': i, 'name': n, 'externalId': EXTERNAL.get(n, 99)}
           for i, n in enumerate(VANILLA)]
    for k, n in enumerate(CUSTOM):
        out.append({'internalId': len(out), 'name': n, 'externalId': 0x1A + k})
    for n in SPECIALS:
        out.append({'internalId': len(out), 'name': n, 'externalId': 0x1A + len(CUSTOM) + len(out) % 7})
    out[11]['externalId'] = len(out) - 1      # Nana's slot ("Popo")
    return out


def ext(name):
    return next(f['externalId'] for f in fighters() if f['name'] == name)


def icon(name, x, y=10.0, hit=7.05):
    return {'fighter': ext(name), 'x': x, 'y': y, 'z': 0.0, 'scaleX': 0.6, 'scaleY': 0.75,
            'sfxID': 194, 'collisionOffsetX': 0.0, 'collisionOffsetY': 0.0,
            'collisionSizeX': hit, 'collisionSizeY': 7.2 if hit else 0.0}


# --- groups -------------------------------------------------------------------

def test_normalize_keeps_project_spelling_and_drops_bad_entries():
    kept, problems = groups.normalize([
        {'base': 'luigi', 'alts': ['Luigi & Boo', 'Dr. Luigi', 'Nobody', 'Sheik']},
        {'base': 'Mario', 'alts': ['Metal Mario', 'Dr. Luigi']},   # Dr. Luigi already used
        {'base': 'Fox', 'alts': ['Popo', 'Sandbag', 'Fox']},        # nothing usable left
    ], fighters())
    assert kept == [{'base': 'Luigi', 'alts': ['Luigi & Boo', 'Dr. Luigi']},
                    {'base': 'Mario', 'alts': ['Metal Mario']}]
    assert len(problems) == 6


def test_a_playable_custom_wins_over_a_same_named_special():
    kept, _ = groups.normalize([{'base': 'Bowser', 'alts': ['Giga Bowser']}], fighters())
    assert groups.resolve(kept, fighters()) == [{'base': ext('Bowser'), 'alts': [0x1A + 3]}]


def test_without_fighter_drops_a_base_group_and_empty_groups():
    g = [{'base': 'Luigi', 'alts': ['Luigi & Boo']}, {'base': 'Mario', 'alts': ['Metal Mario']}]
    assert groups.without_fighter(g, 'luigi & boo') == [{'base': 'Mario', 'alts': ['Metal Mario']}]
    assert groups.without_fighter(g, 'Mario') == [{'base': 'Luigi', 'alts': ['Luigi & Boo']}]


def test_store_round_trip(tmp_path):
    proj = tmp_path / 'project.mexproj'
    assert groups.load(proj) == []
    groups.save(proj, [{'base': 'Mario', 'alts': ['Metal Mario']}])
    assert json.loads((tmp_path / groups.LLOAD_FILE).read_text())['groups'][0]['base'] == 'Mario'
    assert groups.load(proj) == [{'base': 'Mario', 'alts': ['Metal Mario']}]


# --- tucked icons ---------------------------------------------------------------

GROUPS = [{'base': ext('Luigi'), 'alts': [ext('Luigi & Boo'), ext('Dr. Luigi')]}]


def test_tuck_hides_each_alternate_behind_its_base():
    icons = [icon('Mario', -20), icon('Dr. Luigi', -10), icon('Luigi', 0), icon('Luigi & Boo', 10)]
    out, index = layout.tuck(icons, GROUPS)
    assert [i['fighter'] for i in out] == [ext('Mario'), ext('Luigi & Boo'), ext('Dr. Luigi'), ext('Luigi')]
    for alt in out[1:3]:
        assert (alt['x'], alt['y'], alt['scaleX']) == (0, 10.0, 0.6)          # the base's spot
        assert alt['collisionSizeX'] == alt['collisionSizeY'] == 0.0          # never hovered
    assert out[1]['sfxID'] == 194                                             # its own sound kept
    assert index == {ext('Mario'): 0, ext('Luigi & Boo'): 1, ext('Dr. Luigi'): 2, ext('Luigi'): 3}
    assert layout.table(GROUPS, index) == [[(ext('Luigi'), 3), (ext('Luigi & Boo'), 1),
                                            (ext('Dr. Luigi'), 2)]]


def test_tuck_is_idempotent_and_survives_a_reflow():
    icons = [icon('Mario', -20), icon('Luigi', 0), icon('Luigi & Boo', 10)]
    once, _ = layout.tuck(icons, GROUPS)
    twice, _ = layout.tuck(once, GROUPS)
    assert not layout.changed(once, twice)
    # MexCLI's Template.Apply restores hit boxes and moves every icon into a slot:
    reflowed = [dict(i, x=5.0 * n, collisionSizeX=7.05, collisionSizeY=7.2) for n, i in enumerate(once)]
    again, _ = layout.tuck(reflowed, GROUPS)
    luigi = next(i for i in again if i['fighter'] == ext('Luigi'))
    assert all(i['x'] == luigi['x'] and i['collisionSizeX'] == 0.0
               for i in again if i['fighter'] in GROUPS[0]['alts'])


def test_an_alternate_with_no_icon_gets_one():
    out, index = layout.tuck([icon('Luigi', 0)], GROUPS)
    assert len(out) == 3 and index[ext('Luigi')] == 2
    assert out[0]['sfxID'] == layout.DEFAULT_SFX


def test_a_fighter_leaving_its_group_is_untucked_to_the_end():
    tucked, _ = layout.tuck([icon('Mario', -20), icon('Luigi', 0), icon('Luigi & Boo', 0)], GROUPS)
    out, _ = layout.tuck(tucked, [])
    assert [i['fighter'] for i in out] == [ext('Mario'), ext('Luigi'), ext('Luigi & Boo'), ext('Dr. Luigi')]
    assert [i['collisionSizeX'] for i in out[2:]] == [layout.DEFAULT_HIT_BOX[0]] * 2


def test_a_group_whose_base_has_no_icon_is_skipped():
    out, index = layout.tuck([icon('Mario', 0)], GROUPS)
    assert [i['fighter'] for i in out] == [ext('Mario')] and layout.table(GROUPS, index) == []


# --- the code -------------------------------------------------------------------

def test_code_splices_the_table_between_prologue_and_body():
    g = [[(8, 2), (0x2D, 1)], [(7, 6), (0x2B, 3), (0x2E, 4), (0x23, 5)]]
    w = code.words(g)
    table = bytes.fromhex('0208022d010407062b032e0423050000')
    assert w[:4] == list(PREFIX) and w[-len(BODY):] == list(BODY)
    assert w[4] == 0x48000001 | (4 + len(table))
    assert b''.join(x.to_bytes(4, 'big') for x in w[5:5 + len(table) // 4]) == table
    lines = code.source(g).splitlines()
    assert lines[0] == 'C2263334 %08X' % (len(lines) - 1)
    assert lines[-1].endswith('00000000')


def test_code_rejects_ids_that_do_not_fit():
    with pytest.raises(ValueError):
        code.table_bytes([[(300, 1), (2, 2)]])


# --- export: the code in codes.ini ----------------------------------------------

OTHER = '$!Skip Slippi SSS [KELLZ]\n04263384 48000010\n'


@pytest.fixture
def project(tmp_path, monkeypatch):
    proj = tmp_path / 'proj'
    (proj / 'files').mkdir(parents=True)
    calls = []

    def fake_mexcli(*args, stdin=None, timeout=120):
        calls.append(args)
        if args[0] == 'sync-codes':     # what MexCLI would write back
            (proj / 'files' / 'codes.ini').write_text(open(args[2], encoding='utf-8').read(), encoding='utf-8')
        return {'success': True}

    monkeypatch.setattr(lload_export, '_mexcli', fake_mexcli)
    return proj / 'project.mexproj', calls


def _ini(proj):
    return parse_ini((proj.parent / 'files' / 'codes.ini').read_text(encoding='utf-8'))


def test_sync_code_adds_refreshes_and_removes(project):
    proj, calls = project
    (proj.parent / 'files' / 'codes.ini').write_text(OTHER, encoding='utf-8')
    one = code.source([[(8, 1), (7, 2)]])
    two = code.source([[(8, 1), (7, 2), (5, 3)]])

    assert lload_export.sync_code(proj, one) is True
    mine = [c for c in _ini(proj) if c['name'] == code.CODE_NAME]
    assert len(mine) == 1 and mine[0]['enabled'] and mine[0]['creator'] == code.CODE_CREATOR

    assert lload_export.sync_code(proj, one) is False                     # unchanged: no MexCLI
    assert lload_export.sync_code(proj, two) is True
    assert [c['source'] for c in _ini(proj) if c['name'] == code.CODE_NAME] == [two]

    assert lload_export.sync_code(proj, None) is True
    assert [c['name'] for c in _ini(proj)] == ['Skip Slippi SSS']
    assert lload_export.sync_code(proj, None) is False
    assert [c[0] for c in calls] == ['sync-codes'] * 3


def test_sync_code_re_enables_a_disabled_copy(project):
    proj, _ = project
    src = code.source([[(8, 1), (7, 2)]])
    (proj.parent / 'files' / 'codes.ini').write_text(
        serialize_ini([{'name': code.CODE_NAME, 'creator': code.CODE_CREATOR, 'description': '',
                        'source': src, 'enabled': False}]), encoding='utf-8')
    assert lload_export.sync_code(proj, src) is True
    assert _ini(proj)[0]['enabled'] is True


# --- remove-fighter repair -------------------------------------------------------

def test_repair_after_remove_restores_falcons_icon(project, monkeypatch, tmp_path):
    proj, _ = project
    written = []
    monkeypatch.setattr(lload_export, 'set_icons', lambda p, icons: written.append(icons))
    groups.save(proj, [{'base': 'Luigi', 'alts': ['Luigi & Boo']}])
    before = {'fighters': fighters(),
              'icons': [icon('Luigi & Boo', 0, hit=0.0), icon('Luigi', 0), icon('C. Falcon', 10),
                        icon('Dr. Luigi', 20), icon('Sandbag', 30)]}
    lload_export.repair_after_remove(proj, before, 'Luigi & Boo')
    after = [i['fighter'] for i in written[0]]
    assert after == [ext('Luigi'), ext('C. Falcon'), ext('Dr. Luigi') - 1, ext('Sandbag') - 1]
    groups.forget_fighter(proj, 'Luigi & Boo')        # the route does this separately
    assert groups.load(proj) == []


# --- review fixes ------------------------------------------------------------------

def test_a_base_without_an_icon_turns_its_group_off_everywhere():
    stored = [{'base': 'Luigi', 'alts': ['Luigi & Boo']}, {'base': 'Mario', 'alts': ['Metal Mario']}]
    kept, problems = groups.normalize(stored, fighters(), [icon('Mario', 0), icon('Metal Mario', 0, hit=0.0)])
    assert kept == [{'base': 'Mario', 'alts': ['Metal Mario']}]
    assert problems == ['Luigi has no select-screen icon, so its L group is off']


def test_resolve_tolerates_padded_names():
    assert groups.resolve([{'base': ' Luigi ', 'alts': ['Luigi & Boo ']}], fighters()) ==         [{'base': ext('Luigi'), 'alts': [ext('Luigi & Boo')]}]


def test_an_alternate_made_a_base_gets_its_hit_box_back():
    was_alt = icon('Luigi', 0, hit=0.0)
    out, _ = layout.tuck([was_alt, icon('Mario', 0)], GROUPS)
    luigi = next(i for i in out if i['fighter'] == ext('Luigi'))
    assert luigi['collisionSizeX'] == layout.DEFAULT_HIT_BOX[0]


def test_ensure_untucks_when_the_last_group_goes(project, monkeypatch):
    proj, calls = project
    src = code.source([[(ext('Luigi'), 1), (ext('Luigi & Boo'), 0)]])
    (proj.parent / 'files' / 'codes.ini').write_text(
        serialize_ini([{'name': code.CODE_NAME, 'creator': code.CODE_CREATOR, 'description': '',
                        'source': src, 'enabled': True}]), encoding='utf-8')
    layout_now = {'fighters': fighters(), 'icons': [icon('Luigi & Boo', 0, hit=0.0), icon('Luigi', 0)]}
    written = []
    monkeypatch.setattr(lload_export, 'get_layout', lambda p: layout_now)
    monkeypatch.setattr(lload_export, 'set_icons', lambda p, icons: written.append(icons))
    assert lload_export.ensure(proj) == []
    assert [i['fighter'] for i in written[0]] == [ext('Luigi'), ext('Luigi & Boo')]
    assert written[0][1]['collisionSizeX'] == layout.DEFAULT_HIT_BOX[0]


def test_ensure_reports_dropped_groups_and_failures(project, monkeypatch):
    proj, _ = project
    (proj.parent / 'files' / 'codes.ini').write_text(OTHER, encoding='utf-8')
    groups.save(proj, [{'base': 'Luigi', 'alts': ['Luigi & Boo']}, {'base': 'Fox', 'alts': ['Nobody']}])
    monkeypatch.setattr(lload_export, 'get_layout',
                        lambda p: {'fighters': fighters(), 'icons': [icon('Luigi', 0)]})
    monkeypatch.setattr(lload_export, 'set_icons', lambda p, icons: None)
    warnings = lload_export.ensure(proj)
    assert warnings == ['L alternates: "Nobody" is not a selectable fighter in this project; '
                        'left out of this build']
    assert [c['name'] for c in _ini(proj)] == ['Skip Slippi SSS', code.CODE_NAME]

    monkeypatch.setattr(lload_export, 'get_layout', lambda p: (_ for _ in ()).throw(RuntimeError('busy')))
    assert 'not updated' in lload_export.ensure(proj)[0]


def test_projects_without_groups_cost_no_mexcli_call(project, monkeypatch):
    proj, calls = project
    (proj.parent / 'files' / 'codes.ini').write_text(OTHER, encoding='utf-8')
    monkeypatch.setattr(lload_export, 'get_layout', lambda p: pytest.fail('no layout read expected'))
    assert lload_export.ensure(proj) == [] and calls == []
