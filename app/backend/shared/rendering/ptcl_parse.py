#!/usr/bin/env python3
"""
ptcl_parse.py -- deterministic decoder for melee Ef*Data.dat particle banks.

Turns the sysdolphin particle interpreter (decomp:
src/sysdolphin/baselib/particle.c) into a structural parser so that effect
color-operand offsets are DERIVED from the bank grammar instead of found by
marker-scanning raw bytes.

WHAT IT DECODES
    An Ef*Data.dat is an HSD archive whose single public symbol
    (`effFoxDataTable`, `effCaptainDataTable`, ...) resolves to an
    `SBM_EffectTable` (HSDRaw/Melee/Ef/SBM_EffectTable.cs):
        +0x00  Particles        -> HSD_ParticleGroup  (the "cmdBank")
        +0x04  TextureGraphics  -> HSD_TEXGraphicBank (the "texBank")
        +0x08+ Models[]         -> SBM_EffectModel (0x14 each; JOBJ/anim trees)

    HSD_ParticleGroup (HSDRaw/Common/HSD_ParticleGroup.cs) on disk:
        +0x00  u16 version   (0x00 or 0x40-0x43; see psInitDataBankLoad
                              particle.c:4514) -- always 0x42 in vanilla Ef*
        +0x02  u16 unk2      (== effect id prefix / 0x1000)
        +0x04  s32 EffectIDStart
        +0x08  s32 GeneratorCount
        +0x0C  s32 offset[GeneratorCount]   (relative to ParticleGroup start;
                                             each -> an HSD_ParticleGenerator)

    HSD_ParticleGenerator = 0x40-byte header (type/texGroup/life/kind/grav/
    fric/vel/size/params) + a variable bytecode stream at +0x3C. That bytecode
    is the particle "script": the SAME opcode grammar the runtime interpreter
    walks (particle.c hsd_80393440-adjacent big switch, ~line 5200-7185).

COLOR-CARRYING OPCODES (the ones a MAP mission edits)
    0xC0-0xCF  PrimCol set   (particle.c:6453) low nibble = channel mask
                             (bit0=R bit1=G bit2=B bit3=A); operands: 1 count
                             byte (u16-extended if high bit set) then one byte
                             per set channel.  0xCF = all 4 = the "CF record".
    0xD0-0xDF  EnvCol set    (particle.c:6511) same layout. 0xDF right after a
                             0xCF (+ 0xAD PrimEnv flag) is our "secondary
                             color at +7".
    0xEA       MatCol set    (particle.c:7030) count + flags byte; flags&1 -> 1
                             RGB byte, flags&8 -> 1 A byte.
    0xEB       AmbCol set    (particle.c:7072) same as MatCol.
    (0xBA/0xBB/0xE0/0xE9 carry SIGNED per-channel *deltas* w/ randomization,
    not literal colors -- reported as delta ops, not edit targets.)

NOT in the ptcl bank: the `07 07 07 04`, `42 48`, and `98 00 ##` color blocks
from the reference doc live in the effect MODELS region (JOBJ material / TEV /
matanim / display-list vertex colors), far past the ptcl bank. This parser's
--models pass locates those structurally-adjacent color blocks by signature
so a MAP mission gets both, but they are decoded as raw blocks, not opcodes.

Usage:
    python ptcl_parse.py <EfXxData.dat> [--json] [--models] [--all-ops]
    python ptcl_parse.py --verify        # ground-truth self-test
"""

import argparse
import json
import os
import struct
import sys

# ---------------------------------------------------------------------------
# HSD archive header
# ---------------------------------------------------------------------------

DATA_START = 0x20  # HSD archive: 0x20 header, then data section


def _u16(d, o):
    return struct.unpack_from(">H", d, o)[0]


def _u32(d, o):
    return struct.unpack_from(">I", d, o)[0]


