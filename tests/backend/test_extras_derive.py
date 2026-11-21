"""
Tests for helpers.derive_modifications_from_dat -- remaking a downloaded
effect DAT (website effect zip) as a create-shaped {layer: {color}} dict.

Website effect imports used to store only the modded DAT; color-format
extras install from 'modifications', so every imported laser/sideb/shine
installed as a silent no-op (user report 2026-08-19). Derivation reads the
mod DAT through the same offset system get_current uses and must:
  - reproduce config vanilla exactly when reading a vanilla DAT
  - round-trip: apply_hex_patches(derive(mod)) onto vanilla == derive(mod)
  - return {} for model/texture/texture_region types (no readable colors)

Uses the real vanilla EfFxData.dat from storage/test-base/files (read-only,
copies for mutation -- repo convention) plus a synthetic sideb DAT built
around the 3E99999A42480000 marker find_sideb_offsets keys on.
"""
from tests.paths import BACKEND
import shutil
import sys
from pathlib import Path

import pytest

BACKEND_DIR = BACKEND
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import vault.extras.helpers as helpers  # noqa: E402
from vault.extras import color_patch  # noqa: E402
from core.extra_lookup import get_extra_type  # noqa: E402

VANILLA_EFFX = BACKEND_DIR.parent / "storage" / "test-base" / "files" / "EfFxData.dat"

pytestmark = pytest.mark.skipif(
    not VANILLA_EFFX.exists(),
    reason="vanilla EfFxData.dat not present in storage/test-base/files")


def _synthetic_sideb_dat(tmp_path, primary, secondary, tertiary):
    """Minimal DAT body find_sideb_offsets can detect: 12 RGBA color bytes
    (alpha FF) immediately before the 3E99999A42480000 marker."""
    colors = bytes.fromhex(primary + secondary + tertiary)
    assert len(colors) == 12 and colors[3] == colors[7] == colors[11] == 0xFF
    body = b"\x00" * 0x40 + colors + bytes.fromhex("3E99999A42480000") + b"\x00" * 0x40
    p = tmp_path / "PlFc.dat"
    p.write_bytes(body)
    return p


def test_vanilla_shine_derives_config_vanilla():
    cfg = get_extra_type("Fox", "shine")
    mods = helpers.derive_modifications_from_dat(VANILLA_EFFX, "shine", cfg)
    vanilla = cfg["vanilla"]
    assert mods["primary"]["color"] == vanilla["primary"]
    assert mods["secondary"]["color"] == vanilla["secondary"]
    # sparkles only present when the CF-multi records marker-verify
    if "sparkles" in mods:
        assert mods["sparkles"]["color"] == vanilla["sparkles"]


def test_modded_sideb_derives_planted_colors(tmp_path):
    cfg = get_extra_type("Falco", "sideb")
    mod = _synthetic_sideb_dat(tmp_path, "112233FF", "445566FF", "778899FF")
    mods = helpers.derive_modifications_from_dat(mod, "sideb", cfg)
    assert mods["primary"]["color"] == "112233FF"
    assert mods["secondary"]["color"] == "445566FF"
    assert mods["tertiary"]["color"] == "778899FF"


def test_sideb_round_trip_onto_vanilla(tmp_path):
    """derive(mod) applied to a vanilla-colored DAT must re-derive equal --
    the install path writes exactly the downloaded mod's colors."""
    cfg = get_extra_type("Falco", "sideb")
    mod = _synthetic_sideb_dat(tmp_path, "112233FF", "445566FF", "778899FF")
    van_dir = tmp_path / "van"
    van_dir.mkdir()
    target = _synthetic_sideb_dat(van_dir, "0099FFFF", "CCE6FFFF", "FFFFFFFF")
    derived = helpers.derive_modifications_from_dat(mod, "sideb", cfg)
    offsets = helpers.get_dynamic_offsets(target, "sideb", cfg.get("offsets", {}))
    color_patch.apply_hex_patches(target, offsets, derived)
    assert helpers.derive_modifications_from_dat(target, "sideb", cfg) == derived


def test_model_and_texture_region_types_return_empty(tmp_path):
    gun_cfg = get_extra_type("Falco", "gun")
    assert gun_cfg.get("type") == "model"
    assert helpers.derive_modifications_from_dat(VANILLA_EFFX, "gun", gun_cfg) == {}

    shield_cfg = get_extra_type("Fox", "common_shield")
    assert shield_cfg.get("format") == "texture_region"
    assert helpers.derive_modifications_from_dat(
        VANILLA_EFFX, "common_shield", shield_cfg) == {}


def test_unreadable_dat_returns_empty(tmp_path):
    cfg = get_extra_type("Fox", "shine")
    missing = tmp_path / "nope.dat"
    assert helpers.derive_modifications_from_dat(missing, "shine", cfg) == {}


def test_rebuilt_dat_without_layout_derives_nothing(tmp_path):
    """Image/texture shines (NERV, Honeycomb) are REBUILT DATs -- the shine
    hex matrix moves and detection fails. Derivation must return {} rather
    than read garbage colors at vanilla-layout offsets."""
    cfg = get_extra_type("Fox", "shine")
    rebuilt = tmp_path / "EfFxData.dat"
    rebuilt.write_bytes(b"\x00" * 0x30000)  # no 98 00 2B shine pattern
    assert helpers.derive_modifications_from_dat(rebuilt, "shine", cfg) == {}
