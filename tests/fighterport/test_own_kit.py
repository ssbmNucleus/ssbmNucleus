"""The helpers a fighter's own specials are written with (`own_kit`), the items they make (`own_items`), and the readers
they stand on."""
import numpy as np

from echo_ultimate.gamedata import articles
from fighter_port import code, own_items, own_kit


# the up special's table as the game has it (vl.prc, param_special_hi)


def test_a_c_text_takes_floats_as_c_floats_and_the_rest_as_they_print():
    assert own_kit.fill('#define A @a@\n#define B @b@\n{ x; }', {'a': 0.5, 'b': 7}) == '#define A 0.5f\n#define B 7\n{ x; }'


def test_a_script_flag_gives_the_frame_the_code_acts_on():
    move = {'flags': [{'cmd': 'off_flag', 'real': 3}, {'cmd': 'on_flag', 'real': 16}, {'cmd': 'on_flag', 'real': 40}]}
    assert own_kit.flag_frame(move) == 16 and own_kit.flag_frame({}) is None


def test_an_items_hitbox_keeps_the_games_numbers_and_is_sized_for_the_world():
    game = {'damage': 1.8, 'angle': 60, 'kbg': 100, 'fkb': 0, 'bkb': 30, 'size': 6.0, 'rehit': 0, 'effect': 'collision_attr_normal'}
    got = own_kit.hitbox(game, 0.5)
    assert (got['damage'], got['angle'], got['knockback_growth'], got['base_knockback']) == (2, 60, 100, 30)
    assert got['size'] == 768 and got['element'] == 0 and got['again'] == 0
    fire = own_kit.hitbox(dict(game, effect='collision_attr_fire', rehit=7, damage=10.0), 1.0, damage=0, element=11)
    assert fire['again'] == 7 and fire['damage'] == 0 and fire['element'] == 11 and fire['hit_sfx_kind'] == 8


def slab(colours, cell=(0.3, 0.25), gap=0.001):
    """A figure of little coloured rectangles, as the game builds one: two faces a rectangle, neighbours a hair apart."""
    rows, cols = len(colours), len(colours[0])
    P, UV, T = [], [], []
    for j in range(rows):
        for i in range(cols):
            if colours[j][i] is None:
                continue
            z0, y1 = i * (cell[0] + gap), (rows - j) * (cell[1] + gap)
            for x, order in ((-0.46, (0, 1, 2, 0, 2, 3)), (0.46, (0, 2, 1, 0, 3, 2))):
                base = len(P)
                P += [[x, y1 - cell[1], z0], [x, y1 - cell[1], z0 + cell[0]], [x, y1, z0 + cell[0]], [x, y1, z0]]
                UV += [[(colours[j][i] + 0.5) / 4.0, 0.5]] * 4
                T += [[base + order[0], base + order[1], base + order[2]], [base + order[3], base + order[4], base + order[5]]]
    return {'positions': np.array(P), 'uvs': np.array(UV), 'triangles': np.array(T), 'normals': np.zeros((len(P), 3)), 'texture': 'p'}


def test_a_slab_of_little_rectangles_is_read_as_a_picture_a_pixel_each(tmp_path):
    from PIL import Image
    palette = Image.new('RGBA', (4, 1))
    palette.putdata([(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 0, 255)])
    palette.save(tmp_path / 'p.png')
    figure = [[None, 0, 0, None], [1, 1, 2, 2], [3, None, None, 3]]
    image, extent = own_items.slab_picture(slab(figure), tmp_path / 'p.png')
    assert image.size == (4, 3) and image.mode == 'RGBA'
    got = np.asarray(image)
    assert [tuple(got[0, i]) for i in range(4)] == [(0, 0, 0, 0), (255, 0, 0, 255), (255, 0, 0, 255), (0, 0, 0, 0)]
    assert tuple(got[1, 0]) == (0, 255, 0, 255) and tuple(got[1, 3]) == (0, 0, 255, 255) and got[2, 1, 3] == 0
    assert extent[0] == 0.0 and round(extent[3] - extent[2], 2) == 0.75                    # three rows of 0.25
    # ... and stands as a flat model seen from both sides, with its picture saved larger
    model = own_items.cutout(image, extent, 'figure', tmp_path, grow=4)
    assert model['triangles'] == 4 and np.allclose(model['parts'][0]['positions'][:, 0], 0.0)
    assert Image.open(tmp_path / 'tex' / 'figure.png').size == (16, 12)


