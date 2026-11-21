"""
Tests for vault/extras/relocate.py -- vanilla-byte guarding + automatic
offset relocation for extras hex patches (docs/EXTRAS_AUDIT.md "Offset
safety: guard + relocation").

Covers:
  - clean vanilla write (guard passes, no relocation needed)
  - re-applied write (current bytes == a previously-applied color, guard
    passes via `also_valid`)
  - shifted file: a copy of a REAL vanilla Ef file with bytes inserted before
    the ptcl bank (dsize/effect-table pointers fixed up to stay a valid HSD
    archive) -- every ptcl color operand moves by a constant offset; parser
    relocation must find the new offset structurally, not by raw seek
  - ambiguous / failed relocation -> skip, no write
  - model-region (070707) signature relocation
  - apply_hex_patches / patch_shine_sparkle_color end-to-end with `safety=`

Uses the real vanilla EfFxData.dat from storage/test-base/files (read-only;
copies are made for every mutated fixture, per repo convention -- never
modify storage/test-base/files in place).
"""
from tests.paths import BACKEND
import struct
import sys
from pathlib import Path

import pytest

BACKEND_DIR = BACKEND
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
SKINLAB_DIR = BACKEND_DIR / "shared" / "rendering"
if str(SKINLAB_DIR) not in sys.path:
    sys.path.insert(0, str(SKINLAB_DIR))

import ptcl_parse  # noqa: E402
import vault.extras.relocate as relocate  # noqa: E402
import vault.extras.helpers as helpers  # noqa: E402
from vault.extras import color_patch  # noqa: E402

VANILLA_EFFX = BACKEND_DIR.parent / "storage" / "test-base" / "files" / "EfFxData.dat"

# Ground-truth ptcl-bank color offset from ptcl_parse.GROUND_TRUTH /
# PTCL_FORMAT.md: shine sparkles rec1 primary, PrimCol, vanilla bytes FFFFFF.
SPARKLE_PRIMARY_OFFSET = 0x127
SPARKLE_PRIMARY_VANILLA = bytes.fromhex("FFFFFF")

pytestmark = pytest.mark.skipif(
    not VANILLA_EFFX.exists(), reason="storage/test-base/files/EfFxData.dat not present")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def vanilla_copy(tmp_path):
    """A writable copy of the real vanilla EfFxData.dat."""
    dst = tmp_path / "EfFxData.dat"
    dst.write_bytes(VANILLA_EFFX.read_bytes())
    return dst


@pytest.fixture
def shifted_copy(tmp_path):
    """A copy of the real vanilla EfFxData.dat with PAD bytes inserted into
    the Models[] region (between the effect-table pointers and the
    ParticleGroup) -- a valid HSD archive where every ptcl-bank color operand
    has moved by a constant offset relative to vanilla, simulating what a
    HSDRawViewer re-save (texture/model import) does to layout.
    """
    data = bytearray(VANILLA_EFFX.read_bytes())
    ds = ptcl_parse.DATA_START
    et_off = ds  # single public root at data offset 0 for Ef*Data files
    fsize, dsize, nreloc, npub = struct.unpack_from(">IIII", data, 0)
    part_ptr = struct.unpack_from(">I", data, et_off + 0)[0]
    tex_ptr = struct.unpack_from(">I", data, et_off + 4)[0]
    pg = ds + part_ptr

    insert_at = et_off + 8  # right after the two effect-table pointers
    pad = 32
    assert insert_at <= pg, "fixture assumption: Models[] region has room before ParticleGroup"

    new = bytearray()
    new += data[:insert_at]
    new += b"\x00" * pad
    new += data[insert_at:]

    struct.pack_into(">I", new, 0, fsize + pad)
    struct.pack_into(">I", new, 4, dsize + pad)
    struct.pack_into(">I", new, et_off + 0, part_ptr + pad)
    struct.pack_into(">I", new, et_off + 4, tex_ptr + pad)

    dst = tmp_path / "EfFxData_shifted.dat"
    dst.write_bytes(bytes(new))
    return dst, pad


@pytest.fixture
def unrelated_copy(tmp_path):
    """A file with NO relationship to the vanilla ptcl bank (garbage bytes) --
    relocation must fail cleanly rather than crash or write garbage."""
    dst = tmp_path / "EfFxData_garbage.dat"
    dst.write_bytes(b"\xAB" * 4096)
    return dst


