"""Work the Skin Lab no longer repeats: unchanged textures are not re-sent on a recolor,
and the session's UV layout is read from the renderer once."""
from tests.backend.test_assistant_skin_lab import session  # noqa: F401  (fixture)
from randall.recolor import skin_lab as lab


def test_a_recolor_sends_only_the_textures_whose_pixels_change(session):
    viewer, _ = session
    analysis = lab.skin_lab('test', 'analyze_palette', max_groups=3, include_materials=False)
    red = next(g['index'] for g in analysis['groups'] if g.get('centerHue') is not None
               and (g['centerHue'] < 20 or g['centerHue'] > 340))
    viewer.updates.clear()
    result = lab.skin_lab('test', 'recolor', adjustments=[{'index': red, 'hue_shift': 120}])
    assert result['updated_textures'] == [0, 1, 2], 'the reply still lists every texture the analysis covers'
    assert viewer.updates == [0], 'only the red texture changed, so only it is uploaded'
    viewer.updates.clear()
    lab.skin_lab('test', 'recolor', adjustments=[{'index': red, 'hue_shift': 120}])
    assert viewer.updates == [], 'the same values again change nothing'
    lab.skin_lab('test', 'reset_palette')
    assert viewer.updates == [0]


def test_the_uv_layout_is_read_once_per_session(session):
    viewer, _ = session
    calls = []
    viewer.get_uv_layout = lambda: calls.append(1) or [
        {'index': 0, 'triangles': [[0, 0, 1, 0, 0, 1, -2, 0, 0, 3, 0, 0, 0, 4, 0]]}]
    lab.skin_lab('test', 'texture_usage')
    lab.skin_lab('test', 'texture_sheet')
    lab.skin_lab('test', 'highlight', texture_indices=[0])
    lab.skin_lab('test', 'texture_usage')
    assert len(calls) == 1


def test_a_costume_recolor_tells_the_view_its_textures_and_material_colours(session):
    """The workbench swaps a whole-costume recolor in place: the textures it uploaded
    and the material colours it set, with the values the session set."""
    from randall.assistant import tools
    viewer, _ = session
    sent = []

    def material_command(command):
        if command['type'] == 'setMaterialColors':
            sent.append(command['edits'])
        return {'success': True, 'materials': [{'id': 'Group 0:2', 'fields': [
            {'key': 'diffuse', 'kind': 'color', 'value': '#c03030ff'}]}]}
    viewer.material_command = material_command
    tools.execute(tools.prepare('skin_lab', {'session_id': 'test', 'action': 'analyze_palette', 'max_groups': 3}))
    result = tools.execute(tools.prepare('skin_lab', {'session_id': 'test', 'action': 'recolor',
                                                      'adjustments': [{'hue_shift': 120}]}))
    update = result['viewer_update']
    assert update['from'] == result['source_file_id'], 'the first edit swaps onto the opened source'
    uploaded = [i for i in result['updated_textures'] if i in viewer.updates]
    assert uploaded and sorted(t['index'] for t in update['textures']) == sorted(uploaded)
    assert update['materials'] == sent[-1] and update['materials'][0]['id'] == 'Group 0:2'
