"""The delivery path: a vault costume, into the copy of the game someone plays.

Randall's project tools add a costume to a project's *inputs*. A project input
is not a game. The review this module implements is blunt about the difference:
"saved to your library" and "added to the project" are intermediate states that
must never be presented as "in your game", and the first product milestone is a
beginner getting one change into the game they actually play, understanding
what happened, and being able to undo it.
(artifacts/harness-experiment-20260922/ASTRA-BIGPICTURE.md)

**What this module may write.** Exactly three things, and nothing else:

1. the destination project's own files, through MexCLI's import/remove commands;
2. the export artifact under ``output/artifacts/``, through the exporter;
3. the ONE playable copy the user designated -- and only after
   `destination.check_output_path` has confirmed it is not the clean Melee ISO
   and not a file this app did not produce, only by staging beside it and
   `os.replace`-ing after the staged bytes were hashed against the build, and
   only after moving the previous copy aside so an undo has something to put
   back. The clean Melee ISO is a read-only source, forever.

**Structure.** A delivery is a journaled operation with five phases -- install,
export, verify_build, promote, activate -- and a receipt that is written
*before* the first mutation and updated after each one. That gives three
properties the first version did not have:

* **Truthful completion.** `achieved` is derived by one predicate,
  `current_state`, which re-reads reality: the costume slots are still in the
  project with the bytes we put there, the playable copy on disk still hashes
  to the build we made, and the player is pointed at it. The receipt, the flags
  and the sentence all come from that one reading, so they cannot disagree.
* **Resumability.** A second attempt does not reinstall: it runs the phases
  that are not done. An interrupted delivery is a `running` receipt that
  `recover_deliveries` reconciles against what is actually on disk.
* **Restoration.** Undo removes exactly the slots this delivery added --
  identified by content hash, not by position -- and puts the previous playable
  copy back. It is itself resumable, and it reports `undone` only once both
  halves are verified.

**Three things this module deliberately does NOT do**, because claiming them
would be the same lie in a new place:

* It does not delete anything from the library. Removing a costume from a build
  and deleting a saved copy are different operations with different receipts
  (session S07); this one only ever touches the build and its playable copy.
* It does not judge gameplay. Hashing the costume's bytes inside the disc image
  proves the file is on the disc; it says nothing about how the costume moves,
  and nothing here checks that the game boots. The envelope keeps interactive
  play, automated movement checks and whole-build checks apart.
* It does not report a fresh Slippi test. The vault's label carries its own
  provenance -- validator, manual override, retest date -- and it is reported
  as whatever it actually is.
"""

import hashlib
import json
import time
from pathlib import Path

from core import critical_ops, playable_iso
from core.metadata import load_metadata

from randall.assistant.tasks.contracts import new_id
from . import destination as destinations
from . import projects

# The delivery path's public names live in the modules below; `__all__` re-exports them.
from .deliver_checks import (_absence_check, _check, _iso_check, _label_limitation,
                             _label_provenance, _not_run_checks, _slippi_check)
from .deliver_policy import (PHASES, RECEIPT_SCHEMA, REQUESTED_OUTCOMES, WORKFLOW, WORKFLOW_VERSION,
                             DeliveryError, OnlineRiskUndecided, delivery_enabled)
from .deliver_project import _added_slots, _costume_table, _member_states, _project_revision, _resolve_build
from .deliver_receipts import (_achieved, current_state, _later_active_deliveries, list_deliveries,
                               public_deliveries, read_receipt, recover_deliveries,
                               _standing_receipt, _write_receipt)
from .deliver_replies import (_blocked_undo, _build_unverified, _decision, _delivered, _envelope,
                              _export_failed, _finish, _gated, _install_failed, _placement,
                              _prepared_only, _undecided_envelope, _verification_facts)
from .deliver_steps import (_build_session, _default_export, _default_install, _default_remove,
                            _promote_artifact, _restore_playable_copy)


def _subject_from_post(data, post_id):
    """A website post already downloaded into the vault -> its vault costume."""
    ledger = (data.get('_website_imports') or {}).get(str(post_id)) or []
    costumes = [reference for reference in ledger if reference.get('kind') == 'costume']
    if not costumes:
        raise DeliveryError('That mod is not in your library yet. Download it first, '
                            'then I can put it in your game.')
    if len(costumes) > 1:
        raise DeliveryError('That mod put several costumes in your library. '
                            'Name the one to put in the game: '
                            + ', '.join(f"{c['owner']} {c['id']}" for c in costumes[:6]) + '.')
    return costumes[0]['owner'], costumes[0]['id']


#: Every provenance field the vault stores about an online-play label. Carried
#: whole, because "safe" from a validator run at import, "safe" set by hand and
#: "safe" from a retest last week are three different claims.
LABEL_FIELDS = ('slippi_safe', 'slippi_tested', 'slippi_test_date',
                'slippi_manual_override', 'dat_hash')


def _resolve_subject(args):
    from randall.assistant.vault_items import _item, _skin
    data = load_metadata(default={})
    if args.get('website_post_id') is not None and not args.get('skin_id'):
        character, skin_id = _subject_from_post(data, args['website_post_id'])
    else:
        character, skin_id = args.get('character'), args.get('skin_id')
        if not character or not skin_id:
            raise DeliveryError('Name the costume by its exact character and vault ID, '
                                'or give the website post it came from.')
    character, skin = _skin(data, character, skin_id)
    if skin.get('is_nana'):
        raise DeliveryError('Choose the Ice Climbers costume; its paired Nana comes along '
                            'automatically.')
    item = _item(character, skin)
    return {'kind': 'vault_costume', 'character': character, 'skin_id': skin['id'],
            'name': item['name'], 'key': f"vault_costume:{character}:{skin['id']}",
            'label': {field: skin.get(field) for field in LABEL_FIELDS},
            'item': item}


