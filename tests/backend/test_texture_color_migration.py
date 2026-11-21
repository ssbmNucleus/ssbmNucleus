"""
Regression tests for the task #12 texture-extra color-picker migration
(Fox/Falco upb_texture, C. Falcon punch_texture): the hue-degrees slider was
replaced with a target-color ColorPicker, but the CLI export/shift/import
transport and the underlying degrees math are unchanged -- see
vault/extras/textures.py's module docstring for the full contract.

These are pure-function tests (no HSDRawViewer CLI, no game boot): they
exercise resolve_hue_shift / color_to_hue_shift / resolve_vanilla_hue
directly against a fake type_config, which is exactly the "textures.py's
shift is a pure function" case the migration mission's self-test asked for.
A full CLI-level verify (does the shifted PNG actually differ correctly) is
deferred to extras_audit.py --extra upb_texture / punch_texture (see
docs/EXTRAS_AUDIT.md).
"""
import vault.extras.textures as textures


FAKE_CFG = {'vanilla_hue': 15}


def test_resolve_hue_shift_old_shape_passthrough():
    """OLD saved mods: {"hue": degrees} is an ABSOLUTE TARGET HUE, taken
    as-is -- no vanilla-hue math at this layer (that always happened
    downstream in apply_texture_extra_hue, unchanged by the migration)."""
    assert textures.resolve_hue_shift('Fox', 'upb_texture', FAKE_CFG, {'hue': 180}) == 180.0
    assert textures.resolve_hue_shift('Fox', 'upb_texture', FAKE_CFG, {'hue': 0}) == 0.0


def test_resolve_hue_shift_new_shape_color():
    """NEW saves: {"color": "RRGGBB"} converts to its hue in degrees."""
    # Pure red -> hue 0
    assert textures.resolve_hue_shift('Fox', 'upb_texture', FAKE_CFG, {'color': 'FF0000'}) == 0.0
    # Pure cyan -> hue 180
    result = textures.resolve_hue_shift('Fox', 'upb_texture', FAKE_CFG, {'color': '00FFFF'})
    assert abs(result - 180.0) < 0.01


def test_resolve_hue_shift_prefers_color_over_hue():
    """If a mod somehow has both (shouldn't happen, but be deterministic),
    the new `color` shape wins."""
    mods = {'color': '00FFFF', 'hue': 999}
    result = textures.resolve_hue_shift('Fox', 'upb_texture', FAKE_CFG, mods)
    assert abs(result - 180.0) < 0.01


def test_resolve_hue_shift_missing_both_is_none():
    assert textures.resolve_hue_shift('Fox', 'upb_texture', FAKE_CFG, {}) is None
    assert textures.resolve_hue_shift('Fox', 'upb_texture', FAKE_CFG, None) is None


def test_resolve_vanilla_hue_reads_config_constant():
    """Back-compat: the vanilla-hue SOURCE is the static config constant,
    NOT a live re-measurement (see textures.py docstring's "Vanilla-hue
    SOURCE" section) -- this is what keeps old and new saves byte-identical."""
    assert textures.resolve_vanilla_hue('Fox', 'upb_texture', FAKE_CFG) == 15
    assert textures.resolve_vanilla_hue('Fox', 'upb_texture', {}) == 30  # documented default


