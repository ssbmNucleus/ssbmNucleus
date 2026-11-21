"""A fighter of forms (fighter_port/forms.py, fighters.FORMS): the switch's states and code, the preload and the
link, each held against what it must do without a game."""
import json
import struct

import pytest

from fighter_port import fighters, forms, own_template


def test_a_group_names_its_forms_in_the_order_the_switch_goes_round():
    group, entry = fighters.group('pfushigisou')
    assert group == 'ptrainer' and [f for f, _ in entry['forms']] == ['pzenigame', 'pfushigisou', 'plizardon']
    assert fighters.group('ptrainer')[0] == 'ptrainer'
    assert fighters.group('wolf') == (None, None)
    assert set(entry) <= set(fighters.FORM_VALUES)
    # the group itself is not a form: only its members get the switch
    assert forms.group_of('ptrainer') == (None, None) and forms.group_of('plizardon')[0] == 'ptrainer'


def test_the_switch_clips_go_on_the_switch_specials_actions_and_two_free_ones():
    got = forms.clips('pzenigame', {'speciallwin', 'speciallwout', 'wait1'})
    assert got == {'speciallwin': 'SpecialLw', 'speciallwout': 'SpecialLwHit'}     # no air clips: left out
    assert set(forms.ARRIVE_ACTIONS) <= set(own_template.FREE_ACTIONS)
    assert forms.clips('wolf') == {}


def _ctx(first=400, work=''):
    action = {m: i for i, m in enumerate(['SpecialLw', 'SpecialAirLw', 'SpecialLwHit', 'SpecialAirLwHit', 'SpecialHi',
                                          'SpecialAirHi', 'SpecialS1', 'SpecialAirS1', 'SpecialS3Hi', 'SpecialAirS3Hi',
                                          'SpecialNStart', 'SpecialAirNStart'], 300)}
    total = {'SpecialLw': 12, 'SpecialLwHit': 40, 'SpecialHi': 30, 'SpecialAirHi': 30}
    row = {m: {'flags': 0x340000, 'move': 0x10} for m in action}
    return {'first': first, 'action': action, 'total': total, 'row': row, 'moves': {}, 'work': work}


def test_the_switch_states_come_first_and_the_specials_after_them_without_the_switch():
    seen = {}

    def inner(of, ctx):
        seen.update(ctx)
        return {'source': ['// inner'], 'rows': [{'name': 'inner'}], 'load': ['L;'], 'frame': ['F;'], 'entries': [],
                'numbers': {}, 'flash': [], 'provides': ['inner']}, None

    mine, why = forms.build('pzenigame', 'template', _ctx(), inner)
    assert why is None
    assert seen['first'] == 400 + forms.STATES and seen['switch'] == 'down'
    assert [r['name'] for r in mine['rows']][:4] == ['the switch: leaving', 'the switch: leaving, in the air',
                                                    'the switch: arriving', 'the switch: arriving, in the air']
    assert mine['rows'][4]['name'] == 'inner'
    # no air clips: the air states play the ground's actions
    assert [r['action'] for r in mine['rows'][:4]] == [300, 300, 302, 302]
    text = '\n'.join(mine['source'])
    assert '#define FORM_LEAVE 400' in text and '#define FORM_ARRIVE_AIR 403' in text
    assert 'void SpecialLw(GOBJ *gobj)' in text and 'void SpecialAirLw(GOBJ *gobj)' in text
    assert '#define FORM_WAIT 140' in text and '#define FORM_UNTOUCHABLE 25' in text
    assert '@' not in text and text.rstrip().endswith('// inner')
    assert mine['load'][0] == 'FormLoad(fd);' and mine['frame'][0] == 'FormFrame(fd);'
    # a fighter that is not a form gets its specials as they are
    assert forms.build('wolf', 'wolf', _ctx(), inner)[0]['rows'] == [{'name': 'inner'}]


def test_without_its_clip_that_ends_a_form_the_switch_is_not_built():
    ctx = _ctx()
    ctx['total'].pop('SpecialLw')
    mine, why = forms.build('pzenigame', 'template', ctx, lambda of, c: (None, 'x'))
    assert mine is None and 'SpecialLw' in why


def test_the_template_leaves_the_switch_to_forms():
    ctx = _ctx()
    ctx['switch'] = 'down'
    mine, _ = own_template.build(ctx)
    text = '\n'.join(mine['source'])
    assert 'void SpecialLw(' not in text and 'void SpecialHi(' in text


def test_the_arriving_frame_he_may_act_from_is_the_games(tmp_path):
    (tmp_path / 'game.json').write_text(json.dumps({'motions': {'d03speciallwout': {'cancel_frame': 16}}}), 'utf-8')
    mine, _ = forms.build('pzenigame', 'template', _ctx(work=str(tmp_path)),
                          lambda of, c: (None, 'no specials'))
    assert '#define FORM_ARRIVE_END 16' in '\n'.join(mine['source'])
    assert {n['what']: n['value'] for n in mine['numbers']['switch']}['the switch: the frame he may act from as he arrives'] == 16


