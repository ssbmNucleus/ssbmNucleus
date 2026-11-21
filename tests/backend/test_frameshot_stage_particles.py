"""frameshot.kill_stage_particles relinks the game's particle lists only with the game frozen.

Unfrozen, the walk races the game's own particle update: a particle freed between the read of a next pointer and its
write goes back on a live list, which loops when the pool hands it out again, and the game hangs drawing particles
(the fighterport G19 stop, 2026-11-13).
"""
from devtools import frameshot as f


class _Mem:
    def __init__(self):
        self.m, self.log = {}, []

    def u32(self, a):
        return self.m.get(a, 0)

    def u8(self, a):
        return self.m.get(a, 0)

    def write_u32(self, a, v):
        self.log.append(('write', a))
        self.m[a] = v


def test_the_stage_particles_are_unlinked_only_with_the_game_frozen(monkeypatch):
    d, frozen = _Mem(), {'on': False}
    monkeypatch.setattr(f.framestep, 'is_frozen', lambda _d: frozen['on'])
    monkeypatch.setattr(f.framestep, 'freeze', lambda _d: (d.log.append(('freeze',)), frozen.update(on=True)))
    monkeypatch.setattr(f.framestep, 'unfreeze', lambda _d: (d.log.append(('unfreeze',)), frozen.update(on=False)))
    monkeypatch.setattr(f.framestep, 'wait_render_frames', lambda _d, n=2, **_k: n)
    # link 0: a stage particle (bank 0x1E) at the head, then one of a fighter's
    d.m[f._PS_PART_HEADS] = 0x80001000
    d.m[0x80001000], d.m[0x80001000 + 8] = 0x80002000, f._PS_STAGE_BANK
    d.m[0x80002000], d.m[0x80002000 + 8] = 0, 3

    f.kill_stage_particles(d)
    assert d.log[0] == ('freeze',) and d.log[-1] == ('unfreeze',)
    assert ('write', f._PS_PART_HEADS) in d.log
    assert d.m[f._PS_PART_HEADS] == 0x80002000        # the stage particle is out, the fighter's stays

    # a capture that is already stepping frozen stays frozen
    d.log.clear()
    frozen['on'] = True
    d.m[f._PS_PART_HEADS] = 0x80001000
    f.kill_stage_particles(d)
    assert ('freeze',) not in d.log and ('unfreeze',) not in d.log
    assert d.m[f._PS_PART_HEADS] == 0x80002000
