"""
Vanilla-byte guarding + automatic offset relocation for extras hex patches.

Motivation (docs/dev/EXTRAS_MISSION_TEMPLATE.md lesson #1): a shifted write into
an Ef*Data.dat particle bank or model-color block does not fail loudly -- it
corrupts whatever bytes happen to sit at the stale offset, and a shifted
070707/CF write into a particle *script* can HANG THE GAME. Re-saving a DAT
through HSDRawViewer (texture import, model import) can shift every offset
after the edit point, so a hardcoded/config offset that was correct at audit
time can silently point at the wrong bytes on a later build.

This module is the safety net wrapped around the shared write paths in
color_patch.py (`apply_hex_patches`, `patch_shine_sparkle_color`, the
shine_gradient / 070707 / CF matrix writers) and helpers.py:

    1. GUARD: before writing new bytes at offset O, read what's actually at O
       in the TARGET file. If it matches the expected vanilla bytes (or a
       previously-applied color the caller already knows about), the write is
       safe -- proceed exactly as before.
    2. RELOCATE: if the guard fails, try to find where those bytes moved to:
         (a) ptcl-bank color operands (CF/070707/RGB writes into an Ef*Data
             file that also has a real particle bank) -- parse the VANILLA
             reference file with ptcl_parse to identify the operand by
             (script index, opcode kind, ordinal-within-script), then parse
             the TARGET file and look up the same identity to get the new
             offset. Verify vanilla bytes match there before writing.
         (b) model-region blocks (070707 / 42_48 / 98 matrix) -- signature
             scan: search the target file for the marker bytes bracketed by
             enough surrounding vanilla context to be unique. Require exactly
             ONE hit; verify; relocate.
    3. SKIP LOUDLY: if relocation fails (no hit, ambiguous, or the bytes at
       the candidate still don't match), log a prominent warning naming the
       extra id / layer / offsets and record the skip -- and NEVER write.

Every public function here returns enough detail for the caller to append a
per-layer entry to the existing result dict (`results['skipped']` etc in
colors.py) without inventing new response shapes.
"""

import logging
import os

logger = logging.getLogger(__name__)

def _ptcl_parse():
    """Import shared.rendering.ptcl_parse lazily (deferred so this module has no
    import-time cost; the package import keeps PyInstaller able to trace it)."""
    from shared.rendering import ptcl_parse
    return ptcl_parse


# =============================================================================
# Guard
# =============================================================================

class RelocationResult:
    """Outcome of guard_and_resolve(): either a safe offset to write at, or a
    skip with a reason. `offset` is None iff `ok` is False."""

    __slots__ = ("ok", "offset", "reason", "relocated")

    def __init__(self, ok, offset=None, reason=None, relocated=False):
        self.ok = ok
        self.offset = offset
        self.reason = reason
        self.relocated = relocated

    def __repr__(self):
        if self.ok:
            return f"RelocationResult(ok=True, offset=0x{self.offset:X}, relocated={self.relocated})"
        return f"RelocationResult(ok=False, reason={self.reason!r})"


def read_bytes(path, offset, length):
    """Read `length` bytes at `offset` from `path`. Returns b'' if out of range
    or the file can't be read (never raises -- callers treat empty as a
    guard-fail, which is the safe default)."""
    try:
        with open(path, 'rb') as f:
            f.seek(offset)
            return f.read(length)
    except Exception as e:
        logger.debug(f"[relocate] read_bytes failed for {path}@0x{offset:X}: {e}")
        return b''


def guard_offset(target_path, offset, expected_variants):
    """Check whether the bytes currently at `offset` in `target_path` match
    any of `expected_variants` (list of bytes objects -- vanilla bytes plus
    any previously-applied color the caller already read/considers valid).

    Returns True if the guard passes (safe to write at `offset` as-is).
    """
    if not expected_variants:
        # No known-good bytes to check against -- caller didn't supply a
        # vanilla reference, so we can't guard. Treat as pass-through (the
        # existing per-format callers already do their own "read current
        # color" dance in that case).
        return True
    max_len = max(len(v) for v in expected_variants)
    current = read_bytes(target_path, offset, max_len)
    for variant in expected_variants:
        if current[:len(variant)] == variant:
            return True
    return False


# =============================================================================
# ptcl-bank operand relocation
# =============================================================================