# ---------------------------------------------------------------------------
# guard_offset / resolve_write_offset -- clean + re-applied writes
# ---------------------------------------------------------------------------

def test_guard_passes_on_clean_vanilla_bytes(vanilla_copy):
    result = relocate.resolve_write_offset(
        str(VANILLA_EFFX), str(vanilla_copy), SPARKLE_PRIMARY_OFFSET,
        SPARKLE_PRIMARY_VANILLA, extra_id="shine", layer_id="sparkles")
    assert result == {"offset": SPARKLE_PRIMARY_OFFSET, "relocated": False}


def test_guard_passes_on_previously_applied_color(vanilla_copy):
    # Simulate a prior install: overwrite the vanilla bytes with a custom
    # color (as apply_hex_patches would have done on a previous build).
    prior_color = bytes.fromhex("112233")
    with open(vanilla_copy, "r+b") as f:
        f.seek(SPARKLE_PRIMARY_OFFSET)
        f.write(prior_color)

    # Guard against vanilla bytes alone would fail (current != vanilla) --
    # but `also_valid` (the "already read current color" path) accepts it.
    result = relocate.resolve_write_offset(
        str(VANILLA_EFFX), str(vanilla_copy), SPARKLE_PRIMARY_OFFSET,
        SPARKLE_PRIMARY_VANILLA, extra_id="shine", layer_id="sparkles",
        also_valid=[prior_color])
    assert result == {"offset": SPARKLE_PRIMARY_OFFSET, "relocated": False}


def test_guard_fails_without_vanilla_or_prior_match(vanilla_copy):
    with open(vanilla_copy, "r+b") as f:
        f.seek(SPARKLE_PRIMARY_OFFSET)
        f.write(bytes.fromhex("445566"))  # neither vanilla nor a known prior color

    # No vanilla_path passed -> guard fails, no way to relocate -> skip.
    result = relocate.resolve_write_offset(
        None, str(vanilla_copy), SPARKLE_PRIMARY_OFFSET,
        SPARKLE_PRIMARY_VANILLA, extra_id="shine", layer_id="sparkles")
    assert result["offset"] is None
    assert result["skip"] is True
    assert "no vanilla reference" in result["reason"]


# ---------------------------------------------------------------------------
# ptcl-bank relocation on a genuinely shifted file
# ---------------------------------------------------------------------------

def test_ptcl_relocation_finds_shifted_operand(shifted_copy):
    shifted_path, pad = shifted_copy

    # A naive guard at the ORIGINAL vanilla offset must fail (bytes there are
    # now zero-padding, not FFFFFFFF), forcing relocation.
    result = relocate.resolve_write_offset(
        str(VANILLA_EFFX), str(shifted_path), SPARKLE_PRIMARY_OFFSET,
        SPARKLE_PRIMARY_VANILLA, extra_id="shine", layer_id="sparkles_primary")

    assert result["offset"] == SPARKLE_PRIMARY_OFFSET + pad
    assert result["relocated"] is True


def test_ptcl_relocation_writes_land_on_correct_bytes(shifted_copy):
    """End-to-end: after relocation, writing the new color actually lands on
    the PrimCol operand (not on adjacent bytecode) -- verified by re-parsing
    the patched file and confirming script structure is intact (no hang-the-
    game corruption: the byte immediately after the 4-byte RGBA operand must
    still decode as a valid opcode continuation, i.e. the walk doesn't error)."""
    shifted_path, pad = shifted_copy
    new_color = bytes.fromhex("00FF00FF")  # green RGBA (PrimCol channels=RGBA)

    result = relocate.resolve_write_offset(
        str(VANILLA_EFFX), str(shifted_path), SPARKLE_PRIMARY_OFFSET,
        SPARKLE_PRIMARY_VANILLA, extra_id="shine", layer_id="sparkles_primary")
    assert result["offset"] is not None

    with open(shifted_path, "r+b") as f:
        f.seek(result["offset"])
        f.write(new_color)

    # Re-parse: the script must still walk cleanly and the operand at the
    # relocated offset must now read back the new color.
    data = shifted_path.read_bytes()
    hdr, scripts = ptcl_parse.parse_bank(data)
    found = None
    for sc in scripts:
        for c in sc.colors:
            if c["file_off"] == result["offset"]:
                found = c
    assert found is not None
    assert found["bytes"] == new_color.hex().upper()


