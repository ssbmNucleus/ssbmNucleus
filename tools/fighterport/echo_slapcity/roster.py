"""Discover fighters and their actual input tables without exporting bodies, clips or sounds."""
from .fighter import Fighter


def roster(game):
    names = set()
    for path in game.container():
        parts = path.split('/')
        if len(parts) == 4 and parts[:2] == ['smash', 'characters'] and parts[2] == parts[3]:
            names.add(parts[2])
    rows = []
    for name in sorted(names):
        try:
            fighter = Fighter(game, name)
            moves = fighter.moveset()
            inputs = fighter.character.get('standardSCinputTrigger') or {}
            rows.append({'fighter': name, 'moves': len(moves), 'inputs': inputs,
                         'missing_moves': sorted({m for v in inputs.values()
                                                  for m in (v if isinstance(v, list) else [v])
                                                  if isinstance(m, str) and m and m not in moves})})
        except (KeyError, ValueError, StopIteration) as exc:
            rows.append({'fighter': name, 'error': f'{type(exc).__name__}: {exc}'})
    return rows
