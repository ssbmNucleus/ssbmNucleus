"""
Constants for the MEX API backend.

Contains character prefixes, vanilla costume counts, and other static data.
"""

# Character code mapping for costume lookup
# Maps character display name to their 2-letter code
CHAR_PREFIXES = {
    "C. Falcon": "Ca", "Falco": "Fc", "Fox": "Fx",
    "Marth": "Ms", "Roy": "Fe", "Bowser": "Kp",
    "DK": "Dk", "Ganondorf": "Gn", "Jigglypuff": "Pr",
    "Kirby": "Kb", "Link": "Lk", "Luigi": "Lg",
    "Mario": "Mr", "Mewtwo": "Mt", "Ness": "Ns",
    "Peach": "Pe", "Pichu": "Pc", "Pikachu": "Pk",
    "Ice Climbers": "Pp", "Nana": "Nn", "Samus": "Ss", "Sheik": "Sk",
    "Yoshi": "Ys", "Young Link": "Cl", "Zelda": "Zd",
    "Dr. Mario": "Dr", "G&W": "Gw", "Mr. Game & Watch": "Gw"
}


# Vanilla SSBM CSS costume slot order per character (slot 0 = default, left to right on CSS).
# Derived from actual DOL data via MexManager CostumesFromDOL at 0x803C2360.
VANILLA_CSS_COLOR_ORDER = {
    'Bowser':           ['Nr', 'Re', 'Bu', 'Bk'],
    'C. Falcon':        ['Nr', 'Gy', 'Re', 'Wh', 'Gr', 'Bu'],
    'DK':               ['Nr', 'Bk', 'Re', 'Bu', 'Gr'],
    'Dr. Mario':        ['Nr', 'Re', 'Bu', 'Gr', 'Bk'],
    'Falco':            ['Nr', 'Re', 'Bu', 'Gr'],
    'Fox':              ['Nr', 'Or', 'La', 'Gr'],
    'Ganondorf':        ['Nr', 'Re', 'Bu', 'Gr', 'La'],
    'Ice Climbers':     ['Nr', 'Gr', 'Or', 'Re'],
    'Jigglypuff':       ['Nr', 'Re', 'Bu', 'Gr', 'Ye'],
    'Kirby':            ['Nr', 'Ye', 'Bu', 'Re', 'Gr', 'Wh'],
    'Link':             ['Nr', 'Re', 'Bu', 'Bk', 'Wh'],
    'Luigi':            ['Nr', 'Wh', 'Aq', 'Pi'],
    'Mario':            ['Nr', 'Ye', 'Bk', 'Bu', 'Gr'],
    'Marth':            ['Nr', 'Re', 'Gr', 'Bk', 'Wh'],
    'Mewtwo':           ['Nr', 'Re', 'Bu', 'Gr'],
    'Mr. Game & Watch': ['Nr'],
    'Nana':             ['Nr', 'Ye', 'Aq', 'Wh'],
    'Ness':             ['Nr', 'Ye', 'Bu', 'Gr'],
    'Peach':            ['Nr', 'Ye', 'Wh', 'Bu', 'Gr'],
    'Pichu':            ['Nr', 'Re', 'Bu', 'Gr'],
    'Pikachu':          ['Nr', 'Re', 'Bu', 'Gr'],
    'Roy':              ['Nr', 'Re', 'Bu', 'Gr', 'Ye'],
    'Samus':            ['Nr', 'Pi', 'Bk', 'Gr', 'La'],
    'Sheik':            ['Nr', 'Re', 'Bu', 'Gr', 'Wh'],
    'Yoshi':            ['Nr', 'Re', 'Bu', 'Ye', 'Pi', 'Aq'],
    'Young Link':       ['Nr', 'Re', 'Bu', 'Wh', 'Bk'],
    'Zelda':            ['Nr', 'Re', 'Bu', 'Gr', 'Wh'],
}


def vanilla_costume_specs(character):
    """(colour suffix, slot) for each of a character's vanilla costume slots, in CSS order.

    Mr. Game & Watch has four slots that all use PlGwNr: his colours are runtime
    material recolours, not separate costume files.
    """
    if character == 'Mr. Game & Watch':
        return [('Nr', i) for i in range(4)]
    return [(color, i) for i, color in enumerate(
        VANILLA_CSS_COLOR_ORDER.get(character, []))]


# Vanilla Melee has 128 total costumes across all fighters
# (26 playable + Nana + Master Hand)
VANILLA_COSTUME_COUNT = 128

# MD5 hash of vanilla NTSC 1.02 Melee ISO
VANILLA_ISO_MD5 = "0e63d4223b01d9aba596259dc155a174"

# Stage names mapping (add if needed in the future)
STAGE_NAMES = {}
