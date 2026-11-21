"""
The stock icons and CSS portraits an ISO ships for each costume slot, read from
the disc itself: which stock frame each costume uses (from main.dol for vanilla
builds, from MxDt.dat for m-ex builds), exporting the icons and portraits with
HSDRawViewer / MexCLI, and mapping costume stems to the extracted PNGs.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional
from core.config import MEXCLI_PATH, VANILLA_ASSETS_DIR, get_subprocess_args
from generate_csp import HSDRAW_EXE
from vault.importing.iso_costume_files import _split_costume_stem

logger = logging.getLogger(__name__)


_INTERNAL_TO_EXTERNAL = [
    0x08, 0x02, 0x00, 0x01, 0x04, 0x05, 0x06,
    0x13, 0x0B, 0x0C, 0x0E, 0x20, 0x0D, 0x10,
    0x11, 0x0F, 0x0A, 0x07, 0x09, 0x12, 0x15,
    0x16, 0x14, 0x18, 0x03, 0x19, 0x17, 0x1A,
    0x1E, 0x1B, 0x1C, 0x1D, 0x1F,
]


def _stock_lookup_key(costume_code: str) -> str:
    """Normalize a costume filename/code for stock lookup."""
    return os.path.splitext(os.path.basename(costume_code or ''))[0].lower()


def _slot_asset(asset_map: dict[str, str], path: str, costume_code: str) -> Optional[str]:
    """The ISO's stock icon / CSS portrait for the slot a costume file occupies.

    Keyed by the file's own stem first: an ADDED costume (PlSkNrMod.dat) has
    its own m-ex stock, and its content-derived code (PlSkNr) names the
    vanilla slot beside it, whose art is not this costume's. Only a plain
    slot file falls back to the content code.
    """
    stem = os.path.splitext(os.path.basename(path))[0]
    found = asset_map.get(stem.lower())
    parts = _split_costume_stem(stem)
    if found or (parts and parts[2]):
        return found
    return asset_map.get(_stock_lookup_key(costume_code))


def _to_external_id(internal_id: int, character_count: int = 0x21) -> int:
    """Port of mexLib.MexFighterIDConverter.ToExternalID for vanilla ids."""
    base_character_count = 0x21
    internal_special_count = 6
    external_special_count = 7
    added_chars = character_count - base_character_count
    is_special = internal_id >= character_count - internal_special_count

    if internal_id >= character_count - internal_special_count - added_chars and not is_special:
        return (base_character_count - external_special_count) + (
            internal_id - (base_character_count - internal_special_count)
        )

    external_id = internal_id + (-added_chars if is_special else 0)
    if external_id < len(_INTERNAL_TO_EXTERNAL):
        external_id = _INTERNAL_TO_EXTERNAL[external_id]
    if is_special:
        external_id += added_chars
    if internal_id == 11:  # Popo special case in mexLib; stock extractor skips Nana.
        external_id = character_count - 1
    return external_id


def _vanilla_stock_frame(internal_id: int, costume_index: int) -> Optional[int]:
    """Frame used by vanilla IfAll Stc_scemdls for a costume stock icon."""
    if internal_id > 26 or internal_id == 11:
        return None
    external_id = _to_external_id(internal_id, 0x21)
    if internal_id == 7:
        external_id = 25
    elif external_id == 26:
        pass
    elif external_id >= 19:
        external_id -= 1
    return external_id + costume_index * 30


class _DolReader:
    """Minimal big-endian DOL address reader for Melee's costume tables."""

    def __init__(self, path: Path):
        self.data = path.read_bytes()
        self.section_offsets = [self._u32_at(i * 4) for i in range(18)]
        self.section_addresses = [self._u32_at(0x48 + i * 4) for i in range(18)]
        self.section_lengths = [self._u32_at(0x90 + i * 4) for i in range(18)]

    def _u32_at(self, offset: int) -> int:
        if offset < 0 or offset + 4 > len(self.data):
            return 0
        return int.from_bytes(self.data[offset:offset + 4], 'big')

    def _to_file_offset(self, address: int) -> Optional[int]:
        if address & 0x80000000:
            for section_offset, section_address, section_length in zip(
                self.section_offsets, self.section_addresses, self.section_lengths
            ):
                if not section_address:
                    continue
                if section_address <= address < section_address + section_length:
                    return section_offset + (address - section_address)
            return None
        return address if 0 <= address < len(self.data) else None

    def read_u8(self, address: int) -> Optional[int]:
        offset = self._to_file_offset(address)
        if offset is None or offset >= len(self.data):
            return None
        return self.data[offset]

    def read_u32(self, address: int) -> Optional[int]:
        offset = self._to_file_offset(address)
        if offset is None or offset + 4 > len(self.data):
            return None
        return self._u32_at(offset)

    def read_string(self, address: int) -> str:
        offset = self._to_file_offset(address)
        if offset is None:
            return ''
        end = offset
        while end < len(self.data) and self.data[end] != 0:
            end += 1
        try:
            return self.data[offset:end].decode('ascii', errors='ignore')
        except Exception:
            return ''

    def read_string_pointer(self, address: int) -> str:
        pointer = self.read_u32(address)
        if not pointer:
            return ''
        return self.read_string(pointer)


