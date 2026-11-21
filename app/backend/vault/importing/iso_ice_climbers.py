"""
Pairing Ice Climbers costumes found on a disc: each Popo DAT is matched with
the Nana DAT of the same colour (and slot) from the same ISO, so the vault
stores them as one pair.
"""

from __future__ import annotations

import logging
import os
from typing import Optional
from vault.importing.iso_costume_files import _split_costume_stem

logger = logging.getLogger(__name__)


# Vanilla Melee pairs IC costumes by a FIXED colour mapping, NOT matching codes:
# Popo and Nana use different colour codes for the same costume slot (only the
# 'Nr' default matches). Mirrors character_detector.POPO_TO_NANA. Matching by
# raw suffix paired everything except Default wrong (or not at all).
_POPO_TO_NANA_CODE = {'Nr': 'Nr', 'Re': 'Wh', 'Or': 'Aq', 'Gr': 'Ye'}


def _expected_nana_sufs(popo_suf: Optional[str]) -> list[str]:
    """Nana colour suffixes for a Popo colour, best-first: the canonical vanilla
    pairing, then the same suffix (custom packs that name both halves alike)."""
    out: list[str] = []
    canon = _POPO_TO_NANA_CODE.get(popo_suf)
    if canon:
        out.append(canon)
    if popo_suf and popo_suf not in out:
        out.append(popo_suf)
    return out


def _ic_key(entry: dict) -> tuple[Optional[str], str]:
    """(colour, slot) identity for an IC costume candidate, from its FILE name.
    colour = last 2 chars of the PlPp/PlNn stem; slot = first char of the
    extension (.dat->'d', .lat->'l', .rat->'r', ...). Popo↔Nana must match BOTH
    the (canonical) colour AND the slot — 20XX ships several extension slots per
    colour (PlPpRe.dat/.lat/.rat), so colour alone collides. An m-ex added
    costume's variant suffix is part of the slot too: PlPpNrMod_001 pairs with
    PlNnNrMod_001."""
    name = os.path.basename(entry.get('path') or entry.get('costume_code') or '')
    stem, ext = os.path.splitext(name)
    colour = stem[-2:] if len(stem) >= 4 else None
    slot = (ext.lstrip('.')[:1] or 'd').lower()
    parts = _split_costume_stem(stem)
    if parts:
        colour = parts[1]
        slot += parts[2]
    return colour, slot