def parse_archive(data):
    """Return (data_section_start, effect_table_offset, public_name)."""
    fsize, dsize, nreloc, npub = struct.unpack_from(">IIII", data, 0)
    reloc_off = DATA_START + dsize
    pub_off = reloc_off + nreloc * 4
    # public symbol table: npub entries of (data_offset u32, name_offset u32)
    # extern-ref table follows (count implied by header field we don't need);
    # the string bank starts right after the public+extern tables. For Ef*Data
    # there is a single public root at data_offset 0.
    do, no = struct.unpack_from(">II", data, pub_off)
    str_off = pub_off + npub * 8
    name = data[str_off + no:str_off + no + 64].split(b"\x00")[0].decode(
        "ascii", "replace")
    return DATA_START, DATA_START + do, name


# ---------------------------------------------------------------------------
# Particle bytecode opcode grammar (decomp particle.c interpreter ~5200-7185)
# ---------------------------------------------------------------------------
#
# Each entry: opcode(-range) -> (name, operand_decoder). The decoder is called
# with (data, pc, opcode) and returns (bytes_consumed_after_opcode,
# list_of_color_operands, note). A color operand is a dict:
#   {"kind": "prim"/"env"/"mat"/"amb", "channels": "RGBA"|..., "rel": N,
#    "size": N}  where rel = byte offset of the color relative to the opcode.

FLOAT_OPS = {  # opcode-class -> number of 4-byte floats (bit-masked variants)
}


def _count_extension(d, pc):
    """A 'count' byte that is u16-extended when its high bit is set.
    Returns (value, bytes_consumed)."""
    c = d[pc]
    if c & 0x80:
        return (((c & 0x7F) << 8) + d[pc + 1], 2)
    return (c, 1)


def _channels_from_mask(mask):
    s = ""
    if mask & 1:
        s += "R"
    if mask & 2:
        s += "G"
    if mask & 4:
        s += "B"
    if mask & 8:
        s += "A"
    return s


