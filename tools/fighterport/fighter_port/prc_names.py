"""The names of a fighter's own values (his `vl.prc`) and of his articles' scripts, found by trying words.

    python -m fighter_port.prc_names <fighter> [word ...] [--root <dump>] [--most 4] [--scripts]

The game's files hold a name only as a hash: its length (the top byte) and the crc32 of the lower-case name. So a
name is found only by guessing it, and a guess is tried only where some hash has its length. The words tried are:
the ones given; the words of every name the port's modules already read (their `NAMES`: the game reuses its words,
`speed_max`, `landing_frame`); the common words of fighter parameters; and the fighter's own words, from his effect
and sound names and his article folders (Greninja: shuriken, water, bunshin, moon). Names of one to `--most` words
joined by `_` are tried over all of them, then names of one word more over the words of the names found so far (a
file reuses its own words: `attack_speed_min_up` was found that way).

Prints the names found, table by table, with what is still unnamed, and a `NAMES` line to paste into the fighter's
module. With --scripts it also names his articles' scripts (`game_` + words run together: `game_maxshot`), for
`articles.load(names=...)`.

(Greninja's cold trial wrote this by hand, in four rounds: 104 of his special tables' names. GAPS G1, G8.)
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import time
import zlib
from pathlib import Path

HERE = Path(__file__).parent

# Words fighter parameters are made of, beyond the ones the modules already name (read from Ultimate's
# own names found so far: Duck Hunt's, Wolf's, Greninja's, Byleth's tables)
COMMON = '''x y z r up down back front left right start end loop max min speed spd frame time count num rate mul add
sub dec accel brake angle degree rot offset scale size radius height length distance life power damage hit attack
shoot shot charge hold air ground landing fall gravity jump stick turn reverse init first last base limit range
target check type id node bone pos dir vec ratio cancel wait move rush warp stop pass reflect absorb catch throw
special lw hi s n effect sound flash color alpha visible enable disable is on off'''.split()


def hash40(name):
    b = name.lower().encode('utf-8')
    return (len(b) << 32) | (zlib.crc32(b) & 0xFFFFFFFF)


def known_names():
    """Every name the port's own modules read from a `vl.prc` (their `NAMES` and `TABLES`), read from their source
    (nothing is imported), and the names the earlier fighters' modules had found (`prc_known_names.txt`: those
    modules are kept under the git tag archive/fighterport-character-specific-2026-11, their names here)."""
    listed = HERE / 'prc_known_names.txt'
    out = set(listed.read_text('utf-8').split()) if listed.is_file() else set()
    for path in sorted(HERE.glob('own_*.py')):
        try:
            tree = ast.parse(path.read_text('utf-8'))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ('NAMES', 'TABLES')
                                                    for t in node.targets):
                out |= {c.value for c in ast.walk(node.value)
                        if isinstance(c, ast.Constant) and isinstance(c.value, str) and re.fullmatch(r'[a-z0-9_]+', c.value)}
    return out


def words_of(names):
    return {w for n in names for w in n.split('_') if w}


def fighter_words(fighter, root):
    """The fighter's own words: his effect and sound names (less the fighter's name) and his model folders."""
    from echo_ultimate.gamedata import arc, names as names_
    root = Path(root)
    out = set()
    try:
        got = arc.extract(root, root / 'gamedata', [p.format(f=fighter) for p in names_.LABEL_FILES[:1] + names_.LABEL_FILES[2:4]])
    except Exception:                                  # (no archive tool: the given words and the stock ones still)
        got = {}
    # only his own names (`gekkouga_shuriken_hold`, `se_gekkouga_special_n01`): a file's other runs of letters are
    # noise, and three thousand words make the search slow and its finds doubtful
    own = re.compile(rf'(?:se_|vc_)?{re.escape(fighter)}_([a-z0-9_]+)')
    for path in got.values():
        if path:
            out |= {w for n in names_.labels_in(path) if (m := own.fullmatch(n))
                    for w in m.group(1).split('_') if w.isalpha() and len(w) > 1}
    path_list = root / 'Hashes_FullPath'
    if path_list.exists():
        start = f'fighter/{fighter}/model/'
        with open(path_list, encoding='utf-8', errors='replace') as f:
            out |= {line[len(start):].split('/', 1)[0] for line in f if line.startswith(start)}
    return {w for w in out if 0 < len(w) <= 16}


FF = 0xFFFFFFFF
SUFFIXES_AT_MOST = 1_500_000            # the most word runs tried as a name's end in one go (memory and time)


def search(words, targets, most, joiner='_', start=b''):
    """{hash: name} of every name of 1..`most` of `words` (joined by `joiner`, after `start`) whose hash is in
    `targets` ({length: {crc32}}).

    Met in the middle: a name is a beginning P (one or two words) and an end S (the rest). The crc32 of P + S is
    A^n(crc(P) ^ FF) ^ c(S) ^ FF, where n is the length of S, A^n is the crc's step over n zero bytes and c(S) the crc's
    step over S from nothing; both halves are worked out once and matched by sorting, so four words of a few hundred
    take seconds where trying every name would take hours."""
    import numpy as np
    if not targets or most < 1:
        return {}
    ws = sorted({w.encode() for w in words if w})
    j = joiner.encode()
    found = {}

    def direct(names):
        for b in names:
            got = targets.get(len(b))
            if got:
                c = zlib.crc32(b)
                if c in got:
                    found[(len(b) << 32) | c] = b.decode()

    p1 = [start + w for w in ws]
    direct(p1)
    if most < 2:
        return found
    p2 = [start + a + j + b for a in ws for b in ws]
    direct(p2)
    # the end: the rest of the words, as many as there is room for
    ends = 0
    suffix = [b'']
    while ends < most - 2 and len(suffix) * len(ws) <= SUFFIXES_AT_MOST:
        suffix = [s + j + w for s in suffix for w in ws]
        ends += 1
        if ends >= 1:
            meet(np, p2, suffix, targets, found)
    return found


def meet(np, beginnings, ends, targets, found):
    """Every beginning + end whose hash is in `targets`, into `found`."""
    by_len = {}
    for b in beginnings:
        by_len.setdefault(len(b), []).append(b)
    ends_by_len = {}
    for s in ends:
        ends_by_len.setdefault(len(s), []).append(s)
    end_c = {n: np.array([zlib.crc32(s, FF) ^ FF for s in group], dtype=np.uint32) for n, group in ends_by_len.items()}
    for n, group in ends_by_len.items():
        zeros = b'\0' * n
        for m, begun in by_len.items():
            crcs = targets.get(m + n)
            if not crcs:
                continue
            q = np.array([zlib.crc32(zeros, zlib.crc32(b)) ^ FF for b in begun], dtype=np.uint32)
            order = np.argsort(q, kind='stable')
            qs = q[order]
            for t in crcs:
                want = np.uint32(t ^ FF) ^ end_c[n]
                at = np.searchsorted(qs, want)
                at[at >= len(qs)] = 0
                for k in np.nonzero(qs[at] == want)[0]:
                    name = begun[int(order[int(at[k])])] + group[int(k)]
                    found[((m + n) << 32) | t] = name.decode()


def by_length(hashes):
    out = {}
    for h in hashes:
        out.setdefault(h >> 32, set()).add(h & 0xFFFFFFFF)
    return out


def vl_hashes(fighter, root):
    from echo_ultimate.gamedata import arc, moves
    from echo_ultimate.gamedata.prc import Prc
    root = Path(root)
    want = moves.archive_paths(fighter)['vl']
    path = root / 'gamedata' / want
    if not path.exists():
        path = Path(arc.extract(root, root / 'gamedata', [want])[want] or path)
    data = path.read_bytes()
    return Prc(data, []), data


def script_hashes(fighter, root):
    """The hashes of his registered scripts that no name the readers know gives (an article's, mostly)."""
    from echo_ultimate.gamedata import arc, moves, names as names_
    from echo_ultimate.gamedata.acmd import Scripts
    root = Path(root)
    want = moves.archive_paths(fighter)['scripts']
    got = arc.extract(root, root / 'gamedata', [want])[want]
    known = names_.candidates(fighter, root / 'Hashes_FullPath')
    sc = Scripts(got, known)
    return {r['hash'] for r in sc.registered if str(r['name']).startswith('0x')}


def say_now(*a):
    print(*a, flush=True)


def find(fighter, root, given=(), most=4, scripts=False, say=say_now):
    """-> {'names': {hash: name} of the vl.prc, 'scripts': {hash: name}, 'left': hashes still unnamed}"""
    t0 = time.time()
    prc, _ = vl_hashes(fighter, root)
    hashes = set(prc.hashes)
    stock = known_names()
    words = set(given) | words_of(stock) | set(COMMON) | fighter_words(fighter, root)
    from echo_ultimate.gamedata.names import fighter_param_names
    words |= words_of(fighter_param_names())
    words = {w.lower() for w in words if re.fullmatch(r'[A-Za-z0-9]+', w)}
    found = {h: n for n in stock | set(fighter_param_names()) | set(given) if (h := hash40(n)) in hashes}
    targets = by_length(hashes - set(found))
    say(f'{len(hashes)} hashes in his vl.prc; {len(found)} named by names already known; trying {len(words)} words, '
        f'names of 1 to {most}')
    doubt = {}                                          # words in a name -> the finds of that many expected by chance
    for k in range(1, most + 1):
        doubt[k] = chance(words, targets, k)
    found.update(search(words, targets, most))
    # one word more, over the words this file is found to use
    used = words_of(found.values()) | set(given)
    targets = by_length(hashes - set(found))
    if len(used) <= 90:
        doubt[most + 1] = chance(used, targets, most + 1)
        found.update(search(used, targets, most + 1))
    say(f'{len(found)} of {len(hashes)} named in {time.time() - t0:.0f} s')
    out = {'names': found, 'left': sorted(hashes - set(found)), 'scripts': {}, 'doubt': doubt}
    if scripts:
        unnamed = script_hashes(fighter, root)
        targets = by_length(unnamed)
        for kind in ('game_', 'effect_', 'sound_', 'expression_'):
            out['scripts'].update(search(words | used, targets, 3, joiner='', start=kind.encode()))
        say(f"{len(out['scripts'])} of {len(unnamed)} unnamed scripts named")
    return out


DOUBTFUL = 0.05     # a round whose chance finds come to more than this has its finds checked by eye


def chance(words, targets, k, joiner=1, start=0):
    """How many names of exactly `k` of `words` would match some hash of `targets` by chance alone (a hash is 32 bits
    of crc beside the length: a few billion tries of one length will hit one of its hashes now and then)."""
    from collections import Counter
    lens = Counter(len(w) for w in set(words))
    dist = Counter({start: 1})
    for i in range(k):
        nxt = Counter()
        for total, count in dist.items():
            for size, n in lens.items():
                nxt[total + size + (joiner if i else 0)] += count * n
        dist = nxt
    return sum(count * len(targets.get(total, ())) for total, count in dist.items()) / 2 ** 32


def show(fighter, root, found, say=print):
    """Each table of the vl.prc with its values named as found."""
    from echo_ultimate.gamedata.prc import Prc
    _, data = vl_hashes(fighter, root)
    prc = Prc(data, list(found['names'].values()))
    for table, value in prc.root.items():
        rows = value if isinstance(value, list) else [value]
        first = rows[0] if rows else None
        if not isinstance(first, dict):
            say(f'{table} = {rows if len(rows) > 1 else first}')
            continue
        unnamed = [k for k in first if str(k).startswith('0x')]
        say(f"{table} ({len(rows)} row{'s' if len(rows) != 1 else ''}; {len(first) - len(unnamed)} of {len(first)} named)")
        for k, v in first.items():
            say(f'    {k} = {v}')


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('fighter', help="the game's name for him (gekkouga)")
    p.add_argument('words', nargs='*', help="words to try beside the stock ones: the move's nickname's, its article's")
    p.add_argument('--root', default=os.environ.get('ULTIMATE_DUMP'), help='the dump (default: ULTIMATE_DUMP)')
    p.add_argument('--most', type=int, default=4, help='words in a name, at most (one more over the words found)')
    p.add_argument('--scripts', action='store_true', help="also name his articles' scripts (game_ + words)")
    p.add_argument('--quiet', action='store_true', help='only the NAMES line')
    a = p.parse_args(argv)
    if not a.root:
        p.error('--root (or ULTIMATE_DUMP) is needed')
    got = find(a.fighter, a.root, [w.lower() for w in a.words], a.most, a.scripts)
    if not a.quiet:
        show(a.fighter, a.root, got)
        if got['scripts']:
            print('scripts:', ' '.join(f'0x{h:010x}={n}' for h, n in sorted(got['scripts'].items(), key=lambda x: x[1])))
        print(f"{len(got['left'])} still unnamed")
    stock = known_names()
    new = sorted(n for n in got['names'].values() if n not in stock)
    sure = [n for n in new if got['doubt'].get(n.count('_') + 1, 0) <= DOUBTFUL]
    check = [n for n in new if n not in sure]
    print('NAMES += ' + repr(tuple(sure)))
    if check:
        rounds = ', '.join(f'{k} words: {v:.1f}' for k, v in sorted(got['doubt'].items()) if v > DOUBTFUL)
        print(f'CHECK BY EYE before using (finds expected by chance alone: {rounds}); a name that makes no sense for '
              f'its table and value is a coincidence: ' + repr(tuple(check)))
    if got['scripts']:
        print('articles.load(names=' + repr(tuple(sorted({n.split('_', 1)[1] for n in got['scripts'].values()}))) + ')')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
