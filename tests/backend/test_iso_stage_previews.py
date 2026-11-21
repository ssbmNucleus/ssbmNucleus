import hashlib
import struct
from pathlib import Path

from PIL import Image
import pytest

from vault.routes import das
from vault.importing import stage_previews
from vault.importing.das_scan import DetectedVariant
from shared.vanilla_extract import vanilla_refs


class FakePool:
    calls = []
    failures = set()

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def render(self, args):
        self.calls.append(args)
        if Path(args[1]).stem in self.failures:
            # Failed/partial native output must never become a vault preview.
            Path(args[2]).write_bytes(b'partial PNG')
            return False
        Image.new('RGB', stage_previews.PREVIEW_SIZE, 'green').save(args[2])
        return True


@pytest.fixture
def renderer(monkeypatch):
    FakePool.calls = []
    FakePool.failures = set()
    monkeypatch.setattr(stage_previews, 'CspRenderPool', FakePool)
    return FakePool


def extracted_iso(monkeypatch, vault, files):
    iso = vault.touch('test.iso')
    # Use the real FST reader: a basename-only Gr* filter used to discard
    # arbitrary variant names inside GrPs/ and the other stage folders.
    parents = {str(Path(name).parent) for name in files}
    assert len(parents) == 1
    count = 2 + len(files)
    names = bytearray()
    entries = bytearray(struct.pack('>III', 0x01000000, 0, count))
    payload = bytearray(0x4000)

    def name_offset(name):
        offset = len(names)
        names.extend(name.encode('ascii') + b'\0')
        return offset

    entries.extend(struct.pack('>III', 0x01000000 | name_offset(parents.pop()), 0, count))
    for name, content in files.items():
        entries.extend(struct.pack('>III', name_offset(Path(name).name), len(payload), len(content)))
        payload.extend(content)
    fst = entries + names
    payload[:6] = b'GALE01'
    struct.pack_into('>II', payload, 0x424, 0x1000, len(fst))
    payload[0x1000:0x1000 + len(fst)] = fst
    iso.write_bytes(payload)
    return iso


def test_iso_import_saves_previews_and_returns_card_urls(vault, monkeypatch, renderer):
    iso = extracted_iso(monkeypatch, vault, {'GrPs/Neon.dat': b'neon-stage'})
    client = vault.client(das, 'das_bp')
    result = client.post('/api/mex/das/scan-iso', json={'isoPath': str(iso)}).get_json()

    assert result['success'] and result['importedCount'] == 1
    item = result['imported'][0]
    assert item['screenshotUrl'] == f"/storage/das/pokemon_stadium/{item['id']}_screenshot.png"
    saved = vault.read()['stages']['pokemon_stadium']['variants'][0]
    assert saved['has_screenshot'] is True
    assert vault.path('das', 'pokemon_stadium', saved['filename']).is_file()
    with Image.open(vault.path('das', 'pokemon_stadium', saved['screenshot_filename'])) as img:
        assert img.size == (768, 432)
    args = renderer.calls[0]
    assert args[args.index('--groups') + 1] == '0,1,2,5'
    assert args[args.index('--frame') + 1] == '60'


def test_preview_failure_keeps_import_and_later_variants(vault, monkeypatch, renderer):
    renderer.failures = {'Broken'}
    iso = extracted_iso(monkeypatch, vault, {'GrNBa/Broken.dat': b'bad', 'GrNBa/Good.dat': b'good'})
    result = vault.client(das, 'das_bp').post('/api/mex/das/scan-iso', json={'isoPath': str(iso)}).get_json()
    assert result['success'] and result['importedCount'] == 2
    saved = vault.read()['stages']['battlefield']['variants']
    broken = next(e for e in saved if e['name'] == 'Broken')
    good = next(e for e in saved if e['name'] == 'Good')
    assert vault.path('das', 'battlefield', broken['filename']).is_file()
    assert not broken.get('has_screenshot')
    assert good['has_screenshot']
    assert not list(vault.path('das', 'battlefield').glob('.preview-*'))
    assert not vault.path('das', 'battlefield', f"{broken['id']}_screenshot.png").exists()


def test_rescan_backfills_old_preview_then_preserves_it(vault, monkeypatch, renderer):
    content = b'existing-stadium'
    iso = extracted_iso(monkeypatch, vault, {'GrPs/Old.dat': content})
    variant = DetectedVariant('GrPs', 'Pokemon Stadium', 'pokemon_stadium', 'Old',
                              vault.touch('old.dat', data=content), hashlib.md5(content).hexdigest(), 'mex', 'Old')
    entry = das.das_scan.import_variant_to_vault(variant, vault.storage / 'das')
    vault.write({'stages': {'pokemon_stadium': {'variants': [entry]}}})
    client = vault.client(das, 'das_bp')

    result = client.post('/api/mex/das/scan-iso', json={'isoPath': str(iso)}).get_json()
    assert result['success'] and result['importedCount'] == 0
    assert len(result['skipped']) == 1 and result['skipped'][0]['screenshotUrl']
    assert len(renderer.calls) == 1
    assert len(vault.read()['stages']['pokemon_stadium']['variants']) == 1

    # Preserve a user-supplied screenshot, including non-PNG formats.
    screenshot = vault.path('das', 'pokemon_stadium', f"{entry['id']}_screenshot.png")
    screenshot.unlink()
    custom = screenshot.with_suffix('.jpg')
    Image.new('RGB', (320, 240), 'blue').save(custom)
    original = custom.read_bytes()
    result = client.post('/api/mex/das/scan-iso', json={'isoPath': str(iso)}).get_json()
    assert result['importedCount'] == 0
    assert result['skipped'][0]['screenshotUrl'].endswith('.jpg')
    assert len(renderer.calls) == 1 and custom.read_bytes() == original


def test_empty_scan_never_starts_renderer(vault, monkeypatch, renderer):
    iso = extracted_iso(monkeypatch, vault, {'GrNBa/vanilla.dat': b'vanilla'})
    result = vault.client(das, 'das_bp').post('/api/mex/das/scan-iso', json={'isoPath': str(iso)}).get_json()
    assert result['success'] and result['importedCount'] == 0
    assert renderer.calls == []


def test_preview_work_does_not_hold_metadata_transaction(vault, monkeypatch, renderer):
    from contextlib import contextmanager
    active = False
    transaction = das.metadata_transaction

    @contextmanager
    def track_transaction(**kwargs):
        nonlocal active
        with transaction(**kwargs) as metadata:
            active = True
            try:
                yield metadata
            finally:
                active = False

    render = renderer.render

    def check_unlocked(self, args):
        assert not active, 'Native render must not hold the vault write transaction'
        return render(self, args)

    monkeypatch.setattr(das, 'metadata_transaction', track_transaction)
    monkeypatch.setattr(renderer, 'render', check_unlocked)
    iso = extracted_iso(monkeypatch, vault, {'GrNBa/Test.dat': b'stage'})
    result = vault.client(das, 'das_bp').post('/api/mex/das/scan-iso', json={'isoPath': str(iso)}).get_json()
    assert result['imported'][0]['screenshotUrl']