def _pair_ice_climbers(pre_candidates: list[dict],
                       nana_pool: Optional[dict] = None) -> list[dict]:
    """Combine Popo + Nana DATs from the same (source_iso, color) into a single
    paired 'Ice Climbers' candidate. Unmatched halves pass through as solo
    entries — never silently dropped.

    nana_pool maps (source_iso, color_suffix) -> Nana DAT path for EVERY Nana in
    the ISO (incl. vanilla ones filtered out of candidates). It lets a modded
    Popo whose Nana is unchanged still pair with the correct same-colour Nana,
    instead of rendering a Nana-less solo CSP."""
    popo = [c for c in pre_candidates if c['character'] == 'Ice Climbers']
    nana = [c for c in pre_candidates if c['character'] == 'Ice Climbers (Nana)']
    other = [c for c in pre_candidates
             if c['character'] not in ('Ice Climbers', 'Ice Climbers (Nana)')]

    logger.info(
        f"[iso-scan][ic] entering pairing: {len(popo)} Popo, "
        f"{len(nana)} Nana, {len(other)} other characters"
    )
    for p in popo:
        logger.info(
            f"[iso-scan][ic]   Popo: code={p.get('costume_code')!r:14} "
            f"key={_ic_key(p)!r} source={p.get('source_iso')!r}"
        )
    for n in nana:
        logger.info(
            f"[iso-scan][ic]   Nana: code={n.get('costume_code')!r:14} "
            f"key={_ic_key(n)!r} source={n.get('source_iso')!r}"
        )

    # Index Nana by (source, colour, slot). Each Nana can be claimed once.
    nana_index: dict[tuple, dict] = {}
    for n in nana:
        ncolour, nslot = _ic_key(n)
        if ncolour:
            nana_index.setdefault((n['source_iso'], ncolour, nslot), n)

    paired: list[dict] = []
    unmatched_popo: list[dict] = []
    for p in popo:
        pcolour, pslot = _ic_key(p)
        match = None
        for ecolour in _expected_nana_sufs(pcolour):
            match = nana_index.pop((p['source_iso'], ecolour, pslot), None)
            if match:
                break
        if not match:
            unmatched_popo.append(p)
            continue
        out = dict(p)
        out['paired_path'] = match['path']
        out['paired_costume_code'] = match['costume_code']
        logger.info(
            f"[iso-scan][ic] PAIR {p.get('costume_code')} <-> "
            f"{match.get('costume_code')}  (colour={pcolour!r} slot={pslot!r}, "
            f"source={p.get('source_iso')!r}) — canonical colour+slot pairing"
        )
        paired.append(out)

    # Pool fallback: a modded Popo whose Nana is UNCHANGED has no Nana candidate
    # (the vanilla Nana was filtered out as vanilla), so it would otherwise
    # render a Nana-less solo CSP. Pull the same-colour Nana straight from the
    # ISO's extracted files. This runs BEFORE the cross-colour guess so we use
    # the *correct* colour Nana whenever the ISO has one.
    still_unmatched: list[dict] = []
    pool_pairs = 0
    for p in unmatched_popo:
        pcolour, pslot = _ic_key(p)
        pool_nana = None
        if nana_pool:
            for ecolour in _expected_nana_sufs(pcolour):
                pool_nana = nana_pool.get((p['source_iso'], ecolour, pslot))
                if pool_nana:
                    break
        if not pool_nana:
            still_unmatched.append(p)
            continue
        out = dict(p)
        out['paired_path'] = pool_nana
        out['paired_costume_code'] = os.path.splitext(os.path.basename(pool_nana))[0]
        logger.info(
            f"[iso-scan][ic] PAIR {p.get('costume_code')} <-> "
            f"{os.path.basename(pool_nana)}  (colour={pcolour!r} slot={pslot!r}, "
            f"source={p.get('source_iso')!r}) — canonical Nana from ISO"
        )
        paired.append(out)
        pool_pairs += 1

    # Guessed pairing for ISOs where Popo/Nana don't share suffixes AND the ISO
    # has no same-colour Nana at all (e.g. Akaneia ships PlPpNr + PlPpBu +
    # PlNnGr). Greedy pairing-by-order within the same source ISO is the
    # practical heuristic — "we kind of just have to guess".
    leftover_nana = list(nana_index.values())
    by_source_popo: dict[str, list[dict]] = {}
    for p in still_unmatched:
        by_source_popo.setdefault(p['source_iso'], []).append(p)
    by_source_nana: dict[str, list[dict]] = {}
    for n in leftover_nana:
        by_source_nana.setdefault(n['source_iso'], []).append(n)

    guess_pairs = 0
    for source, popos in by_source_popo.items():
        nanas = by_source_nana.get(source, [])
        for p, n in zip(popos, nanas):
            out = dict(p)
            out['paired_path'] = n['path']
            out['paired_costume_code'] = n['costume_code']
            logger.info(
                f"[iso-scan][ic] PAIR {p.get('costume_code')} <-> "
                f"{n.get('costume_code')}  (suf mismatch, "
                f"source={source!r}) — guessed pairing"
            )
            paired.append(out)
            guess_pairs += 1
        # Anything left over in popos beyond min(len(popos), len(nanas)) is
        # truly unmatched — pair with a placeholder Nana=None so generate_csp
        # falls through to solo render rather than dropping the skin entirely.
        for p in popos[len(nanas):]:
            logger.info(
                f"[iso-scan][ic] SOLO Popo {p.get('costume_code')!r} — no "
                f"Nana left to guess-pair in source={source!r}, rendering solo"
            )
            paired.append(dict(p))
        for n in nanas[len(popos):]:
            # Lone Nana with no Popo at all: solo Nana — generate_csp's Ice
            # Climbers path renders her solo when no pair_file is provided.
            logger.info(
                f"[iso-scan][ic] SOLO Nana {n.get('costume_code')!r} — no "
                f"Popo left to guess-pair in source={source!r}, rendering solo"
            )
            paired.append(dict(n))

    # Nanas whose source had no unmatched Popos at all:
    for source, nanas in by_source_nana.items():
        if source in by_source_popo:
            continue  # already handled in the loop above
        for n in nanas:
            logger.info(
                f"[iso-scan][ic] SOLO Nana {n.get('costume_code')!r} — no "
                f"unmatched Popo in source={source!r}, rendering solo"
            )
            paired.append(dict(n))

    solo = sum(1 for x in paired if not x.get('paired_path'))
    logger.info(
        f"[iso-scan][ic] pairing done: {len(paired)} entries "
        f"({len(paired) - pool_pairs - guess_pairs - solo} exact-suffix pairs, "
        f"{pool_pairs} same-colour-from-ISO pairs, "
        f"{guess_pairs} guessed pairs, {solo} solo)"
    )
    return other + paired
