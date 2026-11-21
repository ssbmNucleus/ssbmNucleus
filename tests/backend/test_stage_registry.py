"""
core/stages.py is the single registry every stage table derives from. These
tests pin (a) the registry's own invariants and (b) that each derived table is
byte-for-byte what the hand-written literals used to be, so the refactor can
never silently rename a vault folder or a project stage name.
"""
from core import stages
from vault.importing.vanilla_stage_specs import VANILLA_STAGE_SPECS
from tests.left_out import left_out


LEGACY_DAS_STAGES = {
    'GrNBa': {'code': 'GrNBa', 'name': 'Battlefield', 'folder': 'battlefield'},
    'GrNLa': {'code': 'GrNLa', 'name': 'Final Destination', 'folder': 'final_destination'},
    'GrSt': {'code': 'GrSt', 'name': "Yoshi's Story", 'folder': 'yoshis_story'},
    'GrOp': {'code': 'GrOp', 'name': 'Dreamland', 'folder': 'dreamland'},
    'GrPs': {'code': 'GrPs', 'name': 'Pokemon Stadium', 'folder': 'pokemon_stadium'},
    'GrIz': {'code': 'GrIz', 'name': 'Fountain of Dreams', 'folder': 'fountain_of_dreams'},
}


def test_registry_covers_every_versus_stage_exactly_once():
    assert len(stages.VS_STAGES) == 29
    for key in ('code', 'folder', 'slippi_id', 'internal_id'):
        values = [s[key] for s in stages.VS_STAGES]
        assert len(set(values)) == len(values), f'duplicate {key}'
    assert set(stages.LEGAL_STAGE_CODES) == {s['code'] for s in stages.VS_STAGES if s['legal']}
    assert len(stages.MORE_STAGE_CODES) == 23
    assert not (set(stages.LEGAL_STAGE_CODES) & set(stages.MORE_STAGE_CODES))


def test_more_stages_match_the_vanilla_stage_specs_table():
    """The ADDED-stage import path (vanilla_stage_specs) and the slot panel
    must agree on which codes are the non-tournament versus stages."""
    spec_codes = {spec['code'] for spec in VANILLA_STAGE_SPECS.values()}
    assert spec_codes == set(stages.MORE_STAGE_CODES)
    for spec in VANILLA_STAGE_SPECS.values():
        row = stages.STAGES_BY_CODE[spec['code']]
        assert row['internal_id'] == spec['vanillaInternalID']
        assert row['dual_root'] == spec['hasLanguageVariants']
        assert row['project_name'] == spec['name']


def test_legal_table_is_the_historical_das_literal():
    assert stages.LEGAL_STAGES == LEGACY_DAS_STAGES
    assert list(stages.LEGAL_STAGES) == list(LEGACY_DAS_STAGES)


def test_derived_tables_match_their_old_literals():
    from projects.install import das
    from projects.routes import mod_export, music_playlists
    from vault.importing import das_scan, stage_detector
    from projects.install import test_build

    assert das.DAS_STAGES == LEGACY_DAS_STAGES
    assert das_scan.LEGAL_STAGES == {
        c: {'name': v['name'], 'folder': v['folder']} for c, v in LEGACY_DAS_STAGES.items()}

    # Vault-side tables cover every versus stage, with the six first and
    # unchanged.
    assert list(stages.ALL_STAGES)[:6] == list(LEGACY_DAS_STAGES)
    assert {c: stages.ALL_STAGES[c] for c in LEGACY_DAS_STAGES} == LEGACY_DAS_STAGES
    assert len(stages.ALL_STAGES) == 29
    assert mod_export.DAS_STAGES == stages.ALL_STAGES
    assert set(stage_detector.STAGE_MAPPING) == set(stages.ALL_STAGES)
    assert {c: stage_detector.STAGE_MAPPING[c] for c in LEGACY_DAS_STAGES} == das_scan.LEGAL_STAGES
    assert test_build.DAS_STAGES == {
        'GrNBa': ('battlefield', 'battlefield'),
        'GrNLa': ('final_destination', 'finaldestination'),
        'GrSt': ('yoshis_story', 'yoshisstory'),
        'GrOp': ('dreamland', 'dreamland'),
        'GrPs': ('pokemon_stadium', 'pokemonstadium'),
        'GrIz': ('fountain_of_dreams', 'fountainofdreams'),
    }
    assert music_playlists.DAS_SONG_STAGES == {
        'GrNBa': ('battlefield', 'Battlefield'),
        'GrNLa': ('final_destination', 'Final Destination'),
        'GrSt': ('yoshis_story', "Yoshi's Story"),
        'GrOp': ('dreamland', 'Dream Land N64'),
        'GrPs': ('pokemon_stadium', 'Pokemon Stadium'),
        'GrIz': ('fountain_of_dreams', 'Fountain of Dreams'),
    }


def test_root_filenames_cover_dual_language_stages():
    assert stages.root_filenames('GrGr') == ['GrGr.dat']
    assert stages.root_filenames('GrCn') == ['GrCn.dat', 'GrCn.usd']
    assert stages.root_filenames('GrPs') == ['GrPs.dat', 'GrPs.usd']


def test_slot_modes():
    for code in stages.LEGAL_STAGE_CODES:
        assert stages.slot_mode(code) == 'das'
    for code in stages.MORE_STAGE_CODES:
        assert stages.slot_mode(code) == 'replace'


@left_out('app/utility/DynamicAlternateStages', why='the DAS loader patches, made from Melee stage files')
def test_bundled_das_loaders_exist_for_exactly_the_legal_six():
    with_loader = {s['code'] for s in stages.VS_STAGES if stages.das_loader_path(s['code'])}
    assert with_loader == set(stages.LEGAL_STAGE_CODES)


def test_catalog_entries_are_json_shaped():
    legal = stages.catalog_entry('GrNBa')
    assert legal['mode'] == 'das'
    assert legal['artUrl'] == '/vanilla/stages/battlefield.png'
    assert legal['iconUrl'] is None
    assert legal['bannerUrl'] is None

    more = stages.catalog_entry('GrCn')
    assert more['mode'] == 'replace'
    assert more['dualRoot'] is True
    assert more['rootFiles'] == ['GrCn.dat', 'GrCn.usd']
    # The stage-select ICON (the stage thumbnail) is the art; the banner is
    # only the text logo and stays a secondary field.
    assert more['artUrl'] == '/api/mex/stages/GrCn/art/icon'
    assert more['iconUrl'] == '/api/mex/stages/GrCn/art/icon'
    assert more['bannerUrl'] == '/api/mex/stages/GrCn/art/banner'
