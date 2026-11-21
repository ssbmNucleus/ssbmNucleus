"""Small image-provider boundary for generated material swatches.

One explicit request produces one fresh image. The only retry is a single
repeat after the provider itself answered with a transient error status: that
answer means nothing was generated, so nothing was billed. A timeout or dropped
connection is never retried -- the image may have been made and billed. No model
escalation or shared prompt cache. Credentials and provider payloads stay here.

Providers bill per IMAGE (or, for FLUX.2 Klein, per megapixel with a 1 MP
minimum) -- never much under a cent -- while a Melee texture is 256 px at most.
So several materials are requested as one gridded sheet and cropped apart:
measured on meta/muse-image, four clean swatches for $0.010 in a single call.
"""
import base64
import binascii
import io
import json
import logging
import math
import os

import numpy as np
import requests
from PIL import Image


# Measured 2026-09-18 on one Aztec prompt: muse $0.010 with the cleanest flat,
# edge-to-edge repeat; flux.2-klein-4b $0.014 (1 MP minimum at any size) and a
# muddled, framed result; krea-2-medium-turbo $0.015, 1K only, bevelled tiles.
DEFAULT_MATERIAL_MODEL = 'meta/muse-image'
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 16_777_216
MAX_SHEET = 4
# Provider answers that mean "nothing was generated, try again". A zombie-Link
# sheet failed once with 400 and the identical request succeeded minutes later;
# the failure cost the model a round to rewrite its prompts.
RETRY_STATUSES = frozenset({400, 500, 502, 503})

# What the material card and Randall read when no image was made. Users never see the provider's name, keys,
# credits or money (owner's rule, 2026-10-07): the provider's own status and words go to the log and the
# result's `diagnostic` ("Report this chat"), never into these.
USED_UP = "This month's Randall usage is used up, so no image was generated."
UNAVAILABLE = 'Image generation is unavailable right now, so no image was generated.'
NOT_SET_UP = "Randall's AI access isn't set up, so no image was generated."

_log = logging.getLogger(__name__)


class ImageUnavailable(ValueError):
    """No image was made: the message is the plain sentence, `diagnostic` the provider detail.

    A ValueError, so the assistant's tool layer shows the message as the tool's error and keeps
    `diagnostic` off the model (assistant/tools.py, compaction.UI_ONLY_ANY).
    """

    def __init__(self, message, diagnostic):
        super().__init__(message)
        self.diagnostic = diagnostic


def _unavailable(message, diagnostic):
    _log.warning('Image generation failed: %s', diagnostic)
    return ImageUnavailable(message, diagnostic)


SWATCH = ('Create a seamless, tileable material swatch for a game texture. '
          'Flat straight-on surface, even lighting, no perspective, objects, '
          'text or borders. Make its pattern readable at small texture sizes. '
          'Fill the square edge to edge. Material: ')
# Not every request is a material. "Money themed" needs actual banknotes --
# portraits, numerals, engraving -- and the swatch wrapper above forbids
# exactly that ("no objects, text or borders"), so a money Falcon came out as
# green noise. Artwork keeps the all-over, edge-to-edge framing a texture needs
# and allows the subject itself.
ARTWORK = ('Create artwork for a game texture: an all-over, edge-to-edge composition of the '
           'subject below, straight-on and evenly lit, no frame, border, margin or background '
           'scene. Objects, lettering and fine detail are welcome; keep them large enough to '
           'read at small texture sizes. Subject: ')
GRID = ('A 2x2 grid of four SEPARATE square material swatches for game textures, divided by thin '
        'straight black gutters. Each quadrant is a flat, straight-on, seamless, edge-to-edge '
        'all-over pattern with even lighting and no objects, text or borders inside it, '
        'readable at small texture sizes. ')
QUADRANTS = ('Top-left', 'Top-right', 'Bottom-left', 'Bottom-right')


