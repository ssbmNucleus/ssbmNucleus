"""GALE01 animation-buffer allocation and admission limits, patched together.

Both fighter buffers come from fighter_x59C_alloc_data. Match and demo startup
initialize that same descriptor independently, so both initializers and both
row-size guards must agree. 0xffe0 is the largest 32-byte aligned unsigned
immediate supported by the original compare instruction. The wide profile uses
an unsigned shift test in the same instruction slot and allocates 128 KiB.
"""
import hashlib
import struct
from .engine_capacity import DolImage,decode_allocator

EXTENDED=0xffe0
WIDE=0x1ffe0  # largest 32-byte aligned row below the 128 KiB allocation
ALLOCATOR=0x804590ac
# Existing DOL instructions bound to fighter.c, ftdemo.c and ftdata.c.
SITES={
    'match_allocation':(0x80067a94,[0x3c608046,0x3c800001,0x386390ac,0x38848000,0x38a00020,0x483132a1],3),
    'demo_allocation':(0x800beb38,[0x3c608046,0x3c800001,0x386390ac,0x3884b000,0x38a00020,0x482bc1fd],3),
    'match_limit':(0x80085aa4,[0x7c040378,0x4182003c,0x28048000,0x40810020,0x4cc63182],2),
    'demo_limit':(0x80085c5c,[0x7c040378,0x41820040,0x2804b000,0x40810020,0x4cc63182],2)}


def wide_words(name,expected):
    words=expected[:]
    if name.endswith('allocation'):
        words[1]=0x3c800002  # lis r4,2
        words[3]=0x38840000 # addi r4,r4,0: 131072 bytes
    else:
        # srwi. r0,r4,17: unsigned size >> 17 is 0..32767. The existing
        # ble passes exactly when this is zero (size < 131072). r4 retains
        # the original byte size for the existing assertion diagnostic.
        # r0 is dead here: both success paths reload it before use.
        words[2]=0x54807c7f
    return words


def measure(read):
    result={}
    for name,(address,expected,index) in SITES.items():
        raw=read(address,len(expected)*4)
        if len(raw)!=len(expected)*4:raise ValueError('Short animation capacity code read')
        words=list(struct.unpack('>'+str(len(expected))+'I',raw));masked=words[:]
        if words==wide_words(name,expected):
            if name.endswith('limit'):
                reloads={'match_limit':[0x801b000c,0x7c60f214,0x80030004],
                         'demo_limit':[0x807c010c,0x80030014,0x7c60da14]}[name]
                if read(address+44,12)!=struct.pack('>3I',*reloads):raise ValueError('Wide guard scratch register is not reloaded')
            result[name]=dict(address=address,bytes=WIDE,raw=raw.hex(),allocation_bytes=0x20000,unsigned_admission_max=0x1ffff)
            continue
        masked[index]=(masked[index]&0xffff0000)|(expected[index]&0xffff)
        if masked!=expected:raise ValueError('Unrecognized animation capacity code: '+name)
        value=words[index]&0xffff
        if value not in (expected[index]&0xffff,EXTENDED):raise ValueError('Unsupported animation capacity')
        result[name]=dict(address=address,bytes=value,raw=raw.hex())
    values={k:v['bytes'] for k,v in result.items()}
    if values not in (dict(match_allocation=32768,demo_allocation=45056,match_limit=32768,demo_limit=45056),dict.fromkeys(SITES,EXTENDED),dict.fromkeys(SITES,WIDE)):
        raise ValueError('Animation allocation and size guards disagree')
    return dict(schema='gale01-animation-capacity-v1',match_bytes=values['match_limit'],demo_bytes=values['demo_limit'],sites=result)


def measure_dol(data):return measure(DolImage(data).code)


def extend(data,capacity=EXTENDED):
    if capacity not in (EXTENDED,WIDE):raise ValueError('Explicit extended animation profile required')
    image=DolImage(data);before=measure(image.code)
    if before['match_bytes']!=32768:raise ValueError('Unmodified animation capacity required')
    out=bytearray(data);changes=[]
    for name,(address,expected,index) in SITES.items():
        replacement=wide_words(name,expected) if capacity==WIDE else expected[:]
        if capacity==EXTENDED:replacement[index]=(expected[index]&0xffff0000)|EXTENDED
        for slot,(old,word) in enumerate(zip(expected,replacement)):
            if old==word:continue
            at=address+slot*4
            section=next(s for s in image.sections if s['address']<=at< s['address']+s['size'])
            offset=section['offset']+at-section['address']
            struct.pack_into('>I',out,offset,word)
            changes.append(dict(site=name,address=at,offset=offset,before=f'{old:08x}',after=f'{word:08x}'))
    after=measure_dol(bytes(out))
    return bytes(out),dict(schema='gale01-animation-capacity-patch-v1',before=before,after=after,changes=changes,
        input_sha256=hashlib.sha256(data).hexdigest(),output_sha256=hashlib.sha256(out).hexdigest(),
        extra_match_bytes_per_fighter=2*((0x20000 if capacity==WIDE else EXTENDED)-32768),native_accepted=False)


def capture(read):
    code=measure(read);allocator=decode_allocator(read(ALLOCATOR,0x2c),32)
    expected=0x20000 if code['match_bytes']==WIDE else code['match_bytes']
    if allocator['status']!='INITIALIZED_DESCRIPTOR' or allocator['size']!=expected:
        raise ValueError('Live animation allocator differs from match code')
    return dict(code=code,allocator=allocator,scope='Live initialized buffer descriptor and all four code sites; animation playback is separate.')
