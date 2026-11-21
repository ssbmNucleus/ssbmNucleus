"""
Looking extras up in the catalog (core/extra_types.py): which extras a
character has (its own plus the ones it shares with another fighter), one
extra by id, the character a shared extra is stored under, and the unit a
part belongs to or the parts of a unit.
"""

from core.extra_types import EXTRA_TYPES, UNIT_PARTS, PART_OWNER


def part_owner(type_id):
    """The unit (primary extra type id) a part belongs to, else None."""
    return PART_OWNER.get(type_id)


def get_unit_parts(character, type_id):
    """[(part_id, config)] for the parts of a unit that THIS character has
    (charge_flames is Fox-only even though Up-B is shared with Falco)."""
    out = []
    for part_id in UNIT_PARTS.get(type_id, []):
        cfg = get_extra_type(character, part_id)
        if cfg:
            out.append((part_id, cfg))
    return out


def has_extras(character):
    """Check if a character has any extras available (including shared)."""
    if character in EXTRA_TYPES and len(EXTRA_TYPES[character]) > 0:
        return True
    # Check if any other character has shared extras for this character
    for other_char, extras in EXTRA_TYPES.items():
        for extra in extras:
            if extra.get('shared') and character in extra.get('sharedWith', []):
                return True
    return False


def get_extra_types(character):
    """Get all extra types for a character, including shared extras from other characters."""
    # Start with the character's own extras
    result = list(EXTRA_TYPES.get(character, []))

    # Add shared extras from other characters
    for other_char, extras in EXTRA_TYPES.items():
        if other_char == character:
            continue
        for extra in extras:
            if extra.get('shared') and character in extra.get('sharedWith', []):
                # Include the shared extra (it's already configured with owner info)
                result.append(extra)

    return result


def get_extra_type(character, type_id):
    """Get a specific extra type by id (including shared extras)."""
    # Use get_extra_types which includes shared extras
    types = get_extra_types(character)
    for t in types:
        if t["id"] == type_id:
            return t
    return None


def get_storage_character(character, extra_type):
    """Get the character to use for storage (owner for shared extras).

    For shared extras, mods are stored under the owner character.
    This ensures only one set of mods exists for shared effects.
    """
    type_config = get_extra_type(character, extra_type)
    if type_config and type_config.get('shared'):
        return type_config.get('owner', character)
    return character
