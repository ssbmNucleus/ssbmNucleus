"""Secret query-string values never reach the backend's log (core/log_redaction.py ``SecretQueryFilter``).

0.9.0 smoke test (2026-11-19): every request line werkzeug wrote to mex_api_<date>.log carried the session token
(``?preview=1&_nucleus_token=...``, which media URLs hold), and the same lines went to stdout, which Electron echoes.
"""
import io
import logging
import re

from tests.paths import BACKEND

from core.log_redaction import SecretQueryFilter, redact_log_text, redact_query_secrets

LINE = ('127.0.0.1 - - [19/Nov/2026 15:23:18] "GET /api/assistant/files/45e43432?preview=1&_nucleus_token='
        'Zk3-9_qPw HTTP/1.1" 200 -')


def test_secret_query_values_are_blanked_and_the_rest_kept():
    assert redact_query_secrets(LINE) == ('127.0.0.1 - - [19/Nov/2026 15:23:18] "GET /api/assistant/files/45e43432'
                                          '?preview=1&_nucleus_token=*** HTTP/1.1" 200 -')
    for name in ('_nucleus_token', 'access_token', 'api_key', 'apikey', 'X-Amz-Signature', 'sig', 'client_secret',
                 'password', 'auth', 'jwt', 'code', 'credentials'):
        said = redact_query_secrets(f'GET /x?page=2&{name}=VALUE123&size=10 HTTP/1.1')
        assert said == f'GET /x?page=2&{name}=***&size=10 HTTP/1.1', name
    for kept in ('GET /x?preview=1&fighter=Marth HTTP/1.1', 'GET /x?skin_id=abc&offset=4', 'token=abc in prose'):
        assert redact_query_secrets(kept) == kept
    assert 'Zk3-9_qPw' not in redact_log_text(LINE), 'what leaves the machine is blanked the same way'


def test_the_filter_blanks_a_request_line_a_child_logger_writes_through_the_handler():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter('%(name)s - %(levelname)s - %(message)s'))
    handler.addFilter(SecretQueryFilter())
    parent, child = logging.getLogger('redaction-test'), logging.getLogger('redaction-test.werkzeug')
    parent.addHandler(handler)
    parent.setLevel(logging.INFO)
    try:
        # werkzeug's shape: the request line is one of the record's args
        child.info('%s - - [%s] "%s" %s -', '127.0.0.1', '19/Nov/2026 15:23:18',
                   'GET /api/assistant/files/45e43432?preview=1&_nucleus_token=Zk3-9_qPw HTTP/1.1', 200)
        child.info('no %s here', 'secret')
    finally:
        parent.removeHandler(handler)
    written = stream.getvalue()
    assert 'Zk3-9_qPw' not in written
    assert 'redaction-test.werkzeug - INFO - 127.0.0.1 - - [19/Nov/2026 15:23:18] "GET /api/assistant/files/45e43432' \
           '?preview=1&_nucleus_token=*** HTTP/1.1" 200 -' in written
    assert 'no secret here' in written


def test_app_puts_the_filter_on_both_of_its_log_handlers():
    source = (BACKEND / 'app.py').read_text(encoding='utf-8')
    assert re.search(r'for _handler in LOG_HANDLERS:\s+_handler\.addFilter\(SecretQueryFilter\(\)\)', source)
    assert re.search(r'basicConfig\(.*?handlers=LOG_HANDLERS\s*\)', source, re.S)
