"""Small numeric adaptations shared by source readers and native hit writers."""
import math


def shield_bonus(damage, multiplier=1):
    """Melee adds a signed offset to damage for shield depletion only."""
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
           for v in (damage, multiplier)) or multiplier < 0:
        raise ValueError('damage must be finite and shield multiplier finite/nonnegative')
    # Non-damaging declarations (including healing/throw sentinel values) have
    # no ordinary shield hit. Do not turn them into a positive shield bonus.
    return max(0.0, float(damage)) * (float(multiplier) - 1)


def shield_field(value=0):
    """Round/clamp to Melee's signed 8-bit fighter/item script field."""
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('shield damage offset must be finite')
    return max(-128, min(127, round(value)))