# No wish is filed from this module. A delivery with no designated game copy is
# a setting the user has not made yet, with an alternative that already exists
# ("designate one"), and `contracts.Wish` is explicit that a denial or an unset
# preference is not a capability gap. If a genuinely unsupported build format
# turns up here, file it through `reports/wishes.py` (`classify_blocker`
# -> `record`) with a typed evidence code -- never by constructing a Wish.

# --------------------------------------------------------------------------
# planning
# --------------------------------------------------------------------------

def _iso_filename(project):
    from werkzeug.utils import secure_filename
    stem = secure_filename(project['name']) or 'nucleus-build'
    return f'{stem[:60]}.iso'


#: `set_as_my_game` -> the destination kind its approval designates. "Randall never
#: picks a destination" still holds: this is the user's explicit choice, made on the
#: approval card that names the project and the new file, and nothing is designated
#: unless they press it. Before this existed nothing in the app could designate one
#: (POST /destination had no caller), so a delivery for someone with no game copy
#: set always ended at "a disc image exists, but nothing you launch changed".
MY_GAME_KINDS = {'slippi': 'slippi_netplay', 'offline': 'offline_build'}


def _designation(args, record, project):
    """The game copy approving this delivery makes the user's, or None.

    Only when the call asks for it (`set_as_my_game`), only for a named project,
    and only when no game copy is designated for that project already. The new
    copy goes to this app's own output folder under a Nucleus-suffixed name
    (`destination.suggested_output`), so it is never the clean Melee file and never
    a file somebody else made; for a Slippi copy the played-ISO rule runs now,
    before the card is shown, so its question is asked instead of approved past.

    Raises:
        DeliveryError: with the sentence the user (or the call) has to answer.
    """
    wanted = args.get('set_as_my_game')
    if not wanted:
        if args.get('start_from_clean'):
            raise DeliveryError('start_from_clean only goes with set_as_my_game.')
        return None
    if wanted not in MY_GAME_KINDS:
        raise DeliveryError(f"set_as_my_game must be one of {', '.join(MY_GAME_KINDS)}.")
    if record is not None:
        raise DeliveryError(f'{destinations.spoken(record)} is already set as the game you play. '
                            'Leave set_as_my_game out and the costume goes there.')
    if not args.get('project_id') or args.get('destination_id'):
        raise DeliveryError('Name the project (project_id) whose playable copy becomes the game '
                            'you play; set_as_my_game does not go with destination_id.')
    kind = MY_GAME_KINDS[wanted]
    output = destinations.suggested_output(project['name'])
    played = None
    try:
        destinations.check_output_path(output)
        if kind == 'slippi_netplay':
            played = destinations._played_iso_decision(
                destinations.launcher_iso(), project['id'],
                bool(args.get('start_from_clean')), output)
    except destinations.DestinationError as exc:
        raise DeliveryError(str(exc)) from exc
    previous = destinations.default_destination()
    played_name = (Path(played['played_path']).name
                   if played and played.get('played_path') and played['status'] != 'no_played_file'
                   else None)
    return {'kind': kind, 'play_mode': 'slippi_netplay' if kind == 'slippi_netplay' else 'offline',
            'label': project['name'], 'project_id': project['id'],
            'output_filename': Path(output).name,
            'start_from_clean': bool(args.get('start_from_clean')),
            'played_status': (played or {}).get('status'), 'played_filename': played_name,
            'replaces': destinations.spoken(previous) if previous else None,
            'settings_revision': destinations.settings_revision()}


def _designation_lines(designation):
    """What making this the game they play does NOT do, said before they approve it."""
    if designation['kind'] != 'slippi_netplay':
        return []
    played = designation.get('played_filename')
    return [(f'Slippi Launcher keeps opening {played} until you choose '
             if played else 'Slippi Launcher opens it once you choose ')
            + f"{designation['output_filename']} as its Melee ISO in its settings. I can't "
            + "change Slippi Launcher's settings for you."]


