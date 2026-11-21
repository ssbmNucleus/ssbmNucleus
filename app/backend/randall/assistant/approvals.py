"""Per-action approval state. No client-supplied arguments or blanket permissions.

The engine owns pending requests; the HTTP layer decides their opaque IDs and
selects only offered scope IDs. Grants bind an immutable prepared call and its
selected scope, and are consumed once by the dispatcher.
"""
import hashlib
import json
import threading
import time
import uuid
from dataclasses import dataclass

APPROVAL_TIMEOUT = 15 * 60
TERMINAL = {'approved', 'denied', 'cancelled', 'expired', 'interrupted'}


@dataclass(frozen=True)
class PreparedCall:
    name: str
    arguments: str
    plan: str
    preview: str
    policy: str

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps([self.name, self.arguments, self.plan, self.policy]).encode()).hexdigest()


class Grant:
    def __init__(self, fingerprint, choice=None):
        self._fingerprint = fingerprint
        self.choice = choice
        self._used = False
        self._lock = threading.Lock()

    def consume(self, fingerprint):
        with self._lock:
            if self._used or self._fingerprint != fingerprint:
                return False
            self._used = True
            return True


class UnofferedChoice(ValueError):
    """The decision named an option this approval did not offer.

    Distinct from "no such approval" so the HTTP layer can answer 400 for a
    bad choice and 404 for a missing approval; they used to be the same
    ValueError, which is why an unoffered id looked like a missing chat.
    """


def request(preview):
    now = time.time()
    return {**preview, 'id': uuid.uuid4().hex, 'status': 'pending', 'created_at': now,
            'expires_at': now + APPROVAL_TIMEOUT}


def decide(approval, decision, choice=None):
    """Caller holds the run lock. Retries of the same decision are idempotent."""
    if decision not in ('approve', 'deny'):
        raise ValueError('Decision must be approve or deny.')
    choices = [option['id'] for option in approval.get('choices', [])]
    if decision == 'approve' and choices:
        if choice not in choices:
            raise UnofferedChoice('Choose one of the offered download options.')
    elif choice is not None:
        raise UnofferedChoice('This decision does not accept a download option.')
    target = 'approved' if decision == 'approve' else 'denied'
    if approval['status'] == target:
        if approval.get('choice') != choice:
            raise RuntimeError('This approval already used a different download option.')
        return False
    if approval['status'] != 'pending':
        raise RuntimeError('This approval is no longer pending.')
    if time.time() >= approval['expires_at']:
        raise RuntimeError('This approval has expired.')
    approval.update(status=target, decision=decision, decided_at=time.time())
    if choice is not None:
        approval['choice'] = choice
    return True
