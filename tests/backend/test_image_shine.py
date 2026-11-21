"""Tests for image/PNG-based shines (vault/routes/extras/effect_model.py).

Two layers, both on REAL files rather than hand-built stubs:

- the vanilla `EfFxData.dat` from `storage/test-base/files` (the same file
  test_extras_derive.py uses) drives the PNG round-trip, the revert-exactness
  and the "everything else is untouched" guarantees;
- real downloaded image shines drive classification and DAT extraction. Those
  are third-party binaries, so they are NOT committed: point
  `NUCLEUS_IMAGE_SHINE_SAMPLES` at a directory of `EfFxData*.dat` files (the
  default is the scratch dir the 2026-09-09 investigation downloaded them to)
  and the sample tests run; without it they skip, loudly, by name.

The API layer is exercised through the real blueprint with a temp vault and a
temp "project", so import -> install -> read-back -> restore is the same code
path the app runs.
"""
from tests.paths import BACKEND
import io
import os
import shutil
import struct
import sys
from pathlib import Path

import pytest

BACKEND_DIR = BACKEND
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import vault.routes.extras.colors as colors                      # noqa: E402
import vault.extras.helpers as extras_helpers              # noqa: E402
from vault.extras import effect_model as em                # noqa: E402
from core.extra_lookup import get_extra_type  # noqa: E402

VANILLA_EFFX = BACKEND_DIR.parent / 'storage' / 'test-base' / 'files' / 'EfFxData.dat'
SAMPLE_DIR = Path(os.environ.get(
    'NUCLEUS_IMAGE_SHINE_SAMPLES',
    BACKEND_DIR.parents[2] / '.tmp' / 'png-shine-20260909' / 'samples'))

pytestmark = pytest.mark.skipif(
    not VANILLA_EFFX.exists(),
    reason='vanilla EfFxData.dat not present in storage/test-base/files')


@pytest.fixture
def cfg():
    return get_extra_type('Fox', 'shine')


@pytest.fixture
def vanilla():
    return VANILLA_EFFX.read_bytes()


