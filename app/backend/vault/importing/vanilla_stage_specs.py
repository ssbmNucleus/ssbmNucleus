"""
Vanilla (non-tournament) stage specs -- GENERATED, do not hand-edit values.

Source of truth: MexStage.FromDOL data serialized by a MexCLI import-iso
scan of the vanilla NTSC 1.02 ISO (scratchpad/gen_vanilla_stage_specs.py).
The code/function pointers are vanilla main.dol addresses, which remain
valid in every m-ex build, so a custom stage wrapping a modded vanilla
GrXx.dat can reuse the vanilla stage's own GOBJ/function tables verbatim.

playlist entries are hand-curated vanilla music ids (the engine's own
stage-music fallback is keyed by vanilla internal id, which an ADDED
stage doesn't have).
"""

VANILLA_STAGE_SPECS = {
    "grcs": {
        "code": "GrCs",
        "hasLanguageVariants": False,
        "name": "Princess Peach's Castle",
        "location": "Mushroom Kingdom",
        "seriesID": 6,
        "vanillaInternalID": 2,
        "playlist": [
            {
                "musicID": 4,
                "chanceToPlay": 100
            }
        ],
        "soundBank": 34,
        "reverbValue1": 1,
        "reverbValue2": 1,
        "collisionMaterials": 2151406776,
        "mapDescPointer": 2151550964,
        "onStageInit": 2149372796,
        "onStageLoad": 2149373088,
        "onStageGo": 2149373092,
        "onGo": 2149372728,
        "onUnknown2": 2149373128,
        "onTouchLine": 2149387012,
        "onUnknown4": 2149387020,
        "unknownValue": 1,
        "movingCollisionPointer": 2151550952,
        "movingCollisionCount": 2
    },
    "grrc": {
        "code": "GrRc",
        "hasLanguageVariants": False,
        "name": "Rainbow Cruise",
        "location": "Mushroom Kingdom",
        "seriesID": 6,
        "vanillaInternalID": 3,
        "playlist": [
            {
                "musicID": 66,
                "chanceToPlay": 100
            }
        ],
        "soundBank": 55,
        "reverbValue1": 1,
        "reverbValue2": 1,
        "collisionMaterials": 2151406856,
        "mapDescPointer": 2151566900,
        "onStageInit": 2149577064,
        "onStageLoad": 2149577368,
        "onStageGo": 2149577372,
        "onGo": 2149577060,
        "onUnknown2": 2149577408,
        "onTouchLine": 2149588048,
        "onUnknown4": 2149588056,
        "unknownValue": 4,
        "movingCollisionPointer": 2151566760,
        "movingCollisionCount": 23
    },
    "grkg": {
        "code": "GrKg",
        "hasLanguageVariants": False,
        "name": "Kongo Jungle",
        "location": "DK Island",
        "seriesID": 1,
        "vanillaInternalID": 4,
        "playlist": [
            {
                "musicID": 33,
                "chanceToPlay": 100
            }
        ],
        "soundBank": 37,
        "reverbValue1": 1,
        "reverbValue2": 1,
        "collisionMaterials": 2151406936,
        "mapDescPointer": 2151552772,
        "onStageInit": 2149405244,
        "onStageLoad": 2149405432,
        "onStageGo": 2149405436,
        "onGo": 2149405240,
        "onUnknown2": 2149405496,
        "onTouchLine": 2149418052,
        "onUnknown4": 2149418060,
        "unknownValue": 1,
        "movingCollisionPointer": 2151552736,
        "movingCollisionCount": 6
    },
    "grgd": {
        "code": "GrGd",
        "hasLanguageVariants": False,
        "name": "Jungle Japes",
        "location": "DK Island",
        "seriesID": 1,
        "vanillaInternalID": 5,
        "playlist": [
            {
                "musicID": 50,
                "chanceToPlay": 100
            }
        ],
        "soundBank": 41,
        "reverbValue1": 1,
        "reverbValue2": 1,
        "collisionMaterials": 2151407016,
        "mapDescPointer": 2151567944,
        "onStageInit": 2149591920,
        "onStageLoad": 2149592100,
        "onStageGo": 2149592140,
        "onGo": 2149591916,
        "onUnknown2": 2149592176,
        "onTouchLine": 2149594568,
        "onUnknown4": 2149594576,
        "unknownValue": 1,
        "movingCollisionPointer": 0,
        "movingCollisionCount": 0
    },
    "grgb": {
        "code": "GrGb",
        "hasLanguageVariants": False,
        "name": "Great Bay",
        "location": "Termina",
        "seriesID": 13,
        "vanillaInternalID": 6,
        "playlist": [
            {
                "musicID": 34,
                "chanceToPlay": 80
            },
            {
                "musicID": 74,
                "chanceToPlay": 20
            }
        ],
        "soundBank": 36,
        "reverbValue1": 1,
        "reverbValue2": 1,
        "collisionMaterials": 2151407096,
        "mapDescPointer": 2151562884,
        "onStageInit": 2149532224,
        "onStageLoad": 2149532368,
        "onStageGo": 2149532372,
        "onGo": 2149532220,
        "onUnknown2": 2149532408,
        "onTouchLine": 2149541900,
        "onUnknown4": 2149541908,
        "unknownValue": 1,
        "movingCollisionPointer": 2151562848,
        "movingCollisionCount": 6
    },
    "grsh": {
        "code": "GrSh",
        "hasLanguageVariants": False,
        "name": "Temple",
        "location": "Hyrule",
        "seriesID": 13,
        "vanillaInternalID": 7,
        "playlist": [
            {
                "musicID": 75,
                "chanceToPlay": 80
            },
            {
                "musicID": 1,
                "chanceToPlay": 20
            }
        ],
        "soundBank": 55,
        "reverbValue1": 24,
        "reverbValue2": 24,
        "collisionMaterials": 2151407176,
        "mapDescPointer": 2151567592,
        "onStageInit": 2149588068,
        "onStageLoad": 2149588208,
        "onStageGo": 2149588212,
        "onGo": 2149588064,
        "onUnknown2": 2149588248,
        "onTouchLine": 2149588804,
        "onUnknown4": 2149588812,
        "unknownValue": 1,
        "movingCollisionPointer": 0,
        "movingCollisionCount": 0
    },
    "grze": {
        "code": "GrZe",
        "hasLanguageVariants": False,
        "name": "Brinstar",
        "location": "Planet Zebes",
        "seriesID": 10,
        "vanillaInternalID": 8,
        "playlist": [
            {
                "musicID": 97,
                "chanceToPlay": 100
            }
        ],
        "soundBank": 40,
        "reverbValue1": 64,
        "reverbValue2": 64,
        "collisionMaterials": 2151407256,
        "mapDescPointer": 2151553584,
        "onStageInit": 2149418148,
        "onStageLoad": 2149418280,
        "onStageGo": 2149418284,
        "onGo": 2149418144,
        "onUnknown2": 2149418320,
        "onTouchLine": 2149436600,
        "onUnknown4": 2149436608,
        "unknownValue": 1,
        "movingCollisionPointer": 2151553552,
        "movingCollisionCount": 5
    },
    "grkr": {
        "code": "GrKr",
        "hasLanguageVariants": False,
        "name": "Brinstar Depths",
        "location": "Planet Zebes",
        "seriesID": 10,
        "vanillaInternalID": 9,
        "playlist": [
            {
                "musicID": 51,
                "chanceToPlay": 100
            }
        ],
        "soundBank": 42,
        "reverbValue1": 128,
        "reverbValue2": 128,
        "collisionMaterials": 2151407336,
        "mapDescPointer": 2151566492,
        "onStageInit": 2149572604,
        "onStageLoad": 2149572756,
        "onStageGo": 2149572760,
        "onGo": 2149572600,
        "onUnknown2": 2149572796,
        "onTouchLine": 2149577044,
        "onUnknown4": 2149577052,
        "unknownValue": 1,
        "movingCollisionPointer": 2151566456,
        "movingCollisionCount": 6
    },
    "gryt": {
        "code": "GrYt",
        "hasLanguageVariants": False,
        "name": "Yoshi's Island",
        "location": "Yoshi's Island",
        "seriesID": 12,
        "vanillaInternalID": 11,
        "playlist": [
            {
                "musicID": 95,
                "chanceToPlay": 80
            },
            {
                "musicID": 77,
                "chanceToPlay": 20
            }
        ],
        "soundBank": 55,
        "reverbValue1": 1,
        "reverbValue2": 1,
        "collisionMaterials": 2151407496,
        "mapDescPointer": 2151567768,
        "onStageInit": 2149588900,
        "onStageLoad": 2149589004,
        "onStageGo": 2149589008,
        "onGo": 2149588896,
        "onUnknown2": 2149589044,
        "onTouchLine": 2149591900,
        "onUnknown4": 2149591908,
        "unknownValue": 1,
        "movingCollisionPointer": 0,
        "movingCollisionCount": 0
    },
    "grgr": {
        "code": "GrGr",
        "hasLanguageVariants": False,
        "name": "Green Greens",
        "location": "Dream Land",
        "seriesID": 5,
        "vanillaInternalID": 13,
        "playlist": [
            {
                "musicID": 35,
                "chanceToPlay": 100
            }
        ],
        "soundBank": 43,
        "reverbValue1": 1,
        "reverbValue2": 1,
        "collisionMaterials": 2151407656,
        "mapDescPointer": 2151577144,
        "onStageInit": 2149659748,
        "onStageLoad": 2149659892,
        "onStageGo": 2149659896,
        "onGo": 2149659736,
        "onUnknown2": 2149659932,
        "onTouchLine": 2149674596,
        "onUnknown4": 2149674604,
        "unknownValue": 1,
        "movingCollisionPointer": 0,
        "movingCollisionCount": 0
    },
    "grcn": {
        "code": "GrCn",
        "hasLanguageVariants": True,
        "name": "Corneria",
        "location": "Lylat System",
        "seriesID": 2,
        "vanillaInternalID": 14,
        "playlist": [
            {
                "musicID": 6,
                "chanceToPlay": 100
            }
        ],
        "soundBank": 35,
        "reverbValue1": 1,
        "reverbValue2": 1,
        "collisionMaterials": 2151407736,
        "mapDescPointer": 2151554444,
        "onStageInit": 2149438288,
        "onStageLoad": 2149438584,
        "onStageGo": 2149438728,
        "onGo": 2149438144,
        "onUnknown2": 2149438764,
        "onTouchLine": 2149461732,
        "onUnknown4": 2149461740,
        "unknownValue": 1,
        "movingCollisionPointer": 2151554360,
        "movingCollisionCount": 8
    },
    "grve": {
        "code": "GrVe",
        "hasLanguageVariants": True,
        "name": "Venom",
        "location": "Lylat System",
        "seriesID": 2,
        "vanillaInternalID": 15,
        "playlist": [
            {
                "musicID": 84,
                "chanceToPlay": 100
            }
        ],
        "soundBank": 44,
        "reverbValue1": 1,
        "reverbValue2": 136,
        "collisionMaterials": 2151407816,
        "mapDescPointer": 2151568268,
        "onStageInit": 2149595928,
        "onStageLoad": 2149596624,
        "onStageGo": 2149596800,
        "onGo": 2149595924,
        "onUnknown2": 2149596836,
        "onTouchLine": 2149608820,
        "onUnknown4": 2149608828,
        "unknownValue": 1,
        "movingCollisionPointer": 2151568200,
        "movingCollisionCount": 5
    },
    "grpu": {
        "code": "GrPu",
        "hasLanguageVariants": False,
        "name": "Poke Floats",
        "location": "Kanto Skies",
        "seriesID": 9,
        "vanillaInternalID": 17,
        "playlist": [
            {
                "musicID": 65,
                "chanceToPlay": 100
            }
        ],
        "soundBank": 55,
        "reverbValue1": 1,
        "reverbValue2": 1,
        "collisionMaterials": 2151407976,
        "mapDescPointer": 2151573504,
        "onStageInit": 2149653760,
        "onStageLoad": 2149653976,
        "onStageGo": 2149653980,
        "onGo": 2149653756,
        "onUnknown2": 2149654016,
        "onTouchLine": 2149658816,
        "onUnknown4": 2149658824,
        "unknownValue": 1,
        "movingCollisionPointer": 0,
        "movingCollisionCount": 0
    },
    "grmc": {
        "code": "GrMc",
        "hasLanguageVariants": False,
        "name": "Mute City",
        "location": "F-Zero Grand Prix",
        "seriesID": 0,
        "vanillaInternalID": 18,
        "playlist": [
            {
                "musicID": 56,
                "chanceToPlay": 100
            }
        ],
        "soundBank": 38,
        "reverbValue1": 1,
        "reverbValue2": 64,
        "collisionMaterials": 2151408056,
        "mapDescPointer": 2151559364,
        "onStageInit": 2149514348,
        "onStageLoad": 2149514460,
        "onStageGo": 2149514464,
        "onGo": 2149514344,
        "onUnknown2": 2149514500,
        "onTouchLine": 2149526460,
        "onUnknown4": 2149526544,
        "unknownValue": 1,
        "movingCollisionPointer": 2151559344,
        "movingCollisionCount": 3
    },
    "grbb": {
        "code": "GrBb",
        "hasLanguageVariants": False,
        "name": "Big Blue",
        "location": "F-Zero Grand Prix",
        "seriesID": 0,
        "vanillaInternalID": 19,
        "playlist": [
            {
                "musicID": 3,
                "chanceToPlay": 80
            },
            {
                "musicID": 55,
                "chanceToPlay": 20
            }
        ],
        "soundBank": 45,
        "reverbValue1": 1,
        "reverbValue2": 1,
        "collisionMaterials": 2151408136,
        "mapDescPointer": 2151557600,
        "onStageInit": 2149472192,
        "onStageLoad": 2149472712,
        "onStageGo": 2149472716,
        "onGo": 2149472188,
        "onUnknown2": 2149472752,
        "onTouchLine": 2149514252,
        "onUnknown4": 2149514260,
        "unknownValue": 1,
        "movingCollisionPointer": 2151557432,
        "movingCollisionCount": 28
    },
    "grot": {
        "code": "GrOt",
        "hasLanguageVariants": True,
        "name": "Onett",
        "location": "Eagleland",
        "seriesID": 8,
        "vanillaInternalID": 20,
        "playlist": [
            {
                "musicID": 60,
                "chanceToPlay": 80
            },
            {
                "musicID": 61,
                "chanceToPlay": 20
            }
        ],
        "soundBank": 39,
        "reverbValue1": 1,
        "reverbValue2": 1,
        "collisionMaterials": 2151408216,
        "mapDescPointer": 2151557088,
        "onStageInit": 2149463864,
        "onStageLoad": 2149464004,
        "onStageGo": 2149464008,
        "onGo": 2149463860,
        "onUnknown2": 2149464044,
        "onTouchLine": 2149472096,
        "onUnknown4": 2149472104,
        "unknownValue": 1,
        "movingCollisionPointer": 0,
        "movingCollisionCount": 0
    },
    "grfs": {
        "code": "GrFs",
        "hasLanguageVariants": False,
        "name": "Fourside",
        "location": "Eagleland",
        "seriesID": 8,
        "vanillaInternalID": 21,
        "playlist": [
            {
                "musicID": 31,
                "chanceToPlay": 100
            }
        ],
        "soundBank": 46,
        "reverbValue1": 1,
        "reverbValue2": 1,
        "collisionMaterials": 2151408296,
        "mapDescPointer": 2151562492,
        "onStageInit": 2149526800,
        "onStageLoad": 2149526944,
        "onStageGo": 2149526948,
        "onGo": 2149526796,
        "onUnknown2": 2149526984,
        "onTouchLine": 2149532128,
        "onUnknown4": 2149532136,
        "unknownValue": 1,
        "movingCollisionPointer": 2151562472,
        "movingCollisionCount": 3
    },
    "grim": {
        "code": "GrIm",
        "hasLanguageVariants": False,
        "name": "Icicle Mountain",
        "location": "Infinite Glacier",
        "seriesID": 4,
        "vanillaInternalID": 22,
        "playlist": [
            {
                "musicID": 40,
                "chanceToPlay": 80
            },
            {
                "musicID": 2,
                "chanceToPlay": 20
            }
        ],
        "soundBank": 55,
        "reverbValue1": 1,
        "reverbValue2": 1,
        "collisionMaterials": 2151408376,
        "mapDescPointer": 2151565080,
        "onStageInit": 2149541996,
        "onStageLoad": 2149544064,
        "onStageGo": 2149544412,
        "onGo": 2149541992,
        "onUnknown2": 2149544416,
        "onTouchLine": 2149558520,
        "onUnknown4": 2149558528,
        "unknownValue": 1,
        "movingCollisionPointer": 2151563440,
        "movingCollisionCount": 195
    },
    "gri1": {
        "code": "GrI1",
        "hasLanguageVariants": False,
        "name": "Kingdom",
        "location": "Mushroom",
        "seriesID": 6,
        "vanillaInternalID": 24,
        "playlist": [
            {
                "musicID": 41,
                "chanceToPlay": 80
            },
            {
                "musicID": 7,
                "chanceToPlay": 20
            }
        ],
        "soundBank": 55,
        "reverbValue1": 1,
        "reverbValue2": 1,
        "collisionMaterials": 2151408536,
        "mapDescPointer": 2151565556,
        "onStageInit": 2149558540,
        "onStageLoad": 2149558660,
        "onStageGo": 2149558664,
        "onGo": 2149558536,
        "onUnknown2": 2149558700,
        "onTouchLine": 2149567408,
        "onUnknown4": 2149567416,
        "unknownValue": 1,
        "movingCollisionPointer": 2151565512,
        "movingCollisionCount": 7
    },
    "gri2": {
        "code": "GrI2",
        "hasLanguageVariants": False,
        "name": "Kingdom II",
        "location": "Mushroom",
        "seriesID": 6,
        "vanillaInternalID": 25,
        "playlist": [
            {
                "musicID": 43,
                "chanceToPlay": 80
            },
            {
                "musicID": 7,
                "chanceToPlay": 20
            }
        ],
        "soundBank": 55,
        "reverbValue1": 1,
        "reverbValue2": 1,
        "collisionMaterials": 2151408616,
        "mapDescPointer": 2151566004,
        "onStageInit": 2149567428,
        "onStageLoad": 2149567660,
        "onStageGo": 2149567664,
        "onGo": 2149567424,
        "onUnknown2": 2149567700,
        "onTouchLine": 2149572584,
        "onUnknown4": 2149572592,
        "unknownValue": 1,
        "movingCollisionPointer": 2151565920,
        "movingCollisionCount": 14
    },
    "grfz": {
        "code": "GrFz",
        "hasLanguageVariants": False,
        "name": "Flat Zone",
        "location": "Superflat World",
        "seriesID": 3,
        "vanillaInternalID": 27,
        "playlist": [
            {
                "musicID": 30,
                "chanceToPlay": 100
            }
        ],
        "soundBank": 55,
        "reverbValue1": 1,
        "reverbValue2": 1,
        "collisionMaterials": 2151408776,
        "mapDescPointer": 2151577920,
        "onStageInit": 2149674616,
        "onStageLoad": 2149674808,
        "onStageGo": 2149674812,
        "onGo": 2149674612,
        "onUnknown2": 2149674816,
        "onTouchLine": 2149679796,
        "onUnknown4": 2149679804,
        "unknownValue": 1,
        "movingCollisionPointer": 0,
        "movingCollisionCount": 0
    },
    "groy": {
        "code": "GrOy",
        "hasLanguageVariants": False,
        "name": "Yoshi's Island N64",
        "location": "Past Stages",
        "seriesID": 12,
        "vanillaInternalID": 29,
        "playlist": [
            {
                "musicID": 59,
                "chanceToPlay": 100
            }
        ],
        "soundBank": 55,
        "reverbValue1": 1,
        "reverbValue2": 1,
        "collisionMaterials": 2151408936,
        "mapDescPointer": 2151572616,
        "onStageInit": 2149640092,
        "onStageLoad": 2149640228,
        "onStageGo": 2149640232,
        "onGo": 2149640088,
        "onUnknown2": 2149640268,
        "onTouchLine": 2149643268,
        "onUnknown4": 2149643276,
        "unknownValue": 1,
        "movingCollisionPointer": 0,
        "movingCollisionCount": 0
    },
    "grok": {
        "code": "GrOk",
        "hasLanguageVariants": False,
        "name": "Kongo Jungle N64",
        "location": "Past Stages",
        "seriesID": 1,
        "vanillaInternalID": 30,
        "playlist": [
            {
                "musicID": 57,
                "chanceToPlay": 100
            }
        ],
        "soundBank": 55,
        "reverbValue1": 1,
        "reverbValue2": 1,
        "collisionMaterials": 2151409016,
        "mapDescPointer": 2151572876,
        "onStageInit": 2149643372,
        "onStageLoad": 2149643492,
        "onStageGo": 2149643496,
        "onGo": 2149643368,
        "onUnknown2": 2149643556,
        "onTouchLine": 2149648256,
        "onUnknown4": 2149648264,
        "unknownValue": 1,
        "movingCollisionPointer": 2151572864,
        "movingCollisionCount": 2
    }
}