def plan_delivery(args):
    """Resolve subject and destination and seal the change. Writes nothing.

    Returns `(plan, preview)` in the shape the approval machinery takes, so the
    card the user confirms names the exact costume, the exact game copy, the
    limitation that matters BEFORE they press it, and what "in my game" will
    mean when it finishes.

    The plan carries a seal -- the destination's settings revision and the
    identity of the exact output file, the project's content revision, and a
    digest of the install plan -- so an approval authorizes one target and not
    "whatever that name points at later".

    Raises:
        DeliveryError: including the case where the destination has to be chosen
            first; the message lists the real game copies by name.
    """
    outcome = args.get('outcome') or 'install'
    if outcome not in REQUESTED_OUTCOMES:
        raise DeliveryError(f"outcome must be one of {', '.join(REQUESTED_OUTCOMES)}.")
    subject = _resolve_subject(args)
    record, _reason = destinations.resolve(
        destination_id=args.get('destination_id'), project_id=args.get('project_id'),
        task_destination_id=args.get('task_destination_id'))
    if record is not None:
        available = destinations.availability(record)
        if not available['ready']:
            raise DeliveryError(available['message'])
    build_id = args.get('project_id') or (record or {}).get('project_ref', {}).get('project_id')
    project, undecided = _resolve_build(build_id)
    if undecided is not None:
        raise DeliveryError(undecided['prompt'])

    designation = _designation(args, record, project)
    if designation is not None and outcome == 'prepare':
        raise DeliveryError('set_as_my_game builds the playable copy, so it goes with outcome '
                            '"install" or "play", not "prepare".')

    install_args = {'project_id': project['id'],
                    'items': [{'character': subject['character'], 'skin_id': subject['skin_id']}]}
    install_plan, install_preview = projects.prepare_install(install_args)
    play_mode = (designation or {}).get('play_mode') or (record or {}).get('play_mode', 'unset')
    where = (designation['label'] if designation else
             destinations.spoken(record) if record else project['name'])
    playable = (record is not None or designation is not None) and play_mode != 'unset'
    change = (f"add {subject['name']} to {where}"
              + (' and make it the game you play' if designation is not None else
                 ' and make a playable copy' if outcome != 'prepare' and playable else
                 ' and rebuild the project' if outcome != 'prepare' else
                 ' (project files only, no playable copy yet)'))
    limitations = _label_limitation(subject, play_mode)
    if play_mode == 'slippi_netplay' and outcome != 'prepare' \
            and _label_provenance(subject.get('label') or {})['status'] != 'pass' \
            and not args.get('online_risk_accepted'):
        raise OnlineRiskUndecided(
            limitations[0] + ' This copy is the one you play online, so say which you want: '
            'put it in anyway, or put it in an offline copy instead.')
    if not playable and outcome != 'prepare':
        limitations.append('No game copy is set as yours yet, so this builds a new copy of the '
                           "game, but it won't be the one you launch.")
    if designation is not None:
        limitations.extend(_designation_lines(designation))
    plan = {'workflow': WORKFLOW, 'workflow_version': WORKFLOW_VERSION,
            'requested_outcome': outcome, 'project': install_plan['project'],
            'destination_id': (record or {}).get('id'),
            'destination': destinations.public(record),
            'seal': {'destination': destinations.seal(record),
                     'project_revision': _project_revision(project['path']),
                     # The ASSET identities, not the whole install plan: the
                     # plan carries a snapshot of the project, which changes the
                     # moment the install lands, so keying resumption on it
                     # would start a second delivery on every retry. These
                     # hashes are what the user approved, and they change when
                     # the costume's bytes change -- which is exactly when a
                     # resumed delivery would otherwise report `installed` for
                     # bytes nobody imported.
                     'assets_digest': 'sha256:' + hashlib.sha256(json.dumps(
                         sorted((source['character'], source['skin_id'], source['sha256'])
                                for source in install_plan.get('sources', [])),
                         sort_keys=True).encode()).hexdigest(),
                     'install_digest': 'sha256:' + hashlib.sha256(
                         json.dumps(install_plan, sort_keys=True).encode()).hexdigest()},
            'subject': {k: subject[k] for k in ('kind', 'character', 'skin_id', 'name',
                                                'key', 'label')},
            'install_args': install_args, 'install': install_plan, 'change': change}
    if designation is not None:
        # What the approval makes the user's game. `apply_deliver` designates exactly
        # this, then delivers to it; the settings revision in it means a game copy
        # designated in between invalidates the approval instead of being overruled.
        plan['designation'] = designation
        consequence = (f"{project['name']} becomes the game you play"
                       + (f" (instead of {designation['replaces']})" if designation['replaces'] else '')
                       + '. I add the costume and save the game as a new file, '
                       + f"{designation['output_filename']}, in Nucleus's games folder. "
                       + 'No file you already have is changed.')
    elif playable and outcome != 'prepare':
        consequence = ('Your game copy is rebuilt with this costume in it and saved over '
                       + (destinations.public(record) or {}).get('output_filename', 'your copy')
                       + '. The copy it replaces is kept so I can undo this.')
    elif outcome != 'prepare':
        consequence = ('This builds a new copy of the game, but nothing you launch changes until '
                       'a game copy is set as yours.')
    else:
        consequence = ('Only the project files change. The copy you play is not rebuilt until '
                       'you ask for that.')
    preview = {'project_action': 'deliver', 'title': f'Here’s the change: {change}.',
               'project_name': project['name'], 'items': install_preview['items'],
               'change': change, 'destination': destinations.public(record),
               'designation': ({key: designation[key] for key in
                                ('kind', 'label', 'output_filename', 'played_filename', 'replaces')}
                               if designation is not None else None),
               'limitations': limitations,
               # The approval card shows `description`, not `limitations`: the
               # limitation that matters has to be on the card they press.
               'description': ' '.join(limitations),
               'consequence': consequence,
               'confirm_label': (f'Add to {project["name"]}' if outcome == 'prepare'
                                 else f'Add it and make {where} my game' if designation is not None
                                 else f'Add to {where} and rebuild')}
    return plan, preview


# --------------------------------------------------------------------------
# delivering
# --------------------------------------------------------------------------

def deliver_to_game(_install=None, _export=None, **args):
    """The workflow entry point: put one costume into a game copy the user named.

    Always returns a result envelope, including for the stops that write
    nothing -- the switch being off, no destination chosen, no build to choose
    from, an unresolvable costume.
    """
    if not delivery_enabled():
        return _gated(args)
    try:
        plan, _preview = plan_delivery(args)
        args, plan = _designate_approved(args, plan)
    except ValueError as exc:
        return _undecided_envelope(args, exc)
    return deliver(args, plan, _install=_install, _export=_export)


