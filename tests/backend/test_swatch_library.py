"""A generated swatch is kept by theme, so a repeat theme needs no new image."""
import io

from PIL import Image

from shared import mod_files
from randall.recolor import swatch_library, workflows


def png():
    out = io.BytesIO()
    Image.new('RGB', (8, 8), 'orange').save(out, 'PNG')
    return out.getvalue()


def made(prompt):
    return {'prompt': prompt, 'file_id': mod_files.register(png(), 'Generated material.png')['file_id']}


def test_themes_are_canonical_and_ignore_the_ice_climbers():
    assert swatch_library.surface_themes('molten magma with lava cracks') == ['lava']
    assert swatch_library.surface_themes('recolor ice climbers blue') == []
    assert swatch_library.surface_themes('icy frozen crystals') == ['ice', 'crystal']
    assert swatch_library.surface_themes('make mario gold') == []


def test_a_swatch_is_found_again_by_its_theme_or_a_synonym(vault):
    lava, camo = made('Glowing molten lava with black crust'), made('Woodland camo pattern')
    swatch_library.record([lava, camo, made('plain white cloth')])
    assert swatch_library.find(['lava']) == [lava]
    assert swatch_library.find(swatch_library.surface_themes('a magma skin')) == [lava]
    assert swatch_library.find(['camo', 'lava']) == [lava, camo][::-1][::-1] or \
        swatch_library.find(['camo', 'lava']) == [camo, lava]
    assert swatch_library.find(['galaxy']) == []


def test_newest_first_capped_and_missing_files_skipped(vault, monkeypatch):
    monkeypatch.setattr(swatch_library, 'OFFER', 2)
    old, gone, new = made('lava one'), made('lava two'), made('lava three')
    swatch_library.record([old, gone, new])
    (mod_files.root() / gone['file_id'] / 'metadata.json').unlink()
    assert swatch_library.find(['lava']) == [new, old]


def test_the_workflow_offers_saved_swatches_for_the_theme(vault):
    lava = made('Glowing lava')
    swatch_library.record([lava])
    flow = workflows.Workflow('make a lava bowser skin', {}, main_model='main', recolor=True)
    flow._main('evidence_ready')
    seen = []
    list(flow.stream([{'role': 'user', 'content': 'make a lava bowser skin'}], [{}], 'k',
                     __import__('threading').Event(),
                     lambda history, *a: seen.append(history) or iter([{'type': 'completion', 'message': {}}])))
    note = seen[0][-1]['content']
    assert lava['file_id'] in note and 'instead of generating' in note
