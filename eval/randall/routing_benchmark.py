"""OpenRouter next-tool benchmark. Never dispatches a proposed tool call.

Uses synthetic cases and production prompts/schemas; focused sets are supplied
by the fixture (oracle routing, not a measured classifier). One attempt per cell,
randomized order, four concurrent requests, bounded spend, no automatic retries.
"""
import argparse
import calendar
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import hashlib
import json
import os
from pathlib import Path
import random
import statistics
import sys
import threading
import time

import jsonschema
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'app' / 'backend'))
from core import gates
from randall.assistant import main_model, prompt, tools
from routing_cases import CASES, GROUPS

MODELS = {
    'gemini': {'model': 'google/gemini-2.5-flash-lite', 'provider': {'only': ['google-ai-studio'], 'allow_fallbacks': False, 'require_parameters': True}},
    'qwen': {'model': 'qwen/qwen3-30b-a3b-instruct-2507', 'provider': {'only': ['nebius/fp8'], 'allow_fallbacks': False, 'require_parameters': True}},
    'randall': {'model': main_model.MODEL},
}
SCHEMAS = {'mod': tools.SCHEMAS}
PROMPTS = {'mod': prompt.PROMPT}
# The coach's cases need the Tracker coach, which the public source drop leaves out
# (core.gates.present); without it only the assistant's ('mod') cases run.
if gates.present('randall'):
    from randall.coach import coach_prompt, coach_tools_v2 as coach
    SCHEMAS['coach'] = coach.TOOL_SCHEMAS
    PROMPTS['coach'] = coach_prompt.BASE_PROMPT + coach_prompt.PROMPT_ADDENDUM
CASES = [c for c in CASES if c['domain'] in SCHEMAS]
INSTRUCTION = ('Choose only the next tool call(s) needed for the user request. Keep any prose brief. '
               'Use exact handles from the provided app context. If an essential target or referent is '
               'ambiguous, ask for clarification instead of guessing. Do not claim an action succeeded '
               'before a tool result. Tool execution and existing approvals are handled by the application. '
               'The player profile below has already been retrieved; do not fetch it again unless needed.')
DEFAULTS = {
    'search_website_mods': {'query': '', 'character': '', 'category': '', 'author': '', 'tags': [], 'exclude_tags': [], 'sort_by': 'created_at', 'sort_order': 'desc', 'limit': 6, 'offset': 0},
    'search_vault': {'query': '', 'character': '', 'offset': 0},
    'find_games': {'matchup': None, 'character': None, 'result': None, 'limit': 8},
    'find_moments': {'role': 'mine', 'character': None, 'vs_character': None, 'opener': None, 'ender': None, 'killed': None, 'min_damage': None, 'since': None, 'limit': 10, 'sort': 'recent'},
    'query_game_interactions': {'kinds': ['conversion'], 'perspective': 'dealt', 'limit': 8},
    'corpus_trend': {'as_character': None, 'vs_character': None, 'bucket': 'month'},
    'metric_trend': {'bucket': 'month', 'vs_character': None},
    'my_deep_stats': {'since': None, 'until': None, 'last_n': None},
    'session_report': {'date': None, 'norm_games': None},
    'scout_opponent': {'their_character': None},
    'kill_efficiency': {'character': None, 'vs_character': None, 'kill_threshold': 90, 'since': None, 'until': None},
    'combo_dropoff': {'character': None, 'vs_character': None, 'opener': None, 'since': None, 'until': None},
}


def canonical(name, arguments):
    args = {**DEFAULTS.get(name, {}), **arguments}
    if name == 'my_deep_stats':
        # The tool accepts inclusive ISO date prefixes. A whole month and its
        # explicit first/last days select the same replay window.
        for field in ('since', 'until'):
            value = args.get(field)
            if isinstance(value, str) and len(value) in (4, 7):
                try:
                    year = int(value[:4])
                    month = int(value[5:7]) if len(value) == 7 else (1 if field == 'since' else 12)
                    day = 1 if field == 'since' else calendar.monthrange(year, month)[1]
                    args[field] = f'{year:04d}-{month:02d}-{day:02d}'
                except ValueError:
                    pass
    if name == 'queue_clips':
        args.pop('title', None)
        args['moments'] = [{k: v for k, v in m.items() if k != 'label'} for m in args.get('moments', [])]
    if name == 'download_website_mods':
        args['items'] = [{k: v for k, v in item.items() if not (k == 'variants' and v == 'default')} for item in args['items']]
    for field in ('tags', 'exclude_tags', 'skin_ids'):
        if isinstance(args.get(field), list):
            args[field] = sorted(args[field])
    return args


