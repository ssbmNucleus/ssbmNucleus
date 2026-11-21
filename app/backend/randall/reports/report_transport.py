"""The bug-report worker's two-stage transport, for Randall's own reports.

Feature requests (randall/routes/wishes.py) and "Report this chat"
(randall/routes/chat_reports.py) both send through the bug-report worker that
in-app bug reports use: stage one creates the remote report and returns its id,
stage two uploads the frozen bundle into it. The worker URL is read at call time
from the transport module the route passes in (shared/diagnostics/bug_report.py,
or a test's stand-in), so there is one report pipeline and one set of worker
limits. The policy around a send (consent, lease, retries) is not here; it is
`randall.reports.wishes.submit` and `randall.reports.chat_report.submit`.
"""
import requests

from randall.reports import wishes as wishlib


def _make_create(setup_module):
    """Stage one: create the remote report and return its id."""
    def create(meta, headers):
        try:
            created = requests.post(setup_module._BUGREPORT_URL, json=meta,
                                    headers=headers or {}, timeout=15)
        except requests.RequestException as exc:
            raise RuntimeError(f'report server unreachable: {exc}') from exc
        if created.status_code in (426, 429) or not created.ok:
            detail = {}
            try:
                detail = created.json() or {}
            except ValueError:
                pass
            raise wishlib.TransportRefused('report server refused',
                                           status=created.status_code, detail=detail)
        return (created.json() or {}).get('id')
    return create


def _make_upload(setup_module):
    """Stage two: upload the frozen bundle into an already-created report.

    Separate from `create` so `wishes.submit` can persist the report id between
    them: a lost acknowledgment then retries into the SAME remote report
    instead of filing a second one.
    """
    def upload(report_id, zip_bytes):
        try:
            response = requests.put(f'{setup_module._BUGREPORT_URL}/{report_id}/zip',
                                    data=zip_bytes,
                                    headers={'Content-Type': 'application/zip'}, timeout=60)
        except requests.RequestException as exc:
            raise RuntimeError(f'upload failed: {exc}') from exc
        if not response.ok:
            detail = {}
            try:
                detail = response.json() or {}
            except ValueError:
                pass
            raise wishlib.TransportRefused('upload failed', status=response.status_code,
                                           detail=detail)
        notified = False
        try:
            notified = bool((response.json() or {}).get('notified'))
        except ValueError:
            pass
        # `notified: false` is still an ACCEPTED report -- R2 holds it. Never
        # refile merely to obtain a Discord ping.
        return {'notified': notified}
    return upload
