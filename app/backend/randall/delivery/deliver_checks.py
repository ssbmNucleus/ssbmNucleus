"""The evidence a delivery reports: the stored online-play label as exactly what it is, the checks a
rebuild does not run, and the disc-image byte checks after a delivery and after an undo."""

from pathlib import Path

from randall.assistant.tasks.contracts import CheckResult

from .deliver_policy import CHECKS_VERSION, MIN_PLAYABLE_ISO_BYTES
from .deliver_project import _file_digest


def _check(check_id, status, **fields):
    return CheckResult(check_id=check_id, status=status,
                       implementation_version=CHECKS_VERSION, **fields)


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------

def _label_provenance(label):
    """What the stored online-play label actually is, in one sentence and a status.

    Four distinct things live in this metadata and the first version reported
    all of them as "the check run when it was added":

    * a validator verdict from the import (`slippi_tested`), with the bytes it
      ran on (`dat_hash`);
    * a value somebody set by hand (`slippi_manual_override`), which is a claim,
      not a measurement;
    * a retest with its own date (`slippi_test_date`);
    * nothing at all.
    """
    safe = label.get('slippi_safe')
    tested = label.get('slippi_tested')
    manual = label.get('slippi_manual_override')
    when = label.get('slippi_test_date')
    if manual:
        source = 'set by hand in your library, not measured'
    elif tested is True:
        source = ('checked by the importer when this costume was added to your library'
                  + (f' ({when})' if when else ''))
    elif safe is None:
        source = 'not recorded'
    else:
        source = 'recorded without saying what checked it'
    verdict = ('safe' if safe is True else 'not safe' if safe is False else 'unknown')
    # Only an explicit passing verdict from an actual check reads as a pass.
    status = 'pass' if (safe is True and tested is True and not manual) else \
             'warn' if safe is False else 'unknown'
    return {'verdict': verdict, 'source': source, 'status': status,
            'tested_bytes': label.get('dat_hash') or '', 'tested_at': when or ''}


def _slippi_check(subject):
    """The stored label, reported as exactly what it is. Never a fresh test."""
    provenance = _label_provenance(subject.get('label') or {})
    return _check('slippi_online_label', provenance['status'], required=False,
                  measured_values={'label': provenance['verdict'],
                                   'provenance': provenance['source'],
                                   'tested_bytes': provenance['tested_bytes'],
                                   'tested_at': provenance['tested_at']},
                  reason=f"Online play: {provenance['verdict']} — {provenance['source']}. "
                         'Nothing was tested just now.')


def _label_limitation(subject, play_mode=None):
    """The online-play sentence, said BEFORE the change as well as after."""
    provenance = _label_provenance(subject.get('label') or {})
    online = play_mode == 'slippi_netplay'
    if provenance['status'] == 'pass':
        return []
    if provenance['verdict'] == 'not safe':
        return [('This costume is labelled NOT safe for online play (' + provenance['source']
                 + '). Nothing was tested just now.'
                 + (' Putting it in a copy you play on Slippi is likely to cause problems '
                    'online.' if online else ''))]
    return [("It's not known whether this costume is safe for online play (" + provenance['source']
             + ').'
             + (' If you play this copy on Slippi, that is a risk.' if online else ''))]


def _not_run_checks():
    """The checks a rebuild does NOT perform, named so a reply cannot imply them."""
    return [
        _check('automated_movement_checks', 'unknown', required=False,
               reason='Not run. Rebuilding the game does not play the character; '
                      'ask me to test it in game.'),
        _check('interactive_play', 'unknown', required=False,
               reason='Only you can judge this, by playing it.'),
        _check('full_build_checks', 'unknown', required=False,
               reason='Not run. Only this costume was checked; the rest of the game was not '
                      're-checked.'),
        _check('costume_slot_mapping', 'unknown', required=False,
               reason='Not checked. The files being in the game does not show which colour '
                      'slot it uses; that needs the game running.'),
    ]


