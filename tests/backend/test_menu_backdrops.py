"""
The CSS and SSS layout editors' backdrops are rendered from the user's own
game (shared/vanilla_extract/menu_backdrops.py), not shipped: the old
css_template.png / sss_template.png screenshots are gone (ship rule
retail-menu-backdrops).

Fast tests pin the cache and the fallback with a stand-in renderer: one render
per source, a new render when the source or RENDER_VERSION changes, None (and
so a plain editor background) when there is no game, no renderer or a failed
render, and no retry of a failed render. The slow test renders both screens
with the real HSDRawViewer from the vanilla files in storage/test-base.
"""
import json
from pathlib import Path

import pytest
from flask import Flask

from tests.paths import APP
from shared.vanilla_extract import menu_backdrops, vanilla_refs

PNG = b'\x89PNG\r\n\x1a\n'


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A private backdrop cache, fresh failure memo, and vanilla sources that
    exist only when a test writes them."""
    monkeypatch.setattr(menu_backdrops, 'BACKDROP_DIR', tmp_path / 'menu_backdrops')
    monkeypatch.setattr(menu_backdrops, '_failed', set())
    monkeypatch.setattr(menu_backdrops, '_sha_memo', {})
    sources = tmp_path / 'test-base' / 'files'
    sources.mkdir(parents=True)

    def ensure(name, storage_path=None):
        path = sources / name
        return path if path.is_file() else None
    monkeypatch.setattr(vanilla_refs, 'ensure_vanilla_ref', ensure)
    return sources


@pytest.fixture
def renderer(tmp_path, monkeypatch):
    """A stand-in HSDRawViewer: records each argv and writes a PNG unless told
    to fail."""
    exe = tmp_path / 'hsdraw' / 'HSDRawViewer.exe'
    exe.parent.mkdir()
    exe.write_bytes(b'stand-in')
    monkeypatch.setattr(menu_backdrops, 'HSDRAW_EXE', exe)
    calls = []
    state = {'fail': False}

    class Done:
        def __init__(self, code):
            self.returncode, self.stdout, self.stderr = code, '', 'boom' if code else ''

    def run(argv, **kwargs):
        calls.append(list(argv))
        if state['fail']:
            return Done(1)
        Path(argv[3]).write_bytes(PNG + f'{Path(argv[2]).name} #{len(calls)}'.encode())
        return Done(0)
    monkeypatch.setattr(menu_backdrops.subprocess, 'run', run)
    return calls, state


def test_renders_once_per_source_and_caches(home, renderer):
    calls, _ = renderer
    (home / 'MnSlChr.usd').write_bytes(b'vanilla css scene')

    first = menu_backdrops.backdrop_path('css')
    assert first == menu_backdrops.BACKDROP_DIR / 'css.png'
    assert first.read_bytes().startswith(PNG)
    # The mode flag comes first, so the viewer's window can never open.
    assert calls[0][1:3] == ['--menu-render', str(home / 'MnSlChr.usd')]
    stamp = json.loads((menu_backdrops.BACKDROP_DIR / 'css.json').read_text(encoding='utf-8'))
    assert stamp['render_version'] == menu_backdrops.RENDER_VERSION

    assert menu_backdrops.backdrop_path('css') == first
    assert len(calls) == 1, 'a cached backdrop was rendered again'


def test_a_new_source_or_renderer_renders_again(home, renderer, monkeypatch):
    calls, _ = renderer
    source = home / 'MnSlMap.usd'
    source.write_bytes(b'vanilla sss scene')
    menu_backdrops.backdrop_path('sss')

    source.write_bytes(b'another game')
    menu_backdrops.backdrop_path('sss')
    assert len(calls) == 2

    monkeypatch.setattr(menu_backdrops, 'RENDER_VERSION', menu_backdrops.RENDER_VERSION + 1)
    menu_backdrops.backdrop_path('sss')
    assert len(calls) == 3
    assert menu_backdrops.backdrop_path('sss', render=False) is not None


def test_no_game_means_no_backdrop_and_no_render(home, renderer):
    calls, _ = renderer
    assert menu_backdrops.backdrop_path('css') is None
    assert menu_backdrops.backdrop_path('sss') is None
    assert menu_backdrops.backdrop_path('title') is None
    assert calls == []


def test_missing_renderer_gives_none(home, renderer, monkeypatch, tmp_path):
    calls, _ = renderer
    (home / 'MnSlChr.usd').write_bytes(b'vanilla css scene')
    monkeypatch.setattr(menu_backdrops, 'HSDRAW_EXE', tmp_path / 'nowhere' / 'HSDRawViewer.exe')
    assert menu_backdrops.backdrop_path('css') is None
    assert calls == []


def test_a_failed_render_is_not_retried_for_the_same_source(home, renderer):
    calls, state = renderer
    source = home / 'MnSlChr.usd'
    source.write_bytes(b'vanilla css scene')
    state['fail'] = True
    assert menu_backdrops.backdrop_path('css') is None
    assert menu_backdrops.backdrop_path('css') is None
    assert len(calls) == 1
    assert not (menu_backdrops.BACKDROP_DIR / 'css.png').exists()

    # Another source is worth a try.
    state['fail'] = False
    source.write_bytes(b'another game')
    assert menu_backdrops.backdrop_path('css') is not None
    assert len(calls) == 2


def test_a_render_that_writes_no_png_counts_as_failed(home, renderer, monkeypatch):
    (home / 'MnSlMap.usd').write_bytes(b'vanilla sss scene')

    class Done:
        returncode, stdout, stderr = 0, 'SUCCESS', ''
    monkeypatch.setattr(menu_backdrops.subprocess, 'run', lambda argv, **kw: Done())
    assert menu_backdrops.backdrop_path('sss') is None


def test_never_raises(home, monkeypatch):
    def broken(name, storage_path=None):
        raise OSError('disc unreadable')
    monkeypatch.setattr(vanilla_refs, 'ensure_vanilla_ref', broken)
    assert menu_backdrops.backdrop_path('css') is None


def test_routes_serve_the_backdrop_or_404(home, monkeypatch, tmp_path):
    from vault.routes.menus import menus_bp
    app = Flask(__name__)
    app.register_blueprint(menus_bp)
    client = app.test_client()

    png = tmp_path / 'css.png'
    png.write_bytes(PNG + b'backdrop')
    monkeypatch.setattr(menu_backdrops, 'backdrop_path',
                        lambda screen, render=True: png if screen == 'css' else None)
    ok = client.get('/api/mex/menus/css/backdrop')
    assert ok.status_code == 200 and ok.data == PNG + b'backdrop'
    assert ok.mimetype == 'image/png'
    assert client.get('/api/mex/menus/sss/backdrop').status_code == 404


def test_the_screenshots_are_gone():
    public = APP / 'frontend' / 'public'
    assert not (public / 'css_template.png').exists()
    assert not (public / 'sss_template.png').exists()


# --------------------------------------------------------------------------
# slow: the real renderer on the vanilla files
# --------------------------------------------------------------------------

VANILLA = APP / 'storage' / 'test-base' / 'files'


def _luma(path):
    np = pytest.importorskip('numpy')
    Image = pytest.importorskip('PIL.Image')
    with Image.open(path) as image:
        assert image.size == (640, 527)
        rgb = np.asarray(image.convert('RGB')).astype(float)
    return rgb, rgb.mean(axis=2)


@pytest.mark.slow
@pytest.mark.skipif(not (VANILLA / 'MnSlChr.usd').is_file()
                    or not (VANILLA / 'MnSlMap.usd').is_file(),
                    reason='no vanilla MnSlChr / MnSlMap in storage/test-base')
def test_renders_both_screens_from_the_vanilla_files(tmp_path, monkeypatch):
    from core.config import HSDRAW_EXE
    if not Path(HSDRAW_EXE).exists():
        pytest.skip('HSDRawViewer is not fetched')
    monkeypatch.setattr(menu_backdrops, 'BACKDROP_DIR', tmp_path / 'menu_backdrops')
    monkeypatch.setattr(menu_backdrops, '_failed', set())
    monkeypatch.setattr(vanilla_refs, 'ensure_vanilla_ref',
                        lambda name, storage_path=None: VANILLA / name)

    css = menu_backdrops.backdrop_path('css')
    assert css is not None, 'the CSS did not render (does the pinned HSDLib have --menu-render?)'
    rgb, luma = _luma(css)
    # The grey header band and the four N/A doors stand out from the dark
    # middle of the screen.
    middle = luma[150:250].mean()
    assert luma[0:90].mean() > middle + 25
    assert luma[300:480, 40:600].mean() > middle + 25

    sss = menu_backdrops.backdrop_path('sss')
    assert sss is not None, 'the SSS did not render'
    rgb, luma = _luma(sss)
    # Fogged navy background (fog drawn per pixel, as GX does: the old
    # per-vertex fog turned the whole plane flat navy) ...
    assert rgb[..., 2].mean() > 1.8 * rgb[..., 0].mean()
    assert luma.std() > 15
    # ... and the frame model after its intro: the top border line.
    assert (luma[34:48, 40:600] > 100).mean() > 0.1
