"""What a Brawl fighter shows and when: the face on each frame of a clip, the parts of the model drawn at rest, an
eye's layers made ready for the importer, the lids of its blink; which targets a hit strikes; the shared effects a
script draws. The last tests read the real disc and run only when BRAWL_ROOT names a folder with it extracted."""
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from echo_brawl import gamedata, model


class Scripts:
    """A moveset of one action: its scripts by kind."""

    def __init__(self, **scripts):
        self.scripts = scripts

    def script(self, kind, index):
        return self.scripts.get(kind, [])


def box(number, flags):
    return {'event': 'hitbox', 'args': [number, 10, 361, 100, 30, 5.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, flags]}


def test_a_hit_says_whether_it_strikes_those_on_the_ground_or_in_the_air():
    # two bits of a hitbox's last word: it hits fighters on the ground, it hits fighters in the air (Donkey Kong's
    # Hand Slap has only the first)
    m = Scripts(main=[box(0, 3 << 16), box(1, 1 << 16), box(2, 2 << 16)])
    hits = gamedata.action(m, 0, ['TopN'])['hitboxes']
    assert [h['targets'] for h in hits] == [None, 'ground', 'air']


def test_the_face_a_clip_shows_is_read_a_frame_at_a_time():
    # Ike standing: his resting face but for eight frames, half shut going in and coming out of a blink
    shown = {'FaceM': [True] * 3 + [False] * 5 + [True] * 2,
             'BlinkHalfM': [False] * 3 + [True] + [False] * 3 + [True] + [False] * 2,
             'BlinkM': [False] * 4 + [True] * 3 + [False] * 3,
             'TalkM': [False] * 10}
    assert gamedata.faces(shown) == [(1, 'open'), (4, 'half'), (5, 'closed'), (8, 'half'), (9, 'open')]
    # a clip joined on after another counts on from it
    assert gamedata.faces(shown, 24.0)[1] == (28, 'half')
    # eyes screwed up in pain are shut; a clip that never leaves the resting face says nothing
    assert gamedata.faces({'FaceM': [False] * 4, 'OuchM': [True] * 4}) == [(1, 'closed')]
    assert gamedata.faces({'FaceM': [True] * 4, 'BlinkM': [False] * 4}) == []


def test_a_hidden_form_of_the_face_is_taken_out_of_the_rip():
    draws = [('skin', 'face', 'FaceM', True), ('eye', 'eyes', 'FaceM', True),
             ('skin', 'blinkface', 'BlinkM', False), ('eye', 'blinkeyes', 'BlinkM', False),
             ('metal', 'sword', 'SwordM', True), ('metal', 'sheath', 'SheathM', False)]
    parts = {'draws': draws}
    # all of it ripped: everything not drawn at rest goes
    everything = {'face', 'eyes', 'blinkface', 'blinkeyes', 'sword', 'sheath'}
    assert model.hidden(parts, everything) == ['blinkeyes', 'blinkface', 'sheath']
    # a rip that kept one copy of what two forms share (the eyes, under the blinking face's name): that copy stays
    assert model.hidden(parts, everything - {'eyes'}) == ['blinkface', 'sheath']


def test_a_picture_is_drawn_out_as_the_game_wraps_it():
    picture = Image.fromarray(np.array([[[255, 0, 0, 255], [0, 0, 255, 255]]], np.uint8), 'RGBA')      # red, blue
    row = lambda image: [tuple(int(c) for c in image.getpixel((x, 0))[:3]) for x in range(image.width)]
    red, blue = (255, 0, 0), (0, 0, 255)
    assert row(model.spread(picture, (0, 0), (2, 1), (1, 0))) == [red, blue, red, blue]                 # repeated
    assert row(model.spread(picture, (0, 0), (2, 1), (2, 0))) == [red, blue, blue, red]                 # mirrored
    assert row(model.spread(picture, (-1, 0), (2, 1), (0, 0))) == [red, red, red, blue, blue, blue]     # held at its edges


