import io
import stat
import zipfile

import pytest

from core.safe_archive import ArchiveLimits, safe_extract_zip


def test_safe_zip_extracts_regular_files(tmp_path):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("folder/mod.dat", b"melee")
    with zipfile.ZipFile(io.BytesIO(payload.getvalue())) as archive:
        safe_extract_zip(archive, tmp_path)
    assert (tmp_path / "folder" / "mod.dat").read_bytes() == b"melee"


@pytest.mark.parametrize("name", ["../escape.txt", "/absolute.txt", "C:/drive.txt"])
def test_safe_zip_rejects_escaping_paths(tmp_path, name):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr(name, b"bad")
    with zipfile.ZipFile(io.BytesIO(payload.getvalue())) as archive:
        with pytest.raises(ValueError):
            safe_extract_zip(archive, tmp_path)
    assert not (tmp_path.parent / "escape.txt").exists()


def test_safe_zip_rejects_symlinks(tmp_path):
    payload = io.BytesIO()
    link = zipfile.ZipInfo("link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr(link, "../outside")
    with zipfile.ZipFile(io.BytesIO(payload.getvalue())) as archive:
        with pytest.raises(ValueError, match="links"):
            safe_extract_zip(archive, tmp_path)


def test_safe_zip_enforces_total_size_before_writing(tmp_path):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("one.bin", b"123")
        archive.writestr("two.bin", b"456")
    limits = ArchiveLimits(max_total_bytes=5)
    with zipfile.ZipFile(io.BytesIO(payload.getvalue())) as archive:
        with pytest.raises(ValueError, match="total"):
            safe_extract_zip(archive, tmp_path, limits=limits)
    assert list(tmp_path.iterdir()) == []


