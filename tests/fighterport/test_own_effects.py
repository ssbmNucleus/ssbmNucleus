"""A fighter's own effects as Melee particle generators: the Melee side's writers against their readers and against
bytes taken from the game, the conversion's rules on small made-up emitters, and Duck Hunt's real file.

The first tests need no game files. Marth's own effect file is read from the donor zip named by PORT_DONOR_ZIP
(a Marth.zip that holds EfMsData.dat); Duck Hunt's from the dump named by ULTIMATE_DUMP.
"""
import math
import os
import struct
import zipfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from echo_ultimate import effects
from fighter_port import own_effects as oe

DUMP = os.environ.get('ULTIMATE_DUMP')
DUCK = Path(DUMP) / 'gamedata' / 'effect' / 'fighter' / 'duckhunt' / 'ef_duckhunt.eff' if DUMP else None
needs_duck = pytest.mark.skipif(not (DUCK and DUCK.exists()), reason="needs ULTIMATE_DUMP with Duck Hunt's effect file")
DONOR = os.environ.get('PORT_DONOR_ZIP')
MARTH_FILE = 'EfMsData.dat'


def has_marth():
    if not (DONOR and Path(DONOR).exists()):
        return False
    with zipfile.ZipFile(DONOR) as z:
        return MARTH_FILE in z.namelist()


needs_marth = pytest.mark.skipif(not has_marth(), reason="needs PORT_DONOR_ZIP naming a Marth.zip with EfMsData.dat")

f32 = lambda value: struct.pack('>f', value)

# The command lists of Marth's four generators, as they are in EfMsData.dat.
MARTH_COMMANDS = [
    'a53e81a53e82a53e83ff',
    '4001e83f8000008f000000000000000040900000cf00ffffffffaddf004aa7f800400001e403e503400101e403e503400001e403e503400101ff',
    '40008f000000000000000040f00000e83f800000cf0000a6ffffaddf000000c20008ff',
    '4000cf00ffffffffaddf00a300e80002ff',
]


# ---- particle commands ----

def test_marths_command_lists_decode_as_the_spec_says_and_encode_to_the_same_bytes():
    launcher, _ = oe.decode_commands(bytes.fromhex(MARTH_COMMANDS[0]))
    assert launcher == [(0xA5, [16001]), (0xA5, [16002]), (0xA5, [16003]), (0xFF, [])]
    trail, end = oe.decode_commands(bytes.fromhex(MARTH_COMMANDS[2]))
    assert end == len(bytes.fromhex(MARTH_COMMANDS[2]))
    assert trail == [(0x40, [0, 0]), (0x8F, [dict(x=0.0, y=0.0, z=7.5)]), (0xE8, [1.0]),
                     (0xCF, [0, dict(r=0, g=166, b=255, a=255)]), (0xAD, []), (0xDF, [0, dict(r=0, g=0, b=194, a=0)]),
                     (0x00, [8]), (0xFF, [])]
    flash, _ = oe.decode_commands(bytes.fromhex(MARTH_COMMANDS[3]))
    assert flash == [(0x40, [0, 0]), (0xCF, [0, dict(r=255, g=255, b=255, a=255)]), (0xAD, []),
                     (0xDF, [0, dict(r=163, g=0, b=232, a=0)]), (0x00, [2]), (0xFF, [])]
    for text in MARTH_COMMANDS:
        data = bytes.fromhex(text)
        commands, end = oe.decode_commands(data)
        assert end == len(data) and oe.encode_commands(commands) == data


def test_marths_third_generator_is_written_byte_for_byte():
    # header: Disc, texture group 2, gives off for 1 frame, particles of 8 frames, additive and at once, no pull,
    # friction 0, leaves backward at 1.5, one particle, half-width 9
    header = bytes.fromhex('0000' '0002' '0001' '0008' '00400100') + f32(0) * 2 + f32(0) * 2 + bytes.fromhex('bfc00000') \
        + f32(0) * 2 + bytes.fromhex('bf800000' '41100000') + f32(0) * 3
    assert len(header) == oe.HEADER_BYTES == 0x3C
    commands, _ = oe.decode_commands(bytes.fromhex(MARTH_COMMANDS[2]))
    block = oe.generator(commands, tex_group=2, gen_life=1, life=8, kind=oe.ADDITIVE | oe.IMMEDIATE, friction=0.0,
                         velocity=(0.0, 0.0, -1.5), random=-1.0, size=9.0)
    assert block == header + bytes.fromhex(MARTH_COMMANDS[2])
    back = oe.read_generator(block)
    assert back['length'] == len(block) and back['commands'] == commands
    assert (back['tex_group'], back['gen_life'], back['life'], back['kind']) == (2, 1, 8, 0x400100)
    assert back['velocity'] == (0.0, 0.0, -1.5) and back['random'] == -1.0 and back['size'] == 9.0


def test_waits_and_counts_take_one_byte_or_two():
    wait = lambda frames: oe.encode_commands([(oe.WAIT, [frames])])
    assert wait(8) == b'\x08' and wait(31) == b'\x1f' and wait(32) == b'\x20\x20' and wait(8191) == b'\x3f\xff'
    with pytest.raises(ValueError):
        wait(8192)
    assert oe.encode_commands([(oe.PICTURE, [0, 3])]) == b'\x40\x03'
    assert oe.encode_commands([(oe.PICTURE, [300, 2])]) == b'\x61\x2c\x02'          # the wait first, then the picture
    size = lambda count: oe.encode_commands([(oe.SIZE, [count, 1.0])])
    assert size(0) == b'\xa0\x00' + f32(1.0) and size(127) == b'\xa0\x7f' + f32(1.0)
    assert size(128) == b'\xa0\x80\x80' + f32(1.0) and size(32767) == b'\xa0\xff\xff' + f32(1.0)
    with pytest.raises(ValueError):
        size(32768)
    for data in (wait(31), wait(32), wait(8191), size(128), size(32767), b'\x61\x2c\x02'):
        assert oe.encode_commands(oe.decode_commands(data)[0]) == data


def test_axes_and_channels_are_kept_in_the_code():
    assert oe.encode_commands([(oe.ADD_POSITION, [dict(y=1.0)])]) == b'\x8a' + f32(1.0)
    assert oe.encode_commands([(0x90, [dict(z=2.0, x=1.0)])]) == b'\x95' + f32(1.0) + f32(2.0)
    assert oe.encode_commands([(oe.PRIM, [5, dict(a=128)])]) == b'\xc8\x05\x80'       # alpha alone
    assert oe.encode_commands([(0xD0, [0, dict(b=2, r=1)])]) == b'\xd5\x00\x01\x02'   # red and blue, in that order
    for data in (b'\x8a' + f32(1.0), b'\x95' + f32(1.0) + f32(2.0), b'\xc8\x05\x80', b'\xd5\x00\x01\x02'):
        assert oe.encode_commands(oe.decode_commands(data)[0]) == data


def test_every_command_goes_round():
    sample = dict(e=300, f=0.25, H=513, B=7, b=-3)
    commands = [(code, [sample[letter] for letter in layout]) for code, layout in oe.FIXED.items()
                if code not in oe.END_CODES]
    commands += [(0xE9, [0b1011, 4, [-1, 2, -3]]), (0xEA, [200, 9, 17, 33]), (0xEB, [0, 1, 5, None]),
                 (oe.WAIT, [40]), (oe.PICTURE, [0, 1]), (0x85, [dict(x=1.0, z=-2.0)]), (0x9A, [dict(y=0.5)]),
                 (0xC2, [3, dict(g=4)]), (0xFE, [])]
    data = oe.encode_commands(commands)
    back, end = oe.decode_commands(data)
    assert back == commands and end == len(data)
    # a position, velocity or colour command may be given by its base code: its dict says which numbers follow
    assert oe.encode_commands([(0x80, [dict(x=1.0, z=-2.0)]), (oe.PRIM, [3, dict(g=4)])]) == \
        oe.encode_commands([(0x85, [dict(x=1.0, z=-2.0)]), (0xC2, [3, dict(g=4)])])
    with pytest.raises(ValueError):
        oe.encode_commands([(oe.SIZE, [1.0])])                                         # an argument short


def test_reading_stops_at_the_end_command_and_waits_add_up():
    data = oe.encode_commands([(oe.WAIT, [3]), (oe.PICTURE, [4, 0]), (oe.END, [])]) + b'\x05\xff'
    commands, end = oe.decode_commands(data)
    assert commands == [(oe.WAIT, [3]), (oe.PICTURE, [4, 0]), (oe.END, [])] and end == len(data) - 2
    assert oe.waits(commands) == 7
    assert len(oe.decode_commands(data, stop_at_end=False)[0]) == 5