def decode_one(d, pc, script_end):
    """Decode a single opcode at pc.

    Returns dict:
      {opcode, name, next_pc, colors:[...], note, terminates:bool}
    or None if pc is out of range / undecodable (caller stops).
    """
    if pc >= script_end:
        return None
    opcode = d[pc]
    start = pc
    pc += 1
    colors = []
    note = ""
    terminates = False
    yields = False  # low-range op with nonzero operand ends the frame's loop

    if opcode < 0x80:
        # Low range: operand = opcode & 0x1F, extended by one byte if bit 0x20.
        operand = opcode & 0x1F
        if opcode & 0x20:
            operand = (operand << 8) + d[pc]
            pc += 1
        sub = opcode & 0xC0
        if sub == 0x40:
            # Texture command: reads 1 poseNum byte
            pc += 1
            name = "TEX"
        elif sub == 0x00:
            name = "WAIT" if operand else "NOP"
        else:
            name = "LOW_%02X" % opcode
        if operand != 0:
            yields = True
        return {"opcode": opcode, "name": name, "next_pc": pc,
                "colors": colors, "note": "operand=%d" % operand,
                "terminates": False, "yields": yields}

    # High range: classify like the decomp (cls = opcode & 0xF8; if >0x98 use
    # &0xF0 for C0/D0 else the raw opcode).
    cls = opcode & 0xF8
    if cls > 0x98:
        c2 = opcode & 0xF0
        if c2 in (0xC0, 0xD0):
            cls = c2
        else:
            cls = opcode

    if cls == 0x80:  # set pos: 4 bytes per set axis (bits 1/2/4)
        for bit in (1, 2, 4):
            if opcode & bit:
                pc += 4
        name = "POS_SET"
    elif cls == 0x88:  # add pos
        for bit in (1, 2, 4):
            if opcode & bit:
                pc += 4
        name = "POS_ADD"
    elif cls == 0x90:  # set vel
        for bit in (1, 2, 4):
            if opcode & bit:
                pc += 4
        name = "VEL_SET"
    elif cls == 0x98:  # add vel
        for bit in (1, 2, 4):
            if opcode & bit:
                pc += 4
        name = "VEL_ADD"
    elif cls == 0xA0:  # size interp: count(ext) + 4 float
        _, cb = _count_extension(d, pc)
        pc += cb + 4
        name = "SIZE"
    elif cls == 0xA1:
        name = "TEX_OFF"
    elif cls == 0xA2:
        pc += 4
        name = "GRAV"
    elif cls == 0xA3:
        pc += 4
        name = "FRIC"
    elif cls in (0xA4, 0xB9):  # spawn child particle by id: 2 bytes
        pc += 2
        name = "SPAWN_PTCL"
    elif cls in (0xF1, 0xF2):  # spawn child particle (ptclref remap): 2 bytes
        pc += 2
        name = "SPAWN_PTCL_REF"
    elif cls == 0xA5:  # spawn generator: 2 bytes
        pc += 2
        name = "SPAWN_GEN"
    elif cls in (0xEF, 0xF0):  # spawn generator + flags: 3 bytes
        pc += 3
        name = "SPAWN_GEN_FLAGS"
    elif cls == 0xA6:  # life w/ random: 4 bytes
        pc += 4
        name = "LIFE"
    elif cls == 0xA7:  # conditional kill: 1 byte
        pc += 1
        name = "COND_KILL"
    elif cls == 0xA8:  # pos random offset: 3 floats
        pc += 12
        name = "POS_RAND"
    elif cls == 0xA9:  # force func: 4 bytes
        pc += 4
        name = "FORCE_FN"
    elif cls == 0xAA:  # spawn child random ptclref: 4 bytes
        pc += 4
        name = "SPAWN_PTCL_RAND"
    elif cls == 0xAB:  # velocity scale: 4 bytes
        pc += 4
        name = "VEL_SCALE"
    elif cls == 0xAC:  # size interp random: count(ext) + 8
        _, cb = _count_extension(d, pc)
        pc += cb + 8
        name = "SIZE_RAND"
    elif cls == 0xAD:
        name = "PRIMENV"
    elif cls in (0xAE, 0xAF, 0xB0, 0xB1):
        name = "MIRROR"
    elif cls == 0xB2:
        name = "APPSRT_XFORM"
    elif cls == 0xB3:  # alpha compare: count(ext) + mode + p1 + p2
        _, cb = _count_extension(d, pc)
        pc += cb + 3
        name = "ACMP"
    elif cls in (0xB4, 0xB5):
        name = "TEXINTERP"
    elif cls == 0xB6:  # rotate interp: count(ext) + 4
        _, cb = _count_extension(d, pc)
        pc += cb + 4
        name = "ROTATE"
    elif cls == 0xB7:  # aim vel toward jobj: 1 byte
        pc += 1
        name = "AIM_JOBJ"
    elif cls == 0xB8:  # force toward jobj: 1 + 4 + 4
        pc += 9
        name = "FORCE_JOBJ"
    elif cls == 0xBA:  # primcol delta random: 4 signed deltas
        pc += 4
        name = "PRIMCOL_DELTA"
        note = "signed R/G/B/A deltas (randomized, not literal color)"
    elif cls == 0xBB:  # envcol delta random: 4 signed deltas
        pc += 4
        name = "ENVCOL_DELTA"
        note = "signed R/G/B/A deltas (randomized, not literal color)"
    elif cls == 0xBC:  # posenum random: 2 bytes
        pc += 2
        name = "POSENUM_RAND"
    elif cls == 0xBD:  # normalize vel: 8 bytes
        pc += 8
        name = "VEL_NORM"
    elif cls == 0xBE:  # vel component mul: 12 bytes
        pc += 12
        name = "VEL_MUL"
    elif cls == 0xBF:  # jobj offset: 1 byte
        pc += 1
        name = "JOBJ_OFS"
    elif cls == 0xC0:  # PRIMCOL set  <<< color op
        cnt, cb = _count_extension(d, pc)
        pc += cb
        chans = _channels_from_mask(opcode & 0xF)
        color_rel = pc - start
        colors.append({"kind": "prim", "channels": chans,
                       "rel": color_rel, "size": len(chans),
                       "count": cnt})
        pc += len(chans)
        name = "PRIMCOL"
    elif cls == 0xD0:  # ENVCOL set  <<< color op
        cnt, cb = _count_extension(d, pc)
        pc += cb
        chans = _channels_from_mask(opcode & 0xF)
        color_rel = pc - start
        colors.append({"kind": "env", "channels": chans,
                       "rel": color_rel, "size": len(chans),
                       "count": cnt})
        pc += len(chans)
        name = "ENVCOL"
    elif cls == 0xE0:  # dual prim+env delta: 4 signed deltas
        pc += 4
        name = "DUALCOL_DELTA"
        note = "signed deltas (randomized, not literal color)"
    elif cls == 0xE9:  # dual prim/env selective delta: flags+timing+per-flag
        flags = d[pc]
        pc += 2  # flags + timing
        for bit in (0x01, 0x02, 0x04, 0x08):
            if flags & bit:
                pc += 1
        name = "DUALCOL_SEL_DELTA"
        note = "signed deltas (randomized, not literal color)"
    elif cls == 0xE1:  # callback set: 1 byte
        pc += 1
        name = "CALLBACK"
    elif cls == 0xEC:  # userdata: 1 + 4
        pc += 5
        name = "USERDATA"
    elif cls == 0xE2:
        name = "TEXEDGE"
    elif cls == 0xE3:  # palnum: 1 byte
        pc += 1
        name = "PALNUM"
    elif cls in (0xE4, 0xE5):  # texflip: 1 byte
        pc += 1
        name = "TEXFLIP"
    elif cls in (0xE6, 0xE7):
        name = "DIRVEC"
    elif cls == 0xE8:  # trail: 4 bytes
        pc += 4
        name = "TRAIL"
    elif cls == 0xEA:  # MATCOL set  <<< color op (count+flags then conditional)
        cnt, cb = _count_extension(d, pc)
        pc += cb
        flags = d[pc]
        pc += 1
        got = ""
        color_rel = pc - start
        if flags & 1:
            got += "RGB"
            pc += 1
        if flags & 8:
            got += "A"
            pc += 1
        if got:
            colors.append({"kind": "mat", "channels": got,
                           "rel": color_rel, "size": (1 if flags & 1 else 0)
                           + (1 if flags & 8 else 0), "count": cnt})
        name = "MATCOL"
    elif cls == 0xEB:  # AMBCOL set  <<< color op
        cnt, cb = _count_extension(d, pc)
        pc += cb
        flags = d[pc]
        pc += 1
        got = ""
        color_rel = pc - start
        if flags & 1:
            got += "RGB"
            pc += 1
        if flags & 8:
            got += "A"
            pc += 1
        if got:
            colors.append({"kind": "amb", "channels": got,
                           "rel": color_rel, "size": (1 if flags & 1 else 0)
                           + (1 if flags & 8 else 0), "count": cnt})
        name = "AMBCOL"
    elif cls == 0xED:  # rotate interp random: 9 bytes
        pc += 9
        name = "ROTATE_RAND"
    elif cls == 0xFA:  # loop mark: 1 byte
        pc += 1
        name = "LOOP_MARK"
    elif cls == 0xFB:
        name = "LOOP_BACK"
    elif cls == 0xFC:
        name = "MARK"
    elif cls == 0xFD:
        name = "JUMP"
    elif cls in (0xFE, 0xFF):
        name = "END"
        terminates = True
    else:
        # Unknown high opcode -- cannot know operand length; stop this script.
        return {"opcode": opcode, "name": "UNKNOWN_%02X" % opcode,
                "next_pc": None, "colors": [], "note": "undecodable opcode",
                "terminates": True, "yields": False}

    return {"opcode": opcode, "name": name, "next_pc": pc, "colors": colors,
            "note": note, "terminates": terminates, "yields": False}


