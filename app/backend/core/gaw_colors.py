"""Mr. Game & Watch color plumbing shared by the vault and the export path.

G&W's costume colors are engine-side: the m-ex MxDt MiscData GawColors table
holds one {fill, outline} pair per costume slot (mexLib models it as
MexFighter.GaWData; MexCLI keeps it in lockstep with costume add/remove/reorder
and reads a `gaw.json` sidecar from costume zips). This module converts between
the storage forms:

  - "#AARRGGBB" hex strings (gaw.json sidecar, vault metadata, the creator UI)
  - packed ARGB uints (the project's data/fighters/NNN.json, camelCase `gaWData`)
  - the {'fill': (r, g, b), 'outline': (r, g, b, a)} dicts generate_csp /
    stock_gen / hd_csp_cache take as `gw_colors`
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Vanilla defaults (slot 0): black fill, semi-transparent white outline.
DEFAULT_FILL = "#FF000000"
DEFAULT_OUTLINE = "#80FFFFFF"

# A model imported onto G&W (Randall's importer) draws its own textures, and the
# game multiplies every material's diffuse by the slot's fill at load
# (ftGw_Init_OnLoad -> ftMaterial_800BFB4C): a black fill draws it black, a white
# one leaves the textures as they are. His move items take the fill too, so they
# turn white for that slot (owner's choice, 2026-10-07). The outline stays his own.
IMPORT_FILL = "#FFFFFFFF"


def import_sidecar() -> dict:
    """The gaw.json a model imported onto G&W carries: white fill, his usual outline."""
    return {'fill': IMPORT_FILL, 'outline': DEFAULT_OUTLINE}


def parse_hex_color(text: str | None) -> int | None:
    """'#AARRGGBB' or '#RRGGBB' (alpha FF assumed) -> packed ARGB uint, else None."""
    if not text or not isinstance(text, str):
        return None
    hex_str = text.strip().lstrip('#')
    if len(hex_str) == 6:
        hex_str = 'FF' + hex_str
    if len(hex_str) != 8:
        return None
    try:
        return int(hex_str, 16)
    except ValueError:
        return None


def format_hex_color(argb: int) -> str:
    return f"#{argb & 0xFFFFFFFF:08X}"


def argb_rgb(argb: int) -> tuple[int, int, int]:
    return ((argb >> 16) & 0xFF, (argb >> 8) & 0xFF, argb & 0xFF)


def argb_rgba(argb: int) -> tuple[int, int, int, int]:
    r, g, b = argb_rgb(argb)
    return (r, g, b, (argb >> 24) & 0xFF)


def gw_colors_from_hex(fill_hex: str | None, outline_hex: str | None) -> dict | None:
    """Build the `gw_colors` dict the render pipeline takes from hex strings.
    Missing/invalid values fall back to the vanilla defaults; returns None only
    if BOTH are missing (nothing to override)."""
    fill = parse_hex_color(fill_hex)
    outline = parse_hex_color(outline_hex)
    if fill is None and outline is None:
        return None
    if fill is None:
        fill = parse_hex_color(DEFAULT_FILL)
    if outline is None:
        outline = parse_hex_color(DEFAULT_OUTLINE)
    return {'fill': argb_rgb(fill), 'outline': argb_rgba(outline)}


def load_project_gaw_colors(project_path) -> list[dict] | None:
    """Read the per-slot GawColors from a project's fighter JSON.

    `project_path` is the .mexproj file (or the project dir). mexLib serializes
    each fighter to data/fighters/NNN.json (camelCase); G&W is index 24 in a
    standard project but we scan for the one with non-null `gaWData` to be safe.
    Returns [{'fill': (r,g,b), 'outline': (r,g,b,a)}, ...] indexed by costume
    slot, or None if unavailable.
    """
    try:
        project_dir = Path(project_path)
        if project_dir.is_file():
            project_dir = project_dir.parent
        fighters_dir = project_dir / 'data' / 'fighters'
        if not fighters_dir.is_dir():
            return None

        from mexcli.project import fighter_files
        listed = fighter_files(project_dir)
        candidates = listed[24:25] + listed[:24] + listed[25:]
        for path in candidates:
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
            except Exception:
                continue
            gaw = data.get('gaWData')
            if not gaw:
                continue
            colors = []
            for entry in gaw.get('colors', []):
                fill = int(entry.get('fill', 0xFF000000))
                outline = int(entry.get('outline', 0x80FFFFFF))
                colors.append({'fill': argb_rgb(fill), 'outline': argb_rgba(outline)})
            return colors
    except Exception as e:  # noqa: BLE001 - reading colors is best-effort
        logger.warning(f"Could not read project GaW colors: {e}")
    return None
