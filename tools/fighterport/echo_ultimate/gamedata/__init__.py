"""Gameplay data read from Smash Ultimate's own files: attributes, move timing
and hitboxes, with no wiki in between.

Everything here reads files extracted from a decrypted ``data.arc`` (see
``arc.py``); nothing in this package contains game data, and extracted files
stay outside the repository.

    prc.py          .prc parameter files (attributes); names are hash40 values
    motion_list.py  motion_list.bin: per motion its scripts, animation, cancel frame
    nro.py          the fighter's compiled script module (lua2cpp_<fighter>.nro)
    acmd.py         move scripts decoded from that module by following its code
    moves.py        hitboxes with real frame windows, grabs, throws, one call per fighter
    names.py        candidate names for the hashes the files use

Run ``python -m echo_ultimate.gamedata <fighter> --root <dump folder>``.
Checked on Shulk on 2026-11-10: all 36 wiki frame-data rows for his 15 normal
attacks match in frame window, damage, angle and knockback, and 90 of 90 named
attributes match. See ../README.md for the limits.
"""
from .prc import Prc, hash40

__all__ = ['Prc', 'hash40']