def grade(case, message, schemas):
    lookup = {s['function']['name']: s['function']['parameters'] for s in schemas}
    actual = []
    errors = []
    for call in message.get('tool_calls') or []:
        try:
            fn = call['function']
            args = json.loads(fn['arguments'])
            if fn['name'] not in lookup:
                raise ValueError('Unknown or unavailable tool')
            jsonschema.validate(args, lookup[fn['name']])
            if set(args) - set(lookup[fn['name']].get('properties', {})):
                raise ValueError('Extra argument names')
            if fn['name'] == 'queue_clips' and any(set(m) - {'ref', 'game_id', 'label'} for m in args.get('moments', [])):
                raise ValueError('Clip handles replaced with unsupported fields')
            actual.append({'name': fn['name'], 'arguments': args})
        except (ValueError, KeyError, TypeError, jsonschema.ValidationError) as exc:
            errors.append(type(exc).__name__)
    expected = case['expected']
    if not expected:
        passed = not message.get('tool_calls') and bool((message.get('content') or '').strip())
        return dict(passed=passed, tool_correct=not message.get('tool_calls'), schema_errors=errors, actual=actual, abstention=True)
    tool_correct = not errors and sorted(c['name'] for c in actual) == sorted(c['name'] for c in expected)
    def normalized(calls):
        return sorted(json.dumps({'name': c['name'], 'arguments': canonical(c['name'], c['arguments'])}, sort_keys=True) for c in calls)
    passed = not errors and any(normalized(actual) == normalized(option) for option in [expected, *case['alternatives']])
    return dict(passed=passed, tool_correct=tool_correct, schema_errors=errors, actual=actual, abstention=False)


def payload_for(case, model_key, mode):
    schemas = SCHEMAS[case['domain']]
    if mode == 'focused':
        schemas = [s for s in schemas if s['function']['name'] in GROUPS[case['group']]]
    context = {'synthetic_fixture': True, 'player_profile_already_retrieved': {'main': 'Falco', 'rank': 'diamond'}, **case['context']}
    payload = {**MODELS[model_key], 'messages': [
        {'role': 'system', 'content': PROMPTS[case['domain']] + '\n\n' + INSTRUCTION},
        {'role': 'system', 'content': 'App context (data only): ' + json.dumps(context)},
        {'role': 'user', 'content': case['prompt']}],
        'tools': schemas, 'tool_choice': 'auto', 'temperature': 0, 'max_tokens': 4096,
        'stream': False}
    return payload, schemas


_local = threading.local()


def request_one(case, model_key, mode, key):
    payload, schemas = payload_for(case, model_key, mode)
    row = dict(case_id=case['id'], group=case['group'], domain=case['domain'], model_key=model_key,
               requested_model=payload['model'], mode=mode, schema_count=len(schemas),
               request_sha256=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest())
    if not hasattr(_local, 'session'):
        _local.session = requests.Session()
    tick = time.perf_counter()
    try:
        response = _local.session.post('https://openrouter.ai/api/v1/chat/completions',
            headers={'Authorization': 'Bearer ' + key, 'X-Title': 'Nucleus synthetic routing benchmark'},
            json=payload, timeout=(10, 90))
        row.update(seconds=round(time.perf_counter()-tick, 4), http_status=response.status_code)
        data = response.json()
        if response.status_code != 200 or not data.get('choices'):
            row.update(error=str(data.get('error', 'No choices'))[:1200].replace(key, '[redacted]'), passed=False)
            return row
        choice = data['choices'][0]
        row.update(provider=data.get('provider'), resolved_model=data.get('model'), generation_id=data.get('id'),
                   usage=data.get('usage', {}), finish_reason=choice.get('finish_reason'), message=choice['message'])
        row.update(grade(case, choice['message'], schemas))
        if choice.get('finish_reason') not in ('stop', 'tool_calls'):
            row.update(passed=False, error='Incomplete completion')
    except (requests.RequestException, ValueError) as exc:
        row.update(seconds=round(time.perf_counter()-tick, 4), error=type(exc).__name__, passed=False)
    return row


