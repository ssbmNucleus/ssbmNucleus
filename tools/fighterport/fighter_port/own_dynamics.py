"""The parts of a fighter the game swings by physics (ears, hair, tails, capes), written into its Melee fighter data.

Melee calls these "dynamics" (ftdynamics.c; the simulation is lb_8001044C in lb_00F9.c). A fighter's data holds, at
+0x2C:   how many chains, the chains, how many collision spheres, the spheres, and rows of "how many joints at the head
         of each chain follow the clip" that an action can choose;
at +0x10 a pair of bytes an action: how many frames it blends in over, and which of those rows it uses;
and each action's flag word says which applies: 0x10000000 every chain follows the clip, 0x08000000 the action's row
is used, neither and every chain swings.

What Melee can hold (all checked in its code): a chain is a line of joints, each the first child of the one before,
numbered in a row; the last joint is only carried; at most 9 chains and 11 spheres; a joint that is being swung takes
nothing from its clip; a swung joint must not be turned about its own length at rest. The frozen rig's swing plan
(`own_skeleton.swing_plan`) has already put the source's chains in that form.

THE NUMBERS ARE READINGS. The source says how each joint swings with numbers of its own engine (how hard it is pulled
back to its pose, air resistance, gravity, the widest angles); Melee's simulation has five numbers a joint of another
kind. The mapping below keeps what each number is for and takes its size from what Melee's own fighters use (Marth's
cape, Fox's tail, Link's hat, Jigglypuff's tuft). It is meant to be looked at in the game and changed.
"""
from __future__ import annotations

import math
import struct

BOTH = 0x18000000
FOLLOW_CLIP, USE_ROW = 0x10000000, 0x08000000
OFF = 256                            # a row's number for "this whole chain follows the clip"
MOST_CHAINS, MOST_SPHERES = 9, 11
SHARE = 0.5                          # a joint the source leaves less than this much to physics follows its clip

GRAVITY = 0.07                       # a chain's pull down for a source gravity of 1 (Fox's tail 0.044, Marth's cape 0.17)
GRAVITY_RANGE = (0.005, 0.15)
SPRING = (0.005, 0.0005, 0.02)       # pull back to the rest pose: a floor, more per unit of the source's, a ceiling
CONE = (math.radians(5), math.radians(60))   # the narrowest and widest a joint may swing from its rest (Marth's cape: 60)
DAMPING = (0.0087, 0.0035, 0.07)     # for a source air resistance of 1, and the least and most (Marth's cape: 0.0087)
STEP = 0.07                          # the most a joint turns in one frame (vanilla 0.05 to 0.14)
FILL = (2 * math.pi,) * 3 + (-2 * math.pi,) * 3      # six numbers every vanilla file carries and the game never reads


def joint_numbers(source, rest):
    """One swung joint's 15 numbers (stiffness, pull back, rest turn x y z w, widest angle, the six unread ones,
    damping, most turn a frame), from the source's numbers for it and its rest turn in the rig."""
    goal = float(source.get('goalstrength', 0.0))
    spring = 0.0 if goal <= 0 else min(SPRING[2], SPRING[0] + SPRING[1] * goal)
    widest = max((abs(float(source[k])) for k in ('minangley', 'maxangley', 'minanglez', 'maxanglez') if k in source),
                 default=math.degrees(CONE[1]))
    cone = min(CONE[1], max(CONE[0], math.radians(widest)))
    damping = min(DAMPING[2], max(DAMPING[1], DAMPING[0] * float(source.get('airresistance', 1.0))))
    return (1.0, spring, float(rest[0]), float(rest[1]), float(rest[2]), 0.0, cone) + FILL + (damping, STEP)


def chain_gravity(numbers):
    pulls = [float(n.get('localgravity', 1.0)) * float(n.get('fallspeedscale', 1.0)) for n in numbers] or [1.0]
    return min(GRAVITY_RANGE[1], max(GRAVITY_RANGE[0], GRAVITY * sum(pulls) / len(pulls)))


