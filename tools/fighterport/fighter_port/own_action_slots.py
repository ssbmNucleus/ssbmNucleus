"""Explicit native adapters own their assigned animation slots.

The donor's automatic split-special placeholders must not consume a slot an
adapter has reserved for a real phase. Missing clips retain the existing
missing-special handling; conflicting explicit owners fail deterministically.
"""


def reserve(table,assignments,stems):
    names={stem[3:]:stem for stem in stems}
    owners={}
    for clip,entry in (assignments or {}).items():
        if clip not in names:continue
        motion=entry.get('motion') if isinstance(entry,dict) else entry
        if not isinstance(motion,str):raise ValueError('owned action reservation requires one native motion')
        if motion in owners and owners[motion]!=names[clip]:
            raise ValueError(f'{motion}: two explicitly assigned source clips')
        owners[motion]=names[clip]
    for stem,rows in table.items():
        table[stem]=[row for row in rows if row['target_motion'] not in owners or owners[row['target_motion']]==stem]
    return owners
