"""
Execution evidence for a costume verification (verify_costume.py), read back
from RAM and from the built disc: the ground and character kind tables, one
measured check record, whether the intended candidate was inserted, selected,
booted and captured at the requested states, and which file the build added
to the disc.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


# --- RAM ground truth (decomp) ------------------------------------------------ #
# StageInfo.grkind values for the stages this profile can run on. Source:
# melee decomp src/melee/gr/forward.h `enum GrKind`. The ground kind is NOT the
# SSS icon index and NOT the internal stage id -- see shared/ingame/stage_state.py.
GROUND_KIND = {
    "finaldestination": 0x25,   # Gr_Kind_Last
    "battlefield": 0x24,        # Gr_Kind_Battle
    "dreamland": 0x1C,          # Gr_Kind_OldPupupu
    "pokemonstadium": 0x10,     # Gr_Kind_PStadium
    "yoshisstory": 0x0A,        # Gr_Kind_Story
    "fountainofdreams": 0x0C,   # Gr_Kind_Izumi
}

# EXTERNAL character id (the player block's c_kind, what the harness writes) ->
# INTERNAL FighterKind (Fighter.x04, what the live fighter reports). Source:
# melee decomp src/melee/pl/player.c `ftMapping_list`, indexed by CharacterKind.
# Vanilla only: an m-ex added fighter (external id >= 0x1A) has no entry here,
# which makes the character check `unknown` -- a recorded limitation, never a
# pass.
CKIND_TO_FTKIND = {
    0x00: 0x02, 0x01: 0x03, 0x02: 0x01, 0x03: 0x18, 0x04: 0x04, 0x05: 0x05,
    0x06: 0x06, 0x07: 0x11, 0x08: 0x00, 0x09: 0x12, 0x0A: 0x10, 0x0B: 0x08,
    0x0C: 0x09, 0x0D: 0x0C, 0x0E: 0x0A, 0x0F: 0x0F, 0x10: 0x0D, 0x11: 0x0E,
    0x12: 0x13, 0x13: 0x07, 0x14: 0x16, 0x15: 0x14, 0x16: 0x15, 0x17: 0x1A,
    0x18: 0x17, 0x19: 0x19,
}


# --- execution evidence -------------------------------------------------------- #

def _check(cid, status, *, expected=None, observed=None, reason="",
           critical=False, code=None):
    """One measured check. `code` is what a policy switches on -- a reason
    string is for a person, and classifying outcomes by prose is how "the
    harness could not run" ended up meaning "the costume is defective"."""
    return {"check_id": cid, "status": status, "expected": expected,
            "observed": observed, "reason": reason, "critical": bool(critical),
            "code": code or cid}


