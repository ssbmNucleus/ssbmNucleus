"""The rules rigswap holds a skeleton answer to, checked as the app's MCP takes the answer (``answer_import``), so the
user's AI hears at once, in rigswap's words, what rigswap would only say an ask later.

rigswap's relay (rigswap/ai.py ``_relayed``) checks an answer against its ask's schema and takes it. The skeleton
asks then hold it to more than its shape (rigswap/core/fill.py), and an answer that breaks one of those rules is not
handed back: rigswap asks a new round, "An earlier answer could not be used: the left arm names no hand. Answer again
with that put right." (0.9.0 build 3 smoke: the schema lets an arm's hand be null, ``answer_import`` said accepted,
and the user's AI spent a round on it.)

Here are those rules as far as the answer and its ask tell them, by the ask's ``round`` (rigswap's route name):

* ``core fill`` and ``core fill again`` (``fill.read`` -> ``fill.entries``): a body planned as a biped or a quadruped
  names its hips, chest and skull from the table; an arm or a leg that is named at all names both of its ends
  (shoulder and hand, hip and ankle) on joints of the table, and two different ones; a pair is named on both sides or
  on neither; a quadruped has both pairs. A null neck is left to rigswap: it is a fault only on a skeleton the file
  had (a fitted one may have no neck), which the answer does not say.
* ``core fill limb`` and ``core fill limb again`` (``fill.closer`` -> ``fill._limb_fault``): one limb's answer names
  both its ends, each joint a dot of the limb's line, and in order along it.

What needs the model itself (which side a limb lies on, whether the body builds on those joints) stays rigswap's, so
an answer let through here can still come back as a new ask. A value of the wrong kind is left alone: rigswap's own
schema check refuses it first, in its words. These rules are restated, not imported: rigswap's code runs only in its
own Python, beside the model. tests/backend/test_relay_answer_checks.py runs the pinned rigswap's own ``entries``
and ``_limb_fault`` on the same answers and checks both say the same.
"""
import re

FILL_ROUNDS = ('core fill', 'core fill again')
LIMB_ROUNDS = ('core fill limb', 'core fill limb again')
LEG, ARM = ('hip', 'knee', 'ankle', 'toe'), ('clavicle', 'shoulder', 'elbow', 'hand')
LIMBS = (('legs', LEG, ('hip', 'ankle')), ('arms', ARM, ('shoulder', 'hand')))
CORE = ('hips', 'chest', 'neck', 'skull')

_ROW = re.compile(r'\s*(\d+)\s')


class _Unread(Exception):
    """A value of a kind the schema does not allow: rigswap's schema check says so, not this."""


def _joint(value):
    if value is None or (isinstance(value, int) and not isinstance(value, bool)):
        return value
    raise _Unread()


def _table(question, header):
    """The numbers in the first column of the table in ``question`` whose header line starts with ``header`` (the
    words of its first columns), in order; None when the question has no such table."""
    lines = str(question or '').splitlines()
    for i, line in enumerate(lines):
        if line.split()[:len(header)] == list(header):
            numbers = []
            for row in lines[i + 1:]:
                found = _ROW.match(row)
                if not found:
                    break
                numbers.append(int(found.group(1)))
            return numbers or None
    return None


def _fill_fault(answer, joints):
    """fill.entries' rules, in its words, for one whole-body answer; ``joints``: the table's numbers, or None."""
    if answer.get('plan') not in ('biped', 'quadruped'):
        return None                         # a ball or another plan: rigswap leaves the body to its own reading

    def known(n, what):
        if n is None or (joints is not None and n not in joints):
            return f'{what} is {n!r}, which is no joint of the table'
        return None

    for key in CORE:
        n = _joint(answer.get(key))
        if key == 'neck' and n is None:
            continue                        # a fitted skeleton's look may say it has no neck
        fault = known(n, key)
        if fault:
            return fault
    named_pairs = set()
    for limbs, parts, ends in LIMBS:
        pair = answer.get(limbs) or {}
        if not isinstance(pair, dict):
            raise _Unread()
        found = 0
        for side in ('left', 'right'):
            said = pair.get(side) or {}
            if not isinstance(said, dict):
                raise _Unread()
            said = {p: _joint(said.get(p)) for p in parts}
            if all(said[p] is None for p in parts):
                continue                    # the body has no such limb
            for end in ends:
                if said[end] is None:
                    return f'the {side} {limbs[:-1]} names no {end}'
            named = [said[p] for p in parts if said[p] is not None]
            for p in parts:
                if said[p] is not None:
                    fault = known(said[p], f"the {side} {limbs[:-1]}'s {p}")
                    if fault:
                        return fault
            if len(set(named)) < 2:
                return f'the {side} {limbs[:-1]} is one joint: it needs two ends'
            found += 1
        if found == 1:
            return f'one of the {limbs} is named and not the other'
        if found:
            named_pairs.add(limbs)
    if answer.get('plan') == 'quadruped' and named_pairs != {'legs', 'arms'}:
        return 'a quadruped has hind legs and, as its arms, front legs'
    return None


def _limb_fault(answer, dots, parts):
    """fill._limb_fault, in its words: the limb's two ends are named, each joint a dot of its line, in order along
    it. ``dots``: the line's dots from the question's table, or None (only the ends are checked then)."""
    said = {p: _joint(answer.get(p)) for p in parts}
    ends = (parts[0], parts[-2] if parts[-1] == 'toe' else parts[-1])
    for end in ends:
        if said[end] is None:
            return f'no {end} is named'
    if dots is None:
        return None
    named = [(p, said[p]) for p in parts if said[p] is not None]
    for p, n in named:
        if n not in dots:
            return f'the {p} is {n!r}, which is no dot of this line'
    for (p, a), (q, b) in zip(named, named[1:]):
        if dots.index(b) <= dots.index(a):
            return f'the {q} ({b}) does not lie past the {p} ({a}) along the line'
    return None


def fault(ask, answer):
    """Why rigswap could not use ``answer`` to the relayed ``ask`` (its ``ask-<id>.json`` record), in rigswap's own
    words, or None: an ask these rules do not cover, an answer they let through, or one whose shape is rigswap's
    schema check to refuse."""
    if not isinstance(ask, dict) or not isinstance(answer, dict):
        return None
    rounds = ask.get('round')
    try:
        if rounds in FILL_ROUNDS:
            return _fill_fault(answer, _table(ask.get('question'), ('n', 'parent')))
        if rounds in LIMB_ROUNDS:
            schema = ask.get('schema') if isinstance(ask.get('schema'), dict) else {}
            parts = tuple(schema.get('required') or ())
            if parts not in (ARM[1:], LEG):
                return None                 # not a limb ask this knows
            return _limb_fault(answer, _table(ask.get('question'), ('n', 'along')), parts)
    except _Unread:
        return None
    return None
