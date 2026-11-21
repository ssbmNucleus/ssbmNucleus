"""The Any Climbers kind-alias block: a pair's clone leader answers vanilla
`fp->kind == FTKIND_X` checks (Link zair, Kirby copy, Falcon flame ...) as
its donor. The words are hand-encoded so the shipped app needs no assembler;
this pins them against the assembler when devkitPPC is installed and checks
the per-project table inference.
"""
import shutil
from pathlib import Path

import pytest

from vault.climbers import engine_code
from vault.climbers.engine import gen_engine_code as gen


def _fighter(name, symbol, sub=-1, behavior=0):
    return {"name": name, "subCharacter": sub, "subCharacterBehavior": behavior,
            "files": {"fighterDataSymbol": symbol}}


VANILLA = [_fighter("Mario", "ftDataMario"), _fighter("Fox", "ftDataFox"),
           _fighter("C. Falcon", "ftDataCaptain"), _fighter("Kirby", "ftDataKirby"),
           _fighter("Link", "ftDataLink"), _fighter("Jigglypuff", "ftDataPurin"),
           _fighter("Zelda", "ftDataZelda", sub=7, behavior=1),
           _fighter("Sheik", "ftDataSeak", sub=6, behavior=1),
           _fighter("Ice Climbers", "ftDataPopo", sub=9, behavior=0),
           _fighter("Nana", "ftDataNana")]


def test_project_aliases_maps_pair_leaders_to_their_donor():
    fighters = VANILLA + [_fighter("C. Falcon & Jigglypuff", "ftDataCaptain", sub=5),
                          _fighter("Link & Kirby", "ftDataLink", sub=3),
                          _fighter("Metal Mario", "ftDataMario")]   # a clone, not a pair
    assert engine_code.project_aliases(fighters) == {10: 2, 11: 4}


def test_project_aliases_skips_vanilla_and_transform_pairs():
    assert engine_code.project_aliases(VANILLA) == {}


def test_alias_words_shape():
    words = gen.alias_words({10: 2, 11: 4})
    assert words[0] == 0x80030004                     # lwz r0,4(r3)
    assert words[-1] == gen.ALIAS_HOOK_ORIG           # replaced instruction re-executed
    assert len(words) == 2 + 5 * 2
    assert words[1] == 0x2C00000A and words[4] == 0x38000002 and words[5] == 0x90030004
    assert words[3] == 0x900322F4                     # stash to ft_var51


def test_a_no_swap_pair_locks_its_cooldown_at_the_alias():
    assert gen.alias_words({10: 2}, no_swap={10}) == [
        0x80030004, 0x2C00000A, 0x40820018, 0x900322F4, 0x38000002, 0x90030004,
        0x3C007FFF, 0x900322F8, gen.ALIAS_HOOK_ORIG]
    # the other pair in the project keeps its swap
    assert gen.alias_words({10: 2, 11: 4}, no_swap={11})[1:6] == gen.alias_words({10: 2})[1:6]


def test_desired_source_locks_only_the_named_pair(monkeypatch):
    monkeypatch.setattr(engine_code, "code_entry", lambda: ("Any Climbers", "C2006B84 00000001\n60000000 00000000"))
    fighters = VANILLA + [_fighter("Plusle & Minun", "ftDataCaptain", sub=5),
                          _fighter("Link & Kirby", "ftDataLink", sub=3)]
    _, source = engine_code.desired_source(fighters, ["Plusle & Minun"])
    words = source.split()
    assert "900322F8" in words                # stw r0,ft_var52(r3)
    assert words.count("3C007FFF") == 1       # one lock, for one clone
    _, free = engine_code.desired_source(fighters)
    assert "3C007FFF" not in free.split()


def test_alias_ini_lines_are_c2_blocks():
    lines = gen.alias_ini_lines({10: 2})
    assert lines[0].startswith(f"C2{gen.ALIAS_HOOK & 0x01FFFFFF:06X} ")
    for hook in (gen.KIRBY_CAP_PRELOAD_HOOK, gen.KIRBY_CAP_LOAD_HOOK):
        assert any(l.startswith(f"C2{hook & 0x01FFFFFF:06X} ") for l in lines)
    assert not any(l.startswith("C20BD9F8") for l in lines)   # the old victim-kind hook is gone
    assert gen.alias_ini_lines({}) == []


