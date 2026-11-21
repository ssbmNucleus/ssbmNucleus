"""fighter_port.items: a projectile's data moved into a fighter that has none, and the C text for its code."""
import importlib.util
import struct
from pathlib import Path

from fighter_port import code, items
from fighter_port.oneshot import at_frame, shot_scripts  # noqa: F401  (at_frame: same module must import cleanly)
from vault.echo.subactions import Dat

_spec = importlib.util.spec_from_file_location('weapon_files', Path(__file__).with_name('test_oneshot_weapons.py'))
files = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(files)


def fighter(with_item):
    """A fighter data file: ftData (0x4C bytes, item list at +0x48) and, optionally, one item whose
    description points at common attributes, own attributes, a state (with a script) and a model."""
    ft = bytearray(0x4C)
    if not with_item:
        return files.dat([(ft, [])], [(0, 'ftDataDonor')])
    struct.pack_into('>I', ft, 0x48, 1)
    common = bytearray(struct.pack('>4f', 0.0, 0.8, 1.0, 200.0))
    own = bytearray(struct.pack('>2f', 1.5, 75.0))
    script = bytearray(b'\x2c\x00\x00\x00' + bytes(16) + bytes(4))            # stands in for a script
    state = bytearray(struct.pack('>IIII', 7, 0, 0, 6))                      # joint animation -> 7, script -> 6
    joint = bytearray(0x40)
    model = bytearray(struct.pack('>IIII', 8, 0, 0, 0))
    desc = bytearray(struct.pack('>IIIIII', 3, 4, 0, 5, 9, 0))
    anim = bytearray(8)
    return files.dat([(ft, [0x48]), (bytearray(struct.pack('>I', 2)), [0]), (desc, [0, 4, 0xC, 0x10]), (common, []), (own, []),
                      (state, [0, 0xC]), (script, []), (anim, []), (joint, []), (model, [0])], [(0, 'ftDataTemplate')])


def test_an_item_moves_into_a_fighter_that_has_none():
    out, index, desc = items.add_item(fighter(False), fighter(True), 0, Dat)
    d = Dat(out)
    ft, listed = items.item_list(d)
    assert index == 0 and listed == [desc]
    common, own, states, model = (d.ptr(desc + o) for o in (0, 4, 0xC, 0x10))
    assert round(d.f32(common + 0xC), 1) == 200.0 and round(d.f32(own), 1) == 1.5        # the data came along
    assert d.ptr(states + 0xC) is not None and d.ptr(model) is not None                  # and what it points to
    assert [n for n, _ in d.roots] == ['ftDataDonor']
    assert bytes(d.buf[0x20:0x20 + 0x48]) == bytes(0x48)                                 # the fighter's own bytes stay put


def test_the_item_gets_its_own_numbers_and_model():
    out, _, desc = items.add_item(fighter(False), fighter(True), 0, Dat)
    out = items.set_own_attributes(out, desc, [7.9, 17.0], Dat)
    out = items.set_spin(out, desc, 0.0, Dat)
    d = Dat(out)
    assert [round(d.f32(d.ptr(desc + 4) + 4 * i), 1) for i in range(2)] == [7.9, 17.0]
    assert d.f32(d.ptr(desc) + 0xC) == 0.0
    # a model from an add-on file: the item points at it, and the old model's animation is dropped for real
    addon = files.dat([(bytes(4), [])] + [(b, p) for b, p in files.addon_file(1, shift=1)[0]],
                      [(0, 'stub'), (files.addon_file(1)[1] + 1, 'mexCostume')])
    out = items.set_model(out, desc, addon, Dat)
    d = Dat(out)
    state = d.ptr(desc + 0xC)
    assert d.ptr(state) is None and state not in d.relocs                                # null, not a pointer to offset 0
    assert d.ptr(state + 0xC) is not None                                                # the script stays
    joint = d.ptr(d.ptr(desc + 0x10))
    assert d.ptr(joint + 0x10) is not None and not d.u32(joint + 4) & 0x80               # its mesh; drawn unlit


