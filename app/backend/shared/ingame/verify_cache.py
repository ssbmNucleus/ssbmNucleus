"""
Reusing a costume verification result (verify_costume.py): the canonical cache
specification and key, which outcomes are worth remembering, and why a stored
result may not be served again.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from core.hashing import sha256_file
from shared.ingame.verify_profile import MANIFEST_SCHEMA, resolve_profile
from shared.ingame.verify_outcome import deterministic_unknown


def cache_spec(*, candidate_hash, member_hashes, profile_version, engine,
               toolchain, character, stage, nana_hash=None):
    """The canonical specification a verification result is keyed by.

    Every effective input and every implementation identity, in one ordered
    document. The key is its hash, and the stored record carries the spec back
    so a reader can see what a hit actually claimed to match.
    """
    return {
        "schema": "verification-cache-spec-v2",
        "candidate_sha256": candidate_hash,
        "candidate_members": dict(sorted((member_hashes or {}).items())),
        "nana_sha256": nana_hash,
        "profile_version": profile_version,
        "engine_id": (engine or {}).get("id"),
        "engine_sources": (engine or {}).get("sources"),
        "toolchain_id": (toolchain or {}).get("id"),
        "toolchain": {k: v for k, v in (toolchain or {}).items()
                      if k not in {"schema", "id"}},
        "character": str(character).lower(),
        "stage": stage,
        "manifest_schema": MANIFEST_SCHEMA,
    }


def cache_key(spec):
    """The hash of a canonical cache spec."""
    if not isinstance(spec, dict):
        raise TypeError("the cache key is computed from a cache spec")
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"),
                           default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


# A verdict is worth remembering when it will be the same again for these
# bytes. A measured pass or failure always will be; an inconclusive result only
# when every one of its reasons is a bounded limitation of the profile or of
# what the harness can observe (see `deterministic_unknown`).
CACHEABLE_OUTCOMES = frozenset({"verified", "failed", "unknown"})


def _required_captures(profile_version):
    """(move, frame) the stored record must carry, from the profile itself."""
    try:
        resolved = resolve_profile(profile_version)
    except ValueError:
        return None
    return {(c["move"], int(c["frame"])) for c in resolved["expected_captures"]}


def validate_cached(stored, spec, key):
    """Why a stored verification result may NOT be reused, or None.

    A cache entry is a claim by a previous run, kept in an ordinary file. It is
    read as DATA and checked against the specification that was asked for, and
    then against the evidence its own verdict depends on:

    * schema, key and the full canonical spec;
    * candidate hash, profile and engine identity;
    * the EXACT set of captures the profile requires -- it previously accepted
      a record carrying one of ten;
    * every referenced file, recursively: each capture AND both passes of its
      measurement pair, re-hashed;
    * consistency between the verdict and the checks -- a `verified` record
      whose own checks are failing or unknown is not a verified record.
    """
    if not isinstance(stored, dict):
        return "the stored entry is not a verification manifest"
    if stored.get("schema") != MANIFEST_SCHEMA:
        return f"stored schema {stored.get('schema')!r} is not {MANIFEST_SCHEMA}"
    cache = stored.get("cache") or {}
    if cache.get("key") != key:
        return "the stored entry was written under a different cache key"
    if cache.get("spec") != spec:
        return "the stored entry's cache specification differs from this run's"
    record = stored.get("game_verification") or {}
    claimed = str(record.get("candidate_hash") or "").split(":")[-1]
    if claimed != spec["candidate_sha256"]:
        return (f"the stored entry is about candidate {claimed[:16]}..., not "
                f"{spec['candidate_sha256'][:16]}...")
    if record.get("profile_version") != spec["profile_version"]:
        return "the stored entry was produced under a different capture profile"
    if (stored.get("engine_version") or {}).get("id") != spec["engine_id"]:
        return "the stored entry was produced by a different engine version"

    outcome = record.get("outcome")
    if outcome not in CACHEABLE_OUTCOMES:
        return (f"the stored outcome {outcome!r} is not a measured verdict")
    if outcome == "unknown" and not deterministic_unknown(
            outcome, stored.get("outcome_reasons") or []):
        return ("the stored entry is inconclusive for a reason that is not "
                "deterministic, so it says nothing about a later run")

    # The verdict has to agree with the record's own checks.
    checks = (stored.get("execution_evidence") or {}).get("checks") or []
    appearance = stored.get("appearance_checks") or []
    statuses = {c.get("status") for c in checks} | {a.get("status")
                                                    for a in appearance}
    if outcome == "verified" and statuses - {"pass"}:
        return ("the stored entry says `verified` while its own checks are "
                + ", ".join(sorted(s for s in statuses if s != "pass")))
    if outcome == "failed" and "fail" not in statuses:
        return "the stored entry says `failed` but no check of its own failed"
    if outcome == "unknown" and "fail" in statuses:
        return "the stored entry says `unknown` while a check of its own failed"

    captures = record.get("captures") or []
    if not captures:
        return "the stored entry references no captures"
    required = _required_captures(spec["profile_version"])
    if required is not None:
        have = {(c.get("move"), c.get("frame")) for c in captures}
        short = required - have
        if short:
            return ("the stored entry is missing required captures: "
                    + ", ".join(f"{m}:{f}" for m, f in sorted(short)))
    for row in captures:
        references = [(row.get("path"), row.get("hash"), "capture")]
        for name, pair in (row.get("measurement_pair") or {}).items():
            references.append((pair.get("path"), pair.get("hash"),
                               f"{name} pass"))
        for path, expected, what in references:
            path = Path(path or "")
            expected = str(expected or "").split(":")[-1]
            if not path.name:
                return f"a {what} in the stored entry names no file"
            if not path.is_file():
                return f"the stored {what} {path.name} no longer exists"
            if not expected or sha256_file(path) != expected:
                return f"the stored {what} {path.name} does not match its hash"
    return None
