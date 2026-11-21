"""The game's particles, read from a snapshot of its memory, and what is wrong with them.

Melee keeps each link's live particles on one list (`hsd_804D0908[linkNo]`, 16 links), its free particles on the
pool's free list (`hsd_804D0F60`, HSD_ObjAllocData: free head at +4, used at +8), its live generators on one list
(`hsd_804D78FC`) and its free generators on their pool's free list (`hsd_804D0F90`). A particle's own fields
(sysdolphin psstructs.h): next 0x0, kind 0x4, bank 0x8, texGroup 0x9, linkNo 0x1D, idnum 0x1E, life 0x2A, gen 0x88,
appsrt 0x8C; a generator's: next 0x0, kind 0x4, type 0x16, bank 0x18, linkNo 0x19, texGroup 0x1A, idnum 0x1C,
numChild 0x50.

A loop in a live list hangs the game in `particleSort` as it draws (Greninja's Substitute, 2026-11-13); a particle
that is both live and free, or whose generator is free, is how such a loop is made. `faults` finds each.
"""
from __future__ import annotations

import struct

BASE = 0x80000000
LINKS, LINK_HEADS = 16, 0x804D0908
PARTICLE_POOL, GENERATOR_POOL, GENERATORS = 0x804D0F60, 0x804D0F90, 0x804D78FC
MOST = 20000                        # a list longer than this is taken to loop


def _reader(mem):
    def u32(a):
        return struct.unpack_from('>I', mem, a - BASE)[0]

    def u16(a):
        return struct.unpack_from('>H', mem, a - BASE)[0]

    def u8(a):
        return mem[a - BASE]

    def ok(p):
        return BASE <= p < BASE + len(mem) - 0x98 and p % 4 == 0
    return u32, u16, u8, ok


def _walk(u32, ok, head):
    """-> (the nodes in order, what ended the walk: None for its end, else a note)"""
    seen, order, p = set(), [], head
    while p:
        if not ok(p):
            return order, f'a bad pointer {p:#x}'
        if p in seen:
            return order, f'a loop back to {p:#x} (node {order.index(p)})'
        if len(order) >= MOST:
            return order, f'more than {MOST}'
        seen.add(p)
        order.append(p)
        p = u32(p)
    return order, None


def particle(mem, p):
    u32, u16, u8, _ = _reader(mem)
    return dict(at=hex(p), kind=hex(u32(p + 4)), bank=u8(p + 8), tex=u8(p + 9), link=u8(p + 0x1D),
                id=u16(p + 0x1E), life=u16(p + 0x2A), gen=hex(u32(p + 0x88)), appsrt=hex(u32(p + 0x8C)))


def generator(mem, g):
    u32, u16, u8, _ = _reader(mem)
    return dict(at=hex(g), kind=hex(u32(g + 4)), type=hex(u16(g + 0x16)), bank=u8(g + 0x18), link=u8(g + 0x19),
                tex=u8(g + 0x1A), id=u16(g + 0x1C), children=u32(g + 0x50))


def read(mem):
    """The lists, from a snapshot of the game's memory (bytes from 0x80000000)."""
    u32, _, u8, ok = _reader(mem)
    links = {k: _walk(u32, ok, u32(LINK_HEADS + 4 * k)) for k in range(LINKS)}
    return dict(links=links, free=_walk(u32, ok, u32(PARTICLE_POOL + 4)),
                used=u32(PARTICLE_POOL + 8), gens=_walk(u32, ok, u32(GENERATORS)),
                free_gens=_walk(u32, ok, u32(GENERATOR_POOL + 4)))