def test_ptcl_relocation_fails_on_unrelated_file(vanilla_copy, unrelated_copy):
    result = relocate.resolve_write_offset(
        str(VANILLA_EFFX), str(unrelated_copy), SPARKLE_PRIMARY_OFFSET,
        SPARKLE_PRIMARY_VANILLA, extra_id="shine", layer_id="sparkles_primary")
    assert result["offset"] is None
    assert result["skip"] is True


def test_ptcl_relocation_offset_not_a_color_operand(vanilla_copy):
    """Guard fails at an offset that isn't a ptcl color operand at all (e.g.
    mid-bytecode garbage) -- relocation must report 'not eligible', not crash,
    and never write."""
    bogus_offset = 0x10  # inside the HSD header, not a color operand
    with open(vanilla_copy, "r+b") as f:
        f.seek(bogus_offset)
        current = f.read(3)
    # Guard against a color that's neither the current bytes at 0x10 nor
    # anything close -- force a guard failure so relocation is attempted.
    fake_vanilla = bytes((b ^ 0xFF) for b in current) or b"\x01\x02\x03"
    result = relocate.resolve_write_offset(
        str(VANILLA_EFFX), str(vanilla_copy), bogus_offset, fake_vanilla,
        extra_id="shine", layer_id="bogus")
    assert result["offset"] is None
    assert result["skip"] is True
    assert "not a ptcl-bank color operand" in result["reason"]


# ---------------------------------------------------------------------------
# Model-region (070707) signature relocation
# ---------------------------------------------------------------------------

def _build_070707_fixture(tmp_path, shift=0):
    """A tiny synthetic file with a 07 07 07 04 model-color block, optionally
    preceded by `shift` bytes of unrelated padding (simulating a model-region
    insert upstream of the block)."""
    prefix = b"\x11\x22\x33\x44" * 8  # 32 bytes of unrelated context
    marker = b"\x07\x07\x07\x04"
    color1 = b"\xFF\xB2\x00"   # falcon-kick-tip-style vanilla color1
    color2 = b"\xFF\xE5\x00"
    suffix = b"\x66\x77\x88\x99" * 8
    block = marker + color1 + b"\x00" + color2
    data = prefix + block + suffix
    if shift:
        data = (b"\x00" * shift) + data
    path = tmp_path / f"model_{shift}.dat"
    path.write_bytes(data)
    marker_off = len(prefix) + (shift if shift else 0)
    return path, marker_off


def test_signature_relocation_finds_shifted_070707_block(tmp_path):
    vanilla_path, vanilla_marker_off = _build_070707_fixture(tmp_path, shift=0)
    target_path, target_marker_off = _build_070707_fixture(tmp_path, shift=48)

    result = relocate.relocate_by_signature(
        str(vanilla_path), str(target_path), vanilla_marker_off, marker_len=4)

    assert result.ok
    assert result.offset == target_marker_off
    assert result.relocated is True


def test_signature_relocation_ambiguous_when_multiple_hits(tmp_path):
    vanilla_path, vanilla_marker_off = _build_070707_fixture(tmp_path, shift=0)

    # Target contains the SAME block twice (ambiguous) -- build directly.
    single_data = vanilla_path.read_bytes()
    target = single_data + single_data
    target_path = tmp_path / "model_ambiguous.dat"
    target_path.write_bytes(target)

    result = relocate.relocate_by_signature(
        str(vanilla_path), str(target_path), vanilla_marker_off, marker_len=4)

    assert not result.ok
    assert "ambiguous" in result.reason


def test_signature_relocation_no_match_skips(tmp_path):
    vanilla_path, vanilla_marker_off = _build_070707_fixture(tmp_path, shift=0)
    target_path = tmp_path / "model_nomatch.dat"
    target_path.write_bytes(b"\x00" * 512)  # no block present at all

    result = relocate.relocate_by_signature(
        str(vanilla_path), str(target_path), vanilla_marker_off, marker_len=4)

    assert not result.ok
    assert "no match" in result.reason