def test_the_shots_code_names_its_states_flag_and_donor():
    shot = {'joint': 75, 'flag': 1, 'onload': 0x801364AC,
            'shots': [{'item': 0, 'states': (343, 347), 'pierce': False}, {'item': 1, 'states': (344, 348), 'pierce': True}]}
    text, provides = code.source('Marth', None, shot)
    c = text['fighter.c']
    assert provides == ['2 projectiles for the neutral special', 'sword trail data']
    assert set(text) == {'fighter.c', 'item_0.c', 'item_1.c'}
    assert 's == 343 || s == 347' in c and 'Shoot(gobj, 0, -1.00f);' in c and 's == 344 || s == 348' in c and 'Shoot(gobj, 1, -1.00f);' in c
    assert 'ftcmd_var.flag1' in c and '0x801364ac' in c and '#define SHOT_JOINT 75' in c
    assert 'MEX_IndexFighterItem(fd->kind, items[1], 1);' in c
    assert 'id->pos.X -= 2.0f * id->self_vel.X;' in c                                    # so nothing close is skipped
    assert 'OnGiveDamage(GOBJ *item) { return true; }' in text['item_0.c']               # gone when it hits
    assert 'OnGiveDamage(GOBJ *item) { return false; }' in text['item_1.c']              # goes on through
    assert c.count('void OnFrame(GOBJ *gobj)') == 1


def test_armour_and_the_ledge_catch_share_one_frame_function():
    text, provides = code.source('Marth', None, None, {'states': (369, 371), 'first': 46, 'last': 66},
                                 {'state': 368, 'first': 9, 'last': 24, 'width': 18.0, 'y': 27.2, 'height': 54.4})
    c = text['fighter.c']
    assert provides == ['armour on the down special', 'a ledge catch as far as the whip reaches', 'sword trail data']
    assert 'fd->state_id == 369 || fd->state_id == 371' in c and 'fd->state.frame + 1.0f >= 46.0f' in c and 'fd->dmg.armor = ARMOUR;' in c
    assert 'fd->state_id == 368' in c and 'cliffgrab_width = TETHER_X;' in c and 'own->cliffgrab_height' in c
    assert c.count('void OnFrame(GOBJ *gobj)') == 1 and 'ArmourFrame(fd);' in c and 'TetherFrame(fd);' in c


def test_an_items_hitbox_is_edited_where_it_is():
    from vault.echo.subactions import FighterDat
    template = fighter(True)
    d = Dat(template)
    script = d.ptr(d.ptr(items.item_list(d)[1][0] + 0xC) + 0xC)
    # Mario's fireball: its hitbox command, then the word of item-only flags, then the end
    real = bytes.fromhex('2c0000060258000000000000b486400002860023' '10fdd000' '00000000')
    d.buf[0x20 + script:0x20 + script + len(real)] = real
    out, _, desc = items.add_item(fighter(False), d.to_bytes(), 0, Dat)
    out = items.set_hitbox(out, desc, {'damage': 12, 'angle': 35, 'knockback_growth': 78, 'base_knockback': 39,
                                       'size': 359, 'element': 0}, FighterDat)
    o = Dat(out)
    at = 0x20 + o.ptr(o.ptr(desc + 0xC) + 0xC)
    assert bytes(o.buf[at + 20:at + 28]) == real[20:]                                    # the flags word is untouched
    hit = FighterDat(out).decode_script(o.ptr(o.ptr(desc + 0xC) + 0xC)).commands[0].fields
    assert (hit['damage'], hit['angle'], hit['knockback_growth'], hit['base_knockback'], hit['size']) == (12, 35, 78, 39, 359)


