"""
attributes.py -- the common fighter attributes block (SBM_CommonFighterAttributes,
0x184 bytes at ftData+0x00): walk/run/jump/gravity/weight/shield/landing lag.

Layout transcribed from HSDRaw/Melee/Pl/SBM_CommonFighterAttributes.cs. Every
entry is a 32-bit float except the ones marked int. Edits are in place.
"""
from __future__ import annotations

# (offset, key, type, label)
ATTRIBUTES: list[tuple[int, str, str, str]] = [
    (0x000, "initial_walk_speed", "f", "Initial Walk Speed"),
    (0x004, "walk_acceleration", "f", "Walk Acceleration"),
    (0x008, "max_walk_speed", "f", "Max Walk Speed"),
    (0x00C, "walk_animation_speed", "f", "Walk Animation Speed"),
    (0x010, "mid_walk_point", "f", "Mid Walk Point"),
    (0x014, "fast_walk_speed", "f", "Fast Walk Speed"),
    (0x018, "friction", "f", "Friction"),
    (0x01C, "initial_dash_speed", "f", "Initial Dash Speed"),
    (0x020, "stop_turn_initial_speed_a", "f", "Stop Turn Initial Speed A"),
    (0x024, "stop_turn_initial_speed_b", "f", "Stop Turn Initial Speed B"),
    (0x028, "initial_run_speed", "f", "Run Speed"),
    (0x02C, "run_animation_scale", "f", "Run Animation Scale"),
    (0x030, "dash_lockout_direction", "f", "Dash Lockout Direction"),
    (0x034, "dash_duration_before_running", "f", "Dash Duration Before Running"),
    (0x038, "jump_startup_lag", "f", "Jump Squat Frames"),
    (0x03C, "initial_horizontal_jump_velocity", "f", "Initial Horizontal Jump Velocity"),
    (0x040, "initial_vertical_jump_velocity", "f", "Full Hop Velocity"),
    (0x044, "ground_to_air_jump_momentum_multiplier", "f", "Ground To Air Jump Momentum Multiplier"),
    (0x048, "max_shorthop_horizontal_velocity", "f", "Max Short Hop Horizontal Velocity"),
    (0x04C, "max_shorthop_vertical_velocity", "f", "Short Hop Velocity"),
    (0x050, "vertical_air_jump_multiplier", "f", "Double Jump Height Multiplier"),
    (0x054, "horizontal_air_jump_multiplier", "f", "Double Jump Horizontal Multiplier"),
    (0x058, "number_of_jumps", "i", "Number Of Jumps"),
    (0x05C, "gravity", "f", "Gravity"),
    (0x060, "terminal_velocity", "f", "Fall Speed"),
    (0x064, "aerial_speed", "f", "Air Mobility (acceleration)"),
    (0x068, "aerial_friction", "f", "Aerial Friction"),
    (0x06C, "max_aerial_horizontal_speed", "f", "Max Air Speed"),
    (0x070, "air_friction", "f", "Air Friction"),
    (0x074, "fast_fall_terminal_velocity", "f", "Fast Fall Speed"),
    (0x078, "tilt_turn_forced_velocity", "f", "Tilt Turn Forced Velocity"),
    (0x07C, "jab2_window", "f", "Jab 2 Window"),
    (0x080, "jab3_window", "f", "Jab 3 Window"),
    (0x084, "frames_to_change_direction_on_standing_turn", "f", "Standing Turn Frames"),
    (0x088, "weight", "f", "Weight"),
    (0x08C, "model_scale", "f", "Model Scale"),
    (0x090, "shield_size", "f", "Shield Size"),
    (0x094, "shield_break_initial_velocity", "f", "Shield Break Initial Velocity"),
    (0x098, "rapid_jab_window", "i", "Rapid Jab Window"),
    (0x09C, "clank_speed_multiplier", "f", "Clank Speed Multiplier"),
    (0x0A0, "hit_by_item_flag", "f", "Hit By Item Flag"),
    (0x0A4, "unknown_0xa4", "i", "Unknown 0xA4"),
    (0x0A8, "ledge_jump_horizontal_velocity", "f", "Ledge Jump Horizontal Velocity"),
    (0x0AC, "ledge_jump_vertical_velocity", "f", "Ledge Jump Vertical Velocity"),
    (0x0B0, "item_throw_velocity", "f", "Item Throw Velocity"),
    (0x0B4, "item_throw_damage_scale", "f", "Item Throw Damage Scale"),
    (0x0B8, "run_side_special_momentum", "f", "Run Side Special Momentum"),
    (0x0BC, "egg_size", "f", "Egg Size"),
    (0x0C0, "egg_hurtbox", "f", "Egg Hurtbox"),
    (0x0C4, "egg_hurtbox_x", "f", "Egg Hurtbox X"),
    (0x0C8, "egg_hurtbox_y", "f", "Egg Hurtbox Y"),
    (0x0CC, "egg_hurtbox_z", "f", "Egg Hurtbox Z"),
    (0x0D0, "unknown_0xd0", "f", "Unknown 0xD0"),
    (0x0D4, "unknown_0xd4", "f", "Unknown 0xD4"),
    (0x0D8, "egg_hurtbox_radius", "f", "Egg Hurtbox Radius"),
    (0x0DC, "kirby_neutral_special_star_swallow_damage", "f", "Kirby Star Swallow Damage"),
    (0x0E0, "kirby_neutral_special_star_damage", "f", "Kirby Star Damage"),
    (0x0E4, "normal_landing_lag", "f", "Normal Landing Lag"),
    (0x0E8, "nair_landing_lag", "f", "Nair Landing Lag"),
    (0x0EC, "fair_landing_lag", "f", "Fair Landing Lag"),
    (0x0F0, "bair_landing_lag", "f", "Bair Landing Lag"),
    (0x0F4, "uair_landing_lag", "f", "Uair Landing Lag"),
    (0x0F8, "dair_landing_lag", "f", "Dair Landing Lag"),
    (0x0FC, "victory_screen_model_scale", "f", "Victory Screen Model Scale"),
    (0x100, "wall_tech_x", "f", "Wall Tech X"),
    (0x104, "wall_jump_horizontal_velocity", "f", "Wall Jump Horizontal Velocity"),
    (0x108, "wall_jump_vertical_velocity", "f", "Wall Jump Vertical Velocity"),
    (0x10C, "ceiling_tech_x_direction", "f", "Ceiling Tech X Direction"),
    (0x110, "unknown_0x110", "f", "Unknown 0x110"),
    (0x114, "left_bunny_hood_x", "f", "Left Bunny Hood X"),
    (0x118, "left_bunny_hood_y", "f", "Left Bunny Hood Y"),
    (0x11C, "left_bunny_hood_z", "f", "Left Bunny Hood Z"),
    (0x120, "right_bunny_hood_x", "f", "Right Bunny Hood X"),
    (0x124, "right_bunny_hood_y", "f", "Right Bunny Hood Y"),
    (0x128, "right_bunny_hood_z", "f", "Right Bunny Hood Z"),
    (0x12C, "bunny_hood_size", "f", "Bunny Hood Size"),
    (0x130, "flower_x", "f", "Flower X"),
    (0x134, "flower_y", "f", "Flower Y"),
    (0x138, "flower_z", "f", "Flower Z"),
    (0x13C, "flower_size", "f", "Flower Size"),
    (0x140, "screw_attack_upward_knockback", "f", "Screw Attack Upward Knockback"),
    (0x144, "screw_attack_effect_size", "f", "Screw Attack Effect Size"),
    (0x148, "unknown_0x148", "f", "Unknown 0x148"),
    (0x14C, "bubble_ratio", "f", "Bubble Ratio"),
    (0x150, "freeze_offset_1", "f", "Freeze Offset 1"),
    (0x154, "freeze_offset_2", "f", "Freeze Offset 2"),
    (0x158, "freeze_escape_height", "f", "Freeze Escape Height"),
    (0x15C, "freeze_escape_x_momentum", "f", "Freeze Escape X Momentum"),
    (0x160, "frozen_size", "f", "Frozen Size"),
    (0x164, "warp_star_hitbox_scaling", "f", "Warp Star Hitbox Scaling"),
    (0x168, "unknown_0x168", "f", "Unknown 0x168"),
    (0x16C, "camera_zoom_target_bone", "i", "Camera Zoom Target Bone"),
    (0x170, "magnified_x_sway", "f", "Magnified X Sway"),
    (0x174, "magnified_y_sway", "f", "Magnified Y Sway"),
    (0x178, "magnified_z_sway", "f", "Magnified Z Sway"),
    (0x17C, "footstool_y_offset", "f", "Footstool Y Offset"),
    (0x180, "weight_dependent_throw_flags", "i", "Weight-independent Throw Mask"),
]
SIZE = 0x184

