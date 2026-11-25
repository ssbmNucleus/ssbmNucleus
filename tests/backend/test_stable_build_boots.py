"""A packaged build boots without the unreleased features it leaves out.

Since 0.8.16 an installer does not carry the code of a closed gate at all
(tools/build/mex_backend.spec, RELEASE GATES). Since 0.9.0 a stable build
carries the assistant (Randall's chat, its tools and the app MCP) and still
leaves out Combo Video and the Tracker coach (randall.coach). Since 0.10.0
Windows stable builds also carry Play. A build can still hold the assistant back
(core/gates.py packaged_off),
and then carries none of randall, nucleus_api, shared.aiengine or
shared.modellab. core/build_smoke.py names the packages per gate; this test
imports app.py with exactly those packages made unimportable and the packaged
policy in the environment (core.gates.policy_env, what electron/main.js hands
the backend), then checks which routes came up. A shipped module that still
imports a left-out package fails here instead of in an installed app that will
not start.
"""
import json
import os
import subprocess
import sys

import pytest

from tests.paths import BACKEND

sys.path.insert(0, str(BACKEND))
from core import gates  # noqa: E402
from core.build_smoke import _GATED_PACKAGES  # noqa: E402


BOOT = r'''
import json, sys
BLOCKED = tuple(json.loads(sys.argv[1]))


class LeftOutOfTheBuild:
    def find_spec(self, name, path=None, target=None):
        if any(name == p or name.startswith(p + '.') for p in BLOCKED):
            raise ModuleNotFoundError(f'this build does not carry {name}', name=name)
        return None


sys.meta_path.insert(0, LeftOutOfTheBuild())
import app
rules = sorted(rule.rule for rule in app.app.url_map.iter_rules())
print('RULES ' + json.dumps({'rules': rules, 'blueprints': sorted(app.app.blueprints)}))
'''


#: What each packaged build carries, spelled out (not derived from gates.py).
BUILDS = {
    'stable-unix': {'preview': False, 'ships': {'assistant'}},
    'stable-windows': {'preview': False, 'ships': {'assistant', 'play'}, 'release': 'play'},
    'preview': {'preview': True, 'ships': {'assistant'}},
    # The assistant held back for a build: its code left out and its gate closed.
    'assistant-held': {'preview': False, 'ships': set(), 'env': {'NUCLEUS_ASSISTANT': '0'}},
}


def _boot(tmp_path, build):
    shipped = BUILDS[build]['ships']
    blocked = [p for feature, packages in _GATED_PACKAGES.items()
               if feature not in shipped for p in packages]
    env = {k: v for k, v in os.environ.items()
           if not k.startswith('NUCLEUS_') and k not in ('PYTHONPATH',)}
    env.update(gates.policy_env(preview=BUILDS[build]['preview'], release=BUILDS[build].get('release')))
    env.update(BUILDS[build].get('env', {}))
    data = tmp_path / 'data'
    data.mkdir()
    env.update({
        'PYTHONPATH': str(BACKEND),
        'NUCLEUS_DATA_ROOT': str(data),
        'NUCLEUS_ALLOW_DEV_DATA_ROOT': '1',
        # A worker child skips the startup sweep of output/ (app.py).
        'NUCLEUS_WORKER': '1',
    })
    result = subprocess.run([sys.executable, '-c', BOOT, json.dumps(blocked)], cwd=BACKEND, env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]
    line = next(line for line in result.stdout.splitlines() if line.startswith('RULES '))
    return json.loads(line[len('RULES '):])


def _has(rules, fragment):
    return [rule for rule in rules if fragment in rule]


@pytest.mark.parametrize('build', list(BUILDS))
def test_packaged_backend_boots_without_the_left_out_packages(tmp_path, build):
    booted = _boot(tmp_path, build)
    rules, blueprints = booted['rules'], booted['blueprints']

    # The shipped surfaces are all there.
    for fragment in ('/api/mex/storage', '/api/nucleome', '/api/mex/codes', '/api/jobs'):
        assert _has(rules, fragment), f'{fragment} missing: the stable app lost a shipped route'
    assert _has(rules, '/api/mex/menus'), 'menus routes missing'
    # The MCP endpoint is always registered: without the assistant it answers with an error.
    assert '/api/mcp' in rules

    # Never in a packaged build: Combo Video and the Tracker coach.
    assert 'combo_video' not in blueprints
    assert not _has(rules, '/combo-video')
    assert not _has(rules, '/coach')
    assert bool(_has(rules, '/api/play/')) == ('play' in BUILDS[build]['ships'])

    # The assistant and the build-change approval card it drives: every package since 0.9.0,
    # unless the build holds the assistant back.
    assistant_routes = _has(rules, '/api/assistant') + _has(rules, '/api/mex/builds/changes')
    if 'assistant' in BUILDS[build]['ships']:
        assert _has(rules, '/api/assistant') and _has(rules, '/api/mex/builds/changes')
        assert {'assistant', 'wishes', 'chat_reports'} <= set(blueprints)
    else:
        assert not assistant_routes, assistant_routes
        assert not {'assistant', 'wishes', 'chat_reports'} & set(blueprints)
