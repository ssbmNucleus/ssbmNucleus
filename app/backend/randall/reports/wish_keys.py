"""A wish's stable identity and the only strings allowed out: the versioned grouping key, validated
workflow, version and key identifiers, canonical payload hashing, and strict consent booleans."""

import hashlib
import json
import os
import re

from randall.assistant import capabilities


#: The literal first component of the grouping key. Changing it re-groups every
#: backlog row, so it is versioned separately from everything else.
GROUPING_KEY_PREFIX = 'wish-v1'


def strict_bool(value):
    """A real boolean, or nothing.

    The consent and identity flags arrive as JSON. `"false"`, `"0"` and `0` are
    all truthy-or-falsy in ways that differ between languages, and the review
    reproduced `include_identity: "false"` switching identity ON. A consent
    decision is too important to infer, so anything that is not a Python `bool`
    is refused rather than coerced.
    """
    if value is True or value is False:
        return value
    raise ValueError('that choice must be true or false, not text')


# ---------------------------------------------------------------------------
# Grouping key
# ---------------------------------------------------------------------------

def dedupe_key(capability, blocked_operation, implementation_version, variant=''):
    """``SHA256(canonical_JSON([...]))`` over exactly five components.

    Deliberately excluded, because they split one gap into many rows without
    changing what is missing: wording, model, app release, character name, asset
    hash, paths, task ids and user identity. The implementation version IS
    included, because shipping a renderer must open a new row rather than
    silently close the old one.
    """
    return payload_hash([GROUPING_KEY_PREFIX, capability, blocked_operation,
                         implementation_version, variant or ''])


def key_for(classification):
    return dedupe_key(classification.capability, classification.blocked_operation,
                      classification.implementation_version, classification.variant)


def short_key(key):
    """The first 12 hex digits, for a Discord field and a UI row."""
    return (key or '').split(':')[-1][:12]


# ---------------------------------------------------------------------------
# Validated identifiers -- the only strings allowed out of this module
# ---------------------------------------------------------------------------

#: Workflow identifiers this build knows. Anything else becomes `other`: the
#: workflow arrives over HTTP and from facade callers, and the review's probe
#: carried a canary straight through it into `meta.json` and `wish.json`.
KNOWN_WORKFLOWS = frozenset((
    'randall_turn', 'recolor_part', 'menu_background_replace', 'install_menu',
    'deliver_to_game', 'model_import', 'costume_import', 'stage_import',
    'clone_character', 'test_in_game', 'other',
))

_APP_VERSION_RE = re.compile(r'\A[0-9A-Za-z][0-9A-Za-z._+-]{0,31}\Z')
_KEY_RE = re.compile(r'\Asha256:[0-9a-f]{64}\Z')
_SUBMISSION_ID_RE = re.compile(r'\Awsub_[0-9a-f]{16}\Z')


def safe_workflow(workflow):
    """A known workflow identifier, or `other`. Never the caller's text."""
    workflow = (workflow or '').strip()
    return workflow if workflow in KNOWN_WORKFLOWS else 'other'


def safe_app_version():
    """The app version if it looks like one, else `unknown`.

    It comes from the environment, which a packaged build controls but a dev
    machine does not, and it is the one free-ish string the design wants sent.
    Bounded and character-checked rather than trusted.
    """
    value = (os.environ.get('NUCLEUS_APP_VERSION') or '').strip()
    return value if _APP_VERSION_RE.match(value) else 'unknown'


def app_version():
    return safe_app_version()


def api_version():
    return f'capabilities@{capabilities.CAPABILITIES_VERSION}'


def valid_key(key):
    return bool(_KEY_RE.match(key or ''))


def canonical_payload(payload):
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _sha256(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def payload_hash(payload):
    return _sha256(canonical_payload(payload).encode('utf-8'))