# The handful a player actually reaches for; the rest sit behind "More".
PRIMARY = ["weight", "gravity", "terminal_velocity", "fast_fall_terminal_velocity",
           "initial_run_speed", "max_walk_speed", "initial_dash_speed",
           "max_aerial_horizontal_speed", "aerial_speed",
           "initial_vertical_jump_velocity", "max_shorthop_vertical_velocity",
           "vertical_air_jump_multiplier", "number_of_jumps",
           "jump_startup_lag", "shield_size",
           "normal_landing_lag", "nair_landing_lag", "fair_landing_lag",
           "bair_landing_lag", "uair_landing_lag", "dair_landing_lag"]

BY_KEY = {a[1]: a for a in ATTRIBUTES}
ALIASES = {"fallspeed": "terminal_velocity", "fastfallspeed": "fast_fall_terminal_velocity",
           "runspeed": "initial_run_speed", "dashspeed": "initial_dash_speed",
           "walkspeed": "max_walk_speed", "airspeed": "max_aerial_horizontal_speed",
           "jumpsquat": "jump_startup_lag", "fullhop": "initial_vertical_jump_velocity",
           "shorthop": "max_shorthop_vertical_velocity",
           "doublejump": "vertical_air_jump_multiplier", "jumps": "number_of_jumps"}


