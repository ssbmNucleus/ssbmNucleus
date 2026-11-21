"""Room: where a costume's bytes go, the rule for a picture with soft edges, the size that stops the costumes stage;
and a picture of an effect file that the reader cannot read, which costs that effect and not the run.

The first tests need nothing but the code. The rest read Wolf's and Duck Hunt's built costumes and Wolf's effect
file where they are on the machine.
"""
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from echo_ultimate import effects
from fighter_port import skin_cost


# ------------------------------------------------------------------------------------- a picture with soft edges
def picture(side, alpha):
    """A square picture whose see-through is `alpha(x, y)` (0 to 255)."""
    a = np.fromfunction(np.vectorize(alpha), (side, side), dtype=int).astype(np.uint8)
    return Image.fromarray(np.dstack([np.full((side, side, 3), 200, np.uint8), a]), 'RGBA')


def test_a_picture_is_soft_by_the_importers_own_test():
    assert not skin_cost.soft(picture(64, lambda y, x: 255))                       # plain
    assert not skin_cost.soft(picture(64, lambda y, x: 255 if x < 32 else 0))      # a cutout: all or nothing
    assert skin_cost.soft(picture(64, lambda y, x: x * 4))                          # a soft edge
    assert not skin_cost.soft(Image.new('RGB', (64, 64), (9, 9, 9)))               # no see-through at all
    # nearly nothing and nearly all are not soft: 8 and 248 of 255 are the importer's own lines
    assert not skin_cost.soft(picture(64, lambda y, x: 8)) and not skin_cost.soft(picture(64, lambda y, x: 248))
    assert skin_cost.soft(picture(64, lambda y, x: 9)) and skin_cost.soft(picture(64, lambda y, x: 247))
    # the importer looks at one pixel in every 64th of each side: a soft pixel it does not look at does not count
    assert skin_cost.soft(picture(512, lambda y, x: 120 if (x, y) == (8, 8) else 255))
    assert not skin_cost.soft(picture(512, lambda y, x: 120 if (x, y) == (9, 9) else 255))


def test_a_soft_picture_takes_the_room_of_a_plain_one_at_half_the_side():
    assert (skin_cost.PLAIN_BITS, skin_cost.SOFT_BITS) == (4, 16)
    assert skin_cost.soft_side(512) == 256 and skin_cost.soft_side(1024) == 512 and skin_cost.soft_side(1) == 1
    plain = 512 * 512 * skin_cost.PLAIN_BITS // 8
    assert skin_cost.soft_side(512) ** 2 * skin_cost.SOFT_BITS // 8 == plain


