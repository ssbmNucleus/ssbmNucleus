"""Containment and budget tests for the shared archive extractor.

Every hostile member here is a *name only* — nothing in this file decompresses
a bomb; the nested-bomb fixture is a header that advertises a huge size and is
rejected before a byte is read.
"""
import io
import stat
import zipfile

import pytest

from core.safe_extract import (
    ArchiveBudgetExceeded, Budget, DestinationExists, UnsafeArchiveMember,
    dangerous_members, extract_zip, extract_zip_to_new_directory,
    is_safe_member_name, member_parts, preflight_zip, reserve_directory,
    staged_directory,
)


HOSTILE_NAMES = [
    '../review-target/fighter.json',       # the reviewed sibling overwrite
    '..\\review-target\\fighter.json',     # same, Windows separators
    'a/../../escape.dat',                  # traversal in the middle
    '/etc/passwd',                         # absolute posix
    '\\\\server\\share\\payload.dat',      # UNC
    'C:/Windows/System32/payload.dll',     # drive letter
    'C:payload.dat',                       # drive-relative
    'sub/CON',                             # reserved Windows device
    'NUL.dat',                             # reserved stem with extension
    'COM1',
    'LPT9.txt',
    'trailing. /x.dat',                    # trailing space component
    'trailing./x.dat',                     # trailing dot component
    'bad\x00name.dat',                     # embedded NUL
    'ctrl\x01name.dat',                    # control character
    'stream.dat:zone.identifier',          # alternate data stream
    '..',
    '',
]


@pytest.mark.parametrize('name', HOSTILE_NAMES)
def test_hostile_member_names_are_rejected(name):
    assert not is_safe_member_name(name)
    with pytest.raises(UnsafeArchiveMember):
        member_parts(name)


@pytest.mark.parametrize('name,parts', [
    ('fighter.json', ('fighter.json',)),
    ('./fighter.json', ('fighter.json',)),
    ('costumes/PlMsBu.dat', ('costumes', 'PlMsBu.dat')),
    ('costumes\\PlMsBu.dat', ('costumes', 'PlMsBu.dat')),
    ('a/b/c/', ('a', 'b', 'c')),
    ('CONFIG.json', ('CONFIG.json',)),       # CONFIG is not CON
    ('COM10.dat', ('COM10.dat',)),           # only COM1..COM9 are devices
])
def test_ordinary_member_names_survive(name, parts):
    assert member_parts(name) == parts


def test_depth_cap():
    with pytest.raises(UnsafeArchiveMember):
        member_parts('/'.join(['d'] * 40))


def _zip_with(names, data=b'x'):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        for name in names:
            zf.writestr(name, data)
    buffer.seek(0)
    return zipfile.ZipFile(buffer)


def test_sibling_overwrite_is_refused_before_any_write(tmp_path):
    """The exact probe from the review: a member escaping into a sibling."""
    victim = tmp_path / 'review-target'
    victim.mkdir()
    (victim / 'fighter.json').write_text('original')
    destination = tmp_path / 'review'
    with _zip_with(['fighter.json', '../review-target/fighter.json']) as zf:
        with pytest.raises(UnsafeArchiveMember):
            extract_zip(zf, destination, budget=Budget())
    assert (victim / 'fighter.json').read_text() == 'original'
    # Preflight runs to completion first, so the good member was not written.
    assert not (destination / 'fighter.json').exists()


def test_symlink_members_are_refused(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        info = zipfile.ZipInfo('link')
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, '../../outside')
    buffer.seek(0)
    with zipfile.ZipFile(buffer) as zf:
        with pytest.raises(UnsafeArchiveMember):
            extract_zip(zf, tmp_path / 'out', budget=Budget())


def test_extraction_is_confined_and_complete(tmp_path):
    with _zip_with(['fighter.json', 'nested/deep/icon.png']) as zf:
        written = extract_zip(zf, tmp_path / 'out', budget=Budget())
    assert set(written) == {'fighter.json', 'nested/deep/icon.png'}
    assert (tmp_path / 'out' / 'nested' / 'deep' / 'icon.png').read_bytes() == b'x'


def test_content_overrides_replace_member_bytes(tmp_path):
    with _zip_with(['announcer.wav']) as zf:
        extract_zip(zf, tmp_path / 'out', budget=Budget(),
                    contents={'announcer.wav': b'normalized'})
    assert (tmp_path / 'out' / 'announcer.wav').read_bytes() == b'normalized'