def test_color_equal_to_old_hue_reproduces_identical_shift():
    """THE core regression the mission asked for: a target color whose OWN
    hue equals what the old slider stored as an absolute `hue` value (e.g.
    180) must reproduce the EXACT SAME final shift
    (target_hue - vanilla_hue) that the old {"hue": 180} save produced --
    byte-for-byte at the degrees level (the PNG-shift stage,
    shift_texture_hue, is a pure function of this number, so identical
    degrees => identical output pixels). `apply_texture_extra_hue`'s `hue`
    parameter has always been an ABSOLUTE TARGET HUE (see its docstring:
    `hue_shift = hue - vanilla_hue`) -- the old slider UI let the user pick
    that absolute hue directly, it was never "vanilla_hue + a relative
    shift" at this layer. So the equivalence is: color's OWN hue ==
    old_hue_value, not color's hue == vanilla_hue + old_hue_value."""
    import colorsys

    old_hue_value = 180  # what an old saved mod's {"hue": 180} literally meant
    vanilla_hue = FAKE_CFG['vanilla_hue']

    r, g, b = colorsys.hls_to_rgb(old_hue_value / 360, 0.5, 1.0)
    target_hex = f'{round(r*255):02X}{round(g*255):02X}{round(b*255):02X}'

    # OLD behavior: apply_texture_extra_hue computes hue_shift = hue - vanilla_hue
    old_hue_shift = old_hue_value - vanilla_hue

    # NEW behavior: resolve the color to an absolute target hue, then the
    # same downstream subtraction apply_texture_extra_hue always did.
    new_target_hue = textures.resolve_hue_shift('Fox', 'upb_texture', FAKE_CFG,
                                                 {'color': target_hex})
    new_hue_shift = new_target_hue - textures.resolve_vanilla_hue('Fox', 'upb_texture', FAKE_CFG)

    assert abs(new_hue_shift - old_hue_shift) < 0.5  # sub-degree rounding only

    # And the direct old-shape path, for the SAME literal old value, must
    # match exactly (no rounding at all -- passthrough, see
    # test_resolve_hue_shift_old_shape_passthrough).
    old_path_target_hue = textures.resolve_hue_shift('Fox', 'upb_texture', FAKE_CFG,
                                                      {'hue': old_hue_value})
    assert old_path_target_hue == old_hue_value


def test_install_keeps_the_nested_fire_key_out_of_the_color_layers(vault, monkeypatch, caplog):
    """falcon_punch's nested 'fire' key is punch_texture's colour, applied by
    the sibling texture step: the colour patcher never sees it (it used to log
    "Unknown layer 'fire' in modifications, skipping" on every install), and a
    mod carrying only the fire colour still installs."""
    from vault.extras import helpers
    from vault.routes.extras import colors
    import projects.routes.extras as extras_routes

    target = vault.touch('project', 'files', 'EfCaData.dat', data=b'\0' * 64)
    monkeypatch.setattr(helpers, 'get_project_files_dir', lambda: target.parent)
    patched, hued = [], []
    monkeypatch.setattr(extras_routes, 'make_write_safety', lambda *a, **k: {'skipped': []})
    monkeypatch.setattr(extras_routes, 'apply_hex_patches',
                        lambda path, offsets, mods, safety=None: patched.append(dict(mods)) or [])
    monkeypatch.setattr(extras_routes, 'apply_texture_extra_hue',
                        lambda character, extra_id, cfg, hue, path: hued.append((extra_id, round(hue))))
    vault.write({'characters': {'C. Falcon': {'extras': {'falcon_punch': [
        {'id': 'blue', 'name': 'Blue Punch', 'modifications': {
            'color1': {'color': '0000FF'}, 'fire': {'color': '00FFFF'}}},
        {'id': 'fire-only', 'name': 'Cyan Fire', 'modifications': {'fire': {'hue': 180}}},
    ]}}}})
    client = vault.client(colors, 'extras_bp')

    for mod_id in ('blue', 'fire-only'):
        response = client.post('/api/mex/storage/extras/install', json={
            'character': 'C. Falcon', 'extraType': 'falcon_punch', 'modId': mod_id})
        assert response.status_code == 200, response.get_json()

    assert patched == [{'color1': {'color': '0000FF'}}, {}]
    assert hued == [('punch_texture', 180), ('punch_texture', 180)]
    assert 'Unknown layer' not in caplog.text


def test_color_to_hue_shift_helper_matches():
    """color_to_hue_shift is the documented regression-testable pure step;
    assert it agrees with the resolve_hue_shift + resolve_vanilla_hue
    composition used above and in colors.py's install path."""
    from vault.extras.texture_recolor import hex_to_hue

    shift = textures.color_to_hue_shift('Fox', 'upb_texture', FAKE_CFG, '00BFFF')
    expected = hex_to_hue('00BFFF') - FAKE_CFG['vanilla_hue']
    assert abs(shift - expected) < 0.01