def _identify_ptcl_operand(vanilla_path, color_offset):
    """Parse `vanilla_path` with ptcl_parse and find the color operand whose
    file_off == color_offset. Returns (script_index, kind, ordinal, channels,
    size) identity tuple, or None if no operand sits there (not a ptcl-bank
    offset at all, e.g. it's a model-region byte, or the file has no ptcl
    bank / operand truly isn't there).

    `ordinal` = index of this operand within its script's color list, in file
    order -- stable identity even if a model import inserts/removes bytes
    elsewhere in the script (the operand COUNT and ORDER per script don't
    change from a re-save, only their absolute file offsets do).
    """
    pp = _ptcl_parse()
    try:
        data = open(vanilla_path, 'rb').read()
    except Exception as e:
        logger.debug(f"[relocate] could not read vanilla reference {vanilla_path}: {e}")
        return None
    try:
        hdr, scripts = pp.parse_bank(data)
    except Exception as e:
        logger.debug(f"[relocate] ptcl_parse failed on {vanilla_path}: {e}")
        return None
    for sc in scripts:
        for ordinal, c in enumerate(sc.colors):
            if c["file_off"] == color_offset:
                return (sc.index, c["kind"], ordinal, c["channels"], c["size"])
    return None


def _find_ptcl_operand_by_identity(target_path, identity):
    """Parse `target_path` with ptcl_parse and return the file offset of the
    color operand matching `identity` = (script_index, kind, ordinal,
    channels, size), or None if that script/operand doesn't exist in the
    target (e.g. the target is a different / more heavily modified file)."""
    pp = _ptcl_parse()
    script_index, kind, ordinal, channels, size = identity
    try:
        data = open(target_path, 'rb').read()
    except Exception as e:
        logger.debug(f"[relocate] could not read target {target_path}: {e}")
        return None
    try:
        hdr, scripts = pp.parse_bank(data)
    except Exception as e:
        logger.debug(f"[relocate] ptcl_parse failed on {target_path}: {e}")
        return None
    for sc in scripts:
        if sc.index != script_index:
            continue
        # `ordinal` is the operand's index in the script's FULL color list
        # (see _identify_ptcl_operand), so index that list and check the kind
        # -- not a kind-filtered list: PrimCol and EnvCol operands interleave,
        # and a filtered index pointed at a different operand whenever an
        # EnvCol preceded (a shifted install then wrote the wrong operand).
        if ordinal < len(sc.colors):
            cand = sc.colors[ordinal]
            if (cand["kind"] == kind and cand["channels"] == channels
                    and cand["size"] == size):
                return cand["file_off"]
    return None


def relocate_ptcl_operand(vanilla_path, target_path, color_offset, expected_bytes):
    """Attempt ptcl-bank relocation for a color write originally aimed at
    `color_offset` (a byte offset into the VANILLA layout).

    Returns a RelocationResult. `ok=True` means `.offset` is a verified-safe
    place to write `expected_bytes`-shaped data in `target_path` (though the
    actual bytes AT that offset are whatever the current/previous mod left --
    the caller still does its own current-vs-new diffing for CF-multi etc;
    this function only proves the LOCATION is right by checking the vanilla
    reference bytes would fit the operand's declared size).
    """
    identity = _identify_ptcl_operand(vanilla_path, color_offset)
    if identity is None:
        return RelocationResult(False, reason=(
            f"0x{color_offset:X} is not a ptcl-bank color operand in the "
            f"vanilla reference {os.path.basename(vanilla_path)} (no "
            f"(script,kind,ordinal) identity found) -- not eligible for "
            f"ptcl relocation"))

    new_offset = _find_ptcl_operand_by_identity(target_path, identity)
    if new_offset is None:
        script_index, kind, ordinal, channels, size = identity
        return RelocationResult(False, reason=(
            f"ptcl relocation failed: identity (script={script_index}, "
            f"kind={kind}, ordinal={ordinal}) from vanilla offset "
            f"0x{color_offset:X} has no match in target {target_path} "
            f"(script/operand missing or target bank layout diverged)"))

    # Verify: the target file's vanilla-shaped slot exists and is AT LEAST as
    # wide as the expected write. We don't require the CURRENT bytes there to
    # equal `expected_bytes` (that's the guard's job upstream / the caller's
    # current-color read) -- but we DO sanity check the write fits so we
    # never write past a narrower operand. Writes narrower than the operand
    # are fine and expected: the app's CF/070707 formats write 3-byte RGB
    # prefixes into what ptcl_parse reports as 4-byte RGBA PrimCol/EnvCol
    # operands (the 4th byte is alpha, left untouched by design).
    script_index, kind, ordinal, channels, size = identity
    if expected_bytes is not None and len(expected_bytes) > size:
        return RelocationResult(False, reason=(
            f"ptcl relocation found offset 0x{new_offset:X} (script="
            f"{script_index}, kind={kind}, ordinal={ordinal}) but the "
            f"operand size ({size} bytes) is smaller than the expected write "
            f"size ({len(expected_bytes)} bytes) -- refusing to write"))

    logger.warning(
        f"[relocate] ptcl operand relocated: vanilla 0x{color_offset:X} -> "
        f"target 0x{new_offset:X} (script={script_index}, kind={kind}, "
        f"ordinal={ordinal})")
    return RelocationResult(True, offset=new_offset, relocated=True)