def _designate_approved(args, plan):
    """Make the approved project the game the user plays, then aim the delivery at it.

    Only for a plan that carries a `designation` (`set_as_my_game`), which is
    what the approval card showed. The proposal is re-planned first, and any
    change -- the costume, the project, the settings revision (another game copy
    designated in between) -- refuses with nothing written. Then
    `destination.designate` records it from this explicit approval, and the
    delivery is re-planned against the new record by its id, so the seal,
    receipt and undo are the ordinary ones of a designated game copy.

    Returns `(args, plan)` to deliver; unchanged when there is no designation.
    """
    designation = plan.get('designation')
    if not designation:
        return args, plan
    fresh, _preview = plan_delivery(args)
    if fresh != plan:
        raise DeliveryError('The costume, the project or your game settings changed after you '
                            'approved this. Nothing was written; ask me again for a fresh review.')
    project = plan['project']
    try:
        record = destinations.designate(
            designation['kind'], label=designation['label'], project_id=designation['project_id'],
            output_iso_path=destinations.suggested_output(project['name']),
            play_mode=designation['play_mode'], start_from_clean=designation['start_from_clean'],
            make_default=True)
    except destinations.DestinationError as exc:
        raise DeliveryError(str(exc)) from exc
    bound = {key: value for key, value in args.items()
             if key not in ('set_as_my_game', 'start_from_clean')}
    bound.update(destination_id=record['id'], project_id=designation['project_id'])
    bound_plan, _preview = plan_delivery(bound)
    if (bound_plan['subject'] != plan['subject']
            or bound_plan['seal']['assets_digest'] != plan['seal']['assets_digest']
            or bound_plan['seal']['install_digest'] != plan['seal']['install_digest']
            or (bound_plan['destination'] or {}).get('output_filename')
            != designation['output_filename']):
        raise DeliveryError(f"{designation['label']} is now the game you play, but the costume or "
                            'the project changed while I set it, so nothing was built. Ask me again.')
    return bound, bound_plan


def deliver(args, plan, _install=None, _export=None):
    """Execute an approved delivery plan and return its envelope.

    The whole mutation happens inside the build's one session, and inside a
    critical op so closing the window cannot cut it in half. In order:

    1. Take the session. Nothing is read for a decision before the lock.
    2. Revalidate the approval UNDER the lock: the plan, the destination seal
       and the project revision must all still be what was approved.
    3. Find or open the journal for this exact (game copy, costume). An existing
       one is resumed, not repeated.
    4. Record the before-state -- costume table, the destination's ACTUAL
       current playable copy and its hash -- and write the receipt before the
       first byte changes.
    5. Run only the phases that are not done: install, export, verify_build,
       promote, activate.
    6. Report from `current_state`, which re-reads all of it.
    """
    if not delivery_enabled():
        return _gated(args)
    if plan.get('workflow') != WORKFLOW:
        raise DeliveryError('That plan is not a delivery.')
    project = plan['project']
    if not Path(project['path']).is_file():
        raise DeliveryError('That game copy is no longer on disk.')

    session, closer = _build_session(project)
    try:
        with critical_ops.critical_op('Randall delivery'):
            # The destination seal first: when the game copy was repointed, that
            # is the specific thing to say, not "something changed".
            record = destinations.get(plan['destination_id']) if plan.get('destination_id') else None
            if not destinations.reseal_matches(record, plan['seal']['destination']):
                raise DeliveryError('Where your game copy points changed after you approved '
                                    'this. Nothing was written; ask me again and I will show '
                                    'you the new target.')
            fresh, _preview = plan_delivery(args)
            if fresh != plan:
                raise DeliveryError('The costume or the game copy changed. '
                                    'Request a fresh review.')
            return _execute(args, plan, record, session,
                            _install=_install, _export=_export)
    finally:
        closer.__exit__(None, None, None)


def _new_receipt(plan, record, project):
    output_ref = (record or {}).get('output_iso_ref') or {}
    output_path = output_ref.get('path')
    before_output = None
    if output_path and Path(output_path).is_file():
        before_output = {'path': output_path, 'bytes': Path(output_path).stat().st_size,
                         'digest': playable_iso.digest_file(output_path)}
    return {'schema': RECEIPT_SCHEMA, 'receipt_id': new_id('delivery'), 'kind': 'delivery',
            'status': 'running', 'created_at': time.time(), 'updated_at': time.time(),
            'workflow': WORKFLOW, 'workflow_version': WORKFLOW_VERSION,
            'requested_outcome': plan['requested_outcome'],
            'project': project, 'destination_id': plan.get('destination_id'),
            'destination': plan.get('destination'), 'seal': plan['seal'],
            # The exact playable file this delivery is for. Undo restores THIS,
            # never whatever the destination happens to point at later.
            'output_resource': ({'path': output_path,
                                 'path_digest': plan['seal']['destination'].get(
                                     'output_path_digest')}
                                if output_path else None),
            'subject': plan['subject'], 'change': plan['change'],
            'before': {'costumes': _costume_table(project['path']),
                       'project_revision': plan['seal']['project_revision'],
                       'output': before_output, 'disturbed_fighters': []},
            'added': [], 'after': {'costumes': {}, 'artifact': None, 'output': None},
            'backup': None,
            'phases': {name: {'status': 'pending'} for name in PHASES},
            'achieved': {'prepared': False, 'exported': False,
                         'installed': False, 'previewed': False},
            'undone_at': None, 'undo_receipt_id': None}


def _adopt_project_only(plan, record, project):
    """Finish an earlier delivery of THIS costume that stopped at the project.

    With no game copy set, a delivery installs the costume, builds and checks a
    disc image, and stops ("Set a game copy and I can finish it"). Once one is
    set, finishing it means promoting that verified build into the new game copy
    -- not a second delivery, which would import the same costume into a second
    slot. The earlier receipt is bound to the destination now named (with this
    destination's before-state, for undo) and resumed from its recorded phases.
    """
    earlier = _standing_receipt(project['id'], None, plan['subject']['key'],
                                assets_digest=plan['seal']['assets_digest'])
    if earlier is None:
        return None
    bound = _new_receipt(plan, record, project)
    for key in ('destination_id', 'destination', 'seal', 'output_resource', 'change',
                'requested_outcome'):
        earlier[key] = bound[key]
    earlier['before']['output'] = bound['before']['output']
    earlier['backup'] = None
    for name in ('promote', 'activate'):
        earlier['phases'][name] = {'status': 'pending'}
    earlier['adopted_at'] = time.time()
    _write_receipt(earlier)
    return earlier


