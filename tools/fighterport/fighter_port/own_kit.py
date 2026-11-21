"""The helpers a module of a fighter's own specials is written with (`own_template.py` and the generic Slap City and
Rivals builds use them; a fighter's own module `own_<fighter>.py` does too).

  fill(text, values)        a C text with each @name@ put in (a float as a C float)
  item_code(text, values)   one item's C file: filled, with `ITEM_LOST` (an item never outlives its use) after line 1
  number(table, name)       one named value of a vl.prc table, as a float
  flag_frame(move)          the first frame a move's own script raises a flag on
  hitbox(h, drawn)          one of the game's hitboxes as the fields of an item's hitbox command
  fx(ctx, name)             one of the fighter's own effects as the C list of its one-shot generators
  real_frames(move, last)   how many frames a clip plays for at the speeds its script sets
  helpless_landing(ctx)     frames of landing after a helpless fall, from the game's list of motions

They were written for the first fighters ported on skeletons of their own (Duck Hunt, Wolf); those modules are kept
under the git tag archive/fighterport-character-specific-2026-11.
"""
from __future__ import annotations

import re

# In every item's code, after its first line: an item never outlives its use.
ITEM_LOST = '''
// An item of his is taken away when he dies (or is gone), and when it leaves the stage's bounds.
static int Lost(GOBJ *item)
{
    ItemData *id = item->userdata;
    GOBJ *owner = id->fighter_gobj;
    if (!owner || ((FighterData *)owner->userdata)->state_id < ASID_REBIRTH)
        return 1;
    return id->pos.X < stc_stage->blastzoneLeft || id->pos.X > stc_stage->blastzoneRight
           || id->pos.Y < stc_stage->blastzoneBottom || id->pos.Y > stc_stage->blastzoneTop;
}
'''


def item_code(text, values):
    """One item's C file: its text filled, with what every item has (`ITEM_LOST`) after its first line."""
    first, rest = fill(text, values).split(chr(10), 1)
    return first + chr(10) + ITEM_LOST + rest


def fill(text, values):
    """A C text with each @name@ put in: a float as a C float, anything else as it prints."""
    def put(match):
        v = values[match.group(1)]
        return f'{float(v)!r}f' if isinstance(v, float) else str(v)
    return re.sub(r'@(\w+)@', put, text)


def number(table, name, default=None):
    """One named value of a vl.prc table (its first row), as a float; `default` when the name is not there."""
    row = table[0] if isinstance(table, list) and table else table
    v = (row or {}).get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        if default is None:
            raise KeyError(f'vl.prc has no number named {name}')
        return float(default)
    return float(v)


def flag_frame(move, least=1):
    """The first game frame on which a move's own script raises a flag (the game's code acts on it: lets an
    article go, opens a way out), or None."""
    frames = [f['real'] for f in (move or {}).get('flags') or [] if f.get('cmd') == 'on_flag' and f['real'] >= least]
    return min(frames) if frames else None


ELEMENT = {'collision_attr_fire': 1, 'collision_attr_elec': 2}


def hitbox(h, drawn, **more):
    """One of the game's hitboxes (as `moves.hitboxes` gives it) as the fields of an item's hitbox command: its
    damage to the whole number the driver rounds to, its size in the world's units, its angle and knockback as
    written."""
    from .combat_values import shield_field
    fields = {'damage': int(float(h['damage']) + 0.5), 'angle': int(h['angle']), 'knockback_growth': int(h['kbg']),
              'weight_set_knockback': int(h['fkb']), 'base_knockback': int(h['bkb']),
              'size': max(1, int(round(float(h['size']) * drawn * 256))),
              'element': ELEMENT.get(str(h.get('effect')), 0), 'shield_damage': shield_field(h.get('shield_damage')),
              # frames after which it may strike the same target again by itself (the game's own; 0: never)
              'again': int(h['rehit']) if isinstance(h.get('rehit'), (int, float)) and not isinstance(h.get('rehit'), bool) else 0,
              # what a hit sounds like: a burn for fire, else a kick (the game's own hit sounds are not carried)
              'hit_sfx_kind': 8 if str(h.get('effect')) == 'collision_attr_fire' else 2}
    fields.update(more)
    return fields


def fx(ctx, name, size=1.0):
    """One of his own effects as the C list of its generators that give off once ({frames after, number}), for an
    effect played at a point of the stage. (A generator held by a joint cannot be put at a point: left out.)"""
    plan = getattr(ctx.get('effects'), 'plan', None)
    if plan is None:
        return '{0, 0}', []
    from .own_effects import BURST_BEHAVIOUR, OWN_EFFECT
    uses = plan.use(name, size)
    rows = [(delay, OWN_EFFECT + number_) for delay, number_, behaviour in uses if behaviour == BURST_BEHAVIOUR]
    return ', '.join(f'{{{int(d)}, {int(g)}}}' for d, g in rows) or '{255, 0}', rows


def real_frames(move, last):
    """How many frames a clip whose last frame is `last` plays for at the speeds its script sets: its time keys
    ([[frame of play, frame of the clip], ...]), then on at the speed it set last (a rate being frames of play to one
    of the clip), as the driver plays the clip (`oneshot.play_on`). A script that sets its speed once, on its first
    frame, has only the key [0, 0]: its speed is in its rates (Greninja's `specialnstart`: 0.73, 14 frames of 19)."""
    import math
    keys = [k for k in (move or {}).get('time_keys') or [] if len(k) == 2] or [[0, 0.0]]
    rates = [float(r['rate']) for r in (move or {}).get('motion_rates') or []
             if isinstance(r.get('rate'), (int, float)) and not isinstance(r.get('rate'), bool) and r['rate'] > 0]
    frame, at = keys[-1]
    if float(at) >= float(last) - 1e-6:
        return int(round(frame)) if len(keys) > 1 else int(round(last))
    return int(frame + math.ceil((float(last) - float(at)) * (rates[-1] if rates else 1.0) - 1e-4))


def helpless_landing(ctx, default=29):
    """Frames of landing after a helpless fall: one less than the frame the game's list of motions says he may act
    from in that landing (the driver's game.json, beside its other work)."""
    import json
    from pathlib import Path
    try:
        motions = json.loads((Path(ctx['work']) / 'game.json').read_text('utf-8')).get('motions') or {}
        frame = int((motions.get('a04landingfallspecial') or {}).get('cancel_frame') or 0)
    except (OSError, ValueError, KeyError):
        frame = 0
    return frame - 1 if frame > 1 else default
