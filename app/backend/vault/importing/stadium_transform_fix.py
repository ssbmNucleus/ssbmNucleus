"""Pokemon Stadium transformation-visibility repair for custom stage variants.

Community Stadium skins (model swaps) leave their floating side platforms
visible during the fire/grass/rock/water transformations: the engine hides
exactly one map_head model group during a form -- group 5, the "normal form"
group where vanilla keeps its two platforms -- and mod authors put their
platform geometry in the permanent groups (1/2) instead.  The platforms'
COLLISION is already toggled off during forms (the coll lines sit in the
normal-form coll group), so the lingering visuals are walk-through ghosts.
The repair relocates those visuals into group 5 so the engine's own
hide/restore logic applies; gameplay is unchanged.

Separable variants are repaired by geometric duplicate detection: a group-1/2
piece matching a group-5 piece is the redundant persistent copy and is moved
into group 5.  Fully baked imports are handled by conservative playfield
classification and display-list splitting.  Standard collision-space and
mesh-relative anchors cover the welded corpus.  Only thin walking-surface
layers and raised side-platform layers are moved: the arena skirt, ledge
border, stairs, supports, and facade are permanent Stadium geometry and must
remain visible during a transformation.

All surgery is in-file pointer unlinking plus relocation-table upkeep (a
pointer field that becomes NULL loses its reloc entry).  CLI dry-run:

    python -m vault.importing.stadium_transform_fix <GrPs-variant.dat> [--apply out.dat]

This module is the separable-variant repair (plan, apply) and the entry point
repair_stadium_variant. The archive model and pointer surgery are
stadium_dat.py, the baked-variant split stadium_baked_split.py, and freezing the
stage on its normal form stadium_freeze.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from vault.importing.stadium_dat import (GROUP_NORMAL, CANDIDATE_GROUPS, RepairError, Dat,
    dobj_chain, dobj_bbox, _groups, _walk_subtree, _unlink_child, _append_child,
    _extract_dobjs, _new_bare_jobj)
from vault.importing.stadium_baked_split import (ENABLE_BAKED_SPLIT, _has_baked_split_carrier,
    split_baked_platforms)


# -- analysis -------------------------------------------------------------

@dataclass
class Plan:
    jobj_moves: list = field(default_factory=list)  # (group, parent, jobj)
    dobj_moves: list = field(default_factory=list)  # (group, host, [dobjs])
    notes: list = field(default_factory=list)

    @property
    def empty(self):
        return not self.jobj_moves and not self.dobj_moves


def build_plan(dat) -> Plan:
    plan = Plan()
    roots = _groups(dat)
    if roots[GROUP_NORMAL] is None:
        plan.notes.append("group 5 root missing -- nothing to compare against")
        return plan

    g5_boxes = []
    for _, jobj, wt, ws in _walk_subtree(dat, roots[GROUP_NORMAL]):
        for d in dobj_chain(dat, jobj):
            box = dobj_bbox(dat, d, wt, ws)
            if box.npos:
                g5_boxes.append(box)
    if not g5_boxes:
        plan.notes.append("group 5 has no decodable geometry -- baked-in "
                          "variant, flag for manual repair")
        return plan

    for gi in CANDIDATE_GROUPS:
        root = roots[gi]
        if root is None:
            continue
        for parent, jobj, wt, ws in _walk_subtree(dat, root):
            dobjs = dobj_chain(dat, jobj)
            if not dobjs:
                continue
            boxes = [dobj_bbox(dat, d, wt, ws) for d in dobjs]
            dup = [any(b.duplicates(g5b) for g5b in g5_boxes) for b in boxes]
            if not any(dup):
                continue
            if (all(dup) and parent is not None
                    and not dat.valid(dat.u32(jobj + 0x08))):
                plan.jobj_moves.append((gi, parent, jobj))
            elif abs(ws - 1.0) < 1e-6 and all(abs(c) < 1e-4 for c in wt):
                # dobj extraction re-hosts under an identity carrier jobj, so
                # only extract from identity-transform hosts
                hits = [d for d, f in zip(dobjs, dup) if f]
                plan.dobj_moves.append((gi, jobj, hits))
            else:
                plan.notes.append(
                    f"group {gi} jobj@0x{jobj:X}: duplicate dobjs on a "
                    f"transformed host -- flagged for manual repair")
    return plan


def apply_plan(dat, plan: Plan) -> list:
    """Execute the plan; returns a human-readable action log."""
    log = []
    g5root = _groups(dat)[GROUP_NORMAL]
    for gi, parent, jobj in plan.jobj_moves:
        _unlink_child(dat, parent, jobj)
        _append_child(dat, g5root, jobj)
        log.append(f"moved duplicate jobj@0x{jobj:X} from group {gi} to "
                   f"group 5 (hides with the normal form)")
    for gi, host, hits in plan.dobj_moves:
        head = _extract_dobjs(dat, host, hits)
        carrier = _new_bare_jobj(dat)
        dat.set_u32(carrier + 0x10, head)
        dat.reloc_add(carrier + 0x10)
        _append_child(dat, g5root, carrier)
        log.append(f"moved {len(hits)} duplicate dobjs from jobj@0x{host:X} "
                   f"(group {gi}) to a new group-5 jobj")
    return log


def repair_stadium_variant(data: bytes) -> tuple:
    """Main entry: returns (repaired_bytes_or_None, report_dict)."""
    report = {"status": "clean", "actions": [], "notes": []}
    try:
        dat = Dat(data)
        plan = build_plan(dat)
    except RepairError as e:
        report["status"] = "skipped"
        report["notes"].append(str(e))
        return None, report
    report["notes"] = plan.notes
    if plan.empty:
        baked = any("no decodable geometry" in n for n in plan.notes)
        broad_overlay = not plan.notes and not baked
        # Primitive splitting creates direct group-5 carriers whose draw
        # objects deliberately reuse the source material and vertex
        # descriptor.  That shared pair is a durable repair signature.  On a
        # later import, the first split's group-5 geometry can otherwise make
        # the remaining permanent rim look like a fresh broad overlay and get
        # carved away in a second pass.
        if _has_baked_split_carrier(dat):
            return None, report
        if ENABLE_BAKED_SPLIT and (baked or broad_overlay):
            # Empty-group-5 imports need ordinary playfield classification.
            # A second class keeps vanilla group-5 geometry but overlays a
            # much larger custom arena in a permanent group; only permit the
            # large-arena fallback there so stock/texture-only Stadium files
            # with standard anchors remain untouched.
            try:
                actions = split_baked_platforms(
                    dat, broad_only=broad_overlay)
            except RepairError as e:
                report["status"] = "flagged"
                report["notes"].append(f"primitive split failed: {e}")
                return None, report
            if actions:
                report["status"] = "repaired"
                report["actions"] = actions
                report["notes"] = [n for n in plan.notes
                                   if "no decodable geometry" not in n]
                return bytes(dat.b), report
        if plan.notes:
            report["status"] = "flagged"
        return None, report
    try:
        report["actions"] = apply_plan(dat, plan)
    except RepairError as e:
        report["status"] = "failed"
        report["notes"].append(str(e))
        return None, report
    report["status"] = "repaired"
    return bytes(dat.b), report


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser()
    ap.add_argument("dat")
    ap.add_argument("--apply", metavar="OUT")
    args = ap.parse_args()
    raw = open(args.dat, "rb").read()
    fixed, rep = repair_stadium_variant(raw)
    print(json.dumps(rep, indent=2))
    if args.apply and fixed:
        open(args.apply, "wb").write(fixed)
        print("wrote", args.apply)
