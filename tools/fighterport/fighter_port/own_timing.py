"""Shared natural completion and input-interrupt timing for generated special states.

`end` is the source's natural completion in real updates; an absent end leaves completion to the clip.
`cancel_frame_real` enables input checks without ending an untouched move. Do not collapse the two.
"""
from __future__ import annotations
import math

NEVER = 30000


def _frame(value):
    if isinstance(value, bool):
        raise ValueError('Timing cannot be a boolean')
    if value is None or value == 0 or value == -1:
        return NEVER
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f'Invalid real-frame timing: {value!r}')
    return min(NEVER, math.ceil(value))


def move_timing(move):
    """Return independent (natural end, earliest ordinary input interrupt), in simulation updates."""
    return _frame(move.get('end')), _frame(move.get('cancel_frame_real'))


def interrupt_callback(name, ground, air=None):
    """Emit current-input checks only. `air=None` preserves a move's explicit helpless-air policy.

    MexTK's AllGrounded maps to the void ftCo_Wait_IASA; never use its declared int return as a bool.
    No-input checks leave the existing state, animation, hitboxes and item schedule untouched.
    """
    body = f"""void {name}(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    if (fd->phys.air_state == 0)
    {{
        if (t_frame[fd->ply] >= {ground})
            Fighter_IASACheck_AllGrounded(gobj);
    }}
"""
    if air is not None:
        body += f"""    else if (t_frame[fd->ply] >= {air})
        Fighter_IASACheck_AllAerial(gobj);
"""
    return body + '}\n'
