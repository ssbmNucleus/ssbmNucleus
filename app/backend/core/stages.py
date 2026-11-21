"""
core/stages.py -- the ONE registry of Melee's versus stages.

Every backend table that used to spell out the six tournament stages by hand
(DAS blueprint, mod export, vault scanners, duel assembler, test-ISO builder,
music playlists, replay browser) derives from this module, so adding a stage
or fixing a name happens in exactly one place.

Two install models hang off the registry:

* ``mode == 'das'`` -- the six tournament-legal stages. Nucleus installs the
  community Dynamic Alternate Stages loader over the root file and the
  project keeps a ``files/<Code>/`` folder of button-selectable alternates.
  DAS loaders are per-stage compiled binaries (UnclePunch's private
  ``m-ex-projects/stage/dynamicalts``); Nucleus has the six under
  ``utility/DynamicAlternateStages/`` and cannot generate more. Each keeps much
  of the game's own stage file, so each ships as an xdelta patch against the
  user's own vanilla root (``projects/install/das_loaders.py``).
* ``mode == 'replace'`` -- every other versus stage. A skin is written straight
  over the vanilla root file(s) in the project (one active look per stage) and
  the vanilla file is restored from the user's recorded ISO on demand. This is
  what the ``projects/routes/stage_slots.py`` panel drives.

Field guide (one dict per stage, in ``VS_STAGES``):

``code``               Gr file code, e.g. ``'GrNBa'``.
``name``               Display name shown in the app.
``project_name``       The stage's name inside an m-ex project (what
                       ``mexcli set-stage-playlist`` and the in-game selector
                       match on). Differs from ``name`` only for Dream Land
                       and the two Mushroom Kingdoms.
``folder``             Vault folder slug (``storage/das/<folder>`` for DAS
                       variants; also the replay browser's key).
``legal``              True for the six tournament stages.
``dual_root``          True when the retail (En,Ja) disc carries both
                       ``<code>.dat`` (Japanese) and ``<code>.usd`` (English)
                       and the game picks by save language. Replacement
                       installs must write BOTH files.
``internal_id``        Melee internal stage id (``GrKind``); the value an
                       ADDED custom stage is given by vanilla_stage_specs.
``slippi_id``          The .slp / external stage id.
``series``             Franchise label for grouping in the UI.
"""

from core.config import BASE_PATH

DAS_LOADER_DIR = BASE_PATH / "utility" / "DynamicAlternateStages"


def _stage(code, name, folder, *, legal=False, dual_root=False, internal_id,
           slippi_id, series, project_name=None):
    return {
        'code': code,
        'name': name,
        'project_name': project_name or name,
        'folder': folder,
        'legal': legal,
        'dual_root': dual_root,
        'internal_id': internal_id,
        'slippi_id': slippi_id,
        'series': series,
    }


