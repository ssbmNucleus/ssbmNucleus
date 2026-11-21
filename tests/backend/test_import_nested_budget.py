"""Finding 2: nested package payloads are inside the cumulative budget.

The fixtures here are HEADER-ONLY. A ZIP central directory is patched to
*advertise* a huge uncompressed size; the bytes on disk stay tiny and nothing
in this file ever decompresses a bomb. That is exactly what the classifier and
preflight look at, so the declared size is enough to prove the defect and the
fix.
"""
import io
import json
import os
import zipfile

import pytest

from randall.website import website_safety
from vault.routes.import_unified import routes
import vault.importing.custom_character_zip as cc_zip
import vault.importing.unified.archive as unified_archive
from vault.importing.unified.detection import detect_content_type
from core.safe_extract import ArchiveBudgetExceeded, Budget, preflight_zip


ADVERTISED = 1024 * 1024 * 1024  # 1 GiB claimed by the header, 1 byte on disk


def _zip_bytes(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buffer.getvalue()


def _advertise(raw, real_size, declared):
    """Patch every little-endian uncompressed-size field from real to declared."""
    return raw.replace(real_size.to_bytes(4, 'little'), declared.to_bytes(4, 'little'))


def _nested_fighter_package_bomb():
    """An outer ZIP whose nested package advertises a 1 GiB costume.

    A nested `fighter.yml` is what makes the OUTER archive a recognised
    package, which used to end the chat preflight right there.
    """
    inner = _zip_bytes({
        'fighter.yml': b'name: Bomb\n',
        'PlBmNr.dat': b'\x00',
    })
    inner = _advertise(inner, 1, ADVERTISED)
    return _zip_bytes({'package.zip': inner, 'readme.txt': b'hi'})


def test_the_nested_package_still_classifies_as_a_package(tmp_path):
    """Sanity: the classification the exemption used to hang off is unchanged."""
    path = tmp_path / 'mod.zip'
    path.write_bytes(_nested_fighter_package_bomb())
    verdict = detect_content_type(str(path), 'website-mod.zip', deep=False)
    assert verdict['type'] == 'mex_fighter_yml'
    assert verdict['type'] in unified_archive._PACKAGE_TYPES


def test_declared_nested_payload_is_charged_during_classification(tmp_path):
    path = tmp_path / 'mod.zip'
    path.write_bytes(_nested_fighter_package_bomb())
    budget = Budget(max_bytes=16 * 1024 * 1024)
    with pytest.raises(ArchiveBudgetExceeded):
        detect_content_type(str(path), 'website-mod.zip', deep=False, budget=budget)


def test_chat_preflight_rejects_the_nested_bomb(tmp_path):
    """The exact shape from the review: recognised package, huge nested payload.

    Before the fix this returned `{'unsafe_costumes': [], 'checked_count': 0}`
    with zero costumes checked and no complaint about the size.
    """
    path = tmp_path / 'mod.zip'
    path.write_bytes(_nested_fighter_package_bomb())
    with pytest.raises(ValueError, match='safety-check limit'):
        website_safety.inspect_archive(path)


def test_the_converter_preflights_a_nested_package_before_reading_it(tmp_path):
    """fighter_yml_converter used to read nested members with no budget."""
    from vault.importing import fighter_yml_converter
    budget = Budget(max_bytes=16 * 1024 * 1024)
    with pytest.raises(ArchiveBudgetExceeded):
        fighter_yml_converter.convert_fighter_yml_zip(
            _nested_fighter_package_bomb(), 'Bomb', budget=budget)


def test_custom_character_package_import_shares_the_budget(tmp_path, monkeypatch):
    import vault.routes.custom_characters as cc
    import vault.catalog.custom_characters as cc_catalog
    root = tmp_path / 'vault'
    root.mkdir()
    monkeypatch.setattr(cc, 'CUSTOM_CHARACTERS_PATH', root)
    monkeypatch.setattr(cc_zip, 'CUSTOM_CHARACTERS_PATH', root)
    monkeypatch.setattr(cc_catalog, 'CUSTOM_CHARACTERS_PATH', root)  # slug allocation
    # Only the 1-byte payload member's declared size is patched; the json
    # member is longer, so the patch cannot disturb it.
    package = _zip_bytes({'fighter.json': json.dumps({'name': 'Bomb', 'costumes': []}).encode(),
                          'payload.dat': b'\x00'})
    package = _advertise(package, 1, ADVERTISED)
    budget = Budget(max_bytes=16 * 1024 * 1024)
    with pytest.raises(ArchiveBudgetExceeded):
        cc_zip.import_custom_character_zip_bytes(package, 'Bomb', budget)
    assert not any(root.iterdir())


def test_a_restore_charges_its_package_once_not_twice(tmp_path, monkeypatch):
    """Preflight + staged extraction of the SAME archive is one expansion.

    Charging both would fail a legitimately large export at roughly half the
    advertised allowance.
    """
    import vault.routes.custom_characters as cc
    import vault.catalog.custom_characters as cc_catalog
    import core.metadata as core_metadata
    root = tmp_path / 'vault'
    root.mkdir()
    monkeypatch.setattr(cc, 'CUSTOM_CHARACTERS_PATH', root)
    monkeypatch.setattr(cc_zip, 'CUSTOM_CHARACTERS_PATH', root)
    monkeypatch.setattr(cc_catalog, 'CUSTOM_CHARACTERS_PATH', root)  # slug allocation
    meta = tmp_path / 'metadata.json'
    meta.write_text(json.dumps({'custom_characters': []}), encoding='utf-8')
    monkeypatch.setattr(core_metadata, 'METADATA_FILE', meta)

    payload = b'\x00' * (4 * 1024 * 1024)
    package = _zip_bytes({
        cc.NUCLEUS_EXPORT_MARKER: json.dumps({
            'nucleus_export': cc.NUCLEUS_EXPORT_KIND, 'version': 1,
            'entry': {'slug': 'big', 'name': 'Big'}}).encode(),
        'fighter.json': json.dumps({'name': 'Big', 'costumes': []}).encode(),
        'costumes/PlBgNr.dat': payload,
    })
    budget = Budget(max_bytes=6 * 1024 * 1024)  # room for one expansion, not two
    cc_zip.import_custom_character_zip_bytes(package, 'Big', budget)

    assert (root / 'big' / 'costumes' / 'PlBgNr.dat').read_bytes() == payload
    # Declared once: the marker + fighter.json + the 4 MiB costume.
    assert budget.used_bytes < 5 * 1024 * 1024
    assert budget.used_members == 3


def _nest(payload, levels, name='level.zip'):
    for _ in range(levels):
        payload = _zip_bytes({name: payload})
    return payload


def test_a_deeper_fixture_is_refused_rather_than_silently_skipped(tmp_path):
    """The re-review's probe: outer / level1 / level2 / package / costume / csp.

    The inspection used to stop descending at its depth limit and return "no
    unsafe costumes", and the real importer then accepted a costume whose CSP
    header advertised 1 GiB. Nothing here decompresses anything: the header is
    the whole fixture.
    """
    costume = _advertise(_zip_bytes({'csp.png': bytes(1)}), 1, ADVERTISED)
    package = _zip_bytes({'fighter.yml': b'name: Deep', 'costume.zip': costume})
    path = tmp_path / 'mod.zip'
    path.write_bytes(_nest(package, 3))
    with pytest.raises(ValueError, match='nests archives deeper|safety-check limit'):
        website_safety.inspect_archive(path)


def test_the_converter_checks_every_costume_archive_not_just_the_first(tmp_path):
    """It used to validate a costume zip only while hunting for the first CSP."""
    from vault.importing import fighter_yml_converter
    clean = _zip_bytes({'csp.png': bytes(1)})
    bomb = _advertise(_zip_bytes({'stc.png': bytes(1)}), 1, ADVERTISED)
    package = _zip_bytes({
        'fighter.yml': b'name: Deep',
        'one.zip': clean,
        'two.zip': bomb,
    })
    budget = Budget(max_bytes=16 * 1024 * 1024)
    with pytest.raises(ValueError):
        fighter_yml_converter.convert_fighter_yml_zip(package, 'Deep', budget=budget)


def test_the_converter_honours_the_nesting_limit(tmp_path):
    """`max_depth=0` used to accept a nested package anyway."""
    from vault.importing import fighter_yml_converter
    package = _zip_bytes({'fighter.yml': b'name: Deep', 'PlDpNr.dat': bytes(1)})
    outer = _zip_bytes({'package.zip': package})
    with pytest.raises(ArchiveBudgetExceeded):
        fighter_yml_converter.convert_fighter_yml_zip(
            outer, 'Deep', budget=Budget(max_depth=0))


def test_valid_near_limit_siblings_are_accepted(tmp_path):
    """Two honest archives that together fit must not be refused.

    The previous cumulative test proved nothing: each of its fixtures broke the
    compression-ratio rule on its own. These carry REAL incompressible bytes,
    so only the cumulative byte cap can decide, and it accepts them.
    """
    share = 3 * 1024 * 1024
    inner_one = _zip_bytes({'a.bin': os.urandom(share)})
    inner_two = _zip_bytes({'b.bin': os.urandom(share)})
    path = tmp_path / 'mod.zip'
    path.write_bytes(_zip_bytes({'one.zip': inner_one, 'two.zip': inner_two}))
    budget = website_safety.download_budget()
    budget.max_bytes = 10 * 1024 * 1024
    assert website_safety.inspect_archive(path, budget=budget)['unsafe_costumes'] == []
    assert budget.used_bytes == 2 * share             # both were really counted, once each


def test_the_same_siblings_are_refused_once_the_cap_is_below_their_sum(tmp_path):
    """The same fixture, with room for one of them: cumulative, not per archive."""
    share = 3 * 1024 * 1024
    inner_one = _zip_bytes({'a.bin': os.urandom(share)})
    inner_two = _zip_bytes({'b.bin': os.urandom(share)})
    path = tmp_path / 'mod.zip'
    path.write_bytes(_zip_bytes({'one.zip': inner_one, 'two.zip': inner_two}))
    budget = website_safety.download_budget()
    budget.max_bytes = 4 * 1024 * 1024 + 512 * 1024   # fits one, not two
    with pytest.raises(ValueError, match='safety-check limit'):
        website_safety.inspect_archive(path, budget=budget)


def test_a_solid_7z_of_two_ordinary_files_is_accepted(tmp_path):
    """py7zr reports compressed=None for later members of a solid block.

    Treating that as zero triggered the compression-ratio refusal, so an
    entirely ordinary two-file solid archive could not be imported at all.
    """
    py7zr = pytest.importorskip('py7zr')
    from core.safe_archive import safe_extract_7z
    source = tmp_path / 'src'
    source.mkdir()
    for name in ('a.bin', 'b.bin'):
        (source / name).write_bytes(os.urandom(1_100_000))
    archive = tmp_path / 'solid.7z'
    with py7zr.SevenZipFile(archive, 'w') as writer:
        writer.writeall(source, 'src')
    with py7zr.SevenZipFile(archive, 'r') as reader:
        packed = [getattr(info, 'compressed', None) for info in reader.list()]
    assert None in packed, 'fixture is not solid; the regression needs a shared block'
    with py7zr.SevenZipFile(archive, 'r') as reader:
        safe_extract_7z(reader, tmp_path / 'out')
    assert sorted(p.name for p in (tmp_path / 'out').rglob('*') if p.is_file()) == ['a.bin', 'b.bin']


def test_a_7z_entry_that_is_not_a_regular_file_is_refused(tmp_path):
    from core.safe_archive import safe_extract_7z

    class Info:
        def __init__(self, **kwargs):
            self.filename = kwargs.pop('filename')
            self.is_directory = False
            self.uncompressed = 10
            self.compressed = 10
            self.is_symlink = False
            self.is_junction = False
            for key, value in kwargs.items():
                setattr(self, key, value)

    class Archive:
        def __init__(self, infos):
            self._infos = infos
        def list(self):
            return self._infos
        def extractall(self, path=None):
            raise AssertionError('must not extract')

    for flag in ('is_symlink', 'is_junction'):
        with pytest.raises(ValueError, match='links are not allowed'):
            safe_extract_7z(Archive([Info(filename='x.dat', **{flag: True})]),
                            tmp_path / 'out')


def test_an_ordinary_archive_still_passes_the_budget(tmp_path):
    path = tmp_path / 'mod.zip'
    path.write_bytes(_zip_bytes({'PlMsBu.dat': b'\x00' * 2048, 'readme.txt': b'hi'}))
    budget = Budget()
    with zipfile.ZipFile(path) as zf:
        preflight_zip(zf, budget=budget)
    assert budget.used_bytes == 2048 + 2 and budget.used_members == 2


# ── review JJ, finding 1: archive members are bounded before they are read ─

def test_an_archive_member_advertising_a_gigabyte_is_refused_before_it_is_read():
    """It passed preflight with ZERO bytes charged, even at a 1 KiB limit.

    Archive members were exempted from the cumulative charge to stop double
    counting, and the per-member cap went with it -- so identification then
    reached its `archive.read()` on a member advertising 1 GiB.
    """
    raw = _zip_bytes({'payload.zip': bytes(1)})
    patched = _advertise(raw, 1, ADVERTISED)
    with zipfile.ZipFile(io.BytesIO(patched)) as zf:
        assert zf.infolist()[0].file_size == ADVERTISED
        with pytest.raises(ArchiveBudgetExceeded):
            preflight_zip(zf, budget=Budget(max_bytes=1024))


def test_two_identical_siblings_cost_twice(tmp_path):
    """Keying on content alone let two identical 3 MiB siblings past 4.5 MiB.

    Re-reading ONE archive is free; two physical copies are two extractions.
    """
    share = 3 * 1024 * 1024
    inner = _zip_bytes({'a.bin': os.urandom(share)})
    path = tmp_path / 'mod.zip'
    path.write_bytes(_zip_bytes({'one.zip': inner, 'two.zip': inner}))
    budget = website_safety.download_budget()
    budget.max_bytes = int(4.5 * 1024 * 1024)
    with pytest.raises(ValueError, match='safety-check limit'):
        website_safety.inspect_archive(path, budget=budget)


def test_walking_one_archive_three_times_still_costs_once(tmp_path):
    """Classification, the safety preflight and the import see the same file."""
    share = 3 * 1024 * 1024
    inner = _zip_bytes({'a.bin': os.urandom(share)})
    path = tmp_path / 'mod.zip'
    path.write_bytes(_zip_bytes({'one.zip': inner}))
    budget = website_safety.download_budget()
    budget.max_bytes = 5 * 1024 * 1024
    website_safety.inspect_archive(path, budget=budget)
    before = budget.used_bytes
    website_safety.inspect_archive(path, budget=budget)
    assert budget.used_bytes == before


def test_an_unopenable_child_makes_the_plan_uninspected(tmp_path):
    """A malformed child used to disappear from the plan entirely."""
    from vault.importing.unified.normalize import describe_import_target
    path = tmp_path / 'mod.zip'
    path.write_bytes(_zip_bytes({'PlMsBu.dat': bytes(64),
                                 'broken.zip': b'not an archive at all'}))
    report = describe_import_target(str(path), 'mod.zip')
    assert report['uninspected'], report