def spheres(swing, order, most=MOST_SPHERES):
    """The shapes the chains are kept out of, as Melee's spheres: (joint, x, y, z, radius) in the joint's own frame.
    An ellipsoid becomes a sphere of its middle radius. When there are more than Melee holds, the ones the fewest
    joints name are left out. -> (the spheres, the names left out)"""
    used = {}
    for chain in swing['chains']:
        for n in chain['numbers']:
            for name in n.get('collisions', []):
                used[name] = used.get(name, 0) + 1
    shapes = []
    for s in swing.get('spheres', []):
        shapes.append((s['name'], s['bonename'], (s['cx'], s['cy'], s['cz']), float(s['radius'])))
    for s in swing.get('ellipsoids', []):
        shapes.append((s['name'], s['bonename'], (s['cx'], s['cy'], s['cz']), sorted((s['sx'], s['sy'], s['sz']))[1]))
    shapes = [s for s in shapes if used.get(s[0]) and s[1] in order]
    shapes.sort(key=lambda s: -used[s[0]])
    kept, left = shapes[:most], [s[0] for s in shapes[most:]]
    return [(order.index(bone), float(c[0]), float(c[1]), float(c[2]), float(r)) for _n, bone, c, r in kept], left


def row_for(chains, shares):
    """For one clip: how many joints at the head of each chain follow the clip (`OFF` when all of them do).
    `shares`: {joint name: how much of it is left to physics, 0..1}; a joint not named swings."""
    row = []
    for chain in chains:
        swung = chain['joints'][:-1]
        n = 0
        while n < len(swung) and shares.get(swung[n], 1.0) < SHARE:
            n += 1
        row.append(OFF if n == len(swung) else n)
    return tuple(row)


