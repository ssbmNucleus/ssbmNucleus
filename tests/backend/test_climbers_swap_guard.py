"""The D-pad swap refuses a fighter that cannot act.

Reported 2026-09-13 against 0.8.5, within hours of Any Climbers shipping:

  * "if you swap characters to a character thats dead you cant swap back or
    pause and get stuck"
  * "swapping while spawning in crashes the game"

Both are the same hole: the swap toggled the master/slave bit unconditionally
and then ran the follower AI init on the incoming fighter, with no test that
either half was in a state that can be driven.

The ftCommon motion-state enum is contiguous and ordered, so one comparison
covers every refusable state -- dead (0..10, the range the game's own
ftLib_8008732C tests), Sleep (11, the partner while its leader is dead), and
Rebirth/RebirthWait (12..13, on the respawn platform). Wait (14) is the first
state a fighter can act from.
"""
from tests.paths import BACKEND
import re
import sys
from pathlib import Path

import pytest

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

from vault.climbers.engine import gen_engine_code as gen  # noqa: E402


def test_wait_is_the_first_actionable_state():
    """Guard the enum values this whole fix rests on."""
    assert gen.MS_WAIT == 14
    assert gen.FT_MOTION_ID == 0x10


def test_the_swap_tests_both_fighters_before_toggling():
    """Neither half may be dead, asleep or spawning."""
    asm = gen.swap_asm()
    toggle = asm.index('xori    0, 0, 8')
    guard = asm[:toggle]

    # offsets are emitted as decimal, like every other one in the template
    checks = re.findall(r'lwz\s+0, 16\((1[56])\)\s*\n\s*cmpwi\s+0, 14\s*\n\s*blt', guard)
    assert sorted(checks) == ['15', '16'], (
        'both fighters must be checked before the master/slave bit is toggled; '
        f'found {checks}')


def test_the_guard_is_in_the_committed_engine_code():
    """data/any_climbers.ini is generated but committed -- it is what ships."""
    from core.config import BACKEND_DIR as CFG_BACKEND_DIR  # noqa: F401
    ini = (BACKEND_DIR / 'data' / 'any_climbers.ini').read_text(encoding='utf-8')
    words = ''.join(re.findall(r'^[0-9A-F]{8} [0-9A-F]{8}$', ini, re.M)).replace(' ', '')

    # lwz r0,0x10(r15) / cmpwi r0,14   and   lwz r0,0x10(r16) / cmpwi r0,14
    assert '800F00102C00000E' in words, 'leader liveness check missing from the shipped code'
    assert '801000102C00000E' in words, 'partner liveness check missing from the shipped code'


@pytest.mark.skipif(not gen.AS.exists(), reason='devkitPPC assembler not installed')
def test_regenerating_is_a_no_op(tmp_path, monkeypatch):
    """The committed .ini matches what the generator produces right now.

    It is generated-but-committed, so a source edit that was never regenerated
    would ship the OLD code while the reviewed diff showed the new one.

    Needs devkitPPC, which only the dev laptop has; the runners get the byte
    check in test_the_guard_is_in_the_committed_engine_code instead.
    """
    committed = (BACKEND_DIR / 'data' / 'any_climbers.ini').read_text(encoding='utf-8')
    rebuilt = gen.build()
    assert rebuilt.strip().replace('\r', '') == committed.strip().replace('\r', '')