# ---- the particle bank ----

def test_the_particle_bank_holds_its_generators_at_multiples_of_eight():
    blocks = [oe.generator([(oe.END, [])]), None, oe.generator([(oe.WAIT, [2]), (oe.END, [])], size=3.0)]
    bank = oe.particle_bank(blocks, bank=5)
    version, number, first, count = struct.unpack_from('>HHii', bank, 0)
    assert (version, number, first, count) == (0x42, 5, 0, 3)
    offsets = struct.unpack_from('>3i', bank, 12)
    assert offsets == (0x18, 0, 0x58)                                # 12 + 3 * 4 = 24; 0x3D bytes rounded up to 0x40
    assert all(offset % 8 == 0 for offset in offsets) and len(bank) == 0x58 + 0x40
    assert bank[offsets[0]:offsets[0] + len(blocks[0])] == blocks[0]
    assert oe.read_particle_bank(bank) == blocks
    with pytest.raises(ValueError):
        oe.read_particle_bank(b'\x00\x44' + bank[2:])                # a version the game stops on


# ---- pictures ----

def picture(pixels):
    return Image.fromarray(np.asarray(pixels, dtype=np.uint8))


def test_i8_is_stored_block_by_block_and_keeps_red():
    grey = np.arange(16 * 8, dtype=np.uint8).reshape(8, 16)
    rgba = np.stack([grey, grey, grey, np.full_like(grey, 255)], axis=-1)
    data = oe.encode_image(picture(rgba), oe.I8)
    assert len(data) == oe.image_bytes(oe.I8, 16, 8) == 128
    # blocks are 8 across and 4 down: the first block is the left half of the top four rows
    assert data[:32] == bytes(grey[:4, :8].reshape(-1)) and data[32:64] == bytes(grey[:4, 8:].reshape(-1))
    assert data[64:96] == bytes(grey[4:, :8].reshape(-1))
    back = np.asarray(oe.decode_image(data, oe.I8, 16, 8))
    assert (back == np.stack([grey] * 4, axis=-1)).all()             # the console reads it as brightness and alpha


def test_ia8_stores_alpha_before_brightness():
    rgba = np.zeros((4, 4, 4), dtype=np.uint8)
    rgba[..., :3], rgba[..., 3] = 200, 100
    rgba[0, 1] = (10, 10, 10, 250)
    data = oe.encode_image(picture(rgba), oe.IA8)
    assert data[:4] == bytes([100, 200, 250, 10]) and len(data) == oe.image_bytes(oe.IA8, 4, 4) == 32
    assert (np.asarray(oe.decode_image(data, oe.IA8, 4, 4)) == rgba).all()


def test_rgb5a3_has_a_solid_form_and_a_see_through_form():
    rgba = np.zeros((4, 4, 4), dtype=np.uint8)
    rgba[0, 0] = (255, 0, 0, 255)                                    # solid: top bit, five bits a channel
    rgba[0, 1] = (255, 0, 0, 128)                                    # see-through: three bits of alpha, four a channel
    rgba[0, 2] = (0, 255, 0, 230)                                    # nearly solid is stored solid
    rgba[0, 3] = (16, 32, 255, 0)
    data = oe.encode_image(picture(rgba), oe.RGB5A3)
    assert struct.unpack_from('>4H', data, 0) == (0xFC00, 0x4F00, 0x83E0, 0x012F)
    back = np.asarray(oe.decode_image(data, oe.RGB5A3, 4, 4))
    assert tuple(back[0, 0]) == (255, 0, 0, 255) and tuple(back[0, 1]) == (255, 0, 0, 146)
    assert tuple(back[0, 2]) == (0, 255, 0, 255) and tuple(back[0, 3]) == (17, 34, 255, 0)
    # what is read back is stored again as the same bytes
    assert oe.encode_image(oe.decode_image(data, oe.RGB5A3, 4, 4), oe.RGB5A3) == data


def test_each_format_goes_round_on_a_noisy_picture():
    rng = np.random.default_rng(7)
    rgba = rng.integers(0, 256, size=(16, 24, 4), dtype=np.uint8)
    for fmt in (oe.I8, oe.IA8, oe.RGB5A3):
        data = oe.encode_image(picture(rgba), fmt)
        assert len(data) == oe.image_bytes(fmt, 24, 16)
        back = oe.decode_image(data, fmt, 24, 16)
        assert back.size == (24, 16) and oe.encode_image(back, fmt) == data
    colour = np.asarray(oe.decode_image(oe.encode_image(picture(rgba), oe.RGB5A3), oe.RGB5A3, 24, 16)).astype(int)
    assert np.abs(colour[..., :3] - rgba[..., :3]).max() <= 17      # four bits a channel at the worst
    with pytest.raises(ValueError):
        oe.encode_image(picture(rgba), 14)


def test_a_pictures_format_follows_its_colour_and_alpha():
    ramp = np.tile(np.arange(0, 256, 4, dtype=np.uint8), (8, 1))
    mask = np.stack([ramp, ramp, ramp, ramp], axis=-1)
    assert oe.picture_format(picture(mask)) == oe.I8                 # grey, alpha is the brightness
    own = mask.copy()
    own[..., 3] = 255 - ramp
    assert oe.picture_format(picture(own)) == oe.IA8                 # grey with an alpha of its own
    tinted = own.copy()
    tinted[..., 2] = 255
    assert oe.picture_format(picture(tinted)) == oe.RGB5A3
    opaque = mask.copy()
    opaque[..., 3] = 255
    assert oe.picture_format(picture(opaque)) == oe.I8               # grey with no alpha of its own: a reading
    group = oe.texture_group(picture(opaque))
    stored = np.asarray(oe.decode_image(group['images'][0], oe.I8, group['width'], group['height']))
    assert (stored[..., 3] == stored[..., 0]).all() and stored[0, -1, 3] == 252 and stored[0, 0, 3] == 0


def test_a_picture_is_cut_into_its_frames_along_each_row():
    sheet = np.zeros((64, 128, 4), dtype=np.uint8)
    sheet[..., 3] = 255
    for row in range(2):
        for column in range(4):
            sheet[row * 32:(row + 1) * 32, column * 32:(column + 1) * 32, 0] = 30 * (row * 4 + column) + 20
            sheet[row * 32:(row + 1) * 32, column * 32:(column + 1) * 32, 2] = 255        # not grey: RGB5A3
    group = oe.texture_group(picture(sheet), (4, 2))
    assert (group['format'], group['width'], group['height'], len(group['images'])) == (oe.RGB5A3, 32, 32, 8)
    reds = [int(np.asarray(oe.decode_image(data, oe.RGB5A3, 32, 32))[16, 16, 0]) for data in group['images']]
    assert reds == sorted(reds) and reds[0] < 30 and reds[7] > 220    # frame 0 is top left, frame 4 starts row two
    # a frame is stored at a power of two no larger than 64 a side, and smaller when the group would be too big
    assert oe.texture_group(picture(np.zeros((100, 300, 4), dtype=np.uint8)))['width'] == 64
    assert oe.texture_group(picture(np.zeros((100, 300, 4), dtype=np.uint8)))['height'] == 64
    big = oe.texture_group(picture(sheet.repeat(4, axis=0).repeat(4, axis=1)), (4, 2))
    assert big['width'] == 32 and 8 * oe.image_bytes(oe.RGB5A3, 32, 32) <= oe.GROUP_BYTES


def test_a_quarter_picture_is_stored_upside_down_for_the_mirror():
    quarter = np.zeros((16, 16, 4), dtype=np.uint8)
    quarter[..., 3] = 255
    quarter[12:, 12:, :3] = 255                                      # bright at the bottom right: the middle of the whole
    plain = np.asarray(oe.decode_image(oe.texture_group(picture(quarter))['images'][0], oe.I8, 16, 16))
    turned = np.asarray(oe.decode_image(oe.texture_group(picture(quarter), mirrored=True)['images'][0], oe.I8, 16, 16))
    assert plain[15, 15, 0] == 255 and plain[0, 15, 0] == 0
    assert turned[0, 15, 0] == 255 and turned[15, 15, 0] == 0        # now at the top right, where Melee's mirror meets


# ---- the texture bank ----

def two_groups():
    rng = np.random.default_rng(3)
    small = lambda fmt, w, h: bytes(rng.integers(0, 256, size=oe.image_bytes(fmt, w, h), dtype=np.uint8))
    return [dict(format=oe.I8, width=16, height=16, images=[small(oe.I8, 16, 16)]),
            dict(format=oe.RGB5A3, width=8, height=16, images=[small(oe.RGB5A3, 8, 16) for _ in range(3)])]