# ---------------------------------------------------------------------------
# color_patch.apply_hex_patches / patch_shine_sparkle_color end-to-end with safety=
# ---------------------------------------------------------------------------

def test_apply_hex_patches_relocates_cf_layer_on_shifted_file(shifted_copy, monkeypatch):
    shifted_path, pad = shifted_copy
    monkeypatch.setattr(helpers, "STORAGE_PATH", VANILLA_EFFX.parent.parent.parent)

    offsets = {
        # marker CF written at ORIGINAL vanilla offset (marker = color-2);
        # sparkle rec1 marker per ptcl_parse GROUND_TRUTH is 0x125.
        "sparkles_c1": {"format": "CF", "offsets": [0x125]},
    }
    modifications = {"sparkles_c1": {"color": "00FF00"}}
    safety = helpers.make_write_safety(
        str(shifted_path), "shine", "EfFxData.dat",
        vanilla_map={"sparkles_c1": "FFFFFF"})

    skips = color_patch.apply_hex_patches(str(shifted_path), offsets, modifications, safety=safety)
    assert skips == []

    # Verify the color landed at the RELOCATED offset, not the stale one.
    with open(shifted_path, "rb") as f:
        f.seek(0x125 + 2 + pad)
        assert f.read(3) == bytes.fromhex("00FF00")
        # and NOT at the stale original offset (that's now padding/garbage)
        f.seek(0x125 + 2)
        assert f.read(3) != bytes.fromhex("00FF00")


def test_apply_hex_patches_skips_layer_when_relocation_impossible(unrelated_copy, monkeypatch, tmp_path):
    monkeypatch.setattr(helpers, "STORAGE_PATH", VANILLA_EFFX.parent.parent.parent)

    offsets = {"sparkles_c1": {"format": "CF", "offsets": [0x125]}}
    modifications = {"sparkles_c1": {"color": "00FF00"}}
    safety = helpers.make_write_safety(
        str(unrelated_copy), "shine", "EfFxData.dat",
        vanilla_map={"sparkles_c1": "FFFFFF"})

    before = unrelated_copy.read_bytes()
    skips = color_patch.apply_hex_patches(str(unrelated_copy), offsets, modifications, safety=safety)

    assert len(skips) == 1
    assert skips[0]["layer_id"] == "sparkles_c1[0]"
    assert skips[0]["skip"] is True
    # File must be byte-identical -- a failed relocation must never write.
    assert unrelated_copy.read_bytes() == before


def test_apply_hex_patches_no_safety_is_unaffected(vanilla_copy):
    """Backward-compat: omitting `safety` writes unconditionally exactly like
    before this feature existed."""
    offsets = {"sparkles_c1": {"format": "CF", "offsets": [0x125]}}
    modifications = {"sparkles_c1": {"color": "00FF00"}}

    result = color_patch.apply_hex_patches(str(vanilla_copy), offsets, modifications)
    assert result == []

    with open(vanilla_copy, "rb") as f:
        f.seek(0x127)
        assert f.read(3) == bytes.fromhex("00FF00")


def test_patch_shine_sparkle_color_relocates_on_shifted_file(shifted_copy, monkeypatch):
    shifted_path, pad = shifted_copy
    monkeypatch.setattr(helpers, "STORAGE_PATH", VANILLA_EFFX.parent.parent.parent)

    # sparkles_offset uses the ORIGINAL (stale) marker/color/secondary
    # offsets from extra_types.py's shine_gradient config.
    sparkles_offset = {
        "records": [
            {"marker": 0x125, "color": 0x127, "secondary": 0x12E},
        ]
    }
    safety = helpers.make_write_safety(
        str(shifted_path), "shine", "EfFxData.dat", vanilla_map={})

    color_patch.patch_shine_sparkle_color(str(shifted_path), sparkles_offset, "00FF00", safety=safety)

    with open(shifted_path, "rb") as f:
        f.seek(0x127 + pad)
        assert f.read(3) == bytes.fromhex("00FF00")
        f.seek(0x12E + pad)
        assert f.read(3) == bytes.fromhex("00FF00")


