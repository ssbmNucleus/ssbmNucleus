"""Rivals of Aether 2, an Unreal Engine 5 game, carried on the fighter's own skeleton by writing it out in Ultimate's
shapes first (`echo_rivals2`, `fighter_port/source_game.py`). Its moves are WINDOWS (stretches of frames, each
naming the next), not scripts: what is read from them is tested here on small hand-made attacks.

The last test reads the game itself and runs only when RIVALS2 names the game's install folder (and the reader's
uetool can be built: dotnet and the NuGet cache)."""
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from echo_rivals2 import gamedata

HARNESS = Path(__file__).resolve().parents[2] / 'tools' / 'fighterport' / 'fighter_port' / 'harness'


def win(name, frames, nxt='', **more):
    return dict({'StringTableKey': name, 'WindowLengthFrames': frames, 'NextWindowStringTableKey': nxt, 'IasaFrame': -1,
                 'AnimationStartFrame': 0, 'AnimationLengthFrames': frames}, **more)


CHARGE = {'WindowCancelType': 'ERivalsWindowCancelType::StrongReleased', 'PostCancelWindowStringTableKey': 'Active'}
NSPECIAL = {'Windows': [win('Startup', 1, 'Charging'), win('Charging', 35, 'Charged Active'), win('Charged Active', 3, 'Charged Recovery'),
                        win('Charged Recovery', 24), win('Uncharged Active', 2, 'Uncharged Recovery'), win('Uncharged Recovery', 21)]}
USPECIAL = {'Windows': [win('Startup', 16, 'Travel Active'), win('Travel Active', 24, 'Recovery'),
                        win('Recovery', 25, 'Special Fall'), win('Special Fall', 1, 'Special Fall'), win('Special Land', 20)]}
DIVE = {'Windows': [win('Startup', 22, 'Active Loop'), win('Active Loop', 7, 'Active Loop')]}


def test_a_moves_path_runs_along_next_and_stops_at_a_loop_another_part_and_melees_own_states():
    assert [w['StringTableKey'] for w in gamedata.path_from(NSPECIAL, 'Startup')] == [
        'Startup', 'Charging', 'Charged Active', 'Charged Recovery']
    # a part reached only by letting the button go starts at its own window
    assert [w['StringTableKey'] for w in gamedata.path_from(NSPECIAL, 'Uncharged Active')] == ['Uncharged Active', 'Uncharged Recovery']
    # the helpless fall and its landing are Melee's own states, not the move's
    assert [w['StringTableKey'] for w in gamedata.path_from(USPECIAL, 'Startup')] == ['Startup', 'Travel Active', 'Recovery']
    # a loop is kept once; a window another part starts at ends the path that reaches it
    assert [w['StringTableKey'] for w in gamedata.path_from(DIVE, 'Startup')] == ['Startup', 'Active Loop']
    assert [w['StringTableKey'] for w in gamedata.path_from(DIVE, 'Startup', stops={'Active Loop'})] == ['Startup']


def test_a_part_counts_its_frames_from_one_and_a_strongs_charge_window_becomes_its_charge_frame():
    part = gamedata.Part(NSPECIAL, gamedata.path_from(NSPECIAL, 'Startup'), 'd00specialn')
    assert [(s, w['StringTableKey']) for s, w in part.windows] == [(1, 'Startup'), (2, 'Charging'), (37, 'Charged Active'),
                                                                    (40, 'Charged Recovery')]
    assert part.total == 63 and part.charge is None and len(part.clip_frames()) == 64
    strong = {'Windows': [win('Startup', 5, 'Charge'), win('Charge', 1, 'Charge', WindowCancels=[CHARGE]), win('Active', 4)]}
    strong['Windows'][1]['NextWindowStringTableKey'] = 'Active'
    part = gamedata.Part(strong, gamedata.path_from(strong, 'Startup'), 'c03attacks4s')
    assert part.charge == 6 and [s for s, _w in part.windows] == [1, 6] and part.total == 9


def test_rivals_knockback_is_carried_as_a_straight_line_in_the_percent():
    # (a jab: base 4, no scaling -> Melee's jab knockback; the knockback at 0% is the same either way)
    assert gamedata.melee_kb(4.0, 0.0, 3.0) == (24.0, 0.0)
    bkb, kbg = gamedata.melee_kb(8.0, 0.9, 16.0)
    assert kbg > 0 and abs((bkb + 0.18 * kbg) - gamedata.KB_UNIT * 8.0) < 0.2
    assert gamedata.angle_of(362) == gamedata.SPECIAL_ANGLE and gamedata.angle_of(45) == 45.0


def test_a_thing_a_move_makes_is_on_its_windows_frame_at_its_offset_in_melee_units():
    att = {'ArticleCreationData': [
        {'ArticleData': {'ObjectPath': '/Game/Characters/Zetterburn/Attacks/Articles/ART_Zet_Fireball.ART_Zet_Fireball_C'},
         'CreationWindowStringTableKey': 'Recovery', 'CreationWindowFrame': 0, 'InitialOffsetFromOwner': {'X': 110.0, 'Y': 70.0}},
        {'ArticleData': {'ObjectPath': '/Game/X/ART_Zet_FlamePuddle.ART_Zet_FlamePuddle_C'}, 'CreationWindowStringTableKey': ''}]}
    part = gamedata.Part(att, [win('Startup', 15, 'Active'), win('Active', 1, 'Recovery'), win('Recovery', 30)], 'd01specials')
    made = gamedata.made_articles(att, part)
    assert made[0]['id'] == 'fireball' and made[0]['real'] == 17 and made[0]['window'] == 'Recovery'
    assert made[0]['offset'] == pytest.approx([110.0 * gamedata.tc.MELEE_PER_CM, 70.0 * gamedata.tc.MELEE_PER_CM])
    assert made[1]['id'] == 'flamepuddle' and made[1]['real'] is None
    assert made[1]['trigger'] == 'compiled' and made[0]['trigger'] == 'window'
    assert made[1]['source_creation'] == att['ArticleCreationData'][1]
    # A later conditional path retains the declaration, not an invented frame-one spawn.
    branch = gamedata.Part(att, [win('Recovery', 30)], 'd04branch_test')
    later = gamedata.made_articles(att, branch)
    assert later[0]['real'] == 1 and later[0]['trigger'] == 'window'
    assert later[1]['real'] is None and later[1]['trigger'] == 'compiled'


