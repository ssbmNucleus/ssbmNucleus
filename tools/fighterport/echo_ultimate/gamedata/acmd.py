"""Read move scripts (hitboxes, grabs, timing) out of a Smash Ultimate
lua2cpp_<fighter>.nro by following the compiled code.

The game's move scripts are compiled C++. Each one builds its arguments as
constants, pushes them on a Lua stack, then calls an imported function such as
app::sv_animcmd::ATTACK. This walks each script linearly, tracks the constants
the code loads into registers, and records every such call with its arguments.
It does not execute anything and does not follow branches, so a value the
script computes at run time shows as None.
"""
import struct
from pathlib import Path

from .nro import Nro
from .prc import hash40

M64 = (1 << 64) - 1


def sext(v, bits):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


def f32(bits):
    return struct.unpack('<f', struct.pack('<I', bits & 0xFFFFFFFF))[0]


def f64(bits):
    return struct.unpack('<d', struct.pack('<Q', bits & M64))[0]


def bitmask(n, imms, immr, size):
    """AArch64 DecodeBitMasks for logical immediates."""
    combo = (n << 6) | (~imms & 0x3F)
    length = combo.bit_length() - 1
    if length < 1:
        return None
    esize = 1 << length
    levels = esize - 1
    s, r = imms & levels, immr & levels
    welem = (1 << (s + 1)) - 1
    welem = ((welem >> r) | (welem << (esize - r))) & ((1 << esize) - 1)
    out = 0
    for i in range(0, size, esize):
        out |= welem << i
    return out & ((1 << size) - 1)


def fp_imm8(imm8):
    a, b, rest = imm8 >> 7, (imm8 >> 6) & 1, imm8 & 0x3F
    exp = ((b ^ 1) << 7) | (0x7C if b else 0) | (rest >> 4)
    return f32((a << 31) | (exp << 23) | ((rest & 0xF) << 19))


