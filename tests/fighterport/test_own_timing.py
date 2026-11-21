import pytest
from fighter_port.own_timing import NEVER, move_timing


@pytest.mark.parametrize('move,expected', [
    ({'end':47,'cancel_frame_real':36},(47,36)),
    ({'end':64},(64,NEVER)),
    ({'cancel_frame_real':53},(NEVER,53)),
    ({},(NEVER,NEVER)),
    ({'end':15.25,'cancel_frame_real':12.5},(16,13)),
])
def test_natural_end_and_interrupt_use_independent_real_update_clocks(move,expected):
    assert move_timing(move)==expected


@pytest.mark.parametrize('value', [True,False,-2,float('nan'),float('inf'),'47'])
def test_invalid_source_timing_does_not_silently_generate_a_state(value):
    with pytest.raises(ValueError):move_timing({'end':value})
