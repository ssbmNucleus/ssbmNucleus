"""Which of the source game's fighter numbers is which of Melee's: asked of the fighters that are in BOTH games.

For each pair that might mean the same thing, Melee's attribute is put beside the game's field for every fighter
the two games share. A pair whose ratio is the same for every fighter is the same number in other units; a pair
whose ratio wanders is not the same number, whatever the names say. This is the check behind the checklist's
lines on a fighter's numbers: run it before adding a pair to `oneshot.ATTRIBUTES`.

    (cwd app/backend) python both_games.py <game root> <a project's files folder> [<fighter in the game> ...] [-v]

The files folder is any m-ex project's `files` (it holds Melee's own Pl??.dat). Each fighter named is shown with
what the pair's middle ratio would make of its number. -v prints every fighter's two numbers.
"""
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from fighter_port import compat  # noqa: E402

compat.install()
from vault.echo.subactions import FighterDat            # noqa: E402
from vault.echo.attributes import Attributes            # noqa: E402
from echo_ultimate.gamedata import names                # noqa: E402
from echo_ultimate.gamedata.prc import Prc              # noqa: E402

# Melee's file code -> the fighter's name in Ultimate's tables
BOTH = {'Mr': 'mario', 'Fx': 'fox', 'Ca': 'captain', 'Dk': 'donkey', 'Kb': 'kirby', 'Kp': 'koopa', 'Lk': 'link',
        'Sk': 'sheik', 'Ns': 'ness', 'Pe': 'peach', 'Pk': 'pikachu', 'Ss': 'samus', 'Ys': 'yoshi', 'Pr': 'purin',
        'Mt': 'mewtwo', 'Lg': 'luigi', 'Zd': 'zelda', 'Cl': 'younglink', 'Dr': 'mariod', 'Fc': 'falco',
        'Pc': 'pichu', 'Gw': 'gamewatch', 'Gn': 'ganon', 'Fe': 'roy'}
# (Melee's attribute, the game's field): every pair worth asking about, the wrong guesses too
PAIRS = [('friction', 'ground_brake'), ('aerial_speed', 'air_accel_x_mul'), ('aerial_friction', 'air_accel_x_add'),
         ('air_friction', 'air_brake_x'), ('initial_walk_speed', 'walk_accel_add'), ('walk_acceleration', 'walk_accel_mul'),
         ('initial_walk_speed', 'walk_accel_mul'), ('walk_acceleration', 'walk_accel_add'),
         ('mid_walk_point', 'walk_middle_ratio'), ('fast_walk_speed', 'walk_fast_ratio'),
         ('stop_turn_initial_speed_a', 'run_accel_mul'), ('stop_turn_initial_speed_b', 'run_accel_add'),
         ('number_of_jumps', 'jump_count_max'), ('horizontal_air_jump_multiplier', 'jump_aerial_speed_x_mul'),
         ('shield_size', 'shield_radius'), ('normal_landing_lag', 'landing_frame'),
         ('normal_landing_lag', 'landing_heavy_frame'), ('ledge_jump_horizontal_velocity', 'cliff_jump_x_speed'),
         ('ledge_jump_vertical_velocity', 'cliff_jump_y'), ('item_throw_velocity', 'throw_item_speed_mul'),
         ('item_throw_damage_scale', 'throw_item_power_mul'), ('weight', 'weight'), ('gravity', 'air_accel_y'),
         ('max_walk_speed', 'walk_speed_max'), ('initial_dash_speed', 'dash_speed'), ('initial_run_speed', 'run_speed_max'),
         ('terminal_velocity', 'air_speed_y_stable'), ('max_aerial_horizontal_speed', 'air_speed_x_stable'),
         ('jump_startup_lag', 'jump_squat_frame'), ('model_scale', 'scale'), ('walk_animation_speed', 'walk_slow_speed_mul')]


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def main(argv):
    loud = '-v' in argv
    argv = [a for a in argv if a != '-v']
    if len(argv) < 2:
        raise SystemExit(__doc__)
    root, files, asked = Path(argv[0]), Path(argv[1]), argv[2:]
    known = names.candidates('mario', root / 'Hashes_FullPath', ())
    known |= {f'fighter_kind_{n}' for n in list(BOTH.values()) + asked}
    table = Prc((root / 'gamedata/fighter/common/param/fighter_param.prc').read_bytes(), known).root.get('fighter_param_table', [])
    game = {str(r.get('fighter_kind'))[len('fighter_kind_'):]: r for r in table}
    melee = {}
    for code in BOTH:
        p = files / f'Pl{code}.dat'
        if p.exists():
            melee[code] = Attributes(FighterDat(p.read_bytes())).all()
    print(len(melee), 'fighters in both games read;', ', '.join(f'{n} {"found" if n in game else "NOT FOUND"}' for n in asked))
    for m, g in PAIRS:
        rows = []
        for code, name in BOTH.items():
            if code in melee and name in game:
                a, b = melee[code].get(m), game[name].get(g)
                if number(a) and number(b) and b:
                    rows.append((code, a, b, a / b))
        if not rows:
            print(f'{m} <- {g}: nothing to compare')
            continue
        r = [x[3] for x in rows]
        med = statistics.median(r)
        near = sum(1 for x in r if med and abs(x - med) <= 0.15 * abs(med))
        made = '; '.join(f'{n} {game[n].get(g)} -> {game[n].get(g) * med:.4f}' for n in asked
                         if n in game and number(game[n].get(g)))
        print(f'{m} <- {g}: ratio middle {med:.3f} (least {min(r):.3f}, most {max(r):.3f}); '
              f'{near} of {len(r)} within 15%' + (f'; {made}' if made else ''))
        if loud:
            print('    ', [(c, round(a, 4), round(b, 4)) for c, a, b, _ in rows])


if __name__ == '__main__':
    main(sys.argv[1:])