def _phase(receipt, name, status, **detail):
    receipt['phases'][name] = {'status': status, 'at': time.time(), **detail}
    _write_receipt(receipt)


def _execute(args, plan, record, session, _install=None, _export=None):
    project = plan['project']
    outcome = plan['requested_outcome']
    receipt = _standing_receipt(project['id'], plan.get('destination_id'),
                                plan['subject']['key'],
                                assets_digest=plan['seal']['assets_digest'])
    if receipt is None and plan.get('destination_id'):
        receipt = _adopt_project_only(plan, record, project)
    resumed = receipt is not None
    if receipt is None:
        receipt = _new_receipt(plan, record, project)
        _write_receipt(receipt)
    else:
        receipt['requested_outcome'] = outcome
        receipt['status'] = 'running'
        _write_receipt(receipt)

    state_now = current_state(receipt)
    checks = [_slippi_check(plan['subject']), *_not_run_checks()]

    # ---- install ---------------------------------------------------------
    if not state_now['in_project']:
        before = receipt['before']['costumes'] if resumed else _costume_table(project['path'])
        if receipt['phases']['install']['status'] == 'started':
            # The app went away with an import in flight. Reconcile against the
            # table instead of importing again: `_added_slots` against the
            # recorded before-state says exactly what landed.
            landed, _disturbed = _added_slots(project['path'], before,
                                              _costume_table(project['path']))
            if landed:
                receipt['added'] = landed
                receipt['after']['costumes'] = _costume_table(project['path'])
                _phase(receipt, 'install', 'done', slots=len(landed), reconciled=True)
                state_now = current_state(receipt)
        if not state_now['in_project']:
            # Intent, journalled before the native tool runs, so a crash in the
            # middle is reconcilable instead of a duplicate import on retry.
            _phase(receipt, 'install', 'started',
                   fighters=sorted({str(source['fighter'])
                                    for source in plan['install'].get('sources', [])}))
            install = (_install or _default_install)(plan['install_args'], plan['install'])
            after = _costume_table(project['path'])
            added, disturbed = _added_slots(project['path'], before, after)
            if not resumed:
                receipt['before']['costumes'] = before
            receipt['before']['disturbed_fighters'] = disturbed
            receipt['added'] = added
            receipt['after']['costumes'] = after
            if install.get('failed_count') or not added:
                _phase(receipt, 'install', 'failed',
                       detail=install.get('error') or 'nothing was added',
                       partial=install.get('installed_count', 0))
                receipt['status'] = 'failed'
                _write_receipt(receipt)
                return _install_failed(plan, receipt, install, checks)
            _phase(receipt, 'install', 'done', slots=len(added))
            state_now = current_state(receipt)
    elif receipt['phases']['install']['status'] != 'done':
        _phase(receipt, 'install', 'done', note='already in the project')

    if outcome == 'prepare':
        receipt['status'] = 'completed'
        receipt['achieved'] = _achieved(receipt, current_state(receipt))
        _write_receipt(receipt)
        return _prepared_only(plan, receipt, checks)

    # ---- export ----------------------------------------------------------
    # A recorded verification only counts while the bytes it was taken on are
    # still the bytes: an artifact that changed (or is gone) is re-built, not
    # trusted. This is what stops a retry publishing something nobody checked.
    recorded = receipt['after'].get('artifact') or {}
    still_verified = bool(
        recorded.get('verified_digest')
        and recorded.get('path') and Path(recorded['path']).is_file()
        and playable_iso.digest_file(recorded['path']) == recorded['verified_digest'])
    export = None
    if not still_verified or receipt['phases']['export']['status'] != 'done' or \
            receipt['phases']['verify_build']['status'] != 'done':
        export = (_export or _default_export)(project, {'filename': _iso_filename(project)},
                                              session=session)
        if export.get('state') != 'complete':
            _phase(receipt, 'export', 'failed', detail=export.get('error') or 'no disc image')
            receipt['achieved'] = _achieved(receipt, current_state(receipt))
            receipt['status'] = 'running'
            _write_receipt(receipt)
            return _export_failed(plan, receipt, checks, export)
        artifact = {'artifact_id': export.get('artifactId'), 'path': export.get('path'),
                    'digest': playable_iso.digest_file(export.get('path')),
                    'filename': export.get('filename'),
                    'bytes': Path(export['path']).stat().st_size
                    if export.get('path') and Path(export['path']).is_file() else None}
        receipt['after']['artifact'] = artifact
        _phase(receipt, 'export', 'done', artifact_id=artifact['artifact_id'])

        # ---- verify_build ------------------------------------------------
        iso_check = _iso_check(artifact['path'], project['path'], receipt['added'])
        checks.append(iso_check)
        if iso_check.status != 'pass':
            _phase(receipt, 'verify_build', 'failed', detail=iso_check.reason)
            receipt['achieved'] = _achieved(receipt, current_state(receipt))
            _write_receipt(receipt)
            return _build_unverified(plan, receipt, checks, export, iso_check)
        # The digest the verification was taken ON. Publication requires it.
        artifact['verified_digest'] = artifact['digest']
        _phase(receipt, 'verify_build', 'done', digest=artifact['digest'])
    else:
        export = {'state': 'complete', 'warnings': [],
                  'artifactId': recorded.get('artifact_id'), 'path': recorded.get('path')}
        checks.append(_check('costume_in_disc_image', 'pass',
                             measured_values={'digest': recorded.get('verified_digest')},
                             reason='Verified when this build was made, and the build still '
                                    'hashes to what was checked.'))

    # ---- promote ---------------------------------------------------------
    save_error = None
    if record is None or record.get('play_mode', 'unset') == 'unset':
        _phase(receipt, 'promote', 'not_required',
               detail='no playable copy is designated for this build')
    else:
        artifact = receipt['after']['artifact']
        output = (receipt.get('output_resource') or {}).get('path')
        live = (record.get('output_iso_ref') or {}).get('path')
        if not playable_iso.same_file(output, live):
            # The destination was repointed after this delivery was approved.
            # Writing to the new file would put this build in a game nobody
            # asked for, and writing to the old one would be a file the user no
            # longer calls theirs. Neither: stop and say so.
            save_error = ('Your game copy now points at a different file than the one this '
                          'change was approved for, so nothing was saved. Ask me again and I '
                          'will show you the new target.')
            _phase(receipt, 'promote', 'failed', detail=save_error)
            checks.append(_check('saved_copy_matches_build', 'fail', reason=save_error))
            output = None
        already = playable_iso.digest_file(output) if output else None
        if output is None:
            pass
        elif already and already == artifact['verified_digest'] \
                and playable_iso.produced_by_nucleus(output, digest=already):
            # A resumed delivery whose copy is already the build it should be.
            # Copying 1.4 GB over itself would also move the current file aside
            # as a "previous" copy, which is how an undo ended up restoring the
            # delivery it was supposed to reverse.
            receipt['after']['output'] = {'path': output, 'digest': already,
                                          'bytes': Path(output).stat().st_size}
            _phase(receipt, 'promote', 'done', digest=already, note='already saved')
            checks.append(_check('saved_copy_matches_build', 'pass',
                                 measured_values={'digest': already},
                                 reason='The file you play already hashes to this build.'))
        else:
            try:
                saved, _backup = _promote_artifact(
                    artifact['path'], output, receipt=receipt, project=project,
                    slots=receipt['added'], expect_digest=artifact['verified_digest'])
                receipt['after']['output'] = saved
                _phase(receipt, 'promote', 'done', digest=saved['digest'])
                checks.append(_check(
                    'saved_copy_matches_build', 'pass',
                    measured_values={'digest': saved['digest']},
                    reason='The file you play hashes to the build that was made.'))
            except (DeliveryError, destinations.DestinationError,
                    playable_iso.ProtectedPath, OSError) as exc:
                save_error = str(exc)
                _phase(receipt, 'promote', 'failed', detail=save_error)
                checks.append(_check('saved_copy_matches_build', 'fail', reason=save_error))

    # ---- activate --------------------------------------------------------
    activation = destinations.effective_activation(record)
    _phase(receipt, 'activate', 'done' if activation['status'] in
           ('not_required', 'verified', 'user_confirmed') else 'pending',
           activation=activation['status'], evidence=activation.get('evidence', ''))

    state_now = current_state(receipt)
    receipt['achieved'] = _achieved(receipt, state_now)
    receipt['status'] = 'completed' if state_now['complete'] else 'running'
    _write_receipt(receipt)
    if plan.get('destination_id'):
        destinations.record_delivery(plan['destination_id'], receipt['receipt_id'],
                                     receipt['after']['output'] or {}, activation)
    return _delivered(plan, receipt, checks, export, state_now, save_error, activation,
                      resumed=resumed)


