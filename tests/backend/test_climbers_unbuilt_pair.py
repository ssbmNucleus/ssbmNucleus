"""An Any Climbers pair works before it has ever been installed.

A pair is stored in the vault as a *recipe* — two fighter names plus composited
art — not a baked `fighter.zip`, so that creating one does not require an open
project. Only the install path called `pairs.materialize`, so every other
consumer met a `fighter.zip` that was not there yet.

Reported 2026-09-13, hours after 0.8.5 shipped: making a pair and pressing
Test in game raised "Custom character archive not found:
.../custom_characters/jigglypuff-kirby/fighter.zip". Installing through the ISO
editor worked, which is what localised it to the test-build path.
"""
from tests.paths import BACKEND
import sys
from pathlib import Path

import pytest

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

from vault.climbers import roster  # noqa: E402


PAIR = {'slug': 'jigglypuff-kirby', 'name': 'Jigglypuff + Kirby',
        'climbers': {'leader': 'Jigglypuff', 'partner': 'Kirby'}}


def test_a_pair_is_materialized_before_it_is_added(monkeypatch, tmp_path):
    """The build materializes the recipe instead of demanding a stored zip."""
    from projects.install import test_build

    monkeypatch.setattr(test_build, '_pair_entry', lambda slug: PAIR)
    monkeypatch.setattr(test_build, 'CUSTOM_CHARACTERS_PATH', tmp_path / 'chars')

    proj = tmp_path / 'proj'
    proj.mkdir()
    monkeypatch.setattr(test_build, 'create_temp_project',
                        lambda iso, log=None, **_k: (str(proj), str(proj / 'p.mexproj')))

    built = tmp_path / 'built.zip'
    built.write_bytes(b'PK\x05\x06' + b'\0' * 18)
    seen = {}

    def fake_materialize(entry, char_dir, project_path):
        seen['entry'] = entry
        seen['char_dir'] = Path(char_dir)
        return built

    monkeypatch.setitem(sys.modules, 'vault.climbers.pairs',
                        type(sys)('vault.climbers.pairs'))
    sys.modules['vault.climbers.pairs'].materialize = fake_materialize

    added = {}

    class FakeMex:
        def __init__(self, *a):
            pass

        def _run_command(self, cmd, *args):
            added['zip'] = args[-1]
            return {'name': 'Jigglypuff + Kirby'}

    monkeypatch.setattr(test_build, 'MexManager', FakeMex)
    monkeypatch.setattr(test_build, '_place_in_css',
                        lambda *a, **k: {'cssIcon': None}, raising=False)

    with pytest.raises(Exception):
        # The CSS/export tail needs a real project; we only assert on what
        # happened BEFORE it — the pair was built and handed to add-fighter.
        test_build.build_custom_character_iso('v.iso', PAIR['slug'], 'out.iso')

    assert seen['entry'] is PAIR, 'the recipe was not passed to materialize'
    assert added.get('zip') == str(built), 'add-fighter did not get the built pair'


def test_the_pair_is_not_built_into_the_vault_directory(monkeypatch, tmp_path):
    """A throwaway test build must not clobber the installed package.

    The vault's fighter.zip was built against the user's real project; a test
    build runs against a fresh vanilla temp project, so writing there would
    replace a good package with one missing every m-ex fighter.
    """
    from projects.install import test_build

    vault = tmp_path / 'chars'
    monkeypatch.setattr(test_build, '_pair_entry', lambda slug: PAIR)
    monkeypatch.setattr(test_build, 'CUSTOM_CHARACTERS_PATH', vault)

    proj = tmp_path / 'proj'
    proj.mkdir()
    monkeypatch.setattr(test_build, 'create_temp_project',
                        lambda iso, log=None, **_k: (str(proj), str(proj / 'p.mexproj')))

    seen = {}

    def fake_materialize(entry, char_dir, project_path):
        seen['char_dir'] = Path(char_dir)
        raise RuntimeError('stop here')

    monkeypatch.setitem(sys.modules, 'vault.climbers.pairs',
                        type(sys)('vault.climbers.pairs'))
    sys.modules['vault.climbers.pairs'].materialize = fake_materialize

    with pytest.raises(RuntimeError):
        test_build.build_custom_character_iso('v.iso', PAIR['slug'], 'out.iso')

    assert vault not in seen['char_dir'].parents, (
        f"built into the vault ({seen['char_dir']}) instead of the temp project")
    assert proj in seen['char_dir'].parents


def test_a_non_pair_still_requires_its_archive(monkeypatch, tmp_path):
    """The original error is still raised for an ordinary custom character."""
    from projects.install import test_build

    monkeypatch.setattr(test_build, '_pair_entry', lambda slug: None)
    monkeypatch.setattr(test_build, 'CUSTOM_CHARACTERS_PATH', tmp_path / 'chars')

    with pytest.raises(FileNotFoundError, match='Custom character archive not found'):
        test_build.build_custom_character_iso('v.iso', 'some-fighter', 'out.iso')


def test_nana_is_not_selectable():
    """She is a real fighter but only ever the Ice Climbers' follower."""
    assert not roster.is_selectable('Nana')


def test_both_candidate_paths_hide_the_same_fighters(monkeypatch):
    """The picker must not gain entries just because a project is open.

    The project path applied only the leader/partner blocks, so Nana came back
    listed-but-blocked — and she ships no css_icon.png, which is why the report
    was a broken tile rather than a dimmed one.
    """
    from vault.climbers import pairs

    fighters = [{'name': 'Jigglypuff', 'costumes': [1]},
                {'name': 'Kirby', 'costumes': [1]},
                {'name': 'Nana', 'costumes': [1]}]
    monkeypatch.setattr(pairs, 'load_fighters', lambda p: fighters)
    monkeypatch.setattr(pairs, '_SPECIAL_SLOT_COUNT', 0)

    names = [c['name'] for c in pairs.candidates('some/project')]
    assert 'Nana' not in names, 'Nana is listed when a project is open'
    assert 'Jigglypuff' in names and 'Kirby' in names


def test_the_reported_crash_no_longer_happens(monkeypatch, tmp_path):
    """The exact report: a pair in the vault, no fighter.zip, Test in game.

    Written to go through the real metadata lookup rather than stubbing the
    helper the fix introduced, so it reproduces the original failure on
    unfixed source instead of erroring on a missing attribute.
    """
    import core.metadata
    from projects.install import test_build

    monkeypatch.setattr(core.metadata, 'load_metadata',
                        lambda *a, **k: {'custom_characters': [PAIR]})

    chars = tmp_path / 'chars'
    (chars / PAIR['slug']).mkdir(parents=True)      # the card exists...
    # ...but no fighter.zip inside it, exactly as a freshly created pair sits.
    monkeypatch.setattr(test_build, 'CUSTOM_CHARACTERS_PATH', chars)

    proj = tmp_path / 'proj'
    proj.mkdir()
    monkeypatch.setattr(test_build, 'create_temp_project',
                        lambda iso, log=None, **_k: (str(proj), str(proj / 'p.mexproj')))

    monkeypatch.setitem(sys.modules, 'vault.climbers.pairs', type(sys)('vault.climbers.pairs'))
    sys.modules['vault.climbers.pairs'].materialize = (
        lambda entry, char_dir, project_path: (_ for _ in ()).throw(
            RuntimeError('reached materialize')))

    with pytest.raises(Exception) as exc:
        test_build.build_custom_character_iso('v.iso', PAIR['slug'], 'out.iso')

    assert 'Custom character archive not found' not in str(exc.value), (
        'still refusing a pair that has not been installed yet')
    assert 'reached materialize' in str(exc.value)