def _request(prompt, key):
    """(RGBA image, metadata) for one billed image, repeating once only after a
    transient error status (see RETRY_STATUSES)."""
    # One logical image request, run through the coordinator's shared retry
    # policy: bounded attempts with backoff and jitter, transient statuses only,
    # and each dispatch admitted against the turn's own image allowance (counted
    # in images; a transient status that billed nothing gives its image back), or
    # the task's money budget when it has none. The old inline
    # repeat had no backoff at all, so a rate-limited provider was hit twice in
    # a row, and its `_Transient` was invisible to the shared classifier.
    from randall.assistant.tasks import coordinator as taskflow

    def attempt(span):
        return _request_once(prompt, key, span=span)

    try:
        return taskflow.run_model_request(
            'image', attempt, attempts=2, repairs=0,
            requested_model=os.environ.get('NUCLEUS_MATERIAL_MODEL', DEFAULT_MATERIAL_MODEL),
            task_family='material', timeout_s=180,
            prompt_template_version=taskflow.canonical_hash(prompt))
    except _Transient as again:
        raise _unavailable(UNAVAILABLE, f'image provider HTTP {again.status}, twice') from None


class _Transient(Exception):
    """A status this endpoint treats as transient, whatever it means elsewhere.

    The images endpoint answers 400 when a provider is busy, so the shared
    classifier cannot decide from the status alone; `transient = True` is this
    call site declaring what it knows (see coordinator.classify).
    """
    transient = True

    def __init__(self, status):
        super().__init__(status)
        self.status = status


def _request_once(prompt, key, *, span=None):
    """(RGBA image, metadata) for one provider request."""
    if not key:
        raise _unavailable(NOT_SET_UP, 'no provider key for this request (generated materials need the '
                                       'Patreon-provisioned key)')
    model = os.environ.get('NUCLEUS_MATERIAL_MODEL', DEFAULT_MATERIAL_MODEL)
    payload = {'model': model, 'prompt': prompt, 'aspect_ratio': '1:1', 'n': 1}
    return _image_request(prompt, key, model, payload, span or _NoSpan())


class _NoSpan:
    """Absorbs span annotations when this runs outside a traced request."""

    def __getattr__(self, _name):
        return ''

    def __setattr__(self, _name, _value):
        pass

    def record_usage(self, _usage):
        return self


def _image_request(prompt, key, model, payload, _span):
    try:
        with requests.post('https://openrouter.ai/api/v1/images', json=payload,
                           headers={'Authorization': f'Bearer {key}'},
                           timeout=(15, 180), stream=True) as response:
            _span.http_status = getattr(response, 'status_code', None)
            if response.status_code in RETRY_STATUSES:
                _span.provider_error = f'HTTP {response.status_code}'
                raise _Transient(response.status_code)
            if response.status_code != 200:
                # Provider errors may echo request data; never forward their body. 402: the key has no
                # credit left, which is this month's usage running out.
                reason = {401: 'key refused', 402: 'no credit left on the key', 429: 'rate limited'}.get(
                    response.status_code, 'request not completed')
                raise _unavailable(USED_UP if response.status_code == 402 else UNAVAILABLE,
                                   f'image provider HTTP {response.status_code} ({reason}); no automatic retry')
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > MAX_IMAGE_BYTES * 2:
                    raise _unavailable(UNAVAILABLE, 'image provider response too large')
                chunks.append(chunk)
            body = json.loads(b''.join(chunks))
            # Billing and identity before the image is decoded: a generation
            # that billed and then produced something we cannot open is still a
            # charge, and recording it after the decode lost it.
            _span.provider_generation_id = str(body.get('id') or '')
            _span.resolved_model = str(body.get('model') or model)
            _span.record_usage(body.get('usage') or {})
    except requests.RequestException as exc:
        raise _unavailable(UNAVAILABLE, f'image request failed or timed out ({type(exc).__name__}); '
                                        'no automatic retry') from None
    except (TypeError, UnicodeError, json.JSONDecodeError):
        raise _unavailable(UNAVAILABLE, 'image provider returned an invalid response') from None
    try:
        encoded = body['data'][0]['b64_json']
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError('Image too large')
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > MAX_PIXELS:
                raise ValueError('Image too large')
            picture = image.convert('RGBA')
    except (KeyError, IndexError, TypeError, ValueError, OSError, binascii.Error, Image.DecompressionBombError):
        raise _unavailable(UNAVAILABLE, 'image provider did not return a supported raster image') from None
    usage = body.get('usage') or {}
    cost = usage.get('cost') if isinstance(usage, dict) else None
    result = {'provider': 'openrouter', 'model': model}
    if type(cost) in (int, float) and math.isfinite(cost) and cost >= 0:
        result['cost_usd'] = cost
    _span.response_validation = 'valid'
    return picture, result


def _png(image):
    output = io.BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