def test_the_texture_bank_puts_every_picture_on_a_multiple_of_32():
    groups = two_groups()
    bank = oe.texture_bank(groups)
    count, first, second = struct.unpack_from('>3I', bank, 0)
    assert (count, first, second) == (2, 0x20, 0x20 + 0x20 + 0x100)
    assert struct.unpack_from('>5IHH', bank, first) == (1, oe.I8, 0, 16, 16, 0, 0)
    assert struct.unpack_from('>I', bank, first + 0x18) == (0x40,)                   # from the bank, not from the group
    assert struct.unpack_from('>5IHH', bank, second) == (3, oe.RGB5A3, 0, 8, 16, 0, 0)
    back = oe.read_texture_bank(bank)
    assert [(g['format'], g['width'], g['height'], g['images']) for g in back] == \
        [(g['format'], g['width'], g['height'], g['images']) for g in groups]
    offsets = [offset for g in back for offset in g['offsets']]
    assert offsets == [0x40, 0x180, 0x280, 0x380] and all(offset % 32 == 0 for offset in offsets)
    assert len(bank) == 0x380 + 0x100
    with pytest.raises(ValueError):
        oe.texture_bank([dict(format=oe.I8, width=16, height=16, images=[b'\0' * 100])])
    with pytest.raises(ValueError):
        oe.texture_bank([dict(format=9, width=16, height=16, images=[b'\0' * 256])])  # a palette is not written
    # the sheet for looking at a bank: a row a group, a cell a picture
    drawn = oe.sheet(back, {0: 'first\nsecond line', 1: 'three frames'}, cell=32)
    assert drawn.mode == 'RGB' and drawn.size == (260 + 3 * 40 + 8, 2 * 40 + 8)


# ---- the effect file ----

def small_file(symbol='effTestDataTable'):
    groups = two_groups()
    blocks = [oe.generator([(oe.PICTURE, [0, 0]), (oe.WAIT, [4]), (oe.END, [])], tex_group=0, life=4),
              oe.generator([(oe.RANDOM_PICTURE, [0, 3]), (oe.WAIT, [9]), (oe.END, [])], tex_group=1, life=9, gen_life=0),
              oe.generator([(oe.WAIT, [2]), (oe.END, [])], tex_group=1, life=2)]
    behaviours = [3, 6, 0]
    return oe.effect_file(symbol, blocks, behaviours, groups), blocks, behaviours, groups


def test_the_effect_file_reads_back_as_it_was_written():
    data, blocks, behaviours, groups = small_file()
    back = oe.read_effect_file(data)
    assert back['symbol'] == 'effTestDataTable' and back['generators'] == blocks and back['behaviours'] == behaviours
    assert back['models'] == 0 and back['model_behaviours'] == []
    assert [(g['format'], g['width'], g['height'], g['images']) for g in back['groups']] == \
        [(g['format'], g['width'], g['height'], g['images']) for g in groups]


def test_the_effect_files_layout_is_the_one_the_game_and_m_ex_read():
    data, blocks, behaviours, groups = small_file()
    size, data_size, relocations, roots, references = struct.unpack_from('>5I', data, 0)
    assert size == len(data) and (relocations, roots, references) == (3, 2, 0) and data[0x14:0x20] == bytes(12)
    body = data[0x20:0x20 + data_size]
    tail = 0x20 + data_size
    assert struct.unpack_from('>3I', data, tail) == (0x00, 0x04, 0x1C)               # the only addresses to fix up
    assert struct.unpack_from('>4I', data, tail + 12) == (0x00, 0, 0x10, len('effTestDataTable') + 1)
    assert data[tail + 12 + 16:] == b'effTestDataTable\0effBehaviorTable\0'
    particles_at, textures_at = struct.unpack_from('>II', body, 0)
    # m-ex's table: no models, then how many generators and where their behaviour bytes are
    assert struct.unpack_from('>iIiI', body, 0x10) == (0, 0, 3, 0x20)
    assert list(body[0x20:0x23]) == behaviours
    assert particles_at % 8 == 0 and particles_at >= 0x23 and textures_at >= particles_at + len(oe.particle_bank(blocks))
    assert body[particles_at:particles_at + 2] == b'\x00\x42'
    assert body[textures_at:textures_at + len(oe.texture_bank(groups))] == oe.texture_bank(groups)
    # the game fixes up the addresses inside the two banks itself: the file's list names none of them
    assert all(where < particles_at for where in oe.read_dat(data)['relocations'])
    # picture data sits on a multiple of 32 bytes in the loaded file, which starts after the 0x20-byte header
    for group in oe.read_effect_file(data)['groups']:
        for offset in group['offsets']:
            assert (textures_at + offset) % 32 == 0
            assert (0x20 + textures_at + offset - 0x20) % 32 == 0
    dat = oe.read_dat(data)
    assert dat['roots'] == {'effTestDataTable': 0x00, 'effBehaviorTable': 0x10} and dat['data'] == body


def test_the_effect_file_stays_aligned_whatever_the_number_of_generators():
    groups = two_groups()
    for count in (1, 2, 31, 32, 33, 97):
        blocks = [oe.generator([(oe.WAIT, [1 + i % 5]), (oe.END, [])], life=1 + i % 5) for i in range(count)]
        data = oe.effect_file('effXxDataTable', blocks, [3] * count, groups)
        back = oe.read_effect_file(data)
        assert back['generators'] == blocks and back['behaviours'] == [3] * count
        assert back['textures_at'] % 32 == 0 and back['particles_at'] % 32 == 0
        assert all((back['textures_at'] + o) % 32 == 0 for g in back['groups'] for o in g['offsets'])


def test_the_effect_file_refuses_what_would_crash_the_game():
    groups = two_groups()
    block = oe.generator([(oe.END, [])])
    with pytest.raises(ValueError):
        oe.effect_file('effXxDataTable', [block], [3, 3], groups)                     # a behaviour too many
    with pytest.raises(ValueError):
        oe.effect_file('effXxDataTable', [], [], groups)                              # the game needs both banks
    with pytest.raises(ValueError):
        oe.effect_file('effXxDataTable', [block], [3], [])
    with pytest.raises(ValueError):
        oe.effect_file('effXxDataTable', [block, None], [3, 3], groups)               # an empty number
    with pytest.raises(ValueError):
        oe.effect_file('effXxDataTable', [oe.generator([(oe.END, [])], tex_group=2)], [3], groups)
    with pytest.raises(ValueError):                                                    # picture 1 of a group of one
        oe.effect_file('effXxDataTable', [oe.generator([(oe.PICTURE, [0, 1]), (oe.END, [])])], [3], groups)
    with pytest.raises(ValueError):                                                    # a random picture past the end
        oe.effect_file('effXxDataTable', [oe.generator([(oe.RANDOM_PICTURE, [1, 3]), (oe.END, [])], tex_group=1)], [3], groups)
    with pytest.raises(ValueError):
        oe.effect_file('effXxDataTable', [block], [8], groups)                        # there are behaviours 0 to 7


# ---- Marth's own file ----

@pytest.fixture(scope='module')
def marth():
    with zipfile.ZipFile(DONOR) as z:
        return z.read(MARTH_FILE)


@needs_marth
def test_marths_effect_file_is_read(marth):
    got = oe.read_effect_file(marth)
    assert got['symbol'] == 'effMarsDataTable' and got['models'] == 2
    assert got['behaviours'] is None and got['model_behaviours'] is None            # a vanilla file has no m-ex table
    assert (got['particles_at'], got['textures_at']) == (0x40, 0x1E0)
    assert [(g['format'], g['width'], g['height'], g['offsets']) for g in got['groups']] == [
        (oe.I8, 64, 64, [0x40]), (0, 64, 64, [0x1060, 0x1860]), (oe.I8, 64, 64, [0x2080])]
    # its picture data is on multiples of 32 in the loaded file, and nothing in its address list is inside a bank
    assert all((got['textures_at'] + o) % 32 == 0 for g in got['groups'] for o in g['offsets'])
    textures_end = got['textures_at'] + 0x3080
    assert not [w for w in oe.read_dat(marth)['relocations'] if got['particles_at'] <= w < textures_end]
    assert [g.hex()[0x3C * 2:] for g in got['generators']] == MARTH_COMMANDS