class Machine:
    """Constant tracker over a linear run of instructions."""

    def __init__(self, nro: Nro):
        self.n = nro
        self.d = nro.d
        self.reset()

    def reset(self):
        self.R = [None] * 32   # ints, or ('sp', off); index 31 unused
        self.F = [None] * 32

    def rd_mem(self, addr, size):
        if isinstance(addr, int) and 0 <= addr <= len(self.d) - size:
            return int.from_bytes(self.d[addr:addr + size], 'little')
        return None

    def clobber(self):
        for i in range(19):
            self.R[i] = None
        for i in list(range(8)) + list(range(16, 32)):
            self.F[i] = None

    def step(self, pc):
        """Apply one instruction. Returns the call target for BL, else None."""
        i = struct.unpack_from('<I', self.d, pc)[0]
        R, F = self.R, self.F
        rd, rn = i & 31, (i >> 5) & 31
        if (i & 0xFC000000) == 0x94000000:                       # BL
            return pc + (sext(i & 0x3FFFFFF, 26) << 2)
        if (i & 0x1F800000) == 0x12800000:                       # MOVN / MOVZ / MOVK
            opc, sf, hw, imm = (i >> 29) & 3, i >> 31, (i >> 21) & 3, (i >> 5) & 0xFFFF
            mask = M64 if sf else 0xFFFFFFFF
            sh = 16 * hw
            if rd != 31:
                if opc == 2:
                    R[rd] = (imm << sh) & mask
                elif opc == 0:
                    R[rd] = ~(imm << sh) & mask
                elif opc == 3:
                    R[rd] = ((R[rd] & ~(0xFFFF << sh)) | (imm << sh)) & mask if isinstance(R[rd], int) else None
            return None
        if (i & 0x1F800000) == 0x12000000:                       # logical immediate
            opc, sf = (i >> 29) & 3, i >> 31
            val = bitmask((i >> 22) & 1, (i >> 10) & 63, (i >> 16) & 63, 64 if sf else 32)
            if rd != 31:
                R[rd] = val if (opc == 1 and rn == 31) else None
            return None
        if (i & 0x9F000000) == 0x90000000:                       # ADRP
            imm = sext((((i >> 5) & 0x7FFFF) << 2) | ((i >> 29) & 3), 21)
            R[rd] = (pc & ~0xFFF) + (imm << 12)
            return None
        if (i & 0x9F000000) == 0x10000000:                       # ADR
            R[rd] = pc + sext((((i >> 5) & 0x7FFFF) << 2) | ((i >> 29) & 3), 21)
            return None
        if (i & 0x1F000000) == 0x11000000:                       # ADD / SUB immediate
            sub, imm = (i >> 30) & 1, (i >> 10) & 0xFFF
            if (i >> 22) & 1:
                imm <<= 12
            imm = -imm if sub else imm
            src = ('sp', 0) if rn == 31 else R[rn]
            if rd != 31:
                if isinstance(src, int):
                    R[rd] = (src + imm) & (M64 if i >> 31 else 0xFFFFFFFF)
                elif isinstance(src, tuple):
                    R[rd] = (src[0], src[1] + imm)
                else:
                    R[rd] = None
            return None
        if (i & 0x7FE0FFE0) == 0x2A0003E0:                       # MOV reg (ORR with zero reg)
            rm = (i >> 16) & 31
            v = 0 if rm == 31 else R[rm]
            if rd != 31:
                R[rd] = (v & 0xFFFFFFFF) if (isinstance(v, int) and not i >> 31) else v
            return None
        if (i & 0x3B000000) == 0x39000000 and (i >> 22) & 3 == 1:  # LDR unsigned offset (int or fp)
            size = i >> 30
            vec = (i >> 26) & 1
            base = R[rn] if rn != 31 else None
            addr = base + (((i >> 10) & 0xFFF) << size) if isinstance(base, int) else None
            raw = self.rd_mem(addr, 1 << size) if addr is not None else None
            if vec:
                F[rd] = None if raw is None else f32(raw) if size == 2 else f64(raw) if size == 3 else None
            elif rd != 31:
                R[rd] = raw
            return None
        if (i & 0x3B000000) == 0x18000000:                       # LDR literal
            addr = pc + (sext((i >> 5) & 0x7FFFF, 19) << 2)
            opc, vec = i >> 30, (i >> 26) & 1
            if vec:
                raw = self.rd_mem(addr, 4 if opc == 0 else 8)
                F[rd] = None if raw is None else f32(raw) if opc == 0 else f64(raw)
            elif rd != 31:
                R[rd] = self.rd_mem(addr, 8 if opc == 1 else 4)
            return None
        if (i & 0xFF201FE0) == 0x1E201000:                       # FMOV scalar immediate
            v = fp_imm8((i >> 13) & 0xFF)
            F[rd] = v
            return None
        if (i & 0xFFFFFC00) == 0x1E270000:                       # FMOV Sd, Wn
            v = 0 if rn == 31 else R[rn]
            F[rd] = f32(v) if isinstance(v, int) else None
            return None
        if (i & 0xFFFFFC00) == 0x9E670000:                       # FMOV Dd, Xn
            v = 0 if rn == 31 else R[rn]
            F[rd] = f64(v) if isinstance(v, int) else None
            return None
        if (i & 0x9FFFFFE0) == 0x0F00E400:                       # MOVI vN, #0
            F[rd] = 0.0
            return None
        if (i & 0xFFE0FC00) == 0x4EA01C00 and rn == ((i >> 16) & 31):  # MOV Vd, Vn
            F[rd] = F[rn]
            return None
        if (i & 0x3B200C00) == 0x38200800 and (i >> 22) & 3 == 1 and not (i >> 26) & 1:  # LDR reg offset
            idx = R[(i >> 16) & 31]
            if rd != 31:
                R[rd] = ('const', idx) if isinstance(idx, int) else None
            return None
        if (i & 0xFFE0FC00) == 0x1E204000:                       # FMOV Sd, Sn
            F[rd] = F[rn]
            return None
        # anything else: forget whatever it may have written
        if (i & 0x0A000000) == 0x08000000:                       # loads and stores
            is_load = (i >> 22) & 1
            vec = (i >> 26) & 1
            pair = (i & 0x3A000000) == 0x28000000
            if is_load:
                tgt = F if vec else R
                tgt[rd] = None
                if pair:
                    tgt[(i >> 10) & 31] = None
            if not pair and (i & 0x3B200C00) in (0x38000400, 0x38000C00) and rn != 31:
                R[rn] = None                                     # pre/post index writes the base
        elif (i & 0x1C000000) == 0x14000000 or (i & 0x7C000000) == 0x34000000 or (i & 0xFE000000) == 0x54000000:
            pass                                                 # branches
        elif (i & 0x0E000000) == 0x0E000000:                     # FP / SIMD data processing
            if (i & 0xFF200C00) == 0x1E200000 and ((i >> 16) & 7) in (0, 1) and (i >> 19) & 3 == 3:
                R[rd] = None                                     # fp -> int conversions write a general reg
            else:
                F[rd] = None
        elif rd != 31:
            R[rd] = None
        return None