# Order matters: the six legal stages come first in the order the Stages panel
# has always listed them; the rest follow Melee's internal-id order (which is
# also the vanilla stage-select reading order).
VS_STAGES = [
    _stage('GrOp', 'Dreamland', 'dreamland', legal=True, internal_id=28, slippi_id=28,
           series='Kirby', project_name='Dream Land N64'),
    _stage('GrPs', 'Pokemon Stadium', 'pokemon_stadium', legal=True, dual_root=True,
           internal_id=16, slippi_id=3, series='Pokemon'),
    _stage('GrSt', "Yoshi's Story", 'yoshis_story', legal=True, internal_id=10, slippi_id=8,
           series='Yoshi'),
    _stage('GrNBa', 'Battlefield', 'battlefield', legal=True, internal_id=31, slippi_id=31,
           series='Smash'),
    _stage('GrIz', 'Fountain of Dreams', 'fountain_of_dreams', legal=True, internal_id=12,
           slippi_id=2, series='Kirby'),
    _stage('GrNLa', 'Final Destination', 'final_destination', legal=True, internal_id=32,
           slippi_id=32, series='Smash'),

    _stage('GrCs', "Princess Peach's Castle", 'peachs_castle', internal_id=2, slippi_id=4,
           series='Mario'),
    _stage('GrRc', 'Rainbow Cruise', 'rainbow_cruise', internal_id=3, slippi_id=11,
           series='Mario'),
    _stage('GrKg', 'Kongo Jungle', 'kongo_jungle', internal_id=4, slippi_id=5,
           series='Donkey Kong'),
    _stage('GrGd', 'Jungle Japes', 'jungle_japes', internal_id=5, slippi_id=12,
           series='Donkey Kong'),
    _stage('GrGb', 'Great Bay', 'great_bay', internal_id=6, slippi_id=13, series='Zelda'),
    _stage('GrSh', 'Temple', 'temple', internal_id=7, slippi_id=14, series='Zelda'),
    _stage('GrZe', 'Brinstar', 'brinstar', internal_id=8, slippi_id=6, series='Metroid'),
    _stage('GrKr', 'Brinstar Depths', 'brinstar_depths', internal_id=9, slippi_id=15,
           series='Metroid'),
    _stage('GrYt', "Yoshi's Island", 'yoshis_island', internal_id=11, slippi_id=16,
           series='Yoshi'),
    _stage('GrGr', 'Green Greens', 'green_greens', internal_id=13, slippi_id=17, series='Kirby'),
    _stage('GrCn', 'Corneria', 'corneria', dual_root=True, internal_id=14, slippi_id=7,
           series='Star Fox'),
    _stage('GrVe', 'Venom', 'venom', dual_root=True, internal_id=15, slippi_id=22,
           series='Star Fox'),
    _stage('GrPu', 'Poke Floats', 'poke_floats', internal_id=17, slippi_id=23, series='Pokemon'),
    _stage('GrMc', 'Mute City', 'mute_city', internal_id=18, slippi_id=10, series='F-Zero'),
    _stage('GrBb', 'Big Blue', 'big_blue', internal_id=19, slippi_id=24, series='F-Zero'),
    _stage('GrOt', 'Onett', 'onett', dual_root=True, internal_id=20, slippi_id=9,
           series='EarthBound'),
    _stage('GrFs', 'Fourside', 'fourside', internal_id=21, slippi_id=18, series='EarthBound'),
    _stage('GrIm', 'Icicle Mountain', 'icicle_mountain', internal_id=22, slippi_id=25,
           series='Ice Climber'),
    _stage('GrI1', 'Mushroom Kingdom', 'mushroom_kingdom', internal_id=24, slippi_id=19,
           series='Mario', project_name='Kingdom'),
    _stage('GrI2', 'Mushroom Kingdom II', 'mushroom_kingdom_ii', internal_id=25, slippi_id=20,
           series='Mario', project_name='Kingdom II'),
    _stage('GrFz', 'Flat Zone', 'flat_zone', internal_id=27, slippi_id=27,
           series='Game & Watch'),
    _stage('GrOy', "Yoshi's Island N64", 'yoshis_island_n64', internal_id=29, slippi_id=29,
           series='Yoshi'),
    _stage('GrOk', 'Kongo Jungle N64', 'kongo_jungle_n64', internal_id=30, slippi_id=30,
           series='Donkey Kong'),
]

STAGES_BY_CODE = {s['code']: s for s in VS_STAGES}
STAGES_BY_FOLDER = {s['folder']: s for s in VS_STAGES}
STAGES_BY_SLIPPI_ID = {s['slippi_id']: s for s in VS_STAGES}

# The DAS blueprint's historical ordering (Battlefield first). Kept as a
# separate tuple because several tables and their tests iterate in this order.
LEGAL_STAGE_CODES = ('GrNBa', 'GrNLa', 'GrSt', 'GrOp', 'GrPs', 'GrIz')
MORE_STAGE_CODES = tuple(s['code'] for s in VS_STAGES if not s['legal'])

# Byte-for-byte the shape das.py / mod_export.py always exposed:
#   {'GrNBa': {'code': 'GrNBa', 'name': 'Battlefield', 'folder': 'battlefield'}, ...}
LEGAL_STAGES = {
    code: {'code': code,
           'name': STAGES_BY_CODE[code]['name'],
           'folder': STAGES_BY_CODE[code]['folder']}
    for code in LEGAL_STAGE_CODES
}