@needs_marth
def test_marths_generators_and_banks_are_written_back_the_same(marth):
    got = oe.read_effect_file(marth)
    body = oe.read_dat(marth)['data']
    keys = ('tex_group', 'gen_life', 'life', 'kind', 'gravity', 'friction', 'velocity', 'radius', 'angle', 'random',
            'size', 'shape', 'params')
    for block in got['generators']:
        parts = oe.read_generator(block)
        assert oe.encode_commands(parts['commands']) == block[oe.HEADER_BYTES:]
        assert oe.generator(parts['commands'], **{k: parts[k] for k in keys}) == block
    # the particle bank: the same starts; Marth's own bank number and first number are in its head
    particles = body[got['particles_at']:got['textures_at']]
    again = oe.particle_bank(got['generators'], bank=0x10)
    assert struct.unpack_from('>4i', again, 12) == struct.unpack_from('>4i', particles, 12) == (0x20, 0x68, 0xE0, 0x140)
    assert again[:4] == particles[:4] and struct.unpack_from('>i', particles, 4) == (16000,)
    assert oe.read_particle_bank(again) == got['generators']
    # the texture bank: the same bytes but for the unused ones after its list of groups, where Marth's file has leftovers
    textures = body[got['textures_at']:got['textures_at'] + 0x3080]
    again = oe.texture_bank(got['groups'])
    assert len(again) == 0x3080 and again[:0x10] == textures[:0x10] and again[0x20:] == textures[0x20:]


# ---- one emitter as one generator ----

def emitter(**changes):
    """A made-up emitter with every number `echo_ultimate.effects.emitter` gives: one white square, 2 across, that
    lives 10 frames, given off once, standing still."""
    base = dict(
        name='test1', colour_keys=[], alpha_keys=[dict(time=0.0, value=1.0)], colour2_keys=[],
        alpha2_keys=[dict(time=0.0, value=1.0)], size_keys=[dict(time=0.0, value=(1.0, 1.0, 1.0))],
        colour=(1.0, 1.0, 1.0, 1.0), colour2=(1.0, 1.0, 1.0, 1.0), size=(2.0, 2.0, 2.0), size_random=(0.0, 0.0, 0.0),
        life=10, life_random=0, blend='normal', textures=[], grid=(1, 1), frames='one', frame_table=[], frames_random=0,
        one_time=True, start=0, loop=60, emit_frames=1, rate=1.0, shape='point', radius=(1.0, 1.0, 1.0),
        speed=0.0, speed_along=0.0, direction=(0.0, 1.0, 0.0), spread_degrees=0.0, speed_random=0.0,
        gravity=0.0, gravity_direction=(0.0, -1.0, 0.0), drag=1.0,
        turn=(0.0, 0.0, 0.0), turn_random=(0.0, 0.0, 0.0), spin=(0.0, 0.0, 0.0), spin_random=(0.0, 0.0, 0.0), spin_keep=1.0)
    base.update(changes)
    return base


def given_off(header, frames=600):
    """How many particles a generator gives off in its first `frames` frames, by the game's own sums
    (particle.c: hsd_8039F05C sets the count it starts at, hsd_8039EE24 adds to it every frame)."""
    random, life = np.float32(header['random']), header['gen_life']
    if header['kind'] & oe.IMMEDIATE:
        count = np.float32(1.0 if random < 0 and np.float32(1.0) + random > np.float32(1.1920929e-7) else
                           0.0 if random < 0 else 0.9999999)
    else:
        count = np.float32(0.0)
    assert random < 0                                                # every generator made here gives off evenly
    total = 0
    for _ in range(frames):
        count = np.float32(count - random)
        while count >= 1:
            total, count = total + 1, np.float32(count - np.float32(1.0))
        if life:
            life -= 1
            if not life:
                break
    return total


def test_a_one_time_emitter_is_a_burst_placed_at_the_joint_plus_the_offset():
    got = oe.convert(emitter(one_time=True, emit_frames=3, rate=2.0, start=4))
    header = got['header']
    assert (header['gen_life'], header['random']) == (3, -2.0) and header['kind'] & oe.IMMEDIATE
    assert got['behaviour'] == oe.BURST_BEHAVIOUR == 3 and not got['steady'] and got['delay'] == 4
    assert given_off(header) == 6
    assert given_off(oe.convert(emitter(emit_frames=1, rate=8.0))['header']) == 8
    assert given_off(oe.convert(emitter(emit_frames=9, rate=2.5))['header']) == 22   # fractions carry over
    assert oe.read_generator(got['generator'])['gen_life'] == 3
    items = oe.script_items([(got['delay'], 7, got['behaviour'])], bone=2, offset=(1.0, 8.0, -2.5))
    assert items == [(4, dict(bone_id=2, use_common_bone_ids=0, destroy_on_state_change=0, unk1=0, gfx_id=6007, unk2=0,
                              z=256, y=2048, x=-640, range_z=0, range_y=0, range_x=0))]


def test_an_emitter_that_is_not_one_time_is_steady_and_held_by_the_joint():
    got = oe.convert(emitter(one_time=False, emit_frames=6, rate=0.5, loop=60), offset=(0.0, 3.0, 1.0),
                     emission=dict(interval=5, interval_random=0, by_distance=False))
    header = got['header']
    assert header['gen_life'] == 0 and header['random'] == pytest.approx(-0.5 / 6) and header['kind'] & oe.IMMEDIATE
    assert got['behaviour'] == oe.STEADY_BEHAVIOUR == 6 and got['steady']
    assert given_off(header, frames=126) == 11                       # one at once, then one every twelve frames
    # the game does not use the script's offset for a held generator: it is added to each particle
    assert (oe.ADD_POSITION, [dict(x=0.0, y=3.0, z=1.0)]) in got['commands']
    assert (oe.ADD_POSITION, [dict(x=0.0, y=3.0, z=1.0)]) not in oe.convert(emitter(), offset=(0.0, 3.0, 1.0))['commands']
    items = oe.script_items([(0, 4, got['behaviour'])], bone=9, offset=(1.0, 2.0, 3.0))
    assert items[0][1]['destroy_on_state_change'] == 1 and items[0][1]['gfx_id'] == 6004
    assert (items[0][1]['z'], items[0][1]['y'], items[0][1]['x']) == (0, 0, 0)
    # with no interval it gives off its rate every frame
    assert oe.convert(emitter(one_time=False, rate=1.0))['header']['random'] == -1.0


def test_frames_skipped_between_givings_off_thin_a_burst_evenly():
    two = dict(interval=1, interval_random=0, by_distance=False)
    got = oe.convert(emitter(emit_frames=3, rate=2.0), emission=two)                 # frames 0 and 2: four particles
    assert got['header']['gen_life'] == 3 and given_off(got['header']) == 4
    got = oe.convert(emitter(emit_frames=1, rate=3.0), emission=dict(interval=9, interval_random=0))
    assert (got['header']['gen_life'], got['header']['random']) == (1, -3.0)
    slow = oe.convert(emitter(emit_frames=60, rate=1.0), emission=dict(interval=19, interval_random=0))
    assert slow['header']['gen_life'] == 41 and given_off(slow['header']) == 3        # frames 0, 20 and 40


def test_the_other_reading_of_a_steady_emitter_can_be_switched_back(monkeypatch):
    monkeypatch.setattr(oe, 'INTERVAL_APPLIES', False)
    got = oe.convert(emitter(one_time=False, emit_frames=6, rate=0.5, loop=60), emission=dict(interval=5, interval_random=0))
    assert got['header']['random'] == pytest.approx(-(0.5 * 6 / 60)) and got['header']['gen_life'] == 0
    burst = oe.convert(emitter(emit_frames=3, rate=2.0), emission=dict(interval=1, interval_random=0))
    assert (burst['header']['gen_life'], burst['header']['random']) == (3, -2.0)


def test_an_emitter_that_gives_off_nothing_is_refused():
    with pytest.raises(ValueError):
        oe.convert(emitter(rate=0.0))


def test_gravity_pulls_the_way_the_emitter_says_and_is_scaled():
    falls = oe.convert(emitter(gravity=0.01, gravity_direction=(0.0, -1.0, 0.0)), scale=0.5, size=2.0)['header']
    assert falls['gravity'] == pytest.approx(0.01) and falls['kind'] & oe.GRAVITY    # Melee takes it off the upward speed
    rises = oe.convert(emitter(gravity=0.04, gravity_direction=(0.0, 1.0, 0.0)), scale=0.5)['header']
    assert rises['gravity'] == pytest.approx(-0.02) and rises['kind'] & oe.GRAVITY
    none = oe.convert(emitter(gravity=0.0))['header']
    assert none['gravity'] == 0.0 and not none['kind'] & oe.GRAVITY
    side = oe.convert(emitter(gravity=0.01, gravity_direction=(1.0, 0.0, 0.0)))
    assert not side['header']['kind'] & oe.GRAVITY and any('pull to the side' in text for text in side['dropped'])