# =============================================================================
# Model-region block relocation (070707 / 42_48 / 98 matrix)
# =============================================================================

def relocate_by_signature(vanilla_path, target_path, marker_offset, marker_len,
                           context_before=16, context_after=16):
    """Signature-scan relocation for model-region color blocks (07 07 07 04,
    42 48, 98 00 NN) that are NOT ptcl bytecode and so have no structural
    parser. Builds a signature from the vanilla file: `context_before` bytes
    before the marker + the marker itself (`marker_len` bytes) +
    `context_after` bytes after, then searches for that exact byte string in
    the target file.

    Requires EXACTLY ONE hit (ambiguous = skip, per spec). Returns a
    RelocationResult whose `.offset` (when ok) is the marker offset in the
    target file (i.e. directly comparable to the original `marker_offset`,
    NOT the signature start).
    """
    try:
        vdata = open(vanilla_path, 'rb').read()
    except Exception as e:
        return RelocationResult(False, reason=f"could not read vanilla reference: {e}")
    try:
        tdata = open(target_path, 'rb').read()
    except Exception as e:
        return RelocationResult(False, reason=f"could not read target: {e}")

    sig_start = max(0, marker_offset - context_before)
    sig_end = min(len(vdata), marker_offset + marker_len + context_after)
    signature = vdata[sig_start:sig_end]
    if not signature:
        return RelocationResult(False, reason=(
            f"empty signature window around vanilla offset 0x{marker_offset:X}"))

    marker_rel = marker_offset - sig_start  # marker's position within signature

    hits = []
    pos = 0
    while True:
        pos = tdata.find(signature, pos)
        if pos == -1:
            break
        hits.append(pos + marker_rel)
        pos += 1
        if len(hits) > 1:
            break  # already ambiguous, no need to keep scanning

    if len(hits) == 0:
        # Signature didn't match verbatim -- shrink context progressively
        # before giving up, in case content just past the block (e.g. a
        # sibling animation track) differs slightly between builds while the
        # marker+color bytes themselves are unchanged.
        for shrink in (8, 4, 0):
            sig_start2 = max(0, marker_offset - shrink)
            sig_end2 = min(len(vdata), marker_offset + marker_len + shrink)
            sig2 = vdata[sig_start2:sig_end2]
            marker_rel2 = marker_offset - sig_start2
            hits2 = []
            pos = 0
            while True:
                pos = tdata.find(sig2, pos)
                if pos == -1:
                    break
                hits2.append(pos + marker_rel2)
                pos += 1
                if len(hits2) > 1:
                    break
            if len(hits2) == 1:
                hits = hits2
                break
            if len(hits2) > 1:
                return RelocationResult(False, reason=(
                    f"signature relocation ambiguous for marker at vanilla "
                    f"0x{marker_offset:X}: {len(hits2)}+ hits with "
                    f"{shrink}-byte context"))

    if len(hits) == 0:
        return RelocationResult(False, reason=(
            f"signature relocation found no match in target for marker at "
            f"vanilla 0x{marker_offset:X} (tried context {context_before}/"
            f"{context_after} bytes down to 0)"))
    if len(hits) > 1:
        return RelocationResult(False, reason=(
            f"signature relocation ambiguous for marker at vanilla "
            f"0x{marker_offset:X}: multiple hits in target"))

    new_marker_offset = hits[0]
    logger.warning(
        f"[relocate] model-block relocated: vanilla marker 0x{marker_offset:X} "
        f"-> target 0x{new_marker_offset:X}")
    return RelocationResult(True, offset=new_marker_offset, relocated=True)