ATTACK_ARGS = ['id', 'part', 'bone', 'damage', 'angle', 'kbg', 'fkb', 'bkb', 'size', 'x', 'y', 'z', 'x2', 'y2', 'z2',
               'hitlag', 'sdi', 'clang', 'facing', 'set_weight', 'shield_damage', 'trip', 'rehit', 'reflectable',
               'absorbable', 'flinchless', 'disable_hitlag', 'direct', 'ground_air', 'hitbits', 'collision_part',
               'friendly_fire', 'effect', 'sfx_level', 'sfx_type', 'type']


def short(sym):
    """'_ZN3app10sv_animcmd6ATTACKEP9lua_State' -> 'ATTACK'; module calls -> 'AttackModule::clear_all'."""
    if not sym:
        return None
    if 'sv_animcmd' in sym:
        tail = sym.split('sv_animcmd', 1)[1]
        n = ''
        while tail and tail[0].isdigit():
            n += tail[0]
            tail = tail[1:]
        return tail[:int(n)] if n else tail
    if 'lua_bind' in sym:
        tail = sym.split('lua_bind', 1)[1]
        n = ''
        while tail and tail[0].isdigit():
            n += tail[0]
            tail = tail[1:]
        name = tail[:int(n)] if n else tail
        return name.replace('__', '::').replace('_impl', '')
    return None


