"""fighter_port/SPECIALS.md stays true to the code it points at: every `file:name` pointer names a file that defines
that name, and every C or Python block it quotes is a piece of one of the modules, word for word (indentation
aside). A change to a module that moves what the guide quotes fails here, and the guide is mended by hand.

The guide's worked examples are fighters' own modules (own_wolf.py, own_duckhunt.py, own_gekkouga.py ...), which
left the tree for the git tag archive/fighterport-character-specific-2026-11. A file is read from the tree and,
for what is not there, from that tag; without the tag in this clone those checks are skipped.

Pointers into the Melee decompilation are checked only when it is on this machine (MELEE_DECOMP, else
~/projects/melee)."""
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2] / 'tools' / 'fighterport'
GUIDE = REPO / 'fighter_port' / 'SPECIALS.md'
DECOMP = Path(os.environ.get('MELEE_DECOMP') or Path.home() / 'projects' / 'melee') / 'src' / 'melee'
SEARCH = [REPO / 'fighter_port', REPO / 'fighter_port' / 'harness', REPO, REPO / 'echo_ultimate' / 'gamedata']
QUOTED = ('own_wolf.py', 'own_duckhunt.py', 'own_gekkouga.py', 'own.py', 'own_template.py', 'harness/look_probe.py')
ARCHIVE = 'archive/fighterport-character-specific-2026-11'                     # where the fighters' own modules went


def archived(name):
    """A fighter_port file as it stood at the archive tag, or None (no such file there, or no tag in this clone)."""
    got = subprocess.run(['git', 'show', f'{ARCHIVE}:tools/fighterport/fighter_port/{name}'], cwd=REPO,
                         capture_output=True, text=True, encoding='utf-8', errors='replace')
    if got.returncode != 0:
        return None
    t = got.stdout
    return t.replace('{{', '{').replace('}}', '}') if Path(name).name == 'own.py' else t


def find_file(name):
    """A pointer's file: under fighter_port (or the harness, or the repo), else in the decompilation (None when
    it is not there or the name is not one file)."""
    for base in SEARCH:
        if (base / name).is_file():
            return base / name
    if name.endswith(('.c', '.h')) and DECOMP.is_dir():
        hits = list(DECOMP.rglob(Path(name).name))
        return hits[0] if len(hits) == 1 else None
    return None


def text_of(path):
    t = path.read_text('utf-8', errors='replace')
    return t.replace('{{', '{').replace('}}', '}') if path.name == 'own.py' else t   # its C texts are str.format


def defines(path, name, text=None):
    """A Python def, class or constant; a C function, #define, or table (in a C file or a module's C text)."""
    t, n = text if text is not None else text_of(path), re.escape(name)
    pats = [rf'^\s*(?:async\s+)?def {n}\s*\(', rf'^class {n}\b', rf'^{n}\s*=',
            rf'^(?:static\s+|inline\s+|const\s+)*[A-Za-z_][\w\s\*]*?\b{n}\s*\([^;]*\)\s*(?:\{{.*)?$',
            rf'^#define {n}\b', rf'^(?:static\s+)?(?:const\s+)?[A-Za-z_][\w\s\*]*\b{n}\s*\[.*\]\s*=']
    return any(re.search(p, t, re.M) for p in pats)


def dedent(lines):
    least = min((len(x) - len(x.lstrip()) for x in lines if x.strip()), default=0)
    return [x[least:] for x in lines]


def test_every_pointer_of_the_guide_is_defined_where_it_says():
    text = GUIDE.read_text('utf-8')
    pointers = set(re.findall(r'`([\w/]+\.(?:py|c|h)):(\w+)`', text))
    assert len(pointers) > 50
    bad = []
    for file, name in sorted(pointers):
        path = find_file(file)
        old = None if file.endswith(('.c', '.h')) else archived(file)
        if path is None and old is None:
            if file.endswith(('.c', '.h')) and not DECOMP.is_dir():
                continue                                    # the decompilation is not on this machine
            if not file.endswith(('.c', '.h')) and archived('own_template.py') is None:
                continue                                    # the archive tag is not in this clone
            bad.append(f'no file {file} (for {name})')
        elif not ((path is not None and defines(path, name)) or (old is not None and defines(None, name, old))):
            bad.append(f'{file} defines no {name}')
    assert not bad, bad


def test_every_quoted_block_is_a_piece_of_a_module_word_for_word():
    text = GUIDE.read_text('utf-8')
    files = {}
    for name in QUOTED:
        here, old = find_file(name), archived(name)
        if here is None and old is None:
            pytest.skip(f'{name} is neither in the tree nor at {ARCHIVE} in this clone')
        files[name] = (text_of(here) if here is not None else '').split('\n')
        files[name + ' (archived)'] = (old or '').split('\n')
    blocks = re.findall(r'```(c|python)\n(.*?)\n```', text, re.S)
    assert len(blocks) > 10
    bad = []
    for lang, body in blocks:
        want = dedent(body.split('\n'))
        n = len(want)
        if not any(dedent(lines[i:i + n]) == want for lines in files.values() for i in range(len(lines) - n + 1)
                   if lines[i].strip() == want[0].strip()):
            bad.append(f'a {lang} block is in no module: {want[0]!r} ...')
    assert not bad, bad


def test_the_template_is_the_module_the_route_falls_back_on():
    """A fighter with no module of its own is built with the template's plain specials (`own_route.run` asks for
    'template' when the fighter's own name finds no module)."""
    from fighter_port import compat
    compat.install()
    from fighter_port import fighters, own
    assert fighters.specials('template') is not None and 'template' in own.BUILD
    assert 'nobody_ported_yet' not in own.BUILD