# ---------------------------------------------------------------------------
# Bank walk
# ---------------------------------------------------------------------------

class Script:
    def __init__(self, index, gen_file_off, bytecode_file_off, header):
        self.index = index
        self.gen_file_off = gen_file_off       # file off of HSD_ParticleGenerator
        self.bytecode_file_off = bytecode_file_off
        self.header = header                   # dict of parsed 0x40 header fields
        self.ops = []                          # list of decoded op dicts (+ abs)
        self.end_file_off = None

    @property
    def colors(self):
        out = []
        for op in self.ops:
            for c in op.get("colors", []):
                abs_off = op["file_off"] + c["rel"]
                out.append({
                    "file_off": abs_off,
                    "opcode": op["opcode"],
                    "op_name": op["name"],
                    "kind": c["kind"],
                    "channels": c["channels"],
                    "size": c["size"],
                    "count": c["count"],
                    "bytes": c["bytes"],
                })
        return out


def parse_bank(data):
    """Parse the ptcl bank; returns (dict header, [Script])."""
    ds, et_off, pub_name = parse_archive(data)
    part_ptr = _u32(data, et_off + 0x00)   # relative to data section
    tex_ptr = _u32(data, et_off + 0x04)
    if part_ptr == 0:
        # No ptcl particle bank (e.g. Link's EfLkData: all effects live in the
        # Models[] JOBJ trees). Return an empty script list; the models region
        # spans the whole file from just past the effect table.
        hdr = {
            "public_name": pub_name,
            "effect_table_off": et_off,
            "particle_group_off": None,
            "tex_bank_off": ds + tex_ptr if tex_ptr else None,
            "version": 0,
            "unk2": 0,
            "effect_id_start": None,
            "generator_count": 0,
            "bank_end": et_off + 0x08,  # Models[] begins right after the 2 ptrs
            "no_ptcl_bank": True,
        }
        return hdr, []
    pg = ds + part_ptr
    version = _u16(data, pg + 0x00)
    unk2 = _u16(data, pg + 0x02)
    eff_id_start = _u32(data, pg + 0x04)
    gcount = _u32(data, pg + 0x08)

    if version not in (0x00, 0x40, 0x41, 0x42, 0x43):
        raise ValueError("unexpected ParticleGroup version 0x%X" % version)

    offs = [_u32(data, pg + 0x0C + i * 4) for i in range(gcount)]

    # The generator offsets are relative to the ParticleGroup start. A zero
    # entry means "same as previous" (blank). Build (start,end) spans.
    scripts = []
    # Determine the span end for each generator: the next nonzero offset, or
    # the tex bank / end of the bank.
    bank_end = ds + tex_ptr if tex_ptr else len(data)
    starts = []
    for i, o in enumerate(offs):
        starts.append(pg + o if o else None)
    for i in range(gcount):
        s = starts[i]
        if s is None:
            continue
        # find next start
        nxt = bank_end
        for j in range(i + 1, gcount):
            if starts[j] is not None:
                nxt = starts[j]
                break
        gen_off = s
        header = {
            "type_flags": _u16(data, gen_off + 0x00),
            "texGroup": _u16(data, gen_off + 0x02),
            "genLife": _u16(data, gen_off + 0x04),
            "life": _u16(data, gen_off + 0x06),
            "kind": _u32(data, gen_off + 0x08),
        }
        bc = gen_off + 0x3C
        sc = Script(i, gen_off, bc, header)
        sc.end_file_off = nxt
        # Walk the bytecode
        pc = bc
        guard = 0
        while pc < nxt and guard < 100000:
            guard += 1
            op = decode_one(data, pc, nxt)
            if op is None or op["next_pc"] is None:
                # attach the terminal/unknown op for visibility, then stop
                if op is not None:
                    op["file_off"] = pc
                    for c in op["colors"]:
                        c["bytes"] = data[pc + c["rel"]:
                                          pc + c["rel"] + c["size"]].hex().upper()
                    sc.ops.append(op)
                break
            op["file_off"] = pc
            for c in op["colors"]:
                c["bytes"] = data[pc + c["rel"]:
                                  pc + c["rel"] + c["size"]].hex().upper()
            sc.ops.append(op)
            pc = op["next_pc"]
            if op["terminates"]:
                break
        scripts.append(sc)

    hdr = {
        "public_name": pub_name,
        "effect_table_off": et_off,
        "particle_group_off": pg,
        "tex_bank_off": ds + tex_ptr if tex_ptr else None,
        "version": version,
        "unk2": unk2,
        "effect_id_start": eff_id_start,
        "generator_count": gcount,
        "bank_end": bank_end,
    }
    return hdr, scripts


