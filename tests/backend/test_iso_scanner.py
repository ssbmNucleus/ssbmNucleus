from tests.paths import BACKEND
import sys
import importlib
from pathlib import Path

from PIL import Image, ImageDraw


BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

from vault.importing import iso_scanner  # noqa: E402
from core import jobs
from vault.importing.iso_scanner import ScanCandidates, _validate_csp_preview  # noqa: E402
from shared.rendering import csp_concurrency  # noqa: E402

csp_module = importlib.import_module('generate_csp')


class FakeICDatParser:
    def __init__(self, path):
        self.path = Path(path)

    def read_dat(self):
        return None

    def detect_character(self):
        name = self.path.name
        if 'PlPp' in name:
            return 'Ice Climbers', 'PlyIceClimber5K_Share_joint'
        if 'PlNn' in name:
            return 'Ice Climbers (Nana)', 'PlyIceClimberNana5K_Share_joint'
        return None, None

    def detect_costume_color(self):
        suffix = self.path.stem[-2:]
        return {
            'Nr': 'Default',
            'Gr': 'Green',
            'Ye': 'Yellow',
            'Or': 'Orange',
            'Aq': 'Aqua/Light Blue',
            'Re': 'Red',
            'Wh': 'White',
        }.get(suffix, 'Unknown')


