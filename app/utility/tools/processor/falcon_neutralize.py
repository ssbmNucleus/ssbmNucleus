"""Convert Captain Falcon costumes to the NEUTRAL color identity at install.

Falcon is the one character whose vanilla skeleton genuinely differs per color
slot (25-33 of 63 bone transforms differ from Neutral; the tree shape is
identical across all six colors). A costume whose skeleton matches one color
but is played in another desyncs on Slippi netplay, and the validator cannot
tell those apart because it keys its vanilla reference off the symbol embedded
in the DAT. Since the base color under a mod is visually irrelevant, we
sidestep the whole class of bug: every Falcon costume becomes a Neutral one
when it is installed.

"Neutral" means two coordinated rewrites:
  * every skeleton root's bone transforms are rewritten to the vanilla Nr
    reference (reusing the validator's differential-tested tree walker), and
  * every color-suffixed root symbol (PlyCaptain5KRe_* etc.) is renamed to the
    un-suffixed neutral form (PlyCaptain5K_*). The neutral name is always two
    bytes shorter, so it is overwritten in place inside the string table --
    no offset moves, the file size is unchanged, and the two dead bytes left
    after the new NUL are invisible to every NUL-terminated reader.

Applied at INSTALL time only: `convert_falcon_zip` reads the vault zip
read-only and emits a temp zip for MexCLI. Vault files are never mutated.
Any failure is fail-open -- the original zip installs unmodified.
"""
import logging
import os
import re
import struct
import tempfile
import zipfile
from pathlib import Path

from costume_validator import (
    DAT_HEADER_SIZE,
    JointTreeMismatch,
    _is_skeleton_root,
    _iter_roots,
    _pointer,
    _u32,
    _walk,
    is_costume_file,
    ref_dir,
)

logger = logging.getLogger(__name__)

FALCON_PREFIX = "PlyCaptain5K"
NR_REF_NAME = "PlyCaptain5K_Share_joint.bin"


def _nr_ref_path():
    """The vanilla-Neutral reference skeleton, resolved per call via ref_dir().

    Must NOT be the module-level REF_DIR constant: that is the bundled in-tree
    directory, which frozen builds deliberately ship EMPTY (the tables are
    Nintendo data, derived from the user's own ISO into storage instead). Using
    it made neutralize fail-open on every packaged install while working in
    every dev checkout and test run.
    """
    return ref_dir() / NR_REF_NAME

# A Falcon symbol carrying a two-letter color token right after the model name
# (PlyCaptain5KRe_Share_joint, PlyCaptain5KGy_Share_matanim_joint, ...).
# The neutral symbol has no token, so "_S..." never matches.
_COLOR_SYMBOL_RE = re.compile(r"^(PlyCaptain5K)[A-Z][a-z](_.+)$")


def _rename_falcon_symbols(buf):
    """Rename every color-suffixed PlyCaptain5K symbol in the string table to
    its neutral form, in place. Returns [(old, new), ...].

    Parses the header itself rather than reusing _iter_roots: the string table
    sits after BOTH the root table and the ref-node table, and _iter_roots
    ignores the ref count (harmless there -- costume DATs have none -- but a
    rename must not gamble on that).
    """
    if len(buf) < DAT_HEADER_SIZE or _u32(buf, 0) != len(buf):
        return []
    data_end = _pointer(buf, 4, 0)
    reloc_count = _u32(buf, 8)
    root_count = _u32(buf, 12)
    ref_count = _u32(buf, 16)
    root_table = data_end + reloc_count * 4
    string_table = root_table + (root_count + ref_count) * 8

    renames = []
    seen_offsets = set()
    for i in range(root_count + ref_count):
        entry = root_table + i * 8
        if entry + 8 > len(buf):
            break
        name_off = _u32(buf, entry + 4)
        if name_off in seen_offsets:  # entries may share one string
            continue
        seen_offsets.add(name_off)
        str_off = string_table + name_off
        if str_off >= len(buf):
            continue
        end = buf.find(b"\0", str_off)
        if end < 0:
            continue
        old = buf[str_off:end].decode("ascii", "replace")
        m = _COLOR_SYMBOL_RE.match(old)
        if not m:
            continue
        new = m.group(1) + m.group(2)
        new_bytes = new.encode("ascii")
        buf[str_off:str_off + len(new_bytes)] = new_bytes
        buf[str_off + len(new_bytes)] = 0  # old tail stays as dead padding
        renames.append((old, new))
    return renames


