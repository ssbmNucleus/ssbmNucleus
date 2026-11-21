"""Render stage variants directly from their DATs, using the CSP render host.

No ISO build and no Dolphin session: one warm `--stage-render` worker draws the
whole stage offline in ~1-2s. Two callers share the framing table below:

* the ISO scan, which previews each variant as it lands in the vault
  (``render_imported_stage_previews``);
* the vault's bulk "Stage screenshots" flow, which re-renders any selection of
  already-stored variants straight out of their zips (``render_vault_variants``).

A preview failure is never fatal -- the imported stage stays, and the bulk flow
reports a per-variant reason instead of losing the whole batch.
"""
import logging
import re
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote

from PIL import Image

import file_retry
from core.config import HSDRAW_EXE
from core.stages import ALL_STAGES
from shared.rendering.csp_pool import CspRenderPool

logger = logging.getLogger(__name__)

# Match-start framing calibrated against the in-game stage captures. Group
# filters exclude Battlefield's adventure geometry and Stadium transformations.
_FRAMING = {
    'GrNBa': ((0, 31.7, 189.5), (0, 25.7, 0), (0, 1, 3, 6)),
    'GrNLa': ((0, 10, 237.1), (0, 4, 0), None),
    'GrOp': ((0, 30.2, 214.1), (0, 24.2, 0), None),
    'GrSt': ((0, 25.5, 201.7), (0, 19.5, 0), None),
    'GrIz': ((0, 25.9, 175.3), (0, 19.9, 0), None),
    'GrPs': ((0, 61, 310), (0, 4, 0), (0, 1, 2, 5)),
}
# Only these stages have a hand-calibrated camera. Every other vault stage (the
# 'replace' slot stages) is reported as unsupported rather than drawn from an
# arbitrary viewpoint.
SUPPORTED_STAGE_CODES = frozenset(_FRAMING)
PREVIEW_SIZE = (768, 432)
JOB_TIMEOUT = 45

# GrPs1..4 are Stadium's transformation models, not the stage's normal look.
# Matched as a SUFFIX: the vault holds them under descriptive names too
# ("Fire Trans GrPs1.dat"), either as sidecars or as variants of their own.
_STADIUM_FORM_RE = re.compile(r'grps[1-4]\.(?:dat|usd)$')


def stage_render_args(stage_code, dat_path, output_path):
    eye, interest, groups = _FRAMING[stage_code]
    args = ['--stage-render', str(dat_path), str(output_path),
            '--eye', ','.join(map(str, eye)),
            '--interest', ','.join(map(str, interest)),
            '--fov', '46.5', '--frame', '60',
            '--size', f'{PREVIEW_SIZE[0]}x{PREVIEW_SIZE[1]}']
    if groups is not None:
        args.extend(['--groups', ','.join(map(str, groups))])
    return args


def _verified_png(path):
    """Read a finished render, refusing anything that isn't the PNG we asked
    for -- a truncated or half-written native output must never be saved or
    shown as a preview."""
    with Image.open(path) as image:
        image.load()
        if image.format != 'PNG' or image.size != PREVIEW_SIZE:
            raise ValueError('Invalid stage preview image')
    return Path(path).read_bytes()


def stage_member_in_archive(names, stage_code):
    """The member of a vault variant zip holding the stage's normal root model.

    Stadium's per-transformation sidecars (GrPs1..4) are separate models and
    never the preview subject. A multi-stage archive is matched by name so a
    variant that also carries another stage's file can't be drawn from it.
    """
    files = [n for n in names
             if not n.endswith('/') and n.lower().endswith(('.dat', '.usd'))]
    if stage_code == 'GrPs':
        files = [n for n in files
                 if not _STADIUM_FORM_RE.search(Path(n).name.lower())]
    if not files:
        return None
    named = [n for n in files if stage_code.lower() in Path(n).name.lower()]
    return (named or files)[0]


def _missing_member_reason(names, stage_code):
    """Why an archive yielded nothing to render. A Stadium transformation kept
    as a variant of its own is a real thing in the vault, and it is not a stage
    -- at the stage camera it renders as an empty frame, so say so instead of
    blaming the renderer."""
    if stage_code == 'GrPs' and any(_STADIUM_FORM_RE.search(Path(n).name.lower())
                                    for n in names):
        return 'a Stadium transformation form has no stage preview'
    return 'no stage file inside the variant archive'


