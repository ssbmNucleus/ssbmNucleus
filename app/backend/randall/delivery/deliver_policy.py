"""What a delivery is: the workflow id and versions, the outcomes a request may ask for, the
phases, the size and backup limits, the preview switch, and the two refusals."""


WORKFLOW = 'deliver_to_game'
WORKFLOW_VERSION = 2
CHECKS_VERSION = 'deliver@2'
RECEIPT_SCHEMA = 'nucleus-delivery-receipt-v2'

#: What the caller asked for. `prepare` stops at the project inputs on purpose
#: (and says so); `install` rebuilds and saves the playable copy; `play`
#: additionally hands back the control that starts it, which Randall does not
#: press himself.
REQUESTED_OUTCOMES = ('prepare', 'install', 'play')

#: The ordered phases of a delivery. A retry runs the ones that are not done.
PHASES = ('install', 'export', 'verify_build', 'promote', 'activate')

#: A Melee disc image is ~1.3 GB. Anything far below this is not a game, whatever
#: the exporter reported. Module-level so a test can shrink it for a synthetic
#: image without weakening the check itself.
MIN_PLAYABLE_ISO_BYTES = 400 * 1024 * 1024

#: How many superseded playable copies to keep per destination. One is enough to
#: undo the last delivery; more is just the user's disk.
KEPT_BACKUPS = 1


def delivery_enabled():
    """The preview switch, read from `core.gates` and nowhere else.

    Delivery rebuilds and OVERWRITES the file someone boots, so it stays closed
    until the path has been exercised on real builds. The gate row (`delivery`
    / ``NUCLEUS_DELIVERY``) is the single definition of that, including what a
    packaged build sets; reading the variable here as well would be a second
    copy of the policy that could disagree with it.
    """
    from core import gates
    return gates.delivery_enabled()


class DeliveryError(ValueError):
    """The request cannot be turned into a delivery. Nothing was written."""


class OnlineRiskUndecided(DeliveryError):
    """An online game copy, and a costume nobody has established is safe for it.

    Not a warning added after the fact: the destination model asks for an
    explicit choice, because "labelled unsafe" and "never checked" both mean the
    user is about to take a risk in ranked play that they may not have meant to.
    """