def execution_evidence(*, resolved, requested, batch_row, sidecars):
    """Did the intended candidate get inserted, selected, booted and captured?

    Every check reads back what the ENGINE reported, never what the harness
    asked for. `requested` carries the character, the external ckind and the
    costume slot the build actually produced.
    """
    checks = []

    checks.append(_check(
        "profile_complete",
        "pass" if resolved["complete"] else "fail",
        expected="every profile entry resolved against the engine catalog",
        observed={"unsupported": resolved["unsupported"]},
        reason="" if resolved["complete"] else
        f"unsupported profile entries: {', '.join(resolved['unsupported'])}",
        code="profile_incomplete"))

    status = (batch_row or {}).get("status")
    checks.append(_check(
        "capture_run", "pass" if status == "ok" else "fail",
        expected="ok", observed=status,
        reason="" if status == "ok" else
        f"the capture run reported {status!r}: {(batch_row or {}).get('reason', '')}",
        code="capture_run_failed"))

    iso = (requested.get("iso_identity") or {})
    if not iso:
        checks.append(_check(
            "candidate_inserted", "unknown", expected="the candidate's own "
            "bytes on the built disc", observed=None,
            reason="no disc was built, so nothing was inserted", critical=True,
            code="no_build"))
    else:
        checks.append(_check(
            "candidate_inserted",
            "pass" if iso.get("insertion_verified") else "unknown",
            expected="exactly one costume file added, hashing to a member of "
                     "the sealed package",
            observed={"file": iso.get("inserted_file"),
                      "member": iso.get("inserted_member"),
                      "added_costumes": iso.get("added_costumes")},
            reason="" if iso.get("insertion_verified") else
            (iso.get("insertion_note") or "the inserted bytes were not confirmed"),
            critical=True, code="insertion_unproven"))
        unchanged = iso.get("unchanged_during_capture")
        checks.append(_check(
            "iso_unchanged_during_capture",
            "pass" if unchanged else ("unknown" if unchanged is None else "fail"),
            expected=iso.get("sha256"), observed=iso.get("sha256_after_capture"),
            reason="" if unchanged else
            ("the disc was replaced between the build and the end of the "
             "captures, so the captures are not of the disc that was hashed"
             if unchanged is False else
             "the disc was not re-hashed after the captures"),
            critical=True, code="iso_replaced"))

    identity = (batch_row or {}).get("live_identity") or {}
    live_slot = identity.get("costume_id")
    want_slot = requested.get("costume_slot")
    if live_slot is None:
        checks.append(_check(
            "costume_slot_loaded", "unknown", expected=want_slot, observed=None,
            reason="the live fighter's costume id could not be read",
            critical=True,
        code="slot_unreadable"))
    else:
        checks.append(_check(
            "costume_slot_loaded",
            "pass" if int(live_slot) == int(want_slot) else "fail",
            expected=want_slot, observed=int(live_slot),
            reason="" if int(live_slot) == int(want_slot) else
            (f"the build inserted the candidate at slot {want_slot} but the "
             f"match is wearing slot {live_slot}: the captures are of a "
             f"different costume"),
            critical=True))

    live_kind = identity.get("kind")
    want_kind = CKIND_TO_FTKIND.get(requested.get("ckind"))
    if want_kind is None:
        checks.append(_check(
            "character_loaded", "unknown", expected=None, observed=live_kind,
            reason=(f"external character id {requested.get('ckind')!r} is not a "
                    f"vanilla fighter, so there is no verified internal-kind "
                    f"mapping to compare against"),
            critical=True,
        code="character_kind_unmapped"))
    elif live_kind is None:
        checks.append(_check(
            "character_loaded", "unknown", expected=want_kind, observed=None,
            reason="the live fighter's internal kind could not be read",
            critical=True,
        code="character_unreadable"))
    else:
        checks.append(_check(
            "character_loaded",
            "pass" if int(live_kind) == want_kind else "fail",
            expected=want_kind, observed=int(live_kind),
            reason="" if int(live_kind) == want_kind else
            "the fighter in the match is not the one the candidate targets",
            critical=True))

    stage_state = (batch_row or {}).get("live_stage_state") or {}
    live_ground = stage_state.get("ground_kind")
    want_ground = GROUND_KIND.get(resolved["stage"])
    if want_ground is None:
        checks.append(_check(
            "stage_loaded", "unknown", expected=None, observed=live_ground,
            reason=f"no verified ground kind for stage {resolved['stage']!r}",
            critical=True,
        code="stage_unmapped"))
    elif live_ground is None:
        checks.append(_check(
            "stage_loaded", "unknown", expected=want_ground, observed=None,
            reason="the engine's ground kind could not be read", critical=True,
        code="stage_unreadable"))
    else:
        checks.append(_check(
            "stage_loaded",
            "pass" if int(live_ground) == want_ground else "fail",
            expected=want_ground, observed=int(live_ground),
            reason="" if int(live_ground) == want_ground else
            "the match did not load the stage the profile declares",
            critical=True))

    # Per-capture action state + landed frame, from the engine's own reading.
    by_move = {s.get("move"): s for s in sidecars}
    live_kind = (batch_row or {}).get("live_identity", {}).get("kind")
    observations, missing, wrong_state = [], [], []
    unexpected_states, wrong_port, no_frame, frame_moved = [], [], [], []
    seen_frames = {}
    for want in resolved["expected_captures"]:
        sidecar = by_move.get(want["move"])
        found = None
        if sidecar:
            for cap in sidecar.get("captures", []):
                if cap.get("move_frame") == want["frame"]:
                    found = cap
                    break
        if found is None or not found.get("file"):
            missing.append(f"{want['move']}:{want['frame']}")
            observations.append({**want, "captured": False})
            continue
        label = f"{want['move']}:{want['frame']}"
        row = {**want, "captured": True, "file": found.get("file"),
               "state": found.get("state"), "state_name": found.get("state_name"),
               "anim_frame": found.get("anim_frame"), "x": found.get("x"),
               "y": found.get("y"), "facing": found.get("facing"),
               "airborne": found.get("airborne"),
               "game_frame": found.get("game_frame"),
               "port": found.get("port"),
               "autofit": found.get("autofit")}
        expected_states = _expected_states(want["move"], live_kind)
        if expected_states is None:
            # A move whose action state this build cannot name is NOT a move
            # whose action state was checked. It used to skip validation and
            # leave the aggregate check passing, which is how a special
            # reporting `Wait` came back as execution-complete.
            unexpected_states.append(f"{label} ({found.get('state_name')})")
            row["state_expected"] = None
        elif found.get("state") not in expected_states:
            wrong_state.append(f"{label} ({found.get('state_name')})")
            row["state_expected"] = sorted(expected_states)
        else:
            row["state_expected"] = sorted(expected_states)
        # The port the reading came from. ABSENT IS NOT ZERO: a reading with
        # no port recorded is not a reading from port 0, and treating it as one
        # let a whole run of `None`s through.
        if found.get("port") != 0:
            wrong_port.append(f"{label} (port {found.get('port')!r})")
        # A simulation frame counter that is present, plausible, and does not
        # repeat across two different move frames.
        counter = found.get("game_frame")
        if not isinstance(counter, int) or isinstance(counter, bool)                 or not 0 <= counter <= 0xFFFFFFFF:
            no_frame.append(f"{label} (simulation frame {counter!r})")
        else:
            previous = seen_frames.get(counter)
            if previous is not None and previous != label:
                frame_moved.append(f"{label} shares frame {counter} with {previous}")
            seen_frames[counter] = label
        # The ANIMATION frame. This build has no mapping from a move's logical
        # frame to its animation time -- running animations loop, speeds
        # differ, and the saved grab reads 2.0 on logical frame 3 -- so the
        # value is only checked for being a finite, plausible reading. That it
        # corresponds to the requested frame is NOT established here, and
        # `frame_counters` says so rather than implying otherwise.
        anim = found.get("anim_frame")
        if not isinstance(anim, (int, float)) or isinstance(anim, bool)                 or anim != anim or anim in (float("inf"), float("-inf"))                 or not -1.0 <= float(anim) <= 10000.0:
            no_frame.append(f"{label} (animation frame {anim!r})")
        observations.append(row)

    checks.append(_check(
        "captures_present", "pass" if not missing else "fail",
        expected=len(resolved["expected_captures"]),
        observed=len(resolved["expected_captures"]) - len(missing),
        reason="" if not missing else
        f"no capture landed on: {', '.join(missing)}",
        code="captures_missing"))
    if wrong_state:
        action_status, action_reason = "fail", (
            f"captured outside the expected action state: {', '.join(wrong_state)}")
    elif unexpected_states:
        action_status, action_reason = "unknown", (
            f"this build has no action-state expectation for: "
            f"{', '.join(unexpected_states)}. The observed state is recorded, "
            f"but nothing checked it -- specials are character-specific and "
            f"the engine has no portable table")
    else:
        action_status, action_reason = "pass", ""
    checks.append(_check(
        "action_states", action_status,
        expected="each frame captured in its move's action state",
        observed={"mismatched": wrong_state, "unexpected": unexpected_states},
        reason=action_reason, critical=True,
        code="unsupported_special" if action_status == "unknown" else "wrong_action_state"))
    checks.append(_check(
        "capture_port", "pass" if not wrong_port else "fail",
        expected=0, observed={"other_ports": wrong_port},
        reason="" if not wrong_port else
        f"a reading came from another port: {', '.join(wrong_port)}",
        critical=True,
        code="wrong_port"))
    checks.append(_check(
        "frame_counters",
        "pass" if not (no_frame or frame_moved) else "unknown",
        expected="one distinct simulation frame per captured move frame, and a "
                 "finite animation frame with each. NOT established: that the "
                 "animation frame corresponds to the requested move frame -- "
                 "this build has no per-fighter animation-rate mapping",
        observed={"missing": no_frame, "repeated": frame_moved},
        reason="" if not (no_frame or frame_moved) else
        ("; ".join(no_frame + frame_moved))[:400], code="frame_counters_unusable"))

    unproven = (batch_row or {}).get("unproven_fresh") or 0
    checks.append(_check(
        "frames_fresh", "pass" if not unproven else "unknown",
        expected=0, observed=unproven, code="frames_not_proven_fresh",
        reason="" if not unproven else
        (f"{unproven} capture(s) were byte-identical to the previous one, so "
         f"the renderer cannot be proven to have advanced")))

    statuses = {c["status"] for c in checks}
    complete = statuses <= {"pass"}
    return {
        "status": "complete" if complete else "incomplete",
        "checks": checks,
        "missing_captures": missing,
        "observations": observations,
    }


