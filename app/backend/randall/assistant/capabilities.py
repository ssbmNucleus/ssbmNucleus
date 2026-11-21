"""What this app can and cannot do, as DATA, beside the operations themselves.

Design source: artifacts/harness-experiment-20260922/ASTRA-WISH.md, section 1
("Use a small capability definition for each actual missing operation: canonical
name, operation, implementation version, supported scope, limitation sentence,
and real alternatives. This is data owned beside the relevant operation, not a
growing collection of exception-message special cases.").

Two rules shape this module:

* **Nothing here is inferred from prose.** A capability is declared by the
  people who wrote the operation, with a version string that changes when the
  implementation changes. `wishes.classify_blocker` will only call something a
  missing capability when a definition here says so. No message matching, no
  `note`/`limitations` scanning.
* **A definition states its SCOPE, not just its name.** "Cannot commit to an
  extracted ISO folder" is a bounded claim; "cannot install builds" is not. The
  `variants` tuple is the bounded technical distinction that changes which
  implementation is missing (a build format, a per-mesh mask versus separate
  overlapping texture storage) and is the only free dimension of the grouping
  key. Wording, model, app release, character, asset hash, path, task id and
  user identity are deliberately not part of it.

`capability_status(operation)` is the read-only lookup the model-facing tool
wraps (its schema lives in tools.py, which this builder does not own -- see
artifacts/harness-experiment-20260922/W/INTEGRATION-PATCHES.md). It answers
`supported`, `unsupported`, `outside_scope` or `unknown`, and *only* a confirmed
`unsupported` may become a wish.
"""
from dataclasses import dataclass, field

#: Bumped when the *shape* of a definition changes, not when one is added.
CAPABILITIES_VERSION = 1

#: What `capability_status` can answer. `unknown` is the honest default: an
#: operation nobody declared is not thereby missing, and it is not thereby
#: present either. Only `unsupported` is evidence of a capability gap.
STATUSES = ('supported', 'unsupported', 'outside_scope', 'unknown')

#: Which product domain a requested operation belongs to. `melee` is inside the
#: product's intended domain (so an unimplemented operation there is a legitimate
#: feature request); `outside` is not (so it must never fill the backlog).
DOMAINS = ('melee', 'outside')


@dataclass(frozen=True)
class Capability:
    """One declared operation: what it is, which build lacks it, and what to do
    instead.

    Fields are the design's list verbatim:

    name
        The canonical capability name. This is the backlog row's identity and
        the first component of the grouping key; it never carries a version, a
        character or a file.
    operation
        The operation a caller actually tried to perform, e.g.
        ``builds.commit_change``. `capability_status` is keyed on this.
    implementation_version
        The version of the shipped implementation that has this status. Two
        different implementation versions are two different backlog rows,
        because shipping a renderer must not be silently credited to the gap
        that predates it. Unrelated app releases do NOT appear here.
    supported_scope
        What the implementation DOES cover, in one sentence, so an
        `unsupported` verdict is bounded rather than absolute.
    limitation
        The single honest sentence Randall may say. Ordinary language: no tool
        names, ids, flag names or "library".
    alternatives
        Real, currently available things the user can do instead. Empty is
        allowed and is better than an invented one.
    variants
        The bounded technical distinctions that change WHICH implementation is
        missing. A variant outside this tuple is not grouped; it is rejected, so
        an unbounded string (a filename, a character) can never widen the key.
    status
        One of :data:`STATUSES`, for the operation AS A WHOLE.
    domain
        One of :data:`DOMAINS`.
    supported_scopes / unsupported_scopes
        Scope tokens that override `status` for one particular input. An
        operation is rarely missing outright: `builds.commit_change` WORKS, and
        is missing only for a build that is not a Nucleus project. Declaring it
        globally unsupported made Randall say it could not install anything.
        A scope in neither tuple and not a declared variant answers `unknown`,
        which is the honest answer and never a wish.
    """
    name: str
    operation: str
    implementation_version: str
    supported_scope: str
    limitation: str
    alternatives: tuple = ()
    variants: tuple = ()
    status: str = 'unsupported'
    domain: str = 'melee'
    supported_scopes: tuple = ()
    unsupported_scopes: tuple = ()
    #: A short, stable description of the outcome the user was after. Used to
    #: generate the submitted summary from the catalog rather than from chat.
    requested_outcome: str = ''
    #: Typed evidence codes this gap is legitimately reached by. A wish whose
    #: observation carries an evidence code outside this set is refused: it is
    #: the mechanism that stops an unrelated failure from being filed here.
    evidence_codes: tuple = ()

    def status_for(self, scope=''):
        """The status for one scope: `supported`, `unsupported` or `unknown`.

        Order matters. An explicitly unsupported scope wins, then an explicitly
        supported one, then a declared variant (or no scope at all) falls back
        to the operation's own status. Anything else is an input nobody
        declared, and an undeclared input is not evidence of a missing
        capability -- the caller must refuse it rather than round it to the
        nearest known case.
        """
        scope = (scope or '').strip()
        if scope and scope in self.unsupported_scopes:
            return 'unsupported'
        if scope and scope in self.supported_scopes:
            return 'supported'
        if not scope or scope in self.variants:
            return self.status
        return 'unknown'

    def variant_or_refuse(self, variant):
        """Normalise a variant, refusing anything the definition did not declare.

        An undeclared variant would fork the grouping key on arbitrary text,
        which is exactly how one gap becomes forty rows.
        """
        variant = (variant or '').strip()
        if not variant:
            return ''
        if variant not in self.variants:
            raise ValueError(
                f'{variant!r} is not a declared variant of {self.name!r}; '
                f'declared: {list(self.variants)}')
        return variant