def _visible_csp(path: Path):
    image = Image.new('RGBA', (136, 188), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((42, 24, 94, 76), fill=(240, 210, 160, 255))
    draw.rectangle((34, 72, 102, 158), fill=(70, 120, 220, 255))
    draw.rectangle((24, 100, 112, 138), fill=(180, 40, 60, 255))
    image.save(path)


def _candidate_dict(dat_path: Path):
    return {
        'path': str(dat_path),
        'hash': '0123456789abcdef',
        'character': 'Fox',
        'costume_code': 'PlFxZz.dat',
        'source_iso': 'test.iso',
        'stock_path': None,
    }


def test_validate_csp_preview_rejects_transparent_image(tmp_path):
    png = tmp_path / 'blank.png'
    Image.new('RGBA', (136, 188), (0, 0, 0, 0)).save(png)

    ok, reason = _validate_csp_preview(png)

    assert not ok
    assert reason == 'transparent'


def test_validate_csp_preview_rejects_solid_opaque_frame(tmp_path):
    png = tmp_path / 'solid.png'
    Image.new('RGBA', (136, 188), (0, 0, 0, 255)).save(png)

    ok, reason = _validate_csp_preview(png)

    assert not ok
    assert reason == 'solid_frame'


def test_validate_csp_preview_accepts_visible_model_shape(tmp_path):
    png = tmp_path / 'csp.png'
    _visible_csp(png)

    ok, reason = _validate_csp_preview(png)

    assert ok
    assert reason == 'ok'


def test_find_ice_climbers_pair_uses_explicit_mismatched_pair(monkeypatch, tmp_path):
    monkeypatch.setattr(csp_module, 'DATParser', FakeICDatParser)
    popo = tmp_path / 'PlPpGr.dat'
    nana = tmp_path / 'PlNnAq.dat'
    popo.write_bytes(b'popo')
    nana.write_bytes(b'nana')

    char_type, pair_file, popo_color, nana_color = csp_module.find_ice_climbers_pair(
        popo,
        explicit_pair_filepath=nana,
    )

    assert char_type == 'popo'
    assert pair_file == str(nana)
    assert popo_color == 'Green'
    assert nana_color == 'Aqua/Light Blue'


def test_find_ice_climbers_pair_does_not_escape_temp_tree(monkeypatch, tmp_path):
    monkeypatch.setattr(csp_module, 'DATParser', FakeICDatParser)
    repo = tmp_path / 'repo'
    skin_dir = repo / 'output' / 'iso_scan' / 'job' / 'skins' / 'Ice_Climbers_bad'
    vanilla_nana_dir = repo / 'utility' / 'assets' / 'vanilla' / 'Nana' / 'PlNnYe'
    skin_dir.mkdir(parents=True)
    vanilla_nana_dir.mkdir(parents=True)
    popo = skin_dir / 'PlPpGr.dat'
    vanilla_nana = vanilla_nana_dir / 'PlNnYe.dat'
    popo.write_bytes(b'popo')
    vanilla_nana.write_bytes(b'nana')

    char_type, pair_file, popo_color, nana_color = csp_module.find_ice_climbers_pair(popo)

    assert char_type == 'popo'
    assert pair_file is None
    assert popo_color == 'Green'
    assert nana_color == 'Yellow'


def test_build_candidate_drops_failed_preview(monkeypatch, tmp_path):
    source_dat = tmp_path / 'source.dat'
    source_dat.write_bytes(b'fake dat bytes')
    generated = tmp_path / 'generated.png'
    Image.new('RGBA', (136, 188), (0, 0, 0, 0)).save(generated)

    monkeypatch.setattr(csp_concurrency, 'CSP_LAUNCH_STAGGER_S', 0)
    monkeypatch.setattr(iso_scanner, 'generate_csp', lambda _path, **_kwargs: str(generated))

    job = ScanCandidates(job=jobs.Job('iso_scan', job_id='job'), iso_paths=[], work_dir=tmp_path)
    skins_dir = tmp_path / 'skins'
    skins_dir.mkdir()
    candidate, error_kind = iso_scanner._build_candidate(
        0, _candidate_dict(source_dat), skins_dir, job)

    assert candidate is None
    assert error_kind == 'preview_failed'


def test_build_candidate_keeps_valid_preview(monkeypatch, tmp_path):
    source_dat = tmp_path / 'source.dat'
    source_dat.write_bytes(b'fake dat bytes')
    generated = tmp_path / 'generated.png'
    _visible_csp(generated)

    monkeypatch.setattr(csp_concurrency, 'CSP_LAUNCH_STAGGER_S', 0)
    monkeypatch.setattr(iso_scanner, 'generate_csp', lambda _path, **_kwargs: str(generated))

    job = ScanCandidates(job=jobs.Job('iso_scan', job_id='job'), iso_paths=[], work_dir=tmp_path)
    skins_dir = tmp_path / 'skins'
    skins_dir.mkdir()
    candidate, error_kind = iso_scanner._build_candidate(
        0, _candidate_dict(source_dat), skins_dir, job)

    assert error_kind is None
    assert candidate is not None
    assert candidate.csp_path
    assert Path(candidate.csp_path).exists()


def test_build_candidate_passes_staged_ice_climbers_pair(monkeypatch, tmp_path):
    source_dat = tmp_path / 'popo.dat'
    pair_dat = tmp_path / 'nana.dat'
    source_dat.write_bytes(b'popo bytes')
    pair_dat.write_bytes(b'nana bytes')
    generated = tmp_path / 'generated.png'
    _visible_csp(generated)
    seen = {}

    def fake_generate(_path, **kwargs):
        seen.update(kwargs)
        return str(generated)

    monkeypatch.setattr(csp_concurrency, 'CSP_LAUNCH_STAGGER_S', 0)
    monkeypatch.setattr(iso_scanner, 'generate_csp', fake_generate)

    job = ScanCandidates(job=jobs.Job('iso_scan', job_id='job'), iso_paths=[], work_dir=tmp_path)
    skins_dir = tmp_path / 'skins'
    skins_dir.mkdir()
    candidate_data = _candidate_dict(source_dat)
    candidate_data.update({
        'character': 'Ice Climbers',
        'costume_code': 'PlPpGr.dat',
        'paired_path': str(pair_dat),
        'paired_costume_code': 'PlNnAq.dat',
    })

    candidate, error_kind = iso_scanner._build_candidate(
        0, candidate_data, skins_dir, job)

    assert error_kind is None
    assert candidate is not None
    assert seen['paired_dat_filepath']
    assert Path(seen['paired_dat_filepath']).name == 'PlNnAq.dat'


def test_is_character_file_accepts_added_mex_costumes():
    # Nucleus names installed costumes `<code>Mod`; mexLib de-duplicates with
    # `_001`. Skipping them made every Nucleus-built ISO scan as empty.
    for name in ('PlFxNr.dat', 'PlFxNr.lat', 'PlSkNrMod.dat', 'PlMtNrMod_001.dat',
                 'PlZdNr_001.dat', 'PlFcBu_002.dat', 'PlFxZz.dat'):
        assert iso_scanner._is_character_file(f'/iso/files/{name}'), name
    for name in ('PlCo.dat', 'PlFx.dat', 'PlFxAJ.dat', 'PlFxDViWaitAJ.dat',
                 'PlKbCpFx.dat', 'PlKbNrCpDk.dat', 'PlFxNrMod.png', 'GrNBa.dat',
                 'PlFxNrModX.dat'):
        assert not iso_scanner._is_character_file(f'/iso/files/{name}'), name


def test_slot_asset_uses_the_files_own_slot():
    stocks = {'plsknr': 'vanilla_slot.png', 'plsknrmod': 'added.png'}
    assert iso_scanner._slot_asset(stocks, '/iso/PlSkNrMod.dat', 'PlSkNr') == 'added.png'
    assert iso_scanner._slot_asset(stocks, '/iso/PlSkNr.dat', 'PlSkNr') == 'vanilla_slot.png'
    # An added costume with no stock of its own must not borrow the vanilla slot's.
    assert iso_scanner._slot_asset(stocks, '/iso/PlSkNr_001.dat', 'PlSkNr') is None
    # A plain slot file still falls back to its content code.
    assert iso_scanner._slot_asset({'plfxnr': 'x.png'}, '/iso/PlFxNr.lat', 'PlFxNr') == 'x.png'
