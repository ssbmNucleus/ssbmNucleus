"""
Guard: no <img src> may hand-build a backend URL.

THE BUG THIS EXISTS TO PREVENT. app.py's `require_backend_token`
before_request 401s every /api/ request that carries no token. `fetch()` sends
it as an X-Nucleus-Token header, but an <img src> cannot send a header at all,
so config.js exposes `backendMediaUrl()` to put the token in the query string
instead.

Components that built their src by hand --

    src={`${BACKEND_URL}${char.icon_url}`}

-- kept working right up until the token was enforced, and then silently
started 401ing. Silently, because the src had an onError that hid the broken
image and showed a letter placeholder. v0.8.0 shipped with every custom
character icon and both character banners replaced by placeholders, and the
backend log filled with 125 unattended 401s that nothing surfaced. A user found
it, not us.

Nothing in the build could catch it: the JSX is valid, the bundle compiles, and
the images fail at RUNTIME against a live token. So the check is structural --
if a template literal glues a backend origin onto an image src, fail here.

The fix at every call site is the same:

    src={backendMediaUrl(char.icon_url)}

which is a no-op for /storage, /vanilla and /utility URLs and appends the token
for /api/ ones, so it is always the right thing to reach for.
"""
from tests.paths import APP, BACKEND
import re
from pathlib import Path

import pytest

FRONTEND = APP / 'frontend' / 'src'

# A template literal starting with a backend origin, used as a src/href.
HAND_BUILT = re.compile(
    r"\b(?:src|href)=\{`\$\{"
    r"(?:BACKEND_URL|BACKEND_BASE|backendBase|BACKEND_ORIGIN"
    r"|API_URL\.replace\('/api/mex', ''\))\}"
)

# The same mistake assigned imperatively: `img.src = \`${API_URL}...\`` for a
# canvas-drawn image, or `link.href = api.url(...)` for an <a download>.
# Neither can send a header either. These broke the CSS editor's icon grid
# (every icon drawn as a white box) and every vault Export button, silently,
# because a failed <a download> just does nothing.
HAND_BUILT_ASSIGN = re.compile(
    r"\.(?:src|href)\s*=\s*(?:`\$\{(?:API_URL|BACKEND_URL)\}|(?:api\.url|apiUrl)\()"
    r"|\b(?:downloadUrl|iconUrl|imgUrl)\s*=\s*(?:api\.url|apiUrl)\("
)

# The same mistake one step removed: an image URL parked in a variable
# (`const iconUrl = hasIcon ? `${API_URL}/custom-stages/...` : null`, later
# <img src={iconUrl}>), or an <a download> fed by a URL-builder function
# (`a.href = kind.exportUrl(id)`). The custom stage icon/banner and every
# Menus-page Export button (icon grids included) slipped past both patterns
# above this way.
HAND_BUILT_INDIRECT = re.compile(
    r"\b\w*(?:Url|URL|Src)\s*=\s*(?:[\w.!]+\s*\?\s*)?`\$\{API_URL\}"
    r"|\.href\s*=\s*(?!backendMediaUrl\()[\w.]*(?:Url|URL)\("
)


def source_files():
    if not FRONTEND.is_dir():
        return []
    return [p for p in sorted(FRONTEND.rglob('*.jsx')) + sorted(FRONTEND.rglob('*.js'))
            if 'node_modules' not in p.parts and not p.name.endswith(('.test.js', '.test.jsx'))]


@pytest.mark.skipif(not FRONTEND.is_dir(), reason='frontend/ not in this checkout')
def test_no_hand_built_backend_media_urls():
    offenders = []
    for path in source_files():
        for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if (HAND_BUILT.search(line) or HAND_BUILT_ASSIGN.search(line)
                    or HAND_BUILT_INDIRECT.search(line)):
                offenders.append(f'{path.relative_to(FRONTEND)}:{n}: {line.strip()}')
    assert not offenders, (
        'These build a backend URL by hand, so they carry no token and will '
        '401 once served from the app. Use backendMediaUrl(...) from config:\n  '
        + '\n  '.join(offenders))


@pytest.mark.skipif(not FRONTEND.is_dir(), reason='frontend/ not in this checkout')
def test_backend_download_links_set_download():
    """A tokened URL is not enough for a download link. Without `download`, a
    click on <a href> is a NAVIGATION, and electron/main.js's will-navigate
    guard cancels any navigation off the renderer's own origin -- the backend
    included. The click does nothing and nothing is logged. After 0.8.9 put the
    token on them, the custom character/stage Export ZIP and vault bundle
    download still did nothing for exactly this reason (Discord, 2026-09-22)."""
    missing = []
    for path in source_files():
        lines = path.read_text(encoding='utf-8').splitlines()
        for n, line in enumerate(lines):
            m = re.search(r'\b(\w+)\.href\s*=\s*backendMediaUrl\(', line)
            if not m:
                continue
            window = '\n'.join(lines[max(0, n - 3):n + 6])
            if f'{m.group(1)}.download' not in window:
                missing.append(f'{path.relative_to(FRONTEND)}:{n + 1}: {line.strip()}')
    assert not missing, ('backend download links without `download` are blocked '
                         'as navigations; set link.download:\n  ' + '\n  '.join(missing))


@pytest.mark.skipif(not FRONTEND.is_dir(), reason='frontend/ not in this checkout')
def test_backend_media_url_helper_still_exists():
    """The guard above is only meaningful while the helper it points at does."""
    config = FRONTEND / 'shared' / 'config' / 'config.js'
    text = config.read_text(encoding='utf-8')
    assert 'export function backendMediaUrl' in text
    # It must scope the token to the backend origin -- appending it to an
    # arbitrary URL would leak the token to whatever host that is.
    assert 'url.origin === new URL(BACKEND_URL).origin' in text
    # ...and only to /api/, which is the only prefix that checks it.
    assert "url.pathname.startsWith('/api/')" in text


@pytest.mark.skipif(not FRONTEND.is_dir(), reason='frontend/ not in this checkout')
def test_every_importer_of_the_helper_actually_imports_it():
    """A codemod that rewrites call sites but misses the import produces a
    ReferenceError at runtime, in a component that may be several clicks deep."""
    missing = []
    for path in source_files():
        text = path.read_text(encoding='utf-8')
        if 'backendMediaUrl(' not in text:
            continue
        if path.name == 'config.js':
            continue
        if not re.search(r'import\s*\{[^}]*\bbackendMediaUrl\b[^}]*\}', text):
            missing.append(str(path.relative_to(FRONTEND)))
    assert not missing, ('use backendMediaUrl but never import it: '
                         + ', '.join(missing))


def test_public_media_prefixes_are_actually_public():
    """The three prefixes the backend serves without a token are the ones an
    <img> may legitimately hit bare. If one is removed from app.py, the
    components pointing at it break exactly the way the icons did."""
    api = BACKEND / 'app.py'
    text = api.read_text(encoding='utf-8')
    for prefix in ('/api/nucleome/stock/', '/api/nucleome/stage-icon/',
                   '/api/nucleome/sprites/'):
        assert prefix in text, f'{prefix} is no longer a public media prefix'
