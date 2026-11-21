"""Minimal reader for a Switch NRO module: segments, dynamic symbols, and the
map from call targets (PLT stubs) to imported function names."""
import struct


class Nro:
    def __init__(self, data: bytes):
        self.d = data
        if data[0x10:0x14] != b'NRO0':
            raise ValueError('not an NRO')
        self.mod0 = struct.unpack_from('<I', data, 4)[0]
        self.text_off, self.text_size, self.ro_off, self.ro_size, self.data_off, self.data_size = \
            struct.unpack_from('<6I', data, 0x20)
        if data[self.mod0:self.mod0 + 4] != b'MOD0':
            raise ValueError('MOD0 header not found')
        dyn = self.mod0 + struct.unpack_from('<i', data, self.mod0 + 4)[0]
        self.dyn = {}
        o = dyn
        while True:
            tag, val = struct.unpack_from('<QQ', data, o)
            if tag == 0:
                break
            self.dyn.setdefault(tag, val)
            o += 16
        self.strtab, self.symtab = self.dyn[5], self.dyn[6]
        self.strsz = self.dyn[10]
        # the symbol table runs up to the string table in these modules
        self.nsyms = (self.strtab - self.symtab) // 24 if self.strtab > self.symtab else 0
        self.syms = []
        for i in range(self.nsyms):
            name, info, other, shndx, value, size = struct.unpack_from('<IBBHQQ', data, self.symtab + i * 24)
            self.syms.append((self.cstr(self.strtab + name) if name < self.strsz else '', info, shndx, value, size))
        # PLT relocations: GOT slot -> symbol
        self.got = {}
        for tag_rel, tag_sz in ((23, 2), (7, 8)):
            rel, sz = self.dyn.get(tag_rel), self.dyn.get(tag_sz)
            if rel is None or sz is None:
                continue
            for i in range(sz // 24):
                off, info, addend = struct.unpack_from('<QQq', data, rel + i * 24)
                sym, typ = info >> 32, info & 0xFFFFFFFF
                if sym and sym < len(self.syms):
                    self.got[off] = self.syms[sym][0]
        self._plt = {}

    def cstr(self, o):
        return self.d[o:self.d.index(b'\0', o)].decode('ascii', 'replace')

    def u32(self, o):
        return struct.unpack_from('<I', self.d, o)[0]

    def plt_target(self, addr):
        """Name of the import a PLT stub at `addr` jumps to, else None.
        Stub: adrp x16, page; ldr x17, [x16, #off]; add x16, x16, #off; br x17"""
        if addr in self._plt:
            return self._plt[addr]
        name = None
        if 0 <= addr < len(self.d) - 16:
            a, b = self.u32(addr), self.u32(addr + 4)
            if (a & 0x9F00001F) == 0x90000010 and (b & 0xFFC003FF) == 0xF9400211:
                immlo, immhi = (a >> 29) & 3, (a >> 5) & 0x7FFFF
                imm = (immhi << 2) | immlo
                if imm & (1 << 20):
                    imm -= 1 << 21
                page = (addr & ~0xFFF) + (imm << 12)
                slot = page + (((b >> 10) & 0xFFF) << 3)
                name = self.got.get(slot)
        self._plt[addr] = name
        return name