def _read_dol_costume_stock_frames(dol_path: Path) -> dict[str, int]:
    """Map costume stem -> vanilla stock animation frame using main.dol order."""
    reader = _DolReader(dol_path)
    mapping: dict[str, int] = {}

    for internal_id in range(0x21):
        costume_count = reader.read_u8(0x803C0EC0 + 0x4 + internal_id * 8)
        costume_pointer = reader.read_u32(0x803C2360 + internal_id * 4)
        if not costume_count or not costume_pointer:
            continue

        for costume_index in range(costume_count):
            frame = _vanilla_stock_frame(internal_id, costume_index)
            if frame is None:
                continue
            file_name = reader.read_string_pointer(costume_pointer + costume_index * 0x0C)
            key = _stock_lookup_key(file_name)
            if key:
                mapping[key] = frame

    return mapping


def _find_disc_file(root: Path, preferred_names: tuple[str, ...]) -> Optional[Path]:
    """Find a file under an extracted ISO, preferring names in order."""
    matches: dict[str, Path] = {}
    wanted = {n.lower() for n in preferred_names}
    for path in root.rglob('*'):
        if path.is_file() and path.name.lower() in wanted:
            matches.setdefault(path.name.lower(), path)
    for name in preferred_names:
        match = matches.get(name.lower())
        if match:
            return match
    return None


def _run_stock_icon_export(ifall_path: Path, out_dir: Path) -> Optional[dict]:
    if not os.path.exists(HSDRAW_EXE):
        logger.warning(f"[iso-scan][stock] HSDRawViewer not found: {HSDRAW_EXE}")
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [HSDRAW_EXE, '--stock-icons', 'export', str(ifall_path), str(out_dir)],
        capture_output=True, text=True, **get_subprocess_args(),
    )
    if result.returncode != 0:
        logger.warning(
            f"[iso-scan][stock] export failed for {ifall_path}: "
            f"{(result.stderr or result.stdout)[-500:]}"
        )
        return None
    manifest_path = out_dir / 'manifest.json'
    if not manifest_path.exists():
        logger.warning(f"[iso-scan][stock] no manifest written for {ifall_path}")
        return None
    try:
        return json.loads(manifest_path.read_text(encoding='utf-8'))
    except Exception as e:
        logger.warning(f"[iso-scan][stock] bad manifest for {ifall_path}: {e}")
        return None


def _run_mex_css_info(mxdt_path: Path, out_path: Path) -> Optional[dict]:
    """Dump an m-ex MxDt.dat's fighter + costume tables to JSON."""
    if not os.path.exists(HSDRAW_EXE):
        logger.warning(f"[iso-scan][stock] HSDRawViewer not found: {HSDRAW_EXE}")
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [HSDRAW_EXE, '--mex-css-info', 'export', str(mxdt_path), str(out_path)],
        capture_output=True, text=True, **get_subprocess_args(),
    )
    if result.returncode != 0 or not out_path.exists():
        logger.warning(
            f"[iso-scan][stock] MxDt read failed for {mxdt_path}: "
            f"{(result.stderr or result.stdout)[-500:]}"
        )
        return None
    try:
        return json.loads(out_path.read_text(encoding='utf-8'))
    except Exception as e:
        logger.warning(f"[iso-scan][stock] bad MxDt dump for {mxdt_path}: {e}")
        return None


