"""Validated control-flow plans for source attacks split into native clips.

The reader's path_end names a loop destination, not a natural end. Input guards
stay explicit; this helper only accepts an unconditional special-release path.
"""
from __future__ import annotations


def release_loop(move, released):
    windows = move.get('windows') or []
    end = move.get('end')
    cursor = 1
    by_name = {}
    for first, name, length in windows:
        if type(first) is not int or type(length) is not int or first != cursor or length <= 0 or name in by_name:
            raise ValueError('Release-loop windows must form a unique contiguous positive timeline')
        by_name[name] = (first, length)
        cursor += length
    if end != cursor or move.get('path_end') not in by_name:
        raise ValueError('Release-loop path must return to an exported window')
    loop_first, loop_length = by_name[move['path_end']]
    if loop_first + loop_length != end:
        raise ValueError('Only a final self-loop is supported by release_loop')
    destination = (released.get('windows') or [[None, None]])[0][1]
    if not released.get('conditional_only') or released.get('path_end'):
        raise ValueError('Release destination must be a separate finite source branch')
    intervals = []
    for cancel in move.get('window_cancels') or []:
        condition = cancel['condition']
        if condition.get('WindowCancelType', '').split('::')[-1] != 'SpecialReleased':
            continue
        if (condition.get('PostCancelWindowStringTableKey') != destination or
                condition.get('WindowCancelPrerequisite', '::None').split('::')[-1] != 'None' or
                condition.get('CancelIntoAttack', '::None').split('::')[-1] != 'None' or
                condition.get('NegatePrerequisite') or condition.get('bPreseveWindowTimer')):
            raise ValueError('Unsupported guarded or cross-attack release')
        first, length = by_name[cancel['window']]
        if (cancel['first'], cancel['last']) != (first, first + length - 1):
            raise ValueError('Release must cover each complete charge window')
        intervals.append((first, first + length))
    intervals.sort()
    if (not intervals or intervals[-1][1] != end or
            any(a[1] != b[0] for a,b in zip(intervals,intervals[1:]))):
        raise ValueError('Release windows must be contiguous through the final loop')
    return dict(release_first=intervals[0][0], stages=[a for a,b in intervals],
                loop_first=loop_first, loop_end=end, destination=destination)


def cancel_intervals(move, destination, kind):
    """Intervals for an unguarded input branch, usable by native special IASA.

    Fail explicitly on prerequisites/timer preservation; those need a mechanic
    adapter instead of unconditional input execution.
    """
    intervals = []
    for event in move.get('window_cancels') or []:
        c = event['condition']
        if (c.get('WindowCancelType','').split('::')[-1] != kind or
                c.get('PostCancelWindowStringTableKey','') != destination):
            continue
        if (c.get('WindowCancelPrerequisite','::None').split('::')[-1] != 'None' or
                c.get('CancelIntoAttack','::None').split('::')[-1] != 'None' or
                c.get('NegatePrerequisite') or c.get('bPreseveWindowTimer')):
            raise ValueError(f'Guarded {kind} branch to {destination} needs an adapter')
        intervals.append((int(event['first']),int(event['last'])))
    return intervals
