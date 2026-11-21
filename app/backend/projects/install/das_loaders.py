"""
DAS loader files: what goes over a legal stage's root file when the Dynamic
Alternate Stages framework is installed into a project.

No loader ships as a file: each one keeps much of the game's own stage file
(the parameter tables, lights, Shy Guy's joint, and in Stadium's case the
transformation models), and nothing extractable from the game ships (owner,
2026-11-19). What ships is `<root>.xdelta` per stage, an xdelta3 (VCDIFF) patch
from the user's own vanilla NTSC 1.02 root (`GrPs.usd`, the others' `.dat`) to
the loader: only what DAS changed. It is applied here, the first time a DAS
install needs it, with the xdelta3 the app already ships for patches. Both ends
are checked by SHA-256, so a modded or other-revision source is never patched
and a bad result is never installed. The rebuilt loader is cached under
`utility/assets/das_loaders` (writable, never shipped), so later installs need
no source at all.

Making a patch (dev only, from the real loader and the 1.02 root):

    xdelta3 -e -9 -S none -A= -s <vanilla GrNBa.dat> <DAS GrNBa.dat> GrNBa.dat.xdelta

`-S none` keeps it decodable by every xdelta3 build the app ships; `-A=` keeps
local file names out of the header.
"""

import hashlib
import logging
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import file_retry
from core.config import PROJECT_ROOT, get_subprocess_args
from core.stages import DAS_LOADER_DIR

logger = logging.getLogger(__name__)

PATCH_SUFFIX = '.xdelta'

# Every loader ships as a patch: the vanilla root it applies to and the loader
# it must produce. Only NTSC 1.02 is accepted at setup (shared/routes/setup.py),
# so there is exactly one valid source.
PATCHED_LOADERS = {
    'GrIz.dat': {
        'source_sha256': 'a1f4c93bf47b159e132979cf041db84ac46a5e8b23e7b6e3d53ee09d8b2c30f4',
        'target_sha256': 'c914042eabca20e5e036505a246a6b8cf7b2b38b3b814b70351b39f12d9236b6',
    },
    'GrNBa.dat': {
        'source_sha256': '5b914b8f28c0dc16b1bafad68704e743d495ead41f0b954cca84479d6868a3b7',
        'target_sha256': '7bb7a8162a40c9497588359bd2b887295bf1e0ef18f0e980ecb7e024ae9d3414',
    },
    'GrNLa.dat': {
        'source_sha256': '2a295a733414fb65a7061a5c092144fb197570682562b87ba5567ff3f08abb02',
        'target_sha256': 'ddaa5e50eb51710348dfccbec9a219ce8a6aad050b2c3db690e91aaa2388d453',
    },
    'GrOp.dat': {
        'source_sha256': '44ef32a76216c3f47b79c430167e915953c3da0664f121c270be11fd5af2574d',
        'target_sha256': 'f17fd3967278a59a4c32860dc5762443fa4f4201cb2d70f10ae94cc2b5557bc4',
    },
    'GrPs.usd': {
        'source_sha256': 'aa740cfbbeced294f058449caca8ac0380532521dde06ca4a6dcc03080cf6a6d',
        'target_sha256': '12425150ae522d136c6f4408b28e2ced4b88afe08845c1ae274d1f48ccd8894c',
    },
    'GrSt.dat': {
        'source_sha256': '1ef0ccc51fc69bf2e06f55377111ec1b67e00438df0597bf6195c3032ae29f83',
        'target_sha256': 'ccb57dd8469dec41146d0ad719d0cabb1d850ea2231ff7edecf9866fffef500c',
    },
}

# Where a rebuilt loader is kept. Next to the other user-derived vanilla
# assets, outside the read-only bundle and outside every ship rule's stage.
DERIVED_LOADER_DIR = PROJECT_ROOT / 'utility' / 'assets' / 'das_loaders'

_lock = threading.Lock()


def loader_name(code):
    """Root file the DAS loader replaces: Stadium's English `.usd`, else `.dat`."""
    return f'{code}.usd' if code == 'GrPs' else f'{code}.dat'


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _matches(path, expected):
    try:
        return Path(path).is_file() and _sha256(path) == expected
    except OSError:
        return False


