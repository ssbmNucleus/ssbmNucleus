"""Generate API.md from the package's own docstrings.

    python -m nucleus_api.gendocs            # writes nucleus_api/API.md
    python -m nucleus_api.gendocs path.md    # writes somewhere else

Nothing is hand-written in API.md: if a docstring is wrong, the docs are wrong,
so they are fixed in one place.
"""
import inspect
import sys
from pathlib import Path

MODULES = ('vault', 'modfile', 'menus', 'website', 'codes', 'render',
           'game', 'builds')


def _signature(function):
    try:
        return str(inspect.signature(function))
    except (TypeError, ValueError):
        return '(...)'


def _public(module):
    for name, value in sorted(vars(module).items()):
        if name.startswith('_') or not inspect.isfunction(value):
            continue
        # A module may document functions it re-exports from a shipped home
        # (codes.py: core.gecko_codes) by naming that home in _DOCUMENTED_FROM.
        if value.__module__ not in (module.__name__, *getattr(module, '_DOCUMENTED_FROM', ())):
            continue
        if value.__name__ != name:
            # An alias, not a second function: a replaceable seam
            # (menus.NATIVE_MENU_READER) documents itself under its real name.
            continue
        yield name, value


def build():
    import nucleus_api

    lines = ['# nucleus_api', '',
             'Auto-generated from the docstrings by `python -m nucleus_api.gendocs`.',
             'Do not edit by hand.', '',
             (nucleus_api.__doc__ or '').strip(), '', '---', '']
    for name in MODULES:
        module = getattr(nucleus_api, name)
        lines += [f'## `nucleus_api.{name}`', '', (module.__doc__ or '').strip(), '']
        for function_name, function in _public(module):
            lines += [f'### `{name}.{function_name}{_signature(function)}`', '',
                      inspect.cleandoc(function.__doc__ or '*(undocumented)*'), '']
        lines.append('---')
        lines.append('')
    workspace_doc = inspect.getmodule(nucleus_api.workspace)
    lines += ['## Workspace rules', '', (workspace_doc.__doc__ or '').strip(), '']
    for function in (nucleus_api.workspace, nucleus_api.use_workspace, nucleus_api.in_path,
                     nucleus_api.open_input, nucleus_api.read_input, nucleus_api.out_path,
                     nucleus_api.derived_output, nucleus_api.library_path):
        lines += [f'### `{function.__name__}{_signature(function)}`', '',
                  inspect.cleandoc(function.__doc__ or ''), '']
    return '\n'.join(lines).rstrip() + '\n'


def main(argv):
    destination = Path(argv[1]) if len(argv) > 1 else Path(__file__).with_name('API.md')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(build(), encoding='utf-8')
    print(f'Wrote {destination} ({destination.stat().st_size} bytes)')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
