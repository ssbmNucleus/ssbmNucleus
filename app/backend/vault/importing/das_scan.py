"""
DAS variant detection from an extracted ISO's files/ directory.

Finds alternate ("Dynamic Alternate Stages") versions of the six legal stages
from two on-disc layouts:

  1. m-ex DAS layout (what this app itself builds): a folder per stage,
     ``files/Gr<code>/<name>.dat``. The root ``Gr<code>.dat`` is just the DAS
     loader, not a stage; ``vanilla.dat`` inside the folder is the base. Every
     other ``*.dat`` in the folder is a variant. This is the simple case.

  2. 20XX-style flat layout (e.g. "20XX 4.05 Corona Beginnings"): alternate
     stages live next to the base as ``files/Gr<code>.<X>at`` where the
     extension is ``<slot><'a'><'t'>`` — ``.dat`` (slot 'd') is the base, and
     ``.0at``..``.9at`` / ``.aat``..``.zat`` are alternate slots. Localized
     ``.usd`` files are bases, not variants.

The detector is a pure function over a directory tree so it can be unit-tested
with synthetic fixtures (no ISO, no wit, no Flask). Vault import lives in
``backend/vault/routes/das.py``-adjacent code; this module only *finds* variants.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from core.stages import LEGAL_STAGES as _REGISTRY_LEGAL_STAGES

# The six DAS-supported stages, derived from the single stage registry
# (core/stages.py). code -> {name, folder}. Detection is keyed on the exact
# stage code so e.g. GrNBa (Battlefield) never picks up GrNBr / GrNBl.
LEGAL_STAGES: dict[str, dict[str, str]] = {
    code: {'name': info['name'], 'folder': info['folder']}
    for code, info in _REGISTRY_LEGAL_STAGES.items()
}

# Base-stage extensions (NOT variants): '.dat' is the canonical base / DAS
# loader slot; '.usd'/'.dat' localized bases.
_BASE_EXTS = {'.dat', '.usd'}

# A 20XX alternate-slot extension: one char + 'at', e.g. '0at', 'lat', 'hat'.
_SLOT_EXT_RE = re.compile(r'^[0-9a-z]at$')

# Folder-layout files that are bases, not user variants.
_FOLDER_SKIP_STEMS = {'vanilla'}


@dataclass(frozen=True)
class DetectedVariant:
    stage_code: str          # e.g. 'GrNBa'
    stage_name: str          # e.g. 'Battlefield'
    folder: str              # vault folder, e.g. 'battlefield'
    name: str                # suggested variant display name
    path: Path               # path to the variant .dat on disk
    md5: str                 # md5 of the .dat bytes
    source: str              # 'mex' (folder layout) | '20xx' (flat .Xat)
    slot: str                # folder filename stem, or the .Xat ext for flat


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _base_md5s(files_dir: Path, code: str) -> set[str]:
    """md5 of every base file for a stage (Gr<code>.dat / .usd), so variants
    that are byte-identical to vanilla are skipped."""
    out: set[str] = set()
    for ext in _BASE_EXTS:
        base = files_dir / f"{code}{ext}"
        if base.is_file():
            out.add(_md5(base))
    return out


def detect_das_variants(
    files_dir: str | Path,
    skip_md5s: Optional[Iterable[str]] = None,
) -> list[DetectedVariant]:
    """Scan an extracted ISO's files/ directory for DAS stage variants.

    Args:
        files_dir: the ISO's ``files/`` directory (has Gr*.dat etc.).
        skip_md5s: md5 hexes already in the vault / vanilla — skipped so a
            re-scan only surfaces genuinely new variants.

    Returns one DetectedVariant per unique (md5) alternate stage, never
    including the base/vanilla/loader. Deduped by md5 within the scan too.
    """
    files_dir = Path(files_dir)
    seen: set[str] = {h.lower() for h in (skip_md5s or [])}
    out: list[DetectedVariant] = []

    if not files_dir.is_dir():
        return out

    for code, info in LEGAL_STAGES.items():
        # Variants identical to this stage's own vanilla base are not "new".
        base_hashes = _base_md5s(files_dir, code)

        # --- (1) m-ex DAS folder layout: files/Gr<code>/<name>.dat ---
        folder = files_dir / code
        if folder.is_dir():
            for dat in sorted(folder.glob('*.dat')):
                if dat.stem.lower() in _FOLDER_SKIP_STEMS:
                    continue
                md5 = _md5(dat)
                if md5 in base_hashes or md5 in seen:
                    continue
                seen.add(md5)
                out.append(DetectedVariant(
                    stage_code=code, stage_name=info['name'], folder=info['folder'],
                    name=dat.stem, path=dat, md5=md5, source='mex', slot=dat.stem,
                ))

        # --- (2) 20XX flat layout: files/Gr<code>.<X>at ---
        for cand in sorted(files_dir.glob(f"{code}.*")):
            if not cand.is_file() or cand.stem != code:
                continue
            ext = cand.suffix.lstrip('.').lower()  # e.g. '0at', 'lat', 'dat'
            if ext in {'dat', 'usd'} or not _SLOT_EXT_RE.match(ext):
                continue
            md5 = _md5(cand)
            if md5 in base_hashes or md5 in seen:
                continue
            seen.add(md5)
            slot = ext[0].upper()
            out.append(DetectedVariant(
                stage_code=code, stage_name=info['name'], folder=info['folder'],
                name=f"{info['name']} {slot}", path=cand, md5=md5,
                source='20xx', slot=ext,
            ))

        # --- (3) Pokemon Stadium special case: it's .usd-based, so 20XX can't
        # use the GrPs.<X>at scheme. Instead it encodes alternates as
        # GrP<digit>.usd (the trailing 's' of GrPs swapped for a slot digit);
        # GrPn.usd is the neutral base. (GrPs1-4.dat are the in-stage transform
        # sub-stages, not alternates — left alone.)
        if code == 'GrPs':
            neutral = files_dir / 'GrPn.usd'
            skip_extra = {_md5(neutral)} if neutral.is_file() else set()
            # The slot char replaces the trailing 's' of GrPs and cycles 0-9 then
            # a-z (same as the .Xat slots), so match any single char — not just
            # digits. Exclude 's' (the base code GrPs) and 'n' (neutral base). No
            # other Melee stage is GrP<char>.usd, so this won't grab anything else.
            for cand in sorted(files_dir.glob('GrP?.usd')):
                slot = cand.stem[-1]
                if slot in ('s', 'n'):
                    continue
                md5 = _md5(cand)
                if md5 in base_hashes or md5 in skip_extra or md5 in seen:
                    continue
                seen.add(md5)
                out.append(DetectedVariant(
                    stage_code=code, stage_name=info['name'], folder=info['folder'],
                    name=f"{info['name']} {slot.upper()}", path=cand, md5=md5,
                    source='20xx', slot=slot,
                ))

    return out


# --------------------------- vault import / dedup ----------------------------
# The DAS vault stores each variant as storage/das/<folder>/<id>.zip containing
# a single .dat (das_import_variant reads the first .dat/.usd), plus a
# metadata.json stages.<folder>.variants[] entry {id, name, ...}.


def _sanitize_id(name: str) -> str:
    s = re.sub(r'[^A-Za-z0-9_-]+', '_', name).strip('_')
    return s or 'variant'


def vault_variant_md5s(das_storage_root: str | Path) -> set[str]:
    """md5 of the .dat/.usd inside every existing vault variant zip — pass to
    detect_das_variants(skip_md5s=...) so a re-scan only surfaces new variants."""
    out: set[str] = set()
    root = Path(das_storage_root)
    if not root.is_dir():
        return out
    for zip_path in root.glob('*/*.zip'):
        try:
            with zipfile.ZipFile(zip_path) as zf:
                for n in zf.namelist():
                    if n.lower().endswith(('.dat', '.usd')):
                        out.add(hashlib.md5(zf.read(n)).hexdigest())
                        break
        except (zipfile.BadZipFile, OSError):
            continue
    return out


def import_variant_to_vault(
    variant: DetectedVariant,
    das_storage_root: str | Path,
    taken_ids: Optional[Iterable[str]] = None,
) -> dict:
    """Write storage/das/<folder>/<id>.zip (the variant .dat inside) and return
    the metadata entry the caller appends to stages.<folder>.variants[]. The id
    is made unique against taken_ids and existing zips on disk."""
    folder = Path(das_storage_root) / variant.folder
    folder.mkdir(parents=True, exist_ok=True)

    taken = set(taken_ids or [])
    base_id = _sanitize_id(variant.name)
    vid, i = base_id, 2
    while vid in taken or (folder / f'{vid}.zip').exists():
        vid = f'{base_id}_{i}'
        i += 1

    # An installed Pokemon Stadium variant keeps its per-transformation skins in
    # a sibling folder named after the variant (files/GrPs/<V>/GrPs1-4.dat).
    # Carry the whole set through, or the vault copy silently loses every form
    # except the normal one.
    forms = {}
    sidecars = variant.path.parent / variant.path.stem
    if sidecars.is_dir():
        found = {n: sidecars / f'GrPs{n}.dat' for n in range(1, 5)}
        if all(p.is_file() for p in found.values()):
            forms = found

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f'{variant.stage_code}.dat', variant.path.read_bytes())
        for n, path in sorted(forms.items()):
            zf.writestr(f'{variant.stage_code}/GrPs{n}.dat', path.read_bytes())
    (folder / f'{vid}.zip').write_bytes(buf.getvalue())

    entry = {
        'id': vid,
        'name': variant.name,
        'filename': f'{vid}.zip',
        'source': f'iso-scan:{variant.source}',
        'md5': variant.md5,
    }
    if forms:
        entry['transformation_skins'] = len(forms)
    return entry