def _apply_patch(source, patch, target_sha256, out_path):
    """Decode `patch` against `source` into `out_path`. True only when the
    result is exactly the expected loader."""
    from projects.install.xdelta import require_xdelta_exe

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='das_loader_', dir=out_path.parent,
                                     ignore_cleanup_errors=True) as tmp:
        staged = Path(tmp) / out_path.name
        try:
            result = subprocess.run(
                [str(require_xdelta_exe()), '-d', '-f', '-s', str(source),
                 str(patch), str(staged)],
                capture_output=True, text=True, timeout=120, **get_subprocess_args())
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning('[das] xdelta3 could not run for %s: %s', patch.name, e)
            return False
        if result.returncode != 0:
            logger.warning('[das] xdelta3 failed for %s: %s', patch.name,
                           (result.stderr or result.stdout or '').strip()[-300:])
            return False
        if not _matches(staged, target_sha256):
            logger.warning('[das] %s produced an unexpected loader; not installed', patch.name)
            return False
        file_retry.replace(staged, out_path)
    return True


def _vanilla_from_iso(name):
    """The root file from the user's recorded vanilla ISO (one bounded read)."""
    try:
        from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
        return ensure_vanilla_ref(name)
    except Exception as e:  # noqa: BLE001 - one source among several
        logger.debug('[das] no vanilla %s from the recorded ISO: %s', name, e)
        return None


def resolve_das_loader(code, *, loader_dir=None, sources=()):
    """Path of a ready DAS loader for `code`, or None when it cannot be had.

    A loader present as a plain file in `loader_dir` is returned as is (only a
    test's synthetic framework has one; none ships). A patched one comes from
    the cache, or is rebuilt from the first source whose bytes are the vanilla
    root: `sources` in order (the caller's project copies), then the recorded
    vanilla ISO.
    """
    name = loader_name(code)
    loader_dir = Path(loader_dir) if loader_dir is not None else DAS_LOADER_DIR
    plain = loader_dir / name
    if plain.is_file():
        return plain

    spec = PATCHED_LOADERS.get(name)
    patch = loader_dir / (name + PATCH_SUFFIX)
    if spec is None or not patch.is_file():
        return None

    def candidates():
        yield from (Path(s) for s in sources if s)
        yield _vanilla_from_iso(name)  # only reached when no project copy fits

    cached = DERIVED_LOADER_DIR / name
    with _lock:
        if _matches(cached, spec['target_sha256']):
            return cached
        for source in candidates():
            if source is None or not _matches(source, spec['source_sha256']):
                continue
            if _apply_patch(source, patch, spec['target_sha256'], cached):
                logger.info('[das] rebuilt %s from %s', name, source)
                return cached
    logger.warning('[das] %s needs the vanilla %s from your own game, and none was found',
                   name, name)
    return None


def has_das_loader(code, project_files, *, loader_dir=None):
    """True when the project's root for `code` is the DAS loader: the bytes the
    shipped patch rebuilds, or a plain loader file where one is present. A
    stage whose install found no vanilla source kept its own root, and a
    stage folder alone does not make DAS work, so both answer False."""
    root = Path(project_files) / loader_name(code)
    if not root.is_file():
        return False
    spec = PATCHED_LOADERS.get(root.name)
    if spec is not None and _matches(root, spec['target_sha256']):
        return True
    loader_dir = Path(loader_dir) if loader_dir is not None else DAS_LOADER_DIR
    plain = loader_dir / root.name
    try:
        return plain.is_file() and _sha256(plain) == _sha256(root)
    except OSError:
        return False


def install_das_loader(code, project_files, *, loader_dir=None):
    """Write the DAS loader over `project_files/<root>`. Returns the loader's
    path, or None (the root file is then left untouched).

    The project's own vanilla copies are tried before the recorded ISO: the
    root itself before DAS replaced it, and `<code>/vanilla.dat` after.
    """
    project_files = Path(project_files)
    root = project_files / loader_name(code)
    loader = resolve_das_loader(
        code, loader_dir=loader_dir,
        sources=(root, project_files / code / 'vanilla.dat'))
    if loader is None:
        return None
    file_retry.retry_locked(shutil.copy2, loader, root)
    return loader
