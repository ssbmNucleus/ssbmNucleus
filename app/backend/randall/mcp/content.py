"""A tool's result as MCP content: its JSON as one text block, and the pictures it carries as image blocks.

The pictures are the ones the chat would show: lab renders and texture sheets, a model import's
portrait (assistant/vision.py ``tool_images``), a new portrait preview (``preview_portrait``) and the
portraits of the skins ``present_vault_skins`` shows. Pictures are read from inside the vault only.
"""
import base64
import json
import logging
import re
from pathlib import Path
from urllib.parse import unquote

from core import config

MAX_IMAGES = 8
MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}

_log = logging.getLogger(__name__)


def text(value):
    return {'type': 'text', 'text': value if isinstance(value, str)
            else json.dumps(value, default=str, ensure_ascii=False)}


def error(message):
    """A failed call: isError with the message, never an HTTP error."""
    return {'content': [text(str(message))], 'isError': True}


def _from_data_url(url):
    head, _, data = str(url).partition(',')
    if not head.startswith('data:') or ';base64' not in head or not data:
        return None
    return {'type': 'image', 'data': data, 'mimeType': head[5:].split(';', 1)[0] or 'image/png'}


def _vault_file(url):
    """The file a result's picture URL names (``/storage/...`` or a portrait preview), inside the vault, or None."""
    root = Path(config.STORAGE_PATH).resolve()
    url = str(url).split('?', 1)[0]
    if url.startswith('/storage/'):
        parts = [unquote(part) for part in url[len('/storage/'):].split('/')]
        if any(part in ('', '.', '..') for part in parts):
            return None
        path = root.joinpath(*parts)
    elif url.startswith('/api/assistant/previews/'):
        artifact = url.rsplit('/', 1)[-1]
        if not re.fullmatch(r'[a-f0-9]{32}', artifact):
            return None
        path = root / 'assistant' / 'previews' / f'{artifact}.png'
    else:
        return None
    path = path.resolve()
    return path if path.is_relative_to(root) and path.is_file() else None


def _file_image(path):
    mime = IMAGE_TYPES.get(path.suffix.lower())
    if mime is None or path.stat().st_size > MAX_IMAGE_BYTES:
        return None
    return {'type': 'image', 'data': base64.b64encode(path.read_bytes()).decode('ascii'), 'mimeType': mime}


def images(name, result):
    """The MCP image blocks for one tool result (at most ``MAX_IMAGES``)."""
    from randall.assistant.vision import tool_images
    found = []
    for part in tool_images(name, result):
        if part.get('type') == 'image_url':
            image = _from_data_url((part.get('image_url') or {}).get('url'))
            if image:
                found.append(image)
    urls = []
    if name == 'preview_portrait' and result.get('image'):
        urls.append(result['image'])
    if name == 'present_vault_skins':
        urls.extend(item['image'] for item in result.get('items') or [] if isinstance(item, dict) and item.get('image'))
    for url in urls:
        if len(found) >= MAX_IMAGES:
            break
        path = _vault_file(url)
        image = _file_image(path) if path is not None else None
        if image:
            found.append(image)
    return found[:MAX_IMAGES]


def tool_result(name, result, *, is_error=None):
    """``result`` (a tool's dict) as an MCP tools/call result. A result with an ``error`` is isError."""
    content = [text(result)]
    if isinstance(result, dict):
        try:
            content.extend(images(name, result))
        except Exception:  # noqa: BLE001 - a picture that cannot be attached never fails the call
            _log.warning('MCP: pictures of %s not attached', name, exc_info=True)
    if is_error is None:
        is_error = isinstance(result, dict) and bool(result.get('error'))
    return {'content': content, 'isError': bool(is_error)}