# =============================================================================
# Top-level guard+relocate entry point used by helpers.py write paths
# =============================================================================

def context_guard(vanilla_path, target_path, offset, write_len,
                  mask_spans=None, context=8, min_compared=4):
    """Prove the write location by NEIGHBORHOOD identity instead of by the
    color bytes themselves: compare the bytes around [offset, offset+write_len)
    between the vanilla reference and the target, skipping every byte inside
    `mask_spans` (the extra's own writable color spans) and the write span
    itself. A previously-installed recolor only changes bytes inside those
    spans, so an intact surrounding context means the layout has NOT shifted
    and writing at `offset` is safe -- this is what lets a mod install cleanly
    ON TOP of another mod (or of itself), where a vanilla-byte guard would
    always fail.

    Returns True only if at least `min_compared` unmasked bytes were compared
    and ALL of them matched (vacuous windows fail closed).
    """
    if not vanilla_path or write_len is None or write_len <= 0:
        return False
    start = max(0, offset - context)
    end = offset + write_len + context
    vwin = read_bytes(vanilla_path, start, end - start)
    twin = read_bytes(target_path, start, end - start)
    if not vwin or len(vwin) != len(twin):
        return False

    def masked(abs_pos):
        if offset <= abs_pos < offset + write_len:
            return True
        for (mstart, mlen) in (mask_spans or []):
            if mstart <= abs_pos < mstart + mlen:
                return True
        return False

    compared = 0
    for i in range(len(vwin)):
        if masked(start + i):
            continue
        if vwin[i] != twin[i]:
            return False
        compared += 1
    return compared >= min_compared