def test_simultaneous_item_boxes_can_share_a_hit_run_without_changing_default_multihits():
    from vault.echo import subactions as sa
    import pytest
    out, _, desc = items.add_item(fighter(False), fighter(True), 0, Dat)
    out = items.set_script(out, desc, 0, [(0, dict(id=0, group=3)), (0, dict(id=1, group=3)),
                                        (0, dict(id=2)), (0, dict(id=3))], Dat)
    d = Dat(out)
    start = 0x20 + d.ptr(d.ptr(desc + items.STATES) + items.SCRIPT)
    size = sa.COMMANDS[items.HITBOX].size + 4
    assert [sa.read_bits(d.buf[start+i*size:start+(i+1)*size], *items.GROUP) for i in range(4)] == [3, 3, 2, 3]
    for group in (-1, 8, 2.5):
        with pytest.raises(ValueError, match='group='):
            items.set_script(fighter(True), items.item_list(Dat(fighter(True)))[1][0], 0, [(0, dict(group=group))], Dat)


def test_a_shots_model_is_drawn_in_its_own_colours_from_every_side():
    class Mem:
        """Words and pointers by offset: enough of a data file for the walk."""
        def __init__(self, words, pointers):
            self.words, self.pointers = dict(words), dict(pointers)

        def u32(self, at):
            return self.words.get(at, 0)

        def ptr(self, at):
            return self.pointers.get(at)

        def set_u32(self, at, value):
            self.words[at] = value
    # a lit joint with one mesh piece, its child a joint of particles (no mesh to touch), the child's next a second mesh
    d = Mem({0x04: 0x80 | 0x8, 0x104: 0x4020 | 0x80, 0x204: 0x80, 0x44: 0x1C, 0x54: 0x80808080, 0x244: 0x4, 0x254: 0x11223344},
            {0x08: 0x100, 0x10C: 0x200, 0x10: 0x30, 0x38: 0x40, 0x4C: 0x50, 0x110: 0x999, 0x210: 0x230, 0x238: 0x240, 0x24C: 0x250})
    items.unlight(d, 0)
    assert [d.u32(j + 4) & 0x80 for j in (0, 0x100, 0x200)] == [0, 0, 0] and d.u32(4) & 0x8          # no joint asks for lights
    assert d.u32(0x44) == 0x11 and d.u32(0x244) == 0x1                                                # constant, not lit
    assert d.u32(0x54) == 0xFFFFFFFF and d.u32(0x254) == 0xFFFFFFFF                                   # in white
    assert 0x99D not in d.words                                                                       # the particles are left alone


def test_a_shot_that_crosses_the_stage_in_a_few_frames_is_drawn_as_a_beam():
    shot = {'joint': 75, 'flag': 1, 'onload': 0x80136390, 'shots': [
        {'item': 4, 'states': (343, 347), 'pierce': False},
        {'item': 5, 'states': (344, 348), 'pierce': True,
         'beam': {'speed': 26.3, 'life': 10.0, 'half': 2.1, 'colour': (255, 200, 72)}}]}
    lines, files = code.shot_source(shot)
    c = '\n'.join(lines)
    assert '#define BEAM_ITEM 5' in c and '#define BEAM_SPEED 26.3f' in c and '#define BEAM_LIFE 10.0f' in c
    # where it was let go, which way, and a count of frames, kept when that shot is let go
    assert 'if (which == BEAM_ITEM)' in c and 'beam_from[fd->ply] = spawn.pos2;' in c and 'beam_age[fd->ply] = 1;' in c
    # drawn after the fighter, in the last pass, three layers; put after the fighter's own drawing once only
    assert 'static void Beam_Draw(GOBJ *gobj, int pass)' in c and 'if (pass != 2 || !beam_age[p])' in c
    assert 'if (!beam_drawn[p] && gobj->gx_cb)' in c and c.index('static u8 beam_age[6];') < c.index('void OnLoad(') < c.index('static void Shoot(')
    assert 'beam_age[fd->ply] = 0;' in c.split('void OnLoad')[1].split('}')[0]
    # the colour's roots (the routine multiplies a colour by itself): gold
    assert 'GXColor c[3] = {{255, 226, 135, 185}, {255, 241, 204, 235}, {255, 255, 244, 255}};' in c
    text, provides = code.source('Marth', None, shot)
    assert 'BeamFrame(fd, gobj);' in text['fighter.c'] and any('beam of light' in x for x in provides)
    plain, _ = code.shot_source(dict(shot, shots=shot['shots'][:1]))
    assert 'BEAM' not in '\n'.join(plain)
