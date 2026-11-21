"""Preservation-first writer for fighter model-part animation tables.

The caller owns anatomical selection *and* must name the intended ownership
policy.  ``source_full_body`` writes a valid one-node AnimJoint with no AObj,
so the native partial-animation traversal does not acquire anchor ownership.
``partial_anchor`` retains the positive-AObj form as an explicit control for
callers that really do intend the partial path to own an anchor.
"""
from __future__ import annotations

import hashlib
import math
import struct

from .rig_inventory import Archive


def _sha(blob):
    return hashlib.sha256(bytes(blob)).hexdigest()


def _root(dat, name):
    rows = [(n, o) for n, o in dat.roots
            if n == name or name is None and n.startswith("ftData")]
    if len(rows) != 1:
        raise ValueError("Exactly one explicitly selected fighter root required")
    return rows[0]


def _extent(dat, at, size, label):
    """Require bytes to fit both the DAT and their implicit structure extent."""
    dat.require(at, size)
    if dat.struct_end(at) < at + size:
        raise ValueError(f"{label} crosses another structure")


def _anim_tree(dat, root):
    if root is None:
        raise ValueError("NULL partial-animation variant")
    rows, seen, pending = [], set(), [(root, 0)]
    while pending:
        at, depth = pending.pop()
        if at in seen:
            raise ValueError("Repeated/cyclic AnimJoint")
        if depth >= 30:
            raise ValueError("AnimJoint exceeds native depth-30 stack")
        seen.add(at); _extent(dat, at, 0x14, "AnimJoint")
        child, nxt, aobj, robj = (dat.ptr(at + x) for x in (0, 4, 8, 12))
        row = dict(offset=at, depth=depth, child=child, next=nxt,
                   aobj=aobj, robj=robj, flags=dat.u32(at + 0x10))
        if aobj is not None:
            _extent(dat, aobj, 0x10, "AObj")
            end = dat.f32(aobj + 4)
            if not math.isfinite(end):
                raise ValueError("Partial-animation AObj has nonfinite duration")
            row["aobj_fields"] = dict(flags=dat.u32(aobj), end_frame=end,
                fobj=dat.ptr(aobj + 8), object_reference=dat.ptr(aobj + 12))
        rows.append(row)
        if nxt is not None: pending.append((nxt, depth))
        if child is not None: pending.append((child, depth + 1))
    first = next((r["aobj_fields"] for r in rows if "aobj_fields" in r), None)
    return rows, 0.0 if first is None else first["end_frame"]