class FakePak:
    def __init__(self, defaults):
        self.defaults = defaults

    def default(self, pkg):
        return self.defaults[pkg]


def test_an_articles_one_hitbox_is_read_from_its_lists_and_a_puddles_hitbox_with_no_numbers_is_harmless():
    fire = {'Windows': [{'StringTableKey': 'Active', 'WindowLengthFrames': 30, 'VelocityData': [{'Velocity': {'X': 30.0, 'Y': 0.0}}]},
                        {'StringTableKey': 'Destroy', 'WindowLengthFrames': 10}],
            'HitboxAttributes': [{'Name': 'Fireball', 'Radius': 30.0, 'OnHitPropertiesName': 'Fireball KB'}],
            'HitboxOnHitProperties': [{'Name': 'Fireball KB', 'Damage': 2, 'BaseKnockback': 6.0, 'KnockbackScaling': 0.1,
                                       'KnockbackAngle': 50, 'AdvancedOnHitProperties': {'SpecialEffect': 'ERivalsHitboxEffect::Burn'}}],
            'GroundCollisionResponse': 'EArticleCollisionResponse::Destroy', 'bIsProjectile': True}
    puddle = {'Windows': [{'StringTableKey': 'Active', 'WindowLengthFrames': 300}], 'ArticleClass': {'ObjectName': "Class'FlamePuddle'"},
              'HitboxAttributes': [{'Name': 'Flame Puddle', 'Radius': 40.0, 'OnHitPropertiesName': 'None'}]}
    rd = type('R', (), {'unit': 0.1})()
    got = gamedata.article(FakePak({'f': fire, 'p': puddle}), 'f', rd)
    assert got['life'] == 30 and got['speed'] == pytest.approx([3.0, 0.0]) and got['projectile']
    assert got['hit']['damage'] == 2.0 and got['hit']['angle'] == 50.0 and got['hit']['effect'] == 'collision_attr_fire'
    assert got['hit']['size'] == pytest.approx(3.0) and got['ends']['GroundCollisionResponse'] == 'Destroy'
    got = gamedata.article(FakePak({'f': fire, 'p': puddle}), 'p', rd)
    assert got['hit'] is None and got['harmless_hitbox'] and got['hit_size_cm'] == 40.0 and got['class'] == "Class'FlamePuddle'"


def test_a_speed_is_carried_in_melee_units_and_a_multiplied_one_stays_a_factor():
    att = {'Windows': [win('Travel Active', 24, 'Recovery', VelocityData=[
        {'Velocity': {'X': 45.0, 'Y': -1.05}, 'HorizontalVelocityType': 'E::None', 'VerticalVelocityType': 'E::None'}]),
        win('Recovery', 25, '', VelocityData=[{'Velocity': {'X': 0.3, 'Y': 0.3}, 'HorizontalVelocityType': 'E::MultiplyVelocity',
                                               'VerticalVelocityType': 'E::MultiplyVelocity'}])]}
    part = gamedata.Part(att, gamedata.path_from(att, 'Travel Active'), 'd02specialhi')
    entry = gamedata.entry_of(None, att, part, None, 'zetterburn', 'Uspecial')
    fly, keep = entry['momentum']
    assert (fly['x'], fly['y']) == pytest.approx((45.0 * gamedata.tc.MELEE_PER_CM, -1.05 * gamedata.tc.MELEE_PER_CM))
    assert (keep['x'], keep['y'], keep['x_kind']) == (0.3, 0.3, 'MultiplyVelocity')
    assert entry['windows'] == [[1, 'Travel Active', 24], [25, 'Recovery', 25]]


def test_a_moves_time_keys_stop_the_frame_before_he_may_act_and_a_specials_clip_is_whole():
    att = {'Windows': [win('Startup', 5, 'Active'), win('Active', 3, 'Recovery'), win('Recovery', 20, '', IasaFrame=10)]}
    part = gamedata.Part(att, gamedata.path_from(att, 'Startup'), 'c00attack11')
    entry = gamedata.entry_of(None, att, part, None, 'zetterburn', 'Jab')
    assert entry['cancel_frame_real'] == 19 and entry['time_keys'] == [[0, 0.0], [18, 18.0]]
    part = gamedata.Part(att, gamedata.path_from(att, 'Startup'), 'd01specials')
    assert gamedata.entry_of(None, att, part, None, 'zetterburn', 'Fspecial')['time_keys'] == [[0, 0.0], [28, 28.0]]