def _png(color=(255, 0, 128, 255), size=(256, 256), checker=False):
    from PIL import Image
    im = Image.new('RGBA', size, color)
    if checker:
        px = im.load()
        for y in range(size[1]):
            for x in range(size[0]):
                if (x // 16 + y // 16) % 2:
                    px[x, y] = (0, 255, 0, 0)
    buf = io.BytesIO()
    im.save(buf, 'PNG')
    return buf.getvalue()


def _texels(png_bytes, cfg):
    return em.rgba_from_image_bytes(png_bytes, em.parse_cfg(cfg))


def _sample_dats():
    if not SAMPLE_DIR.exists():
        return []
    return sorted(p for p in SAMPLE_DIR.rglob('*.dat'))


def _image_samples(cfg):
    """Real downloaded shines whose model 0 is a textured quad."""
    out = []
    for p in _sample_dats():
        try:
            kind, _detail = em.classify_model(p.read_bytes(), cfg)
        except em.EffectModelError:
            continue
        if kind == em.CLASSIFY_IMAGE:
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------

def test_vanilla_shine_is_a_gradient_not_an_image(vanilla, cfg):
    kind, detail = em.classify_model(vanilla, cfg)
    assert kind == em.CLASSIFY_GRADIENT
    assert detail == {'dobjs': 1, 'tobjs': 0, 'jobjs_with_dobj': 1}
    assert em.is_image_model(vanilla, cfg) is False


def test_a_foreign_dat_is_refused_by_root_symbol(cfg, tmp_path):
    """The shine's zips ship PlFx/PlFc fighter files next to EfFxData."""
    fake = tmp_path / 'PlFx.dat'
    body = b'\0' * 0x40
    name = b'ftDataFox\0'
    raw = bytearray()
    raw += struct.pack('>IIIII', 0, len(body), 0, 1, 0) + b'\0' * 12  # 0x20 hdr
    raw += body
    raw += struct.pack('>II', 0, 0)          # root: offset 0, string offset 0
    raw += name
    struct.pack_into('>I', raw, 0, len(raw))
    fake.write_bytes(bytes(raw))
    with pytest.raises(em.EffectModelError, match='not a EfFxData.dat'):
        em.classify_model(fake.read_bytes(), cfg)


# ---------------------------------------------------------------------------
# PNG -> model
# ---------------------------------------------------------------------------

def test_png_install_produces_an_image_model(vanilla, cfg):
    out = em.install_image(vanilla, _texels(_png(), cfg), cfg)

    kind, detail = em.classify_model(out, cfg)
    assert kind == em.CLASSIFY_IMAGE
    assert (detail['width'], detail['height']) == (256, 256)
    assert detail['gx_format'] == 5           # RGB5A3
    # the file still parses as an archive and still has all six models
    dat = em.EffectDat(out)
    assert dat.root_name(0) == 'effFoxDataTable'
    assert len(dat.model_entries(0)) == len(em.EffectDat(vanilla).model_entries(0))


def test_png_pixels_survive_the_round_trip(vanilla, cfg):
    """Install a checkerboard, read it back: RGB5A3 quantizes but does not
    scramble -- opaque stays opaque, transparent stays transparent."""
    png = _png(color=(255, 32, 16, 255), checker=True)
    want = _texels(png, cfg)
    out = em.install_image(vanilla, want, cfg)
    w, h, got = em.read_rgba(em.EffectDat(out), em.parse_cfg(cfg))

    assert (w, h) == (256, 256) and len(got) == len(want)
    for a, b in zip(want, got):
        if a[3] == 0:
            assert b[3] == 0
        else:
            assert b[3] >= 250
            assert max(abs(x - y) for x, y in zip(a[:3], b[:3])) <= 10


def test_uv_orientation_is_not_flipped(vanilla, cfg):
    """The top-left texel must come out top-left: the quad's UVs are
    u=(x+8)/16, v=(8-y)/16, and a mirrored/rotated image is the classic
    hand-built-quad bug."""
    from PIL import Image
    im = Image.new('RGBA', (256, 256), (0, 0, 0, 255))
    px = im.load()
    for y in range(128):
        for x in range(128):
            px[x, y] = (255, 0, 0, 255)          # red top-left quadrant
    buf = io.BytesIO()
    im.save(buf, 'PNG')
    out = em.install_image(vanilla, _texels(buf.getvalue(), cfg), cfg)
    _w, _h, got = em.read_rgba(em.EffectDat(out), em.parse_cfg(cfg))

    assert got[0][0] > 200 and got[0][1] < 40            # (0,0) is red
    assert got[255 * 256 + 255][0] < 40                  # (255,255) is not

    # and the geometry says so too: corner 0 is (+e,-e) with uv (1,1)
    dat = em.EffectDat(out)
    jobj = em.find_display_jobj(dat, em.parse_cfg(cfg))
    pobj = dat.ptr(dat.ptr(jobj + 0x10) + 0x0C)
    attrs = dat.ptr(pobj + 0x08)
    pos_buf = dat.ptr(attrs + 0x14)
    tex_buf = dat.ptr(attrs + 2 * 0x18 + 0x14)
    assert struct.unpack_from('>hhh', dat.data, pos_buf) == (16384, -16384, 0)
    assert struct.unpack_from('>BB', dat.data, tex_buf) == (128, 128)


# ---------------------------------------------------------------------------
# reversibility + not disturbing anything else
# ---------------------------------------------------------------------------

def test_built_model_matches_the_in_game_proven_shape(vanilla, cfg):
    """The three values an in-game bisect proved load-bearing (2026-09-09).

    Each of these, left at its "obvious" value, produced a real failure on
    hardware-accurate emulation: the root pass gate at ROOT_OPA drew nothing
    at all, and the child JObj's vanilla 0.422 scale made the game assert in
    psdisp.c and freeze the frame the shine drew. They are pinned here so a
    later tidy-up cannot quietly reintroduce a freeze that no unit test would
    otherwise notice.
    """
    parsed = em.parse_cfg(cfg)
    out = em.install_image(vanilla, _texels(_png(), cfg), cfg)
    o = em.EffectDat(out)
    jobj = em.find_display_jobj(o, parsed)
    root = o.ptr(o.model_entry(parsed) + 4)

    assert o.u32(root + 0x04) & em.JOBJ_ROOT_TEXEDGE
    assert o.u32(jobj + 0x04) & em.JOBJ_TEXEDGE
    assert struct.unpack_from('>3f', o.data, jobj + 0x20) == (1.0, 1.0, 1.0)
    # and the material/rendermode the same proven mods carry
    dobj = o.ptr(jobj + 0x10)
    mobj = o.ptr(dobj + 0x08)
    assert o.u32(mobj + 0x04) == em.MOBJ_RENDERMODE
    mat = o.ptr(mobj + 0x0C)
    assert o.u32(mat + 0x00) == em.MAT_AMBIENT


def test_revert_restores_the_file_byte_for_byte(vanilla, cfg):
    out = em.install_image(vanilla, _texels(_png(), cfg), cfg)
    assert len(out) > len(vanilla)

    back, changed = em.revert_dat(out, cfg)
    assert changed is True
    assert back == vanilla


def test_revert_is_a_no_op_on_an_untouched_file(vanilla, cfg):
    back, changed = em.revert_dat(vanilla, cfg)
    assert changed is False and back == vanilla


def _strip_header(dat_bytes, cfg):
    """An archive re-save (e.g. the upb fire-texture hue, which runs the
    HSDRawViewer CLI over this same file) drops unreferenced blocks -- our
    revert header among them. This fakes that: same model, no marker."""
    dat = em.EffectDat(dat_bytes)
    off, _hdr = em.find_header(dat)
    assert off is not None
    dat.data[off:off + len(em.MAGIC)] = b'\0' * len(em.MAGIC)
    return dat.to_bytes()


def test_revert_falls_back_to_the_vanilla_reference(vanilla, cfg, monkeypatch,
                                                    tmp_path):
    out = _strip_header(em.install_image(vanilla, _texels(_png(), cfg), cfg), cfg)
    assert em.is_image_model(out, cfg)          # still installed
    assert em.find_header(em.EffectDat(out)) == (None, None)

    ref = tmp_path / 'EfFxData.dat'
    ref.write_bytes(vanilla)
    import shared.vanilla_extract.vanilla_refs as refs
    monkeypatch.setattr(refs, 'ensure_vanilla_ref', lambda name: str(ref))

    back, changed = em.revert_dat(out, cfg)
    assert changed is True
    assert not em.is_image_model(back, cfg)
    # the vanilla model is drawing again, byte-identical in every word that
    # matters (the orphaned append stays behind as dead weight, by design)
    v, b = em.EffectDat(vanilla), em.EffectDat(back)
    jobj = em.find_display_jobj(v, em.parse_cfg(cfg))
    root = v.ptr(v.model_entry(em.parse_cfg(cfg)) + 4)
    assert b.data[jobj:jobj + 0x40] == v.data[jobj:jobj + 0x40]
    assert b.u32(root + 0x04) == v.u32(root + 0x04)


def test_an_unrevertable_image_is_refused_not_guessed(vanilla, cfg, monkeypatch):
    """No marker AND no usable reference: say so instead of leaving the
    picture on screen while reporting success."""
    out = _strip_header(em.install_image(vanilla, _texels(_png(), cfg), cfg), cfg)
    import shared.vanilla_extract.vanilla_refs as refs
    monkeypatch.setattr(refs, 'ensure_vanilla_ref', lambda name: None)
    with pytest.raises(em.EffectModelError, match='cannot take it back out'):
        em.revert_dat(out, cfg)


def test_switching_images_does_not_grow_the_file(vanilla, cfg):
    a = em.install_image(vanilla, _texels(_png((255, 0, 0, 255)), cfg), cfg)
    b = em.install_image(a, _texels(_png((0, 0, 255, 255)), cfg), cfg)
    a2 = em.install_image(b, _texels(_png((255, 0, 0, 255)), cfg), cfg)

    assert len(a) == len(b) == len(a2)
    assert a2 == a          # A -> B -> A is byte-identical to A


def test_install_leaves_every_other_effect_alone(vanilla, cfg):
    """Only the shine JObj's own words may change: its dobj pointer, its
    render-pass flags and its (animation-overridden) static scale, plus the
    model root's ROOT_* pass gate. The gradient bytes, the sparkle records
    and models 1-5 must be untouched."""
    parsed = em.parse_cfg(cfg)
    v = em.EffectDat(vanilla)
    jobj = em.find_display_jobj(v, parsed)
    root = v.ptr(v.model_entry(parsed) + 4)

    out = em.install_image(vanilla, _texels(_png(), cfg), cfg)
    o = em.EffectDat(out)

    changed = [i for i in range(0, v.data_size, 4)
               if v.data[i:i + 4] != o.data[i:i + 4]]
    assert changed == sorted([jobj + 0x04, jobj + 0x10, root + 0x04,
                              jobj + 0x20, jobj + 0x24, jobj + 0x28])
    # the child moves OPA -> TEXEDGE and the root ROOT_OPA -> ROOT_TEXEDGE;
    # without the second one HSD_JObjDisp never descends and nothing draws
    assert v.u32(jobj + 0x04) & em.JOBJ_OPA
    assert o.u32(jobj + 0x04) & em.JOBJ_TEXEDGE
    assert v.u32(root + 0x04) & em.JOBJ_ROOT_OPA
    assert o.u32(root + 0x04) & em.JOBJ_ROOT_TEXEDGE
    assert not o.u32(root + 0x04) & em.JOBJ_ROOT_OPA

    # the gradient's own region (config offsets are FILE offsets)
    hexr = cfg['offsets']['hex']
    assert vanilla[hexr['start']:hexr['end']] == out[hexr['start']:hexr['end']]
    # and the other five effect models still point where they did
    assert (v.model_entries(0)[1:] == o.model_entries(0)[1:])
    for entry in v.model_entries(0)[1:]:
        assert v.data[entry:entry + 0x14] == o.data[entry:entry + 0x14]


def test_gradient_colors_survive_an_image_install_and_revert(vanilla, cfg, tmp_path):
    """A custom gradient underneath an image shine comes back on revert."""
    from vault.extras.color_patch import patch_matrix_colors
    from vault.extras.color_read import read_shine_gradient_colors
    p = tmp_path / 'EfFxData.dat'
    p.write_bytes(vanilla)
    hexr = cfg['offsets']['hex']
    with open(p, 'r+b') as f:
        f.seek(hexr['start'])
        data = f.read(hexr['end'] - hexr['start'])
        f.seek(hexr['start'])
        f.write(patch_matrix_colors(data, color_format='RGBY',
                                    color_map={'621F': '0FF0', 'AB9F': '0A45'}))
    greened = p.read_bytes()
    assert read_shine_gradient_colors(p, hexr)['primary'] == '0FF0'

    out = em.install_image(greened, _texels(_png(), cfg), cfg)
    back, changed = em.revert_dat(out, cfg)
    assert changed is True and back == greened


# ---------------------------------------------------------------------------
# real downloaded image shines
# ---------------------------------------------------------------------------

needs_samples = pytest.mark.skipif(
    not _sample_dats(),
    reason=f'no sample shine DATs under {SAMPLE_DIR} '
           '(set NUCLEUS_IMAGE_SHINE_SAMPLES)')


@needs_samples
def test_real_samples_split_into_the_three_kinds(cfg):
    """Every parseable EfFxData sample must land in exactly one bucket, and
    the image bucket must not be empty (that is the feature's whole point)."""
    kinds = {}
    for p in _sample_dats():
        try:
            kind, _ = em.classify_model(p.read_bytes(), cfg)
        except em.EffectModelError:
            continue        # not an EfFxData (fighter files, model fragments)
        kinds.setdefault(kind, []).append(p.name)
    assert set(kinds) <= {em.CLASSIFY_GRADIENT, em.CLASSIFY_IMAGE,
                          em.CLASSIFY_MODEL}
    assert kinds.get(em.CLASSIFY_IMAGE), 'no image shines among the samples'


@needs_samples
def test_real_samples_rebuild_onto_vanilla_and_revert(vanilla, cfg):
    """The end-to-end import shape: read a downloaded shine's picture, build
    it onto our own vanilla file, read it back, and revert to the byte."""
    samples = _image_samples(cfg)
    assert samples
    parsed = em.parse_cfg(cfg)
    for p in samples:
        src = em.EffectDat(p.read_bytes())
        sw, sh, spx = em.read_rgba(src, parsed)
        px = spx
        if (sw, sh) != (parsed['width'], parsed['height']):
            from PIL import Image
            im = Image.new('RGBA', (sw, sh))
            im.putdata(spx)
            px = list(im.resize((parsed['width'], parsed['height'])).getdata())

        out = em.install_image(vanilla, px, cfg)
        kind, detail = em.classify_model(out, cfg)
        assert kind == em.CLASSIFY_IMAGE, p.name
        assert (detail['width'], detail['height']) == (256, 256), p.name
        back, changed = em.revert_dat(out, cfg)
        assert changed and back == vanilla, p.name


@needs_samples
def test_a_real_sample_installs_through_the_mod_source_path(vanilla, cfg, tmp_path):
    """A stored `model_file` .dat (what the website import writes) installs
    without ever converting to PNG first."""
    sample = _image_samples(cfg)[0]
    storage = tmp_path / 'Fox'
    (storage / 'models').mkdir(parents=True)
    shutil.copy2(sample, storage / 'models' / 'shine_x.dat')
    project = tmp_path / 'EfFxData.dat'
    project.write_bytes(vanilla)

    em.install_mod(project, storage,
                   {'id': 'shine_x', 'model_file': 'models/shine_x.dat'}, cfg)

    assert em.is_image_model(project.read_bytes(), cfg)
    png = em.png_from_mod(storage, {'model_file': 'models/shine_x.dat'}, cfg)
    assert png[:8] == b'\x89PNG\r\n\x1a\n'


@needs_samples
def test_geometry_shines_are_refused_by_name(cfg):
    """Honeycomb / Stop Sign / Triforce replace the MESH, not the texture.
    Importing one must say so rather than install something wrong."""
    geometry = []
    for p in _sample_dats():
        try:
            kind, _ = em.classify_model(p.read_bytes(), cfg)
        except em.EffectModelError:
            continue
        if kind == em.CLASSIFY_MODEL:
            geometry.append(p)
    if not geometry:
        pytest.skip('no geometry-replacement shines among the samples')
    with pytest.raises(em.EffectModelError, match='replaces the effect GEOMETRY'):
        em.texels_from_upload(geometry[0].read_bytes(), '.dat', cfg)


@needs_samples
def test_derive_marks_a_real_image_shine_instead_of_failing(cfg):
    """The reported gap: derive_modifications_from_dat used to return {} for a
    rebuilt image shine, so install answered 422 'no color data'."""
    sample = _image_samples(cfg)[0]
    mods = extras_helpers.derive_modifications_from_dat(sample, 'shine', cfg)
    assert 'image' in mods
    assert mods['image']['width'] == 256
    assert em.is_image_mod({'modifications': mods}) is True


# ---------------------------------------------------------------------------
# the API: import -> install -> read back -> restore
# ---------------------------------------------------------------------------

@pytest.fixture
def api(vault, monkeypatch, vanilla):
    """The extras blueprint against a temp vault and a temp MEX project."""
    import vault.importing.unified.effects as unified_effects
    files_dir = vault.project_root / 'files'
    files_dir.mkdir(parents=True, exist_ok=True)
    (files_dir / 'EfFxData.dat').write_bytes(vanilla)
    vault.touch('test-base', 'files', 'EfFxData.dat', data=vanilla)
    from shared.vanilla_extract import vanilla_refs
    monkeypatch.setattr(vanilla_refs, 'STORAGE_PATH', vault.storage)
    monkeypatch.setattr(extras_helpers, 'STORAGE_PATH', vault.storage)
    monkeypatch.setattr(extras_helpers, 'get_project_files_dir',
                        lambda: files_dir)
    # A .dat upload is routed through the website effect-import path, which
    # binds STORAGE_PATH from core.config at import time rather than reading
    # extras.helpers.STORAGE_PATH -- so it needs its own redirect or the test
    # writes mod files into the developer's real vault.
    monkeypatch.setattr(unified_effects, 'STORAGE_PATH', vault.storage)
    vault.write({'characters': {}})
    client = vault.client(colors, 'extras_bp')
    client.files_dir = files_dir
    client.project_dat = files_dir / 'EfFxData.dat'
    return client


def _import_png(client, data=None, name='Test Image Shine'):
    return client.post('/api/mex/storage/extras/import', data={
        'file': (io.BytesIO(data or _png()), 'shiny.png'),
        'character': 'Falco',            # shared extra -> stored under Fox
        'extraType': 'shine',
        'name': name,
    }, content_type='multipart/form-data')


def test_api_import_png_creates_an_image_mod(api, vault):
    r = _import_png(api)
    assert r.status_code == 200, r.get_json()
    mod = r.get_json()['mod']
    assert mod['format'] == 'effect_model'
    assert mod['modifications']['image']['width'] == 256

    stored = vault.read()['characters']['Fox']['extras']['shine']
    assert [m['id'] for m in stored] == [mod['id']]
    assert (vault.storage / 'Fox' / mod['image_file']).exists()
    assert (vault.storage / 'Fox' / mod['screenshot']).exists()


def test_api_install_then_restore_round_trip(api, vault, vanilla, cfg):
    mod = _import_png(api).get_json()['mod']

    r = api.post('/api/mex/storage/extras/install', json={
        'character': 'Falco', 'extraType': 'shine', 'modId': mod['id']})
    assert r.status_code == 200 and r.get_json()['success'] is True
    assert em.is_image_model(api.project_dat.read_bytes(), cfg)

    # get-current reports the image rather than garbage colors
    r = api.get('/api/mex/storage/extras/current/Falco/shine')
    body = r.get_json()
    assert r.status_code == 200, body
    assert body['imageInstalled'] is True and body['isVanilla'] is False
    assert body['colors'] == {}

    # the PNG endpoint serves what is installed, and the stored mod
    r = api.get('/api/mex/storage/extras/effect-image/Falco/shine')
    assert r.status_code == 200 and r.data[:8] == b'\x89PNG\r\n\x1a\n'
    r = api.get(f'/api/mex/storage/extras/effect-image/Falco/shine?mod={mod["id"]}')
    assert r.status_code == 200 and r.data[:8] == b'\x89PNG\r\n\x1a\n'

    r = api.post('/api/mex/storage/extras/restore-vanilla', json={
        'character': 'Falco', 'extraType': 'shine'})
    assert r.status_code == 200 and r.get_json()['success'] is True
    # Restore includes the image model and the original per-record colors.
    assert not em.is_image_model(api.project_dat.read_bytes(), cfg)
    assert api.project_dat.read_bytes() == vanilla
    r = api.get('/api/mex/storage/extras/current/Falco/shine')
    assert r.get_json().get('imageInstalled') is not True


def test_api_installing_colors_removes_an_installed_image(api, vault, cfg):
    """The switch-back case: a gradient mod must actually reach the screen,
    which means the image model has to come out first."""
    image_mod = _import_png(api).get_json()['mod']
    api.post('/api/mex/storage/extras/install', json={
        'character': 'Falco', 'extraType': 'shine', 'modId': image_mod['id']})
    assert em.is_image_model(api.project_dat.read_bytes(), cfg)

    r = api.post('/api/mex/storage/extras/create', json={
        'character': 'Falco', 'extraType': 'shine', 'name': 'Green',
        'modifications': {'primary': {'color': '0FF0'},
                          'secondary': {'color': '0A45'}}})
    color_mod = r.get_json()['mod']
    r = api.post('/api/mex/storage/extras/install', json={
        'character': 'Falco', 'extraType': 'shine', 'modId': color_mod['id']})
    assert r.status_code == 200, r.get_json()

    assert not em.is_image_model(api.project_dat.read_bytes(), cfg)
    from vault.extras.color_read import read_shine_gradient_colors
    got = read_shine_gradient_colors(api.project_dat, cfg['offsets']['hex'])
    assert got['primary'] == '0FF0' and got['secondary'] == '0A45'


def test_a_gradient_dat_never_becomes_an_image_mod(cfg, vanilla):
    """Handing a color-format DAT to the image builder is a real user mistake
    (both tabs of the shine editor accept .dat), and it must be named rather
    than installed as a blank picture."""
    with pytest.raises(em.EffectModelError, match='color/gradient effect'):
        em.texels_from_upload(vanilla, '.dat', cfg)


def test_api_importing_a_gradient_dat_yields_a_color_mod(api, vanilla):
    """A .dat upload is classified by CONTENT, not by which tab sent it: a
    gradient file becomes a color mod, not an image mod."""
    r = api.post('/api/mex/storage/extras/import', data={
        'file': (io.BytesIO(vanilla), 'EfFxData.dat'),
        'character': 'Fox', 'extraType': 'shine', 'name': 'vanilla-ish',
    }, content_type='multipart/form-data')
    assert r.status_code == 200, r.get_json()
    mod = r.get_json()['mod']
    assert em.is_image_mod(mod) is False
    assert mod['modifications']['primary']['color'] == '621F'


@needs_samples
def test_api_import_a_real_downloaded_shine_dat(api, vault, cfg):
    sample = _image_samples(cfg)[0]
    r = api.post('/api/mex/storage/extras/import', data={
        'file': (io.BytesIO(sample.read_bytes()), sample.name),
        'character': 'Fox', 'extraType': 'shine', 'name': sample.stem,
    }, content_type='multipart/form-data')
    assert r.status_code == 200, r.get_json()
    mod = r.get_json()['mod']
    assert mod['modifications']['image']['imported_from'] == 'dat'

    r = api.post('/api/mex/storage/extras/install', json={
        'character': 'Fox', 'extraType': 'shine', 'modId': mod['id']})
    assert r.status_code == 200, r.get_json()
    assert em.is_image_model(api.project_dat.read_bytes(), cfg)
