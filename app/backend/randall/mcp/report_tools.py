"""``report_problem`` and ``problem_report_status``: the user's AI writes a problem report, the user sends it.

The call only assembles the report on this computer (randall/reports/problem_report.py) and answers "waiting for you
to confirm in Nucleus": nothing leaves the machine until the person at the window reads it and presses Send there
(a window-only route and the chat report's own submit). ``problem_report_status`` says whether they sent or
discarded it.
"""
from randall.reports import problem_report

from . import content

_STATUS_WAIT = 0

TOOLS = [
    {'name': 'report_problem',
     'description': (
         'Write a problem report for the Nucleus developer when something in Nucleus went wrong (an import that '
         'failed or came out broken, a tool that misbehaved). Nothing is sent by this call: Nucleus assembles the '
         'report on this computer (your markdown, its logs, versions, timings and error output, and for an import '
         'its records, preview pictures and, if the user ticks it, the source model) and shows it to the user in '
         'the Nucleus window, where they choose what goes with it and press Send or Discard. Name what it is about '
         'by id only (job_id from import_model or fix_import, import_id from a job result\'s project, chat_id of a '
         'Randall chat), never by path; Nucleus finds the files itself. Say what happened, what you expected and '
         'what you tried. Then tell the user the report waits for them in Nucleus, and call problem_report_status '
         'with the report_id to learn whether they sent it. At most '
         f'{problem_report.PENDING_MAX} reports wait at once and {problem_report.PER_HOUR} are made per hour.'),
     'inputSchema': {
         'type': 'object', 'additionalProperties': False, 'required': ['title', 'markdown'],
         'properties': {
             'title': {'type': 'string', 'maxLength': problem_report.TITLE_MAX,
                       'description': 'One line: what went wrong.'},
             'markdown': {'type': 'string', 'description': (
                 f'The report in markdown, at most {problem_report.MARKDOWN_MAX // 1024} KB: what happened, what '
                 'you expected, the steps, what you already tried. Logs and records go on their own.')},
             'job_id': {'type': 'string', 'description': 'The model import job it is about (import_model\'s job_id).'},
             'import_id': {'type': 'string', 'description': 'The model import it is about (a result\'s project).'},
             'chat_id': {'type': 'string', 'description': 'A Randall chat it is about (its transcript can go too).'},
             'model': {'type': 'string', 'maxLength': problem_report.FIELD_MAX,
                       'description': 'Your own model name, as you know it.'},
             'effort': {'type': 'string', 'maxLength': problem_report.FIELD_MAX,
                        'description': 'Your reasoning effort setting, if you have one.'}}},
     'annotations': {'title': 'Report a problem', 'readOnlyHint': False, 'destructiveHint': False,
                     'openWorldHint': False}},
    {'name': 'problem_report_status',
     'description': ('Whether the user sent a report_problem report: status waiting_for_user (still in the Nucleus '
                     'window), sent (with a short reference), discarded, or expired (nobody sent it within 3 days). '
                     f'It waits up to wait_seconds (default {_STATUS_WAIT}, at most {problem_report.WAIT_MAX}) for '
                     'the user to decide before answering.'),
     'inputSchema': {'type': 'object', 'additionalProperties': False, 'required': ['report_id'],
                     'properties': {'report_id': {'type': 'string'},
                                    'wait_seconds': {'type': 'integer', 'minimum': 0,
                                                     'maximum': problem_report.WAIT_MAX}}},
     'annotations': {'title': 'Problem report status', 'readOnlyHint': True, 'openWorldHint': False}},
]
NAMES = tuple(tool['name'] for tool in TOOLS)


def report_problem(arguments):
    record = problem_report.create(arguments)
    return content.tool_result('report_problem', problem_report.made(record))


def problem_report_status(arguments):
    extra = sorted(set(arguments) - {'report_id', 'wait_seconds'})
    if extra:
        raise problem_report.ReportRefused(f"Unknown arguments: {', '.join(extra)}. Accepted: report_id, wait_seconds.")
    report_id = arguments.get('report_id')
    if not isinstance(report_id, str) or not report_id.strip():
        raise problem_report.ReportRefused('report_id must be the id report_problem answered with.')
    wait = arguments.get('wait_seconds', _STATUS_WAIT)
    if type(wait) is not int or not 0 <= wait <= problem_report.WAIT_MAX:
        raise problem_report.ReportRefused(f'wait_seconds must be a whole number from 0 to {problem_report.WAIT_MAX}.')
    return content.tool_result('problem_report_status', problem_report.wait_for_change(report_id.strip(), wait))


def call(name, arguments):
    try:
        return {'report_problem': report_problem, 'problem_report_status': problem_report_status}[name](arguments)
    except problem_report.ReportRefused as refused:
        return content.error(str(refused))