def inventory(payload, *, root_name=None, joint_count=None):
    dat = Archive(payload); name, fighter = _root(dat, root_name)
    table = dat.ptr(fighter + 0x1C)
    if table is None:
        raise ValueError("Missing model-part table")
    extent = dat.struct_end(table) - table
    if extent <= 0 or extent % 4 or extent // 4 > 5:
        raise ValueError("Invalid model-part pointer table extent")
    _extent(dat, table, extent, "Model-part pointer table")
    parts = []
    for slot in range(extent // 4):
        header = dat.ptr(table + 4 * slot)
        if header is None:
            raise ValueError("NULL model-part header")
        _extent(dat, header, 0x0C, "Model-part header")
        starting, count = struct.unpack_from(">hh", dat.buf, 32 + header)
        if starting < 0 or count <= 0 or count > 255:
            raise ValueError("Invalid model-part starting bone/count")
        if joint_count is not None and (not 1 <= joint_count <= 256 or starting >= joint_count):
            raise ValueError("Model-part starting bone outside measured joint domain")
        entries, variants = dat.ptr(header + 4), dat.ptr(header + 8)
        if entries is None or variants is None:
            raise ValueError("Model-part arrays must be non-NULL")
        _extent(dat, entries, count, "Model-part member array")
        members = list(dat.buf[32 + entries:32 + entries + count])
        if joint_count is not None and any(v >= joint_count for v in members):
            raise ValueError("Model-part member outside measured joint domain")
        variant_extent = dat.struct_end(variants) - variants
        if variant_extent <= 0 or variant_extent % 4 or variant_extent // 4 > 32:
            raise ValueError("Invalid model-part variant pointer extent")
        _extent(dat, variants, variant_extent, "Model-part variant array")
        anims, durations = [], []
        for variant in range(variant_extent // 4):
            anim = dat.ptr(variants + 4 * variant)
            tree, duration = _anim_tree(dat, anim)
            anims.append(dict(variant=variant, root=anim, nodes=tree,
                              duration=duration,
                              aobj_count=sum("aobj_fields" in n for n in tree)))
            durations.append(duration)
        parts.append(dict(slot=slot, header=header, starting_bone=starting,
                          count=count, entries=entries, members=members,
                          variants=variants, variant_count=len(anims),
                          durations=durations, animations=anims))
    return dict(fighter_root=name, fighter_offset=fighter, table=table,
                slot_count=len(parts), parts=parts)


def stateful_replay(payload, *, root_name, joint_count, ownership,
                    skip_parts=(), initial_flags_b5=False,
                    initial_flags_b0=False, auxiliary_srt=-100.0):
    """Bounded state replay of the native branches used by model-part apply.

    Scalar SRT witnesses intentionally model state transitions, not geometry or
    full native playback.  Native ``ftParts_8007506C`` skips shift traversal to
    the next part; this bounded replay refuses a skipped anchor instead of trying
    to model that shift.  Callers must not treat an empty skip set as runtime proof.
    """
    if ownership not in {"source_full_body", "partial_anchor"}:
        raise ValueError("Explicit ownership policy required")
    if type(initial_flags_b5) is not bool or type(initial_flags_b0) is not bool:
        raise ValueError("Initial ownership flags must be explicit booleans")
    if not isinstance(skip_parts, (tuple, list, set)):
        raise ValueError("Explicit ftParts_8007506C skip set required")
    inv = inventory(payload, root_name=root_name, joint_count=joint_count)
    skips = set(skip_parts)
    poses = [0.0, 1.25, -2.5, 4.0]

    def episode(part, anim, blend, restore):
        nodes = anim["nodes"]
        if len(nodes) != 1:
            raise ValueError("Bounded replay requires one AnimJoint")
        node = nodes[0]
        if any(node[k] is not None for k in ("child", "next", "robj")):
            raise ValueError("Bounded replay requires child/next/RObj NULL")
        aobj = node.get("aobj_fields")
        if aobj is not None and (aobj["fobj"] is not None or
                                 aobj["object_reference"] is not None):
            raise ValueError("Bounded replay requires no FObj/object reference")
        if ownership == "source_full_body" and aobj is not None:
            raise ValueError("source_full_body policy must contain zero AObjs")
        if ownership == "partial_anchor" and (aobj is None or anim["duration"] <= 0):
            raise ValueError("partial_anchor policy requires positive-duration AObj")
        anchor = part["starting_bone"]
        if anchor in skips:
            raise ValueError("Replay anchor is skipped by explicit ftParts_8007506C metadata")
        flags_b5, flags_b0 = initial_flags_b5, initial_flags_b0
        real, auxiliary = poses[0], auxiliary_srt

        def apply_once():
            nonlocal flags_b5
            # ftAnim_80070904 calls JObjAddAnim and sets b5 only when both
            # !b0 and aobjdesc != NULL.
            if not flags_b0 and aobj is not None:
                flags_b5 = True

        apply_once(); apply_once()  # repeated application must remain safe
        duration = anim["duration"]
        rate = 0.0 if blend == 0.0 else duration / blend
        x8 = 0.0
        samples = []
        for authored in poses[1:]:
            # Existing full-body SRT update owns unflagged joints.
            if not flags_b5 and not flags_b0:
                real = authored
            x8 += rate
            if blend <= x8:       # 800707B0 tests this before its division
                x8 = blend
                partial_weight = 1.0
            else:
                partial_weight = rate / (rate + (blend - x8))
            if flags_b5:
                real = real * (1.0 - partial_weight) + auxiliary * partial_weight
            samples.append(dict(full_body=authored, resulting_srt=real,
                                flags_b5=flags_b5))
        before_restore = flags_b5
        if restore == "80070CC4":
            flags_b5 = False  # recursive AnimJoint walk clears traversed anchor
        elif restore == "80070F28":
            if anchor not in part["members"]:
                raise ValueError("Full reset list cannot clear anchor ownership")
            flags_b5 = False  # member-array reset clears the listed anchor
        else:
            raise ValueError("Unknown restore path")
        return dict(slot=part["slot"], variant=anim["variant"], blend=blend,
                    duration=duration, rate=rate, aobj_count=anim["aobj_count"],
                    repeated_apply=True, samples=samples,
                    took_ownership=before_restore,
                    follows_full_body=all(x["resulting_srt"] == x["full_body"]
                                          for x in samples),
                    restore=restore, flags_b5_after_restore=flags_b5)

    cases = []
    for part in inv["parts"]:
        for anim in part["animations"]:
            for blend, restore in ((0.0, "80070CC4"), (4.0, "80070F28")):
                cases.append(episode(part, anim, blend, restore))

    # Exercise variants across slots in non-monotonic order.  Each episode is
    # isolated: this catches accidental variant selection/sharing, but is not a
    # persistent or simultaneous multi-slot interaction simulation.
    cross_order = []
    order = [(p, a) for p in inv["parts"] for a in reversed(p["animations"])]
    for index, (part, anim) in enumerate(reversed(order)):
        row = episode(part, anim, float(index % 2) * 4.0,
                      "80070CC4" if index % 2 == 0 else "80070F28")
        cross_order.append(dict(slot=row["slot"], variant=row["variant"],
                                follows_full_body=row["follows_full_body"],
                                restored=not row["flags_b5_after_restore"]))
    return dict(schema="model-parts-stateful-replay-v1", ownership=ownership,
                assumptions=dict(initial_flags_b5=initial_flags_b5,
                    initial_flags_b0=initial_flags_b0,
                    auxiliary_srt=auxiliary_srt,
                    full_body_srt_sequence=poses,
                    ftParts_8007506C_skip_parts=sorted(skips),
                    skip_metadata_runtime_proven=False),
                cases=cases, cross_slot_order=cross_order,
                cross_slot_order_scope=("Isolated episodes in non-monotonic slot order; "
                                        "no simultaneous/persistent slot interaction proof"),
                all_variants_tested=sum(p["variant_count"] for p in inv["parts"]),
                replay_scope=("Simplified scalar apply/partial-tick/b5-clear replay; not full "
                              "native playback. CC4 subtree rest/re-key reload and action-change "
                              "80070F28+80070E74 reset/re-arm lifetime are unmodeled."))


def apply(payload, *, root_name, joint_count, parts, ownership):
    """Return bytes with private model-part headers under an explicit policy."""
    if not isinstance(root_name, str) or not root_name.strip():
        raise ValueError("Explicit nonempty root name required for mutation")
    if ownership not in {"source_full_body", "partial_anchor"}:
        raise ValueError("Explicit ownership policy required")
    if type(joint_count) is not int or not 1 <= joint_count <= 256:
        raise ValueError("Explicit measured joint domain from 1 through 256 required")
    before = Archive(payload); name, fighter = _root(before, root_name)
    old = inventory(payload, root_name=root_name, joint_count=None)
    if not isinstance(parts, list) or len(parts) != old["slot_count"]:
        raise ValueError("Explicit policy for every existing model-part slot required")
    dat = Archive(payload); original_size = dat.data_size
    original_data = bytes(dat.buf[32:32 + original_size]); original_relocs = set(dat.relocs)
    # Reserve the pointer table first.  The first subsequently referenced
    # allocation is then an explicit target boundary, so future appends cannot
    # be mistaken for extra variants/slots by DAT's implicit extent model.
    new_table = dat.append_struct(bytes(old["slot_count"] * 4), align=4)
    new_headers, part_receipts = [], []
    for prior, policy in zip(old["parts"], parts):
        if set(policy) != {"starting_bone", "members", "classical_scale"}:
            raise ValueError("Exact model-part policy fields required")
        start, members, classical = (policy[k] for k in
                                     ("starting_bone", "members", "classical_scale"))
        if type(start) is not int or not 0 <= start < joint_count:
            raise ValueError("Starting bone outside measured joint domain")
        if (not isinstance(members, list) or not members or len(members) > 255 or
                any(type(v) is not int or not 0 <= v < joint_count for v in members)):
            raise ValueError("Nonempty byte-indexed member list required")
        if start not in members:
            raise ValueError("Member list must include starting bone for full reset")
        if type(classical) is not bool:
            raise ValueError("classical_scale must be bool")
        member_ptr = dat.append_struct(bytes(members), align=4)
        variant_roots = []
        for duration in prior["durations"]:
            if ownership == "partial_anchor":
                if not math.isfinite(duration) or duration <= 0:
                    raise ValueError("partial_anchor requires positive finite duration")
                aobj = dat.append_struct(struct.pack(">IfII", 0, duration, 0, 0), align=4)
                anim = dat.append_struct(struct.pack(">IIIII", 0, 0, aobj, 0,
                                                     1 if classical else 0), [8], align=4)
            else:
                anim = dat.append_struct(struct.pack(">IIIII", 0, 0, 0, 0,
                                                     1 if classical else 0), align=4)
            variant_roots.append(anim)
        array_blob = struct.pack(">" + "I" * len(variant_roots), *variant_roots)
        variants = dat.append_struct(array_blob, range(0, len(array_blob), 4), align=4)
        header_blob = struct.pack(">hhII", start, len(members), member_ptr, variants)
        header = dat.append_struct(header_blob, [4, 8], align=4)
        new_headers.append(header)
        part_receipts.append(dict(slot=prior["slot"], old_header=prior["header"],
            new_header=header, starting_bone=start, members=members,
            variant_count=prior["variant_count"], source_durations=prior["durations"],
            classical_scale=classical, member_array=member_ptr,
            variant_array=variants, anim_roots=variant_roots,
            output_aobj_count=0 if ownership == "source_full_body" else len(variant_roots)))
    for slot, header in enumerate(new_headers):
        dat.set_u32(new_table + 4 * slot, header)
        dat.add_reloc(new_table + 4 * slot)
    dat.set_u32(fighter + 0x1C, new_table); dat.add_reloc(fighter + 0x1C)
    result = dat.to_bytes(); after = Archive(result)
    unchanged = bytearray(after.buf[32:32 + original_size])
    unchanged[fighter + 0x1C:fighter + 0x20] = original_data[fighter + 0x1C:fighter + 0x20]
    if bytes(unchanged) != original_data or not original_relocs <= after.relocs:
        raise ValueError("Unexpected mutation outside model-part table pointer")
    final = inventory(result, root_name=root_name, joint_count=joint_count)
    replay = stateful_replay(result, root_name=root_name, joint_count=joint_count,
                             ownership=ownership, skip_parts=(),
                             initial_flags_b5=False, initial_flags_b0=False,
                             auxiliary_srt=-100.0)
    if [p["variant_count"] for p in final["parts"]] != [p["variant_count"] for p in old["parts"]]:
        raise ValueError("Variant domain changed")
    if ownership == "source_full_body":
        if any(a["aobj_count"] for p in final["parts"] for a in p["animations"]):
            raise ValueError("Non-owning output unexpectedly contains AObj")
        if not all(c["follows_full_body"] and not c["took_ownership"]
                   for c in replay["cases"]):
            raise ValueError("Non-owning replay did not preserve full-body ownership")
    return result, dict(schema="model-parts-explicit-ownership-v2",
        status="TRANSFORM_MODEL_PART_POLICY_WRITTEN_OFFLINE",
        input_sha256=_sha(payload), output_sha256=_sha(result),
        ownership=ownership,
        fighter_root=name, joint_count=joint_count, old_table=old["table"],
        new_table=new_table, slot_count=old["slot_count"], parts=part_receipts,
        old_data_unchanged_except_pointer=fighter + 0x1C,
        old_data_preserved=True, old_relocations_preserved=True,
        old_structures_preserved=True, replay=replay,
        no_fobj_descriptors=True,
        output_aobj_count=sum(a["aobj_count"] for p in final["parts"]
                              for a in p["animations"]),
        ownership_effect=("No AObj is reachable, so the modeled apply path does not "
                          "set flags_b5 or suppress changing full-body SRT."
                          if ownership == "source_full_body" else
                          "Positive AObj takes flags_b5 ownership; control only."),
        item_specific_pose_recovered=False, runtime_proven=False)
