from shared.ingame.gamestate import Player,STATIC_PLAYER

class Memory:
    def __init__(self):
        self.bytes={STATIC_PLAYER+12:0}
        self.words={STATIC_PLAYER+0xB0:0x80500000,STATIC_PLAYER+0xB4:0x80500100,
                    0x8050002C:0x80600000,0x8050012C:0x80610000}
    def u8(self,p):return self.bytes.get(p)
    def u32(self,p):return self.words.get(p)

def test_resolve_follows_logical_active_entity_after_transform():
    memory=Memory();player=Player(memory)
    assert player.resolve()==0x80600000
    memory.bytes[STATIC_PLAYER+12]=1
    assert player.resolve()==0x80610000
    memory.words[STATIC_PLAYER+0xB4]=0
    assert player.resolve() is None

def test_invalid_transform_index_never_reads_arbitrary_entity():
    memory=Memory();memory.bytes[STATIC_PLAYER+12]=255
    assert Player(memory).resolve() is None