def apply(pl_bytes, frozen, clips=None, shares=None):
    """Write the frozen rig's swing chains into a fighter's data. -> (the new file, a report)

    clips    {action index: the source clip it plays, or None}; shares {clip: {joint: share left to physics}} with the
             default under None (`echo_ultimate.gamedata.swing.blend`). Without them every action swings every chain.
    """
    from vault.echo.subactions import FighterDat
    order, swing = frozen['order'], frozen.get('swing') or {}
    chains = swing.get('chains') or []
    if len(chains) > MOST_CHAINS:
        raise ValueError(f'{len(chains)} swing chains; Melee holds {MOST_CHAINS}')
    ft = FighterDat(bytes(pl_bytes))
    dat, root = ft.dat, ft.ft_root
    phys = dat.ptr(root + 0x2C)
    if phys is None:
        raise ValueError('this fighter data has no dynamics block to write into')
    report = dict(chains=[], spheres=[], rows=[], actions={})

    def pointer(slot, target):
        dat.set_u32(slot, target)
        dat.add_reloc(slot)

    # the chains
    descs = bytearray()
    places = []
    for chain in chains:
        joints = chain['joints']
        at = [order.index(j) for j in joints]
        if at != list(range(at[0], at[0] + len(at))):
            raise ValueError(f'the chain {joints} is not numbered in a row ({at})')
        rows = [joint_numbers(n, frozen['rest'][j]['r']) for j, n in zip(joints, chain['numbers'])]
        rows.append(rows[-1])                               # the end joint has a place in the table too
        blob = b''.join(struct.pack('>15f', *r) for r in rows)
        places.append(dat.append_struct(blob))
        gravity = chain_gravity(chain['numbers'])
        descs += struct.pack('>iIIfff', at[0], 0, len(joints), 1.0, 1.0, gravity)
        report['chains'].append(dict(joints=joints, first=at[0], gravity=round(gravity, 4),
                                     numbers=[dict(spring=round(r[1], 4), cone=round(r[6], 3), damping=round(r[13], 4))
                                              for r in rows[:-1]]))
    if chains:
        for i, place in enumerate(places):
            struct.pack_into('>I', descs, i * 0x18 + 4, place)
        pointer(phys + 4, dat.append_struct(bytes(descs), [i * 0x18 + 4 for i in range(len(chains))]))
    dat.set_u32(phys, len(chains))

    # the spheres
    balls, left = spheres(swing, order) if chains else ([], [])
    if balls:
        pointer(phys + 0xC, dat.append_struct(b''.join(struct.pack('>iffff', *b) for b in balls)))
    dat.set_u32(phys + 8, len(balls))
    report['spheres'] = [dict(joint=order[b[0]], at=[round(x, 2) for x in b[1:4]], radius=round(b[4], 2)) for b in balls]
    report['spheres_left_out'] = left

    # each action: which chains swing
    default = (shares or {}).get(None, {})
    table, count = ft.action_table
    pairs = dat.ptr(root + 0x10)
    rows, picked = [], {}
    for i in range(count if table is not None else 0):
        stem = (clips or {}).get(i)
        row = row_for(chains, (shares or {}).get(stem, default)) if chains else ()
        flags = dat.u32(table + i * 0x18 + 0x10) & ~BOTH
        which = 0
        if chains and all(v == OFF for v in row):
            flags |= FOLLOW_CLIP
        elif chains and any(row):
            if row not in rows:
                rows.append(row)
            which = rows.index(row)
            flags |= USE_ROW
        dat.set_u32(table + i * 0x18 + 0x10, flags)
        if pairs is not None:
            dat.buf[0x20 + pairs + 2 * i + 1] = which
        picked.setdefault('follows the clip' if flags & FOLLOW_CLIP else f'row {which}' if flags & USE_ROW else 'swings',
                          []).append(i)
    if rows:
        at = [dat.append_struct(struct.pack(f'>{len(chains)}i', *row)) for row in rows]
        pointer(phys + 0x10, dat.append_struct(struct.pack(f'>{len(at)}I', *at), [4 * i for i in range(len(at))]))
    # the results screen's own actions: every chain swings
    demo, demo_pairs = dat.ptr(root + 0x14), dat.ptr(root + 0x18)
    if demo is not None:
        for i in range((dat.struct_end(demo) - demo) // 0x18):
            dat.set_u32(demo + i * 0x18 + 0x10, dat.u32(demo + i * 0x18 + 0x10) & ~BOTH)
            if demo_pairs is not None and demo_pairs + 2 * i + 1 < dat.struct_end(demo_pairs):
                dat.buf[0x20 + demo_pairs + 2 * i + 1] = 0
    report['rows'] = [list(r) for r in rows]
    report['actions'] = {k: len(v) for k, v in picked.items()}
    return dat.to_bytes(), report


def read(pl_bytes):
    """What a fighter's data says about its swing chains: for checking what `apply` wrote."""
    from vault.echo.subactions import FighterDat
    ft = FighterDat(bytes(pl_bytes))
    dat, root = ft.dat, ft.ft_root
    phys = dat.ptr(root + 0x2C)
    out = dict(chains=[], spheres=[], rows=[], flags={})
    if phys is None:
        return out
    count, descs = dat.u32(phys), dat.ptr(phys + 4)
    for i in range(count):
        d = descs + i * 0x18
        n, numbers = dat.u32(d + 8), dat.ptr(d + 4)
        out['chains'].append(dict(first=dat.i32(d), joints=n, gravity=dat.f32(d + 0x14),
                                  numbers=[[dat.f32(numbers + k * 0x3C + 4 * f) for f in range(15)] for k in range(n)]))
    balls = dat.ptr(phys + 0xC)
    for i in range(dat.u32(phys + 8)):
        b = balls + i * 0x14
        out['spheres'].append((dat.i32(b), dat.f32(b + 4), dat.f32(b + 8), dat.f32(b + 12), dat.f32(b + 16)))
    table, n_actions = ft.action_table
    pairs = dat.ptr(root + 0x10)
    used = set()
    for i in range(n_actions if table is not None else 0):
        flags = dat.u32(table + i * 0x18 + 0x10)
        key = 'follows the clip' if flags & FOLLOW_CLIP else 'row' if flags & USE_ROW else 'swings'
        out['flags'][key] = out['flags'].get(key, 0) + 1
        if flags & USE_ROW and pairs is not None:
            used.add(dat.buf[0x20 + pairs + 2 * i + 1])
    rows = dat.ptr(phys + 0x10)
    if rows is not None and used:
        for k in range(max(used) + 1):
            at = dat.ptr(rows + 4 * k)
            out['rows'].append([dat.i32(at + 4 * c) for c in range(count)])
    return out
