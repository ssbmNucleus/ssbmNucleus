"""Ultimate's own recolors on a ported costume, the texture reader behind them, and the
trail / swing sound / voice commands added to a written move script."""
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from echo_ultimate import nutexb
from echo_ultimate.gamedata import names
from fighter_port import recolors
from fighter_port.oneshot import dress


def swizzle(rows_data: bytes, columns: int, rows: int, unit: int) -> bytes:
    """The inverse of nutexb.unswizzle, written the slow obvious way."""
    stack = nutexb._stack(rows)
    wide = columns * unit
    tiles = -(-wide // 64)
    out = bytearray(512 * stack * tiles * (-(-rows // (8 * stack))))
    for y in range(rows):
        for x in range(0, wide, unit):
            at = ((y // (8 * stack)) * 512 * stack * tiles + (y % (8 * stack) // 8) * 512 + (x // 64) * 512 * stack
                  + (x % 64 // 32) * 256 + (y % 8 // 2) * 64 + (x % 32 // 16) * 32 + (y % 2) * 16 + x % 16)
            out[at:at + unit] = rows_data[y * wide + x:y * wide + x + unit]
    return bytes(out)


@pytest.mark.parametrize('columns,rows,unit', [(16, 16, 16), (384, 256, 16), (20, 12, 8), (64, 64, 4)])
def test_block_linear_data_is_put_back_in_rows(columns, rows, unit):
    plain = bytes(np.random.default_rng(1).integers(0, 256, columns * rows * unit, dtype=np.uint8))
    assert nutexb.unswizzle(swizzle(plain, columns, rows, unit), columns, rows, unit) == plain


def test_a_game_texture_reads_like_its_known_good_copy():
    dump, rip = os.environ.get('ULTIMATE_DUMP'), os.environ.get('BYLETH_RIP_TEXTURES')
    if not dump or not rip:
        pytest.skip('needs ULTIMATE_DUMP and BYLETH_RIP_TEXTURES')
    image, head = nutexb.read(Path(dump) / 'gamedata/fighter/master/model/body/c00/def_master_001_col.nutexb')
    assert (head['width'], head['height']) == (1536, 1024)
    assert np.array_equal(np.asarray(image.convert('RGB')), np.asarray(Image.open(Path(rip) / 'def_master_001_col.png').convert('RGB')))


def picture(seed, size=(64, 64)):
    pixels = np.random.default_rng(seed).integers(0, 256, (size[1], size[0], 4), dtype=np.uint8)
    pixels[..., 3] = 255                                # opaque: a see-through picture resizes differently
    return Image.fromarray(pixels, 'RGBA')


def test_costume_textures_are_matched_to_their_sources_by_looking(tmp_path):
    base = {'cloth_col': picture(1), 'skin_col': picture(2), 'hair_col': picture(3, (128, 64))}
    base['cloth_col'].resize((32, 32), Image.LANCZOS).save(tmp_path / 'tex_4.png')      # resized
    base['hair_col'].resize((32, 32), Image.LANCZOS).save(tmp_path / 'tex_7.png')       # resized out of shape
    Image.new('RGBA', (8, 8)).save(tmp_path / 'tex_0.png')                              # a placeholder
    Image.new('RGBA', (32, 32), (90, 90, 90, 255)).save(tmp_path / 'tex_1.png')         # one flat colour
    picture(9, (32, 32)).save(tmp_path / 'tex_2.png')                                   # something else entirely
    assert recolors.match(sorted(tmp_path.glob('tex_*.png')), base) == {4: 'cloth_col', 7: 'hair_col'}


def test_only_the_textures_that_differ_are_replaced(tmp_path):
    base = {'cloth_col': picture(1), 'skin_col': picture(2)}
    other = {'cloth_col': picture(5), 'skin_col': base['skin_col'].copy()}
    assert recolors.changed(base, other) == ['cloth_col']
    costume = tmp_path / 'base.dat'
    costume.write_bytes(b'base')
    calls = []

    def run(args, output):
        calls.append(args[4])
        Path(output).write_bytes(b'step')

    done = recolors.recolor(run, costume, 'node', {4: ('cloth_col', (32, 32)), 6: ('skin_col', (32, 32))},
                            base, other, tmp_path / 'out.dat', tmp_path / 'work')
    assert done == ['cloth_col'] and calls == [4] and (tmp_path / 'out.dat').read_bytes() == b'step'
    assert Image.open(tmp_path / 'work' / 'out-4.png').size == (32, 32)


def test_names_are_found_in_a_bank_files_text(tmp_path):
    f = tmp_path / 'bank.bin'
    f.write_bytes(b'\x00\x01se_master_swing_s\x00\xff\xfeSYS_Smash_Flash\x00ab\x00')
    assert names.labels_in(f) == {'se_master_swing_s', 'sys_smash_flash'}


TRAIL_ON, TRAIL_OFF = (49, {'render_status': 0}, None), (49, {'render_status': 255}, None)
CUES = {'trail_on': TRAIL_ON, 'trail_off': TRAIL_OFF, 'voice': (18, {'value': 0}, None),
        'swing': (17, {'sfx_id': 160}, None), 'swings': {'AttackS4': [(17, {'sfx_id': 158}, None)]}}


def test_a_written_move_gets_its_trail_sound_and_voice_on_the_games_frames():
    script = [(2, {'frame': 13}, None), (11, {}, None), (2, {'frame': 16}, None), (16, {}, None), (0, {}, None)]
    move = {'effects': [{'cmd': 'AFTER_IMAGE4_ON_arg29', 'real': 11, 'name': 'tex'}, {'cmd': 'AFTER_IMAGE_OFF', 'real': 18, 'name': None},
                        {'cmd': 'EFFECT', 'real': 12, 'name': 'sys_smash_flash'}],
            'sounds': [{'cmd': 'PLAY_SE', 'real': 12, 'name': 'se_master_swing_l'}, {'cmd': 'PLAY_SE', 'real': 9, 'name': 'vc_master_attack05'},
                       {'cmd': 'PLAY_SE', 'real': 3, 'name': 'se_master_cloth_m'}, {'cmd': 'STOP_SE', 'real': 6, 'name': 'se_common_smash_start_02'}]}
    items, added = dress(script, move, 40, CUES, 'AttackS4', 'master')
    assert added == ['trail 11-18', 'swing 12', 'voice 9']
    flat = [(c, f.get('frame', f.get('sfx_id', f.get('render_status')))) for c, f, _ in items]
    assert flat == [(2, 9), (18, None), (2, 11), (49, 0), (2, 12), (17, 158), (2, 13), (11, None), (2, 16), (16, None),
                    (2, 18), (49, 255), (0, None)]
    plain, nothing = dress(script, {'effects': [], 'sounds': []}, 40, CUES, 'AttackS4', 'master')
    assert plain == script and nothing == []
    other, added = dress(script, move, 40, CUES, 'AttackHi3', 'master')                 # no sound of its own: the donor's usual
    assert (17, {'sfx_id': 160}, None) in other


def test_a_joined_clips_parts_know_where_they_start():
    from fighter_port.oneshot import cut_keys, part_starts
    keys = [[0, 0.0], [3, 10.0], [46, 53.0]]
    assert cut_keys(keys, 23.0) == [[0, 0.0], [3, 10.0], [16, 23.0]]                     # stops where the source reaches 23
    assert cut_keys(keys, 5.0) == [[0, 0.0], [2, 5.0]]
    parts = [{'time_keys': [[0, 0.0], [11, 14.0]]}, {'time_keys': [[0, 0.0], [53, 53.0]]}]
    assert part_starts(parts) == [0, 11]                                                 # the swing starts as the stance ends
    moved, added = dress([(2, {'frame': 19}, None), (11, {}, None), (0, {}, None)],
                         {'effects': [], 'sounds': [{'cmd': 'PLAY_SE', 'real': 3, 'name': 'se_master_swing_l'}]},
                         64, CUES, 'SpecialS1', 'master', shift=11)
    assert added == ['swing 14'] and moved[0] == (2, {'frame': 14}, None)                # the sound moves with its part
