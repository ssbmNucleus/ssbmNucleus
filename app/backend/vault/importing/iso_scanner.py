"""
ISO scanner - background scan pipeline for ripping new costume skins from ISOs.

A callable module that emits progress callbacks, generates CSPs/DATs per
candidate skin into a per-job work directory, and exposes the result grouped
by character so a UI can render selectable thumbnails.

This module is the scan job and its pipeline (extract each ISO, find the
costumes, render a portrait per candidate, pair Ice Climbers, finish). What it
reads off a disc lives beside it: iso_costume_files.py (which files are
costumes), iso_known_hashes.py (vault and vanilla duplicates),
iso_slot_art.py (the disc's own stock icons and CSS portraits) and
iso_ice_climbers.py (Popo/Nana pairing).
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import file_retry
from core.config import OUTPUT_PATH
from core import jobs

# These come from PROCESSOR_DIR / SERVICES_DIR which are already on sys.path
# via core.config import side effects.
from detect_character import DATParser
from generate_csp import generate_csp
from shared.rendering.csp_pool import active_pool
from shared.rendering.csp_concurrency import csp_workers, staggered_launch
from vault.importing.iso_costume_files import (SKIP_CHARACTERS, _character_from_filename,
    _is_custom_fighter_file, _is_character_file, _ensure_dat_ext)
from vault.importing.iso_known_hashes import (_md5_file, _load_vault_hashes,
    _load_vanilla_hashes, _slippi_fixed_hash)
from vault.importing.iso_slot_art import _slot_asset, _build_stock_maps, _build_csp_maps
from vault.importing.iso_ice_climbers import _ic_key, _pair_ice_climbers

logger = logging.getLogger(__name__)


SCAN_WORK_ROOT = OUTPUT_PATH / "iso_scan"
SCAN_CLEANUP_MAX_AGE_SECONDS = int(os.environ.get('NUCLEUS_ISO_SCAN_MAX_AGE_SECONDS', str(12 * 60 * 60)))


def _safe_scan_job_dir(job_id: str) -> Optional[Path]:
    """Return the direct child work dir for job_id, rejecting traversal."""
    if not job_id:
        return None
    job_name = Path(job_id).name
    if job_name != job_id:
        return None
    root = SCAN_WORK_ROOT.resolve()
    candidate = (SCAN_WORK_ROOT / job_id).resolve()
    if candidate.parent != root:
        return None
    return candidate


def _dir_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def cleanup_stale_jobs(max_age_seconds: Optional[int] = SCAN_CLEANUP_MAX_AGE_SECONDS) -> dict:
    """Remove inactive ISO scan work dirs old enough to be considered stale."""
    SCAN_WORK_ROOT.mkdir(parents=True, exist_ok=True)
    now = time.time()
    removed: list[str] = []
    bytes_removed = 0
    active_ids = {r['id'] for r in jobs.list_jobs(kind=SCAN_KIND, active=True)}

    for child in SCAN_WORK_ROOT.iterdir():
        if not child.is_dir() or child.name in active_ids:
            continue
        safe_child = _safe_scan_job_dir(child.name)
        if safe_child is None or safe_child != child.resolve():
            continue
        try:
            age_seconds = now - child.stat().st_mtime
        except OSError:
            continue
        if max_age_seconds is not None and max_age_seconds > 0 and age_seconds < max_age_seconds:
            continue
        try:
            bytes_removed += _dir_size(child)
            shutil.rmtree(child)
            removed.append(child.name)
        except Exception as e:
            logger.warning(f"[iso-scan][cleanup] failed to remove {child}: {e}")

    if removed:
        logger.info(
            f"[iso-scan][cleanup] removed {len(removed)} stale job dir(s), "
            f"{bytes_removed} bytes"
        )

    return {'removed': len(removed), 'bytes_removed': bytes_removed, 'job_ids': removed}

# Small scan portraits finish quickly once a renderer is warm. Limit default
# GL startups to four; more contexts delayed a 51-portrait batch from 10s to
# 21s. Still bounded by CPU count, with MEX_CSP_PARALLELISM as an override.
CSP_PARALLELISM = csp_workers(default_limit=4)

# Launch staggering (why it exists: HSDRawViewer.Program.RunCSPGeneration has
# two hardcoded Thread.Sleep barriers that don't reliably cover its real
# WinForms/OpenGL init when N instances start at once — the blank-render /
# T-pose pattern seen on Zelda, Mewtwo, Falco) now lives in
# shared/rendering/csp_concurrency.staggered_launch, shared with the HD-CSP cache and
# the texture-pack export. Same MEX_CSP_LAUNCH_STAGGER env var.

SCAN_KIND = 'iso_scan'


def _clean_scan(name, value):
    if name == 'work_dir':
        path = Path(value)
        if path == _safe_scan_job_dir(path.name) and path.exists():
            shutil.rmtree(path)


jobs.register_kind(SCAN_KIND, label='ISO scan', cleanup=_clean_scan)


@dataclass
class CandidateSkin:
    key: str
    character: str
    costume_code: str
    dat_path: str
    csp_path: Optional[str]
    stock_path: Optional[str]
    dat_hash: str
    source_iso: str
    # For Ice Climbers: the paired Nana DAT (when the primary is Popo) or
    # Popo DAT (when the primary is Nana). None for non-paired skins.
    paired_dat_path: Optional[str] = None
    paired_costume_code: Optional[str] = None


@dataclass
class ScanCandidates:
    job: jobs.Job
    iso_paths: list[str]
    work_dir: Path
    stats: dict = field(default_factory=lambda: {
        'existing': 0, 'vanilla': 0, 'dupes': 0,
        'slippi_matched': 0, 'data_mod': 0, 'custom_fighter': 0,
        'unknown': 0, 'errors': 0, 'preview_failed': 0,
        'stock_icons': 0,
        'total_files': 0,
    })
    candidates: dict[str, list[CandidateSkin]] = field(default_factory=dict)
    skipped_vault: list[dict] = field(default_factory=list)
    preview_failures: list[dict] = field(default_factory=list)
    extraction_failures: list[str] = field(default_factory=list)

    def to_dict(self, csp_url_base: str) -> dict:
        chars = {}
        for char, skins in self.candidates.items():
            chars[char] = [
                {
                    'key': s.key,
                    'costume_code': s.costume_code,
                    'csp_url': f"{csp_url_base}/{s.key}/csp" if s.csp_path else None,
                    'source_iso': s.source_iso,
                    'dat_hash': s.dat_hash[:12],
                }
                for s in skins
            ]
        return {
            'stats': self.stats,
            'preview_failures': self.preview_failures,
            'extraction_failures': self.extraction_failures,
            'characters': chars,
            'candidates': {char: [asdict(s) for s in skins]
                           for char, skins in self.candidates.items()},
            'skipped_vault': self.skipped_vault,
            'total_new': sum(len(v) for v in self.candidates.values()),
        }


def _record_vault_match(job: ScanCandidates, preview: Optional[dict], source: str):
    if preview and not any(
        item['character'] == preview['character'] and item['id'] == preview['id']
        for item in job.skipped_vault
    ):
        job.skipped_vault.append({**preview, 'source_iso': source})


def _validate_csp_preview(path: str | Path) -> tuple[bool, str]:
    """Reject renderer outputs that would create blank scan tiles.

    HSDRawViewer can occasionally produce a PNG even when the model viewport did
    not actually render. The importer should not surface those as selectable
    skins, because users then import entries that looked blank in the scan grid.
    Keep this conservative: reject fully transparent/tiny renders and solid
    full-frame images, but allow flat silhouettes such as Mr. Game & Watch.
    """
    try:
        from PIL import Image, ImageStat

        with Image.open(path) as image:
            rgba = image.convert('RGBA')
            width, height = rgba.size
            if width <= 0 or height <= 0:
                return False, 'empty_image'

            alpha = rgba.getchannel('A')
            alpha_hist = alpha.histogram()
            visible_pixels = sum(alpha_hist[17:])
            total_pixels = width * height
            min_visible = max(96, int(total_pixels * 0.03))
            if visible_pixels < min_visible:
                return False, 'transparent'

            mask = alpha.point(lambda a: 255 if a > 16 else 0)
            bbox = mask.getbbox()
            if not bbox:
                return False, 'transparent'
            bbox_w = bbox[2] - bbox[0]
            bbox_h = bbox[3] - bbox[1]
            if bbox_w < max(8, int(width * 0.12)) or bbox_h < max(8, int(height * 0.12)):
                return False, 'tiny_render'

            # Blank renderer failures can come back as one opaque solid frame.
            # Do not reject low-variance silhouettes unless they fill almost
            # the entire CSP frame.
            visible_ratio = visible_pixels / total_pixels
            rgb_var = sum(ImageStat.Stat(rgba.convert('RGB'), mask).var)
            if visible_ratio > 0.92 and rgb_var < 4:
                return False, 'solid_frame'
    except Exception as e:
        return False, f'invalid_png:{e}'

    return True, 'ok'


def _extract_iso(iso_path: Path, dest_dir: Path) -> bool:
    """Extract one ISO into dest_dir with the native Python FST reader.
    Returns True on success; False (with a logged reason) if the file table
    could not be read or held no files."""
    try:
        from shared.vanilla_extract.vanilla_refs import extract_iso_files
        if extract_iso_files(iso_path, dest_dir) > 0:
            return True
        logger.warning(f"could not read the ISO file table for {iso_path.name}: no files extracted")
    except Exception as e:
        logger.warning(f"could not read the ISO file table for {iso_path.name}: {e}")
    return False


# ---------- Public API ----------

def start_scan(iso_paths: list[str]) -> str:
    """Start a shared job; completed candidate files stay until dismissed."""
    cleanup_stale_jobs()
    return jobs.start(SCAN_KIND, lambda job: run_scan(job, iso_paths),
                      params={'iso_paths': list(iso_paths)})


def run_scan(job, iso_paths):
    work_dir = SCAN_WORK_ROOT / job.id
    job.own('work_dir', str(work_dir.resolve()))
    work_dir.mkdir(parents=True, exist_ok=True)
    scan = ScanCandidates(job, list(iso_paths), work_dir)
    _run_scan(scan)
    job.check_stop()
    result = scan.to_dict(f'/api/mex/iso-scan/{job.id}/csp')
    job.release('work_dir')
    return result


def scan_candidates(record):
    return [CandidateSkin(**skin)
            for skins in (record.get('result') or {}).get('candidates', {}).values()
            for skin in skins]


def delete_scan_files(job_id: str) -> bool:
    record = jobs.get(job_id)
    if record and (record['kind'] != SCAN_KIND or record['status'] in jobs.ACTIVE):
        return False
    work_dir = _safe_scan_job_dir(job_id)
    if work_dir is None or not work_dir.exists():
        return False
    shutil.rmtree(work_dir)
    return True


# ---------- Scan pipeline ----------

def _progress(scan: ScanCandidates, phase: str, message: str, percent: int,
              *, current: Optional[int] = None, total: Optional[int] = None):
    scan.job.progress(percent / 100, message, phase=phase, phase_current=current,
                      phase_total=total, stats=dict(scan.stats))


def _run_scan(job: ScanCandidates):
    logger.info(
        f"[iso-scan] === job {job.job.id} START === "
        f"isos={len(job.iso_paths)} workers={CSP_PARALLELISM}"
    )
    for p in job.iso_paths:
        logger.info(f"[iso-scan]   ISO: {p}")
    # --- Phase 1: extract ---
    extract_root = job.work_dir / "extracted"
    extract_root.mkdir(exist_ok=True)

    extracted_count = 0
    for i, iso_path_str in enumerate(job.iso_paths):
        if job.job.should_stop():
            break
        iso_path = Path(iso_path_str)
        pct = int(5 + (i / max(1, len(job.iso_paths))) * 15)
        _progress(job, 'extracting',
              f"Extracting {iso_path.name} ({i+1}/{len(job.iso_paths)})", pct,
              current=i + 1, total=len(job.iso_paths))
        dest = extract_root / iso_path.stem
        if dest.exists():
            # Reuse existing extraction
            extracted_count += 1
            continue
        ok = _extract_iso(iso_path, dest)
        if not ok:
            shutil.rmtree(dest, ignore_errors=True)
            job.stats['errors'] += 1
            job.extraction_failures.append(iso_path.name)
        else:
            extracted_count += 1

    if job.job.should_stop():
        job.job.check_stop()
        return

    if not extracted_count:
        failed = ', '.join(job.extraction_failures)
        raise ValueError(f"Could not extract any selected ISO: {failed}. Check that the files are valid, unpacked ISO/GCM images.")

    # --- Phase 2: walk + hash filter ---
    _progress(job, 'scanning', "Loading vault & vanilla hashes...", 22)
    vault_hashes = _load_vault_hashes()
    vanilla_hashes = _load_vanilla_hashes()
    stock_maps = _build_stock_maps(extract_root, job.work_dir / "stocks")
    job.stats['stock_icons'] = sum(len(v) for v in stock_maps.values())
    csp_maps = _build_csp_maps(extract_root, job.work_dir / "css_csps")
    job.stats['css_csps'] = sum(len(v) for v in csp_maps.values())

    all_files: list[tuple[str, str]] = []  # (path, source_iso_stem)
    for iso_dir in extract_root.iterdir():
        if not iso_dir.is_dir():
            continue
        for root, _, files in os.walk(iso_dir):
            for f in files:
                fp = os.path.join(root, f)
                if _is_character_file(fp):
                    all_files.append((fp, iso_dir.name))

    job.stats['total_files'] = len(all_files)

    # Each pre-candidate is a dict to keep things readable.
    pre_candidates: list[dict] = []
    seen_hashes: set[str] = set()

    for i, (fp, source) in enumerate(all_files):
        if job.job.should_stop():
            break
        if i % 100 == 0:
            pct = 22 + int((i / max(1, len(all_files))) * 30)
            _progress(job, 'scanning',
                  f"Hashing files {i}/{len(all_files)}", pct, current=i, total=len(all_files))
        try:
            file_hash = _md5_file(fp)
        except Exception:
            job.stats['errors'] += 1
            continue

        if file_hash in vanilla_hashes:
            job.stats['vanilla'] += 1
            continue
        if file_hash in vault_hashes:
            job.stats['existing'] += 1
            _record_vault_match(job, vault_hashes[file_hash], source)
            continue
        if file_hash in seen_hashes:
            job.stats['dupes'] += 1
            continue
        seen_hashes.add(file_hash)

        # Custom-fighter costume slots (PlQp*, ...) are NOT vanilla-char
        # skins: their content symbols still say e.g. Fox (cloned from
        # Fox), so the symbol-based identification below would misfile
        # them. They're handled by the custom-characters scan instead.
        if _is_custom_fighter_file(fp):
            job.stats['custom_fighter'] += 1
            logger.info(
                f"[iso-scan][id] CUSTOM_FIGHTER {os.path.basename(fp)} — "
                "non-vanilla Pl code; belongs to a custom character"
            )
            continue

        # Identify character
        try:
            parser = DATParser(fp)
            parser.read_dat()
            if not parser.is_character_costume():
                job.stats['data_mod'] += 1
                logger.debug(
                    f"[iso-scan][id] DATA_MOD {os.path.basename(fp)} — no Ply*5K symbol"
                )
                continue
            character, symbol = parser.detect_character()
            # Filename-prefix override: PlBoXX.dat and PlClXX.dat both
            # carry an "ftDataBoy" symbol, so symbol-based detection tags
            # wireframes as Young Link. The 2-char filename prefix is the
            # authoritative signal — trust it when it disagrees.
            filename_character = _character_from_filename(fp)
            if filename_character and filename_character != character:
                logger.warning(
                    f"[iso-scan][id] OVERRIDE {os.path.basename(fp)}: "
                    f"symbol={symbol!r} said {character!r} but filename "
                    f"prefix says {filename_character!r} — trusting filename"
                )
                character = filename_character
            if not character:
                job.stats['unknown'] += 1
                root_syms = [n.get('symbol') for n in parser.root_nodes][:5]
                logger.warning(
                    f"[iso-scan][id] UNKNOWN {os.path.basename(fp)} — "
                    f"root symbols: {root_syms}"
                )
                continue
            costume_code = parser.get_character_filename() or os.path.basename(fp)
        except Exception as e:
            job.stats['errors'] += 1
            logger.warning(
                f"[iso-scan][id] ERROR parsing {os.path.basename(fp)}: {e}"
            )
            continue

        # Drop characters the user has marked uninteresting.
        if character in SKIP_CHARACTERS:
            logger.info(
                f"[iso-scan][id] SKIP {character} ({costume_code}) — in SKIP_CHARACTERS"
            )
            continue

        logger.info(
            f"[iso-scan][id] {character:22} code={costume_code!r:14} "
            f"symbol={symbol!r} src={source!r}"
        )
        pre_candidates.append({
            'path': fp, 'hash': file_hash,
            'character': character, 'costume_code': costume_code,
            'source_iso': source, 'symbol': symbol,
            'stock_path': _slot_asset(stock_maps.get(source, {}), fp, costume_code),
            'csp_override': _slot_asset(csp_maps.get(source, {}), fp, costume_code),
        })

    if job.job.should_stop():
        job.job.check_stop()
        return

    # --- Phase 2b: pair Ice Climbers Popo + Nana by (source_iso, color suffix) ---
    # Pool of EVERY Nana DAT in each ISO (incl. vanilla ones filtered out as
    # candidates) so a modded Popo with an unchanged Nana still gets the
    # correct same-colour Nana in its CSP instead of rendering solo.
    nana_pool: dict[tuple, str] = {}
    for fp, source in all_files:
        if os.path.basename(fp).startswith('PlNn'):
            colour, slot = _ic_key({'path': fp})
            nana_pool.setdefault((source, colour, slot), fp)
    candidates = _pair_ice_climbers(pre_candidates, nana_pool)

    # --- Phase 3: Slippi-fixed hash check (against both vault AND vanilla) ---
    survivors: list[dict] = []
    for i, c in enumerate(candidates):
        if job.job.should_stop():
            break
        if i % 25 == 0:
            pct = 52 + int((i / max(1, len(candidates))) * 18)
            _progress(job, 'slippi',
                  f"Slippi-fix check {i}/{len(candidates)}", pct, current=i, total=len(candidates))
        fixed = _slippi_fixed_hash(c['path'])
        if fixed and (fixed in vault_hashes or fixed in vanilla_hashes):
            job.stats['slippi_matched'] += 1
            if fixed in vault_hashes and fixed not in vanilla_hashes:
                _record_vault_match(job, vault_hashes[fixed], c['source_iso'])
            continue
        survivors.append(c)

    if job.job.should_stop():
        job.job.check_stop()
        return

    # A vanilla/already-imported ISO has no thumbnails to make. Do not boot
    # the renderer pool: each idle worker can spend 60s waiting for its GPU
    # context, leaving an empty scan showing "Generating thumbnails 0/0".
    if not survivors:
        _finalize(job)
        return

    # --- Phase 3b: Diet-family source detection ---
    # A Diet Melee-style ISO (hacked DOL entry point = injected engine
    # patches, plus at least one costume with stripped-texture materials)
    # authors its skins for the LOW-poly display its engine forces. Those
    # skins are repaired per-candidate in _build_candidate; see
    # shared/rendering/lowpoly_promote.py for the whole story.
    job.diet_sources = _detect_diet_sources(job.iso_paths, survivors)
    if job.diet_sources:
        logger.info(
            f"[iso-scan] Diet-family ISO(s) detected: {sorted(job.diet_sources)} "
            "— low-poly-authored skins will be repaired on import"
        )

    # --- Phase 4: copy DATs + generate CSPs into work dir (parallel) ---
    skins_dir = job.work_dir / "skins"
    skins_dir.mkdir(exist_ok=True)

    results: dict[int, Optional[CandidateSkin]] = {}
    results_lock = threading.Lock()
    completed_counter = {'n': 0, 'errors': 0, 'preview_failed': 0}

    total = len(survivors)
    workers = min(CSP_PARALLELISM, total)
    _progress(job, 'csp',
          f"Generating thumbnails 0/{total}", 70, current=0, total=total)

    # Reuse a handful of persistent --csp-server workers across every costume
    # instead of spawning one HSDRawViewer process per costume (~9x render
    # throughput). generate_csp routes through the pool while it's active and
    # falls back to a one-shot process for any costume the pool fails to
    # render, so a flaky worker or bad DAT never blocks the scan. Kill switch:
    # MEX_CSP_SERVER=0.
    with active_pool(workers=workers, enabled=False if total == 1 else None), \
            ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(_build_candidate, i, c, skins_dir, job): i
            for i, c in enumerate(survivors)
        }
        for fut in as_completed(futures):
            if job.job.should_stop():
                for f in futures:
                    f.cancel()
                break
            idx = futures[fut]
            try:
                candidate, error_kind = fut.result()
            except Exception as e:
                logger.warning(f"CSP worker for #{idx} crashed: {e}")
                candidate, error_kind = None, 'worker_crash'
            with results_lock:
                results[idx] = candidate
                if error_kind == 'preview_failed':
                    completed_counter['preview_failed'] += 1
                elif error_kind:
                    completed_counter['errors'] += 1
                completed_counter['n'] += 1
                n = completed_counter['n']
            pct = 70 + int((n / total) * 28)
            _progress(job, 'csp',
                  f"Generating thumbnails {n}/{total}", pct, current=n, total=total)

    # Stitch results back together in submission order so the UI grid is stable.
    for i in range(total):
        cand = results.get(i)
        if cand is not None:
            job.candidates.setdefault(cand.character, []).append(cand)
    job.stats['errors'] += completed_counter['errors']
    job.stats['preview_failed'] += completed_counter['preview_failed']

    _finalize(job)



def _detect_diet_sources(iso_paths, survivors) -> set[str]:
    """Source-ISO stems that are Diet Melee-family builds: a hacked DOL entry
    point (their injected engine patches boot before the game) AND at least
    one candidate costume carrying the stripped-texture fingerprint. The
    second condition keeps ordinary code-injected packs (20XX, Animelee, ...)
    out — their skins are authored for the normal high-poly display."""
    try:
        from shared.rendering import lowpoly_promote as lp
        hacked = {Path(p).stem for p in iso_paths if lp.dol_entry_hacked(p)}
        if not hacked:
            return set()
        diet: set[str] = set()
        for c in survivors:
            src = c['source_iso']
            if src in hacked and src not in diet and \
                    lp.stripped_tex_materials(c['path']):
                diet.add(src)
        return diet
    except Exception as e:
        logger.warning(f"[iso-scan] diet-source detection failed: {e}")
        return set()


def _apply_diet_fix(dat_path: Path, costume_code: str, diet_source: bool,
                    worker: str, character: str = '') -> bool:
    """Repair a diet-authored costume DAT in place (promote low-poly art,
    sanitize stripped materials, shim the blink indices). Returns whether the
    file was transformed; leaves it untouched on any failure."""
    try:
        from shared.rendering import lowpoly_promote as lp
        from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
        code = (costume_code or '')[:4]
        if len(code) < 4:
            return False
        van_costume = ensure_vanilla_ref(_ensure_dat_ext(costume_code))
        ftdata = ensure_vanilla_ref(code + '.dat')
        if not van_costume or not ftdata:
            return False
        slot = lp.costume_slot_for_code(character, costume_code[4:6])
        plan = lp.plan_diet_fix(dat_path, van_costume, ftdata,
                                costume_slot=slot, diet_source=diet_source)
        if not plan.promote:
            return False
        tmp = dat_path.with_suffix('.dietfix')
        lp.apply_diet_fix(dat_path, tmp, plan)
        file_retry.replace(tmp, dat_path)
        logger.info(
            f"[iso-scan][diet][{worker}] repaired {dat_path.name}: {plan.reason}"
        )
        return True
    except Exception as e:
        logger.warning(
            f"[iso-scan][diet][{worker}] repair failed for {dat_path.name}: {e} "
            "— importing the original file"
        )
        try:
            dat_path.with_suffix('.dietfix').unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _build_candidate(idx: int, c: dict, skins_dir: Path, job: ScanCandidates) -> tuple[Optional[CandidateSkin], Optional[str]]:
    """Per-candidate worker: copy DAT(s) + run HSDRawViewer to generate a CSP.
    Returns (candidate_or_None, error_kind)."""
    if job.job.should_stop():
        return None, None

    worker = threading.current_thread().name
    t0 = time.time()
    key = f"{c['character'].replace(' ', '_').replace('(', '').replace(')', '')}_{c['hash'][:10]}_{idx}"
    skin_folder = skins_dir / key
    skin_folder.mkdir(exist_ok=True)

    primary_name = _ensure_dat_ext(c['costume_code'])
    dat_dest = skin_folder / primary_name
    try:
        shutil.copy2(c['path'], dat_dest)
    except Exception as e:
        logger.warning(f"[iso-scan][csp][{worker}] copy fail {c['path']}: {e}")
        return None, 'copy_error'

    paired_dest: Optional[Path] = None
    if c.get('paired_path'):
        paired_name = _ensure_dat_ext(c.get('paired_costume_code') or 'pair.dat')
        paired_dest = skin_folder / paired_name
        try:
            shutil.copy2(c['paired_path'], paired_dest)
            logger.info(
                f"[iso-scan][csp][{worker}] paired DAT staged for {key}: "
                f"{c['costume_code']} + {c.get('paired_costume_code')}"
            )
        except Exception as e:
            logger.warning(f"[iso-scan][csp][{worker}] paired DAT copy fail for {key}: {e}")
            paired_dest = None

    # Diet Melee-family skins are repaired on the staged copy, so the CSP
    # below and the eventual vault import both see the fixed file.
    diet_source = c['source_iso'] in getattr(job, 'diet_sources', set())
    _apply_diet_fix(dat_dest, c['costume_code'], diet_source, worker,
                    character=c['character'])
    if paired_dest is not None:
        _apply_diet_fix(paired_dest, c.get('paired_costume_code') or '',
                        diet_source, worker, character=c['character'])

    csp_dest: Optional[Path] = None
    csp_status = 'ok'
    try:
        # a modded ISO that ships its OWN CSS portrait for this slot (art
        # that differs from vanilla) contributes it directly — the pack's
        # authored look beats a fresh render of the model
        csp_override = c.get('csp_override')
        if csp_override and os.path.exists(csp_override):
            csp_dest = skin_folder / "csp.png"
            shutil.copy2(csp_override, csp_dest)
            csp_status = 'from_iso_css'
        else:
            # Serialize HSDRawViewer LAUNCHES so each gets a clean ~1.5s init
            # window, then render in parallel. Shared policy — see
            # shared/rendering/csp_concurrency.staggered_launch, which additionally
            # no-ops while a render pool is active. This module installs a pool
            # (active_pool below), so the private copy that used to live here
            # was charging every costume a 1.5s sleep for nothing.
            with staggered_launch():
                generated = generate_csp(
                    str(dat_dest),
                    paired_dat_filepath=str(paired_dest) if paired_dest else None,
                )
            if generated and os.path.exists(generated):
                csp_dest = skin_folder / "csp.png"
                shutil.move(generated, csp_dest)
                ok, reason = _validate_csp_preview(csp_dest)
                if not ok:
                    csp_status = f'invalid:{reason}'
                    try:
                        csp_dest.unlink(missing_ok=True)
                    except OSError:
                        pass
                    csp_dest = None
            else:
                csp_status = 'no_output'
    except Exception as e:
        csp_status = f'exception: {e}'

    elapsed_ms = int((time.time() - t0) * 1000)
    logger.info(
        f"[iso-scan][csp][{worker}] #{idx:<3} {c['character']:22} "
        f"{primary_name:14} csp={csp_status:10} {elapsed_ms:>5}ms"
    )

    if csp_dest is None:
        job.preview_failures.append({
            'key': key,
            'character': c['character'],
            'costume_code': c['costume_code'],
            'source_iso': c['source_iso'],
            'dat_hash': c['hash'][:12],
            'status': csp_status,
            'paired_costume_code': c.get('paired_costume_code'),
        })
        logger.warning(
            f"[iso-scan][csp][{worker}] dropping {key}: preview failed ({csp_status})"
        )
        return None, 'preview_failed'

    stock_dest: Optional[Path] = None
    stock_path = c.get('stock_path')
    if stock_path and os.path.exists(stock_path):
        try:
            stock_dest = skin_folder / "stock.png"
            shutil.copy2(stock_path, stock_dest)
        except Exception as e:
            logger.warning(f"[iso-scan][stock][{worker}] copy fail for {key}: {e}")
            stock_dest = None

    return CandidateSkin(
        key=key,
        character=c['character'],
        costume_code=c['costume_code'],
        dat_path=str(dat_dest),
        csp_path=str(csp_dest) if csp_dest else None,
        stock_path=str(stock_dest) if stock_dest else None,
        dat_hash=c['hash'],
        source_iso=c['source_iso'],
        paired_dat_path=str(paired_dest) if paired_dest else None,
        paired_costume_code=c.get('paired_costume_code'),
    ), None


def _finalize(scan: ScanCandidates):
    scan.job.check_stop()
    scan.job.progress(1, 'Done', stats=dict(scan.stats))
    logger.info('[iso-scan] job %s done: %s', scan.job.id, scan.stats)
