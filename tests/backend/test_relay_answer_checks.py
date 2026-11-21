"""randall/model_import/chat/ask_checks.py: the rules rigswap holds a relayed skeleton answer to, checked as the app's
MCP takes the answer (answer_import), in rigswap's words.

The rules are restated from rigswap/core/fill.py (it runs only in rigswap's own Python, beside the model). The parity
tests below run the PINNED rigswap's own ``entries`` and ``_limb_fault`` (utility/rigswap.manifest.json's commit,
read from a rigswap clone: RIGSWAP_REPO, else ~/projects/rigswap) on the same answers, with its questions drawn by
its own ``table``/``limb_table``, and require both to say the same. Without a clone they skip; moving the pin runs
them on the machine that fetches it (tools/build/fetch_rigswap.py needs the same clone).
"""
import ast
import itertools
import json
import os
import subprocess
import types
from pathlib import Path

import pytest

from tests.paths import APP

from randall.model_import.chat import ask_checks

ARM, LEG = ask_checks.ARM, ask_checks.LEG
FILL_QUESTION = '''Look at the model.

  n  parent  across    deep    high  skin  below  names
  1       -     0.0     0.0    50.0   120      9  hips
  2       1     0.0     0.0    70.0    80      7  chest
  3       2     0.0     0.0    90.0    40      1  head
  4       3     0.0     0.0    95.0    40      0  skull
  5       2    10.0     0.0    75.0    30      1  arm_l
  6       5    20.0     0.0    70.0    20      0  hand_l
  7       2   -10.0     0.0    75.0    30      1  arm_r
  8       7   -20.0     0.0    70.0    20      0  hand_r
  9       1     5.0     0.0    30.0    50      0  leg_l
 10       1    -5.0     0.0    30.0    50      0  leg_r

What to answer:
- character: who or what this is.'''


def _fill_ask(question=FILL_QUESTION, round_='core fill'):
    return {'id': '1-1', 'round': round_, 'question': question, 'schema': {'type': 'object'}}


def _arm(shoulder=None, hand=None, elbow=None, clavicle=None):
    return {'clavicle': clavicle, 'shoulder': shoulder, 'elbow': elbow, 'hand': hand}


def _leg(hip=None, ankle=None, knee=None, toe=None):
    return {'hip': hip, 'knee': knee, 'ankle': ankle, 'toe': toe}


def _answer(**changes):
    answer = {'front_view': 'A', 'plan': 'biped', 'hips': 1, 'chest': 2, 'neck': 3, 'skull': 4,
              'legs': {'left': _leg(1, 9), 'right': _leg(1, 10)},
              'arms': {'left': _arm(5, 6), 'right': _arm(7, 8)}}
    answer.update(changes)
    return answer


def test_the_smoke_tests_handless_arm_is_refused_in_rigswaps_words():
    answer = _answer(arms={'left': _arm(5, None), 'right': _arm(7, 8)})
    assert ask_checks.fault(_fill_ask(), answer) == 'the left arm names no hand'
    assert ask_checks.fault(_fill_ask(round_='core fill again'), answer) == 'the left arm names no hand'
    assert ask_checks.fault(_fill_ask(), _answer()) is None


def test_the_whole_body_rules():
    fault = lambda **changes: ask_checks.fault(_fill_ask(), _answer(**changes))  # noqa: E731
    assert fault(legs={'left': _leg(None, 9), 'right': _leg(1, 10)}) == 'the left leg names no hip'
    assert fault(hips=None) == 'hips is None, which is no joint of the table'
    assert fault(skull=42) == 'skull is 42, which is no joint of the table'
    assert fault(neck=None) is None, 'a fitted skeleton may have no neck: rigswap decides that'
    assert fault(arms={'left': _arm(5, 99), 'right': _arm(7, 8)}) == \
        "the left arm's hand is 99, which is no joint of the table"
    assert fault(arms={'left': _arm(5, 5), 'right': _arm(7, 8)}) == 'the left arm is one joint: it needs two ends'
    assert fault(arms={'left': _arm(5, 6), 'right': _arm()}) == 'one of the arms is named and not the other'
    assert fault(arms={'left': _arm(), 'right': _arm()}) is None, 'a body with no arms'
    assert fault(plan='quadruped', arms={'left': _arm(), 'right': _arm()}) == \
        'a quadruped has hind legs and, as its arms, front legs'
    assert fault(plan='ball', hips=None, arms={'left': _arm(5, None)}) is None, 'left to rigswap\'s own reading'


def test_what_the_schema_check_refuses_is_left_to_rigswap():
    """A wrong kind of value gets rigswap's own schema message (problem-<id>.json), not a guess from here."""
    assert ask_checks.fault(_fill_ask(), _answer(hips='1')) is None
    assert ask_checks.fault(_fill_ask(), _answer(arms=[1, 2])) is None
    assert ask_checks.fault(_fill_ask(), _answer(hips=True)) is None
    assert ask_checks.fault({'round': 'describe round 1'}, {'up': None}) is None, 'an ask these rules do not cover'
    assert ask_checks.fault(_fill_ask(), 'not an object') is None