def test_a_moves_sound_is_its_tables_event_and_the_event_tables_samples_never_a_name_guess():
    """A move's SoundName -> the fighter's sound table (SFX_<F>, then SFX_Universal) -> its FMOD event (the asset
    path writes `_` for the event path's spaces) -> the banks' event table -> its samples, the Default skin's first.
    Matched by name, the first build gave the plain swipes a sample of another set (`sfx_swipe_weak1` for the
    event's `snd_char_atk_swipe_weak_01`) and two voice events stand-ins."""
    from echo_rivals2 import sounds
    fighter_table = sounds.table([{'Properties': {'SoundEffectData': [
        {'Key': 'Burn VO', 'Value': {'SoundEffect': {'AssetPathName': '/Game/FMOD/Events/VO/ZetterburnVO/vo_char_zetter_getup_special.vo_char_zetter_getup_special'}, 'bIsVoiceLine': True, 'SkinOverrideNames': []}},
        {'Key': 'Land', 'Value': {'SoundEffect': {'AssetPathName': '/Game/FMOD/Events/SFX/Universal/General_Movement/snd_movement_land_medium.snd_movement_land_medium'}, 'bIsVoiceLine': False,
                                  'SkinOverrideNames': [{'Key': 'Mecha', 'Value': 'Land Mech'}]}}]}}])
    shared = sounds.table([{'Properties': {'SoundEffectData': [
        {'Key': 'Swipe Weak', 'Value': {'SoundEffect': {'AssetPathName': '/Game/FMOD/Events/SFX/Universal/Basic_Swipes/Normal/snd_swipe_weak.snd_swipe_weak'}, 'bIsVoiceLine': False}}]}}])
    evs = {sounds.event_key(k): dict(v, event=k) for k, v in {
        'event:/VO/ZetterburnVO/vo_char_zetter_getup_special': {'bank': 'VO', 'samples': ['vo_char_zetter_getup_special-001', 'vo_char_zetter_getup_special-001_mech']},
        'event:/SFX/Universal/Basic Swipes/Normal/snd_swipe_weak': {'bank': 'Universal/Basic_Swipes', 'samples': ['snd_char_atk_swipe_weak_01', 'snd_char_atk_swipe_weak_02']},
    }.items()}
    ev, samples = sounds.resolve([fighter_table, shared], evs, 'Swipe Weak')
    assert ev['bank'] == 'Universal/Basic_Swipes' and samples[0] == 'snd_char_atk_swipe_weak_01'
    ev, samples = sounds.resolve([fighter_table, shared], evs, 'Burn VO')
    assert ev['voice'] and samples == ['vo_char_zetter_getup_special-001']
    assert sounds.resolve([fighter_table, shared], evs, 'Land')[0] is None      # its event is in no bank read: said
    assert fighter_table['Land']['skins'] == {'Mecha': 'Land Mech'}
    assert sounds.variants(['a_mech', 'b_dandelion']) == ['a_mech', 'b_dandelion']   # a skin's alone stays
    assert all(w.startswith(('vc_{f}_', 'se_{f}_')) for _key, _pick, words in sounds.ALSO for w in words)


def test_a_word_the_donors_table_takes_in_number_order_is_given_with_its_number():
    """voice.DONOR's `+vc_{f}_attack` matches vc_<f>_attack01.. only: an unnumbered word is never found (the
    first build's nine attack grunts were silent for it)."""
    import re
    from echo_rivals2 import sounds
    from fighter_port import voice
    numbered = {t[1:] for _s, tries in voice.DONOR['Marth']['roles'] for t in tries if t.startswith('+')}
    for _key, _pick, words in sounds.ALSO:
        for w in words:
            assert w not in numbered, f'{w} needs its number'
            stem = re.sub(r'\d+$', '', w)
            if stem in numbered:
                assert re.fullmatch(re.escape(stem) + r'\d+', w)


def test_a_written_game_with_no_identity_folder_keeps_the_donors(tmp_path, capsys):
    sys.path.insert(0, str(HARNESS))
    spec = importlib.util.spec_from_file_location('own_identity', HARNESS / 'own_identity.py')
    identity = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(identity)
    folder = tmp_path / 'root' / 'gamedata' / 'fighter' / 'zetterburn'
    folder.mkdir(parents=True)
    (folder / 'game.json').write_text(json.dumps({'moves': {}}), 'utf-8')
    pytest.importorskip('core.config')                  # (the app's own: the script reads its tools' places there)
    assert identity.main([str(tmp_path / 'work'), 'zetterburn', str(tmp_path / 'root')]) == 0
    assert "the donor's series emblem and victory fanfare stay" in capsys.readouterr().out
    assert not (tmp_path / 'work' / 'package' / 'series.json').exists()


def _tone(path, seconds, channels):
    import wave
    import numpy as np
    pcm = (np.sin(np.arange(int(48000 * seconds)) / 9.0) * 8000).astype('<i2')
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(np.repeat(pcm, channels).tobytes())
    return path


def test_his_emblem_fanfare_and_name_call_are_the_ones_his_character_data_names(tmp_path, monkeypatch):
    """Char_<Short> names all three: its element's emblem, its arcade data's VictoryJingle event and its
    AnnouncerLine event; the event table gives each event's sample (no name is guessed), the fanfare is taken from
    the fighter's own bank when it holds it (the Music bank is never unpacked), and the port's announcer reads the
    call the reader wrote."""
    from echo_rivals2 import identity, sounds
    from fighter_port import source_game, voice
    media = pytest.importorskip('core.media_tools')
    ffmpeg = media.get_ffmpeg()
    if not ffmpeg:
        pytest.skip('no ffmpeg')
    from PIL import Image
    char = {'RivalsElement': 'ERivalsElement::Fire',
            'ArcadeModeData': {'ObjectPath': 'Rivals2/Content/Characters/Zetterburn/AMD_Zetterburn.0'},
            'AnnouncerLine': {'ObjectPath': 'Rivals2/Content/FMOD/Events/Announcer/DefaultAnnouncer/CSS/Characters/'
                                            'vo_announcer_character_zetterburn.0'}}
    amd = {'VictoryJingle': {'AssetPathName': '/Game/FMOD/Events/Music/Arcade_Victory/ms_win_fire.ms_win_fire'}}
    table = {'event:/Music/Arcade Victory/ms_win_fire': {'bank': 'Music', 'samples': ['ms_win_fire']},
             'event:/Announcer/DefaultAnnouncer/CSS/Characters/vo_announcer_character_zetterburn':
                 {'bank': 'Announcer', 'samples': ['Announcer - 17 Zetterburn']},
             'event:/Announcer/DefaultAnnouncer/CSS/Characters/vo_announcer_character_orcane':
                 {'bank': 'Announcer', 'samples': ['Announcer - 18 Orcane']}}

    class FakePak:
        def find(self, name, under=''):
            return under + name

        def default(self, pkg):
            return char if pkg.endswith('Char_Zet') else amd if pkg.endswith('AMD_Zetterburn') else {}

        def export(self, pkgs, out, psk=True):
            got = {}
            for pkg in pkgs:
                if pkg.endswith('menus_css_emblem_fire'):
                    f = Path(out) / (pkg + '.png')
                    f.parent.mkdir(parents=True, exist_ok=True)
                    Image.new('RGBA', (64, 64), (255, 255, 255, 255)).save(f)
                    got[pkg] = [str(f)]
            return got

        def run(self, *args):
            assert args[0] == 'fmod-events'
            return json.dumps(table)

    unpacked = []
    banks = {'Character/Zetterburn/Zetterburn': {'ms_win_fire': _tone(tmp_path / 'win.wav', 0.5, 2)},
             'Announcer': {'Announcer - 17 Zetterburn': _tone(tmp_path / 'call.wav', 0.25, 1),
                           'Announcer - 18 Orcane': _tone(tmp_path / 'other.wav', 0.75, 1)},
             'Music': {}}

    def extract(bank, out):
        name = next(k for k in banks if Path(bank).as_posix().endswith(k + '.assets.bank'))
        unpacked.append(name)
        return banks[name]

    monkeypatch.setattr(sounds, 'extract', extract)
    root = tmp_path / 'root'
    made = identity.write(FakePak(), tmp_path / 'game', 'zetterburn', 'Zetterburn', 'Zet', root, ffmpeg,
                          log=lambda *a: None)
    folder = root / 'gamedata' / 'fighter' / 'zetterburn' / 'identity'
    assert 'menus_css_emblem_fire' in made['picture'] and (folder / 'series_icon.png').is_file()
    assert made['fanfare']['clip'] == 'ms_win_fire' and made['fanfare']['bank'] == 'Character/Zetterburn/Zetterburn'
    assert made['announcer']['clip'] == 'Announcer - 17 Zetterburn' and made['announcer']['seconds'] == 0.25
    assert 'Music' not in unpacked
    said = voice.announcer(root, 'zetterburn', 'rivals2')
    assert said['rate'] == 48000 and len(said['pcm']) == 12000
    assert source_game.announcer(root, 'nobody') is None and voice.announcer(root, 'nobody', 'slapcity') is None


