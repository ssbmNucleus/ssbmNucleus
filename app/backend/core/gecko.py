"""Gecko code parsing/serialization — Python mirror of mexLib's CodeLoader/MexCode.

Pure module (no Flask imports) so the parser is unit-testable and reusable.

Format reference (<ssbmNucleus-mex>/mexLib/Utilties/CodeLoader.cs, Hex.cs,
Types/MexCode.cs):

    $!Name [Creator]        <- "$" starts a code, "!" = enabled
    *description line       <- repeated per description line
    04263384 48000010       <- hex lines: strip "#..." comments + whitespace,
                               exactly 16 hex chars

Where this module is deliberately STRICTER than the C# loader (so anything we
accept is guaranteed to compile there, never the reverse):
  - hex lines must be entirely hex (C# only requires one hex char in the line)
  - C2 blocks must be fully present (C# silently walks past a truncated block)
"""

from __future__ import annotations

import re

# Opcodes the m-ex code loader supports (MexCode.CompressCode). Every other
# top-level opcode raises NotSupportedException in C# and lands in CompileError.
_SUPPORTED_OPCODES = (0x00, 0x02, 0x04, 0xC2)

# Same lookbehind/lookahead pattern as CodeLoader.FromINI's creator match.
_CREATOR_RE = re.compile(r"(?<=\[).+?(?=\]\s*$)")

_HEX_LINE_RE = re.compile(r"^[0-9a-fA-F]{16}$")

# Dolphin gecko ini section headers, ignored when pasted ([Gecko],
# [Gecko_Enabled], ...). parse_ini would skip them anyway (not hex, not $/*),
# listed here so smart_parse doesn't emit "looks like hex" warnings for them.
_DOLPHIN_SECTION_RE = re.compile(r"^\[[A-Za-z0-9_ ]+\]\s*$")

MAX_PASTE_BYTES = 1_000_000

GCT_MAGIC_HEX = "00D0C0DE00D0C0DE"


def trim_hex_line(line):
    """Mirror of Hex.TrimHexLine: strip '#...' comment then all whitespace;
    valid iff exactly 16 hex chars remain. Returns the trimmed hex or None."""
    if not line:
        return None
    trimmed = re.sub(r"\s+", "", re.sub(r"#.*", "", line))
    if _HEX_LINE_RE.match(trimmed):
        return trimmed
    return None


def header(name, creator=""):
    """Canonical identity for a code: 'Name [Creator]' (or bare name).

    Matches CodeLoader.ToINI's header serialization, so it round-trips through
    FromINI. Compare case-insensitively (header(...).lower())."""
    name = (name or "").strip()
    creator = (creator or "").strip()
    return f"{name} [{creator}]" if creator else name


def split_header(text):
    """Inverse of header(): 'Name [Creator]' -> (name, creator).

    Same regex semantics as CodeLoader.FromINI's name/creator split."""
    m = _CREATOR_RE.search(text)
    if m:
        return text[: m.start() - 1].strip(), m.group(0)
    return text.strip(), ""


def parse_ini(text):
    """Mirror of CodeLoader.FromINI. Returns a list of code dicts:
    {name, creator, description, source, enabled}.

    Source lines are preserved verbatim (including inline '#labels'), like C#.
    Codes with no valid hex lines are dropped, like C#."""
    codes = []
    current = None
    src_lines = None
    # A file saved as UTF-8-with-BOM puts ﻿ in front of the first '$', so
    # the first header stops looking like a header and its code is silently
    # dropped. smart_parse already strips it; this path did not.
    text = (text or '').lstrip('﻿')

    def flush():
        if current is not None and src_lines:
            current["source"] = "\n".join(src_lines)
            codes.append(current)

    for line in text.splitlines():
        if line.startswith("$"):
            flush()
            body = line[1:]
            enabled = body.startswith("!")
            if enabled:
                body = body[1:]
            name, creator = split_header(body)
            current = {
                "name": name,
                "creator": creator,
                "description": "",
                "source": "",
                "enabled": enabled,
            }
            src_lines = []
        elif current is not None:
            if line.startswith("*"):
                current["description"] += line[1:].strip() + "\n"
            elif trim_hex_line(line) is not None:
                src_lines.append(line)
    flush()

    for c in codes:
        c["description"] = c["description"].rstrip("\n")
    return codes