def test_soft_pictures_are_made_smaller_whichever_fighter_and_whichever_part(tmp_path):
    picture(512, lambda y, x: x // 2).save(tmp_path / 'fur.png')                    # soft, and large
    picture(512, lambda y, x: 255).save(tmp_path / 'coat.png')                      # plain, and large
    picture(128, lambda y, x: x * 2 % 256).save(tmp_path / 'lash.png')              # soft, and small already
    picture(512, lambda y, x: 255 if x < 256 else 0).save(tmp_path / 'badge.png')   # a cutout
    done = skin_cost.soft_pictures(tmp_path, ['fur', 'coat', 'lash', 'badge', 'not_there'], skin_cost.soft_side(512))
    assert done == {'fur': [[512, 512], [256, 256]]}
    sizes = {n: Image.open(tmp_path / f'{n}.png').size for n in ('fur', 'coat', 'lash', 'badge')}
    assert sizes == {'fur': (256, 256), 'coat': (512, 512), 'lash': (128, 128), 'badge': (512, 512)}
    assert skin_cost.soft(Image.open(tmp_path / 'fur.png'))                         # still soft: only smaller
    # the rule is in no table by fighter: the body stage applies it to every fighter by the picture's own format
    import inspect
    from fighter_port import own_skeleton
    assert not hasattr(own_skeleton, 'SOFT_SIDE')
    assert 'skin_cost.soft_pictures(out, material, soft_side)' in inspect.getsource(own_skeleton.body)


# ------------------------------------------------------------------------------------------ a costume's bytes
def kinds(total, soft=0, plain=0, lists=0):
    by_format = {}
    if soft:
        by_format['RGB5A3'] = dict(bytes=soft, count=4, sizes=['512x512'] * 4)
    if plain:
        by_format['CMPR'] = dict(bytes=plain, count=2, sizes=['512x512', '256x256'])
    return dict(bytes=total, pictures=dict(bytes=soft + plain, count=6, by_format=by_format), display_lists=lists,
                rest=total - soft - plain - lists)


def test_a_costume_over_the_size_a_match_holds_stops_the_stage_and_says_where_its_bytes_are():
    assert skin_cost.COSTUME_MOST == 2_000_000
    assert skin_cost.too_large('PlMsNr.dat', kinds(1_813_808, soft=557_056, plain=284_672, lists=696_448)) is None
    assert skin_cost.too_large('PlMsNr.dat', kinds(2_000_000)) is None
    why = skin_cost.too_large('PlMsNr.dat', kinds(3_386_672, soft=2_129_920, plain=251_904, lists=696_448))
    assert 'PlMsNr.dat is 3,386,672 bytes' in why and '2,129,920 bytes at 16 bits a pixel' in why and '--allow-large' in why
    # a costume that is large for another reason is pointed at its pictures' side and its display lists
    why = skin_cost.too_large('PlMsNr.dat', kinds(2_400_000, plain=900_000, lists=1_200_000))
    assert 'display lists' in why and '16 bits' not in why
    lines = skin_cost.kind_lines('c00 -> PlMsNr.dat', kinds(3_386_672, soft=2_129_920, plain=251_904, lists=696_448))
    assert lines[0] == 'c00 -> PlMsNr.dat: 3,386,672 bytes' and 'RGB5A3' in lines[1] and '4 of 512x512' in lines[1]
    assert 'CMPR' in lines[2] and 'display lists' in lines[3] and 'everything else' in lines[4]


def test_the_costumes_stage_prints_the_bytes_and_stops_before_the_other_costumes():
    text = (Path(skin_cost.__file__).parent / 'harness' / 'own_costumes.py').read_text('utf-8')
    loop = text[text.index('for code, folder in zip(CODES, folders):'):text.index("pkg = work / 'package'")]
    # inside the loop over the costumes, before anything is copied into the package: each one measured (what it says
    # and when it stops is `skin_cost.costume_room`, tested below on real costumes), printed, and stopped on at the
    # first one too large
    assert loop.index('skin_cost.costume_room(') < loop.index("print('\\n'.join(lines))") < loop.index('if stop:')
    assert loop.index('if stop:') < loop.index('raise SystemExit(stop') < loop.index('rows.append(')
    assert "allow_large = '--allow-large' in sys.argv[1:]" in text and 'allow_large)' in loop


SCRATCH = Path(os.environ.get('NUCLEUS_REPO') or Path(__file__).resolve().parents[2]) / 'app' / 'scratch'
WOLF, WOLF_BEFORE = SCRATCH / 'wolf-cold/body/wolf_static.dat', SCRATCH / 'wolf-cold/body-before-gun/wolf_static.dat'
DUCK = SCRATCH / 'duckhunt-native/oneshot/body/duckhunt_static.dat'


@pytest.mark.skipif(not (WOLF_BEFORE.exists() and DUCK.exists()), reason="Wolf's and Duck Hunt's built costumes are not here")
def test_the_bytes_of_real_costumes_by_kind():
    # Wolf's first costume, the one two of which did not load: most of it is four pictures with soft edges
    before = skin_cost.bytes_by_kind(WOLF_BEFORE.read_bytes())
    soft = before['pictures']['by_format']['RGB5A3']
    assert before['bytes'] == WOLF_BEFORE.stat().st_size > skin_cost.COSTUME_MOST
    assert soft['sizes'].count('512x512') == 4 and soft['bytes'] > before['bytes'] // 2
    assert before['pictures']['bytes'] + before['display_lists'] + before['rest'] == before['bytes']
    assert skin_cost.too_large('wolf', before) and '16 bits a pixel' in skin_cost.too_large('wolf', before)
    # Duck Hunt has no picture with soft edges: the rule changes nothing of his
    duck = skin_cost.bytes_by_kind(DUCK.read_bytes())
    assert set(duck['pictures']['by_format']) == {'CMPR'} and skin_cost.too_large('duckhunt', duck) is None


@pytest.mark.skipif(not (WOLF_BEFORE.exists() and DUCK.exists()), reason="Wolf's and Duck Hunt's built costumes are not here")
def test_the_costumes_stage_stops_on_wolfs_first_costume_and_not_on_the_dogs():
    """What the stage asks of each costume it builds (`costume_room`), on the two real ones: Wolf's first, 3.4 MB, of
    which two did not load in one match, and Duck Hunt's, 1.8 MB, which loads beside anything."""
    kinds, lines, stop = skin_cost.costume_room('PlMsNr.dat (c00)', WOLF_BEFORE.read_bytes())
    assert kinds['bytes'] == WOLF_BEFORE.stat().st_size > skin_cost.COSTUME_MOST
    assert lines[0] == f"PlMsNr.dat (c00): {kinds['bytes']:,} bytes" and any('RGB5A3' in line for line in lines)
    assert stop.startswith(f"PlMsNr.dat (c00) is {kinds['bytes']:,} bytes: over 2,000,000") and '--allow-large' in stop
    # given --allow-large it is built, and the line says it is over and what is owed
    _kinds, lines, stop = skin_cost.costume_room('PlMsNr.dat (c00)', WOLF_BEFORE.read_bytes(), allow_large=True)
    assert stop is None and 'OVER 2,000,000' in lines[-1] and 'heap_probe' in lines[-1]
    # a costume under the line: printed, nothing said over it, and the stage goes on
    kinds, lines, stop = skin_cost.costume_room('PlMsNr.dat (c00)', DUCK.read_bytes())
    assert stop is None and kinds['bytes'] <= skin_cost.COSTUME_MOST and not any('OVER' in line for line in lines)


@pytest.mark.skipif(not WOLF.exists(), reason="Wolf's built costume is not here")
def test_wolfs_soft_pictures_are_at_the_side_the_rule_gives():
    now = skin_cost.bytes_by_kind(WOLF.read_bytes())
    soft = now['pictures']['by_format']['RGB5A3']
    side = skin_cost.soft_side(512)
    assert all(int(s.split('x')[0]) <= side for s in soft['sizes']) and skin_cost.too_large('wolf', now) is None


# ------------------------------------------------------------------------------- a picture the reader cannot read
DUMP = Path(os.environ.get('ULTIMATE_DUMP') or Path.home() / 'shulk-calibration-20260904')
WOLF_EFFECTS = DUMP / 'gamedata' / 'effect' / 'fighter' / 'wolf' / 'ef_wolf.eff'
needs_wolf = pytest.mark.skipif(not WOLF_EFFECTS.exists(), reason="Wolf's effect file is not on this machine")


def test_the_driver_reads_the_effect_files_pictures_before_it_makes_the_clip_bank(tmp_path):
    """Wolf's first driver died on one effect picture four minutes in, after the clip bank had been made, and the
    rerun made the bank again. The pictures are read first now (seconds), and the bank's cache is said."""
    import inspect
    from fighter_port import own_route
    run = inspect.getsource(own_route.run)
    assert run.index('effects.pictures()') < run.index('own_bank.build(')
    assert run.index("cache = own / 'bank' / 'cache'") < run.index('own_bank.build(') and 'cache=cache' in run
    # a fighter with no effect file of its own has nothing to read, and that is not a failure
    assert own_route.OwnEffects(tmp_path, 'nobody', 1.0).pictures() is None


@needs_wolf
def test_the_driver_says_how_many_of_wolfs_effect_pictures_it_read():
    from fighter_port import own_route
    assert own_route.OwnEffects(DUMP, 'wolf', 1.0).pictures() == (49, [])


@needs_wolf
def test_every_picture_of_wolfs_effect_file_is_read():
    unread, read = effects.unread_pictures(WOLF_EFFECTS)
    assert unread == [] and read == 49


@needs_wolf
def test_a_picture_in_a_format_the_reader_does_not_know_costs_that_effect_not_the_run(monkeypatch):
    """As it was when Wolf was ported cold: the reader did not know sixteen-bit pictures, his effect file has one, and
    the driver died on it after the clip bank was made."""
    known = dict(effects.FORMATS)
    for fmt in (0x07, 0x08):
        known.pop(fmt)
    monkeypatch.setattr(effects, 'FORMATS', known)
    unread, read = effects.unread_pictures(WOLF_EFFECTS)
    assert unread == [('ef_cmn_parts01', 0x701)] and read == 48
    # a caller that needs every picture is still told by an error, with where the formats are kept
    archive = effects.texture_archive(effects.particle_data(WOLF_EFFECTS.read_bytes()))
    with pytest.raises(ValueError, match='ef_cmn_parts01: picture format 0x701 is not handled'):
        effects.textures(archive)
    # the driver's own reading of the file goes on: the picture is listed, and an emitter drawn with it is not carried
    from fighter_port import own_effects
    plan = own_effects.Plan(WOLF_EFFECTS, 1.0)
    assert plan.pictures() == (48, [('ef_cmn_parts01', 0x701)])
    number = next(n for n, fmt in plan._unread_numbers.items() if fmt == 0x701)
    assert plan._picture(number) is None
    for name in plan.sets:                                  # every set can still be asked for: none raises
        plan.use(name)
    report = plan.report()
    assert report['unread_pictures'] == [dict(name='ef_cmn_parts01', format='0x701')]
    assert any('ef_cmn_parts01' in w for w in report['warnings'])
    lost = [row for rows in report['sets'].values() for row in rows
            if any('a format the reader does not know' in why for why in row['not_carried'])]
    assert all(not row['carried'] for row in lost)