def test_drag_is_melees_friction():
    assert oe.convert(emitter(drag=0.9))['header']['friction'] == pytest.approx(0.9)
    assert oe.convert(emitter(drag=0.9))['header']['kind'] & oe.FRICTION
    plain = oe.convert(emitter(drag=1.0))['header']
    assert plain['friction'] == 1.0 and not plain['kind'] & oe.FRICTION


def test_velocity_is_the_direction_times_the_directed_speed():
    got = oe.convert(emitter(speed_along=2.0, direction=(0.0, 0.5, 1.0), spread_degrees=30.0), scale=0.5, size=2.0)
    assert got['header']['velocity'] == pytest.approx((0.0, 1.0, 2.0))
    assert got['header']['angle'] == pytest.approx(math.radians(30.0)) and got['header']['radius'] == 0.0
    still = oe.convert(emitter(speed_along=0.0, spread_degrees=30.0))['header']
    assert still['velocity'] == (0.0, 0.0, 0.0) and still['angle'] == 0.0
    # the all-direction speed, when it is the larger, is thrown every way and the directed one is listed as dropped
    around = oe.convert(emitter(speed=1.5, speed_along=0.5, direction=(0.0, 2.0, 0.0)), scale=2.0)
    assert around['header']['velocity'] == pytest.approx((0.0, 3.0, 0.0)) and around['header']['angle'] == pytest.approx(math.pi)
    assert any('directed speed' in text for text in around['dropped'])


def test_a_random_speed_sets_each_particles_speed_within_its_range():
    got = oe.convert(emitter(speed_along=2.0, direction=(0.0, 0.0, 1.0), speed_random=25.0))
    assert (oe.RANDOM_SPEED, [pytest.approx(1.5), pytest.approx(0.5)]) in got['commands']    # 1.5 plus up to 0.5
    assert not any(code == oe.RANDOM_SPEED for code, _ in oe.convert(emitter(speed_random=25.0))['commands'])


def test_a_random_life_is_set_on_the_first_frame_and_counts_the_frame_it_runs_on():
    got = oe.convert(emitter(life=20, life_random=25))
    assert got['commands'][0] == (oe.LIFE, [16, 6])                  # 15 to 20 frames, as a new particle's life + 1
    assert got['header']['life'] == 20 and oe.waits(got['commands']) == 20
    # with a picture, the picture's command comes before it and everything else
    shown = oe.convert(emitter(life=20, life_random=25, textures=[1], colour=(1.0, 0.0, 0.0, 1.0)), images=1, mirror='both')
    assert shown['commands'][:3] == [(oe.PICTURE, [0, 0]), (oe.MIRROR_BOTH, []), (oe.LIFE, [16, 6])]
    stepped = oe.convert(emitter(life=4, life_random=50, textures=[1], grid=(2, 1), frames='loop', frame_table=[0, 1]), images=2)
    assert stepped['commands'][:2] == [(oe.PICTURE, [0, 0]), (oe.LIFE, [3, 3])]


