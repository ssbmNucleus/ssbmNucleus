"""check_setup_needed must not depend on filesystem directory order.

Regression for the Linux AppImage first-run loop: iterdir() order is
alphabetical on NTFS but hash-order on ext4, so the "sample the first 5
character folders" check could sample Nana (whose costume folders never get a
csp.png — she shares Popo's portraits) or the vanilla/sounds folder (no Pl*
subfolders at all). A completed setup then looked forever incomplete and the
app re-ran the whole setup — ISO extraction included — on every launch.
"""

from tests.paths import BACKEND
import sys
from pathlib import Path

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

from shared.vanilla_extract.first_run_setup import FirstRunSetup


CHAR_NAMES = [
    'Bowser', 'C. Falcon', 'DK', 'Dr. Mario', 'Falco', 'Fox', 'Ganondorf',
    'Ice Climbers', 'Jigglypuff', 'Kirby', 'Link', 'Luigi', 'Mario', 'Marth',
    'Mewtwo', 'Mr. Game & Watch', 'Nana', 'Ness', 'Peach', 'Pichu', 'Pikachu',
    'Roy', 'Samus', 'Sheik', 'Yoshi', 'Young Link', 'Zelda',
]

NANA_COSTUMES = ['PlNnNr', 'PlNnAq', 'PlNnWh', 'PlNnYe']


def _make_setup(tmp_path) -> FirstRunSetup:
    setup = FirstRunSetup(
        tmp_path / 'project',
        tmp_path / 'mexcli.exe',
        storage_path=tmp_path / 'storage',
    )

    vanilla = setup.vanilla_dir
    for name in CHAR_NAMES:
        codes = NANA_COSTUMES if name == 'Nana' else [f'Pl{name[:2]}Nr']
        for code in codes:
            costume = vanilla / name / code
            costume.mkdir(parents=True)
            (costume / f'{code}.dat').write_bytes(b'dat')
            # Nana legitimately has no per-costume CSPs after a real setup.
            if name != 'Nana':
                (costume / 'csp.png').write_bytes(b'png')

    # Non-character folders that live inside vanilla/ after a real setup.
    (vanilla / 'custom_poses').mkdir()
    (vanilla / 'sounds').mkdir()
    (vanilla / 'sounds' / 'click.wav').write_bytes(b'wav')

    setup.stages_dir.mkdir(parents=True)
    for i in range(len(setup.STAGE_ICONS)):
        (setup.stages_dir / f'stage_{i}.png').write_bytes(b'png')

    # Minimal valid CSP reference bank (legacy count-based recognition).
    setup.CSP_REFERENCE_FTDATA_COUNT = 1
    setup.CSP_REFERENCE_COSTUME_COUNT = 1
    setup.csp_reference_dir.mkdir(parents=True)
    (setup.csp_reference_dir / 'PlFx.dat').write_bytes(b'dat')
    (setup.csp_reference_dir / 'PlFxNr.dat').write_bytes(b'dat')

    return setup


def test_complete_setup_is_recognized_regardless_of_iterdir_order(tmp_path, monkeypatch):
    setup = _make_setup(tmp_path)

    # Simulate ext4: reversed order puts 'sounds' and Nana at the front of
    # iterdir(), where the old sample-the-first-5 check tripped over them.
    real_iterdir = Path.iterdir

    def reversed_iterdir(self):
        return iter(sorted(real_iterdir(self), key=lambda p: p.name, reverse=True))

    monkeypatch.setattr(Path, 'iterdir', reversed_iterdir)

    status = setup.check_setup_needed()
    assert status['complete'] is True, status


def test_missing_csp_still_detected(tmp_path):
    setup = _make_setup(tmp_path)
    # Break a character that IS expected to have CSPs.
    (setup.vanilla_dir / 'Bowser' / 'PlBoNr' / 'csp.png').unlink()

    status = setup.check_setup_needed()
    assert status['complete'] is False
    assert status['reason'] == 'missing_csp'


def test_sounds_folder_does_not_count_toward_character_total(tmp_path):
    setup = _make_setup(tmp_path)
    # Remove one real character: the count must drop below the threshold even
    # though custom_poses and sounds folders are present.
    import shutil
    shutil.rmtree(setup.vanilla_dir / 'Zelda')

    status = setup.check_setup_needed()
    assert status['complete'] is False
    assert status['reason'] == 'insufficient_characters'