# --------------------------------------------------------------------------
# undo
# --------------------------------------------------------------------------

def undo_delivery(receipt_id, _remove=None, _export=None):
    """Put the game back the way it was before one delivery, and say what came back.

    A restoration, not a second change, and resumable like the delivery it
    reverses. It:

    * refuses unless every slot it would remove still holds the exact bytes this
      delivery put there -- position and filename are not identity;
    * refuses when a later delivery to the same project is still standing, whose
      recorded slots removing this one would shift;
    * removes through MexCLI, rebuilds, and checks the costume's files are gone
      from the new image;
    * puts the PRESERVED previous playable copy back at the designated output,
      verified by hash, so the file the user launches is the one they had;
    * reports `undone` only once `current_state` says both halves are true. A
      rebuild that failed leaves the receipt `undoing`, so the offered retry
      resumes instead of answering "already undone".
    """
    if not delivery_enabled():
        # The same switch, on the same mutation. Undo rebuilds and replaces the
        # file someone boots exactly as a delivery does, so leaving it open with
        # the switch off would be the preview shipping through the back door.
        sentence = ('Changing the game you play is switched off in this build, and that '
                    'includes taking a costume back out. Nothing was changed.')
        envelope = _envelope(
            limitations=[sentence],
            facts={'what_changed': 'Nothing.', 'where': 'Nowhere.',
                   'limitation_that_matters': sentence,
                   'how_to_undo': 'Open the build screen and rebuild from there.'})
        envelope.next = _decision(
            'Open the build screen in Nucleus to change the build yourself.',
            [{'action': 'open_build_screen', 'where': 'Nucleus \u2192 Export \u2192 Build ISO'}])
        return _finish(envelope, 'blocked')
    receipt = read_receipt(receipt_id)
    if receipt is None:
        return _finish(_envelope(
            limitations=['No delivery with that receipt.'],
            facts={'what_changed': 'Nothing.', 'where': 'Nowhere.',
                   'limitation_that_matters': 'That receipt is not one of my deliveries.',
                   'how_to_undo': 'Ask me to list what I put in your game.'}), 'blocked')
    if receipt.get('status') == 'undone':
        return _finish(_envelope(
            receipts=[receipt_id],
            facts={'what_changed': 'Nothing this time; this delivery was already undone.',
                   'where': receipt['project']['name'],
                   'summary': f"{receipt['subject']['name']} was already taken back out of "
                              f"{receipt['project']['name']}.",
                   'limitation_that_matters': 'Already undone.',
                   'how_to_undo': 'Ask me to deliver it again to put it back.'}), 'success')

    project = receipt['project']
    if not Path(project['path']).is_file():
        return _finish(_envelope(
            receipts=[receipt_id], limitations=['That game copy is no longer on disk.'],
            facts={'what_changed': 'Nothing.', 'where': project['name'],
                   'limitation_that_matters': 'The build this went into is gone, so there is '
                                              'nothing to put back.',
                   'how_to_undo': 'Nothing to undo.'}), 'blocked')

    session, closer = _build_session(project)
    try:
        with critical_ops.critical_op('Randall delivery undo'):
            return _undo(receipt, project, session, _remove=_remove, _export=_export)
    finally:
        closer.__exit__(None, None, None)


