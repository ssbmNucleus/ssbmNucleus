"""Release gates — the one table.

A gate hides a feature that is BUILT but not publicly released. Every gate is
default-ON (dev sees everything) and is turned off by setting its environment
variable to exactly ``'0'``; ``electron/main.js`` does that for the gates marked
``packaged_off`` when it spawns the backend for a packaged build.

This module is the authority for the backend half. The other halves:

  * ``electron/main.js``  — sets the variables for packaged builds.
    ``tests/backend/test_gates.py`` fails if its list drifts from this table.
  * ``frontend/src/shared/config/features.js`` — the viewer half for the gates the
    UI can decide on its own (Combo Video, Randall). The rest are
    discovered at runtime by probing a route, so the viewer needs no flag.
  * ``docs/dev/ARCHITECTURE.md`` §7 — the human-readable version of this table.

Not a release gate, despite the name: ``NUCLEUS_VAULT_DB`` (which vault storage
backend to use) and ``NUCLEUS_VAULT_DUAL_WRITE``. Those live in ``core.config``.

The ``packaged_off`` gates are the **preview policy**: ``policy_env(preview)``
is the exact environment a packaged build hands the backend,
``docs/dev/PREVIEW-0.9.0.md`` is the table in prose, and
``tests/backend/test_preview_policy.py`` fails if ``main.js`` drifts.

A gate is also closed when its code is not in the checkout: the public source
drop (``tools/public_drop.py``) leaves the unreleased features' packages out,
and a clone of it runs as a dev checkout. See ``present()``.
"""
import os
import sys
from pathlib import Path
from typing import NamedTuple


class Gate(NamedTuple):
    env: str            # environment variable that turns it off (value '0')
    packaged_off: bool  # electron/main.js forces it off in packaged builds
    covers: str         # what disappears when it is off
    ui: str             # how the viewer finds out


GATES: dict[str, Gate] = {
    'assistant': Gate(
        env='NUCLEUS_ASSISTANT', packaged_off=False,
        covers='Randall, the Nucleus assistant: the chat and its vault tools '
               '(/api/assistant/*) and the app MCP (/api/mcp). SHIPPED in 0.9.0, '
               'so main.js no longer forces this off; the variable stays as the '
               'kill switch, and setting packaged_off back to True (plus the '
               'main.js list) leaves the code out of a build again',
        ui='ASSISTANT_ENABLED in config/features.js (VITE_ASSISTANT_PREVIEW, '
           'which the build scripts set exactly when ship_guard.gate_ships says so)'),
    'nucleome': Gate(
        env='NUCLEUS_NUCLEOME', packaged_off=False,
        covers='the whole Tracker surface — SHIPPED in 0.7.0, so main.js no '
               'longer forces this off; the variable stays as the kill switch',
        ui='NUCLEOME_ENABLED in config/features.js'),
    'combo_video': Gate(
        env='NUCLEUS_COMBO_VIDEO', packaged_off=True,
        covers='Combo Video maker (/api/nucleome/combo-video)',
        ui='COMBO_VIDEO_ENABLED in config/features.js (DEV-only fold)'),
    'randall': Gate(
        env='NUCLEUS_RANDALL', packaged_off=True,
        covers='Randall / the Analyst tab (/api/nucleome/coach/*)',
        ui='RANDALL_ENABLED in config/features.js (DEV-only fold)'),
    'vault': Gate(
        env='NUCLEUS_VAULT', packaged_off=False,
        covers='cloud vault: phone pairing, replay push, AND the launch '
               'autorun in tracker/cloud/vault_jobs.py — SHIPPED in 0.7.2 '
               '(the Patreon offer), so main.js no longer forces this off; '
               'the variable stays as the kill switch',
        ui='VaultSection hides on HTTP 404 from /api/nucleome/vault/status'),
    'build_commit': Gate(
        env='NUCLEUS_BUILD_COMMIT', packaged_off=True,
        covers='writing a prepared menu + code change INTO a managed build '
               '(nucleus_api.builds.commit_change and the approval endpoint '
               '/api/mex/builds/changes/<id>/approve). With it closed a change can '
               'still be prepared and inspected; committing it is refused outright '
               'rather than half-applied',
        ui='the approval card is not offered; commit_change returns '
           'outcome=build_commit_disabled'),
    'delivery': Gate(
        env='NUCLEUS_DELIVERY', packaged_off=True,
        covers='delivering a finished change INTO the build someone boots '
               '(randall/delivery/deliver.py). Delivery rebuilds and OVERWRITES that '
               'file, so it stays closed until the path has been exercised on '
               'real builds. Closed means refused with a sentence, never a '
               'partial success that reads like one',
        ui='the assistant offers no "deliver to my game" action; the call '
           'refuses with a typed state'),
    'wish_submit': Gate(
        env='NUCLEUS_WISH_SUBMIT', packaged_off=True,
        covers='sending a recorded feature request to the developer '
               '(POST /api/mex/wishes/<key>/submit). Wishes are still '
               'classified, recorded and counted LOCALLY when this is off — '
               'what the gate stops is anything leaving the machine, and '
               'anything CLAIMING that something left it',
        ui='probes GET /api/mex/wishes/<key>/review -> can_send'),
    'any_mod_download': Gate(
        env='NUCLEUS_ANY_MOD_DOWNLOAD', packaged_off=True,
        covers='Randall downloading ANY published mod from ssbmnucleus.net '
               '(file_type "other": menu files, whole-mod archives with no '
               'per-file export). With it closed the assistant still browses '
               'and inspects every post, and still downloads the three '
               'published EXPORT types (character_dat, stage_dat, '
               'effects_dat) it has always handled; anything else says so and '
               'points at the website download button on the mod page. Held while the '
               'archive containment, nested-budget and destination-binding '
               'work from the 2026-09-22 security review is under review',
        ui='can_download=false on the card and on each file; the refusal '
           'sentence names the website download instead'),
}