def test_patch_shine_sparkle_color_skips_without_safety_on_bad_marker(vanilla_copy):
    """Pre-existing behavior (no relocation attempted) is preserved when
    `safety` is omitted: a marker mismatch just skips that record."""
    sparkles_offset = {"records": [{"marker": 0x0, "color": 0x2, "secondary": 0x9}]}
    before = vanilla_copy.read_bytes()
    color_patch.patch_shine_sparkle_color(str(vanilla_copy), sparkles_offset, "00FF00")
    assert vanilla_copy.read_bytes() == before


# ---------------------------------------------------------------------------
# Mod on top of mod: reinstall / restore over previously-applied colors
# (2026-07-03 audit -- the vanilla-byte guard alone made every second install
# a silent per-layer skip)
# ---------------------------------------------------------------------------

def test_context_guard_passes_on_recolored_unshifted_file(vanilla_copy):
    """A previous install changed the color bytes but nothing else: the
    context guard proves the layout via the unmasked neighborhood and blesses
    the ORIGINAL offset without relocation."""
    with open(vanilla_copy, "r+b") as f:
        f.seek(SPARKLE_PRIMARY_OFFSET)
        f.write(bytes.fromhex("445566"))  # previous mod's color

    result = relocate.resolve_write_offset(
        str(VANILLA_EFFX), str(vanilla_copy), SPARKLE_PRIMARY_OFFSET,
        SPARKLE_PRIMARY_VANILLA, extra_id="shine", layer_id="sparkles",
        write_len=3, mask_spans=[(SPARKLE_PRIMARY_OFFSET, 3)])
    assert result == {"offset": SPARKLE_PRIMARY_OFFSET, "relocated": False}


def test_context_guard_masks_recolored_neighbor_layer(vanilla_copy):
    """The CF secondary sits at primary+7 -- inside the primary's context
    window. With BOTH spans masked (as compute_mask_spans provides), a fully
    recolored record still passes the context guard."""
    with open(vanilla_copy, "r+b") as f:
        f.seek(SPARKLE_PRIMARY_OFFSET)
        f.write(bytes.fromhex("445566"))
        f.seek(SPARKLE_PRIMARY_OFFSET + 7)
        f.write(bytes.fromhex("778899"))

    mask = [(SPARKLE_PRIMARY_OFFSET, 3), (SPARKLE_PRIMARY_OFFSET + 7, 3)]
    result = relocate.resolve_write_offset(
        str(VANILLA_EFFX), str(vanilla_copy), SPARKLE_PRIMARY_OFFSET,
        SPARKLE_PRIMARY_VANILLA, extra_id="shine", layer_id="sparkles",
        write_len=3, mask_spans=mask)
    assert result == {"offset": SPARKLE_PRIMARY_OFFSET, "relocated": False}

    # Without the neighbor masked, the context guard must fail closed (the
    # recolored secondary breaks neighborhood identity) -- and then ptcl
    # identity relocation still resolves the same offset structurally.
    result = relocate.resolve_write_offset(
        str(VANILLA_EFFX), str(vanilla_copy), SPARKLE_PRIMARY_OFFSET,
        SPARKLE_PRIMARY_VANILLA, extra_id="shine", layer_id="sparkles",
        write_len=3, mask_spans=[(SPARKLE_PRIMARY_OFFSET, 3)])
    assert result["offset"] == SPARKLE_PRIMARY_OFFSET
    assert result["relocated"] is True


def test_ptcl_relocation_trusts_identity_on_shifted_and_modded_file(shifted_copy):
    """Shifted layout AND a previous mod's color at the moved operand: the
    old final byte-verify (vanilla bytes required) would skip; structural
    identity must win."""
    shifted_path, pad = shifted_copy
    with open(shifted_path, "r+b") as f:
        f.seek(SPARKLE_PRIMARY_OFFSET + pad)
        f.write(bytes.fromhex("445566"))  # previous mod applied post-shift

    result = relocate.resolve_write_offset(
        str(VANILLA_EFFX), str(shifted_path), SPARKLE_PRIMARY_OFFSET,
        SPARKLE_PRIMARY_VANILLA, extra_id="shine", layer_id="sparkles",
        write_len=3, mask_spans=[(SPARKLE_PRIMARY_OFFSET, 3)])
    assert result["offset"] == SPARKLE_PRIMARY_OFFSET + pad
    assert result["relocated"] is True