def _expected_states(move, live_kind):
    """The action-state ids a move's frame 1+ should report, or None if unknown."""
    if move == "idle":
        from .gamestate import WAIT
        return {WAIT}
    try:
        from .gamestate import attack_states, ATTACK_STATES
    except Exception:
        return None
    states = attack_states(move, live_kind) if live_kind is not None \
        else ATTACK_STATES.get(move)
    if states:
        return set(states)
    if move == "run":
        from .gamestate import RUN, DASH
        return {RUN, DASH}
    # Specials are character-specific (CharSpecific_NNN); the engine has no
    # portable table, so there is nothing to compare against. Recording the
    # observed state is the honest answer, not inventing an expectation.
    return None


def _iter_disc_files(iso_path, names=None, limit_bytes=8 << 20):
    """(name, bytes) for files on a GameCube disc image, flat FST walk.

    Melee's disc is flat (`core.iso_reads.file_names` relies on the same), so
    this is a short walk rather than a filesystem. `names`, when given, is the
    only set read -- the point is to check a handful of costume files, not to
    pull a 1.4 GB disc through memory.
    """
    import struct
    wanted = None if names is None else set(names)
    with Path(iso_path).open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        header = stream.read(0x430)
        if len(header) != 0x430 or header[0x1C:0x20] != bytes.fromhex("c2339f3d"):
            raise ValueError("expected a complete GameCube disc header")
        offset, length = struct.unpack_from(">II", header, 0x424)
        if not 12 <= length <= 16 * 1024 * 1024 or offset + length > size:
            raise ValueError("invalid or truncated FST region")
        stream.seek(offset)
        fst = stream.read(length)
        count = struct.unpack_from(">I", fst, 8)[0]
        strings = fst[count * 12:]
        for index in range(1, count):
            entry = fst[index * 12:(index + 1) * 12]
            if entry[0]:
                continue
            name_offset = int.from_bytes(entry[1:4], "big")
            end = strings.find(bytes(1), name_offset)
            name = strings[name_offset:end].decode("ascii", errors="replace")
            if wanted is not None and name not in wanted:
                continue
            start, payload = struct.unpack_from(">II", entry, 4)
            if not payload or payload > limit_bytes or start + payload > size:
                continue
            stream.seek(start)
            yield name, stream.read(payload)


