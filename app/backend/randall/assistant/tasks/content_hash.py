"""Content hashes a trace keeps instead of content: canonical JSON values, complete tool schemas,
image bytes in any form, and the exact request body and its attached images."""

import json

from .contracts import digest


# ------------------------------------------------------------------- hashing

def canonical_hash(value):
    """A stable hash of real content, with no plaintext retained.

    Used for prompts, schemas and message bodies. The previous "input artifact
    hash" summarised roles and lengths, so two entirely different requests of
    the same shape collided -- which makes the field useless for the one job it
    has, telling whether two requests were the same request.
    """
    return digest(value)


def schema_hash(schemas):
    """Hash the COMPLETE tool schemas, not just their names.

    Two rosters offering the same tool names with different parameters are
    different contracts and must not share a version.
    """
    return digest([json.dumps(s, sort_keys=True, default=str) for s in (schemas or [])])


def image_bytes_hash(data):
    """One hash for an image, whatever form it arrives in.

    Accepts raw bytes, a base64 string or a `data:` URL and always hashes the
    decoded bytes, so the main model's attachment and the labeller's sheet of
    the same picture produce the same identity.
    """
    import base64
    import binascii
    if isinstance(data, (bytes, bytearray)):
        raw = bytes(data)
    else:
        text = str(data)
        if text.startswith('data:'):
            text = text.split(',', 1)[-1]
        try:
            raw = base64.b64decode(text, validate=True)
        except (binascii.Error, ValueError):
            raw = text.encode('utf-8', 'surrogatepass')
    return digest(raw)


def _message_content_hash(messages):
    """Hash the actual request body; store the hash, never the prose."""
    return digest([json.dumps(m, sort_keys=True, default=str) for m in (messages or [])])


def _image_hashes(messages):
    """Hashes of the images ACTUALLY attached to this request.

    The report's false success came partly from not knowing which pictures the
    reviewer saw. A decoded-bytes hash per attached image makes "the exact image
    hashes actually supplied" answerable from the trace, and comparable with the
    hash of the file on disk.
    """
    hashes = []
    for message in messages or []:
        content = message.get('content')
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get('type') == 'image_url':
                hashes.append(image_bytes_hash((part.get('image_url') or {}).get('url') or ''))
    return hashes