def test_kirby_cap_words_alias_the_kind_argument_then_run_the_prologue():
    words = gen.kirby_cap_words({10: 2, 11: 4})
    assert words == [0x2C03000A, 0x40820008, 0x38600002,
                     0x2C03000B, 0x40820008, 0x38600004,
                     gen.KIRBY_CAP_HOOK_ORIG]
    assert gen.KIRBY_CAP_HOOK_ORIG == 0x7C0802A6   # mflr r0


def test_player_kind_answers_with_the_stash_only_for_a_listed_pair():
    words = gen.player_kind_words({10: 2, 11: 4})
    assert words[-1] == gen.PLAYER_KIND_HOOK_ORIG == 0x8001001C   # lwz r0,0x1C(r1)
    assert words[1] == 0x41800000 | (len(words) - 2) * 4          # -1 skips to the replaced lwz
    assert words[11] == 0x808422F4                                # lwz r4,ft_var51(r4)
    # each entry checks stash AND kind: Echo's VAR_B shares ft_var51
    assert words[12:17] == [0x2C04000A, 0x40820010, 0x2C030002, 0x40820008, 0x7C832378]
    assert words[17:22] == [0x2C04000B, 0x40820010, 0x2C030004, 0x40820008, 0x7C832378]


def test_alias_ini_lines_carry_the_player_kind_hook():
    lines = gen.alias_ini_lines({10: 2})
    assert any(l.startswith(f"C2{gen.PLAYER_KIND_HOOK & 0x01FFFFFF:06X} ") for l in lines)


def test_the_bundled_code_spawns_a_follower_behind_its_leader():
    name, source = engine_code.code_entry()
    assert f"C2{gen.FOLLOWER_SPAWN & 0x01FFFFFF:06X}" in source
    assert "C0230040" in source          # lfs f1,0x40(r3), the replaced instruction
    assert "3C00C120" in source          # lis r0,-10.0@h


@pytest.mark.skipif(not gen.AS.exists(), reason="devkitPPC assembler not installed")
def test_player_kind_words_match_the_assembler():
    asm = f"""
    cmpwi   3, 0
    blt     2f
    mulli   4, 31, {gen.PLAYER_STRIDE}
    lis     5, {hex(gen.PLAYER_SLOTS >> 16)}
    ori     5, 5, {hex(gen.PLAYER_SLOTS & 0xFFFF)}
    add     4, 4, 5
    lbz     5, {gen.PLAYER_TRANSFORMED}(4)
    slwi    5, 5, 2
    add     4, 4, 5
    lwz     4, {gen.ENTITY0}(4)
    lwz     4, 0x2C(4)
    lwz     4, {gen.FT_ORIG_KIND}(4)
    cmpwi   4, 10
    bne     1f
    cmpwi   3, 2
    bne     1f
    mr      3, 4
1:
2:
    lwz     0, 0x1C(1)
"""
    assert gen.assemble(asm) == gen.player_kind_words({10: 2})


@pytest.mark.skipif(not gen.AS.exists(), reason="devkitPPC assembler not installed")
def test_hand_encoded_words_match_the_assembler():
    asm = f"""
    lwz     0, 4(3)
    cmpwi   0, 10
    bne     1f
    stw     0, {gen.FT_ORIG_KIND}(3)
    li      0, 2
    stw     0, 4(3)
1:
    lbz     0, 0x221F(3)
"""
    assert gen.assemble(asm) == gen.alias_words({10: 2})
    asm2 = """
    cmpwi   3, 10
    bne     1f
    li      3, 2
1:
    mflr    0
"""
    assert gen.assemble(asm2) == gen.kirby_cap_words({10: 2})
    asm3 = f"""
    lwz     0, 4(3)
    cmpwi   0, 10
    bne     1f
    stw     0, {gen.FT_ORIG_KIND}(3)
    li      0, 2
    stw     0, 4(3)
    lis     0, 0x7FFF
    stw     0, {gen.FT_COOLDOWN}(3)
1:
    lbz     0, 0x221F(3)
"""
    assert gen.assemble(asm3) == gen.alias_words({10: 2}, no_swap={10})


def test_desired_source_appends_alias_block(monkeypatch):
    monkeypatch.setattr(engine_code, "code_entry", lambda: ("Any Climbers", "C2006B84 00000001\n60000000 00000000"))
    name, source = engine_code.desired_source(
        VANILLA + [_fighter("C. Falcon & Jigglypuff", "ftDataCaptain", sub=5)])
    assert source.startswith("C2006B84 00000001")
    assert f"C2{gen.ALIAS_HOOK & 0x01FFFFFF:06X}" in source
    name2, source2 = engine_code.desired_source(VANILLA)
    assert source2 == "C2006B84 00000001\n60000000 00000000"