def _iso_check(iso_path, project_path, slots, check_id='costume_in_disc_image'):
    """Open the produced disc image and compare the costume's BYTES with the project.

    Names are not evidence. What is checked is that the disc's file table has a
    valid extent under that name and that the payload at that extent hashes to
    the same bytes as the costume file in the project the build came from.
    """
    from core import iso_reads
    if not iso_path or not Path(iso_path).is_file():
        return _check(check_id, 'fail',
                      reason='The export reported success but no disc image is there.')
    path = Path(iso_path)
    size = path.stat().st_size
    if size < MIN_PLAYABLE_ISO_BYTES:
        return _check(check_id, 'fail', measured_values={'bytes': size},
                      thresholds={'bytes': MIN_PLAYABLE_ISO_BYTES}, units={'bytes': 'B'},
                      reason='The disc image is too small to be a game.')
    wanted = [slot for slot in slots if slot.get('filename')]
    if not wanted:
        return _check(check_id, 'unknown',
                      reason='The build did not record a file name for the new costume, so '
                             'Nucleus cannot confirm it is inside the disc image.')
    try:
        entries = iso_reads.fst_entries(path)
    except (OSError, ValueError) as exc:
        return _check(check_id, 'unknown',
                      reason=f'The disc image could not be read back: {exc}')
    missing, wrong_bytes, unverifiable = [], [], []
    for slot in wanted:
        name = slot['filename']
        if name not in entries:
            missing.append(name)
            continue
        expected = slot.get('sha256') or _file_digest(project_path, name)
        if not expected:
            unverifiable.append(name)
            continue
        try:
            actual = iso_reads.file_digest(path, name, entries=entries)
        except (OSError, ValueError) as exc:
            return _check(check_id, 'unknown',
                          reason=f'The disc image could not be read back: {exc}')
        if ('sha256:' + str(actual)) != expected:
            wrong_bytes.append(name)
    status = 'fail' if (missing or wrong_bytes) else 'unknown' if unverifiable else 'pass'
    reason = ''
    if missing:
        reason = 'The rebuilt disc image does not contain the new costume files.'
    elif wrong_bytes:
        reason = 'The disc image has files with those names, but not the bytes of this costume.'
    elif unverifiable:
        reason = 'Nucleus could not hash the costume in the project to compare it.'
    return _check(check_id, status,
                  measured_values={'expected': [slot['filename'] for slot in wanted],
                                   'missing': missing, 'wrong_bytes': wrong_bytes,
                                   'bytes': size},
                  reason=reason)


def _absence_check(iso_path, filenames):
    """After an undo: is the removed costume's file still on the disc?

    A `warn`, not a failure, when it is. What makes a costume SELECTABLE is the
    fighter's costume table, and that is checked separately (`build_restored`
    and `current_state`). MexCLI's removal takes the entry out of that table and
    may leave the file itself in the project, in which case the exporter writes
    an unused file to the disc. That is worth saying out loud, and it is not a
    restoration that did not happen -- calling it a failure would leave an undo
    that actually worked reporting that it had not.
    """
    from core import iso_reads
    wanted = sorted({name for name in filenames if name})
    path = Path(iso_path) if iso_path else None
    if not wanted or path is None or not path.is_file():
        return _check('costume_absent_from_disc_image', 'unknown', required=False,
                      reason='Nucleus could not check the rebuilt disc image for the file.')
    try:
        present = set(iso_reads.fst_entries(path))
    except (OSError, ValueError) as exc:
        return _check('costume_absent_from_disc_image', 'unknown', required=False,
                      reason=f'The disc image could not be read back: {exc}')
    still = [name for name in wanted if name in present]
    return _check('costume_absent_from_disc_image', 'warn' if still else 'pass',
                  required=False,
                  measured_values={'removed': wanted, 'still_present': still},
                  reason='' if not still else
                         "The costume is no longer one of the character's colours, but its "
                         'file is still on the disc as an unused leftover.')