def mex_costume_stock_frames(css_info: dict, reserved: int, stride: int) -> dict[str, int]:
    """Map costume stem -> m-ex stock frame.

    m-ex swaps the vanilla Stc_scemdls table for its own Stc_icns one, keyed
    `reserved + costumeId * stride + internalId` (mexLib MxDtImporter). The
    costume order costumeId indexes lives in MxDt, not main.dol -- which is why
    a modded disc's added costumes have no DOL frame to look up at all.
    """
    mapping: dict[str, int] = {}
    for fighter in css_info.get('fighter_costumes') or []:
        try:
            internal_id = int(fighter.get('internal_id'))
        except (TypeError, ValueError):
            continue
        for costume in fighter.get('costumes') or []:
            key = _stock_lookup_key(costume.get('file_name'))
            try:
                costume_id = int(costume.get('costume_id'))
            except (TypeError, ValueError):
                continue
            if key:
                mapping[key] = reserved + costume_id * stride + internal_id
    return mapping


def _costume_frames_for_manifest(iso_dir: Path, manifest: dict, out_dir: Path) -> dict[str, int]:
    """Costume stem -> stock frame, read from whichever table this ISO uses."""
    fmt = manifest.get('format')

    if fmt == 'vanilla':
        dol_path = _find_disc_file(iso_dir, ('main.dol',))
        if not dol_path:
            logger.info(f"[iso-scan][stock] {iso_dir.name}: missing main.dol")
            return {}
        try:
            return _read_dol_costume_stock_frames(dol_path)
        except Exception as e:
            logger.warning(f"[iso-scan][stock] {iso_dir.name}: DOL parse failed: {e}")
            return {}

    if fmt == 'mex':
        mxdt_path = _find_disc_file(iso_dir, ('MxDt.dat',))
        if not mxdt_path:
            logger.info(f"[iso-scan][stock] {iso_dir.name}: m-ex stocks but no MxDt.dat")
            return {}
        try:
            reserved = int(manifest['reserved'])
            stride = int(manifest['stride'])
        except (KeyError, TypeError, ValueError):
            logger.info(
                f"[iso-scan][stock] {iso_dir.name}: m-ex stock table without reserved/stride"
            )
            return {}
        css_info = _run_mex_css_info(mxdt_path, out_dir / 'mex_css_info.json')
        if not css_info:
            return {}
        return mex_costume_stock_frames(css_info, reserved, stride)

    logger.info(f"[iso-scan][stock] {iso_dir.name}: unknown stock table format {fmt!r}")
    return {}


def _build_stock_map_for_iso(iso_dir: Path, out_dir: Path) -> dict[str, str]:
    """Extract actual ISO stock icons and map costume stem -> PNG path."""
    ifall_path = _find_disc_file(iso_dir, ('IfAll.usd', 'IfAll.dat'))
    if not ifall_path:
        logger.info(f"[iso-scan][stock] {iso_dir.name}: missing IfAll, stock extraction skipped")
        return {}

    manifest = _run_stock_icon_export(ifall_path, out_dir)
    if not manifest:
        return {}

    costume_frames = _costume_frames_for_manifest(iso_dir, manifest, out_dir)
    if not costume_frames:
        logger.info(f"[iso-scan][stock] {iso_dir.name}: no costume frames found")
        return {}

    frame_to_png: dict[int, str] = {}
    for entry in manifest.get('entries', []):
        try:
            frame = int(entry.get('frame'))
            width = int(entry.get('width', 0))
            height = int(entry.get('height', 0))
        except (TypeError, ValueError):
            continue
        # Costume stock icons are 24x24; skip timer digits and cursor fragments
        # that live in the same Stc_scemdls animation bank.
        if width != 24 or height != 24:
            continue
        filename = entry.get('filename')
        if not filename:
            continue
        png_path = out_dir / filename
        if png_path.exists():
            frame_to_png[frame] = str(png_path)

    stock_map = {
        key: frame_to_png[frame]
        for key, frame in costume_frames.items()
        if frame in frame_to_png
    }
    logger.info(
        f"[iso-scan][stock] {iso_dir.name}: mapped {len(stock_map)} stocks "
        f"from {manifest.get('format')} IfAll ({len(costume_frames)} costumes)"
    )
    return stock_map