def test_apply_hex_patches_reinstall_over_previous_mod(vanilla_copy, monkeypatch):
    """Install mod A, then mod B on top -- every layer must write both times
    (the original user-visible bug: second install skipped all layers)."""
    monkeypatch.setattr(helpers, "STORAGE_PATH", VANILLA_EFFX.parent.parent.parent)

    offsets = {
        "sparkles_c1": {"format": "CF", "offsets": [0x125]},
        "sparkles_c2": {"format": "RGB", "offsets": [0x12E]},
    }
    vanilla_map = {"sparkles_c1": "FFFFFF", "sparkles_c2": "FFE851"}

    for color in ("112233", "445566"):
        mods = {"sparkles_c1": {"color": color}, "sparkles_c2": {"color": color}}
        safety = helpers.make_write_safety(
            str(vanilla_copy), "shine", "EfFxData.dat", vanilla_map=vanilla_map)
        skips = color_patch.apply_hex_patches(str(vanilla_copy), offsets, mods, safety=safety)
        assert skips == [], f"reinstall with {color} skipped layers: {skips}"

    with open(vanilla_copy, "rb") as f:
        f.seek(0x127)
        assert f.read(3) == bytes.fromhex("445566")
        f.seek(0x12E)
        assert f.read(3) == bytes.fromhex("445566")


def test_apply_hex_patches_restore_vanilla_after_mod(vanilla_copy, monkeypatch):
    """Writing the vanilla colors back over an installed mod (restore-vanilla
    with safety) must not skip."""
    monkeypatch.setattr(helpers, "STORAGE_PATH", VANILLA_EFFX.parent.parent.parent)

    offsets = {"sparkles_c1": {"format": "CF", "offsets": [0x125]}}
    vanilla_map = {"sparkles_c1": "FFFFFF"}

    safety = helpers.make_write_safety(
        str(vanilla_copy), "shine", "EfFxData.dat", vanilla_map=vanilla_map)
    assert color_patch.apply_hex_patches(
        str(vanilla_copy), offsets, {"sparkles_c1": {"color": "112233"}},
        safety=safety) == []

    safety = helpers.make_write_safety(
        str(vanilla_copy), "shine", "EfFxData.dat", vanilla_map=vanilla_map)
    skips = color_patch.apply_hex_patches(
        str(vanilla_copy), offsets, {"sparkles_c1": {"color": "FFFFFF"}},
        safety=safety)
    assert skips == []

    with open(vanilla_copy, "rb") as f:
        f.seek(0x127)
        assert f.read(3) == SPARKLE_PRIMARY_VANILLA


def test_matrix_safe_mode_reinstall_and_restore(tmp_path):
    """98-matrix safe mode (offset-level 'vanilla', e.g. Fox/Falco upb tip):
    entries hold the PREVIOUS mod's color after install A, so vanilla-only
    matching made install B and restore silent no-ops. The current-first-entry
    extension must recolor them while leaving non-color entries alone."""
    header = bytes([0x98, 0x00, 0x03])
    entry = lambda v, c: bytes([v]) + c + b"\x00"  # vertex + RGBY color + coord
    vanilla_color = bytes.fromhex("FE60")
    position = bytes.fromhex("1234")  # simulates a mixed-matrix position entry
    data = header + entry(1, vanilla_color) + entry(2, vanilla_color) + entry(3, position)
    path = tmp_path / "matrix.dat"
    path.write_bytes(data)

    offsets = {"tip": {"start": 0, "end": len(data), "format": "RGBY", "vanilla": "FE60"}}

    def colors_at():
        raw = path.read_bytes()
        return [raw[4:6].hex().upper(), raw[8:10].hex().upper(), raw[12:14].hex().upper()]

    color_patch.apply_hex_patches(str(path), offsets, {"tip": {"color": "0F0F"}})
    assert colors_at() == ["0F0F", "0F0F", "1234"]

    # Reinstall with a different color: previously a no-op (nothing matched
    # vanilla FE60 anymore).
    color_patch.apply_hex_patches(str(path), offsets, {"tip": {"color": "ABCD"}})
    assert colors_at() == ["ABCD", "ABCD", "1234"]

    # Restore vanilla: previously also a no-op for the same reason.
    color_patch.apply_hex_patches(str(path), offsets, {"tip": {"color": "FE60"}})
    assert colors_at() == ["FE60", "FE60", "1234"]