def test_staged_directory_discards_everything_on_failure(tmp_path):
    final = tmp_path / 'character'
    with pytest.raises(RuntimeError):
        with staged_directory(final) as staging:
            (staging / 'fighter.json').write_text('partial')
            raise RuntimeError('boom')
    assert not final.exists()
    assert not any(p.name.startswith('.staging-') for p in tmp_path.iterdir())


def test_staged_extract_commits_into_a_fresh_folder(tmp_path):
    final = tmp_path / 'character'
    with _zip_with(['fighter.json', 'art/icon.png']) as zf:
        paths = extract_zip_to_new_directory(zf, final, budget=Budget())
    assert (final / 'fighter.json').exists() and (final / 'art' / 'icon.png').exists()
    assert paths['art/icon.png'] == final / 'art' / 'icon.png'


# ── cumulative budget ──────────────────────────────────────────────────────

def _bomb_zip(declared_size):
    """A ZIP whose central directory ADVERTISES a huge member. The payload is
    one byte; nothing here ever decompresses anything."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        zf.writestr('payload.bin', b'x')
    raw = bytearray(buffer.getvalue())
    buffer.seek(0)
    with zipfile.ZipFile(io.BytesIO(bytes(raw))) as probe:
        original = probe.infolist()[0].file_size
    # Patch every little-endian uncompressed-size field (local header + central
    # directory) from 1 to the advertised size.
    patched = bytes(raw).replace(original.to_bytes(4, 'little') * 1,
                                 declared_size.to_bytes(4, 'little'))
    return io.BytesIO(patched)


def test_budget_rejects_a_declared_decompression_bomb():
    budget = Budget(max_bytes=8 * 1024 * 1024)
    with zipfile.ZipFile(_bomb_zip(1024 * 1024 * 1024)) as zf:
        assert zf.infolist()[0].file_size == 1024 * 1024 * 1024
        with pytest.raises(ArchiveBudgetExceeded):
            preflight_zip(zf, budget=budget)


def test_budget_is_cumulative_across_layers():
    budget = Budget(max_bytes=1000)
    with _zip_with(['a.bin'], data=b'y' * 600) as zf:
        preflight_zip(zf, budget=budget)
    assert budget.used_bytes == 600
    with _zip_with(['b.bin'], data=b'y' * 600) as second:
        with pytest.raises(ArchiveBudgetExceeded):
            preflight_zip(second, budget=budget)


def test_budget_caps_member_count_and_nesting():
    budget = Budget(max_members=2, max_depth=1)
    with _zip_with(['a', 'b', 'c']) as zf:
        with pytest.raises(ArchiveBudgetExceeded):
            preflight_zip(zf, budget=budget)
    nesting = Budget(max_depth=1)
    with nesting.nested():
        with pytest.raises(ArchiveBudgetExceeded):
            with nesting.nested():
                pass


def test_budget_caps_wall_clock_time():
    budget = Budget(max_seconds=1)
    budget.started -= 5  # pretend this operation has been running for 5s
    with pytest.raises(ArchiveBudgetExceeded):
        budget.check_time()
    with pytest.raises(ArchiveBudgetExceeded):
        budget.charge_bytes(1)


def test_archive_limits_follow_the_remaining_allowance():
    budget = Budget(max_bytes=1000, max_members=10)
    budget.charge_bytes(400)
    budget.charge_members(4)
    limits = budget.archive_limits()
    assert limits.max_total_bytes == 600 and limits.max_entries == 6


def test_dangerous_members_are_reported():
    found = dangerous_members(['fighter.json', 'tools/setup.exe', 'run.BAT', 'x.dat'])
    assert found == ['tools/setup.exe', 'run.BAT']


# ── Windows filename identity (2026-09-22 re-review, 5) ───────────────────

@pytest.mark.parametrize('name', [
    'COM¹.dat',                 # a reserved device spelled with a superscript
    'LPT²',
    'a<b.dat',
    'a>b.dat',
    'a|b.dat',
    'a?b.dat',
    'a*b.dat',
    'quote".dat',
    'LONGFI~1.DAT',                  # an 8.3 short alias
])
def test_windows_namespace_tricks_are_rejected(name):
    assert not is_safe_member_name(name)


def test_two_members_that_are_the_same_file_on_windows_are_refused(tmp_path):
    """`fighter.json` and `FIGHTER.JSON` are one file; the second overwrote it."""
    with _zip_with(['fighter.json', 'FIGHTER.JSON']) as zf:
        with pytest.raises(UnsafeArchiveMember, match='same file'):
            extract_zip(zf, tmp_path / 'out', budget=Budget())
    assert not (tmp_path / 'out').exists()


def test_a_name_used_as_both_a_file_and_a_folder_is_refused(tmp_path):
    with _zip_with(['assets', 'assets/icon.png']) as zf:
        with pytest.raises(UnsafeArchiveMember, match='both a file and a folder'):
            extract_zip(zf, tmp_path / 'out', budget=Budget())


def test_a_windows_reparse_entry_is_a_link(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        info = zipfile.ZipInfo('junction')
        info.external_attr = 0x400        # FILE_ATTRIBUTE_REPARSE_POINT
        zf.writestr(info, 'target')
    buffer.seek(0)
    with zipfile.ZipFile(buffer) as zf:
        with pytest.raises(UnsafeArchiveMember, match='link'):
            extract_zip(zf, tmp_path / 'out', budget=Budget())


def test_the_refusal_names_the_entry_and_carries_no_local_path(tmp_path):
    with _zip_with(['../escape.dat']) as zf:
        with pytest.raises(UnsafeArchiveMember) as caught:
            extract_zip(zf, tmp_path / 'out', budget=Budget())
    message = str(caught.value)
    assert '../escape.dat' in message and 'walks up out of' in message
    assert str(tmp_path) not in message and 'C:' not in message
    detail = caught.value.as_dict()
    assert detail['member'] == '../escape.dat' and detail['action']


def test_a_hostile_member_name_is_escaped_in_the_message(tmp_path):
    with pytest.raises(UnsafeArchiveMember) as caught:
        member_parts('bad\x01name.dat')
    assert '\x01' not in str(caught.value) and 'bad?name.dat' in str(caught.value)


# ── the destination is not a link, and a commit never half-replaces ───────

def test_a_link_supplied_as_the_extraction_root_is_refused(tmp_path):
    real = tmp_path / 'real'
    real.mkdir()
    link = tmp_path / 'link'
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('this environment cannot create a directory symlink')
    with _zip_with(['fighter.json']) as zf:
        with pytest.raises(UnsafeArchiveMember, match='link rather than a real folder'):
            extract_zip(zf, link, budget=Budget())
    assert not (real / 'fighter.json').exists()


def test_an_existing_destination_is_refused_rather_than_half_replaced(tmp_path):
    """The item-by-item replacement could delete an original and stop there."""
    final = tmp_path / 'character'
    final.mkdir()
    (final / 'keep.json').write_text('original')
    with _zip_with(['keep.json', 'extra.dat']) as zf:
        with pytest.raises(DestinationExists):
            extract_zip_to_new_directory(zf, final, budget=Budget())
    assert (final / 'keep.json').read_text() == 'original'
    assert not (final / 'extra.dat').exists()
    assert not any(p.name.startswith('.staging-') for p in tmp_path.iterdir())


def test_reserving_a_destination_is_exclusive(tmp_path):
    final = tmp_path / 'character'
    assert reserve_directory(final) == final
    with pytest.raises(DestinationExists):
        reserve_directory(final)


def test_a_reserved_destination_commits_atomically(tmp_path):
    final = reserve_directory(tmp_path / 'character')
    with _zip_with(['fighter.json']) as zf:
        extract_zip_to_new_directory(zf, final, budget=Budget(), replace=True)
    assert (final / 'fighter.json').exists()
    assert not any(p.name.startswith('.staging-') for p in tmp_path.iterdir())


# ── budget identity: a second look at the same bytes is not a second cost ─

def test_the_same_archive_is_charged_once_however_often_it_is_walked():
    budget = Budget()
    with _zip_with(['a.bin'], data=b'y' * 1000) as zf:
        preflight_zip(zf, budget=budget)
        first = budget.used_bytes
        preflight_zip(zf, budget=budget)     # the identification pass
        preflight_zip(zf, budget=budget)     # and the import pass
    assert budget.used_bytes == first == 1000


def test_a_different_archive_is_still_charged():
    budget = Budget()
    with _zip_with(['a.bin'], data=b'y' * 1000) as first:
        preflight_zip(first, budget=budget)
    with _zip_with(['b.bin'], data=b'y' * 1000) as second:
        preflight_zip(second, budget=budget)
    assert budget.used_bytes == 2000