def _undo(receipt, project, session, _remove=None, _export=None):
    record = destinations.get(receipt['destination_id']) if receipt.get('destination_id') else None
    placement = _placement(receipt)
    removed_files = [slot['filename'] for slot in receipt.get('added', [])]
    checks = []

    # ---- preconditions, all of them, before anything is removed ----------
    # Read under the build session: a check taken before the lock describes a
    # build somebody else may still have been writing.
    later = _later_active_deliveries(receipt)
    if later:
        names = ', '.join(row['subject'].get('name', 'another costume') for row in later[:4])
        return _blocked_undo(receipt, project,
                             f'I put {names} into {project["name"]} after this one. Taking this '
                             'one out now would move where those sit, and I will not do that '
                             'behind their back. Undo '
                             f'{later[0]["subject"].get("name", "the newest one")} first.',
                             how='Undo the newer one first.')

    members = _member_states(project['path'], receipt.get('added', []))
    if members['conflict']:
        why = '; '.join(f"{slot['fighter_name']} slot {slot['slot']}: {slot['why']}"
                        for slot in members['conflict'])
        return _blocked_undo(receipt, project,
                             'Those costume slots are not the ones I put there any more ('
                             + why + '), so removing them could take out the wrong costume.',
                             how='Not automatically, for this one. Open the build and remove '
                                 'the slot yourself.')

    # The playable copy this delivery was approved for has to still be the one
    # the destination points at, or restoring would put these bytes in a game
    # the user never asked me to touch.
    output = (receipt.get('output_resource') or {}).get('path')
    playable = record is not None and record.get('play_mode', 'unset') != 'unset'
    if playable:
        live = (record.get('output_iso_ref') or {}).get('path')
        if not playable_iso.same_file(output, live):
            return _blocked_undo(
                receipt, project,
                'Your game copy points at a different file than the one this change went '
                'into, so I will not write the old bytes over it. Point it back, or undo '
                'this in the build screen.',
                how='Point your game copy back at the file this went into first.')

    receipt['status'] = 'undoing'
    _write_receipt(receipt)

    # ---- remove ----------------------------------------------------------
    if members['found']:
        manifest = {}
        for slot in members['found']:
            manifest.setdefault(str(slot['fighter']), []).append(slot['current_index'])
        removal = (_remove or _default_remove)(project, manifest, session=session)
        checks.append(_check('costume_removed_from_project',
                             'pass' if removal.get('totalFailed', 0) == 0 else 'fail',
                             measured_values={'removed': removal.get('totalRemoved', 0),
                                              'failed': removal.get('totalFailed', 0),
                                              'expected': len(members['found'])},
                             reason='' if removal.get('totalFailed', 0) == 0
                                    else 'MexCLI could not remove every slot.'))
    # Every member this delivery added must be gone now -- not "most of them".
    remaining = _member_states(project['path'], receipt.get('added', []))
    checks.append(_check('every_delivered_costume_removed',
                         'pass' if not remaining['found'] and not remaining['conflict']
                         else 'fail',
                         measured_values={'still_there': len(remaining['found']),
                                          'of': len(receipt.get('added', []))},
                         reason='' if not remaining['found'] else
                                'Some of what this delivery added is still in the build.'))
    restored_table = _costume_table(project['path'])
    exact = restored_table == receipt['before']['costumes']
    checks.append(_check('build_restored', 'pass' if exact else 'warn',
                         reason='' if exact else
                                'The slots this delivery added are gone, but other parts of '
                                'the build changed in between, so it is not byte-identical to '
                                'the state before.'))

    # ---- rebuild ---------------------------------------------------------
    export = (_export or _default_export)(project, {'filename': _iso_filename(project)},
                                          session=session)
    rebuilt = export.get('state') == 'complete'
    absence = None
    if rebuilt:
        absence = _absence_check(export.get('path'), removed_files)
        checks.append(absence)
        if absence.status == 'unknown':
            # The rebuild produced something this app cannot read as a disc.
            # Publishing it would put unchecked bytes at the path the user
            # boots, which is the failure the whole verification step exists
            # for -- so the rebuild does not count as one.
            rebuilt = False

    # ---- put the previous playable copy back -----------------------------
    restored_output, restore_note = None, ''
    if playable:
        before_output = (receipt.get('before') or {}).get('output')
        try:
            restored_output = _restore_playable_copy(
                receipt.get('backup') or before_output, output,
                receipt=receipt, project=project)
        except (DeliveryError, destinations.DestinationError,
                playable_iso.ProtectedPath) as exc:
            restore_note = str(exc)
        if restored_output is None and rebuilt:
            # No preserved copy to put back (or it no longer matches): the
            # honest restoration is the freshly rebuilt image WITHOUT the
            # costume, promoted the same way a delivery promotes.
            try:
                restored_output, _backup = _promote_artifact(
                    export.get('path'), output, receipt=receipt, project=project, slots=[],
                    expect_digest=playable_iso.digest_file(export.get('path')))
                restore_note = ('The copy you had was not available to put back, so your game '
                                'copy is a fresh build without the costume.')
            except (DeliveryError, destinations.DestinationError,
                    playable_iso.ProtectedPath, OSError) as exc:
                restore_note = str(exc)
        checks.append(_check('playable_copy_restored',
                             'pass' if restored_output else 'fail',
                             measured_values={'digest': (restored_output or {}).get('digest')},
                             reason='' if restored_output else
                                    (restore_note or 'The copy you play was not put back.')))
        if restored_output:
            destinations.record_delivery(record['id'], receipt['receipt_id'], restored_output,
                                         destinations.effective_activation(record))

    receipt['after']['output'] = restored_output or receipt['after'].get('output')
    state_now = current_state(receipt)
    # The reading this undo concluded from, kept on the receipt: an undo that
    # stopped half way has to be diagnosable without re-running it.
    receipt['undo_state'] = {key: value for key, value in state_now.items()
                             if key not in ('activation',)}
    # A warning is a thing worth saying, not a restoration that did not happen.
    complete = bool(state_now['restored']
                    and (rebuilt or not receipt.get('added'))
                    and all(c.status != 'fail' for c in checks))
    leftovers = [c for c in checks
                 if c.check_id == 'costume_absent_from_disc_image' and c.status == 'warn']
    receipt['status'] = 'undone' if complete else 'undoing'
    if complete:
        receipt['undone_at'] = time.time()
    receipt['achieved'] = {'prepared': True, 'exported': bool(rebuilt),
                           'installed': bool(complete and state_now['playable']),
                           'previewed': False}
    _write_receipt(receipt)

    limitations = []
    if not rebuilt:
        limitations.append('The costume slot is out of the project, but the playable copy '
                           'could not be rebuilt: '
                           + (export.get('error') or 'the build produced no disc image.')
                           + ' Ask me again and I will pick up where this stopped.')
    if state_now['playable'] and not restored_output:
        limitations.append('Your game copy was NOT put back yet, so the file you launch still '
                           'has the costume in it. ' + (restore_note or ''))
    elif restore_note:
        limitations.append(restore_note)
    if leftovers:
        limitations.append(leftovers[0].reason)
    limitations.append('Your saved copy of this costume is untouched and still in your '
                       'library. Deleting it is a separate thing to ask for.')

    summary = (f'Put {project["name"]} back the way it was before I added '
               f'{receipt["subject"]["name"]}: {placement} is free again. '
               + ('Your game copy is the one you were playing before. '
                  if restored_output and complete else
                  'Your game copy was NOT put back yet. ' if state_now['playable']
                  else 'Your game copy was rebuilt without it. ' if rebuilt else
                  'Your game copy was NOT rebuilt. ')
               + 'The saved skin is still in your library.')

    envelope = _envelope(
        achieved=dict(receipt['achieved']), checks=checks, limitations=limitations,
        receipts=[receipt['receipt_id']],
        facts={'restored': f'{project["name"]}: {placement} is free again, the way it was '
                           f'before I added {receipt["subject"]["name"]}.',
               'change': f'remove {receipt["subject"]["name"]} from {project["name"]} and '
                         'keep it in your library',
               'summary': summary,
               'what_changed': (f'{receipt["subject"]["name"]} was removed from {placement} in '
                                f'{project["name"]}'
                                + (', the game copy was rebuilt without it'
                                   if rebuilt else ', and the game copy was not rebuilt')
                                + (', and the copy you were playing is back.'
                                   if restored_output else '.')),
               'where': project['name'],
               'limitation_that_matters': limitations[0],
               'how_to_undo': 'Ask me to put it back and I will deliver it again.',
               'receipt_id': receipt['receipt_id'],
               'status': receipt['status'],
               'target_build_id': project['id'],
               'library_copy': 'untouched',
               'verification': _verification_facts()})
    if not complete:
        envelope.next = _decision(
            'Ask me again and I will finish putting it back, or open the build screen.',
            [{'action': 'undo_delivery', 'receipt_id': receipt['receipt_id']},
             {'action': 'open_build_screen', 'where': 'Nucleus → Export → Build ISO'}])
    return _finish(envelope, 'success' if complete else 'partial')


# --------------------------------------------------------------------------
# tool entry points
# --------------------------------------------------------------------------

def prepare_deliver(args):
    """Approval preview for `deliver_to_game`."""
    if not delivery_enabled():
        raise DeliveryError('Putting costumes straight into your game is switched off in this '
                            'build. I can add it to a project instead.')
    return plan_delivery(args)


def apply_deliver(args, plan):
    """Approved execution for `deliver_to_game`."""
    if not delivery_enabled():
        return _gated(args)
    args, plan = _designate_approved(args, plan)
    return deliver(args, plan)


def undo_delivery_tool(receipt_id):
    """`undo_delivery` as the model calls it."""
    return undo_delivery(receipt_id)


__all__ = ['WORKFLOW', 'WORKFLOW_VERSION', 'REQUESTED_OUTCOMES', 'PHASES', 'DeliveryError',
           'public_deliveries',
           'deliver_to_game', 'undo_delivery', 'plan_delivery', 'deliver', 'current_state',
           'list_deliveries', 'read_receipt', 'recover_deliveries', 'delivery_enabled',
           'prepare_deliver', 'apply_deliver', 'undo_delivery_tool']