# ---------------------------------------------------------------------------
# The seeded definitions: the six paths the design names.
# ---------------------------------------------------------------------------

#: nucleus_api.builds -- commit_change refuses any build that is not a MEX
#: project (`nucleus_api/builds.py`, `_unsupported`/`prepare_change`).
BUILD_COMMIT = Capability(
    name='unsupported_build_commit',
    operation='builds.commit_change',
    implementation_version='builds.commit_change@1',
    supported_scope='Installing a prepared menu and its codes into a Nucleus project.',
    limitation="I can't install it into this kind of build yet.",
    alternatives=('Use the prepared files in a Nucleus project.',),
    # The build format IS the missing implementation, so it is the variant.
    # `unknown_format` is deliberately NOT here: rounding an unrecognised build
    # to a known one would file a gap nobody demonstrated. A caller that cannot
    # name the format must refuse rather than guess.
    variants=('extracted_iso', 'iso', 'gcm', 'nkit'),
    # The operation itself works -- for a Nucleus project. It is missing only
    # for the formats below, which is why `status` is `supported` and the scope
    # decides.
    status='supported',
    supported_scopes=('mex_project',),
    unsupported_scopes=('extracted_iso', 'iso', 'gcm', 'nkit'),
    requested_outcome='Install a prepared change into this build',
    evidence_codes=('operation_unavailable',),
)

#: nucleus_api.menus.preview -- there is no offline menu renderer and no
#: verified in-game menu capture. An author's screenshot is a reference and
#: never satisfies `previewed`.
MENU_PREVIEW = Capability(
    name='menu_output_preview',
    operation='render_menu_artifact',
    implementation_version='menus.preview@1',
    supported_scope='Producing and installing the menu file itself, and recording an '
                    "author's published screenshot as a reference only.",
    limitation="I can't show the finished menu yet.",
    alternatives=("Install it and look at the screen in game.",),
    variants=('character_select', 'stage_select'),
    requested_outcome='Show the produced menu screen',
    evidence_codes=('operation_unavailable',),
)

#: shared.rendering.part_identity -- a part that shares affected texels with another has
#: no per-part UV mask. `_required_mask` says so in typed form
#: (``{'required': True, 'available': False, 'kind': 'uv'}``); the colour-mask
#: case is `available: True` and is therefore NOT this gap.
INDEPENDENT_PART_RECOLOR = Capability(
    name='independent_part_recolor',
    operation='skinlab.recolor_part_in_isolation',
    implementation_version='part_identity.required_mask@1',
    supported_scope="Recolouring every part that shares the affected pixels together, and "
                    "recolouring one part's own colours inside a texture it shares.",
    limitation='Changing that part on its own would also change what it shares pixels with.',
    alternatives=('Recolour both together.', 'Leave the costume unchanged.'),
    # Two genuinely different missing implementations, per the design.
    variants=('per_mesh_mask', 'separate_overlapping_texture_usage'),
    requested_outcome='Recolour one part without changing the others',
    evidence_codes=('operation_unavailable',),
)

#: The narrower gap the design allows an inconclusive identification to reveal:
#: choosing a part INSIDE an otherwise identified texture. An unresolved label on
#: its own is a decision, not this.
PART_SELECTION_IN_TEXTURE = Capability(
    name='part_selection_within_texture',
    operation='skinlab.select_part_within_texture',
    implementation_version='part_identity.resolve_part@1',
    supported_scope='Naming which textures a mapped part uses, and confirming geometry by '
                    'highlighting a candidate in a Skin Lab session.',
    limitation="I can't let you pick a part inside a texture I've already identified.",
    alternatives=('Highlight the part in a preview, then ask again.',),
    variants=(),
    requested_outcome='Select one part inside an identified texture',
    evidence_codes=('operation_unavailable',),
)

