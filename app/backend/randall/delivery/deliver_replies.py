"""What a delivery says: the task envelope it fills and every terminal or paused reply, from the
preview switch being off to a verified delivery, kept to the same words about evidence."""

import copy

from randall.assistant.tasks import coordinator
from randall.assistant.tasks.contracts import NextRequest, TaskResult
from . import destination as destinations

from .deliver_checks import _label_limitation
from .deliver_policy import WORKFLOW, WORKFLOW_VERSION, OnlineRiskUndecided
from .deliver_project import _resolve_build


# --------------------------------------------------------------------------
# envelope helpers
# --------------------------------------------------------------------------

def _envelope(**fields):
    """Fill the CURRENT task's envelope, or a standalone one when none is tracking.

    There is one result envelope per task (`assistant/tasks/contracts.py`), and
    a workflow that minted a second one would publish a result the coordinator
    never saw.
    """
    envelope = coordinator.current().envelope if coordinator.tracking() else TaskResult()
    envelope.workflow = WORKFLOW
    envelope.workflow_version = WORKFLOW_VERSION
    for key, value in fields.items():
        setattr(envelope, key, value)
    return envelope


def _decision(prompt, responses, evidence=()):
    return NextRequest(kind='decision', task_revision=1, prompt=prompt,
                       allowed_responses=list(responses), evidence_ids=list(evidence))


def _current_revision(envelope):
    """A `next` request belongs to the revision it is raised under, not to revision 1."""
    if envelope.next is not None:
        envelope.next.task_revision = envelope.revision


def _finish(envelope, outcome):
    """This call's terminal outcome, in its reply. The chat's task stays open.

    `outcome` is the Session-1 enumeration and nothing else: success, partial,
    blocked, denied, failed, cancelled. "installed" is a postcondition in
    `achieved`, never an outcome word.

    The task a tool runs under is the run's whole objective (`engine._work_turn`).
    `engine._close_objective` closes it when the run is over, graded from every
    receipt's outcome (`turn_facts._turn_outcome`). Finishing it here, mid-turn,
    is what made the next model round refuse with "That task already finished as
    partial; it cannot spend more": the delivery's card became the user's last
    line, with no reply, although the result itself named the next step. So the
    delivery's facts go on the task's envelope (saved, not closed) and its
    outcome goes in the reply.
    """
    _current_revision(envelope)
    task = coordinator.current()
    if coordinator.tracking() and task.envelope is envelope and not task.finished:
        task.save()
    reply = copy.deepcopy(envelope)
    reply.state = 'completed' if outcome != 'failed' else 'failed'
    reply.outcome = outcome
    if reply.state == 'failed' and reply.error is None:
        reply.error = {'kind': 'unspecified', 'detail': 'The delivery failed without a recorded reason.'}
    reply.validate()
    return reply.to_dict()


def _pause(envelope):
    """A no-writes stop that is waiting on the user. Persisted, not finished."""
    _current_revision(envelope)
    envelope.validate()
    task = coordinator.current()
    if coordinator.tracking() and task.envelope is envelope:
        task.save()
    return envelope.to_dict()


def _gated(args):
    """The preview switch is off: say so plainly and change nothing."""
    sentence = ('Putting costumes straight into your game is switched off in this build. '
                'I can still add it to a project for you, and you can build the playable '
                'copy from the build screen.')
    envelope = _envelope(
        limitations=[sentence],
        facts={'requested_outcome': args.get('outcome') or 'install',
               'what_changed': 'Nothing. Your game and your project are untouched.',
               'where': 'Nowhere.', 'limitation_that_matters': sentence,
               'how_to_undo': 'There is nothing to undo.'})
    envelope.next = _decision(
        'Add it to a project instead, or open the build screen and build there.',
        [{'action': 'install_project_mods'},
         {'action': 'open_build_screen', 'where': 'Nucleus → Export → Build ISO'}])
    return _finish(envelope, 'blocked')