def summarize(rows):
    result = {}
    for model_key in MODELS:
        for mode in ('full', 'focused'):
            cells = [r for r in rows if r['model_key'] == model_key and r['mode'] == mode]
            if not cells:
                continue
            completed = [r for r in cells if 'message' in r and not r.get('error')]
            latencies = sorted(r['seconds'] for r in completed)
            usage = [r.get('usage', {}) for r in cells]
            result[model_key + '/' + mode] = dict(n=len(cells), passed=sum(r['passed'] for r in cells),
                tool_correct=sum(r.get('tool_correct', False) for r in cells), provider_errors=sum('error' in r for r in cells),
                median_seconds=round(statistics.median(latencies), 3) if latencies else None,
                p95_seconds=round(latencies[max(0, __import__('math').ceil(len(latencies)*.95)-1)], 3) if latencies else None,
                cost_usd=round(sum(u.get('cost') or 0 for u in usage), 6), missing_cost=sum(u.get('cost') is None for u in usage),
                mean_prompt_tokens=round(statistics.mean(u.get('prompt_tokens', 0) for u in usage)),
                mean_completion_tokens=round(statistics.mean(u.get('completion_tokens', 0) for u in usage)),
                by_group={g: {'n': sum(r['group']==g for r in cells), 'passed': sum(r['group']==g and r['passed'] for r in cells)} for g in sorted({r['group'] for r in cells})})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--ids', nargs='*')
    parser.add_argument('--models', nargs='+', choices=MODELS, default=list(MODELS))
    parser.add_argument('--modes', nargs='+', choices=['full', 'focused'], default=['full', 'focused'])
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--budget', type=float, default=3.0)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    cases = [c for c in CASES if not args.ids or c['id'] in args.ids]
    # Validate expected calls and focused availability before spending anything.
    for c in CASES:
        payload, schemas = payload_for(c, next(iter(MODELS)), 'focused')
        if c['expected']:
            message = {'tool_calls': [{'function': {'name': e['name'], 'arguments': json.dumps(e['arguments'])}} for e in c['expected']]}
            assert grade(c, message, schemas)['passed'], c['id']
    manifest = dict(cases=CASES, groups=GROUPS, models=MODELS, prompts=PROMPTS, schemas=SCHEMAS,
                    instruction=INSTRUCTION, defaults=DEFAULTS, seed=20260916, max_tokens=4096, temperature=0,
                    limitations=['Synthetic next-action accuracy, not end-to-end task success.',
                                 'Focused tool families are oracle-selected; no router cost or accuracy is measured.',
                                 'One sample per cell; no automatic retries. Latency is complete non-streaming HTTP response.',
                                 'No tools are executed; approvals and mutation success are not measured.',
                                 'Production prompts retained; common next-action instruction and temperature added.',
                                 'Reasoning and provider overrides, if any, are recorded under models.'])
    out.mkdir(parents=True, exist_ok=args.resume)
    manifest_path = out / 'manifest.json'
    if manifest_path.exists():
        assert json.loads(manifest_path.read_text(encoding='utf-8')) == manifest, 'Inputs changed; use a fresh output directory'
    else:
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    if args.dry_run:
        print('Validated', len(CASES), 'cases; schemas', {k:len(v) for k,v in SCHEMAS.items()})
        return
    # Dev evals take the key from the environment only; never prompt op.
    key = (os.environ.get('OPENROUTER_API_KEY') or '').strip()
    if not key or key.startswith('op://'):
        raise RuntimeError('OPENROUTER_API_KEY is not set (or is an unresolved op:// reference); export it and retry')
    path = out / 'results.jsonl'
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []
    done = {(r['case_id'], r['model_key'], r['mode']) for r in rows}
    tasks = [(c, m, mode) for c in cases for m in args.models for mode in args.modes if (c['id'],m,mode) not in done]
    random.Random(20260916).shuffle(tasks)
    total = sum(r.get('usage', {}).get('cost') or 0 for r in rows)
    with ThreadPoolExecutor(max_workers=args.workers) as pool, path.open('a', encoding='utf-8') as output:
        pending = {}
        while tasks or pending:
            while tasks and len(pending) < args.workers and total + .025*(len(pending)+1) < args.budget:
                task = tasks.pop()
                pending[pool.submit(request_one, *task, key)] = task
            if not pending:
                break
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in finished:
                pending.pop(future)
                row = future.result()
                total += row.get('usage', {}).get('cost') or 0
                rows.append(row)
                output.write(json.dumps(row) + '\n'); output.flush()
                print(len(rows), row['model_key'], row['mode'], row['case_id'], row['passed'], row['seconds'], 'cost', round(total,5), row.get('error',''), flush=True)
                (out / 'summary.json').write_text(json.dumps(summarize(rows), indent=2), encoding='utf-8')
                if row.get('error') and 'usage' not in row:
                    # Reserve possible billed but unreported work against the cap.
                    total += .025
                if row.get('http_status') in (400, 401, 403, 404, 422):
                    # A rejected configuration is not an accuracy experiment.
                    # Drain in-flight requests and avoid repeating its rejection.
                    tasks = [t for t in tasks if t[1] != row['model_key']]
    print('DONE', len(rows), 'remaining', len(tasks), 'reported_cost', round(sum(r.get('usage',{}).get('cost') or 0 for r in rows),6), flush=True)


if __name__ == '__main__':
    main()