def serialize_ini(codes):
    """Mirror of CodeLoader.ToINI. Accepts dicts shaped like parse_ini output.

    mexcli's FromINI treats \\n and \\r\\n alike, so plain \\n is used here."""
    out = []
    for c in codes:
        bang = "!" if c.get("enabled") else ""
        out.append(f"${bang}{header(c.get('name'), c.get('creator'))}")
        for dline in (c.get("description") or "").splitlines():
            if dline:
                out.append(f"*{dline}")
        out.append(c.get("source") or "")
    return "\n".join(out) + "\n"


def _compiled_bytes(source):
    """Hex-decode a source block the way MexCode.TryCompileCode does.
    Returns (data, error, line_index)."""
    data = bytearray()
    for idx, line in enumerate((source or "").split("\n")):
        if not line.strip():
            continue
        hexline = trim_hex_line(line)
        if hexline is None:
            return None, "Invalid hex format", idx
        data.extend(bytes.fromhex(hexline))
    return bytes(data), None, None


def validate_source(source):
    """Validate a code's hex source against what the m-ex loader can compile.

    Replica of MexCode.TryCompileCode + CompressCode's opcode walk, with the
    stricter bounds noted in the module docstring. Returns
    {ok: bool, error?: str, line?: int} (line is 0-based within source)."""
    data, err, line = _compiled_bytes(source)
    if err:
        return {"ok": False, "error": f"line {line + 1}: {err}", "line": line}
    if not data:
        return {"ok": False, "error": "no hex code lines found"}

    i = 0
    while i < len(data):
        op = data[i]
        code_line = i // 8
        if op in (0x00, 0x02, 0x04):
            i += 8
        elif op == 0xC2:
            count = int.from_bytes(data[i + 4 : i + 8], "big")
            if count < 1:
                return {
                    "ok": False,
                    "error": f"line {code_line + 1}: C2 injection with zero-length body",
                    "line": code_line,
                }
            end = i + 8 * (count + 1)
            if end > len(data):
                return {
                    "ok": False,
                    "error": (
                        f"line {code_line + 1}: C2 injection claims {count} lines "
                        "but the code is truncated"
                    ),
                    "line": code_line,
                }
            i = end
        else:
            return {
                "ok": False,
                "error": (
                    f"line {code_line + 1}: opcode 0x{op:02X} is not supported by the "
                    "m-ex code loader (only 00/02/04 writes and C2 injections)"
                ),
                "line": code_line,
            }
    return {"ok": True}


def _strip_loose_comment(line):
    """For loose (non-ini) pastes also treat '//...' as a comment."""
    return re.sub(r"//.*", "", re.sub(r"#.*", "", line))


def _normalize_loose_line(line):
    """Convert '//label' comments to '#label' so the stored source stays
    compatible with the C# loader (Hex.TrimHexLine only strips '#...')."""
    return re.sub(r"\s*//\s*(.*)$", lambda m: f"  #{m.group(1)}" if m.group(1) else "", line).strip()


def _looks_hexish(line):
    """A line that is mostly hex but not a valid 16-char code line — worth a
    warning so silently-dropped lines are visible in the preview."""
    stripped = re.sub(r"\s+", "", _strip_loose_comment(line))
    if not stripped:
        return False
    hex_chars = sum(1 for ch in stripped if ch in "0123456789abcdefABCDEF")
    return len(stripped) >= 8 and hex_chars / len(stripped) > 0.9