def test_a_sample_two_events_share_plays_by_one_number_under_every_name_a_script_gives_it(tmp_path):
    """Rivals 2's Fstrong VO and Ustrong VO events play the sample Effort Heavy plays: the reader writes it once
    (sounds.json: a name and its `also`), the bank holds it once, and each name a script plays it by gets its
    number (else verify 7.1 finds the strongs' shouts silent)."""
    import io
    import zipfile
    from fighter_port import voice
    folder = tmp_path / 'gamedata' / 'fighter' / 'zetterburn' / 'sound'
    folder.mkdir(parents=True)
    (folder / 'sounds.json').write_text(json.dumps({
        'vc_zetterburn_effort_heavy': {'file': 'a.wav', 'also': ['vc_zetterburn_fstrong_vo', 'vc_zetterburn_ustrong_vo']},
        'vc_zetterburn_jump_vo': {'file': 'b.wav', 'also': []}}), 'utf-8')
    groups = voice.aliases(tmp_path, 'zetterburn', 'rivals2')
    assert groups == [{'vc_zetterburn_effort_heavy', 'vc_zetterburn_fstrong_vo', 'vc_zetterburn_ustrong_vo'}]
    assert voice.aliases(tmp_path, 'zetterburn', 'ultimate') == []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('scripts.json', json.dumps(['SFX_v_mars_jump', 'SFX_v_mars_effort']))
    chosen = {'v_mars_effort': ('vc_zetterburn_effort_heavy', None), 'v_mars_jump': ('vc_zetterburn_jump_vo', None)}
    ids = voice.calls(buf.getvalue(), 7, chosen, groups)
    assert ids['vc_zetterburn_fstrong_vo'] == ids['vc_zetterburn_ustrong_vo'] == ids['vc_zetterburn_effort_heavy'] == 70001
    assert voice.calls(buf.getvalue(), 7, chosen) == {'vc_zetterburn_effort_heavy': 70001, 'vc_zetterburn_jump_vo': 70000}


@pytest.mark.skipif(not os.environ.get('RIVALS2') or not Path(os.environ.get('RIVALS2', '')).is_dir(),
                    reason='RIVALS2 does not name the game\'s install folder')
def test_the_games_own_neutral_special_is_read_to_its_windows(tmp_path):
    from echo_rivals2 import pak
    p = pak.Pak(os.environ['RIVALS2'], tmp_path / 'cache')
    att = p.default(p.find('ATT_Zet_Nspecial', 'Rivals2/Content/Characters/Zetterburn/Attacks/'))
    path = [w['StringTableKey'] for w in gamedata.path_from(att, att['Windows'][0]['StringTableKey'])]
    assert path[:2] == ['Startup', 'Charging'] and gamedata.windows(att)['Charging']['WindowLengthFrames'] == 35


def test_an_in_place_roll_is_given_root_travel_from_the_characters_speed():
    """Rivals 2 plays a roll's clip in place and moves him in code; Melee's roll follows the clip's root, so with
    no travel the round's roll went nowhere. The Group track is moved ahead (Unreal's X), backwards for a back roll."""
    import numpy as np
    from echo_rivals2 import transcode

    class FakeClip:
        bones = [{'name': 'Group'}, {'name': 'Root_M'}]
        frames = 30
        t = np.zeros((30, 2, 3))

    d = transcode.travel_of(30, 28.0)
    assert d[0] == 0.0 and d[10] == 0.0 and d[-1] == 28.0 * 10 and np.all(np.diff(d) >= 0)
    clip = FakeClip()
    clip.t = np.zeros((30, 2, 3))
    assert transcode.give_travel(clip, 'Roll_Backward', {'RollSpeed': 28.0}) == -280.0
    assert clip.t[-1, 0, 0] == -280.0 and not clip.t[:, 1].any()
    assert transcode.give_travel(clip, 'Spot_Dodge', {'RollSpeed': 28.0}) is None
    assert transcode.give_travel(clip, 'Roll_Forward', {}) is None


