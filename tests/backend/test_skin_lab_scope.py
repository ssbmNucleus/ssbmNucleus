"""The part scope says what an edit reaches; it never refuses one or asks the user.

A measured Goku Fox turn read "one shared palette texture covering the whole
body", concluded "I can isolate just the orange fur by colour", recoloured, and
only then discovered the gi had gone with it. Colour groups are not body parts.
The part-map adapter knows which parts read the same pixels, so every edit's
result names what it reached beyond its part (`also_changed`, and
`unmapped_textures` for a costume no part map covers, a model import among them):
the model reads that and the render, and separates it or says so. The old stop
that refused until the user's answer was recorded is gone.
"""
from tests.paths import BACKEND
import io
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

BACKEND_DIR = BACKEND
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from randall.recolor import skin_lab as lab                            # noqa: E402
from shared.rendering import part_identity                                # noqa: E402

VANILLA = BACKEND_DIR.parent / 'utility' / 'assets' / 'vanilla'
VANILLA_FOX = VANILLA / 'Fox' / 'PlFxNr' / 'PlFxNr.dat'
VANILLA_MARIO = VANILLA / 'Mario' / 'PlMrBk' / 'PlMrBk.dat'

needs_fox = pytest.mark.skipif(not VANILLA_FOX.is_file(), reason='no vanilla Fox costume here')
needs_mario = pytest.mark.skipif(not VANILLA_MARIO.is_file(), reason='no vanilla Mario costume here')


class FakeViewer:
    """A renderer that serves the costume's own decoded pixels and records writes.

    Real enough for the gate: the scope is computed from the DAT plus this list,
    which is exactly what a live session provides.
    """

    def __init__(self, mapping):
        self.textures, self.pixels = [], {}
        import numpy as np
        for record in sorted((r for r in mapping['textures'] if r['viewer_index'] is not None),
                             key=lambda r: r['viewer_index']):
            pixels = part_identity.decoded_pixels(record)
            if pixels is None:            # a format datprobe cannot decode yet
                pixels = np.zeros((record['height'], record['width'], 4), dtype=np.uint8)
            buffer = io.BytesIO()
            Image.fromarray(pixels, 'RGBA').save(buffer, format='PNG')
            self.textures.append({'index': record['viewer_index'], 'width': record['width'],
                                  'height': record['height'],
                                  'matAnim': record['kind'] == 'matanim', 'animates': -1})
            self.pixels[record['viewer_index']] = buffer.getvalue()
        self.camera = {'rotX': 0, 'rotY': 0, 'scale': 1, 'x': 0, 'y': 0}
        self.updates = []
        self.closed = False

    def material_command(self, command):
        return {'materials': []}

    def get_uv_layout(self):
        return []

    def get_full_texture(self, index):
        return self.pixels[index]

    def update_texture(self, index, value):
        self.pixels[index] = value
        self.updates.append(index)

    def grab_frame(self, *args, **kwargs):
        return next(iter(self.pixels.values()))

    def export_dat(self):
        return b'\x00' * 64

    def close(self):
        self.closed = True

    def alive(self):
        return not self.closed


@pytest.fixture
def open_session():
    """Install a session whose scope comes from a REAL costume, no renderer."""
    made = []

    def build(dat_path, origin):
        import hashlib
        mapping = part_identity.build_map(dat_path, origin)
        viewer = FakeViewer(mapping)
        part_identity.label_parts(mapping)
        report = part_identity.describe(mapping)
        session_id = f'scope-{len(made)}'
        item = {'viewer': viewer, 'scratch': SimpleNamespace(cleanup=lambda: None),
                'used': time.monotonic(), 'palette': None, 'edited': False,
                'hidden_textures': None, 'scope': report,
                'scope_index': lab._scope_index(report),
                'source_sha256': hashlib.sha256(Path(dat_path).read_bytes()).hexdigest(),
                'source': {'name': Path(dat_path).name, 'origin': origin}}
        lab._sessions[session_id] = item
        made.append(session_id)
        return session_id, item, viewer, report

    yield build
    for session_id in made:
        lab._sessions.pop(session_id, None)


def _part_textures(report, name):
    return report['parts'][name]['viewer_indices']


# --------------------------------------------------------------------------- #
# every edit is made; its result says what else it reached                    #
# --------------------------------------------------------------------------- #
@needs_mario
def test_a_shared_part_is_edited_and_the_result_names_the_co_owner(open_session):
    session_id, item, viewer, report = open_session(
        VANILLA_MARIO, {'character': 'Mario', 'costume_code': 'PlMrBk'})
    targets = _part_textures(report, 'cap')
    assert report['parts']['cap']['scope'] == 'shared'

    lab.skin_lab(session_id, 'analyze_palette', texture_indices=targets, max_groups=4,
                 include_materials=False)
    result = lab.skin_lab(session_id, 'recolor', adjustments=[{'index': 0, 'hue_shift': 120}])
    assert result['updated_textures'] and item['edited'] is True and viewer.updates
    assert any("'cap' and 'cap emblem' (same pixels" in line for line in result['also_changed'])
    assert 'analyze_palette parts' in result['note'] and 'choose_scope' not in result['note']


