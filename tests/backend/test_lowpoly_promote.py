"""Diet Melee import repair (shared.rendering.lowpoly_promote) — safety properties.

The live transform (promote + matanim remap + sanitize + blink shims) was
verified in-game against Diet Melee 64 v1.03 (raw import hangs a
vanilla-engine build at match load; transformed import boots with the
intended N64 model). These tests pin the offline invariants: the planner
must never fire on vanilla/normally-authored files, and the ftData readers
must keep producing the engine's numbers.

Needs the vanilla reference DATs (extracted on demand from the recorded
vanilla ISO); skips cleanly where no vanilla ISO has been recorded.
"""

import pytest

from shared.rendering import lowpoly_promote as lp


def _ref(name):
    from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
    try:
        path = ensure_vanilla_ref(name)
    except Exception:
        path = None
    if not path:
        pytest.skip(f"no vanilla reference available for {name}")
    return path


def test_ness_visibility_sets_match_engine():
    high, low = lp.visibility_sets(_ref('PlNs.dat'))
    assert low == list(range(25, 51))
    assert high == list(range(0, 25)) + list(range(51, 70))


def test_bowser_visibility_sets_match_engine():
    high, low = lp.visibility_sets(_ref('PlKp.dat'))
    assert low == (list(range(29, 78)) + [100, 103, 106, 109, 112])
    assert len(high) == 61 and 0 in high and 114 in high


def test_blink_indices_read_ftdata():
    # ftData->x8->x8: Ness demands animated TObjs at walk indices [10, 8]
    assert lp.blink_indices(_ref('PlNs.dat')) == [10, 8]


def test_falcon_has_no_blink_requirement():
    assert lp.blink_indices(_ref('PlCa.dat')) == []


def test_vanilla_ness_satisfies_its_own_blink_walk():
    animated = lp.animated_walk_indices(_ref('PlNsNr.dat'))
    assert animated.get(8) == 3 and animated.get(10) == 3
    assert lp.verify_blink(_ref('PlNsNr.dat'), [10, 8])


def test_vanilla_carries_no_diet_fingerprint():
    assert lp.stripped_tex_materials(_ref('PlNsNr.dat')) == 0
    assert lp.stripped_tex_materials(_ref('PlKpNr.dat')) == 0


def test_planner_never_fires_on_vanilla():
    plan = lp.plan_diet_fix(_ref('PlNsNr.dat'), _ref('PlNsNr.dat'),
                            _ref('PlNs.dat'))
    assert not plan.promote
    # even when the source ISO looks diet-like, an unchanged low set is a no-op
    plan = lp.plan_diet_fix(_ref('PlNsNr.dat'), _ref('PlNsNr.dat'),
                            _ref('PlNs.dat'), diet_source=True)
    assert not plan.promote


def test_vanilla_iso_entry_point_not_flagged(tmp_path):
    from shared.vanilla_extract.vanilla_refs import known_vanilla_iso
    iso = known_vanilla_iso()
    if not iso:
        pytest.skip("no recorded vanilla ISO")
    assert not lp.dol_entry_hacked(iso)
    # and unreadable input never raises
    assert lp.dol_entry_hacked(tmp_path / 'missing.iso') is False


def test_texture_comparator_tolerates_none():
    same = ((1, 2, 2, b'x', b''), [(10, 10, 10)] * 16)
    other = ((1, 2, 2, b'y', b''), [(200, 10, 10)] + [(10, 10, 10)] * 15)
    undecodable = ((1, 2, 2, b'z', b''), None)
    assert lp._textures_match(same, same)
    assert not lp._textures_match(same, other)
    assert not lp._textures_match(same, undecodable)
    # byte-identical undecodable textures still match via the byte key
    assert lp._textures_match(undecodable, undecodable)