def _acl_bytes(rot_xyz, trans_const, wrap=True):
    """A two-track ACL 2.1 clip in the layout echo_rivals2/acl.py reads (one segment): track 0 all default (the
    reference pose), track 1 an animated rotation (8 bits a component) and a constant translation."""
    import struct
    import numpy as np
    rot_xyz = np.asarray(rot_xyz, float)
    ns = len(rot_xyz)
    lo, hi = rot_xyz.min(0), rot_xyz.max(0)
    ext = np.where(hi > lo, hi - lo, 1.0)
    qv = np.round((rot_xyz - lo) / ext * 255).astype(int)
    seg_off, types_off = 0x34, 0x44
    const_off = types_off + 8
    range_off = const_off + 12
    data_off = range_off + 24
    fmt = bytes([8, 0, 0, 0])                                   # rotations padded to four
    bits = ''.join(f'{v:08b}' for row in qv for v in row)
    bits += '0' * (-len(bits) % 8)
    body = struct.pack('<13I', 1, 4, 1, 0, 0, 0, 1, 0, 0xFFFFFFFF, seg_off, types_off, const_off, range_off)
    body += struct.pack('<4I', 24, 24, 0, data_off)
    body += struct.pack('<2I', 2 << 28, 1 << 28)               # track 1: rotation animated, translation constant
    body += struct.pack('<3f', *trans_const)
    body += struct.pack('<6f', *lo, *ext)                        # one rotation group of one: min x y z, extent x y z
    body += fmt + int(bits, 2).to_bytes(len(bits) // 8, 'big')
    misc = 0x3E | (0x40000000 if wrap else 0)
    head = struct.pack('<IHBBIIfI', 0xAC11AC11, 10, 0, 12, 2, ns, 60.0, misc)
    data = head + body
    return struct.pack('<II', len(data) + 8, 0) + data, qv / 255 * ext + lo


def test_an_acl_clip_is_read_from_its_own_bytes_and_written_as_cue4parse_writes_a_clip(tmp_path):
    """Rivals 2's ACL-compressed clips (38 of Zetterburn's 200: the item ones, the teeter, being grabbed) are ones
    CUE4Parse decodes only through a native library it does not ship. acl.py reads them: a default sub-track is the
    reference pose, a wrap-optimised clip gets its first sample again at the end, and the .psa has ActorXAnim's
    conventions (keys' Y negated, the root's W too), so actorx.Clip reads it as it reads CUE4Parse's own."""
    import base64
    import numpy as np
    from echo_rivals2 import acl, actorx
    xyz = [[0.0, 0.1, 0.2], [0.05, 0.12, 0.25], [0.1, 0.2, 0.3]]
    raw, quantized = _acl_bytes(xyz, (1.0, 2.0, 3.0))
    dec = acl.decode(raw)
    assert dec['wrap'] and dec['nsamples'] == 3
    assert np.isnan(dec['rot'][:, 0]).all() and np.isnan(dec['tra'][:, 0]).all()
    assert np.allclose(dec['rot'][:, 1, :3], quantized, atol=1e-6)
    assert np.allclose(np.linalg.norm(dec['rot'][:, 1], axis=-1), 1.0)
    assert np.allclose(dec['tra'][:, 1], (1.0, 2.0, 3.0))
    bones = [dict(name='Group', parent=-1, q=[0, 0, 0, 1], t=[0, 0, 0], s=[1, 1, 1]),
             dict(name='Root_M', parent=0, q=[0.0, 0.0, 0.6, 0.8], t=[0, 0, 50], s=[1, 1, 1])]
    rec = dict(clip='X/AN_Test', name='AN_Test', frames=4, seconds=3 / 60, rate_scale=1.0, additive=False,
               track_to_bone=[0, 1], bones=bones, acl=base64.b64encode(raw).decode())
    out = acl.to_psa(rec, tmp_path / 'AN_Test.psa')
    clip = actorx.Clip(str(out))
    assert clip.frames == 4 and abs(clip.rate - 80.0) < 1e-3
    q = dec['rot'][:, 1]
    mirrored = q * np.array([-1, 1, -1, 1])                     # CUE4Parse's keys as actorx reads them back
    assert np.allclose(clip.q[:3, 1], mirrored, atol=1e-6) and np.allclose(clip.q[3, 1], mirrored[0], atol=1e-6)
    assert np.allclose(clip.t[:, 1], (1.0, -2.0, 3.0))
    assert np.allclose(clip.t[:, 0], 0) and np.allclose(np.abs(clip.q[:, 0, 3]), 1)
    assert clip.bones[1]['name'] == 'Root_M' and np.allclose(clip.bones[1]['t'], (0, 0, 50))


@pytest.mark.skipif(not os.environ.get('RIVALS2') or not Path(os.environ.get('RIVALS2', '')).is_dir(),
                    reason='RIVALS2 does not name the game\'s install folder')
def test_the_item_idle_acl_clip_holds_the_idle_body_cue4parse_decodes(tmp_path):
    """Checked against the game: the item idle (ACL) and the idle (Unreal's per-track codec, decoded by CUE4Parse)
    share the body below the arms on their first frame, and the bone tables are byte for byte the same."""
    import numpy as np
    from echo_rivals2 import actorx, pak
    p = pak.Pak(os.environ['RIVALS2'], tmp_path / 'cache')
    base = 'Rivals2/Content/Characters/Zetterburn/Animation/'
    got = p.export([base + 'Movement/AN_Zet_Idle', base + 'Item/AN_Zet_Item_Idle'], tmp_path / 'out')
    assert base + 'Item/AN_Zet_Item_Idle' in p.acl_decoded and not p.failed
    a = actorx.Clip(next(f for f in got[base + 'Movement/AN_Zet_Idle'] if f.endswith('.psa')))
    b = actorx.Clip(next(f for f in got[base + 'Item/AN_Zet_Item_Idle'] if f.endswith('.psa')))
    body = [i for i, x in enumerate(a.bones) if x['name'].startswith(('Root', 'Spine', 'Hip_', 'Knee', 'Ankle', 'Neck', 'Head'))]
    turn = np.degrees(2 * np.arccos(np.clip(np.abs((a.q[0, body] * b.q[0, body]).sum(-1)), 0, 1)))
    assert turn.max() < 0.5 and np.abs(a.t[0, body] - b.t[0, body]).max() < 0.05
    ca = actorx.chunks(Path(a_path := next(f for f in got[base + 'Movement/AN_Zet_Idle'] if f.endswith('.psa'))).read_bytes())
    cb = actorx.chunks(Path(next(f for f in got[base + 'Item/AN_Zet_Item_Idle'] if f.endswith('.psa'))).read_bytes())
    assert ca['BONENAMES'] == cb['BONENAMES'], a_path


def test_default_palettes_are_discovered_per_fighter():
    from types import SimpleNamespace
    from echo_rivals2.palettes import palette_names
    names = ['Neutral', 'Blue', 'Red', 'Green', 'Black', 'Abyssal', 'Orange']
    files = [f'Characters/Ranno/Data/Palettes/{n}/PS_Ran_Default_{n}.uasset' for n in names]
    files += ['Characters/Zetterburn/PS_Zet_Default_Gold.uasset', 'PS_Ran_Default_Gold.uexp']
    pak = SimpleNamespace(files=lambda: files)
    assert palette_names(pak, 'Ran') == ['Neutral', 'Red', 'Blue', 'Green', 'Black', 'Abyssal']
    files.append('Characters/Ranno/PS_Ran_Default_Gold.uasset')
    assert palette_names(pak, 'Ran') == ['Neutral', 'Red', 'Blue', 'Green', 'Black', 'Gold']


def test_missing_default_palette_is_an_explicit_reader_error():
    from types import SimpleNamespace
    from echo_rivals2.palettes import palette_names
    with pytest.raises(ValueError, match='Neutral'):
        palette_names(SimpleNamespace(files=lambda: ['PS_Ran_Default_Red.uasset']), 'Ran')


def test_conditional_attack_branch_retains_its_own_clip_hits_and_predicate():
    condition = dict(WindowCancelType='E::CharacterSpecific1', WindowCancelFrame=1,
                     WindowCancelLengthFrames=9999, PostCancelWindowStringTableKey='Consume Active',
                     WindowCancelPrerequisite='E::HasHit', NegatePrerequisite=False, bPreseveWindowTimer=False)
    att = {'Windows': [win('Start', 2, 'Active'), win('Active', 2, 'Recovery', WindowCancels=[condition]),
                       win('Recovery', 10), win('Consume Active', 3, 'Consume Recovery', AnimationStartFrame=130),
                       win('Consume Recovery', 42, AnimationStartFrame=133, IasaFrame=28)]}
    parts = gamedata.parts_with_branches('Fstrong', att, [('main','c03attacks4s')])
    assert parts == [('main','c03attacks4s'), ('Consume Active',gamedata.branch_stem('Fstrong','Consume Active'))]
    primary = gamedata.Part(att,gamedata.path_from(att,'Start'),'c03attacks4s')
    entry = gamedata.entry_of(None,att,primary,None,'any-fighter','Fstrong')
    assert entry['windows'] == [[1,'Start',2],[3,'Active',2],[5,'Recovery',10]]
    assert entry['window_cancels'] == [dict(window='Active',first=4,last=4,condition=condition)]
    assert not entry['conditional_only']
    branch = gamedata.Part(att,gamedata.path_from(att,'Consume Active'),parts[1][1])
    followup = gamedata.entry_of(None,att,branch,None,'any-fighter','Fstrong')
    assert followup['conditional_only'] and branch.clip_frames()[0] == 130
    assert followup['end'] == 46 and followup['cancel_frame_real'] == 32
    assert followup['time_keys'][-1] == [45,45.0]  # input window never truncates conditional recovery


def test_conditional_targets_on_existing_paths_do_not_duplicate_clips_and_names_do_not_collide():
    att = {'Windows': [win('Start',2,'Active',WindowCancels=[CHARGE]), win('Active',3)]}
    assert gamedata.parts_with_branches('Move',att,[('main','d00specialn')]) == [('main','d00specialn')]
    assert gamedata.branch_stem('Move','A-B') != gamedata.branch_stem('Move','A B')
    assert gamedata.branch_stem('Move','A B') == gamedata.branch_stem('Move','A B')


def test_conditional_loop_and_unresolved_destination_are_retained_without_a_fake_exit():
    jump = dict(WindowCancelType='E::ResourceReady',PostCancelWindowStringTableKey='Loop')
    unknown = dict(WindowCancelType='E::Custom',PostCancelWindowStringTableKey='Missing')
    att = {'Windows':[win('Start',2,WindowCancels=[jump,unknown]),win('Loop',4,'Loop')]}
    parts = gamedata.parts_with_branches('Nspecial',att,[('main','d00specialn')])
    assert len(parts)==2 and parts[1][0]=='Loop'
    loop = gamedata.Part(att,gamedata.path_from(att,'Loop'),parts[1][1])
    entry = gamedata.entry_of(None,att,loop,None,'any-fighter','Nspecial')
    assert entry['path_end']=='Loop' and entry['end']==5
    primary = gamedata.Part(att,gamedata.path_from(att,'Start'),'d00specialn')
    assert gamedata.window_cancels(primary)[1]['condition']==unknown


def test_existing_angled_path_covers_its_cancel_destination():
    cancel = dict(WindowCancelType='E::AngleUp',PostCancelWindowStringTableKey='Active Up')
    att = {'Windows':[win('Start',2,'Active',WindowCancels=[cancel]),win('Active',3),win('Active Up',3)]}
    parts = [('main','c02attacks3s'),('angle: Up','c02attacks3hi')]
    assert gamedata.parts_with_branches('Ftilt',att,parts)==parts


def test_post_throw_branch_keeps_its_attack_instead_of_releasing_victim_twice():
    release = dict(ReleaseWindowStringTableKey='Active', ThrowKnockbackData=dict(Damage=0, BaseKnockback=0,
                       KnockbackScaling=0, KnockbackAngle=0))
    att = {'Windows':[win('Active',2,'Recovery'),win('Recovery',40),win('Consume',1,'Recovery')],
           'ThrowData':{'ThrowReleaseData':[release]}}
    hit = dict(first=1,damage=7,angle=45,bkb=40,kbg=60)
    branch = gamedata.Part(att,gamedata.path_from(att,'Consume'),'d04branch_throw')
    entry = dict(hitboxes=[hit],other=[])
    gamedata.throw_hits(None,att,entry,branch)
    assert entry == dict(hitboxes=[hit],other=[])
    primary = gamedata.Part(att,gamedata.path_from(att,'Active'),'e01throwf')
    entry = dict(hitboxes=[hit],other=[])
    gamedata.throw_hits(None,att,entry,primary)
    assert not entry['hitboxes']
    assert [e['cmd'] for e in entry['other']] == ['ATTACK_ABS','ATK_HIT_ABS']


def test_cancel_on_window_exit_boundary_stays_reachable():
    condition = dict(WindowCancelType='E::CharacterSpecific1',WindowCancelFrame=3,
                     WindowCancelLengthFrames=9999,PostCancelWindowStringTableKey='Consume')
    att = {'Windows':[win('Startup',9,'Active'),win('Active',3,'Recovery',WindowCancels=[condition]),
                       win('Recovery',40),win('Consume',3)]}
    part = gamedata.Part(att,gamedata.path_from(att,'Startup'),'c03attackhi4')
    cancel = gamedata.window_cancels(part)[0]
    assert (cancel['first'],cancel['last'])==(13,13)


def test_velocity_intervals_modifiers_and_raw_parameters_survive_reading():
    velocity=dict(Velocity={'X':60,'Y':0},HorizontalVelocityType='E::ConstVelocity',VerticalVelocityType='E::None',
                  ApplyVelocityOnWindowFrame=1,ApplyVelocityUntilFrame=9999,VelocityModifiers=[{'kind':'fixture'}])
    att={'Windows':[win('Start',3,VelocityData=[velocity])]}
    part=gamedata.Part(att,gamedata.path_from(att,'Start'),'c03attacks4s')
    entry=gamedata.entry_of(None,att,part,None,'any','Fstrong')
    event=entry['momentum'][0]
    assert (event['real'],event['last'])==(2,3) and event['x']==6
    assert event['modifiers']==[{'kind':'fixture'}] and event['source_velocity']==velocity



def test_jab_listener_preserves_finite_source_window_and_rejects_conditional_branches():
    c=dict(WindowCancelType='ERivalsWindowCancelType::AttackPressed',WindowCancelFrame=3,
           WindowCancelLengthFrames=2,PostCancelWindowStringTableKey='Startup 2',
           WindowCancelPrerequisite='ERivalsWindowCancelPrerequisite::None')
    att={'Windows':[win('Start',4,'Recovery'),win('Recovery',10,WindowCancels=[c])]}
    part=gamedata.Part(att,gamedata.path_from(att,'Start'),'c00attack11')
    windows=gamedata.jab_windows(part)
    assert [(w['start'],w['end'],w['neutral']) for w in windows]==[(8,10,False)]
    assert windows[0]['source_condition']==c
    c['WindowCancelPrerequisite']='ERivalsWindowCancelPrerequisite::Burn'
    assert gamedata.jab_windows(part)==[]
    c['WindowCancelPrerequisite']='ERivalsWindowCancelPrerequisite::None'
    c['NegatePrerequisite']=True
    assert gamedata.jab_windows(part)==[]
    c['NegatePrerequisite']=False;c['WindowCancelType']='ERivalsWindowCancelType::AttackHeld'
    assert gamedata.jab_windows(part)==[]


def _visual_functions():
    def local(name):
        return dict(Token='EX_LocalVariable', Variable=dict(Property=dict(Name=name)))
    end = dict(Token='EX_EndOfScript', StatementIndex=99)
    ret = dict(Token='EX_Return', Expression=dict(Token='EX_Nothing'), StatementIndex=98)
    code = [dict(Token='EX_ComputedJump', StatementIndex=0, CodeOffsetExpression=local('EntryPoint')),
            dict(Token='EX_SetArray', StatementIndex=10, AssigningProperty=local('groups'),
                 Elements=[dict(Token='EX_NameConst', Value='Clothing')]),
            dict(Token='EX_Let', StatementIndex=20, Variable=local('meshes'),
                 Expression=dict(Token='EX_VirtualFunction', Function='GetRecolorableMeshComponents', Parameters=[])),
            dict(Token='EX_FinalFunction', StatementIndex=30,
                 Function=dict(ObjectName="Function'Renderer:SetParameterFromAnimCurve'", ObjectPath='/Script/Rivals2'),
                 Parameters=[local('meshes'), local('groups'), dict(Token='EX_NameConst', Value='Visible'),
                             dict(Token='EX_NameConst', Value='ClothVisible'), dict(Token='EX_True')]), ret, end]
    tick = [dict(Token='EX_LocalFinalFunction', StatementIndex=0,
                 Function=dict(ObjectName="Function'Renderer:ExecuteUbergraph_Renderer'"),
                 Parameters=[dict(Token='EX_IntConst', Value=10)]), ret, end]
    return [dict(Name='ReceiveTick', ScriptBytecode=tick),
            dict(Name='ExecuteUbergraph_Renderer', ScriptBytecode=code)]


def test_renderer_curve_binding_follows_tick_entry_and_preserves_float_parameter():
    from echo_rivals2.visuals import tick_bindings, Unsupported
    f = _visual_functions()
    got = tick_bindings(f, {'Clothing': ['Cape', 'Tie']})
    assert len(got) == 1
    assert got[0]['slots'] == ['Cape', 'Tie']
    assert got[0]['parameter'] == 'Visible' and got[0]['curve'] == 'ClothVisible'
    assert got[0]['exclude_shield_mesh'] is True
    # A guard before the material call must not become an unconditional visibility rule.
    f[1]['ScriptBytecode'].insert(3, dict(Token='EX_JumpIfNot', StatementIndex=25))
    with pytest.raises(Unsupported, match='EX_JumpIfNot'):
        tick_bindings(f, {'Clothing': ['Cape', 'Tie']})


def test_renderer_uses_skin_inheritance_and_child_tick_override():
    from echo_rivals2.visuals import renderer
    class P:
        def find(self, _): return 'Skin'
        def default(self, _):
            return {'CharacterRendererClass': {'AssetPathName': '/Game/Child.Child_C'}}
        def props(self, pkg):
            parent = {'ObjectPath': 'Rivals2/Content/Parent.0'} if pkg.endswith('Child') else {'ObjectPath': '/Script/Rivals2'}
            groups = ['Tie'] if pkg.endswith('Child') else ['Cape']
            return [dict(Type='BlueprintGeneratedClass', SuperStruct=parent),
                    dict(Name='Default__Renderer', Properties=dict(MaterialSlotGroups=[
                        dict(Key='Clothing', Value=dict(MaterialSlotNames=groups))]))]
        def scripts(self, pkg):
            return _visual_functions() if pkg.endswith('Parent') else []
    p = P()
    got = renderer(p, 'Any')
    assert got['bindings'][0]['slots'] == ['Tie'] and not got['unresolved']
    # An overridden tick that never invokes the parent does not inherit its side effects.
    original = p.scripts
    p.scripts = lambda pkg: [dict(Name='ReceiveTick', ScriptBytecode=[
        dict(Token='EX_Return', Expression=dict(Token='EX_Nothing')), dict(Token='EX_EndOfScript')])] \
        if pkg.endswith('Child') else original(pkg)
    assert renderer(p, 'Any')['bindings'] == []


def test_pak_rejects_partial_script_decode_even_from_cache(tmp_path):
    from echo_rivals2.pak import Pak
    p = Pak.__new__(Pak)
    p.cache = tmp_path
    p.run = lambda *a: json.dumps([dict(Name='Tick', ScriptBytecode=[dict(Token='EX_Return')])])
    with pytest.raises(ValueError, match='incomplete bytecode'):
        p.scripts('Renderer')
    key = tmp_path / 'scripts' / 'Renderer.json'
    assert not key.exists()
    key.parent.mkdir(exist_ok=True)
    key.write_text(json.dumps([dict(Name='Tick', ScriptBytecode=[])]), encoding='utf-8')
    with pytest.raises(ValueError, match='incomplete bytecode'):
        p.scripts('Renderer')


def _acl_float_curves(wrap=False):
    import struct
    # Four tracks: constant 0.25, quantized 3-bit [-2,5], raw float (unaligned), 9-bit [10,12].
    # Serialized bit-rate 24 means 32 raw bits, not 24 bits. Both samples cross byte boundaries.
    sample_values = [(1, -1.5, 400), (6, 123.25, 17)]
    bits = ''.join(f'{a:03b}' + f'{struct.unpack("<I", struct.pack("<f", v))[0]:032b}' + f'{c:09b}'
                   for a, v, c in sample_values)
    bits += '0' * (-len(bits) % 8)
    body = struct.pack('<5I', 44, 20, 24, 28, 44) + bytes([0, 3, 24, 9])
    body += struct.pack('<5f', .25, -2, 7, 10, 2) + int(bits, 2).to_bytes(len(bits) // 8, 'big')
    head = struct.pack('<IHBBIIfI', 0xAC11AC11, 10, 0, 0, 4, 2, 60.0, 0x40000000 if wrap else 0)
    return struct.pack('<II', len(head) + len(body) + 8, 0) + head + body


@pytest.mark.parametrize('wrap', [False, True])
def test_acl_scalar_curves_decode_constants_quantized_and_unaligned_raw_tracks(wrap):
    import base64
    import numpy as np
    from echo_rivals2.acl import decode_scalar, curve_tracks
    raw = _acl_float_curves(wrap)
    got = decode_scalar(raw)
    expected = [[.25, -1, -1.5, 10 + 800/511], [.25, 4, 123.25, 10 + 34/511]]
    assert np.allclose(got['values'], expected, atol=1e-7)
    assert got['wrap'] is wrap
    record = dict(acl=base64.b64encode(raw).decode(), seconds=(2 if wrap else 1)/60,
                  curve_names=[dict(DisplayName=n) for n in ['Constant', 'Ramp', 'Raw', 'Angle']])
    curves = curve_tracks(record)['FloatCurves']
    assert [c['CurveName'] for c in curves] == ['Constant', 'Ramp', 'Raw', 'Angle']
    keys = curves[2]['FloatCurve']['Keys']
    assert [x['Value'] for x in keys] == ([-1.5, 123.25, -1.5] if wrap else [-1.5, 123.25])
    assert keys[-1]['Time'] == record['seconds']
    assert all(x['InterpMode'] == 'RCIM_Linear' for x in keys)


@pytest.mark.parametrize('offset,value', [(12, 9), (15, 12), (32, 43), (52, 25)])
def test_acl_scalar_unknown_layouts_fail_instead_of_making_curves(offset, value):
    from echo_rivals2.acl import decode_scalar, Unsupported
    raw = bytearray(_acl_float_curves())
    raw[offset] = value
    with pytest.raises(Unsupported):
        decode_scalar(raw)
    with pytest.raises(Unsupported):
        decode_scalar(raw[:50])


def test_curve_batch_decodes_acl_then_roundtrips_cache_without_bone_data(tmp_path):
    import base64
    from echo_rivals2.pak import Pak
    p = Pak.__new__(Pak)
    p.cache = tmp_path
    record = dict(acl=base64.b64encode(_acl_float_curves()).decode(), seconds=1/60, curves=None,
                  curve_names=[dict(DisplayName=n) for n in ['a','b','c','d']])
    calls = []
    def run(mode, batch):
        calls.append((mode, batch))
        return json.dumps({'Anim': record})
    p.run = run
    result = p.animation_curves(['Anim'])
    assert result['Anim']['curves']['FloatCurves'][2]['FloatCurve']['Keys'][1]['Value'] == 123.25
    assert result == p.animation_curves(['Anim']) and calls == [('animation-curves', 'Anim')]
