"""Append the roots of one HSD DAT into another WITHOUT rewriting the target.

Why this exists: HSDRaw's ``HSDRawFile.Save`` is not byte-exact on fighter
Pl*.dat files (it re-lays the data section and drops relocations), and the
Echo codec relies on the donor's script layout staying put.  MexTK's
``-dat file -ow`` goes through that save.  So compiled ``ftFunction`` code is
built standalone (``MexTK -ff ... -o ftFunction.dat``) and appended here:

* the target's data / relocation / root / string tables are kept verbatim
  (asserted), so every existing offset is unchanged;
* the source's data block is appended 0x20-aligned, its relocation entries
  and the pointer VALUES they cover are shifted by the new base, and its
  roots are added.

Used by the Tier-2 (compiled move logic) path; see ``tier2/README.md``.
"""
import struct
import sys


def parse(b):
    """Return (data, relocs, roots, xrefs) of a DAT; roots/xrefs as (offset, name)."""
    fs, ds, rc, rtc, xc = struct.unpack('>IIIII', b[:20])
    data = b[0x20:0x20 + ds]
    p = 0x20 + ds
    relocs = list(struct.unpack('>%dI' % rc, b[p:p + rc * 4]))
    p += rc * 4
    roots = [struct.unpack('>II', b[p + i * 8:p + i * 8 + 8]) for i in range(rtc)]
    p += rtc * 8
    xrefs = [struct.unpack('>II', b[p + i * 8:p + i * 8 + 8]) for i in range(xc)]
    p += xc * 8
    strs = b[p:]

    def name(so):
        return strs[so:strs.index(b'\0', so)].decode()

    return data, relocs, [(o, name(s)) for o, s in roots], [(o, name(s)) for o, s in xrefs]


def build(data, relocs, roots, xrefs):
    """Serialise a DAT from its parts (string table rebuilt, 0x20-padded)."""
    strtab = bytearray()
    names = {}

    def add(n):
        if n not in names:
            names[n] = len(strtab)
            strtab.extend(n.encode() + b'\0')
        return names[n]

    rb = b''.join(struct.pack('>II', o, add(n)) for o, n in roots)
    xb = b''.join(struct.pack('>II', o, add(n)) for o, n in xrefs)
    body = data + struct.pack('>%dI' % len(relocs), *relocs) + rb + xb + bytes(strtab)
    while (len(body) + 0x20) % 0x20:
        body += b'\0'
    hdr = struct.pack('>IIIIIIII', len(body) + 0x20, len(data), len(relocs),
                      len(roots), len(xrefs), 0, 0, 0)
    return hdr + body


def merge_bytes(dst, src):
    """Return dst with every root of src appended (dst content byte-exact)."""
    dd, dr, droots, dx = parse(dst)
    sd, sr, sroots, sx = parse(src)
    base = len(dd)
    while base % 0x20:
        base += 1
    pad = base - len(dd)
    sd = bytearray(sd)
    for r in sr:  # each reloc names a pointer slot whose VALUE is a data offset
        v = struct.unpack('>I', sd[r:r + 4])[0]
        struct.pack_into('>I', sd, r, v + base)
    data = dd + b'\0' * pad + bytes(sd)
    relocs = dr + [r + base for r in sr]
    roots = droots + [(o + base, n) for o, n in sroots]
    xrefs = dx + [(o + base, n) for o, n in sx]
    out = build(data, relocs, roots, xrefs)
    assert out[0x20:0x20 + len(dd)] == dd, 'target data must be preserved verbatim'
    return out


def merge(dst_path, src_path, out_path):
    with open(dst_path, 'rb') as f:
        d = f.read()
    with open(src_path, 'rb') as f:
        s = f.read()
    out = merge_bytes(d, s)
    with open(out_path, 'wb') as f:
        f.write(out)
    print('merged', dst_path, '+', src_path, '->', out_path,
          'roots', [n for _, n in parse(out)[2]], 'size', len(out))


if __name__ == '__main__':
    merge(*sys.argv[1:4])