def test_an_action_is_stored_a_frame_longer_unless_the_engine_plays_its_whole_clip():
    from fighter_port.oneshot import lasts_its_keys
    loops = {'Run', 'CatchWait'}
    # Melee steps the animation once as it enters a dodge, an attack, a ledge action, the first state of a special: a
    # dodge stored as 28 frames is 27 in the game, so the clip that goes on it is given one more
    assert all(lasts_its_keys(m, loops, 'Marth') for m in ('EscapeN', 'Attack11', 'AttackS4', 'AttackAirF', 'CliffClimbQuick',
                                                         'DownAttackU', 'GuardOn', 'ThrowF', 'SpecialNStart', 'SpecialNEnd',
                                                         'SpecialS1', 'SpecialHi', 'SpecialLw'))
    # a grab, a shield drop, a getup, a tech, a taunt, the second and third jab and a landing are entered at their first
    # frame and play their whole clip; a loop wraps on its count
    assert not any(lasts_its_keys(m, loops, 'Marth') for m in ('Catch', 'CatchDash', 'CatchAttack', 'GuardOff', 'DownStandU',
                                                             'DownBoundD', 'Passive', 'PassiveStandF', 'Appeal', 'Attack12',
                                                             'Attack13', 'Landing', 'LandingAirF', 'JumpF', 'Wait1', 'Run'))
    # the donor's own later states: the strike of Marth's counter and the later swings of his chain start at frame 0
    assert not lasts_its_keys('SpecialLwHit', loops, 'Marth') and not lasts_its_keys('SpecialAirS3S', loops, 'Marth')
    assert lasts_its_keys('SpecialLwHit', loops)


def test_a_scripts_loops_are_written_out():
    from echo_brawl.moveset import timeline
    wait = lambda n: {'event': 'wait', 'args': [float(n)]}
    ev = lambda name: {'event': name, 'args': []}
    # a pulse every four frames, three times over, then one more thing
    events = [{'event': 'loop', 'args': [3]}, ev('flash'), wait(4), ev('loop_end'), ev('after')]
    assert [(f, e['event']) for f, e in timeline(events)] == [(1.0, 'flash'), (5.0, 'flash'), (9.0, 'flash'), (13.0, 'after')]
    # a loop with no count goes round with its clip: written once
    events = [{'event': 'loop', 'args': [-1]}, ev('smoke'), wait(10), ev('loop_end')]
    assert [(f, e['event']) for f, e in timeline(events)] == [(1.0, 'smoke')]


def test_the_colour_over_the_body_is_read_from_the_graphics_script():
    flash = lambda *c: {'event': 'flash_overlay', 'args': list(c)}
    m = Scripts(gfx=[{'event': 'wait', 'args': [10.0]}, flash(255, 255, 255, 190), {'event': 'wait', 'args': [1.0]},
                     {'event': 'change_flash', 'args': [8, 255, 0, 0, 0]}, {'event': 'wait', 'args': [8.0]},
                     {'event': 'flash_overlay_off', 'args': []}])
    rows = gamedata.flashes(m, 0)
    # white at once on frame 11, going to clear red over eight frames from 12, off on 20
    assert rows == [[11, [255, 255, 255, 190], 0], [12, [255, 0, 0, 0], 8], [20, [0, 0, 0, 0], 0]]
    from fighter_port.oneshot import flash_keys
    keys = flash_keys(rows)
    # each key knows the colour it starts from: the change starts from the white that was showing
    assert keys[1] == (12, 8, [255, 255, 255, 190], [255, 0, 0, 0])
    # a clip joined on after another plays its flashes later
    assert [k[0] for k in flash_keys(rows, 24)] == [35, 36, 44]