def _undecided_envelope(args, error):
    """The no-writes results: choose a game copy, create one, or a bad request."""
    outcome = args.get('outcome') or 'install'
    if isinstance(error, OnlineRiskUndecided):
        envelope = _envelope(
            limitations=[str(error)],
            facts={'requested_outcome': outcome,
                   'what_changed': 'Nothing yet. I stopped to ask.',
                   'where': 'Nowhere yet.',
                   'limitation_that_matters': str(error),
                   'how_to_undo': 'There is nothing to undo.'})
        envelope.state = 'waiting_decision'
        envelope.next = _decision(
            str(error),
            [{'action': 'deliver_to_game', 'online_risk_accepted': True,
              'label': 'Put it in my online copy anyway'},
             {'action': 'designate_destination', 'play_mode': 'offline',
              'label': 'Put it in an offline copy instead'}])
        return _pause(envelope)
    undecided = None
    try:
        record, _reason = destinations.resolve(destination_id=args.get('destination_id'),
                                               project_id=args.get('project_id'))
        if record is None:
            _project, undecided = _resolve_build(args.get('project_id'))
    except Exception:  # noqa: BLE001 - the original error is the one to report
        undecided = None
    envelope = _envelope(facts={'requested_outcome': outcome,
                                'what_changed': 'Nothing. No change was made.',
                                'where': 'Nowhere yet.',
                                'limitation_that_matters': str(error),
                                'how_to_undo': 'There is nothing to undo.'})
    if undecided is not None:
        envelope.facts['builds'] = [{'id': build['id'], 'name': build['name']}
                                    for build in undecided['builds']]
        envelope.next = _decision(undecided['prompt'], undecided['responses'])
        if undecided['kind'] == 'choose_build':
            envelope.state = 'waiting_decision'
            return _pause(envelope)
        envelope.limitations = [undecided['prompt']]
        return _finish(envelope, 'blocked')
    envelope.limitations = [str(error)]
    envelope.next = _decision(str(error), [{'action': 'name_the_costume'},
                                           {'action': 'designate_destination'}])
    return _finish(envelope, 'blocked')


# --------------------------------------------------------------------------
# replies
# --------------------------------------------------------------------------

def _placement(receipt):
    return ', '.join(f"{slot['fighter_name']} slot {slot['slot']}"
                     for slot in receipt.get('added', []))


def _verification_facts(interactive='Not part of this change.'):
    """Keep the three kinds of evidence apart, always, in these exact words."""
    return {'interactive_play': interactive,
            'automated_costume_checks': 'Not run. Rebuilding the game does not play the '
                                        'character; a test in game is its own request.',
            'full_build_checks': 'Not run. Only this costume was checked into the disc image; '
                                 'the rest of the build was not re-verified.'}


def _where_label(plan, receipt):
    """Where the change landed, for a model-facing fact: names, never paths."""
    record = plan.get('destination') or {}
    if record.get('output_filename'):
        return f"{record.get('spoken') or plan['project']['name']} ({record['output_filename']})"
    return f"the {plan['project']['name']} project"


def _install_failed(plan, receipt, install, checks):
    detail = install.get('error') or 'The costume was not added to the build.'
    partial = install.get('installed_count') or 0
    if partial:
        detail += (f' {partial} of the files went in, so the project is part-changed; '
                   'the receipt records exactly what.')
    envelope = _envelope(
        checks=checks, limitations=[detail],
        receipts=[receipt['receipt_id']],
        facts={'requested_outcome': plan['requested_outcome'], 'change': plan['change'],
               'summary': f"I could not add {plan['subject']['name']} to "
                          f"{plan['project']['name']}.",
               'what_changed': ('Nothing usable. ' + detail) if not partial else
                               ('Part of the costume went in. ' + detail),
               'where': _where_label(plan, receipt),
               'limitation_that_matters': detail,
               'how_to_undo': (f"Ask me to undo receipt {receipt['receipt_id']}: it records "
                               'what actually went in.') if partial else
                              'Nothing to undo: no costume slot was added.',
               'receipt_id': receipt['receipt_id'],
               'target_build_id': plan['project']['id'],
               'verification': _verification_facts()},
        error={'code': 'install_failed', 'message': detail})
    envelope.next = _decision('Inspect the build and try again, or pick another costume.',
                              [{'action': 'inspect_project',
                                'project_id': plan['project']['id']}])
    return _finish(envelope, 'blocked')


def _prepared_only(plan, receipt, checks):
    limitation = ('The copy you play has not been rebuilt, so this costume is not in your '
                  'game yet.')
    envelope = _envelope(
        achieved=dict(receipt['achieved']), checks=checks,
        limitations=[limitation, *_label_limitation(plan['subject'],
                                                    (plan.get('destination') or {}).get('play_mode'))],
        receipts=[receipt['receipt_id']],
        facts={'requested_outcome': 'prepare', 'change': plan['change'],
               'summary': f"Added to the {plan['project']['name']} project files. "
                          'Your game copy has not been rebuilt.',
               'what_changed': f"{plan['subject']['name']} was added at "
                               + _placement(receipt) + '.',
               'where': f"the {plan['project']['name']} project files",
               'limitation_that_matters': limitation,
               'how_to_undo': f"Ask me to undo this (receipt {receipt['receipt_id']}) and I "
                              'will take the slot back out.',
               'receipt_id': receipt['receipt_id'],
               'target_build_id': plan['project']['id'],
               'placement': receipt['added'],
               'verification': _verification_facts()})
    envelope.next = _decision(
        'Rebuild the playable copy now, or open the build screen in Nucleus and press Build.',
        [{'action': 'deliver_to_game', 'outcome': 'install',
          'project_id': plan['project']['id']},
         {'action': 'open_build_screen', 'where': 'Nucleus → Export → Build ISO'}])
    return _finish(envelope, 'success')