def _extract_title(text):
    """'Better Camera [Achilles, UnclePunch]' / '(UnclePunch)' -> (name, creator)."""
    text = text.strip().lstrip("-*#/ ").rstrip(":")
    name, creator = split_header(text)
    if creator:
        return name, creator
    m = re.search(r"\((?P<c>[^()]+)\)\s*$", text)
    if m:
        return text[: m.start()].strip(), m.group("c").strip()
    return text, ""


def _finish_candidate(cand, warnings):
    src = "\n".join(cand["lines"])
    result = validate_source(src)
    code = {
        "name": cand["name"] or "Pasted code",
        "creator": cand["creator"],
        "description": cand["description"],
        "source": src,
        "enabled": True,
        "valid": result["ok"],
        "warnings": warnings,
    }
    if not result["ok"]:
        code["error"] = result["error"]
    return code


def smart_parse(paste):
    """Parse anything a user might carelessly paste into named gecko codes.

    Handles: full INI blocks ($Name [Creator], single or multi-code, incl.
    Dolphin gecko ini sections), raw hex lines, and loose SmashBoards-style
    pastes (title line + description + hex). Preview only — saves nothing.

    Returns {codes: [...], warnings: [...]} where each code is
    {name, creator, description, source, enabled, valid, error?, warnings}."""
    global_warnings = []

    if not paste or not paste.strip():
        return {"codes": [], "warnings": ["nothing to parse"]}
    if len(paste.encode("utf-8", "replace")) > MAX_PASTE_BYTES:
        return {"codes": [], "warnings": ["paste too large (over 1 MB)"]}

    text = paste.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")

    compact = re.sub(r"\s+", "", text)
    if GCT_MAGIC_HEX.lower() in compact.lower():
        global_warnings.append(
            "this looks like a compiled GCT file — paste the code's text/INI "
            "form instead (compiled GCT import is not supported)"
        )

    # INI mode: any $-line present.
    if any(line.startswith("$") for line in text.splitlines()):
        codes = []
        for c in parse_ini(text):
            result = validate_source(c["source"])
            c["valid"] = result["ok"]
            c["warnings"] = []
            if not result["ok"]:
                c["error"] = result["error"]
            # Pasted codes should default to enabled regardless of the $/$!
            # flag — the user pasted it because they want it.
            c["enabled"] = True
            codes.append(c)
        dropped = [
            split_header(line.lstrip("$!").strip())[0]
            for line in text.splitlines()
            if line.startswith("$")
        ]
        if len(dropped) > len(codes):
            global_warnings.append(
                f"{len(dropped) - len(codes)} entr"
                f"{'y' if len(dropped) - len(codes) == 1 else 'ies'} had no "
                "valid hex lines and were skipped"
            )
        return {"codes": codes, "warnings": global_warnings}

    # Loose mode: classify lines into hex runs and text, pair nearest text
    # above a run as its title, earlier text as description.
    codes = []
    pending_text = []  # text lines since the last hex run
    current = None  # {"name","creator","description","lines"}
    line_warnings = []

    def close_current():
        nonlocal current, line_warnings
        if current is not None:
            codes.append(_finish_candidate(current, line_warnings))
            line_warnings = []
        current = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _DOLPHIN_SECTION_RE.match(line):
            continue
        hexline = trim_hex_line(_strip_loose_comment(raw))
        if hexline is not None:
            if current is None:
                name, creator, desc = "", "", ""
                if pending_text:
                    name, creator = _extract_title(pending_text[-1])
                    desc = "\n".join(t.strip() for t in pending_text[:-1])
                current = {
                    "name": name,
                    "creator": creator,
                    "description": desc,
                    "lines": [],
                }
                pending_text = []
            current["lines"].append(_normalize_loose_line(raw))
        else:
            if current is not None:
                # text after a hex run ends that code
                close_current()
            if _looks_hexish(raw):
                line_warnings.append(
                    f"skipped a line that looks like hex but is not a valid "
                    f"8-byte code line: {line[:40]!r}"
                )
            else:
                pending_text.append(raw)
    close_current()

    if not codes:
        global_warnings.append("no gecko code lines found in the paste")
    return {"codes": codes, "warnings": global_warnings}