def _gutter(luma, axis):
    """The CENTRE of the dark gutter band near the middle along `axis` (0 = a
    row), or the exact middle when nothing there is dark enough to be one.
    Splitting at the band's first dark line instead leaves the far cell starting
    inside the gutter, and a black stripe survives into that swatch."""
    profile = luma.mean(axis=1 - axis)
    size = len(profile)
    low, high = int(size * 0.35), int(size * 0.65)
    line = low + int(np.argmin(profile[low:high]))
    if profile[line] >= 60:
        return size // 2
    start = end = line
    while start > low and profile[start - 1] < 60:
        start -= 1
    while end < high - 1 and profile[end + 1] < 60:
        end += 1
    return (start + end + 1) // 2


def split_sheet(image):
    """The four quadrants of a gridded sheet, gutters and outer frame trimmed."""
    luma = np.asarray(image.convert('L'), dtype=np.float32)
    row, col = _gutter(luma, 0), _gutter(luma, 1)
    width, height = image.size
    crops = []
    for left, top, right, bottom in ((0, 0, col, row), (col, 0, width, row),
                                     (0, row, col, height), (col, row, width, height)):
        # A few percent in from every edge clears the gutter and any frame the
        # model drew round the sheet; the swatch is far larger than any texture.
        inset_x, inset_y = int((right - left) * 0.04), int((bottom - top) * 0.04)
        crops.append(image.crop((left + inset_x, top + inset_y, right - inset_x, bottom - inset_y)))
    return crops


def _check_allowance(needed):
    """Refuse a call needing more billed images than the turn has left, before any is requested.

    The turn's own image allowance (coordinator.TaskContext.allow_images) admits each request
    as it is sent; an artwork call is one request per prompt, so without this a call could buy
    some of its images, be refused the rest and return none of them. None left is the
    allowance refusal itself; some left is the call's own mistake, said so it can be resent.
    """
    from randall.assistant.tasks import coordinator as taskflow
    task = taskflow.current()
    left = task.images_left()
    if left is None or needed <= left:
        return
    if left == 0:
        raise taskflow.ImageAllowanceReached(task.image_allowance)
    raise ValueError(f'This request has {left} generated image{"" if left == 1 else "s"} left and this call '
                     f'needs {needed}, so nothing was generated; send fewer artwork prompts (a swatch sheet is '
                     'one image for up to four materials), or ask again in a new message to make more.')


def generate_material_sheet(prompts, *, key=None, style='swatch'):
    """One image per prompt from ONE provider request: (pngs, metadata).

    style='swatch' is a seamless tiling material; style='artwork' is a picture
    of the subject itself (banknotes, a mural), which `fit` lays across a
    texture. Artwork is generated one per request: a 2x2 grid would halve the
    resolution of art that has to read as itself.
    """
    if (not isinstance(prompts, list) or not 1 <= len(prompts) <= MAX_SHEET
            or any(not isinstance(p, str) or not p.strip() or len(p) > 2000 for p in prompts)):
        raise ValueError(f'Describe 1..{MAX_SHEET} materials, each in 1..2000 characters.')
    if style not in ('swatch', 'artwork'):
        raise ValueError('style must be swatch or artwork.')
    _check_allowance(len(prompts) if style == 'artwork' else 1)
    if style == 'artwork':
        images, metadata = [], {}
        for text in prompts:
            picture, meta = _request(ARTWORK + text.strip(), key)
            images.append(picture)
            for field in ('provider', 'model'):
                metadata[field] = meta.get(field, metadata.get(field))
            if 'cost_usd' in meta:
                metadata['cost_usd'] = round(metadata.get('cost_usd', 0) + meta['cost_usd'], 6)
        swatches = images
    elif len(prompts) == 1:
        picture, metadata = _request(SWATCH + prompts[0].strip(), key)
        swatches = [picture]
    else:
        # Unused quadrants still render; plain grey keeps them inert and stops
        # the model inventing a material nobody asked for.
        cells = [p.strip() for p in prompts] + ['plain flat neutral grey'] * (4 - len(prompts))
        picture, metadata = _request(GRID + ' '.join(
            f'{where}: {what}.' for where, what in zip(QUADRANTS, cells)), key)
        swatches = split_sheet(picture)[:len(prompts)]
    metadata.update(width=swatches[0].width, height=swatches[0].height, materials=len(prompts))
    if 'cost_usd' in metadata:
        metadata['cost_per_material_usd'] = round(metadata['cost_usd'] / len(prompts), 6)
    return [_png(swatch) for swatch in swatches], metadata