def _export_failed(plan, receipt, checks, export):
    detail = export.get('error') or 'The build did not produce a disc image.'
    limitation = ('The costume is in the project, but the playable copy could not be built, '
                  f'so it is not in your game: {detail}')
    envelope = _envelope(
        achieved=dict(receipt['achieved']), checks=checks,
        limitations=[limitation, *_label_limitation(plan['subject'],
                                                    (plan.get('destination') or {}).get('play_mode'))],
        receipts=[receipt['receipt_id']],
        facts={'requested_outcome': plan['requested_outcome'], 'change': plan['change'],
               'summary': f"{plan['subject']['name']} is in the {plan['project']['name']} "
                          'project, but your game copy was not rebuilt.',
               'what_changed': f"{plan['subject']['name']} was added at "
                               + _placement(receipt) + '.',
               'where': f"the {plan['project']['name']} project files",
               'limitation_that_matters': limitation,
               'how_to_undo': f"Ask me to undo this (receipt {receipt['receipt_id']}).",
               'receipt_id': receipt['receipt_id'],
               'target_build_id': plan['project']['id'],
               'placement': receipt['added'],
               'resume': 'Ask again and I will pick up at the build; the costume is not '
                         'installed twice.',
               'verification': _verification_facts()},
        error={'code': 'export_failed', 'message': detail})
    envelope.next = _decision(
        'Try the rebuild again, or open the build screen in Nucleus (Export → Build ISO).',
        [{'action': 'deliver_to_game', 'outcome': 'install',
          'project_id': plan['project']['id']},
         {'action': 'open_build_screen', 'where': 'Nucleus → Export → Build ISO'}])
    return _finish(envelope, 'partial')


def _build_unverified(plan, receipt, checks, export, iso_check):
    limitation = (iso_check.reason or 'Nucleus could not confirm the costume is inside the '
                                      'rebuilt disc image.') + \
                 ' Nothing was written to the copy you play.'
    envelope = _envelope(
        achieved=dict(receipt['achieved']), checks=checks,
        limitations=[limitation, *_label_limitation(plan['subject'],
                                                    (plan.get('destination') or {}).get('play_mode'))],
        receipts=[receipt['receipt_id']],
        facts={'requested_outcome': plan['requested_outcome'], 'change': plan['change'],
               'summary': f"A disc image was built, but I could not confirm "
                          f"{plan['subject']['name']} is in it, so I did not put it in "
                          'your game.',
               'what_changed': f"{plan['subject']['name']} is in the "
                               f"{plan['project']['name']} project. Your game copy is "
                               'unchanged.',
               'where': f"the {plan['project']['name']} project files",
               'limitation_that_matters': limitation,
               'how_to_undo': f"Ask me to undo this (receipt {receipt['receipt_id']}).",
               'receipt_id': receipt['receipt_id'],
               'target_build_id': plan['project']['id'],
               'placement': receipt['added'],
               'verification': _verification_facts()},
        error={'code': 'build_unverified', 'message': iso_check.reason})
    envelope.next = _decision(
        'Try again, or open the build screen and look at the build yourself.',
        [{'action': 'deliver_to_game', 'outcome': 'install',
          'project_id': plan['project']['id']},
         {'action': 'open_build_screen', 'where': 'Nucleus → Export → Build ISO'}])
    return _finish(envelope, 'partial')