def test_the_preload_code_hooks_the_end_of_the_loader_and_jumps_over_its_table():
    lines = forms.preload_code([[27, 28, 29]])
    assert lines[0].startswith('C2031D14 ')
    words = [int(w, 16) for line in lines[1:] for w in line.split()]
    assert int(lines[0].split()[1], 16) * 2 == len(words) and words[-1] == 0
    assert words[2] == 0x48000001 | (4 + 8)                     # bl over [3, 27, 28, 29, 0] padded to 8
    assert struct.pack('>2I', *words[3:5])[:5] == bytes([3, 27, 28, 29, 0])
    assert 0x8001001C in words[-3:]                            # the instruction it stands in place of, last
    assert '3D808008 618C55C8' in ' '.join(lines)                # ftData_800855C8
    two = forms.preload_code([[27, 28, 29], [30, 31]])
    assert len(two) == len(lines) + 1 or len(two) == len(lines)
    with pytest.raises(ValueError):
        forms.preload_code([[27]])


def test_the_link_makes_a_ring_and_the_screen_shows_the_first_form(tmp_path):
    (tmp_path / 'fighters').mkdir()
    for k in (27, 28, 29):
        (tmp_path / 'fighters' / f'{k:03d}.json').write_text(json.dumps({'name': str(k), 'subCharacter': -1}), 'utf-8')
    ring = forms.link_project(tmp_path, [27, 28, 29])
    assert ring == {27: 28, 28: 29, 29: 27}
    entry = json.loads((tmp_path / 'fighters' / '029.json').read_text('utf-8'))
    assert entry['subCharacter'] == 27 and entry['subCharacterBehavior'] == 1
    css = {'fighterIcons': [{'fighter': 25}, {'fighter': 26}, {'fighter': 27}, {'fighter': 28}], 'template': 1}
    kept, gone = forms.one_on_the_screen(css, [26, 27, 28])
    assert [i['fighter'] for i in kept['fighterIcons']] == [25, 26] and gone == [27, 28] and kept['template'] == 1


def test_the_port_command_takes_a_group_to_its_own_stages(monkeypatch, tmp_path):
    import argparse
    from fighter_port import port
    assert port.FORM_STAGES == ('forms', 'project', 'link', 'art', 'build', 'verify')
    seen = {}
    monkeypatch.setattr(port, 'run_forms', lambda a, repo, log=print: seen.setdefault('group', a.fighter))
    repo = tmp_path / 'repo'
    (repo / 'app' / 'backend').mkdir(parents=True)
    a = argparse.Namespace(fighter='ptrainer', repo=str(repo), own=True, work=str(tmp_path / 'w'))
    port.run(a, log=lambda *m: None)
    assert seen['group'] == 'ptrainer'


def _form_work(root, name, data=300_000, effects=200_000, clip=2_400_000, costume=750_000):
    import zipfile
    w = root / name
    final = w / 'port' / 'final'
    final.mkdir(parents=True)
    (w / 'port' / 'report.json').write_text('{}', 'utf-8')
    (final / 'PlMs.dat').write_bytes(bytes(data))
    (final / 'EfMsData.dat').write_bytes(bytes(effects))
    (final / 'PlMsAJ.dat').write_bytes(bytes(clip))
    cos = w / 'package' / 'costumes'
    cos.mkdir(parents=True)
    (cos / 'PlMsNr.dat').write_bytes(bytes(costume))
    (cos / 'costumes.json').write_text(json.dumps([{'file': 'PlMsNr.dat', 'folder': 'c00'}]), 'utf-8')
    with zipfile.ZipFile(w / 'package' / 'x.zip', 'w') as z:
        z.writestr('fighter.json', json.dumps({'files': {'fighterDataPath': 'PlMs.dat', 'effectFile': 'EfMsData.dat',
                                                         'animFile': 'PlMsAJ.dat'}}))
    return w


def test_the_room_of_forms_is_every_form_together(tmp_path):
    from fighter_port import verify
    three = [_form_work(tmp_path, n, data=100_000, effects=50_000, costume=400_000, clip=2_000_000) for n in ('a', 'b', 'c')]
    got = verify.forms_room(three)['13.7']
    assert got['verdict'] in ('ok', 'say') and 'Zelda' in got['how']
    # clip files that do not fit beside the second fighter's: the match does not load
    big = [_form_work(tmp_path / 'big', n, clip=2_500_000) for n in ('a', 'b', 'c')]
    got = verify.forms_room(big)['13.7']
    assert got['verdict'] == 'FAULT' and 'clips beside Zelda' in got['how']
    # costumes that do not fit two at a time
    fat = [_form_work(tmp_path / 'fat', n, costume=1_200_000, clip=1_000_000) for n in ('a', 'b', 'c')]
    assert verify.forms_room(fat)['13.7']['verdict'] == 'FAULT'


def test_a_forms_clip_file_has_an_equal_share_of_the_clip_heap_beside_zelda():
    from fighter_port import verify
    share = forms.clip_share('pzenigame')
    assert share == (verify.CLIP_HEAP - verify.ZELDA_CLIPS - verify.TIGHT) // 3
    assert forms.clip_share('wolf') is None
    assert forms.looser(share * 2, share, 0) == forms.LOOSEST and forms.looser(share + 1, share, 2) == 3
    assert forms.looser(2_420_192, share, 0) == 4 and forms.looser(2_194_240, share, 2) == 4
    assert forms.looser(share * 100, share, 0) == forms.LOOSEST