#: Tool dispatch itself IS supported. Its definition exists so that the two
#: typed failures the design asks tools.prepare() to distinguish land correctly:
#: an INVENTED name is an invalid model call (`unknown_tool` -> a bounded repair,
#: never a wish), while an ADVERTISED name that cannot dispatch is an
#: integration bug (`undispatchable_advertised_tool` -> bug, never a wish).
TOOL_DISPATCH = Capability(
    name='tool_dispatch',
    operation='assistant.tools.dispatch',
    implementation_version='tools.prepare@1',
    supported_scope='Running any operation advertised in this turn.',
    limitation="I couldn't run that action.",
    alternatives=('Use one of the available actions.',),
    status='supported',
    requested_outcome='Run a requested action',
    evidence_codes=('unknown_tool', 'disabled_operation', 'undispatchable_advertised_tool'),
)

#: Inside Melee/Nucleus, outside today's Randall capabilities: the design's own
#: example of a LEGITIMATE capability request (the chat prompt excludes moveset
#: authoring explicitly).
MOVESET_AUTHORING = Capability(
    name='moveset_authoring',
    operation='fighter.author_moveset',
    implementation_version='randall.chat@1',
    supported_scope='Making a separate character that keeps an existing fighter\'s moves, '
                    'attributes, animations and audio.',
    limitation="I can't create new moves yet.",
    alternatives=('Make a separate character using existing moves.',),
    variants=(),
    requested_outcome='Give a character new moves',
    evidence_codes=('operation_unavailable',),
)

#: Outside the product's domain entirely. Listed so `capability_status` can say
#: `outside_scope` with a definition behind it instead of guessing, and so these
#: requests can never reach the modding backlog.
OUT_OF_DOMAIN = tuple(
    Capability(name=name, operation=operation, implementation_version='randall.scope@1',
               supported_scope='Melee modding inside SSBM Nucleus.',
               limitation=limitation, alternatives=(), status='outside_scope', domain='outside',
               requested_outcome='', evidence_codes=('out_of_scope_request',))
    for name, operation, limitation in (
        ('unrelated_general_assistance', 'general.assistant_chat',
         'That is outside what I work on here.'),
        ('other_game_modding', 'other_game.modify',
         'I only work on Melee mods in this app.'),
    ))

CAPABILITIES = (BUILD_COMMIT, MENU_PREVIEW, INDEPENDENT_PART_RECOLOR,
                PART_SELECTION_IN_TEXTURE, TOOL_DISPATCH, MOVESET_AUTHORING) + OUT_OF_DOMAIN

# Deliberately NOT declared: `designated_play_copy`, the delivery path's "I
# cannot know which file you launch". The app CAN write a build into a copy the
# user names; what is missing is the user's choice of that file, and an unset
# preference with an existing alternative ("designate one") is a decision, not
# a capability gap. Declaring it here would be enough to let a caller file it,
# so the absence is the safeguard -- `capability_status` answers `unknown` and
# `classify_blocker` refuses to call it a wish. See `delivery/deliver.py`.

_BY_OPERATION = {c.operation: c for c in CAPABILITIES}
_BY_NAME = {c.name: c for c in CAPABILITIES}


def by_operation(operation):
    """The definition for an operation, or None. Never raises: an unknown
    operation is a legitimate answer, not an error."""
    return _BY_OPERATION.get((operation or '').strip())


def by_name(name):
    """The definition for a canonical capability name, or None."""
    return _BY_NAME.get((name or '').strip())


def capability_status(operation, scope=''):
    """`supported` | `unsupported` | `outside_scope` | `unknown` for an operation.

    Read-only and offline: it consults the definitions above and nothing else.
    This is the function the model-callable `capability_status` tool wraps, and
    the only sanctioned way to answer "can Randall do X?" without guessing.

    `scope` narrows the answer to one input -- a build format, a mask kind --
    because most operations are missing for SOME inputs rather than absent.
    Asking without a scope gives the operation's own status.

    An operation with no definition is `unknown`, which is NOT evidence of a
    gap. An unknown proposal goes to the manually reviewed feature-request form,
    never to the automatic backlog.
    """
    definition = by_operation(operation)
    if definition is None:
        return 'unknown'
    if definition.status == 'outside_scope':
        return 'outside_scope'
    return definition.status_for(scope)


def describe(operation, scope=''):
    """The full public description of an operation, for a UI or a tool result.

    Returns catalogue data only -- no chat text, no paths, no evidence.
    """
    definition = by_operation(operation)
    if definition is None:
        return {'operation': operation, 'status': 'unknown',
                'note': 'Nothing in this build declares that operation either way.'}
    return {'operation': definition.operation, 'capability': definition.name,
            'status': capability_status(definition.operation, scope),
            'overall_status': definition.status, 'domain': definition.domain,
            'supported_scopes': list(definition.supported_scopes),
            'unsupported_scopes': list(definition.unsupported_scopes),
            'implementation_version': definition.implementation_version,
            'supported_scope': definition.supported_scope,
            'limitation': definition.limitation,
            'alternatives': list(definition.alternatives),
            'variants': list(definition.variants)}
