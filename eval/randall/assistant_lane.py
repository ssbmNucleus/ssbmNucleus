"""Time a recolor-shaped turn through the vault assistant's real tool surface.

`v2_lane.py` covers the coach; this is the other Randall — `assistant/tools.py`
with `engine.PROMPT`, the stack a "recolor this skin" request actually drives.

Tool results are STUBBED, so no vault, HSDRawViewer or Patreon key is needed and
every model is scored against byte-identical inputs. That measures the two
things that decide how slow Randall feels -- token throughput, and how many
tool round-trips a model needs to finish -- but says nothing about recolor
quality, which needs the real renderer.

One texture read returns a real (tiny) PNG so vision is exercised too; a model
that cannot read the image will loop or guess, and that shows up as extra rounds.

Usage:
    app/venv/Scripts/python.exe eval/randall/assistant_lane.py --model deepseek/deepseek-v4.1-flash
    app/venv/Scripts/python.exe eval/randall/assistant_lane.py --compare
"""
import argparse
import base64
import json
import os
import sys
import time
import zlib

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(os.path.dirname(EVAL_DIR))
sys.path.insert(0, EVAL_DIR)
sys.path.insert(0, os.path.join(REPO_DIR, 'app', 'backend'))

import requests  # noqa: E402
from runner import load_api_key  # noqa: E402
from randall.assistant import main_model, prompt, tools  # noqa: E402

API_URL = 'https://openrouter.ai/api/v1/chat/completions'
MAX_ROUNDS = 12
TASK = ('Recolor my Ukulele Pichu costume to look like Minun: shift the yellow fur to blue. '
        'Open it in the skin lab, look at a texture to confirm the fur colour, then apply it.')

CANDIDATES = [
    'z-ai/glm-5.3-flash',            # incumbent
    'deepseek/deepseek-v4.1-flash',  # 2.6x faster on the first sweep
    'qwen/qwen3.8-flash',            # first sweep: upstream 429, retry
    'bytedance-seed/seed-2.0-mini',  # first sweep: rejected the 2px fixture
]

# Free tiers are rate-limited and generally require opting into prompt logging,
# so these are measured out of interest, not as shipping candidates.
FREE = [
    'thinkingmachines/inkling:free',
    'google/gemma-4-31b-it:free',
    'inclusionai/ling-3.0-flash-vl:free',
]


def tiny_png(side=64):
    """A flat-yellow PNG, built here so the fixture needs no binary in the repo.

    64px rather than 2px: some providers reject undersized images outright
    (seed-2.0-mini answered "Image dimensions are too small"), which scores the
    harness rather than the model.
    """
    raw = b''.join(b'\x00' + b'\xf5\xe9\x48' * side for _ in range(side))
    def chunk(tag, body):
        data = tag + body
        return len(body).to_bytes(4, 'big') + data + zlib.crc32(data).to_bytes(4, 'big')
    header = side.to_bytes(4, 'big') + side.to_bytes(4, 'big') + bytes([8, 2, 0, 0, 0])
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header)
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


IMAGE_URL = 'data:image/png;base64,' + base64.b64encode(tiny_png()).decode()

# Plausible results for the tools this task reaches, so the model can progress.
STUBS = {
    'search_vault': {'items': [{'character': 'Pichu', 'id': 'ukulele-pichu', 'name': 'Ukulele Pichu'}], 'total': 1},
    'open_vault_file': {'file_id': 'f1', 'file': {'name': 'PlPcBuMod.dat'}},
    'skin_lab_open': {'session_id': 's1', 'texture_indices': list(range(16)),
                      'files': [{'file_id': 'p1', 'name': 'Skin preview.png'}],
                      'note': 'Private costume copy.'},
    'skin_lab': {'ok': True},
    'save_mod_copy': {'vault_changed': True, 'note': 'Added to vault.'},
}


def stub_for(name, args):
    if name == 'skin_lab':
        action = args.get('action')
        if action in ('texture', 'get_texture'):
            return {'reading': True, 'files': [{'file_id': 't0', 'name': 'Skin texture 0.png'}]}, True
        if action == 'analyze_palette':
            return {'groups': [{'id': 0, 'hex': '#f5e948', 'share': 0.41, 'label': 'fur'},
                               {'id': 1, 'hex': '#3a2f1d', 'share': 0.12, 'label': 'ear tips'}]}, False
        if action == 'recolor':
            return {'updated_textures': [6, 9, 13], 'files': [{'file_id': 'p2', 'name': 'Recolored skin.png'}]}, False
    return STUBS.get(name, {'ok': True}), False