def faults(mem, most=6):
    """What is wrong with the game's particles now: [line], empty when nothing is."""
    u32, _, u8, _ok = _reader(mem)
    got, out = read(mem), []
    live = {}
    for k, (order, end) in got['links'].items():
        if end:
            out.append(f'link {k}: {len(order)} particles, then {end}')
        for p in order:
            if p in live:
                out.append(f'particle {p:#x} is on link {live[p]} and link {k}')
            live.setdefault(p, k)
            if u8(p + 0x1D) != k:
                out.append(f'particle {p:#x} on link {k} says it is on link {u8(p + 0x1D)}: {particle(mem, p)}')
    free, free_end = got['free']
    if free_end:
        out.append(f'the particle free list: {len(free)}, then {free_end}')
    both = [p for p in free if p in live]
    for p in both[:most]:
        out.append(f'particle {p:#x} is live (link {live[p]}) and free: {particle(mem, p)}')
    gens, gen_end = got['gens']
    if gen_end:
        out.append(f'the generator list: {len(gens)}, then {gen_end}')
    free_gens, fg_end = got['free_gens']
    if fg_end:
        out.append(f'the generator free list: {len(free_gens)}, then {fg_end}')
    free_gens = set(free_gens)
    for g in gens:
        if g in free_gens:
            out.append(f'generator {g:#x} is live and free: {generator(mem, g)}')
    orphans = [p for p in live if u32(p + 0x88) and u32(p + 0x88) in free_gens]
    for p in orphans[:most]:
        out.append(f'particle {p:#x} names a FREE generator: {particle(mem, p)}; '
                   f'it: {generator(mem, u32(p + 0x88))}')
    return out + heap_faults(mem, most)


HEAP_ARRAY, HEAP_HANDLE = 0x804D7360, 0x804D5E00     # OSAlloc.c HeapArray; the handle HSD allocates from
CELL_HEAD = 0x20                                    # an OS heap cell's header: prev 0, next 4, size 8 (32 bytes)


def heap_faults(mem, most=6):
    """What is wrong with the heap the game's objects come from (OSAlloc.c: HeapDesc {size, free, allocated}, each
    list of cells in address order): a broken list, cells that overlap, and the bomb of a loop in the particle list,
    a live particle in memory the heap holds free (the next growth of the particle pool is handed it)."""
    u32, _, _, ok = _reader(mem)
    out = []
    array, handle = u32(HEAP_ARRAY), u32(HEAP_HANDLE)
    if not ok(array) or handle >= 32:
        return [f'no heap to read (array {array:#x}, handle {handle})']
    spans = {}
    for name, at in (('free', 4), ('allocated', 8)):
        cells, prev, p = [], 0, u32(array + 12 * handle + at)
        while p and len(cells) < MOST:
            if not ok(p):
                out.append(f'the {name} list: a bad pointer {p:#x} after {len(cells)} cells')
                break
            if u32(p) != prev:
                out.append(f'the {name} list: cell {p:#x} says the one before is {u32(p):#x}, not {prev:#x}')
            if p in {c for c, _ in cells}:
                out.append(f'the {name} list loops at {p:#x}')
                break
            cells.append((p, u32(p + 8)))
            prev, p = p, u32(p + 4)
        spans[name] = cells
    every = sorted([(a, a + n, k) for k in spans for a, n in spans[k]])
    for (a0, a1, k0), (b0, b1, k1) in zip(every, every[1:]):
        if b0 < a1:
            out.append(f'a {k0} cell {a0:#x}+{a1 - a0:#x} and a {k1} cell {b0:#x}+{b1 - b0:#x} overlap')
    free = sorted((a, a + n) for a, n in spans['free'])
    starts = [a for a, _ in free]
    import bisect
    live = [p for order, _ in read(mem)['links'].values() for p in order]
    inside = []
    for p in live:
        i = bisect.bisect_right(starts, p) - 1
        if i >= 0 and free[i][0] <= p < free[i][1]:
            inside.append((p, free[i]))
    for p, (a, b) in inside[:most]:
        out.append(f'live particle {p:#x} lies in a FREE heap cell {a:#x}+{b - a:#x}: {particle(mem, p)}')
    if len(inside) > most:
        out.append(f'... {len(inside)} live particles in free cells in all')
    return out


