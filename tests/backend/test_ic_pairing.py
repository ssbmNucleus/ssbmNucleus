"""
Tests for Ice Climbers Popo/Nana pairing in the ISO scan (_pair_ice_climbers).

Vanilla Melee pairs IC costumes by a FIXED colour mapping, not matching codes:
  Popo Nr->Nana Nr, Popo Re->Nana Wh, Popo Or->Nana Aq, Popo Gr->Nana Ye.
Plus a vanilla-Nana pool fallback (a modded Popo whose Nana is unchanged must
still pair with the correct-colour Nana pulled from the ISO).
"""
from tests.paths import BACKEND
import os
import sys
from pathlib import Path

BACKEND_DIR = BACKEND
PROCESSOR_DIR = BACKEND_DIR.parent / 'utility' / 'tools' / 'processor'
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(PROCESSOR_DIR))

from vault.importing.iso_ice_climbers import _pair_ice_climbers, _expected_nana_sufs


def _popo(code, src='iso1', path=None):
    return {'character': 'Ice Climbers', 'costume_code': code,
            'source_iso': src, 'path': path or f'/cand/{code}'}


def _nana(code, src='iso1', path=None):
    return {'character': 'Ice Climbers (Nana)', 'costume_code': code,
            'source_iso': src, 'path': path or f'/cand/{code}'}


def _ics(result):
    return [c for c in result if c['character'] == 'Ice Climbers']


# ------------------------- canonical colour mapping --------------------------

def test_expected_nana_sufs_canonical_then_same():
    assert _expected_nana_sufs('Re') == ['Wh', 'Re']
    assert _expected_nana_sufs('Or') == ['Aq', 'Or']
    assert _expected_nana_sufs('Gr') == ['Ye', 'Gr']
    assert _expected_nana_sufs('Nr') == ['Nr']
    assert _expected_nana_sufs('Bu') == ['Bu']   # custom code -> same-suffix only


def test_all_four_vanilla_pairs_from_candidates():
    pairs = {'PlPpNr.dat': 'PlNnNr.dat', 'PlPpRe.dat': 'PlNnWh.dat',
             'PlPpOr.dat': 'PlNnAq.dat', 'PlPpGr.dat': 'PlNnYe.dat'}
    cands = [_popo(p) for p in pairs] + [_nana(n) for n in pairs.values()]
    res = _pair_ice_climbers(cands)
    paired = {c['costume_code']: c.get('paired_costume_code') for c in _ics(res)}
    assert paired == pairs                              # each Popo got its canonical Nana


# --------------------------- the real-world bug ------------------------------

def test_modded_popo_pairs_with_canonical_vanilla_nana_from_pool():
    # Modded Popo Red; its Nana (White) is unchanged so it's only in the pool.
    res = _pair_ice_climbers([_popo('PlPpRe.dat')],
                             nana_pool={('iso1', 'Wh', 'd'): '/iso/PlNnWh.dat'})
    ics = _ics(res)
    assert ics[0]['paired_path'] == '/iso/PlNnWh.dat'   # correct colour, not solo


def test_does_not_mismatch_with_wrong_colour_candidate():
    # Only a WRONG-colour Nana candidate exists, but the correct White Nana is in
    # the ISO pool. Must use the pool (canonical), NOT guess the wrong candidate.
    res = _pair_ice_climbers(
        [_popo('PlPpRe.dat'), _nana('PlNnAq.dat', path='/cand/PlNnAq.dat')],
        nana_pool={('iso1', 'Wh', 'd'): '/iso/PlNnWh.dat'})
    popo = _ics(res)[0]
    assert popo['paired_path'] == '/iso/PlNnWh.dat'     # White, not Aqua


def test_matches_color_and_extension_slot():
    # 20XX ships several extension slots per colour (PlPpRe.dat/.lat/.rat). Each
    # Popo slot must pair with the SAME-slot Nana, not just any same-colour one.
    cands = [
        _popo('PlPpRe.dat', path='/c/PlPpRe.dat'),
        _popo('PlPpRe.lat', path='/c/PlPpRe.lat'),
        _nana('PlNnWh.dat', path='/c/PlNnWh.dat'),
        _nana('PlNnWh.lat', path='/c/PlNnWh.lat'),
    ]
    res = _pair_ice_climbers(cands)
    by = {os.path.basename(c['path']): os.path.basename(c['paired_path'])
          for c in _ics(res)}
    assert by == {'PlPpRe.dat': 'PlNnWh.dat', 'PlPpRe.lat': 'PlNnWh.lat'}


def test_candidate_canonical_nana_preferred_over_pool():
    res = _pair_ice_climbers(
        [_popo('PlPpRe.dat'), _nana('PlNnWh.dat', path='/cand/PlNnWh.dat')],
        nana_pool={('iso1', 'Wh', 'd'): '/iso/PlNnWh.dat'})
    assert _ics(res)[0]['paired_path'] == '/cand/PlNnWh.dat'


# ---------------------------- custom / fallbacks -----------------------------

def test_custom_matching_code_pack_uses_same_suffix():
    # A custom pack that names both halves PlPpBu / PlNnBu (non-vanilla code).
    res = _pair_ice_climbers(
        [_popo('PlPpBu.dat'), _nana('PlNnBu.dat', path='/cand/PlNnBu.dat')])
    assert _ics(res)[0]['paired_path'] == '/cand/PlNnBu.dat'


def test_guessed_pairing_last_resort():
    # No canonical/same-colour Nana anywhere (pool empty), only an odd leftover
    # candidate Nana -> cross-colour guess so the skin still renders paired.
    res = _pair_ice_climbers(
        [_popo('PlPpRe.dat'), _nana('PlNnGr.dat', path='/cand/PlNnGr.dat')],
        nana_pool={})
    assert _ics(res)[0]['paired_path'] == '/cand/PlNnGr.dat'


def test_truly_unmatched_popo_is_solo():
    res = _pair_ice_climbers([_popo('PlPpRe.dat')], nana_pool={})
    assert not _ics(res)[0].get('paired_path')


def test_pool_is_source_scoped():
    res = _pair_ice_climbers([_popo('PlPpRe.dat', src='isoA')],
                             nana_pool={('isoB', 'Wh', 'd'): '/iso/PlNnWh.dat'})
    assert not _ics(res)[0].get('paired_path')


def test_no_pool_arg_is_backward_compatible():
    res = _pair_ice_climbers([_popo('PlPpRe.dat')])
    assert not _ics(res)[0].get('paired_path')


def test_added_costumes_pair_by_variant_suffix():
    # A Nucleus-built ISO: added costumes carry `Mod` / `_001` after the colour
    # (content code is still the base slot). Each pairs with its own Nana, not
    # the plain slot's.
    cands = [
        _popo('PlPpNr.dat', path='/iso/PlPpNr.dat'),
        _popo('PlPpNr.dat', path='/iso/PlPpNrMod.dat'),
        _popo('PlPpRe.dat', path='/iso/PlPpReMod_001.dat'),
        _nana('PlNnNr.dat', path='/iso/PlNnNrMod.dat'),
        _nana('PlNnWh.dat', path='/iso/PlNnWhMod_001.dat'),
        _nana('PlNnNr.dat', path='/iso/PlNnNr.dat'),
    ]
    res = _pair_ice_climbers(cands)
    paired = {os.path.basename(c['path']): os.path.basename(c['paired_path'])
              for c in _ics(res)}
    assert paired == {'PlPpNr.dat': 'PlNnNr.dat',
                      'PlPpNrMod.dat': 'PlNnNrMod.dat',
                      'PlPpReMod_001.dat': 'PlNnWhMod_001.dat'}
