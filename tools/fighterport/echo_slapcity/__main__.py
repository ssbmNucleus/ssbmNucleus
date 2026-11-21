"""python -m echo_slapcity <game data folder> <fighter> <root>: write the fighter in the port's shapes under <root>
(see transcode.py) and its game data (gamedata.py) beside them.
python -m echo_slapcity <game data folder> --list: list fighter names, input tables and missing moves as JSON.
"""
import argparse
import json
import sys
import time
from pathlib import Path

from . import transcode
from .unity import Game


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data_dir')
    parser.add_argument('fighter', nargs='?')
    parser.add_argument('root', nargs='?')
    parser.add_argument('--list', action='store_true', dest='list_roster')
    args = parser.parse_args(argv)
    if args.list_roster:
        if args.fighter or args.root:
            parser.error('--list takes only the game data folder')
        from .roster import roster
        rows = roster(Game(args.data_dir))
        print(json.dumps(rows, indent=2))
        return 1 if any('error' in row for row in rows) else 0
    if args.fighter is None or args.root is None:
        parser.error('export needs a fighter and an output root (or use --list)')
    data_dir, fighter, root = args.data_dir, args.fighter, args.root
    import ssbh_data_py as ssbh
    t = time.time()
    game = Game(data_dir)
    print(f'opened {data_dir} in {time.time() - t:.1f} s')
    # the sounds first: with UnityPy's own decoding (AudioClip.samples) FMOD took none of the clips once the bodies
    # had been read (FORMAT), though each decoded in a fresh process (not dug into; unity.audio decodes now)
    from . import sounds
    from .fighter import Fighter
    sounds.write(Fighter(game, fighter), Path(root) / 'gamedata' / 'fighter' / fighter)
    from . import identity
    identity.write(game, fighter, Path(root) / 'gamedata' / 'fighter' / fighter)
    summary, _sk, _f = transcode.write(game, fighter, root, ssbh)
    from . import gamedata
    data = gamedata.load(fighter, root, game=game)
    out = Path(root) / 'gamedata' / 'fighter' / fighter / 'game.json'
    out.write_text(json.dumps(data, indent=1, default=str), 'utf-8')
    print(f"the game data: {len(data['moves'])} moves, {len(data['melee_attributes'])} numbers -> {out}")
    print(f"{fighter}: {len(summary['joints'])} joints, {len(summary['stems'])} clips, {len(summary['costumes'])} "
          f"costumes, unit {summary['unit']:.4f} (height {summary['height_in_game_units']:.3f} in the game's units); "
          f'{time.time() - t:.1f} s')


if __name__ == '__main__':
    sys.exit(main())
