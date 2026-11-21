"""
The bundle/texture-pack export must ship HD portraits for costumes that have no
vault identity (e.g. Animelee-patch slots, which are custom art with only an SD
CSP). This covers the plumbing that selects the right CSP. The actual 4x render
(generate_csp -> HSDRawViewer) is NOT exercised here; only the cache keying and
the place_costume_csp resolution priority:
    export-time HD CSP  ->  live vault perceptual match  ->  SD fallback.
"""
from tests.paths import BACKEND
import sys
from dataclasses import asdict
from pathlib import Path

from PIL import Image

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

import core.config  # noqa: F401 - wires processor onto sys.path, defines STORAGE_PATH
import shared.rendering.hd_csp_cache as hc
from projects.install.texture_pack import CostumeMapping, place_costume_csp


def _png(path, size, color=(10, 20, 30, 255)):
    Image.new('RGBA', size, color).save(path)
    return path


def test_costume_mapping_has_hd_fields():
    cm = CostumeMapping(index=0, character='Fox', costume_index=0, skin_id='x',
                        real_csp_path='sd.png')
    d = asdict(cm)
    assert d['hd_csp_path'] is None
    assert d['dat_hash'] is None


def test_cache_key_and_lookup(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, 'CACHE_DIR', tmp_path / 'cache')
    dat = tmp_path / 'PlFxNr.dat'
    dat.write_bytes(b'hello-costume')
    h = hc.hash_dat(dat)
    assert h and len(h) == 32                       # md5 hex
    assert hc.cached_path(h).name == f'{h}_4x.png'
    assert hc.get_cached(h) is None                 # nothing rendered yet
    (tmp_path / 'cache').mkdir()
    hc.cached_path(h).write_bytes(b'x')             # simulate a cached render
    assert hc.get_cached(h) == hc.cached_path(h)


def test_hash_is_content_addressed(tmp_path):
    a = tmp_path / 'a.dat'; a.write_bytes(b'AAAA')
    b = tmp_path / 'b.dat'; b.write_bytes(b'AAAA')
    c = tmp_path / 'c.dat'; c.write_bytes(b'BBBB')
    assert hc.hash_dat(a) == hc.hash_dat(b)         # same bytes -> same key
    assert hc.hash_dat(a) != hc.hash_dat(c)         # different bytes -> different key


def test_place_prefers_hd_then_sd(tmp_path):
    sd = _png(tmp_path / 'sd.png', (136, 188))
    hd = _png(tmp_path / 'hd.png', (544, 752))
    out = tmp_path / 'out'; out.mkdir()

    # HD present -> the 4x render is shipped, not the SD CSP.
    c = {'character': 'Fox', 'real_csp_path': str(sd), 'hd_csp_path': str(hd)}
    assert place_costume_csp(c, 'a.png', out, storage_path=None)
    assert Image.open(out / 'a.png').size == (544, 752)

    # No HD resolved + no vault -> SD fallback.
    c = {'character': 'Fox', 'real_csp_path': str(sd), 'hd_csp_path': None}
    assert place_costume_csp(c, 'b.png', out, storage_path=None)
    assert Image.open(out / 'b.png').size == (136, 188)

    # HD path recorded but the file is gone -> SD fallback (never breaks a build).
    c = {'character': 'Fox', 'real_csp_path': str(sd), 'hd_csp_path': str(tmp_path / 'gone.png')}
    assert place_costume_csp(c, 'c.png', out, storage_path=None)
    assert Image.open(out / 'c.png').size == (136, 188)