def enabled(name: str) -> bool:
    """Whether a gate is open, read from the environment at call time.

    Default ON; off only when the variable is exactly '0' (the historical
    semantics of every call site this replaced), or when the gate's code is not
    in this checkout (``present``).
    """
    return os.environ.get(GATES[name].env, '1') != '0' and present(name)


#: app/backend, where a source checkout keeps every package a gate can leave out.
_BACKEND = Path(__file__).resolve().parents[1]


def _on_disk(module: str) -> bool:
    """Whether backend module or package `module` has its source in this checkout.

    os.path, not pathlib: tests stub Path.is_file to prove a request opens no file,
    and a gate check must neither count as one nor read as "not there".
    """
    path = os.path.join(str(_BACKEND), *module.split('.'))
    return os.path.isfile(os.path.join(path, '__init__.py')) or os.path.isfile(path + '.py')


def present(name: str) -> bool:
    """Whether gate `name`'s code is in this checkout.

    The public source drop leaves the code of unreleased features out
    (core/build_smoke.py ``_GATED_PACKAGES``, excluded in tools/public_drop.py),
    and a clone of it is a dev checkout, where every gate defaults open. A gate
    whose packages are not on disk therefore reads closed, as in a stable
    build, and every call site skips it the same way. Only a missing package
    counts: an ImportError inside a package that is there still surfaces.

    A frozen build is not a checkout: the spec decided what went in, and
    electron/main.js closes the gates it left out, so it is always True there.
    """
    if getattr(sys, 'frozen', False):
        return True
    from core.build_smoke import _GATED_PACKAGES
    return all(_on_disk(package) for package in _GATED_PACKAGES.get(name, ()))


def packaged_off_env() -> list[str]:
    """The variables a packaged build sets to '0'. Mirrored by electron/main.js."""
    return [g.env for g in GATES.values() if g.packaged_off]


def delivery_enabled() -> bool:
    """Whether a finished change may be delivered into the build someone boots."""
    return enabled('delivery')


#: The gates a preview package leaves OPEN. Everything else marked
#: `packaged_off` stays '0' — a preview opens the assistant surface, not the
#: write paths behind it. Since 0.9.0 the assistant is not packaged_off, so
#: this changes nothing until it is held back again; then a preview build
#: (NUCLEUS_PREVIEW_FEATURES=assistant) opens it as before.
# The Tracker coach (NUCLEUS_RANDALL) stays off in every package, preview
# included: an assistant preview opens the assistant chat only (owner, 2026-10-04).
PREVIEW_OPEN_GATES = ('NUCLEUS_ASSISTANT',)


def policy_env(preview: bool) -> dict[str, str]:
    """Exactly what a PACKAGED build puts in the backend's environment.

    `preview` is `package.json previewFeatures?.includes('assistant')` — the
    flag build.bat writes into the packaged manifest from
    `NUCLEUS_PREVIEW_FEATURES=assistant`. The result is the whole contract:
    electron/main.js must produce this mapping and nothing else, and
    `tests/backend/test_preview_policy.py` asserts both halves agree.
    """
    return {env: ('1' if preview and env in PREVIEW_OPEN_GATES else '0')
            for env in packaged_off_env()}


def preview_policy_env() -> dict[str, str]:
    """The packaged PREVIEW policy: the write paths and the coach shut (the assistant
    is open in every package since 0.9.0)."""
    return policy_env(preview=True)


def policy_summary() -> dict[str, str]:
    """Every gate as it stands in THIS process, right now."""
    return {g.env: ('1' if enabled(name) else '0') for name, g in GATES.items()}


def policy_log_line() -> str:
    """One line for the startup log, so a bug report names the live policy.

    Only the switches a preview build moves are listed: the whole table would
    be forty characters of noise per launch and is already in ARCHITECTURE §7.
    """
    interesting = [GATES['assistant'].env, GATES['randall'].env,
                   GATES['build_commit'].env, GATES['delivery'].env,
                   GATES['wish_submit'].env]
    live = policy_summary()
    return ' '.join(f'{env}={live[env]}' for env in interesting)