def colours(commands, frames):
    """The prim colour a particle shows on each frame, by the game's own steps (particle.c hsd_8039930C: a command
    list runs on the frame a particle is made until its first wait, then after each wait; a colour fades over its
    count and the display mixes by what is left of it, psdisp.c getColorPrimEnv)."""
    now, target, count, left = [255] * 4, [255] * 4, 0, 0
    wait, at, shown, alive = 1, 0, [], True
    for _ in range(frames):
        if count:
            left -= 1
            if left == 0:
                now, count = list(target), 0
        wait -= 1
        while alive and wait == 0:
            code, arguments = commands[at]
            at += 1
            if code in (oe.WAIT, oe.PICTURE):
                wait = arguments[0]
            elif 0xC0 <= code < 0xD0:
                if count:
                    now = [t + (n - t) * left // count for n, t in zip(now, target)]
                count = left = arguments[0]
                target = [arguments[1].get(channel, n) for channel, n in zip('rgba', now)]
                if not count:
                    now = list(target)
            elif code == oe.END:
                alive = False
        shown.append(tuple(t + (n - t) * left // count for n, t in zip(now, target)) if count else tuple(now))
    return shown


def test_colour_and_alpha_keys_share_one_timeline_that_adds_up_to_the_life():
    got = oe.convert(emitter(life=10, colour_keys=[dict(time=0.0, value=(1.0, 1.0, 1.0)), dict(time=1.0, value=(1.0, 0.0, 0.0))],
                             alpha_keys=[dict(time=0.0, value=1.0), dict(time=0.6, value=1.0), dict(time=1.0, value=0.0)]),
                     modes=dict(colour='keys', colour2='fixed', alpha='keys', alpha2='fixed'))
    commands = got['commands']
    assert commands[-1] == (oe.END, []) and oe.waits(commands) == 10
    assert [code for code, _ in commands] == [oe.PRIM, oe.WAIT, oe.PRIM, oe.WAIT, oe.END]
    shown = colours(commands, 10)
    assert shown[0] == (255, 255, 255, 255)
    assert shown[6][3] == 255 and shown[6][1] == 102                 # green is 6/10 of the way down, alpha still full
    assert shown[8][3] == pytest.approx(127, abs=1) and shown[8][1] == 51
    assert shown[9][3] == pytest.approx(64, abs=1)
    assert oe.read_generator(got['generator'])['commands'] == oe.decode_commands(oe.encode_commands(commands))[0]


def test_a_track_that_is_not_keyed_gives_the_fixed_colour():
    keys = [dict(time=0.0, value=1.0), dict(time=1.0, value=0.0)]
    fixed = oe.convert(emitter(alpha_keys=keys, colour=(1.0, 0.5, 0.0, 0.4)),
                       modes=dict(colour='fixed', colour2='fixed', alpha='fixed', alpha2='fixed'))
    assert fixed['commands'][0] == (oe.PRIM, [0, dict(r=255, g=128, b=0, a=102)])
    assert [code for code, _ in fixed['commands']] == [oe.PRIM, oe.WAIT, oe.END]
    keyed = oe.convert(emitter(alpha_keys=keys, colour=(1.0, 0.5, 0.0, 0.4)),
                       modes=dict(colour='fixed', colour2='fixed', alpha='keys', alpha2='fixed'))
    assert colours(keyed['commands'], 10)[5] == (255, 128, 0, pytest.approx(128, abs=1))
    odd = oe.convert(emitter(), modes=dict(colour=1, colour2='fixed', alpha='fixed', alpha2='fixed'))
    assert any('not known' in text for text in odd['notes'])


def test_a_second_colour_and_second_alpha_are_listed_as_not_carried():
    keys = [dict(time=0.0, value=(1.0, 0.0, 0.0)), dict(time=1.0, value=(0.0, 0.0, 1.0))]
    got = oe.convert(emitter(colour2_keys=keys, alpha2_keys=[dict(time=0.0, value=1.0), dict(time=1.0, value=0.5)]),
                     modes=dict(colour='fixed', colour2='keys', alpha='fixed', alpha2='keys'))
    assert 'the second colour track' in got['dropped'] and 'the second alpha track' in got['dropped']
    more = oe.convert(emitter(textures=[3, 4]), tex_group=0, images=1)
    assert any('more picture' in text for text in more['dropped'])


def test_smoke_with_two_alpha_tracks_is_eaten_away_by_an_alpha_test():
    got = oe.convert(emitter(life=12, alpha_keys=[dict(time=0.0, value=0.05), dict(time=1.0, value=0.9)],
                             alpha2_keys=[dict(time=0.0, value=3.0), dict(time=1.0, value=0.5)]),
                     modes=dict(colour='fixed', colour2='fixed', alpha='keys', alpha2='keys'))
    tests = [arguments for code, arguments in got['commands'] if code == oe.ALPHA_TEST]
    assert tests and all(arguments[1] == 0x33 and arguments[3] == 255 for arguments in tests)
    assert tests[0][0] == 0 and tests[0][2] == round(0.05 * 255)     # at first nearly all of the picture is kept
    assert 'the second alpha track' not in got['dropped'] and any('eaten away' in text for text in got['notes'])
    assert oe.waits(got['commands']) == 12


def test_additive_blend_sets_melees_flag():
    assert oe.convert(emitter(blend='add'))['header']['kind'] & oe.ADDITIVE == 0x400000
    assert not oe.convert(emitter(blend='normal'))['header']['kind'] & oe.ADDITIVE


def test_the_picture_command_follows_how_the_emitter_goes_through_its_frames():
    one = oe.convert(emitter(textures=[1]), tex_group=2, images=1)
    assert one['header']['tex_group'] == 2 and one['commands'][0] == (oe.PICTURE, [0, 0])
    random = oe.convert(emitter(textures=[1], grid=(2, 1), frames='random', frames_random=2), images=2)
    assert random['commands'][0] == (oe.RANDOM_PICTURE, [0, 2])      # frame 0 or 1, by the game's own command
    assert not any(code == oe.PICTURE for code, _ in random['commands'])
    once = oe.convert(emitter(life=6, textures=[1], grid=(1, 2), frames='once', frame_table=[0, 0, 0, 0, 0, 1]), images=2)
    assert [c for c in once['commands'] if c[0] in (oe.PICTURE, oe.WAIT)] == [
        (oe.PICTURE, [0, 0]), (oe.WAIT, [5]), (oe.PICTURE, [0, 1]), (oe.WAIT, [1])]
    over = oe.convert(emitter(life=8, textures=[1], grid=(4, 1), frames='over_life', frame_table=[0, 1, 2, 3]), images=4)
    assert [c for c in over['commands'] if c[0] in (oe.PICTURE, oe.WAIT)] == [
        (oe.PICTURE, [0, 0]), (oe.WAIT, [2]), (oe.PICTURE, [0, 1]), (oe.WAIT, [2]), (oe.PICTURE, [0, 2]), (oe.WAIT, [2]),
        (oe.PICTURE, [0, 3]), (oe.WAIT, [2])]
    loop = oe.convert(emitter(life=5, textures=[1], grid=(2, 1), frames='loop', frame_table=[0, 1]), images=2)
    assert [arguments[1] for code, arguments in loop['commands'] if code == oe.PICTURE] == [0, 1, 0, 1, 0]
    plain = oe.convert(emitter())
    assert not any(code in (oe.PICTURE, oe.RANDOM_PICTURE) for code, _ in plain['commands'])
    assert any('no picture' in text for text in plain['notes'])
    both = oe.convert(emitter(textures=[1]), images=1, mirror='both')
    assert (oe.MIRROR_BOTH, []) in both['commands']


def test_melees_size_is_half_the_width_and_size_keys_become_size_commands():
    assert oe.convert(emitter(size=(4.0, 4.0, 4.0)))['header']['size'] == 2.0
    assert oe.convert(emitter(size=(4.0, 4.0, 4.0)), scale=0.5, size=3.0)['header']['size'] == 3.0
    got = oe.convert(emitter(life=10, size=(4.0, 4.0, 4.0), size_keys=[dict(time=0.0, value=(0.5, 0.5, 0.5)),
                                                                     dict(time=0.4, value=(1.0, 1.0, 1.0)),
                                                                     dict(time=1.0, value=(2.0, 2.0, 2.0))]))
    assert got['header']['size'] == 1.0
    assert [c for c in got['commands'] if c[0] in (oe.SIZE, oe.WAIT)] == [
        (oe.SIZE, [4, 2.0]), (oe.WAIT, [4]), (oe.SIZE, [6, 4.0]), (oe.WAIT, [6])]
    long = oe.convert(emitter(size=(3.0, 20.0, 3.0)))
    assert long['header']['size'] == pytest.approx(11.5 / 2) and any('longer one way' in text for text in long['dropped'])
    varies = oe.convert(emitter(size=(4.0, 4.0, 4.0), size_random=(50.0, 50.0, 50.0)))
    assert (oe.SIZE_RANDOM, [0, 1.0, 1.0]) in varies['commands']     # between half the size and all of it


def test_only_the_turn_toward_the_camera_is_carried():
    got = oe.convert(emitter(life=10, turn=(0.0, 0.0, 0.5), turn_random=(0.0, 0.0, 6.0), spin=(0.0, 0.0, 0.1)))
    assert (oe.RANDOM_TURN, [0.5, 6.0, 0]) in got['commands']
    assert (oe.SPIN, [10, pytest.approx(1.0)]) in got['commands']    # ten frames of 0.1, as one even turn
    assert not got['dropped']
    other = oe.convert(emitter(turn=(1.5, 0.0, 0.0), spin_random=(0.0, 0.0, 0.1)))
    assert any('x and y' in text for text in other['dropped']) and any('random part of its spin' in text for text in other['dropped'])


def test_a_volume_scatters_particles_in_a_box_of_its_radius():
    got = oe.convert(emitter(shape='sphere', radius=(3.0, 0.5, 2.0)), scale=0.5, size=2.0)
    assert (oe.SCATTER, [3.0, 0.5, 2.0]) in got['commands'] and any('box' in text for text in got['notes'])
    assert got['header']['radius'] == 0.0 and oe.read_generator(got['generator'])['shape'] == oe.DISC
    assert not any(code == oe.SCATTER for code, _ in oe.convert(emitter(shape='point', radius=(3.0, 3.0, 3.0)))['commands'])


def test_every_converted_list_waits_its_life_and_ends():
    for life in (1, 2, 7, 44, 300):
        got = oe.convert(emitter(life=life, life_random=30, textures=[1], grid=(2, 2), frames='loop', frame_table=[0, 1, 2, 3],
                                 colour_keys=[dict(time=0.2, value=(1.0, 0.5, 0.0)), dict(time=0.7, value=(0.0, 0.5, 1.0))],
                                 alpha_keys=[dict(time=0.0, value=0.0), dict(time=0.3, value=1.0), dict(time=1.0, value=0.0)],
                                 size_keys=[dict(time=0.0, value=(0.5, 0.5, 0.5)), dict(time=1.0, value=(2.0, 2.0, 2.0))]),
                         images=4, modes=dict(colour='keys', colour2='fixed', alpha='keys', alpha2='fixed'))
        assert oe.waits(got['commands']) == life and got['commands'][-1] == (oe.END, [])
        back = oe.read_generator(got['generator'])
        assert back['length'] == len(got['generator']) and back['life'] == life


def test_script_items_fill_the_effect_command():
    items = oe.script_items([(0, 0, 3), (2, 1, 6)], bone=1, offset=(0.0, 8.0, 2.0), destroy=True)
    assert [delay for delay, _ in items] == [0, 2] and [fields['gfx_id'] for _, fields in items] == [6000, 6001]
    subactions = pytest.importorskip('vault.echo.subactions')
    data, pointers = subactions.FighterDat.encode_script([(oe.EFFECT_COMMAND, items[0][1], None)])
    # the spec's example: effect 6000 on bone 1, removed when the move ends, at (0, 8, 2) from the joint
    assert data == bytes.fromhex('28050000' '17700000' '00000800' '02000000' '00000000') + bytes(4) and not pointers


# ---- an effect the game's script makes follow its bone (Wolf's Fire Wolf, 2026-11-13) ----

def test_a_one_time_emitter_that_follows_its_bone_is_held_and_keeps_its_end():
    got = oe.convert(emitter(one_time=True, emit_frames=3, rate=2.0), offset=(0.0, 3.0, 1.0), held=True)
    assert got['behaviour'] == oe.STEADY_BEHAVIOUR and got['held'] and not got['steady']
    assert got['header']['gen_life'] == 3 and given_off(got['header']) == 6              # its own end, as before
    assert (oe.ADD_POSITION, [dict(x=0.0, y=3.0, z=1.0)]) in got['commands']            # the place rides the joint
    plain = oe.convert(emitter(one_time=True, emit_frames=3, rate=2.0), offset=(0.0, 3.0, 1.0))
    assert plain['behaviour'] == oe.BURST_BEHAVIOUR and not plain['held']
    # a held generator with an end of its own takes the call's destroy flag; one with no end always has it
    items = oe.script_items([(0, 4, 6), (0, 5, 6)], bone=4, offset=(0.0, 3.0, 1.0), destroy=False, ends={4})
    assert [fields['destroy_on_state_change'] for _, fields in items] == [0, 1]
    assert all((fields['x'], fields['y'], fields['z']) == (0, 0, 0) for _, fields in items)
    items = oe.script_items([(0, 4, 6)], bone=4, destroy=True, ends={4})
    assert items[0][1]['destroy_on_state_change'] == 1


def test_the_calls_turn_turns_the_way_particles_fly_and_are_pulled():
    up = emitter(speed_along=1.0, direction=(0.0, 1.0, 0.0), gravity=0.1, gravity_direction=(0.0, -1.0, 0.0))
    got = oe.convert(up, turn=(90.0, 0.0, 0.0))                          # the effect's up laid ahead
    assert got['header']['velocity'] == pytest.approx((0.0, 0.0, 1.0), abs=1e-9)
    # the pull is turned too and now points behind: Melee pulls up and down only, so it is said and not carried
    assert got['header']['gravity'] == 0.0 and any('pull to the side' in d for d in got['dropped'])
    half = oe.convert(up, turn=(0.0, 0.0, 180.0))                        # upside down: it flies down and is pulled up
    assert half['header']['velocity'] == pytest.approx((0.0, -1.0, 0.0), abs=1e-9)
    assert half['header']['gravity'] == pytest.approx(-0.1)


def test_a_streak_that_flies_along_its_length_is_laid_by_its_speed():
    flame = emitter(size=(1.0, 8.0, 1.0), speed_along=0.01, direction=(0.0, -1.0, 0.0))     # flies against its picture's up
    long = oe.streak(flame)
    assert long and long[1] == 'y'
    got = oe.convert(flame, long=long, turn=(90.0, 0.0, 0.0))
    assert (oe.ALONG_SPEED, []) in got['commands']
    assert next(c for c in got['commands'] if c[0] == oe.RANDOM_TURN)[1][0] == pytest.approx(math.pi)
    # too slow for the game to read a way off: it is given the least speed
    assert np.linalg.norm(got['header']['velocity']) == pytest.approx(oe.LEAST_SPEED)
    # with its length across, a quarter turn; flying the way its picture points, no turn
    across = emitter(size=(8.0, 1.0, 1.0), speed_along=1.0, direction=(1.0, 0.0, 0.0))
    got = oe.convert(across, long=oe.streak(across))
    assert (oe.ALONG_SPEED, []) in got['commands']
    assert next(c for c in got['commands'] if c[0] == oe.RANDOM_TURN)[1][0] == pytest.approx(math.pi / 2)
    along = emitter(size=(1.0, 8.0, 1.0), speed_along=1.0, direction=(0.0, 1.0, 0.0))
    got = oe.convert(along, long=oe.streak(along))
    assert (oe.ALONG_SPEED, []) in got['commands'] and not any(c[0] == oe.RANDOM_TURN for c in got['commands'])
    # a streak that flies across its length keeps the fixed turn
    side = emitter(size=(1.0, 8.0, 1.0), speed_along=1.0, direction=(0.0, 0.0, 1.0))
    assert (oe.ALONG_SPEED, []) not in oe.convert(side, long=oe.streak(side))['commands']


def test_a_streak_laid_by_its_speed_can_be_switched_back(monkeypatch):
    monkeypatch.setattr(oe, 'LAY_ALONG_SPEED', False)
    flame = emitter(size=(1.0, 8.0, 1.0), speed_along=0.01, direction=(0.0, -1.0, 0.0))
    got = oe.convert(flame, long=oe.streak(flame), turn=(90.0, 0.0, 0.0))
    assert (oe.ALONG_SPEED, []) not in got['commands']
    assert next(c for c in got['commands'] if c[0] == oe.RANDOM_TURN)[1][0] == pytest.approx(math.pi / 2)


def test_a_fixed_alpha_of_nothing_is_drawn_by_its_second_alpha():
    # Wolf's Fire Wolf flames: a fixed alpha of 0 (never seen, read as it stood) and a second alpha of 2
    flame = emitter(colour=(0.0, 0.5, 1.0, 0.0), colour2=(1.0, 1.0, 1.0, 2.0),
                    alpha_keys=[dict(time=0.0, value=0.0), dict(time=1.0, value=1.0)])
    modes = dict(colour='fixed', colour2='fixed', alpha='fixed', alpha2='fixed')
    got = oe.convert(flame, modes=modes)
    prim = next(c for c in got['commands'] if c[0] == oe.PRIM)[1][1]
    assert prim['a'] == 255 and not any(c[0] == oe.ALPHA_TEST for c in got['commands'])
    half = oe.convert(dict(flame, colour2=(1.0, 1.0, 1.0, 0.5)), modes=modes)
    assert next(c for c in half['commands'] if c[0] == oe.PRIM)[1][1]['a'] == oe._byte(0.5)
    plain = oe.convert(dict(flame, colour=(0.0, 0.5, 1.0, 0.5)), modes=modes)
    assert next(c for c in plain['commands'] if c[0] == oe.PRIM)[1][1]['a'] == oe._byte(0.5)  # any other fixed alpha: as it was


# ---- Duck Hunt's own file ----

SCRIPT_NAMES = ['duckhunt_feather', 'duckhunt_feather_long', 'duckhunt_attack_line', 'duckhunt_atk_smoke_r',
                'duckhunt_atk_smoke_l', 'duckhunt_attack100_start', 'duckhunt_attack100', 'duckhunt_entry_smoke',
                'duckhunt_target_impact', 'duckhunt_trick_smoke', 'duckhunt_clay_trace_r', 'duckhunt_clay_trace_l',
                'duckhunt_wildegunman_light', 'duckhunt_win1_grass', 'duckhunt_final_smoke', 'duckhunt_final_muzzle',
                'duckhunt_final_can', 'duckhunt_final_hit', 'duckhunt_final_hit2', 'duckhunt_final_hit3']


@pytest.fixture(scope='module')
def plan():
    return oe.Plan(DUCK, 0.9698)


@needs_duck
def test_the_name_list_maps_the_names_duck_hunts_scripts_use_to_sets():
    names = effects.names(DUCK.read_bytes())
    assert len(names) == 50 and all(names[name] is not None for name in SCRIPT_NAMES)
    assert names['duckhunt_feather'] == 'P_DuckhuntFeather' and names['duckhunt_atk_smoke_r'] == 'P_DuckhuntAtkSmokeR'
    assert names['duckhunt_attack100_start'] == 'P_DuckhuntAttack100Start'
    assert names['duckhunt_final_muzzle'] == 'P_DuckhuntFinalMuzzleflash'              # a name need not match its set's
    sets = effects.set_names(effects.particle_data(DUCK.read_bytes()))
    assert sets[0] == 'P_DuckhuntFeather' and list(names.values()) == sets            # one name a set, in the file's order
    # a script carries the name's hash, lower case
    from echo_ultimate.gamedata.prc import hash40
    assert hash40('duckhunt_feather') >> 32 == len('duckhunt_feather')


@needs_duck
def test_duck_hunts_emission_numbers():
    v = effects.particle_data(DUCK.read_bytes())
    sets = effects.effects(v)
    assert effects.emission(v, sets['P_DuckhuntFeather'][0]['binary']) == dict(interval=5, interval_random=0, by_distance=False)
    assert effects.emission(v, sets['P_DuckhuntAttack100'][2]['binary']) == dict(interval=1, interval_random=1, by_distance=False)
    assert effects.emission(v, sets['P_DuckhuntClayTraceR'][0]['binary'])['by_distance']
    assert effects.track_modes(v, sets['P_DuckhuntAtkSmokeR'][2]['binary']) == dict(colour='fixed', colour2='keys', alpha='keys', alpha2='keys')
    assert effects.model(v, sets['P_DuckhuntFeather'][0]['binary']) is None
    assert effects.model(v, sets['P_DuckhuntAtkSmokeR'][0]['binary']) is not None
    target = sets['P_DuckhuntTarget'][1]['binary']
    assert effects.mirror(v, target) == 'both' and effects.mirror(v, sets['P_DuckhuntFeather'][0]['binary']) == 'none'


@needs_duck
def test_the_feather_set_is_two_steady_generators_held_by_the_joint(plan):
    assert plan.set_name('duckhunt_feather') == plan.set_name('P_DuckhuntFeather') == 'P_DuckhuntFeather'
    uses = plan.use('duckhunt_feather')
    assert [(delay, behaviour) for delay, _, behaviour in uses] == [(0, 6), (10, 6)]
    assert plan.use('P_DuckhuntFeather', 1.0) == uses                                 # made once for a size
    for _, number, _ in uses:
        got = oe.read_generator(plan.generators[number])
        assert got['gen_life'] == 0 and got['random'] == pytest.approx(-0.5 / 6)       # without end, one every 12 frames
        assert got['kind'] & oe.GRAVITY and got['gravity'] == pytest.approx(0.009 * 0.9698)   # feathers fall
        assert got['kind'] & oe.FRICTION and got['friction'] == pytest.approx(0.91)
        assert not got['kind'] & oe.ADDITIVE and got['size'] == pytest.approx(1.5 * 0.9698)
        assert got['life'] in (44, 40) and oe.waits(got['commands']) == got['life']
        group = plan.groups[got['tex_group']]
        assert (group['format'], group['width'], group['height'], len(group['images'])) == (oe.RGB5A3, 64, 64, 1)
    assert all(fields['destroy_on_state_change'] == 1 for _, fields in oe.script_items(uses, bone=4))
    # another size is another pair of generators on the same picture
    bigger = plan.use('duckhunt_feather', 2.0)
    assert {n for _, n, _ in bigger}.isdisjoint({n for _, n, _ in uses})
    assert oe.read_generator(plan.generators[bigger[0][1]])['tex_group'] == oe.read_generator(plan.generators[uses[0][1]])['tex_group']
    rows = plan.report()['sets']['P_DuckhuntFeather']
    assert [row['emitter'] for row in rows] == ['feather1', 'feather2'] and all(row['carried'] and row['steady'] for row in rows)


def test_a_steady_emitter_given_a_lasting_ends_by_itself():
    # a mode's aura that the fighter's code gives again while the mode lasts (Shulk's arts): it must not outlive
    # the mode, and no change of state should be needed to end it
    got = oe.convert(emitter(one_time=False, emit_frames=6, rate=0.5, loop=60), lasting=12)
    assert got['header']['gen_life'] == 12 and got['behaviour'] == oe.STEADY_BEHAVIOUR and got['steady']
    assert got['header']['random'] == oe.convert(emitter(one_time=False, emit_frames=6, rate=0.5, loop=60))['header']['random']
    assert any('12 frames' in n for n in got['notes'])
    once = oe.convert(emitter(emit_frames=3, rate=2.0), lasting=12)        # a one-time emitter keeps its own end
    assert once['header']['gen_life'] == 3


@needs_duck
def test_use_can_give_a_set_a_lasting_and_only_some_of_its_emitters():
    plan = oe.Plan(DUCK, 0.9698)
    kept = plan.use('duckhunt_feather', lasting=12)
    assert [b for _, _, b in kept] == [oe.STEADY_BEHAVIOUR] * 2
    assert all(plan.ends(n) and oe.read_generator(plan.generators[n])['gen_life'] == 12 for _, n, _ in kept)
    plain = plan.use('duckhunt_feather')                                # without: other generators, with no end
    assert {n for _, n, _ in plain}.isdisjoint({n for _, n, _ in kept}) and not any(plan.ends(n) for _, n, _ in plain)
    plan = oe.Plan(DUCK, 0.9698)
    one = plan.use('duckhunt_feather', only=('feather2',))
    assert [d for d, _, _ in one] == [10]                               # feather2 alone (it starts 10 frames in)
    rows = plan.report()['sets']['P_DuckhuntFeather']
    assert not rows[0]['generators'] and any('only part' in n for n in rows[0]['notes']) and rows[1]['generators']
    with pytest.raises(KeyError):
        plan.use('duckhunt_feather', only=('feather9',))


@needs_duck
def test_an_attack_smoke_set_is_bursts(plan):
    every = plan.use('duckhunt_atk_smoke_r', 0.7)
    rows = {row['emitter']: row for row in plan.report()['sets']['P_DuckhuntAtkSmokeR']}
    flat = {n for row in rows.values() if row.get('model') is None for n in row['generators']}
    uses = [u for u in every if u[1] in flat]
    # (its four emitters drawn on 3D shapes are flattened STAND-INS: see test_own_effect_shapes.py)
    assert len(every) == 8 and len(uses) == 4 and all(behaviour == 3 for _, _, behaviour in every)
    assert [delay for delay, _, _ in uses] == [2, 2, 1, 2]                            # each emitter's own start
    for _, number, _ in uses:
        got = oe.read_generator(plan.generators[number])
        assert 1 <= got['gen_life'] <= 3 and got['random'] <= -1.0 and got['kind'] & oe.IMMEDIATE
        assert oe.waits(got['commands']) == got['life'] and got['commands'][-1] == (oe.END, [])
    smoke = oe.read_generator(plan.generators[uses[0][1]])
    assert smoke['gravity'] < 0 and smoke['commands'][0] == (oe.RANDOM_PICTURE, [0, 2])    # it rises; one of two puffs
    assert plan.groups[smoke['tex_group']]['format'] == oe.IA8
    assert rows['impact1_b']['carried'] and 'STAND-IN' in rows['impact1_b']['stand_in'][0]
    assert rows['smoke1']['carried'] and not rows['smoke1']['steady']
    assert all(fields['destroy_on_state_change'] == 0 for _, fields in oe.script_items(uses, bone=0))


def added(commands):
    """The places a read generator's commands add to its particles' (the code carries which axes in its low bits)."""
    return [c[1][0] for c in commands if c[0] & ~0x07 == oe.ADD_POSITION]


@needs_duck
def test_a_set_that_follows_its_bone_is_held_and_kept_apart_from_the_same_set_given_off_once(plan):
    once = plan.use('duckhunt_atk_smoke_r', 0.7)
    held = plan.use('duckhunt_atk_smoke_r', 0.7, offset=(0.0, 2.0, 0.0), follow=True)
    assert all(behaviour == oe.STEADY_BEHAVIOUR for _, _, behaviour in held)
    assert {n for _, n, _ in held}.isdisjoint({n for _, n, _ in once})
    assert [delay for delay, _, _ in held] == [delay for delay, _, _ in once]            # the same timing
    for _, number, _ in held:
        assert plan.ends(number)                                                         # one-time: it keeps its end
        assert added(oe.read_generator(plan.generators[number])['commands']) == [dict(x=0.0, y=2.0, z=0.0)]
    assert plan.use('duckhunt_atk_smoke_r', 0.7, offset=(0.0, 2.0, 0.0), follow=True) == held
    assert not any(plan.ends(n) for _, n, _ in plan.use('duckhunt_feather'))           # a steady one has none


@needs_duck
def test_a_stand_in_draws_a_3d_shape_emitter_as_a_flat_picture_held_by_the_joint():
    plan = oe.Plan(DUCK, 0.9698)
    v, shape = plan.v, 'impact1_b'                                       # drawn on a 3D shape (see above)
    plan.by_hand('duckhunt_atk_smoke_r', shape)                          # the port makes its own: not flattened
    assert len(plan.use('duckhunt_atk_smoke_r', 0.7)) == 7
    smoke = next(row for row in plan.sets['P_DuckhuntAtkSmokeR'] if effects.emitter(v, row['binary'])['name'] == 'smoke1')
    picture = effects.texture_names(v)[effects.emitter(v, smoke['binary'])['textures'][0]]
    uses = plan.stand_in('duckhunt_atk_smoke_r', shape, picture, width=10.0, offset=(0.0, 1.0, 0.0))
    assert len(uses) == 1 and uses[0][2] == oe.STEADY_BEHAVIOUR
    got = oe.read_generator(plan.generators[uses[0][1]])
    # 10 across at its largest: Melee's size is half the width
    largest = max(got['size'], *[c[1][1] for c in got['commands'] if c[0] == oe.SIZE])
    assert largest == pytest.approx(5.0, rel=1e-3)
    assert got['velocity'] == (0.0, 0.0, 0.0) and added(got['commands']) == [dict(x=0.0, y=1.0, z=0.0)]
    row = next(r for r in plan.report()['sets']['P_DuckhuntAtkSmokeR'] if r['emitter'] == shape)
    assert not row['carried'] and row['stand_in'] and 'STAND-IN' in row['stand_in'][0]
    assert plan.stand_in('duckhunt_atk_smoke_r', shape, picture, width=10.0, offset=(0.0, 1.0, 0.0)) == uses
    with pytest.raises(KeyError):
        plan.stand_in('duckhunt_atk_smoke_r', shape, 'no_such_picture', width=10.0)


@needs_duck
def test_the_written_file_reads_back_as_the_plan(plan):
    plan.use('duckhunt_feather')
    plan.use('duckhunt_atk_smoke_r', 0.7)
    plan.use('duckhunt_target')
    data = plan.file('effDhDataTable')
    back = oe.read_effect_file(data)
    assert back['symbol'] == 'effDhDataTable' and back['generators'] == plan.generators
    assert back['behaviours'] == plan.behaviours and set(back['behaviours']) <= {3, 6}
    assert [(g['format'], g['width'], g['height'], g['images']) for g in back['groups']] == \
        [(g['format'], g['width'], g['height'], g['images']) for g in plan.groups]
    assert all((back['textures_at'] + o) % 32 == 0 for g in back['groups'] for o in g['offsets'])
    report = plan.report()
    assert report['bytes']['generators'] == len(plan.generators) and len(report['groups']) == len(plan.groups)
    # the gun sight: a quarter picture with no alpha of its own, stored as a mask and drawn four times
    sight = next(g for g in report['groups'] if 'target00' in g['picture'])
    assert sight['format'] == 'I8' and 'mirrored' in sight['picture']
    target = next(row for row in report['sets']['P_DuckhuntTarget'] if row['emitter'] == 'target1')
    assert (oe.MIRROR_BOTH, []) in oe.read_generator(plan.generators[target['generators'][0]])['commands']
    afterimage = next(row for row in report['sets']['P_DuckhuntTarget'] if row['emitter'] == 'target1_afterimage')
    assert not afterimage['carried']                                                   # it gives off by distance moved
    with pytest.raises(KeyError):
        plan.use('duckhunt_no_such_effect')