def test_an_own_item_has_none_of_the_templates_effects_as_it_is_removed():
    # (item.c ItemSwitch plays the common numbers' effect at +0x64 when an item's time is up and at +0x68 when a
    # hit ends it: the template's are a fireball's puff)
    assert own_items.GONE_EFFECTS == (0x64, 0x68)


def test_the_box_the_stage_stops_an_item_with_is_its_models_own_size():
    model = {'min': np.array([-2.5, -3.5, -2.5]), 'max': np.array([2.5, 3.4, 2.5])}
    box = own_items.box_of(model, own_items.TO_ITEM, 2.0)
    assert (box['top'], box['bottom'], box['right'], box['left']) == (6.8, -7.0, -5.0, 5.0)


def test_registrations_fall_into_runs_of_one_owner():
    reg = lambda name, func: {'agent': 'animcmd_game', 'name': name, 'func': func}
    listed = [reg('game_move', 0x10d180), reg('game_fly', 0xfd430), reg('game_stand', 0xfd4c0), reg('game_fly', 0xff710),
              reg('game_hit', 0xff7a0), reg('game_dash', 0xaf540), reg('game_fly2', 0xaf5d0),
              {'agent': 'animcmd_sound', 'name': 'sound_fly', 'func': 0x105270}]
    got = [[r['name'] for _n, r in run] for run in articles.runs(listed)]
    assert got == [['game_move'], ['game_fly', 'game_stand'], ['game_fly', 'game_hit'], ['game_dash', 'game_fly2']]