def run(model, key, verbose=False):
    schemas = tools.SCHEMAS
    messages = [{'role': 'system', 'content': prompt.PROMPT},
                {'role': 'user', 'content': TASK}]
    started = time.time()
    first_token = None
    rounds = 0
    calls = []
    prompt_tokens = completion_tokens = cached_tokens = 0

    for _ in range(MAX_ROUNDS):
        rounds += 1
        body = {'model': model, 'messages': messages, 'max_tokens': 4096,  # the app allows 16384; bounded here only to cap sweep cost
                'tools': schemas, 'tool_choice': 'auto'}
        response = requests.post(API_URL, json=body, timeout=180,
                                 headers={'Authorization': f'Bearer {key}',
                                          'X-Title': 'Nucleus assistant lane'})
        if response.status_code != 200:
            return {'model': model, 'error': f'HTTP {response.status_code}: {response.text[:180]}'}
        payload = response.json()
        if first_token is None:
            first_token = time.time() - started
        usage = payload.get('usage') or {}
        prompt_tokens += usage.get('prompt_tokens') or 0
        completion_tokens += usage.get('completion_tokens') or 0
        cached_tokens += ((usage.get('prompt_tokens_details') or {}).get('cached_tokens') or 0)
        choice = (payload.get('choices') or [{}])[0]
        message = choice.get('message') or {}
        messages.append({k: v for k, v in message.items() if k in ('role', 'content', 'tool_calls')})

        requested = message.get('tool_calls') or []
        if not requested:
            break
        for call in requested:
            name = call['function']['name']
            try:
                args = json.loads(call['function']['arguments'] or '{}')
            except ValueError:
                args = {}
            calls.append(name + (f":{args.get('action')}" if args.get('action') else ''))
            result, with_image = stub_for(name, args)
            messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': json.dumps(result)})
            if with_image:
                messages.append({'role': 'user', 'content': [
                    {'type': 'text', 'text': 'Texture image from the tool above.'},
                    {'type': 'image_url', 'image_url': {'url': IMAGE_URL}}]})
        if verbose:
            print('   ', ' '.join(calls[-len(requested):]), flush=True)

    elapsed = time.time() - started
    return {'model': model, 'seconds': round(elapsed, 1), 'first_token_s': round(first_token or 0, 1),
            'rounds': rounds, 'calls': calls, 'tool_calls': len(calls),
            'prompt_tokens': prompt_tokens, 'cached_tokens': cached_tokens,
            'completion_tokens': completion_tokens,
            'tok_per_s': round(completion_tokens / elapsed, 1) if elapsed else 0,
            'finished': bool(calls) and rounds < MAX_ROUNDS}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model')
    parser.add_argument('--compare', action='store_true')
    parser.add_argument('--free', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    # `.env` holds an op:// reference, so load_api_key() shells out to 1Password
    # and needs its desktop prompt answered. An env var skips that entirely,
    # which matters when this runs somewhere nobody can click an approval.
    key = os.environ.get('OPENROUTER_API_KEY') or load_api_key()
    targets = FREE if args.free else CANDIDATES if args.compare else [args.model or main_model.MODEL]

    results = []
    for model in targets:
        print(f'--- {model}', flush=True)
        try:
            outcome = run(model, key, args.verbose)
        except Exception as exc:  # a dead model must not end the sweep
            outcome = {'model': model, 'error': f'{type(exc).__name__}: {exc}'}
        results.append(outcome)
        print('   ', json.dumps({k: v for k, v in outcome.items() if k != 'calls'}), flush=True)

    print('\n== summary ==')
    print(f'{"model":36}{"secs":>7}{"ttft":>7}{"rounds":>7}{"tools":>6}{"tok/s":>7}{"cached":>8}')
    for r in results:
        if r.get('error'):
            print(f'{r["model"]:36}  {r["error"][:58]}')
        else:
            print(f'{r["model"]:36}{r["seconds"]:7}{r["first_token_s"]:7}'
                  f'{r["rounds"]:7}{r["tool_calls"]:6}{r["tok_per_s"]:7}{r["cached_tokens"]:8}')


if __name__ == '__main__':
    main()