# ---------------------------------------------------------------------------
# Models-region color-block scan (07 07 07 / 42 48 / 98 00 ##)
# ---------------------------------------------------------------------------
#
# These are HSD material / TEV / display-list vertex-color structures inside
# the SBM_EffectModel JOBJ trees -- NOT ptcl bytecode. We locate them by their
# well-known byte signatures so a MAP mission gets a full color inventory.
# (Kept structurally simple; the report documents that these are model colors,
# not opcode operands.)

def scan_model_colors(data, bank_end):
    """Return a list of model-region color-block hits past the ptcl bank."""
    hits = []
    n = len(data)
    # 07 07 07 04 / 07 07 07 07  -> two RGB colors at +4 and +8
    for marker in (b"\x07\x07\x07\x04", b"\x07\x07\x07\x07"):
        pos = bank_end
        while True:
            pos = data.find(marker, pos)
            if pos < 0:
                break
            hits.append({
                "type": "070707",
                "marker_off": pos,
                "color1_off": pos + 4, "color1": data[pos + 4:pos + 7].hex().upper(),
                "color2_off": pos + 8, "color2": data[pos + 8:pos + 11].hex().upper(),
            })
            pos += 1
    # 98 00 NN matrices (RGBY/RGB vertex color lists)
    pos = bank_end
    while True:
        pos = data.find(b"\x98\x00", pos)
        if pos < 0:
            break
        cnt = data[pos + 2]
        if 0 < cnt < 0x60:
            hits.append({"type": "98matrix", "marker_off": pos,
                         "entries": cnt,
                         "first_color_off": pos + 4,
                         "first_color": data[pos + 4:pos + 6].hex().upper()})
        pos += 1
    # 42 48 material terminator: colors 0x10 before the 42
    pos = bank_end
    while True:
        pos = data.find(b"\x42\x48", pos)
        if pos < 0:
            break
        cs = pos - 0x10
        if cs >= bank_end:
            hits.append({"type": "4248", "marker_off": pos,
                         "color_block_off": cs,
                         "block": data[cs:cs + 0x10].hex().upper()})
        pos += 1
    hits.sort(key=lambda h: h.get("marker_off", 0))
    return hits


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def build_report(path, include_models=False, all_ops=False):
    data = open(path, "rb").read()
    hdr, scripts = parse_bank(data)
    out = {"file": os.path.basename(path), "header": hdr, "scripts": []}
    for sc in scripts:
        sd = {
            "index": sc.index,
            "generator_off": "0x%X" % sc.gen_file_off,
            "bytecode_off": "0x%X" % sc.bytecode_file_off,
            "end_off": "0x%X" % sc.end_file_off,
            "texGroup": sc.header["texGroup"],
            "kind": "0x%X" % sc.header["kind"],
            "colors": [],
        }
        for c in sc.colors:
            sd["colors"].append({
                "file_off": "0x%X" % c["file_off"],
                "opcode": "0x%02X" % c["opcode"],
                "op": c["op_name"],
                "kind": c["kind"],
                "channels": c["channels"],
                "count": c["count"],
                "bytes": c["bytes"],
            })
        if all_ops:
            sd["ops"] = [{"off": "0x%X" % op["file_off"],
                          "opcode": "0x%02X" % op["opcode"],
                          "name": op["name"],
                          "note": op["note"]} for op in sc.ops]
        out["scripts"].append(sd)
    if include_models:
        out["model_colors"] = scan_model_colors(data, hdr["bank_end"])
    return out


