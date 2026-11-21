"""Recolor vanilla Fox for real, once per model, and keep the renders.

`assistant_lane.py` stubs every tool, so it measures speed and tool-sequencing
and nothing else. This one runs the actual `recolor/skin_lab.py` against the
extracted vanilla Fox DAT, feeds the model real renders through the app's own
`vision.tool_images`, and saves each model's final preview to
`artifacts/skin-quality/`. That is the only way to see whether a model's colour
judgement is any good -- no offline number predicts it.

The grader is deliberately NOT included: a model must not grade its own work.
Compare the PNGs by eye, or hand them to a model that produced none of them.

Only the vault lookup is stubbed, because vanilla costumes are not reachable
through Randall's tools yet -- the DAT is registered directly and handed over
as if `open_vault_file` had returned it.

Usage:
    app/venv/Scripts/python.exe eval/randall/skin_quality_lane.py --model inclusionai/ling-3.0-flash-vl
    app/venv/Scripts/python.exe eval/randall/skin_quality_lane.py --compare
"""
import argparse
import json
import os
import shutil
import sys
import time

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(os.path.dirname(EVAL_DIR))
sys.path.insert(0, EVAL_DIR)  # runner.py
sys.path.insert(0, os.path.join(REPO_DIR, 'app', 'backend'))

import requests  # noqa: E402
from runner import load_api_key  # noqa: E402
from core import config  # noqa: E402
from randall.assistant import main_model, prompt, tools, vision  # noqa: E402
from shared import mod_files
from randall.recolor import skin_lab  # noqa: E402

API_URL = 'https://openrouter.ai/api/v1/chat/completions'
MAX_ROUNDS = 16
OUT_DIR = os.path.join(REPO_DIR, 'artifacts', 'skin-quality')

TASK = ("Make a military-inspired recolor of this vanilla Fox costume. Open it in the skin lab, "
        "look at the textures and analyze the palette, then recolor it into a believable military "
        "scheme -- olive drab and khaki fatigues, muted webbing, subdued metal. Keep it readable as "
        "Fox. Apply the recolor so the preview shows it, then stop.")

CANDIDATES = [
    'z-ai/glm-5.3-flash',
    'deepseek/deepseek-v4.1-flash',
    'inclusionai/ling-3.0-flash-vl',
]

# Executed for real. Everything else is answered from the stub below.
LIVE = {'skin_lab_open': skin_lab.skin_lab_open, 'skin_lab': skin_lab.skin_lab}


def fox_file_id():
    dat = config.VANILLA_ASSETS_DIR / 'Fox' / 'PlFxNr' / 'PlFxNr.dat'
    if not dat.exists():
        raise SystemExit(f'vanilla Fox missing at {dat}; refresh vanilla assets in Settings')
    return mod_files.register(dat.read_bytes(), 'PlFxNr.dat',
                              origin={'character': 'Fox', 'name': 'Vanilla Fox'})['file_id']


def run(model, key, verbose=False):
    file_id = fox_file_id()
    stubs = {
        'search_vault': {'items': [{'character': 'Fox', 'id': 'vanilla-fox', 'name': 'Vanilla Fox'}], 'total': 1},
        'open_vault_file': {'file_id': file_id, 'file': {'name': 'PlFxNr.dat'}},
    }
    messages = [{'role': 'system', 'content': prompt.PROMPT},
                {'role': 'user', 'content': TASK + f' The costume is already open as file ID {file_id}.'}]
    started = time.time()
    calls, session_id, last_png = [], None, None

    for _ in range(MAX_ROUNDS):
        body = {'model': model, 'messages': messages, 'max_tokens': 4096,
                'tools': tools.SCHEMAS, 'tool_choice': 'auto'}
        response = requests.post(API_URL, json=body, timeout=240,
                                 headers={'Authorization': f'Bearer {key}',
                                          'X-Title': 'Nucleus skin quality lane'})
        if response.status_code != 200:
            return {'model': model, 'error': f'HTTP {response.status_code}: {response.text[:160]}',
                    'calls': calls, 'session_id': session_id}
        message = ((response.json().get('choices') or [{}])[0].get('message')) or {}
        messages.append({k: v for k, v in message.items() if k in ('role', 'content', 'tool_calls')})
        requested = message.get('tool_calls') or []
        if not requested:
            break

        visual = []
        for call in requested:
            name = call['function']['name']
            try:
                args = json.loads(call['function']['arguments'] or '{}')
            except ValueError:
                args = {}
            if name in LIVE:
                try:
                    result = LIVE[name](**args)
                except Exception as exc:  # a failed edit is data, not a crash
                    result = {'error': f'{type(exc).__name__}: {exc}'}
            else:
                result = stubs.get(name, {'ok': True})
            session_id = result.get('session_id') or session_id
            for entry in result.get('files') or []:
                if entry.get('extension') == '.png':
                    last_png = entry['file_id']
            calls.append(name + (f":{args.get('action')}" if args.get('action') else ''))
            if verbose:
                print('    ', calls[-1], '->', json.dumps(result)[:110], flush=True)
            messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': json.dumps(result)})
            # The app's own attachment path, so the model sees what Randall sees.
            visual.extend(vision.tool_images(name, result))

        if visual:
            # Mirror engine.py: drop earlier pixels, keep only this round's. The
            # app caps at 8; 4 is the lowest provider ceiling seen here (ling
            # answers "Too many images in request: 5 > 4"), so cap lower to keep
            # every model comparable rather than failing one of them.
            messages = [m for m in messages
                        if not (m['role'] == 'user' and isinstance(m.get('content'), list))]
            messages.append({'role': 'user', 'content': visual[:4]})

    if session_id:
        # Grab our own frame rather than trusting whatever PNG came last: a model
        # that ends on a texture read would otherwise be "compared" by a 128px
        # close-up instead of its costume.
        try:
            final = skin_lab.skin_lab(session_id=session_id, action='frame')
            for entry in final.get('files') or []:
                if entry.get('extension') == '.png':
                    last_png = entry['file_id']
        except Exception as exc:
            print('    could not grab a final frame:', exc, flush=True)
        try:
            skin_lab.skin_lab(session_id=session_id, action='close')
        except Exception:
            pass

    saved = None
    if last_png:
        try:
            path, _ = mod_files.resolve(last_png)
            os.makedirs(OUT_DIR, exist_ok=True)
            saved = os.path.join(OUT_DIR, model.replace('/', '_') + '.png')
            shutil.copyfile(path, saved)
        except (ValueError, OSError) as exc:
            saved = f'could not save: {exc}'
    return {'model': model, 'seconds': round(time.time() - started, 1),
            'tool_calls': len(calls), 'calls': calls, 'render': saved}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model')
    parser.add_argument('--compare', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    key = os.environ.get('OPENROUTER_API_KEY') or load_api_key()
    targets = CANDIDATES if args.compare else [args.model or main_model.MODEL]

    for model in targets:
        print(f'--- {model}', flush=True)
        try:
            outcome = run(model, key, args.verbose)
        except Exception as exc:
            outcome = {'model': model, 'error': f'{type(exc).__name__}: {exc}'}
        print('   ', json.dumps(outcome), flush=True)


if __name__ == '__main__':
    main()