def _costume_namespace(character):
    """`Pl<XX>` -- the prefix every costume file for this fighter carries."""
    try:
        from core.constants import CHAR_PREFIXES
        code = CHAR_PREFIXES.get(character)
    except Exception:
        code = None
    return f"Pl{code}" if code else None


def insertion_evidence(iso_target, clean_iso, package, character, say):
    """Which file the build ADDED to the disc, and whether it is the candidate.

    Not "is the candidate's bytes anywhere on the disc". That accepted a
    matching `csp.png`, and finding bytes somewhere does not establish that the
    selected slot loads them.

    Instead: take the set difference against the CLEAN disc the build started
    from. A single-costume test build adds exactly one costume file. That file
    is the insertion, by construction and without guessing a naming convention
    -- the builder renames `PlPkNr.dat` to `PlPkNr_001.dat` and nothing in this
    repo can predict that. It must be in the fighter's own `Pl<XX>` namespace
    and it must hash to a member of the sealed package.

    What this still does not establish is the m-ex costume TABLE: that slot N
    points at this file rather than another. `costume_slot_loaded` reads the
    slot the engine loaded; the table between them is not read here, and the
    result says so.
    """
    out = {"schema": "verification-insertion-v1", "inserted_member": None,
           "inserted_file": None, "insertion_verified": False,
           "added_files": None, "added_costumes": None,
           "namespace": _costume_namespace(character)}
    members = package.get("members") or {}
    if not members:
        out["insertion_note"] = ("the sealed package listed no members, so "
                                 "nothing could be looked for on the disc")
        return out
    if not clean_iso or not Path(clean_iso).is_file():
        out["insertion_note"] = ("the clean disc this build started from is no "
                                 "longer readable, so the added files cannot "
                                 "be identified")
        return out
    try:
        from core import iso_reads
        before = set(iso_reads.file_names(clean_iso))
        after = set(iso_reads.file_names(iso_target))
    except Exception as exc:
        out["insertion_note"] = (f"the discs could not be listed "
                                 f"({type(exc).__name__}: {exc}), so the "
                                 f"inserted bytes were not confirmed")
        return out
    added = sorted(after - before)
    out["added_files"] = added
    namespace = out["namespace"]
    costumes = [name for name in added
                if name.lower().endswith((".dat", ".usd"))
                and (namespace is None or name.startswith(namespace))]
    out["added_costumes"] = costumes
    if namespace is None:
        out["insertion_note"] = (f"no costume-file namespace is known for "
                                 f"{character!r}, so an added file cannot be "
                                 f"attributed to that fighter")
        return out
    if len(costumes) != 1:
        out["insertion_note"] = (
            f"the build added {len(costumes)} costume file(s) in the {namespace} "
            f"namespace ({', '.join(costumes) or 'none'}); a single-costume "
            f"verification build must add exactly one, so which file the slot "
            f"holds is not established")
        return out
    name = costumes[0]
    wanted = {digest: member for member, digest in members.items()}
    try:
        blob = dict(_iter_disc_files(iso_target, names=[name])).get(name)
    except Exception as exc:
        out["insertion_note"] = (f"the added file could not be read back "
                                 f"({type(exc).__name__}: {exc})")
        return out
    if blob is None:
        out["insertion_note"] = f"the added file {name} could not be read back"
        return out
    digest = hashlib.sha256(blob).hexdigest()
    out.update(inserted_file=name, inserted_sha256=digest)
    if digest not in wanted:
        out["insertion_note"] = (
            f"the file the build added ({name}) does not hash to any member of "
            f"the sealed package: the builder transformed the bytes, so these "
            f"captures are of a DERIVED costume and the chain back to the "
            f"candidate is unproven")
        say(out["insertion_note"])
        return out
    out.update(inserted_member=wanted[digest], insertion_verified=True,
               limitation=("the m-ex costume table was not read: that the "
                           "loaded slot points at this file rather than "
                           "another is not established here"))
    say(f"the build added exactly one {namespace} costume file, {name}, and it "
        f"is the candidate's own {wanted[digest]}")
    return out