def render_imported_stage_previews(jobs, das_root):
    """Jobs are (DetectedVariant, saved metadata entry) pairs. Return URLs
    keyed by (vault folder, id); the caller commits metadata after rendering.
    Existing screenshots are preserved. All native work stays outside the vault
    metadata lock, with the pool's startup/job deadlines bounding each request.
    """
    previews = {}
    if not jobs:
        return previews
    try:
        with CspRenderPool(HSDRAW_EXE, workers=1, job_timeout=JOB_TIMEOUT) as pool:
            for variant, entry in jobs:
                folder = Path(das_root) / variant.folder
                filename = f"{entry['id']}_screenshot.png"
                dest = folder / filename
                try:
                    if not dest.exists():
                        # Same filesystem as the final PNG for an atomic replace.
                        with TemporaryDirectory(prefix='.preview-', dir=folder) as temp:
                            output = Path(temp) / 'stage.png'
                            if not pool.render(stage_render_args(variant.stage_code, variant.path, output)):
                                raise RuntimeError('Stage renderer did not produce a preview')
                            _verified_png(output)
                            file_retry.replace(output, dest)
                    previews[(variant.folder, entry['id'])] = (
                        f'/storage/das/{quote(variant.folder)}/{quote(filename)}')
                except Exception:
                    logger.warning('Stage preview failed for %s / %s',
                                   variant.stage_code, entry['id'], exc_info=True)
    except Exception:
        logger.warning('Stage preview renderer unavailable', exc_info=True)
    return previews


def _vault_variant_png(variant, das_root, workdir, pool, stop):
    """Render ONE stored variant. Returns (png bytes, None) or (None, reason)."""
    if stop is not None and stop.is_set():
        return None, 'cancelled'
    stage_code = variant.get('stageCode')
    if stage_code not in SUPPORTED_STAGE_CODES:
        return None, 'no camera calibrated for this stage yet'
    variant_id = variant.get('variantId') or ''
    if (not variant_id or '/' in variant_id or '\\' in variant_id
            or Path(variant_id).name != variant_id):
        return None, 'invalid variant id'

    zip_path = Path(das_root) / ALL_STAGES[stage_code]['folder'] / f'{variant_id}.zip'
    if not zip_path.is_file():
        return None, 'variant archive is missing from the vault'

    workdir.mkdir(parents=True, exist_ok=True)
    dat = workdir / f'{stage_code}.dat'
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        member = stage_member_in_archive(names, stage_code)
        if member is None:
            return None, _missing_member_reason(names, stage_code)
        dat.write_bytes(archive.read(member))

    output = workdir / 'preview.png'
    if not pool.render(stage_render_args(stage_code, dat, output)):
        return None, 'the stage renderer could not draw this variant'
    return _verified_png(output), None


def render_vault_variants(variants, das_root, *, stop=None, work_dir=None):
    """Render previews for variants already stored in the vault.

    `variants` are dicts with at least {stageCode, variantId}. Yields
    (variant, png bytes or None, reason or None) in the given order as each
    render finishes, so the caller can stream results while the rest of the
    batch is still drawing. Nothing is written to the vault -- the caller
    decides what to keep. Set `stop` (a threading.Event) to abandon whatever
    has not started yet.

    One worker, like the bulk CSP retake: jobs are submitted sequentially, so
    extra --csp-server GL contexts add no throughput and their GPU pressure is
    what triggers HSDRawViewer's blank-render mode (shared/rendering/csp_concurrency.py).
    """
    variants = list(variants)
    if not variants:
        return
    with TemporaryDirectory(prefix='stage-render-', dir=work_dir) as temp:
        with CspRenderPool(HSDRAW_EXE, workers=1, job_timeout=JOB_TIMEOUT) as pool:
            for index, variant in enumerate(variants):
                try:
                    png, reason = _vault_variant_png(
                        variant, das_root, Path(temp) / str(index), pool, stop)
                except Exception as exc:  # one bad variant mustn't stop the batch
                    logger.warning('Stage render failed for %s',
                                   variant.get('variantId'), exc_info=True)
                    png, reason = None, f'{type(exc).__name__}: {exc}'
                yield variant, png, reason
