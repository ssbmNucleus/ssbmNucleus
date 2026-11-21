import pytest

from randall.recolor import vanilla


@pytest.fixture
def extracted(tmp_path, monkeypatch):
    """A stand-in extracted vanilla set: Fox with two slots, Marth with none."""
    monkeypatch.setattr(vanilla.config, 'VANILLA_ASSETS_DIR', tmp_path)
    for code in ('PlFxNr', 'PlFxOr'):
        directory = tmp_path / 'Fox' / code
        directory.mkdir(parents=True)
        (directory / f'{code}.dat').write_bytes(b'dat')
    (tmp_path / 'Fox' / 'PlFxNr' / 'csp.png').write_bytes(b'png')
    return tmp_path


def test_only_extracted_slots_are_offered(extracted):
    # La and Gr are in the CSS order but absent from disk.
    assert vanilla.available_colors('Fox') == ['Nr', 'Or']
    assert vanilla.available_colors('Marth') == []


def test_naming_a_character_opens_the_default_and_lists_the_rest(extracted, monkeypatch):
    # Asking for the slot list and then asking again for the file cost a whole
    # model round, and the answer was Nr almost every time. One call now.
    monkeypatch.setattr(vanilla.mod_files, 'register',
                        lambda data, name, **kw: {'file_id': 'f', 'name': name})
    result = vanilla.open_vanilla_file('fox')
    assert result['color'] == 'Nr' and result['costume_code'] == 'PlFxNr'
    assert result['files'] and result['colors'] == ['Nr', 'Or']


def test_opening_a_slot_returns_a_working_copy(extracted, monkeypatch):
    registered = []
    monkeypatch.setattr(vanilla.mod_files, 'register',
                        lambda data, name, **kw: registered.append((name, kw)) or {'file_id': 'f', 'name': name})
    result = vanilla.open_vanilla_file('Fox', 'nr')
    assert result['costume_code'] == 'PlFxNr'
    # The portrait rides along so the costume can be shown, not just edited.
    assert [name for name, _ in registered] == ['PlFxNr.dat', 'PlFxNr portrait.png']
    assert registered[0][1]['origin']['vanilla_color'] == 'Nr'


def test_a_missing_character_is_named_not_guessed(extracted):
    with pytest.raises(ValueError, match='No vanilla costumes'):
        vanilla.open_vanilla_file('Sonic')


def test_an_unextracted_character_says_so(extracted):
    with pytest.raises(ValueError, match='Refresh vanilla assets'):
        vanilla.open_vanilla_file('Marth')


def test_an_absent_slot_lists_what_exists(extracted):
    with pytest.raises(ValueError, match='Available: Nr, Or'):
        vanilla.open_vanilla_file('Fox', 'Pink')


def test_game_and_watch_shares_one_dat(extracted):
    """Four colors live in the MxDt row, so only the neutral file exists."""
    directory = extracted / 'Mr. Game & Watch' / 'PlGwNr'
    directory.mkdir(parents=True)
    (directory / 'PlGwNr.dat').write_bytes(b'dat')
    assert vanilla.available_colors('Mr. Game & Watch') == ['Nr']


def test_readiness_is_false_before_extraction(tmp_path, monkeypatch):
    monkeypatch.setattr(vanilla.config, 'VANILLA_ASSETS_DIR', tmp_path)
    assert vanilla.vanilla_assets_ready() is False