def state(mem, most_free=200):
    """What `changes` compares, from one snapshot: each link's particles in order with their own fields (a looping
    list ends at the node it loops back to), the head of the free list, and the live generators."""
    u32, u16, u8, ok = _reader(mem)
    got = read(mem)
    links = {}
    for k, (order, end) in got['links'].items():
        if order or end:
            links[k] = dict(order=order, end=end, nodes={p: dict(particle(mem, p), next=hex(u32(p))) for p in order})
    gens = {g: generator(mem, g) for g in got['gens'][0]}
    return dict(links=links, free=got['free'][0][:most_free], used=got['used'], gens=gens)


def listing(before_or_mem, link=None):
    """Each particle of a link, one line each, in list order: from a snapshot or a `state`. link None: every link
    whose walk did not end cleanly."""
    st = before_or_mem if isinstance(before_or_mem, dict) else state(before_or_mem)
    out = []
    for k, row in st['links'].items():
        if (link is None and not row['end']) or (link is not None and k != link):
            continue
        out.append(f'link {k}, {len(row["order"])} particles' + (f', then {row["end"]}' if row['end'] else ''))
        for i, p in enumerate(row['order']):
            n = row['nodes'][p]
            out.append(f'  {i:3d} {n["at"]} next {n["next"]} kind {n["kind"]} bank {n["bank"]} tex {n["tex"]} '
                       f'id {n["id"]} life {n["life"]} gen {n["gen"]}')
    return out


def changes(before, after):
    """What changed in the particle lists between two `state`s (a frame apart): particles that came and went on each
    link, each one that stayed with its next pointer changed, what was taken from and given to the free list, and
    generators that came and went. A loop made in one frame shows here as the write that closed it."""
    out = []
    for k in sorted(set(before['links']) | set(after['links'])):
        b = before['links'].get(k, dict(order=[], nodes={}, end=None))
        a = after['links'].get(k, dict(order=[], nodes={}, end=None))
        came = [p for p in a['order'] if p not in b['nodes']]
        went = [p for p in b['order'] if p not in a['nodes']]
        for p in came:
            n = a['nodes'][p]
            out.append(f'link {k}: came {n["at"]} (node {a["order"].index(p)}) next {n["next"]} kind {n["kind"]} '
                       f'bank {n["bank"]} id {n["id"]} life {n["life"]} gen {n["gen"]}'
                       + (' (it was FREE the frame before)' if p in before['free'] else ''))
        for p in went:
            n = b['nodes'][p]
            out.append(f'link {k}: went {n["at"]} (was node {b["order"].index(p)}, life {n["life"]}, gen {n["gen"]})'
                       + (' (now free)' if p in after['free'] else ' (NOT on the free list)'))
        for p in a['order']:
            if p in b['nodes'] and b['nodes'][p]['next'] != a['nodes'][p]['next']:
                nb, na = b['nodes'][p], a['nodes'][p]
                out.append(f'link {k}: {na["at"]} (node {b["order"].index(p)} -> {a["order"].index(p)}) next '
                           f'{nb["next"]} -> {na["next"]}; life {nb["life"]} -> {na["life"]}, id {nb["id"]} -> {na["id"]}, '
                           f'gen {nb["gen"]} -> {na["gen"]}')
        if a.get('end') and a['end'] != b.get('end'):
            out.append(f'link {k}: now {a["end"]}')
    taken = [p for p in before['free'][:len(before['free'])] if p not in after['free']]
    given = [p for p in after['free'] if p not in before['free']]
    if taken or given:
        out.append(f'free list: taken {[hex(p) for p in taken]}, given {[hex(p) for p in given]} '
                   f'(used {before["used"]} -> {after["used"]})')
    for g in after['gens']:
        if g not in before['gens']:
            out.append(f'generator came {after["gens"][g]}')
    for g in before['gens']:
        if g not in after['gens']:
            out.append(f'generator went {before["gens"][g]}')
    return out


def summary(mem):
    """One line: how many live particles on each link that has any, free, generators live."""
    got = read(mem)
    links = {k: len(o) for k, (o, _) in got['links'].items() if o}
    return (f'particles {links} (pool used {got["used"]}, free {len(got["free"][0])}); '
            f'generators {len(got["gens"][0])} (free {len(got["free_gens"][0])})')