def neutralize_dat_bytes(buf):
    """Neutralize one Falcon costume DAT held in a bytearray.

    Returns (changed, notes). Non-Falcon DATs and already-neutral DATs come
    back (False, ...) with the buffer untouched. A skeleton that cannot be
    walked against the vanilla Falcon tree leaves the buffer untouched too --
    renaming a DAT we cannot also retarget would be worse than the status quo.
    """
    falcon_roots = [(s, o) for s, o in _iter_roots(buf)
                    if s.startswith(FALCON_PREFIX)]
    if not falcon_roots:
        return False, []

    nr_ref = _nr_ref_path().read_bytes()
    skeleton_roots = [(s, o) for s, o in falcon_roots if _is_skeleton_root(s)]

    # Prove every tree lines up with vanilla Falcon BEFORE writing anything.
    for symbol, root_off in skeleton_roots:
        try:
            _walk(buf, nr_ref, root_off, -1, {"ref_pos": 0, "id": 0},
                  0, apply_fix=False)
        except (JointTreeMismatch, IndexError, struct.error) as e:
            return False, [f"skipped: skeleton does not match vanilla Falcon "
                           f"({symbol}: {e})"]

    notes = []
    for old, new in _rename_falcon_symbols(buf):
        notes.append(f"renamed {old} -> {new}")
    for symbol, root_off in skeleton_roots:
        if _walk(buf, nr_ref, root_off, -1, {"ref_pos": 0, "id": 0},
                 0, apply_fix=True):
            notes.append(f"retargeted {symbol} to the neutral skeleton")

    if not notes:
        return False, ["already neutral"]
    return True, notes


def convert_falcon_zip(zip_path, temp_dir=None):
    """Produce a neutralized copy of a costume zip for install.

    Reads `zip_path` READ-ONLY. Returns the Path of a temp zip when any DAT
    inside needed converting (caller must unlink it after install), or None
    when the original should be installed as-is (already neutral, not a Falcon
    costume, or conversion failed -- fail-open).
    """
    zip_path = Path(zip_path)
    tmp = None
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = []
            all_notes = []
            any_changed = False
            for info in zf.infolist():
                data = zf.read(info)
                base = Path(info.filename).name
                if not info.is_dir() and is_costume_file(base):
                    buf = bytearray(data)
                    changed, notes = neutralize_dat_bytes(buf)
                    all_notes.extend(f"{base}: {n}" for n in notes)
                    if changed:
                        any_changed = True
                        data = bytes(buf)
                members.append((info, data))
        if not any_changed:
            return None

        fd, tmp_name = tempfile.mkstemp(suffix=".zip",
                                        prefix="nucleus_falcon_nr_",
                                        dir=temp_dir)
        os.close(fd)
        tmp = Path(tmp_name)
        with zipfile.ZipFile(tmp, "w") as out:
            for info, data in members:
                out.writestr(info, data)  # keeps name/date/compress_type
        logger.info("Falcon costume neutralized for install: %s (%s)",
                    zip_path.name, "; ".join(all_notes))
        return tmp
    except Exception as e:
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass
        logger.warning("Falcon neutralize failed for %s -- installing the "
                       "original: %s", zip_path, e)
        return None


def convert_falcon_to_color(data, color):
    """Strict destination-color conversion for replacing a vanilla slot.

    Unlike ordinary neutralized imports, failure must abort replacement. The
    DAT data/relocations remain at their original offsets; rebuild the trailing
    symbol strings because Neutral -> another color needs longer names.
    """
    if color not in ('Nr', 'Re', 'Bu', 'Gr', 'Gy', 'Wh'):
        raise ValueError('Unknown Falcon destination color')
    buf = bytearray(data)
    if len(buf) < 32 or _u32(buf, 0) != len(buf) or _u32(buf, 16):
        raise ValueError('Unsupported Falcon costume archive')
    roots = list(_iter_roots(buf))
    skeletons = [(name, offset) for name, offset in roots if _is_skeleton_root(name)]
    if not skeletons or any(not name.startswith(FALCON_PREFIX) for name, _ in skeletons):
        raise ValueError('Expected a Falcon costume skeleton')
    pattern = re.compile(r'^(PlyCaptain5K)(?:[A-Z][a-z])?(_.+)$')
    token = '' if color == 'Nr' else color
    def rename(name):
        return pattern.sub(lambda match: match[1] + token + match[2], name)
    references = []
    for name, offset in skeletons:
        target = rename(name)
        path = ref_dir() / (target + '.bin')
        if not path.is_file():
            raise ValueError(f'Missing vanilla skeleton reference for Falcon {color}')
        ref = path.read_bytes()
        _walk(buf, ref, offset, -1, {'ref_pos': 0, 'id': 0}, 0, apply_fix=False)
        references.append((offset, ref))
    for offset, ref in references:
        _walk(buf, ref, offset, -1, {'ref_pos': 0, 'id': 0}, 0, apply_fix=True)
    table = 32 + _u32(buf, 4) + _u32(buf, 8) * 4
    strings = table + len(roots) * 8
    rebuilt = buf[:strings]
    names = bytearray()
    for index, (name, _) in enumerate(roots):
        struct.pack_into('>I', rebuilt, table + index * 8 + 4, len(names))
        names.extend(rename(name).encode('ascii') + b'\0')
    rebuilt.extend(names)
    struct.pack_into('>I', rebuilt, 0, len(rebuilt))
    # Verify both identity and transforms in the exact output bytes.
    for name, offset in _iter_roots(rebuilt):
        if _is_skeleton_root(name):
            reference = (ref_dir() / (name + '.bin')).read_bytes()
            if _walk(rebuilt, reference, offset, -1, {'ref_pos': 0, 'id': 0}, 0, apply_fix=False):
                raise ValueError('Falcon destination skeleton verification failed')
    return bytes(rebuilt)
