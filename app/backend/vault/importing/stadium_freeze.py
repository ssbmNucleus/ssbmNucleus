"""
Freezing Pokemon Stadium on its normal form: patch the transformation
scheduling ranges in a GrPs-family DAT so the stage never transforms.
"""

from __future__ import annotations

import struct
from vault.importing.stadium_dat import RepairError, Dat


# -- transformation freeze -------------------------------------------------
# yakumono_param's first four ints are the transform scheduling ranges:
# frames until the FIRST transformation (lo, hi) and between subsequent ones
# (lo, hi).  Vanilla ships 3600..3800 / 1200..1800; every surveyed community
# variant keeps those values.  Setting the ranges effectively-infinite
# freezes the stadium in its normal form -- the file-level equivalent of
# "Frozen Stadium", netplay-consistent because both peers share the build.
# Under the m-ex DAS framework the GOVERNING copy of yakumono_param is the
# framework file (files/GrPs.usd), not the individual alts.
YAKU_VANILLA = (3600, 3800, 1200, 1800)
YAKU_FROZEN = (0x7FFFFFFF, 0x7FFFFFFF, 0x7FFFFFFF, 0x7FFFFFFF)


def freeze_stadium_transformations(data: bytes, frozen: bool) -> tuple:
    """Patch the transform scheduling ranges in a GrPs-family DAT.

    Returns (patched_bytes, report).  Unfreezing restores the vanilla
    ranges (the only values observed in the wild)."""
    dat = Dat(data)
    yaku = dat.symbols.get("yakumono_param")
    if yaku is None:
        raise RepairError("no yakumono_param symbol -- not a stadium file")
    old = struct.unpack_from(">4i", dat.b, 0x20 + yaku)
    new = YAKU_FROZEN if frozen else YAKU_VANILLA
    struct.pack_into(">4i", dat.b, 0x20 + yaku, *new)
    report = {
        "frozen": frozen,
        "previous": list(old),
        "applied": list(new),
        "was_frozen": tuple(old) == YAKU_FROZEN,
    }
    return bytes(dat.b), report