class Scripts:
    def __init__(self, path, names=()):
        self.n = Nro(Path(path).read_bytes())
        self.labels = {hash40(x): x for x in names}
        self.exports = sorted((v, s, nm) for nm, _, sh, v, s in self.n.syms if nm and sh != 0 and s)
        self._helpers = {}
        self.registered = self._find_registrations()
        for r in self.registered:
            r['body'] = self._body(r['func'])
        self.starts = sorted({r['func'] for r in self.registered} | {r['body'] for r in self.registered}
                             | {v for v, _, _ in self.exports})

    def label(self, h):
        return self.labels.get(h, f'0x{h:010x}')

    def _owner(self, addr):
        for v, s, nm in self.exports:
            if v <= addr < v + s:
                for k in ('animcmd_game_share', 'animcmd_game', 'animcmd_effect', 'animcmd_sound', 'animcmd_expression',
                          'status_script', 'ai_action', 'ai_mode'):
                    if k in nm:
                        return k
                return nm
        return '?'

    def _find_registrations(self):
        m = Machine(self.n)
        out = []
        for pc in range(self.n.text_off, self.n.text_off + self.n.text_size, 4):
            tgt = m.step(pc)
            if tgt is None:
                continue
            name = self.n.plt_target(tgt)
            if name and 'sv_set_function_hash' in name:
                fn, hsh = m.R[1], m.R[2]
                if isinstance(fn, int) and isinstance(hsh, int):
                    out.append({'func': fn, 'hash': hsh, 'name': self.label(hsh), 'agent': self._owner(pc)})
            m.clobber()
        return out

    def _body(self, func):
        """A registered entry is a small wrapper; the script itself is the local
        function it calls (or jumps to). Returns that address, else the entry."""
        funcs = sorted({r['func'] for r in self.registered})
        nxt = next((x for x in funcs if x > func), func + 0x100)
        lo, hi = self.n.text_off, self.n.text_off + self.n.text_size
        for pc in range(func, min(nxt, func + 0x100), 4):
            i = self.n.u32(pc)
            if (i & 0x7C000000) == 0x14000000:                   # B or BL
                t = pc + (sext(i & 0x3FFFFFF, 26) << 2)
                inside_wrapper = func <= t < nxt
                if lo <= t < hi and not inside_wrapper and self.n.plt_target(t) is None:
                    return t
        return func

    def helper(self, addr):
        """Name of the sv_animcmd call a local wrapper function ends up making."""
        if addr in self._helpers:
            return self._helpers[addr]
        name = None
        for pc in range(addr, min(addr + 0x1000, self.n.text_off + self.n.text_size), 4):
            i = self.n.u32(pc)
            if i == 0xD65F03C0:
                break
            if (i & 0x7C000000) == 0x14000000:                   # BL, or B (wrappers end in a tail jump)
                sym = self.n.plt_target(pc + (sext(i & 0x3FFFFFF, 26) << 2))
                nm = short(sym) if sym and 'sv_animcmd' in sym else None
                if nm and nm not in ('is_excute', 'frame', 'wait'):
                    name = nm
                    break
                if sym and not i & 0x80000000:
                    break                                        # tail jump to some other import: not a wrapper
        self._helpers[addr] = name
        return name

    def decode(self, func, limit=0x8000):
        nxt = next((s for s in self.starts if s > func), func + limit)
        end = min(nxt, func + limit)
        m = Machine(self.n)
        vals, stack, events, frame, built = {}, [], [], None, []
        for pc in range(func, end, 4):
            tgt = m.step(pc)
            if tgt is None:
                continue
            sym = self.n.plt_target(tgt)
            R, F = m.R, m.F
            if sym is None:
                nm = self.helper(tgt)
                if nm:
                    events.append({'cmd': nm, 'frame': frame, 'args': list(built)})
                    built = []
            if sym:
                if 'L2CValueC1E' in sym:
                    kind = sym.split('L2CValueC1E', 1)[1]
                    key = R[0]
                    if kind == 'f':
                        v = F[0]
                    elif kind == 'b':
                        v = None if R[1] is None else bool(R[1] & 1) if isinstance(R[1], int) else None
                    elif kind.startswith('N3phx6Hash40'):
                        v = self.label(R[1]) if isinstance(R[1], int) else None
                    elif isinstance(R[1], tuple) and R[1][0] == 'const':
                        v = f'<const {R[1][1]:#x}>'            # a named game constant, looked up at run time
                    elif kind in ('i', 'l'):
                        v = sext(R[1] & 0xFFFFFFFF, 32) if isinstance(R[1], int) and kind == 'i' else \
                            sext(R[1], 64) if isinstance(R[1], int) else None
                    elif kind in ('j', 'm'):
                        v = R[1] if isinstance(R[1], int) else None
                    else:
                        v = '<runtime>'
                    if key is not None:
                        vals[key] = v
                    if not kind.startswith('RKS0_'):
                        built.append(v)
                elif 'push_lua_stack' in sym:
                    stack.append(vals.get(R[1], '<runtime>') if R[1] is not None else '<runtime>')
                elif 'clear_lua_stack' in sym:
                    stack = []
                elif sym.endswith('sv_animcmd5frameEP9lua_Statef'):
                    top = stack[-1] if stack else None
                    frame = float(top) if isinstance(top, (int, float)) and not isinstance(top, bool) else F[0]
                    events.append({'cmd': 'frame', 'frame': frame})
                    built = []
                elif sym.endswith('sv_animcmd4waitEP9lua_Statef'):
                    top = stack[-1] if stack else None
                    w = float(top) if isinstance(top, (int, float)) and not isinstance(top, bool) else F[0]
                    events.append({'cmd': 'wait', 'frames': w})
                    frame = frame + w if isinstance(frame, float) and isinstance(w, float) else None
                    built = []
                else:
                    nm = short(sym)
                    if nm and nm not in ('is_excute', 'get_value_float', 'get_value_int', 'execute'):
                        ev = {'cmd': nm, 'frame': frame, 'args': list(stack)}
                        if 'lua_bind' in sym:
                            ev['regs'] = [R[1], R[2], F[0]]
                            ev['made'] = list(built)   # values built just before the call
                        events.append(ev)
                        built = []
            m.clobber()
        return events


