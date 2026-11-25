"""Runs a Melee Unlocked fighter kit's driver in a process of its own (projects/install/melee_unlocked.py
``_run_driver`` starts it).

    packaged:  mex_backend --mu-kit <kit>/tools/mexft_build.py <driver arguments...>
    checkout:  python app.py --mu-kit <kit>/tools/mexft_build.py <driver arguments...>

app.py hands over here before it imports Flask or anything of Nucleus's, so the kit's Python (and the fighter C
it compiles) runs in a child that holds none of the backend's state, with an environment that has no backend
token and no window key (core/child_env.py), and that the backend can stop when it takes too long. The installed
app has no ``python`` to start a script with, only the interpreter it is, which is why this is a mode of the
backend program rather than ``python mexft_build.py``.

Standard library only. The exit code is the driver's; what it prints goes to stdout, which the backend reads.
"""
import os
import runpy
import subprocess
import sys
import traceback

FLAG = '--mu-kit'


def main(argv):
    if not argv or not os.path.isfile(argv[0]):
        print('usage: --mu-kit <kit>/tools/mexft_build.py [arguments]', file=sys.stderr)
        return 2
    driver = os.path.abspath(argv[0])
    sys.argv = [driver] + list(argv[1:])
    try:
        runpy.run_path(driver, run_name='__main__')
    except SystemExit as e:
        if e.code in (None, 0):
            return 0
        if isinstance(e.code, int):
            return e.code
        print(e.code, file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        for stream in (e.stdout, e.stderr):
            if stream:
                print(stream if isinstance(stream, str) else stream.decode('utf-8', 'replace'), file=sys.stderr)
        print(str(e), file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - the backend shows the end of this
        traceback.print_exc()
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
