"""
The outcome of a costume verification (verify_costume.py): the reason codes
that make a run unknown or incomplete, classifying a run as verified, failed,
unknown or incomplete, and whether an inconclusive result would repeat.
"""

from __future__ import annotations


# --- outcome ------------------------------------------------------------------- #

# The ONLY reasons an inconclusive run may be `unknown` rather than
# `incomplete`. Each is a bounded, deterministic limitation of this profile or
# of what the harness can observe -- it will say the same thing again for the
# same bytes, and a preview policy may soften it by name. Anything else is work
# that did not finish, and work that did not finish is `incomplete`: failure to
# RUN is not evidence about the costume.
UNKNOWN_REASON_CODES = frozenset({
    "insufficient_framing",        # the actor reaches the rendered boundary
    "unobservable_boundary",       # effects or the HUD sit on that boundary
    "unsupported_special",         # no portable action-state expectation
    "unresolved_isolation",        # the actor could not be separated
    "unmeasurable_render_area",    # the rendered area could not be located
    "character_kind_unmapped",     # an m-ex fighter has no verified kind
})

# Reasons a run is `incomplete`: it did not finish, or the machine could not be
# trusted. Pending and retryable; never softened into game evidence.
INCOMPLETE_REASON_CODES = frozenset({
    "cancelled", "timeout", "dolphin_busy", "harness_error", "no_build",
    "owned_child_not_confirmed_exited", "profile_incomplete",
    "no_frames_measured",
})


def _code_of(row):
    return row.get("code") or row.get("check_id") or "unknown"


def decide_outcome(evidence, appearance, *, run_error=None, profile_complete=True,
                   cancelled=False, execution_failure=None):
    """Classify a run: verified | failed | unknown | incomplete.

    * `verified` -- every required check passed for these bytes.
    * `failed` -- evidence exists and it establishes a defect IN THE COSTUME.
    * `unknown` -- the run executed, but a named conclusion is unsupported by
      an allow-listed profile or observability limitation
      (:data:`UNKNOWN_REASON_CODES`). Deterministic: the same bytes will say
      the same thing again.
    * `incomplete` -- the work did not finish, or the machine could not be
      trusted: timeout, cancellation, a busy emulator, a harness exception.

    The distinction is the point. A generic exception used to become `failed`,
    which put "failed" beside a candidate because Dolphin fell over. Failure to
    run is not evidence against the costume, and an inconclusive result whose
    reason is NOT on the allowlist is not the bounded kind a preview policy may
    soften -- it is unfinished work.

    Returns (outcome, reasons) where each reason is
    ``{"code", "check", "detail"}``: a policy switches on the code, a person
    reads the detail.
    """
    def reason(code, check, detail):
        return {"code": code, "check": check, "detail": str(detail)}

    if cancelled:
        return "incomplete", [reason("cancelled", "run",
                                     run_error or "cancelled")]
    if execution_failure:
        return "incomplete", [reason(
            execution_failure, "run",
            f"{run_error or execution_failure}. This is an execution failure "
            f"of the harness, not evidence about the costume.")]
    if run_error:
        # An exception during the run is the harness failing, not a measured
        # defect. It is retryable and it says nothing about these bytes.
        return "incomplete", [reason(
            "harness_error", "run",
            f"{run_error}. The run did not finish, so nothing was measured "
            f"about the costume.")]

    critical_fail = [c for c in evidence["checks"]
                     if c["status"] == "fail" and c["critical"]]
    appearance_fail = [a for a in appearance if a["status"] == "fail"]
    if critical_fail or appearance_fail:
        return "failed", (
            [reason(_code_of(c), c["check_id"], c["reason"]) for c in critical_fail]
            + [reason(a.get("code") or "appearance_failed",
                      f"{a['move']}:{a['frame']}", a["reason"])
               for a in appearance_fail])

    inconclusive = [(_code_of(c), c["check_id"], c["reason"])
                    for c in evidence["checks"] if c["status"] == "unknown"]
    inconclusive += [(a.get("code") or "unresolved_isolation",
                      f"{a['move']}:{a['frame']}", a["reason"])
                     for a in appearance if a["status"] == "unknown"]
    blocked = [(_code_of(c), c["check_id"], c["reason"])
               for c in evidence["checks"] if c["status"] == "fail"]
    if not profile_complete:
        blocked.append(("profile_incomplete", "profile",
                        "the capture profile is incomplete"))
    if not appearance:
        blocked.append(("no_frames_measured", "appearance",
                        "no frame was measured"))

    # An inconclusive reason outside the allowlist is unfinished work, not a
    # bounded limitation somebody may decide to live with.
    unlisted = [row for row in inconclusive
                if row[0] not in UNKNOWN_REASON_CODES]
    if blocked or unlisted:
        return "incomplete", [reason(*row) for row in blocked + unlisted
                              ] + [reason(*row) for row in inconclusive
                                   if row not in unlisted]
    if inconclusive:
        return "unknown", [reason(*row) for row in inconclusive]
    return "verified", []


def deterministic_unknown(outcome, reasons):
    """Will this inconclusive result say the same thing again for these bytes?

    Only then is it worth remembering. A timeout or a busy emulator is a fact
    about the machine at one moment; an actor that reaches the rendered
    boundary at a fixed camera is a fact about these bytes under this profile,
    and re-booting for it on every identical export buys nothing.
    """
    if outcome != "unknown":
        return False
    return bool(reasons) and all(r.get("code") in UNKNOWN_REASON_CODES
                                 for r in reasons)