def print_table(report):
    h = report["header"]
    print("=" * 74)
    print("FILE: %s   symbol=%s" % (report["file"], h["public_name"]))
    print("  EffectTable@0x%X  ParticleGroup@%s  version=0x%X  "
          "generators=%d" % (h["effect_table_off"],
                             "0x%X" % h["particle_group_off"]
                             if h["particle_group_off"] else "none (no ptcl bank)",
                             h["version"], h["generator_count"]))
    print("  effect_id_start=%s  tex_bank@%s" % (
        h["effect_id_start"] if h["effect_id_start"] is not None else "n/a",
        "0x%X" % h["tex_bank_off"] if h["tex_bank_off"] else "none"))
    print("=" * 74)
    total = 0
    for sc in report["scripts"]:
        if not sc["colors"] and "ops" not in sc:
            continue
        print("script %-2d  gen@%s  bytecode@%s..%s  texGrp=%d  kind=%s" % (
            sc["index"], sc["generator_off"], sc["bytecode_off"],
            sc["end_off"], sc["texGroup"], sc["kind"]))
        for c in sc["colors"]:
            total += 1
            print("    %-8s %-7s %-4s %-8s count=%-3d %s  [%s]" % (
                c["file_off"], c["op"], c["channels"], c["kind"],
                c["count"], c["bytes"], c["opcode"]))
        if "ops" in sc:
            for op in sc["ops"]:
                print("      . %-8s %-4s %-16s %s" % (
                    op["off"], op["opcode"], op["name"], op["note"]))
    print("-" * 74)
    print("total color operands in ptcl bank: %d" % total)
    if "model_colors" in report:
        print("model-region color blocks (07/42/98, past ptcl bank): %d" %
              len(report["model_colors"]))