def test_the_bank_is_made_at_looser_tolerances_and_put_back():
    from fighter_port import own_bank
    kept = own_bank.BUDGETS
    seen = forms.bank(own_bank, 3, lambda: own_bank.BUDGETS)
    assert seen == kept[3:] and own_bank.BUDGETS is kept


def test_a_forms_pictures_are_half_the_side():
    from fighter_port import own_skeleton
    assert own_skeleton.picture_side_for('wolf') == own_skeleton.PICTURE_SIDE
    assert own_skeleton.picture_side_for('pfushigisou') == own_skeleton.PICTURE_SIDE // 2
    assert own_skeleton.picture_side_for('ptrainer') == own_skeleton.PICTURE_SIDE


def test_a_name_wider_than_the_tiles_plate_says_one_word_of_it(monkeypatch, tmp_path):
    """The group's name is the first form's tile: 'Pokemon Trainer' is wider than the plate at every tracking, so
    the tile says its last word; a name no word of which fits keeps the plain crop instead of stopping the link."""
    import importlib
    import io
    import sys
    from pathlib import Path
    from PIL import Image
    monkeypatch.setenv('NUCLEUS_REPO', str(tmp_path))
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'tools' / 'fighterport' / 'fighter_port' / 'harness'))
    sys.modules.pop('roster_tile', None)
    tile = importlib.import_module('roster_tile')
    from fighter_port import name_plate as pres
    assert tile.plate_words('Pokemon Trainer') == ['POKEMONTRAINER', 'TRAINER', 'POKEMON']
    assert tile.plate_words('Wolf') == ['WOLF'] and tile.plate_words('Mr. Game & Watch')[0] == 'MRGAMEWATCH'
    (tmp_path / pres.CSS_TEMPLATE).write_bytes(b'')
    said = []

    def cell(pane, css_dir, word, tracking):
        if len(word) * 7 - tracking > 58:
            raise ValueError('wide')
        said.append(word)
        return Image.new('RGBA', (64, 56))
    monkeypatch.setattr(pres, 'css_cell', cell)
    monkeypatch.setattr(pres, 'glyph_bank', lambda d: set('ABCDEFGHIJKLMNOPQRSTUVWXYZ'))
    face = Image.new('RGBA', (100, 200))
    face.paste((200, 100, 50, 255), (30, 20, 70, 180))
    buf = io.BytesIO()
    face.save(buf, 'PNG')
    assert tile.roster_tile(buf.getvalue(), 'Pokemon Trainer', tmp_path) and said == ['TRAINER']
    assert tile.roster_tile(buf.getvalue(), 'Extraordinarily Unpronounceable', tmp_path) is None


def test_when_the_files_heap_is_short_the_largest_costumes_pictures_go_smaller(tmp_path):
    from fighter_port import own_skeleton
    sizes = {'pzenigame': 540_000, 'pfushigisou': 740_000, 'plizardon': 300_000}
    works = [_form_work(tmp_path, n, data=220_000, effects=150_000, costume=c) for n, c in sizes.items()]
    assert forms.heap_short(works) == ['two of it on Pokemon Stadium']
    assert forms.shrink_side(works) == (works[1], own_skeleton.PICTURE_SIDE // 4)
    (works[1] / 'forms-side.json').write_text(json.dumps({'side': own_skeleton.PICTURE_SIDE // 4}), 'utf-8')
    assert own_skeleton.picture_side_for('pfushigisou', works[1]) == own_skeleton.PICTURE_SIDE // 4
    (works[1] / 'forms-side.json').write_text(json.dumps({'side': forms.SMALLEST_SIDE}), 'utf-8')
    assert forms.shrink_side(works) == (works[0], own_skeleton.PICTURE_SIDE // 4)     # the next largest
    small = [_form_work(tmp_path / 'small', n, data=100_000, effects=50_000, costume=300_000) for n in sizes]
    assert forms.heap_short(small) == []


def test_the_art_stage_does_not_photograph_a_disc_older_than_a_forms_costumes(tmp_path):
    import os
    works = [tmp_path / n for n in ('pzenigame', 'pfushigisou')]
    for w in works:
        (w / 'package' / 'costumes').mkdir(parents=True)
        (w / 'package' / 'costumes' / 'PlMsNr.dat').write_bytes(b'x')
    iso = tmp_path / 'group.iso'
    assert forms.stale_disc(iso, works) == ['pzenigame', 'pfushigisou']          # no disc yet
    iso.write_bytes(b'disc')
    later = iso.stat().st_mtime + 60
    os.utime(works[0] / 'package' / 'costumes' / 'PlMsNr.dat', (later, later))  # a costume made again after the link
    os.utime(works[1] / 'package' / 'costumes' / 'PlMsNr.dat', (later - 120, later - 120))
    assert forms.stale_disc(iso, works) == ['pzenigame']