def test_a_sound_only_code_plays_gets_a_plain_place_in_the_bank(monkeypatch):
    import io
    import zipfile
    from fighter_port import voice
    sound = lambda: {'pcm': np.ones(320, np.int16), 'rate': 32000}
    names = ['se_x_special_n01', 'se_x_special_n02', 'se_x_special_n07', 'se_x_special_s01', 'se_x_smash_s01',
             'se_x_smash_s02', 'se_x_attackdash']
    se = {n: (n, sound()) for n in names}
    monkeypatch.setattr(voice, '_banks', lambda root, fighter, game='ultimate': {'se': se, 'vc': {}, 'cheer': {}})
    # the donor's package: its charge sample is played in a loop, the rest plainly; two voices have a big and a
    # small form (scripts a port's bank has no use for: where a sound the bank gains goes)
    plain = lambda sample: [(1, sample), (16, 1), (4, 15), (6, 204), (14, 0)]
    bent = lambda sample, pitch: [(1, sample), (16, 1), (12, pitch), (4, 15), (6, 204), (14, 0)]
    loop = lambda sample: [(1, sample), (2, 0), (13, 5), (3, 0), (14, 0)]
    samples = ['se_mars_sbreak', 'se_mars_sbreak_tame', 'se_mars_sw_conbo1', 'se_mars_sw_conbo2', 'se_mars_sw_demo2',
               'v_mars_jump', 'v_mars_gake']
    scripts = [plain(0), loop(1), plain(2), plain(3), plain(4), plain(5), bent(5, 65186), bent(5, 450),
               plain(6), bent(6, 65186), bent(6, 450)]
    script_names = ['SFX' + s for s in samples[:6]] + ['SFXv_mars_jumpB', 'SFXv_mars_jumpS', 'SFXv_mars_gake',
                                                       'SFXv_mars_gakeB', 'SFXv_mars_gakeS']
    package = io.BytesIO()
    with zipfile.ZipFile(package, 'w') as z:
        z.writestr('scripts.sem', voice.sem_write(scripts))
        z.writestr('scripts.json', str(script_names).replace("'", '"'))
    moves = {'game_specialn': {'hitboxes': [], 'sounds': [{'cmd': 'PLAY_SE', 'name': 'se_x_special_n01'}]},
             'game_specials': {'hitboxes': [], 'sounds': [{'cmd': 'PLAY_SE', 'name': 'se_x_special_s01'}]},
             'game_attacks4': {'hitboxes': [1], 'sounds': [{'cmd': 'PLAY_SE', 'name': 'se_x_smash_s01'},
                                                           {'cmd': 'PLAY_SE', 'name': 'se_x_smash_s02'}]},
             'game_attackdash': {'hitboxes': [1], 'sounds': [{'cmd': 'PLAY_SE', 'name': 'se_x_attackdash'}]}}
    coded = dict(moves, **{voice.CODE: {'code_plays': True, 'sounds': [{'cmd': 'PLAY_SE', 'name': 'se_x_special_n02'},
                                                                      {'cmd': 'PLAY_SE', 'name': 'se_x_special_n07'}]}})
    pick = lambda mv, route: voice.choose('Marth', 'x', None, samples, mv, 'ultimate', package.getvalue(), route=route)
    name = lambda chosen: {k: v[0] for k, v in chosen.items()}
    # without the code's list: the charge sample holds the second sound of the neutral special, by its row (nothing
    # can call it there). The side special's row does not go round again onto its second sample, which nothing
    # plays on this route: that one is room, for the sound of the move that would otherwise be silent.
    before = name(pick(moves, 'own skeleton')[0])
    assert before['se_mars_sbreak_tame'] == 'se_x_special_n02' and before['se_mars_sw_conbo2'] == 'se_x_attackdash'
    assert [k for k in before if k.startswith(voice.ADDED)] == ['+se_x_smash_s02']
    # with it: the charge sample is silent and the sound the code plays is on a place it can call; the code's
    # sounds come after the sound of a move that would be silent and before the sound of a move heard already
    chosen, left = pick(coded, 'own skeleton')
    after = name(chosen)
    assert after['se_mars_sbreak_tame'] == voice.SILENCE and after['se_mars_sw_conbo2'] == 'se_x_attackdash'
    assert [k for k in after if k.startswith(voice.ADDED)] == ['+se_x_special_n02', '+se_x_special_n07', '+se_x_smash_s02']
    calls = voice.calls(package.getvalue(), 19, chosen)
    assert (calls['se_x_special_n02'], calls['se_x_special_n07'], calls['se_x_smash_s02']) == (190006, 190007, 190009)
    assert any('loops or bends' in line and 'se_x_special_n02' in line for line in left)
    # a sound a script the port writes plays (Wolf's Blaster plays its n02 on frame 40) is never put on the charge
    # sample on this route: nothing calls that place there, so it would be silent. It goes where a script can call it.
    shot = dict(moves, game_specialn={'hitboxes': [], 'sounds': [{'cmd': 'PLAY_SE', 'name': 'se_x_special_n01'},
                                                                 {'cmd': 'PLAY_SE', 'name': 'se_x_special_n02'}]})
    chosen, left = pick(shot, 'own skeleton')
    assert name(chosen)['se_mars_sbreak_tame'] == voice.SILENCE
    assert 'se_x_special_n02' in voice.calls(package.getvalue(), 19, chosen)
    assert any('a script the port writes plays se_x_special_n02' in line for line in left)
    # on the donor's skeleton the donor's own neutral special still plays its charge sample: the row holds
    assert name(pick(shot, None)[0])['se_mars_sbreak_tame'] == 'se_x_special_n02'
    # a special's start whose script plays a sound once (Greninja's charge): on the own skeleton no script the port
    # writes can call the charge sample either, so the sound goes to a plain place and the charge sample is silent
    started = dict(moves, game_specialnstart={'hitboxes': [], 'sounds': [{'cmd': 'PLAY_SE', 'name': 'se_x_special_n02'}]})
    chosen, left = pick(started, 'own skeleton')
    held = name(chosen)
    assert held['se_mars_sbreak_tame'] == voice.SILENCE and 'se_x_special_n02' in held.values()
    assert any('a script the port writes plays se_x_special_n02' in line for line in left)
    # the donor's skeleton keeps it there: the donor's own start script still loops that sample
    assert name(pick(started, None)[0])['se_mars_sbreak_tame'] == 'se_x_special_n02'
    # the bank gains more than its usual most only for the code's sounds
    monkeypatch.setattr(voice, 'MORE', 0)
    assert [k for k in name(pick(coded, 'own skeleton')[0]) if k.startswith(voice.ADDED)] == ['+se_x_special_n02', '+se_x_special_n07']
    assert [k for k in name(pick(moves, 'own skeleton')[0]) if k.startswith(voice.ADDED)] == []
    # on the donor's skeleton the donor's own code still plays its samples: the row goes round as before
    assert name(pick(moves, None)[0])['se_mars_sw_conbo2'] == 'se_x_special_s01'


def test_the_code_file_carries_one_file_for_each_item_of_the_own_states():
    mine = {'source': ['// own'], 'frame': ['OwnFrame(fd, gobj);'], 'load': ['OwnLoad(fd);'], 'provides': ['own states'],
            'table': ['// table'], 'items': [{'code': '// the can'}, {'code': '// the clay'}]}
    files, provides = code.source('Marth', None, None, None, None, None, mine, 0x801364AC)
    assert files['item_0.c'] == '// the can' and files['item_1.c'] == '// the clay' and 'own states' in provides
    assert 'OwnLoad(fd);' in files['fighter.c'] and '0x801364ac' in files['fighter.c']