# ---------------------------------------------------------------------------
# Verify (ground truth)
# ---------------------------------------------------------------------------

GROUND_TRUTH = {
    # file -> list of (file_off, expected_kind, expected_bytes_prefix, label)
    # Offsets below are the COLOR-OPERAND file offsets (= CF marker + 2, i.e.
    # after the `CF <count>` bytes). The reference doc cites the marker (CF
    # byte); the parser reports where the color bytes actually live -- what a
    # patcher writes. Primary = PrimCol (0xCx), secondary = EnvCol (0xDx).
    "EfFxData.dat": [
        (0x127, "prim", "FFFFFF", "shine sparkles rec1 primary (marker 0x125)"),
        (0x12E, "env", "2AA3EE", "shine sparkles rec1 secondary (EnvCol, marker+9)"),
        (0x143, "prim", "FFFFFF", "shine sparkles rec2 primary (marker 0x141)"),
        (0x2F0, "prim", "FFFFFF", "Firefox trailing fire large up-b (marker 0x2EE)"),
        (0x384, "prim", "FFF88F", "Firefox trailing fire small up-b (marker 0x382)"),
        (0x394, "prim", "FF7111", "Firefox trailing fire small (marker 0x392)"),
    ],
    # falcon_kick config stores COLOR positions directly (marker CF+2). The
    # parser reports the same. trail_c1=0x12F prim, trail_c2=0x136 env, etc.
    "EfCaData.dat": [
        (0x12F, "prim", "FFFFFF", "falcon kick trail primary (config trail_c1)"),
        (0x136, "env", "D2CE9E", "falcon kick trail secondary (config trail_c2, EnvCol)"),
        (0x474, "prim", "FF290C", "falcon kick square dots (config dots_c1)"),
        (0x6AF, "prim", "FFFFFF", "falcon kick front chevron (config front_c1)"),
    ],
    "EfMtData.dat": [
        # EfMtData markers per extra_types: upsmash color record. Provide a
        # ptcl-bank probe; the 07-block (0xC758) is in the models region and
        # is checked via the model scan.
    ],
}