def _build_stock_maps(extract_root: Path, stocks_root: Path) -> dict[str, dict[str, str]]:
    maps: dict[str, dict[str, str]] = {}
    for iso_dir in extract_root.iterdir():
        if not iso_dir.is_dir():
            continue
        stock_map = _build_stock_map_for_iso(iso_dir, stocks_root / iso_dir.name)
        if stock_map:
            maps[iso_dir.name] = stock_map
    return maps


# CSS portrait (CSP) external-id order — mexLib MexFighterIDConverter's
# vanilla external ordering (Sheik sits in the 0x13 gap).
_EXTID_TO_CHAR = [
    'C. Falcon', 'DK', 'Fox', 'Mr. Game & Watch', 'Kirby', 'Bowser', 'Link',
    'Luigi', 'Mario', 'Marth', 'Mewtwo', 'Ness', 'Peach', 'Pikachu',
    'Ice Climbers', 'Jigglypuff', 'Samus', 'Yoshi', 'Zelda', 'Sheik', 'Falco',
    'Young Link', 'Dr. Mario', 'Roy', 'Pichu', 'Ganondorf',
]


def _csp_is_vanilla(png_path: Path, character: str, code: str) -> bool:
    """Pixel-compare an extracted CSS portrait against the shipped vanilla
    portrait for that slot. Unknown/missing references count as MODDED
    (fail-open: worst case the vault gets the ISO's own vanilla-looking
    art instead of a render)."""
    ref = VANILLA_ASSETS_DIR / character / code / 'csp.png'
    if not ref.exists():
        return False
    try:
        from PIL import Image
        with Image.open(png_path) as a, Image.open(ref) as b:
            if a.size != b.size:
                return False
            return a.convert('RGBA').tobytes() == b.convert('RGBA').tobytes()
    except Exception:
        return False


def _build_csp_map_for_iso(iso_dir: Path, out_dir: Path) -> dict[str, str]:
    """Extract the ISO's own CSS portraits and map costume stem -> PNG path,
    keeping only portraits that DIFFER from vanilla. Modded packs that ship
    their own CSP art (Diet Melee's N64 renders, Animelee) contribute it to
    the scan directly; vanilla-art slots fall back to our renders."""
    css_path = _find_disc_file(iso_dir, ('MnSlChr.usd', 'MnSlChr.dat'))
    if not css_path:
        return {}
    try:
        from core.constants import VANILLA_CSS_COLOR_ORDER, CHAR_PREFIXES
        out_dir.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [str(MEXCLI_PATH), 'export-csps', str(css_path), str(out_dir)],
            capture_output=True, text=True, timeout=300,
            **get_subprocess_args())
        manifest_path = out_dir / 'manifest.json'
        if not manifest_path.exists():
            logger.info(f"[iso-scan][csp-map] {iso_dir.name}: export-csps "
                        f"produced no manifest ({(result.stdout or '')[:200]})")
            return {}
        manifest = json.loads(manifest_path.read_text())
        csp_map: dict[str, str] = {}
        skipped_vanilla = 0
        for entry in manifest.get('entries', []):
            ext, j = entry.get('externalId'), entry.get('costume')
            if ext is None or j is None or ext >= len(_EXTID_TO_CHAR):
                continue
            character = _EXTID_TO_CHAR[ext]
            prefix = CHAR_PREFIXES.get(character)
            order = VANILLA_CSS_COLOR_ORDER.get(character) or []
            if not prefix or j >= len(order):
                continue
            code = f'Pl{prefix}{order[j]}'
            png = out_dir / entry['file']
            if not png.exists():
                continue
            if _csp_is_vanilla(png, character, code):
                skipped_vanilla += 1
                continue
            csp_map[code.lower()] = str(png)
        logger.info(
            f"[iso-scan][csp-map] {iso_dir.name}: {len(csp_map)} modded CSS "
            f"portraits lifted ({skipped_vanilla} vanilla-identical skipped)")
        return csp_map
    except Exception as e:
        logger.warning(f"[iso-scan][csp-map] {iso_dir.name}: {e}")
        return {}


def _build_csp_maps(extract_root: Path, csps_root: Path) -> dict[str, dict[str, str]]:
    maps: dict[str, dict[str, str]] = {}
    for iso_dir in extract_root.iterdir():
        if not iso_dir.is_dir():
            continue
        csp_map = _build_csp_map_for_iso(iso_dir, csps_root / iso_dir.name)
        if csp_map:
            maps[iso_dir.name] = csp_map
    return maps