def test_without_its_table_only_what_the_answer_alone_shows_is_checked():
    ask = _fill_ask(question='No table here.')
    assert ask_checks.fault(ask, _answer(skull=42)) is None
    assert ask_checks.fault(ask, _answer(hips=None)) == 'hips is None, which is no joint of the table'
    assert ask_checks.fault(ask, _answer(arms={'left': _arm(5, None), 'right': _arm(7, 8)})) == \
        'the left arm names no hand'


LIMB_QUESTION = '''This is one arm of a 3D character model.

  n  along  turn  skin
 12      0     0    30
 15     25    10    20
 17     50    47    20
 20     75     5    10
 21    100     0     5

What to answer, each a dot's number from the table:'''


def _limb_ask(parts=ARM[1:], question=LIMB_QUESTION):
    return {'id': '1-2', 'round': 'core fill limb', 'question': question,
            'schema': {'type': 'object', 'required': list(parts)}}


def test_a_limbs_close_up_answer():
    fault = lambda **joints: ask_checks.fault(_limb_ask(), {'shoulder': None, 'elbow': None, 'hand': None,  # noqa
                                                            **joints})
    assert fault(shoulder=12, elbow=17, hand=20) is None
    assert fault(shoulder=12, elbow=17) == 'no hand is named'
    assert fault(shoulder=12, elbow=18, hand=20) == 'the elbow is 18, which is no dot of this line'
    assert fault(shoulder=17, elbow=15, hand=20) == 'the elbow (15) does not lie past the shoulder (17) along the line'
    leg = _limb_ask(parts=LEG)
    assert ask_checks.fault(leg, {'hip': 12, 'knee': None, 'ankle': None, 'toe': 21}) == 'no ankle is named'
    assert ask_checks.fault(_limb_ask(parts=('a', 'b')), {'a': None, 'b': None}) is None, 'not a limb ask it knows'


# ------------------------------------------------------------------ parity with the pinned rigswap

def _pinned_fill():
    manifest = json.loads((APP / 'utility' / 'rigswap.manifest.json').read_text(encoding='utf-8'))
    commit = manifest['rigswap']['commit']
    repo = Path(os.environ.get('RIGSWAP_REPO') or Path.home() / 'projects' / 'rigswap')
    if not (repo / '.git').exists():
        pytest.skip(f'no rigswap clone at {repo} (RIGSWAP_REPO)')
    shown = subprocess.run(['git', '-C', str(repo), 'show', f'{commit}:rigswap/core/fill.py'],
                           capture_output=True, text=True, encoding='utf-8')
    if shown.returncode:
        pytest.skip(f'the pinned rigswap {commit[:9]} is not in {repo}: {shown.stderr.strip()}')
    return shown.stdout


WANTED = {'VIEWS', 'LEG', 'ARM', 'SPAN', 'QUESTION', 'NECK_OWN', 'FITTED', 'LIMB', 'ARM_ASKED', 'LEG_ASKED',
          'Unusable', 'sides', 'table', 'entries', 'turns', 'limb_table', '_limb_fault'}


@pytest.fixture(scope='module')
def rigswap_fill():
    """The pinned fill.py's own rules and question builders, run here: its module-level definitions named in
    WANTED, with numpy and a body reading that builds every body (what needs the model is not compared)."""
    import numpy as np
    tree = ast.parse(_pinned_fill())
    keep = []
    for node in tree.body:
        names = {node.name} if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else \
            {t.id for t in getattr(node, 'targets', []) if isinstance(t, ast.Name)} | \
            {e.id for t in getattr(node, 'targets', []) if isinstance(t, ast.Tuple) for e in t.elts
             if isinstance(e, ast.Name)}
        if names & WANTED:
            keep.append(node)
    body = types.SimpleNamespace(_descends=lambda parents, b, a: True, _from_record=lambda *a, **k: None,
                                 _Mass=lambda rig: None)
    scope = {'np': np, 'json': json, 'body_reading': body}
    exec(compile(ast.Module(body=keep, type_ignores=[]), 'rigswap/core/fill.py', 'exec'), scope)
    missing = WANTED - set(scope)
    assert not missing, f'the pinned fill.py no longer has {missing}: ask_checks restates what is gone'
    assert ask_checks.LEG == scope['LEG'] and ask_checks.ARM == scope['ARM']
    return scope


