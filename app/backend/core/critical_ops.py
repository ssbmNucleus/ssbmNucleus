"""Registry of in-flight operations that must not die with the process.

The Electron shell asks the backend to exit the moment the user closes the
window, and the shutdown endpoint answers with os._exit() -- which also kills
whatever else the process was doing. That combination shipped a corruption
bug: closing the app seconds after clicking "Download ISO" truncated the
1.5 GB copy mid-stream, and the partial ISO boots to a black screen (a GC
image keeps its boot data at the front, so Dolphin starts it happily).

Anything whose death would leave a half-written artifact on the USER's side
registers here for its duration. The shutdown endpoint refuses to exit while
the registry is non-empty (projects/routes/project.py), and the Electron shell
polls until it drains (electron/main.js 'before-quit').

Use as a context manager, or via begin()/end() when the lifetime doesn't fit
a `with` block (e.g. a Flask response that ends in call_on_close):

    with critical_op('ISO export'):
        ...

    token = begin('ISO download')
    response.call_on_close(lambda: end(token))
"""
import itertools
import threading

_lock = threading.Lock()
_ops: dict = {}          # token -> name
_ids = itertools.count(1)


def begin(name: str) -> int:
    """Register an operation; returns a token for end()."""
    token = next(_ids)
    with _lock:
        _ops[token] = name
    return token


def end(token: int) -> None:
    """Unregister; safe to call twice."""
    with _lock:
        _ops.pop(token, None)


def active_ops() -> list:
    """Names of operations currently in flight (duplicates preserved)."""
    with _lock:
        return list(_ops.values())


class critical_op:
    def __init__(self, name: str):
        self.name = name
        self._token = None

    def __enter__(self):
        self._token = begin(self.name)
        return self

    def __exit__(self, *exc):
        end(self._token)
        return False