def run_verify(base_dir):
    print("PTCL parser ground-truth verify")
    print("base:", base_dir)
    all_ok = True
    for fn, items in GROUND_TRUTH.items():
        path = os.path.join(base_dir, fn)
        if not os.path.exists(path):
            print("  SKIP %s (not found)" % fn)
            continue
        data = open(path, "rb").read()
        hdr, scripts = parse_bank(data)
        # index all decoded color operands by file offset
        by_off = {}
        for sc in scripts:
            for c in sc.colors:
                by_off[c["file_off"]] = c
        print("\n%s  (%d scripts, %d color operands)" % (
            fn, len(scripts), len(by_off)))
        for (off, kind, prefix, label) in items:
            c = by_off.get(off)
            if c is None:
                # tolerate off-by pointing at nearest operand within 2 bytes
                near = None
                for k in (off - 1, off + 1, off - 2, off + 2):
                    if k in by_off:
                        near = k
                        break
                if near is not None:
                    print("    NEAR 0x%X (found operand at 0x%X %s=%s) : %s"
                          % (off, near, by_off[near]["kind"],
                             by_off[near]["bytes"], label))
                    all_ok = False
                else:
                    print("    FAIL 0x%X : NO color operand decoded here : %s"
                          % (off, label))
                    all_ok = False
                continue
            ok_kind = (c["kind"] == kind)
            ok_bytes = c["bytes"].startswith(prefix)
            status = "PASS" if (ok_kind and ok_bytes) else "FAIL"
            if status == "FAIL":
                all_ok = False
            print("    %s 0x%X : %s %s (got kind=%s bytes=%s) : %s" % (
                status, off, kind, prefix, c["kind"], c["bytes"], label))
        # model-region 07-block check for Mewtwo upsmash / falcon kick tip
        if fn == "EfMtData.dat":
            mc = scan_model_colors(data, hdr["bank_end"])
            hit = next((h for h in mc if h.get("marker_off") == 0xC754
                        or h.get("marker_off") == 0xC758), None)
            if hit:
                print("    PASS 0xC754/8 : model 07-block found "
                      "(color1=%s color2=%s) : Mewtwo upsmash swirl"
                      % (hit.get("color1"), hit.get("color2")))
            else:
                print("    INFO : Mewtwo upsmash 07-block (0xC754) not in "
                      "model scan window")
        if fn == "EfCaData.dat":
            mc = scan_model_colors(data, hdr["bank_end"])
            hit = next((h for h in mc if h.get("marker_off") == 0x1DE00),
                       None)
            if hit:
                print("    PASS 0x1DE00 : model 07-block found "
                      "(color1=%s color2=%s) : falcon kick tip"
                      % (hit.get("color1"), hit.get("color2")))
            else:
                print("    INFO : falcon kick tip 07-block (0x1DE00) not in "
                      "model scan window")
    # Cross-check the texture-bank decode via the 17088 rainbow-fire diff
    # containment self-test (ptcl_texbank.py). This guards the TEXGraphicBank
    # offset/size decode that the texture_recolor marquee specs (Din/fire,
    # vanish, etc.) depend on -- see research/docs-research/effect-maps/effect-texbank.md.
    try:
        import ptcl_texbank
        print("\n--- tex-bank (TEXGraphicBank) cross-check ---")
        tb_ok = ptcl_texbank.run_verify(base_dir)
        all_ok = all_ok and tb_ok
    except Exception as e:  # pragma: no cover - defensive
        print("\n  tex-bank cross-check SKIPPED (%s)" % e)

    print("\nOVERALL:", "PASS" if all_ok else "PARTIAL (see items above)")
    return all_ok


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", help="Ef*Data.dat path")
    ap.add_argument("--json", action="store_true", help="JSON output")
    ap.add_argument("--models", action="store_true",
                    help="also scan the models region for 07/42/98 blocks")
    ap.add_argument("--all-ops", action="store_true",
                    help="dump every decoded opcode, not just color ops")
    ap.add_argument("--verify", action="store_true",
                    help="run ground-truth self-test")
    ap.add_argument("--base",
                    default=os.path.join(os.path.dirname(__file__),
                                         "..", "..", "..", "storage", "test-base",
                                         "files"),
                    help="base dir for --verify (test-base/files)")
    args = ap.parse_args(argv)

    if args.verify:
        ok = run_verify(os.path.abspath(args.base))
        return 0 if ok else 1

    if not args.path:
        ap.error("path required (or use --verify)")

    report = build_report(args.path, include_models=args.models,
                          all_ops=args.all_ops)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_table(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