def resolve_key(name: str) -> str:
    import re
    if name in BY_KEY:
        return name
    n = re.sub(r"[^0-9a-z]+", "", str(name).lower())
    if n in ALIASES:
        return ALIASES[n]
    for key in BY_KEY:
        if key.replace("_", "") == n:
            return key
    raise KeyError(f"unknown attribute {name!r}")


class Attributes:
    def __init__(self, fd):
        self.fd = fd
        self.base = fd.dat.ptr(fd.ft_root + 0x00)
        if self.base is None:
            raise ValueError("fighter has no attributes block")

    def get(self, key: str):
        off, key, typ, _ = BY_KEY[resolve_key(key)]
        if key == "weight_dependent_throw_flags":
            # ftCo_DatAttrs +0x180 is a byte, followed by three padding bytes.
            # Retain the old public key while exposing the actual mask value.
            return self.fd.dat.u32(self.base + off) >> 24
        return self.fd.dat.f32(self.base + off) if typ == "f" else self.fd.dat.i32(self.base + off)

    def set(self, key: str, value) -> dict:
        off, key, typ, _ = BY_KEY[resolve_key(key)]
        before = self.get(key)
        if key == "weight_dependent_throw_flags":
            if type(value) is not int or not 0 <= value <= 255:
                raise ValueError('throw mask must be an unsigned byte')
            word = self.fd.dat.u32(self.base + off)
            self.fd.dat.set_u32(self.base + off, (value << 24) | (word & 0xFFFFFF))
        elif typ == "f":
            self.fd.dat.set_f32(self.base + off, float(value))
        else:
            self.fd.dat.set_i32(self.base + off, int(value))
        return {"key": key, "before": before, "after": self.get(key),
                "offset": self.base + off}

    def all(self) -> dict:
        return {a[1]: self.get(a[1]) for a in ATTRIBUTES}

    def listing(self) -> list[dict]:
        return [{"key": k, "label": lbl, "type": t, "value": self.get(k),
                 "primary": k in PRIMARY} for _, k, t, lbl in ATTRIBUTES]
