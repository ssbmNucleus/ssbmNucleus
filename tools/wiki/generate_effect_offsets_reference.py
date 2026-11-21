from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = next(p for p in Path(__file__).resolve().parents if (p / "docs" / "wiki").is_dir())  # repo root
WIKI_REF = ROOT / "docs" / "wiki" / "reference" / "color-effects-reference"
REFERENCE_PATH = WIKI_REF / "Effect-Offsets-Reference.md"
OFFSETS_JSON_PATH = WIKI_REF / "melee_color_offsets.json"

sys.path.insert(0, str(ROOT / "app" / "backend"))

from core.extra_types import EXTRA_TYPES  # noqa: E402


ENTRY_MIN_BYTES = {
    "CF_##": 11,
    "07_07_07": 12,
    "42_48": 16,
    "random": 9,
}

LIST_OFFSET_SPANS = {
    "CF": 11,
    "070707": 12,
}

CHARACTER_LABELS = {
    "Fox_Falco_Shared": "Fox / Falco Shared",
    "Menu": "Menu / Stage Select",
}

STATUS_SUPPORTED = "\U0001F7E2"
STATUS_UNSUPPORTED = "\U0001F534"


def parse_hex(value: str | int) -> int:
    if isinstance(value, int):
        return value
    return int(value, 16)


def data_length(entry: dict) -> int:
    data = entry.get("data")
    if not data:
        return 0
    return len([part for part in str(data).split() if part])


def infer_entry_range(entry: dict, format_name: str) -> tuple[int, int]:
    start = parse_hex(entry["offset"])
    if entry.get("end"):
        return start, parse_hex(entry["end"])

    length = max(data_length(entry), ENTRY_MIN_BYTES.get(format_name, 1))
    return start, start + max(length - 1, 0)


def add_range(coverage: dict[str, list[tuple[int, int]]], file_name: str, start: int, end: int) -> None:
    coverage.setdefault(file_name, []).append((start, end))


def add_property_ranges(
    coverage: dict[str, list[tuple[int, int]]],
    file_name: str,
    prop: dict,
    default_format: str | None,
) -> None:
    format_name = prop.get("format") or default_format

    if "start" in prop and "end" in prop:
        add_range(coverage, file_name, parse_hex(prop["start"]), parse_hex(prop["end"]))
        return

    if "start" in prop and "size" in prop:
        start = parse_hex(prop["start"])
        size = int(prop["size"])
        add_range(coverage, file_name, start, start + max(size - 1, 0))
        return

    if "offsets" in prop:
        span = LIST_OFFSET_SPANS.get(format_name or "", 1)
        for offset in prop["offsets"]:
            start = parse_hex(offset)
            add_range(coverage, file_name, start, start + max(span - 1, 0))
        return

    if "ranges" in prop:
        for entry_range in prop["ranges"]:
            add_range(
                coverage,
                file_name,
                parse_hex(entry_range["start"]),
                parse_hex(entry_range["end"]),
            )


def build_coverage() -> dict[str, list[tuple[int, int]]]:
    coverage: dict[str, list[tuple[int, int]]] = {}

    for extras in EXTRA_TYPES.values():
        for extra in extras:
            if extra.get("type") in {"model", "texture"}:
                continue

            file_name = extra["target_file"]
            default_format = extra.get("format")

            for prop in extra.get("offsets", {}).values():
                add_property_ranges(coverage, file_name, prop, default_format)

            flash_offsets = extra.get("flash_offsets")
            if flash_offsets:
                add_property_ranges(coverage, file_name, flash_offsets, None)

    return coverage


def is_supported(
    coverage: dict[str, list[tuple[int, int]]],
    file_name: str,
    start: int,
    end: int,
) -> bool:
    for supported_start, supported_end in coverage.get(file_name, []):
        if end >= supported_start and start <= supported_end:
            return True
    return False


def format_offset(entry: dict) -> str:
    if entry.get("end"):
        return f"{entry['offset']}-{entry['end']}"
    return str(entry["offset"])


def format_entry_line(
    entry: dict,
    format_name: str,
    file_name: str,
    coverage: dict[str, list[tuple[int, int]]],
) -> str:
    start, end = infer_entry_range(entry, format_name)
    status = STATUS_SUPPORTED if is_supported(coverage, file_name, start, end) else STATUS_UNSUPPORTED

    line = f"- {status} `{format_offset(entry)}`: {entry['desc']}"

    if entry.get("data"):
        line += f". Data: `{entry['data']}`"
    if entry.get("note"):
        line += f". Note: {entry['note']}"

    return line


def generate_offset_section() -> str:
    coverage = build_coverage()
    offsets = json.loads(OFFSETS_JSON_PATH.read_text(encoding="utf-8"))
    parts: list[str] = ["## Offset Data", ""]

    section_groups = [
        offsets.get("characters", {}),
        offsets.get("ui", {}),
    ]

    for section_group in section_groups:
        for character_name, files in section_group.items():
            parts.append(f"## {CHARACTER_LABELS.get(character_name, character_name)}")
            parts.append("")

            for file_name, formats in files.items():
                parts.append(f"### `{file_name}`")
                parts.append("")

                file_note = formats.get("note") if isinstance(formats, dict) else None
                if file_note:
                    parts.append(f"Note: {file_note}")
                    parts.append("")

                for format_name, entries in formats.items():
                    if not isinstance(entries, list):
                        continue

                    usable_entries = [entry for entry in entries if isinstance(entry, dict) and entry.get("offset")]
                    if not usable_entries:
                        continue

                    parts.append(f"#### `{format_name}`")
                    parts.append("")

                    for entry in usable_entries:
                        parts.append(format_entry_line(entry, format_name, file_name, coverage))

                    parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def main() -> None:
    current = REFERENCE_PATH.read_text(encoding="utf-8")
    marker = "\n## Offset Data\n"
    if marker not in current:
        raise RuntimeError("Could not find '## Offset Data' marker in Effect-Offsets-Reference.md")

    prefix = current.split(marker, 1)[0].rstrip() + "\n\n"
    updated = prefix + generate_offset_section()
    REFERENCE_PATH.write_text(updated, encoding="utf-8")


if __name__ == "__main__":
    main()