def test_a_costume_no_part_map_covers_is_edited_and_its_textures_named_unmapped(tmp_path, open_session):
    """A model import (or a restructured mod): no vanilla part map fits, and nothing is refused."""
    from tests.backend.test_part_identity import write_unmapped_port
    port = write_unmapped_port(tmp_path / 'PlFxNrMod.dat')
    session_id, item, viewer, report = open_session(
        port, {'character': 'Fox', 'costume_code': 'PlFxNr'})
    assert report['parts'] == {}, 'no vanilla part map fits this port'

    before = dict(viewer.pixels)
    lab.skin_lab(session_id, 'analyze_palette', texture_indices=[0], max_groups=4,
                 include_materials=False)
    result = lab.skin_lab(session_id, 'recolor', adjustments=[{'index': 0, 'hue_shift': 180}])
    assert item['edited'] is True and viewer.pixels[0] != before[0]
    assert result['unmapped_textures'] == [0] and 'identify' in result['note']


@needs_mario
def test_the_supported_colour_mask_leaves_nothing_to_report(open_session):
    """analyze_palette with parts clusters each named part on its own: its co-owners do not change."""
    session_id, item, viewer, report = open_session(
        VANILLA_MARIO, {'character': 'Mario', 'costume_code': 'PlMrBk'})
    assert report['parts']['cap']['required_mask']['kind'] == 'color'
    lab.skin_lab(session_id, 'analyze_palette',
                 parts={'cap': _part_textures(report, 'cap')}, max_groups=4)
    assert item['palette']['mask'] == 'color' and item['palette']['part_names'] == ['cap']
    result = lab.skin_lab(session_id, 'recolor', adjustments=[{'index': 0, 'hue_shift': 90}])
    assert result['updated_textures'] and item['edited'] is True and 'also_changed' not in result


@needs_fox
def test_an_exclusive_part_reports_nothing_beyond_itself(open_session):
    session_id, item, viewer, report = open_session(
        VANILLA_FOX, {'character': 'Fox', 'costume_code': 'PlFxNr'})
    assert report['parts']['fur']['scope'] == 'exclusive'
    targets = _part_textures(report, 'fur')
    lab.skin_lab(session_id, 'analyze_palette', texture_indices=targets, max_groups=4,
                 include_materials=False)
    result = lab.skin_lab(session_id, 'recolor', adjustments=[{'index': 0, 'hue_shift': 120}])
    assert set(result['updated_textures']) == set(targets) and item['edited'] is True
    assert 'also_changed' not in result and 'unmapped_textures' not in result


@needs_mario
def test_skin_material_apply_on_a_shared_texture_is_made_and_reported(open_session):
    """A mask drawn over a shared texture still writes the whole texture: the apply says so."""
    from randall.recolor import texture_material
    session_id, item, viewer, report = open_session(
        VANILLA_MARIO, {'character': 'Mario', 'costume_code': 'PlMrBk'})
    cap = _part_textures(report, 'cap')
    reached = lab.reach(item, cap)
    assert any("'cap emblem'" in line for line in reached['also_changed'])
    # The apply path asks reach() and refuses nothing (texture_material.skin_material).
    import inspect
    source = inspect.getsource(texture_material.skin_material)
    assert 'lab.reach(item, list(values))' in source and 'require_scope' not in source


def test_no_code_path_refuses_or_asks_any_more():
    import inspect
    from randall.recolor import costume_colours, texture_material
    for module in (lab, costume_colours, texture_material):
        source = inspect.getsource(module)
        assert 'Refusing this' not in source and 'choose_scope' not in source and 'require_scope' not in source
    from randall.assistant import recipes, tools
    skin = next(s for s in tools.SCHEMAS if s['function']['name'] == 'skin_lab')['function']
    assert 'choose_scope' not in skin['parameters']['properties']['action']['enum']
    assert 'choose_scope' not in skin['description'] and 'ASK the user' not in skin['description']
    assert 'choose_scope' not in recipes.CARDS['recolor_part'] and 'REFUSED' not in recipes.CARDS['recolor_part']


# --------------------------------------------------------------------------- #
# what the model is told at open                                              #
# --------------------------------------------------------------------------- #
@needs_mario
def test_open_reports_the_verdict_per_part_in_live_indices(open_session):
    session_id, item, viewer, report = open_session(
        VANILLA_MARIO, {'character': 'Mario', 'costume_code': 'PlMrBk'})
    summary = lab._scope_summary(item['scope'], item['scope_index'])
    assert summary['mapped'] is True
    assert summary['parts']['cap']['scope'] == 'shared'
    assert summary['parts']['cap']['co_owned_with'] == ['cap emblem']
    assert summary['parts']['cap']['required_mask']['kind'] == 'color'
    assert summary['parts']['shirt']['scope'] == 'exclusive'
    assert summary['unresolved_texture_indices'] == []
    assert 'REFUSE' not in summary['note'] and 'also_changed' in summary['note']


def test_an_unscoped_session_reports_nothing():
    """No part map could be built: edits run, and reach has nothing to add."""
    assert lab.reach({'scope_index': {}, 'palette': None}, [0, 1, 2]) == {}
    assert lab._scope_summary(None, {})['mapped'] is False


def test_a_chat_that_recorded_an_old_scope_choice_still_loads():
    """Stored chats keep receipts of the removed choose_scope action: they are read like any other."""
    from randall.assistant import compaction, continuity
    old = {'name': 'skin_lab', 'status': 'done',
           'arguments': {'session_id': 'f' * 32, 'action': 'choose_scope', 'texture_indices': [0], 'value': 'yes'},
           'result': {'scope_receipt': 'abc', 'version': 'skin-lab-scope/1', 'texture_indices': [0],
                      'note': 'Recorded for this source only.'}}
    state = continuity.working_context([old])
    assert [s['session_id'] for s in state['skin_sessions']] == ['f' * 32]
    assert compaction.compact_result(old['result'])['scope_receipt'] == 'abc'
