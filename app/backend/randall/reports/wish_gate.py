"""The release gate for sending a wish off this machine (`wish_submit` in `core.gates`)."""

from core import gates


#: The release gate's name in `core.gates`.
SUBMIT_GATE = 'wish_submit'


def submit_enabled():
    """Whether a wish may leave this machine. Read at CALL time, never cached."""
    return gates.enabled(SUBMIT_GATE)
