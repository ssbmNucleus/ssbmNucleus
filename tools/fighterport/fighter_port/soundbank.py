"""Make donor sound references relative to the fighter's installed m-ex bank.

m-ex FighterPitchShift.asm resolves 5000+script through the fighter's SSM ID.
Walk typed script fields and ftData's sound table; never scan arbitrary words.
"""
from vault.echo.subactions import FighterDat, HEADER_SIZE, write_bits


def localize(data: bytes, donor_bank: int, script_count: int):
    if not 0 <= donor_bank < 256 or not 0 < script_count <= 5000:
        raise ValueError('Invalid donor bank or script count')
    f = FighterDat(data)
    changes = []

    def mapped(value):
        if value // 10000 != donor_bank:
            return value
        index = value % 10000
        if index >= script_count:
            raise ValueError(f'Donor sound script {index} is missing')
        return 5000 + index

    pending = [a.script_offset for a in f.actions if a.script_offset is not None]
    demo = f.dat.ptr(f.ft_root+0x14)
    if demo is not None:
        for entry in range(demo,f.dat.struct_end(demo)-23,24):
            script=f.dat.ptr(entry+12)
            if script is not None:pending.append(script)
    seen = set()
    while pending:
        offset = pending.pop()
        if offset in seen:
            continue
        seen.add(offset)
        for c in f.decode_script(offset).commands:
            if c.after_end:
                break
            if c.pointer is not None:
                pending.append(c.pointer)
            for p in c.spec.params:
                if not (p.key.startswith('sfx_id') or p.key == 'sound_id'):
                    continue
                before = c.fields[p.key]
                after = mapped(before)
                if after != before:
                    write_bits(f.dat.buf, (HEADER_SIZE+c.offset)*8+p.bit_offset,p.bits,after)
                    changes.append(dict(kind='script',offset=c.offset,field=p.key,before=before,after=after))
    table = f.dat.ptr(f.ft_root + 0x4C)
    if table is not None:
        fields = [table+i for i in (4,8,12,16,20,24,36,40,44,48,52)]
        for slot in (0,28,32):
            array = f.dat.ptr(table+slot)
            if array is None:
                continue
            count = f.dat.u32(array)
            values = f.dat.ptr(array+4)
            if count > 256 or (count and values is None):
                raise ValueError('Malformed fighter sound array')
            fields.extend(values+4*i for i in range(count))
        for offset in set(fields):
            before = f.dat.u32(offset)
            after = mapped(before)
            if after != before:
                f.dat.set_u32(offset,after)
                changes.append(dict(kind='fighter-table',offset=offset,before=before,after=after))
    return f.to_bytes(), dict(donor_bank=donor_bank,script_count=script_count,changes=changes)
