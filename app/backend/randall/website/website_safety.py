"""Read-only Slippi preflight for the exact downloaded archive, before vault writes.

Every layer of the download -- the outer archive, each nested archive, and the
package converters the importer will later run -- spends ONE cumulative budget
(see core.safe_extract). Before the 2026-09-22 security review this function
counted the outer ZIP's declared expansion and then returned early for anything
that classified as a package, so a nested ZIP carrying a `fighter.yml` made the
outer archive a "package" and bought the payload inside it a complete exemption
from the byte, member and nesting limits. There are no exemptions now: package
archives skip the costume *inspection* (their costumes use a different
importer) but never the resource budget.
"""
import hashlib
import shutil
import tempfile
import zipfile
from pathlib import Path

MAX_EXPANDED = 512 * 1024 * 1024
MAX_ENTRIES = 10000
LIMIT_MESSAGE = 'Mod archive exceeds the chat safety-check limit. Nothing was imported.'


def download_budget():
    """The cumulative budget for one chat download, shared by preflight+import."""
    from vault.importing.unified import detection
    from core.safe_extract import new_budget
    return new_budget(max_bytes=MAX_EXPANDED, max_members=MAX_ENTRIES,
                      max_depth=detection.MAX_CONTAINER_DEPTH + 1, max_seconds=180.0,
                      message=LIMIT_MESSAGE)


def inspect_archive(path, cancelled=lambda: False, mod_type=None, budget=None):
    # The importer's own classifier, container rules, costume detector and
    # Slippi check -- the same functions vault/routes/import_unified/routes.py
    # imports -- so this walks the archive exactly as the import will.
    from vault.importing.unified import detection
    from vault.importing import character_detector
    from core.rar_tools import rar_to_temp_zip
    from core.safe_archive import safe_extract_7z
    from core.safe_extract import preflight_zip
    import dat_processor  # on sys.path via core.config (SERVICES_DIR)
    budget = budget or download_budget()
    unsafe, checked, cache = [], 0, {}

    def scan(archive_path, label='', depth=0, validate_only=False, occurrence=''):
        nonlocal checked
        if cancelled():
            raise ValueError('Download cancelled. Nothing was imported.')
        with zipfile.ZipFile(archive_path) as archive:
            # Charges this layer's declared expansion and member count against
            # the whole operation, and refuses hostile member names, BEFORE any
            # member of it is read.
            preflight_zip(archive, budget=budget, occurrence=occurrence)
            # Follow the same package and container boundaries as the importer.
            # The classifier looks inside nested archives too, so it is given
            # the SAME ancestry this scan is using; otherwise the two passes
            # charge the same archive twice.
            kind = detection.detect_content_type(str(archive_path), 'website-mod.zip',
                                                 deep=False, budget=budget,
                                                 occurrence=occurrence)['type']
            package = kind in detection._PACKAGE_TYPES
            # Explicit protocol effects do not enter the costume importer, and a
            # package's costumes are read by the package converter -- but their
            # nested archives still have to be validated, so only the costume
            # inspection below is skipped.
            skip_costumes = validate_only or package or mod_type == 'effect'

            inner_archives = detection._list_inner_archives(str(archive_path))
            if inner_archives and depth >= budget.max_depth:
                # Silently stopping here is how a deeper header-only bomb
                # reached the real importer with nothing having looked at it
                # (2026-09-22 re-review, 1). What cannot be inspected is
                # refused, not waved through.
                raise ValueError(
                    'This download nests archives deeper than Nucleus checks from chat '
                    f'({budget.max_depth} levels), so its contents cannot be verified. '
                    'Nothing was imported. Download it from the website and import the '
                    'files inside it.')
            if inner_archives:
                for member in inner_archives:
                    suffix = Path(member).suffix.lower()
                    with tempfile.TemporaryDirectory(prefix='nucleus-safety-') as temporary:
                        child = Path(temporary) / ('archive' + suffix)
                        child.write_bytes(archive.read(member))
                        bounds = budget.archive_limits()
                        if suffix == '.7z':
                            if not detection.HAS_7Z:
                                raise ValueError('Could not check the nested 7z archive. Nothing was imported.')
                            directory = Path(temporary) / 'unpacked'
                            with detection._py7zr().SevenZipFile(child, 'r') as seven:
                                safe_extract_7z(seven, directory, limits=bounds)
                            child = Path(temporary) / 'archive.zip'
                            with zipfile.ZipFile(child, 'w') as output:
                                for file in directory.rglob('*'):
                                    if file.is_file():
                                        output.write(file, file.relative_to(directory).as_posix())
                        elif suffix == '.rar':
                            # The importer now opens nested RARs, so this check
                            # has to look inside them too or it would wave
                            # through costumes that really do get imported.
                            converted = rar_to_temp_zip(child, limits=bounds)
                            if not converted:
                                raise ValueError('Could not check the nested RAR archive. Nothing was imported.')
                            child = Path(temporary) / 'archive.zip'
                            shutil.move(converted, child)
                        with budget.nested():
                            scan(child, label + member + ' / ', depth + 1,
                                 validate_only=skip_costumes,
                                 occurrence=f'{occurrence}!{member}')

            if skip_costumes:
                return
            for costume in character_detector.detect_character_from_zip(str(archive_path)) or []:
                if cancelled():
                    raise ValueError('Download cancelled. Nothing was imported.')
                raw = archive.read(costume['dat_file'])
                digest = hashlib.sha256(raw).hexdigest()
                if digest not in cache:
                    with tempfile.TemporaryDirectory(prefix='nucleus-safety-') as temporary:
                        dat = Path(temporary) / 'costume.dat'
                        dat.write_bytes(raw)
                        cache[digest] = dat_processor.validate_for_slippi(str(dat), auto_fix=False)
                validation = cache[digest]
                checked += 1
                if not validation.get('slippi_safe'):
                    unsafe.append({'name': (label + costume['dat_file'])[:500],
                                   'character': costume['character'], 'color': costume['color'],
                                   'unverified': bool(validation.get('error'))})

    scan(path)
    return {'unsafe_costumes': unsafe, 'checked_count': checked,
            'archive_hash': hashlib.sha256(Path(path).read_bytes()).hexdigest()}
