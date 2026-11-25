"""The environment a program Nucleus starts gets: this process's, without Nucleus's own settings and secrets.

The backend's environment holds the backend token (``NUCLEUS_BACKEND_TOKEN``), the window's approval key
(``NUCLEUS_UI_APPROVAL_KEY``) and the rest of Nucleus's settings (every ``NUCLEUS_*``), and the user's own API keys
may be there too. A helper program that reads a file Nucleus did not make (a fighter's C, a DAT, a model, an ISO)
can be made to misbehave by that file, and with those values it could drive the backend as the window does. So
every helper is started with :func:`child_environment`, which leaves them out. A helper that has to call the
backend back is handed what it needs by its caller (``extra=``), and the call site says so.
"""
import os

#: Nucleus's own settings and secrets: the backend token, the window's key, the data root.
PRIVATE_PREFIXES = ('NUCLEUS_',)
#: The user's own credentials a helper has no use for (OPENROUTER_API_KEY, GITHUB_TOKEN, ...).
SECRET_SUFFIXES = ('_API_KEY', '_TOKEN', '_SECRET', '_SECRET_KEY', '_PASSWORD')
#: A frozen (PyInstaller) Python's variables: they make a child that is the same packaged program reuse this
#: process's unpacked files, and mean nothing to any other program.
FROZEN_PREFIXES = ('_PYI', '_MEI')
#: The app's own Python path, which would make a Python helper import the app's modules instead of its own.
PYTHON_NAMES = ('PYTHONPATH', 'PYTHONHOME')


def is_private(name, *, same_program=False):
    """True when the variable ``name`` is one :func:`child_environment` leaves out."""
    upper = str(name).upper()
    if upper.startswith(PRIVATE_PREFIXES) or upper.endswith(SECRET_SUFFIXES) or upper in PYTHON_NAMES:
        return True
    return not same_program and upper.startswith(FROZEN_PREFIXES)


def child_environment(base=None, *, same_program=False, python=False, extra=None, unset=()):
    """This process's environment (or ``base``) for a child program, without Nucleus's settings and secrets.

    ``same_program``: the child is this packaged program itself (``sys.executable``), so a frozen build's own
    variables are kept. ``python``: the child is Python, so its output is unbuffered UTF-8. ``unset``: more names
    to leave out. ``extra``: variables to give it on top, applied last (a caller handing one back on purpose).
    """
    source = os.environ if base is None else base
    dropped = {str(n).upper() for n in unset}
    env = {key: value for key, value in source.items()
           if not is_private(key, same_program=same_program) and key.upper() not in dropped}
    if python:
        env.update(PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8')
    if extra:
        env.update({key: str(value) for key, value in extra.items()})
    return env