# Same shape for EVERY versus stage (legal six first, in DAS order). This is
# the vault's view: stage skins for all 29 live in storage/das/<folder>/ with
# metadata under stages.<folder>.variants, so the vault page, folders, sort,
# rename, delete, export and duplicate detection are one code path. Only the
# project-side install differs (DAS alt folder vs. replace slot).
ALL_STAGES = dict(LEGAL_STAGES)
ALL_STAGES.update({
    s['code']: {'code': s['code'], 'name': s['name'], 'folder': s['folder']}
    for s in VS_STAGES if not s['legal']
})

# Full-art files for the legal six, extracted from the user's own ISO at first
# run into PROJECT_ROOT/utility/assets/stages (see first_run_setup). The other
# stages only have their SSS icon/banner, copied out of the user's own game
# (shared/vanilla_extract/menu_refs.py, stage_art_path).
VANILLA_ART_FILES = {
    'GrIz': 'fountain of dreams.png',
    'GrPs': 'pokemon stadium.png',
    'GrSt': 'yoshis story.png',
    'GrOp': 'dreamland.png',
    'GrNBa': 'battlefield.png',
    'GrNLa': 'final destination.png',
}


def stage_by_code(code):
    """Registry row for a Gr code, or None. Case-sensitive on purpose: the
    codes are file stems and GrNBa must never match GrNBr."""
    return STAGES_BY_CODE.get(code)


def root_filenames(code):
    """Root stage files the project carries for this stage. Dual-language
    stages (Stadium, Corneria, Venom, Onett) carry both spellings and the
    game picks one from the save's language, so a replacement must touch both."""
    stage = STAGES_BY_CODE[code]
    names = [f'{code}.dat']
    if stage['dual_root']:
        names.append(f'{code}.usd')
    return names


def das_loader_path(code):
    """What Nucleus ships for a stage's DAS loader, or None when it has none:
    an xdelta patch that rebuilds it from the user's own vanilla root
    (projects/install/das_loaders.py), or a plain loader file where one is
    present. Stadium's loader is the English ``.usd`` root; the others are
    ``.dat``."""
    for ext in ('.dat', '.usd'):
        for suffix in ('', '.xdelta'):
            candidate = DAS_LOADER_DIR / f'{code}{ext}{suffix}'
            if candidate.exists():
                return candidate
    return None


def slot_mode(code):
    """'das' for the six loader-backed tournament stages, 'replace' for the
    rest. Legal stages stay 'das' even if the loader file were missing -- the
    DAS blueprint owns those roots and reports the missing loader itself."""
    return 'das' if STAGES_BY_CODE[code]['legal'] else 'replace'


def catalog_entry(code):
    """JSON-ready description of one stage for the viewer."""
    stage = STAGES_BY_CODE[code]
    if stage['legal']:
        # Full stage art extracted from the user's ISO at first run.
        art_url = f"/vanilla/stages/{VANILLA_ART_FILES[code]}"
        icon_url = None
        banner_url = None
    else:
        # The stage-select ICON is the recognisable thumbnail of the stage;
        # the banner is only its text logo. Art = icon. Banner stays
        # available for UIs that want the title treatment as well.
        icon_url = f"/api/mex/stages/{code}/art/icon"
        banner_url = f"/api/mex/stages/{code}/art/banner"
        art_url = icon_url
    return {
        'code': code,
        'name': stage['name'],
        'projectName': stage['project_name'],
        'folder': stage['folder'],
        'series': stage['series'],
        'legal': stage['legal'],
        'dualRoot': stage['dual_root'],
        'mode': slot_mode(code),
        'internalId': stage['internal_id'],
        'slippiId': stage['slippi_id'],
        'rootFiles': root_filenames(code),
        'artUrl': art_url,
        'iconUrl': icon_url,
        'bannerUrl': banner_url,
    }