def _delivered(plan, receipt, checks, export, state_now, save_error, activation, resumed=False):
    """The reply for a delivery that produced a verified disc image.

    Four separate facts decide what it may say, and `current_state` established
    all four: the costume is in the project, its bytes are in the built image,
    the image was written to the file the user plays, and the player is pointed
    at it. Only all four make `installed` true.
    """
    achieved = receipt['achieved']
    installed = achieved['installed']
    record = plan.get('destination') or {}
    where = record.get('spoken') or f"the {plan['project']['name']} project"
    output_name = record.get('output_filename')
    requested = plan['requested_outcome']
    limitations = []

    if save_error:
        limitations.append('The new copy was built, but I could not save it over your game '
                           f'file, so you are still playing the old one: {save_error}')
    elif not state_now['playable']:
        limitations.append('No game copy is set as yours yet. Tell me whether you play on Slippi '
                           f"or offline and I'll make {plan['project']['name']} your game.")
    elif activation['status'] == 'pending':
        limitations.append('Saved, but not active yet: Slippi Launcher still opens another file. '
                           'Choose this one in Launcher once and it is your game from then on. '
                           + (activation.get('evidence') or ''))
    elif activation['status'] == 'unknown':
        limitations.append('Saved, but I cannot tell what your player will open: '
                           + (activation.get('evidence') or '')
                           + ' Tell me you selected it and I will record that as your word.')
    limitations.extend(_label_limitation(plan['subject'], record.get('play_mode')))
    limitations.append('I checked that the costume is in the rebuilt game, byte for byte. '
                       'How it plays has not been checked.')
    if requested == 'play':
        limitations.append("I haven't started the game. I can open a test match, or you can "
                           'launch it yourself.')

    if installed:
        summary = f'Saved to {where}. Your updated game copy is ready.'
    elif not state_now['playable']:
        summary = (f"{plan['subject']['name']} is in {plan['project']['name']} now, but no game "
                   'copy of yours changed yet.')
    elif save_error:
        summary = f'The copy was built, but I could not write it to {where}.'
    elif activation['status'] == 'pending':
        summary = (f'Saved to {where}, but not active yet: select '
                   f'{output_name} in Slippi Launcher once, then it is your game.')
    else:
        summary = (f'Saved to {where}. I could not confirm which file your player will open.')

    envelope = _envelope(
        achieved=dict(achieved), checks=checks, limitations=limitations,
        receipts=[receipt['receipt_id']],
        artifacts=[{'id': (receipt['after']['artifact'] or {}).get('artifact_id'),
                    'kind': 'playable_iso', 'name': output_name
                    or (receipt['after']['artifact'] or {}).get('filename'),
                    'role': 'output'}],
        facts={'requested_outcome': requested, 'change': plan['change'],
               'summary': summary,
               'what_changed': (f"{plan['subject']['name']} was added at "
                                + _placement(receipt)
                                + (', and the copy you play was rebuilt with it.' if installed
                                   else ', and a new copy of the game was built with it.')),
               'where': _where_label(plan, receipt),
               'limitation_that_matters': limitations[0],
               'how_to_undo': f"Ask me to undo this (receipt {receipt['receipt_id']}): I take "
                              'the costume slot back out, rebuild, and put the copy you were '
                              'playing back.',
               'receipt_id': receipt['receipt_id'],
               'target_build_id': plan['project']['id'],
               'destination': record or None,
               'activation': activation,
               'resumed': bool(resumed),
               'selected_source': plan['subject']['key'],
               'placement': receipt['added'],
               'export_warnings': (export or {}).get('warnings') or [],
               'verification': _verification_facts()})

    if state_now['playable'] and activation['status'] in ('pending', 'unknown'):
        player = ('Slippi Launcher' if record.get('play_mode') == 'slippi_netplay'
                  else 'your player')
        envelope.next = _decision(
            f'Select {output_name} in {player} once. Then I can confirm it, '
            'or you can tell me you selected it.',
            [{'action': 'check_slippi_selection',
              'destination_id': plan.get('destination_id')},
             {'action': 'i_selected_this_file',
              'destination_id': plan.get('destination_id')}])
    elif not state_now['playable']:
        # Each answer is a call that exists: finishing promotes THIS verified build
        # into the new game copy (deliver._adopt_project_only), it does not import
        # the costume a second time. Playing it now needs no game copy at all.
        project_id = plan['project']['id']
        envelope.next = _decision(
            f"Make {plan['project']['name']} your game, or just play it now in a test match.",
            [{'action': 'deliver_to_game', 'set_as_my_game': 'slippi', 'project_id': project_id,
              'label': 'Make it my Slippi game'},
             {'action': 'deliver_to_game', 'set_as_my_game': 'offline', 'project_id': project_id,
              'label': 'Make it my offline game'},
             {'action': 'test_in_game', 'kind': 'costume',
              'character': plan['subject']['character'], 'skin_id': plan['subject']['skin_id'],
              'label': 'Just let me play it now'}])
    elif installed and not record.get('player_bound'):
        # "Open game" needs a player the user bound. Without one the honest
        # offer is to choose one, not a button that guesses.
        envelope.next = _decision(
            'Game file saved; choose an emulator to open it, or open it yourself.',
            [{'action': 'choose_emulator',
              'destination_id': plan.get('destination_id')},
             {'action': 'test_in_game'}])
    elif requested == 'play':
        envelope.next = _decision(
            'Start it with Test in game, or open it in your player.',
            [{'action': 'test_in_game'}, {'action': 'open_game'}])

    # `play` asked for a game that is running. A rebuilt copy plus the control
    # that starts it is not that, so it stays `partial` however well it went.
    return _finish(envelope, 'success' if installed and requested != 'play' else 'partial')


def _blocked_undo(receipt, project, sentence, how='Open the build and put it right yourself.'):
    return _finish(_envelope(
        receipts=[receipt['receipt_id']], limitations=[sentence],
        facts={'what_changed': 'Nothing. I did not touch the build.',
               'where': project['name'], 'limitation_that_matters': sentence,
               'how_to_undo': how}), 'blocked')