def _rows():
    """Ten joints as fill.joints writes them, the table's rows (``bone`` is the rig's index)."""
    names = ['hips', 'chest', 'head', 'skull', 'arm_l', 'hand_l', 'arm_r', 'hand_r', 'leg_l', 'leg_r']
    parents = [None, 1, 2, 3, 2, 5, 2, 7, 1, 1]
    places = [(0, 0, 50), (0, 0, 70), (0, 0, 90), (0, 0, 95), (10, 0, 75), (20, 0, 70), (-10, 0, 75), (-20, 0, 70),
              (5, 0, 30), (-5, 0, 30)]
    return [{'n': i + 1, 'parent': parents[i], 'across': float(x), 'deep': float(y), 'high': float(z), 'skin': 10,
             'below': 0, 'names': [names[i]], 'bone': i} for i, (x, y, z) in enumerate(places)]


def _rigswap_says(scope, rows, answer):
    import numpy as np
    rig = types.SimpleNamespace(names=[r['names'][0] for r in rows],
                                heads=np.array([[r['across'], r['deep'], r['high']] for r in rows], float))
    # A null neck is accepted on a fitted skeleton (``settle``) only; the app leaves that one to rigswap, so it is
    # compared as rigswap judges a fitted one.
    settle = (lambda out: (rig, out)) if answer.get('neck') is None else None
    try:
        scope['entries'](rig, types.SimpleNamespace(parents=None), rows, answer, (0.0, 0.0, 1.0), settle)
    except scope['Unusable'] as e:
        return str(e)
    return None


def _answers():
    """Whole-body answers that fit the schema, the ways they go wrong: each limb end named or not, joints off the
    table, one joint for a limb, one side only, plans, a missing core joint."""
    arms = [_arm(5, 6), _arm(5, None), _arm(None, 6), _arm(), _arm(5, 5), _arm(5, 99), _arm(5, 6, elbow=42),
            _arm(5, 6, clavicle=2)]
    legs = [_leg(1, 9), _leg(None, 9), _leg(1, None), _leg(), _leg(9, 9), _leg(1, 9, toe=77)]
    for left_arm, right_arm in itertools.product(arms, [_arm(7, 8), _arm()]):
        yield _answer(arms={'left': left_arm, 'right': right_arm})
    for left_leg, right_leg in itertools.product(legs, [_leg(1, 10), _leg()]):
        yield _answer(legs={'left': left_leg, 'right': right_leg})
    for plan in ('biped', 'quadruped', 'ball', 'other'):
        yield _answer(plan=plan)
        yield _answer(plan=plan, arms={'left': _arm(), 'right': _arm()})
        yield _answer(plan=plan, legs={'left': _leg(), 'right': _leg()})
    for key, value in itertools.product(('hips', 'chest', 'neck', 'skull'), (None, 11, 0, 3)):
        yield _answer(**{key: value})
    yield _answer(hips=None, arms={'left': _arm(5, None), 'right': _arm(7, 8)})


def test_the_whole_body_rules_say_what_the_pinned_rigswap_says(rigswap_fill):
    rows = _rows()
    question = rigswap_fill['QUESTION'].format(table=rigswap_fill['table'](rows), again='', fitted='',
                                               neck=rigswap_fill['NECK_OWN'])
    compared, said = 0, set()
    for answer in _answers():
        for round_ in ask_checks.FILL_ROUNDS:
            ours = ask_checks.fault(_fill_ask(question, round_), answer)
            assert ours == _rigswap_says(rigswap_fill, rows, answer), answer
            compared += 1
            said.add(ours)
    assert compared > 100
    assert {None, 'the left arm names no hand', 'the left leg names no hip', 'one of the arms is named and not the other',
            "the left arm's hand is 99, which is no joint of the table", 'the left arm is one joint: it needs two ends',
            'a quadruped has hind legs and, as its arms, front legs', 'skull is 11, which is no joint of the table'} <= said


def test_a_limbs_rules_say_what_the_pinned_rigswap_says(rigswap_fill):
    rows = [{'n': n, 'parent': None, 'across': float(i), 'deep': 0.0, 'high': float(i * i), 'skin': 10, 'below': 0,
             'names': [str(n)], 'bone': i} for i, n in enumerate((12, 15, 17, 20, 21))]
    dots = [r['n'] for r in rows]
    for parts, asked in ((ARM[1:], rigswap_fill['ARM_ASKED']), (LEG, rigswap_fill['LEG_ASKED'])):
        question = rigswap_fill['LIMB'].format(
            limb='arm', who='', joints='joints', first=dots[0], last=dots[-1], bend='elbow',
            table=rigswap_fill['limb_table'](rows, dots), asked=asked.format(limb='arm', end='hand'), again='')
        choices = [None, 12, 17, 20, 21, 18]
        for values in itertools.product(choices, repeat=len(parts)):
            answer = dict(zip(parts, values))
            assert ask_checks.fault(_limb_ask(parts, question), answer) == \
                rigswap_fill['_limb_fault'](answer, dots, parts), answer
