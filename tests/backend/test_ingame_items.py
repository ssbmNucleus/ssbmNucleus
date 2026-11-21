import struct
import pytest
from shared.ingame import items


class Memory:
    def __init__(self):self.data={}
    def bytes(self,p,n):return bytes(self.data.get(p+i,0) for i in range(n))
    def write_u8(self,p,v):self.data[p]=v
    def put(self,p,b):self.data.update({p+i:v for i,v in enumerate(b)})
    def u8(self,p):return self.bytes(p,1)[0]
    def u16(self,p):return struct.unpack('>H',self.bytes(p,2))[0]
    def u32(self,p):return struct.unpack('>I',self.bytes(p,4))[0]
    def f32(self,p):return struct.unpack('>f',self.bytes(p,4))[0]
    def write_u16(self,p,v):self.put(p,struct.pack('>H',v))
    def write_u32(self,p,v):self.put(p,struct.pack('>I',v))


def test_spawn_selection_preserves_allocation_and_restores_original_table():
    d=Memory();p=items.SPAWNER
    d.put(p,struct.pack('>IB3xIH2xI',91,2,0x81000000,50,0x81000010))
    d.put(0x81000000,bytes([12,16]));d.put(0x81000010,struct.pack('>2H',0,25))
    before=dict(d.data)
    with pytest.raises(ValueError,match='absent'):items.next_spawn(d,21)
    assert d.data==before
    receipt=items.next_spawn(d,16)
    assert items.spawner(d)['countdown']==1 and items.spawner(d)['kinds']==[16]
    assert d.u32(p+8)==0x81000000 and d.u32(p+16)==0x81000010
    items.restore_spawn(d,receipt)
    assert d.data==before


def test_item_reader_refuses_bad_entity_and_cyclic_list():
    d=Memory();d.write_u32(items.ENTITIES,0x81000000);d.write_u32(0x81000024,0x81000100)
    d.put(0x81000100,bytes.fromhex('00060900'));d.write_u32(0x8100012c,0x81001000)
    with pytest.raises(ValueError,match='backpointer'):items.read_items(d)
    d.write_u32(0x81001004,0x81000100)
    assert len(items.read_items(d))==1
    d.write_u32(0x81000108,0x81000100)
    with pytest.raises(ValueError,match='Cyclic'):items.read_items(d)