def test_the_ports_code_plays_the_flashes_by_action_and_frame():
    from fighter_port import code
    files, provides = code.source('Marth', flash=[(300, 12, 8, [255, 255, 255, 190], [255, 0, 0, 0]), (300, 11, 0, [255, 255, 255, 0], [255, 255, 255, 190])])
    text = files['fighter.c']
    assert "the body's colour on the frames the game's scripts give" in provides
    # in the order they play, and run from the per-frame function
    assert text.index('{300, 11, 0, {255, 255, 255, 0}, {255, 255, 255, 190}},') < text.index('{300, 12, 8, {255, 255, 255, 190}, {255, 0, 0, 0}},')
    assert 'FlashFrame(fd);' in text.split('void OnFrame(GOBJ *gobj)')[1]


ROOT = os.environ.get('BRAWL_ROOT', '')
needs_disc = pytest.mark.skipif(not (ROOT and any(Path(ROOT).rglob('FitIke.pac'))), reason='needs BRAWL_ROOT (a disc with Ike on it)')
RIP = Path(ROOT) / 'input' / 'ike.zip' if ROOT else Path('none')
needs_rip = pytest.mark.skipif(not (ROOT and RIP.exists()), reason='needs the ripped model beside the disc')


@needs_disc
def test_ike_blinks_while_he_stands_and_shuts_his_eyes_when_hit():
    game = gamedata.load('ike', ROOT)
    standing = next(v for k, v in game['moves'].items() if k.endswith('wait1'))['faces']
    assert [s for _f, s in standing] == ['open', 'half', 'closed', 'half', 'open']
    assert [f for f, _s in standing] == [1, 20, 21, 26, 28]
    assert any(v.get('faces') and v['faces'][0][1] == 'closed' for k, v in game['moves'].items() if 'damage' in k)


@needs_disc
def test_what_ike_shows_at_rest():
    parts = model.parts(ROOT, 'ike')
    by_bone = {}
    for _material, obj, bone, shown in parts['draws']:
        by_bone.setdefault(bone, shown)
    # his resting face, not the blinking ones; an eye is three pictures over each other
    assert by_bone['FaceM'] and not by_bone['BlinkM'] and not by_bone['BlinkHalfM'] and not by_bone['OuchM']
    assert any(len(refs) == 3 for refs in parts['layers'].values())


@needs_disc
def test_shared_effects_have_names_and_scripts_draw_them():
    words = gamedata.common_effects(ROOT)
    assert words and all(w.startswith('sys_') for w in words.values())
    game = gamedata.load('ike', ROOT)
    drawn = {e['args'][0] for v in game['moves'].values() for e in v.get('effects', []) if e['cmd'] == 'EFFECT'}
    # the shared ones by their own names, the fighter's own by theirs (Eruption's fire, and the blast of a full charge)
    own = set(gamedata.own_effects(ROOT, 'ike').values())
    assert drawn and drawn <= set(words.values()) | own and {'ike_hunka', 'ike_hunka_max', 'sys_dash_smoke'} <= drawn
    full = [e['args'][0] for e in game['moves']['game_specialnend__2']['effects'] if e['cmd'] == 'EFFECT']
    assert 'ike_hunka_max' in full and 'ike_hunka_max' not in [e['args'][0] for e in game['moves']['game_specialnend']['effects'] if e['cmd'] == 'EFFECT']


@needs_disc
@needs_rip
def test_the_lids_of_a_blink_are_drawn_from_the_games_own_blinking_faces():
    import io
    import zipfile
    with zipfile.ZipFile(RIP) as z:
        files = {n: z.read(n) for n in z.namelist() if not n.endswith('/')}
    name = next(n for n in files if n.lower().endswith('.dae'))
    folder = name.rsplit('/', 1)[0] + '/' if '/' in name else ''
    pictures = {n[len(folder):]: Image.open(io.BytesIO(b)) for n, b in files.items() if n.startswith(folder) and n.lower().endswith('.png')}
    lids = model.lids(files[name].decode('utf-8'), pictures, model.parts(ROOT, 'ike'), (64, 64))
    cover = {state: float((np.asarray(image)[..., 3] > 0).mean()) for state, image in lids.items()}
    # shut covers more of the eye than half shut, and neither covers nothing
    assert set(cover) == {'half', 'closed'} and 0.05 < cover['half'] < cover['closed']