def resolve_write_offset(vanilla_path, target_path, offset, expected_vanilla_bytes,
                          extra_id="?", layer_id="?", also_valid=None,
                          block_kind="ptcl", marker_len=1, force_relocate=False,
                          write_len=None, mask_spans=None):
    """The single chokepoint every extras write path should call before
    seeking to `offset` and writing.

    Args:
        vanilla_path: path to the reference vanilla DAT (storage/test-base/
            files/<target_file>), or None if unavailable (guard-only mode:
            we can still guard against `expected_vanilla_bytes` /
            `also_valid`, we just can't relocate).
        target_path: the file actually being patched.
        offset: the offset the caller WOULD write at (config/detected value,
            assumed correct for a vanilla-shaped target file).
        expected_vanilla_bytes: bytes the guard checks for at `offset` (may
            be None to skip the vanilla check, e.g. when the caller has
            already read a "current" color it trusts more).
        extra_id / layer_id: for the warning message / result payload only.
        also_valid: additional list of acceptable byte strings at `offset`
            (e.g. a previously-applied color the apply path already read) --
            these also pass the guard without triggering relocation.
        block_kind: "ptcl" (particle bank operand -> ptcl_parse identity
            relocation) or "model" (070707/42_48/98 signature scan).
        marker_len: for block_kind="model", how many bytes the marker itself
            is (e.g. 4 for `07 07 07 04`, 2 for `42 48`, 3 for `98 00 NN`).
            Ignored for block_kind="ptcl".
        force_relocate: skip the guard entirely and go straight to
            relocation. For callers that already proved staleness some other
            way (e.g. patch_shine_sparkle_color's own CF marker-byte check
            failed) and just need the new offset.
        write_len: how many bytes the caller will write at `offset`. Enables
            the context guard (neighborhood-identity check) as a second
            chance when the vanilla-byte guard fails -- required for
            installing a mod on top of a previous mod, whose color bytes no
            longer match vanilla even though the layout is unchanged.
        mask_spans: list of (start, len) byte spans the context guard must
            ignore -- every color span this EXTRA can write (a previous
            install changed those, and only those).

    Returns a dict:
        {"offset": int, "relocated": bool}                     on success
        {"offset": None, "skip": True, "reason": str,
         "extra_id": ..., "layer_id": ..., "requested_offset": offset}  on failure
    """
    variants = []
    if expected_vanilla_bytes:
        variants.append(expected_vanilla_bytes)
    if also_valid:
        variants.extend(v for v in also_valid if v)

    if not force_relocate:
        # Fast path: bytes at the offset are vanilla / a known prior color.
        # NOTE: when there are no variants AND no write_len, this passes
        # vacuously (legacy pass-through for callers that opted out of both
        # checks) -- guard_offset([]) returns True.
        if variants and guard_offset(target_path, offset, variants):
            return {"offset": offset, "relocated": False}
        # Second chance: the color bytes differ (previous mod), but the
        # UNMASKED neighborhood is byte-identical to vanilla -- layout is
        # unshifted, the offset is right, the write is safe. This is the
        # mod-on-top-of-mod / reinstall path.
        if (vanilla_path and os.path.exists(vanilla_path)
                and context_guard(vanilla_path, target_path, offset,
                                  write_len, mask_spans)):
            return {"offset": offset, "relocated": False}
        # Legacy pass-through: callers with neither expected bytes nor a
        # usable context check (no write_len, or no vanilla reference to
        # compare against) keep the old unguarded-write behavior.
        if not variants and (write_len is None or not vanilla_path
                             or not os.path.exists(vanilla_path)):
            return {"offset": offset, "relocated": False}

    if not vanilla_path or not os.path.exists(vanilla_path):
        reason = (f"guard failed at 0x{offset:X} and no vanilla reference "
                  f"available to attempt relocation")
        logger.warning(f"[relocate] SKIP {extra_id}/{layer_id}: {reason}")
        return {"offset": None, "skip": True, "reason": reason,
                "extra_id": extra_id, "layer_id": layer_id,
                "requested_offset": offset}

    if block_kind == "ptcl":
        result = relocate_ptcl_operand(vanilla_path, target_path, offset,
                                       expected_vanilla_bytes)
    else:
        result = relocate_by_signature(vanilla_path, target_path, offset, marker_len)

    if not result.ok:
        logger.warning(
            f"[relocate] SKIP {extra_id}/{layer_id} (target offset 0x{offset:X}): "
            f"{result.reason}")
        return {"offset": None, "skip": True, "reason": result.reason,
                "extra_id": extra_id, "layer_id": layer_id,
                "requested_offset": offset}

    # Final verify -- MODEL relocations only. For ptcl relocations the
    # structural identity (script index, opcode kind, ordinal, channels,
    # size re-parsed from the TARGET file) is itself the verification: the
    # bytes at the operand may legitimately be a previous mod's color, and
    # requiring them to equal vanilla would block every install onto an
    # already-modded file. Model signature relocation matched vanilla context
    # bytes verbatim, so this literal-byte check is coherent there.
    if (block_kind != "ptcl" and variants
            and not guard_offset(target_path, result.offset, variants)):
        reason = (f"relocation candidate at 0x{result.offset:X} failed final "
                  f"byte verify (expected one of "
                  f"{[v.hex().upper() for v in variants]})")
        logger.warning(f"[relocate] SKIP {extra_id}/{layer_id}: {reason}")
        return {"offset": None, "skip": True, "reason": reason,
                "extra_id": extra_id, "layer_id": layer_id,
                "requested_offset": offset}

    return {"offset": result.offset, "relocated": True}


def vanilla_reference_path(storage_path, target_file):
    """Resolve the vanilla reference DAT path for `target_file`:
    STORAGE_PATH / "test-base" / "files" / <target_file> -- the same
    convention used by texture_recolor.py, effect_probe.py, datram_probe*.py.
    User installs never had a test-base folder, so a missing file is extracted
    from the recorded vanilla ISO on first use (vanilla_refs.py). Returns None
    if `storage_path` is unset or the reference is unobtainable.
    """
    if not storage_path:
        return None
    candidate = os.path.join(str(storage_path), "test-base", "files", target_file)
    if os.path.exists(candidate):
        return candidate
    try:
        from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
        extracted = ensure_vanilla_ref(target_file, storage_path=storage_path)
        return str(extracted) if extracted else None
    except Exception as e:
        logger.debug(f"[relocate] vanilla reference extraction for {target_file} failed: {e}")
        return None