def test_070707_passthrough_without_vanilla_reference(tmp_path):
    """070707 layers with no vanilla reference DAT keep the legacy unguarded
    write (no regression from wiring write_len through)."""
    path, marker_off = _build_070707_fixture(tmp_path, shift=0)
    offsets = {"rings": {"format": "070707", "offsets": [marker_off]}}
    safety = helpers.make_write_safety(
        str(path), "upb", "DoesNotExist.dat", vanilla_map={})
    assert safety["vanilla_path"] is None

    skips = color_patch.apply_hex_patches(
        str(path), offsets, {"rings": {"color": "00FF00"}}, safety=safety)
    assert skips == []
    raw = path.read_bytes()
    assert raw[marker_off + 4:marker_off + 7] == bytes.fromhex("00FF00")
    assert raw[marker_off + 8:marker_off + 11] == bytes.fromhex("00FF00")


def test_compute_mask_spans_covers_all_formats():
    offsets = {
        "cf": {"format": "CF", "offsets": [0x100]},
        "rgb": {"format": "RGB", "offsets": [0x200, 0x210]},
        "seven": {"format": "070707", "offsets": [0x300]},
        "direct": {"start": 0x400, "size": 4, "format": "RGBA"},
        "single_cf": {"start": 0x500, "format": "CF"},
        "matrix": {"start": 0x600, "end": 0x640, "format": "RGBY"},
        "multi": {"ranges": [{"start": 0x700, "end": 0x710}], "format": "RGBY"},
        "sparkles": {"format": "CF-multi",
                     "records": [{"marker": 0x125, "color": 0x127, "secondary": 0x12E}]},
    }
    spans = set(helpers.compute_mask_spans(offsets))
    assert (0x102, 3) in spans          # CF color at +2
    assert (0x200, 3) in spans and (0x210, 3) in spans
    assert (0x304, 3) in spans and (0x308, 3) in spans
    assert (0x400, 4) in spans
    assert (0x502, 3) in spans
    assert (0x600, 0x40) in spans
    assert (0x700, 0x10) in spans
    assert (0x127, 3) in spans and (0x12E, 3) in spans


def test_shifted_install_writes_each_interleaved_operand_at_its_own_slot(tmp_path, monkeypatch):
    """Relocation identifies an operand by its index in the script's FULL
    color list. Looking that index up in a kind-filtered list picked another
    operand whenever PrimCol and EnvCol interleave (Fox's charge flames in
    EfCoData.dat), so a shifted install wrote the wrong operands. Every write
    must land exactly `pad` bytes after its vanilla slot."""
    from core.extra_lookup import get_extra_type
    vanilla_coda = VANILLA_EFFX.parent / "EfCoData.dat"
    if not vanilla_coda.exists():
        pytest.skip("storage/test-base/files/EfCoData.dat not present")
    monkeypatch.setattr(helpers, "STORAGE_PATH", VANILLA_EFFX.parent.parent.parent)
    pad = 32
    data = bytearray(vanilla_coda.read_bytes())
    ds = ptcl_parse.DATA_START
    fsize, dsize = struct.unpack_from(">II", data, 0)
    part_ptr, tex_ptr = struct.unpack_from(">II", data, ds)
    shifted = bytearray(data[:ds + 8]) + b"\x00" * pad + data[ds + 8:]
    struct.pack_into(">II", shifted, 0, fsize + pad, dsize + pad)
    struct.pack_into(">II", shifted, ds, part_ptr + pad, tex_ptr + pad)
    target = tmp_path / "EfCoData.dat"
    target.write_bytes(bytes(shifted))

    cfg = get_extra_type("Fox", "charge_flames")
    safety = helpers.make_write_safety(str(target), "charge_flames", "EfCoData.dat",
                                       cfg["vanilla"])
    mods = {layer: {"color": "12AB34"} for layer in cfg["offsets"]}
    assert color_patch.apply_hex_patches(str(target), cfg["offsets"], mods, safety=safety) == []
    expected = bytearray(shifted)
    for info in cfg["offsets"].values():
        for offset in info["offsets"]:
            expected[offset + pad:offset + pad + 3] = bytes.fromhex("12AB34")
    assert target.read_bytes() == bytes(expected)
