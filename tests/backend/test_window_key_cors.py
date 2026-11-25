"""The window's page is another origin than the backend (file:// when packaged, Vite's port in development), so
every request it sends with a custom header is preflighted. The window-only routes (core/ui_channel.py) need
``X-Nucleus-UI-Key``; app.py's CORS list left it out, so the browser refused those requests before they were sent
(the build-change approval card, Play's writes, the MCP's questions, the Melee Unlocked export)."""
import json
import os
import subprocess
import sys

from tests.paths import BACKEND

BOOT = r'''
import json
import app
web = app.app.test_client()
out = {}
for origin in ('null', 'http://localhost:5173'):
    r = web.open('/api/mex/melee-unlocked/export', method='OPTIONS', headers={
        'Origin': origin, 'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'content-type,x-nucleus-token,x-nucleus-project,x-nucleus-ui-key'})
    out[origin] = [r.status_code, r.headers.get('Access-Control-Allow-Origin'),
                   r.headers.get('Access-Control-Allow-Headers')]
r = web.open('/api/mex/melee-unlocked/export', method='OPTIONS', headers={
    'Origin': 'https://example.invalid', 'Access-Control-Request-Method': 'POST',
    'Access-Control-Request-Headers': 'x-nucleus-ui-key'})
out['foreign'] = [r.status_code, r.headers.get('Access-Control-Allow-Origin'), r.headers.get('Access-Control-Allow-Headers')]
print('CORS ' + json.dumps(out))
'''


def test_the_window_may_send_its_key_and_another_origin_still_may_not(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith('NUCLEUS_') and k != 'PYTHONPATH'}
    env.update({'PYTHONPATH': str(BACKEND), 'NUCLEUS_DATA_ROOT': str(data), 'NUCLEUS_ALLOW_DEV_DATA_ROOT': '1',
                'NUCLEUS_WORKER': '1'})
    result = subprocess.run([sys.executable, '-c', BOOT], cwd=BACKEND, env=env, capture_output=True, text=True,
                            timeout=180)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
    out = json.loads(next(line for line in result.stdout.splitlines() if line.startswith('CORS '))[5:])
    for origin in ('null', 'http://localhost:5173'):
        status, allowed_origin, allowed = out[origin]
        assert status == 200 and allowed_origin == origin, out
        assert 'x-nucleus-ui-key' in (allowed or '').lower(), out
        assert 'x-nucleus-token' in (allowed or '').lower(), out
    assert out['foreign'][1] is None, out
