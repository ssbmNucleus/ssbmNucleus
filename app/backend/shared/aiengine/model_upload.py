"""Model-request bodies that get through a slow uplink.

A tester's import failed seven OpenRouter requests in a row with
`ConnectionError: ('Connection aborted.', TimeoutError('The write operation
timed out'))`, each after ~10.4 s: the second look and one whole chat turn.
Two things added up to that:

* The bodies were big. The second look sent its source picture and four review
  pages as full PNG (~5 MB of base64 on a Togetic-on-Pikachu fit), the
  draft tie-break nine 1600-px pages per order, twice at once.
* urllib3 has no write timeout. It sends a request body with the socket
  timeout set to the CONNECT timeout, and a body passed as one `bytes` goes
  out in a single TLS write under a single deadline -- so every model request
  had ten seconds to upload ALL of its body, however large. Five megabytes in
  ten seconds needs a 4 Mbit/s uplink.

So images are encoded for the model (`encode_image`: downscaled, JPEG
unless a caller needs lossless), and `post_json` sends the body in blocks.
Each block's socket write is still bounded by the connect timeout, which
makes that bound a STALL timeout (no 16 KB of progress in ten seconds) rather
than a total; the whole upload gets a budget that scales with the body
(`upload_budget`), counted from the call and never past the caller's absolute
deadline, and a Stop is honoured between blocks. When an upload provably did
not all go out, `UploadFailed` says so, and the caller's retry can send the
same request with smaller pictures (`shrink_messages`). Once every byte is out
nothing here raises: the provider may already be working, and charging.
"""
import base64
import copy
import io
import json
import time

import requests
import urllib3

# Longest side of a picture sent to a model. The review pages are drawn at
# 390-520 px per camera, three or four cameras across (1170-2080 px); 1280
# keeps each camera panel at 320 px or more, which is what the vision models
# tile an image down to anyway. JPEG q85 at that size is a tenth of the PNG.
MAX_SIDE = 1280
QUALITY = 85
# The one retry after an upload broke: the same pictures, smaller.
SMALL_MAX_SIDE = 768
SMALL_QUALITY = 70
# A body is given this long plus one second per MIN_UPLOAD_BPS bytes to finish
# uploading (a 1 MB body: 20 s + 43 s). The per-block stall bound is what
# catches a dead link; this only stops a crawl from outliving its request.
UPLOAD_BASE_S = 20.
MIN_UPLOAD_BPS = 24_000
# The block the body is handed to the socket in. urllib3 reads its own
# blocksize (16 KB) from a readable body; this is only the fallback.
BLOCK = 16_384


class UploadFailed(requests.ConnectionError):
    """The request body provably did NOT all go out: the connection broke,
    stalled or ran out of time before the socket accepted its last byte, so
    the provider cannot have a complete request to run. A transient failure
    (it is a `requests.ConnectionError`), and one a smaller body may get past.

    A connection lost AFTER the whole body was handed over is never this: the
    provider may have the request and may charge for it, so it stays the plain
    `requests` error it was."""

    def __init__(self, message, *, sent=0, total=0):
        super().__init__(message)
        self.sent = sent
        self.total = total


class UploadCancelled(RuntimeError):
    """The user stopped the request before its body was all sent: nothing
    reached the model, and it is not a failure to retry."""


class UploadTimedOut(TimeoutError):
    """Raised inside the body reader when the upload's time runs out.

    A TimeoutError, so urllib3 and requests wrap it exactly as they wrap a
    socket write timeout: `ConnectionError(('Connection aborted.', ...))`."""


class _Stopped(OSError):
    """Raised inside the body reader on a cancel; wrapped like any write error."""


def upload_budget(nbytes):
    """Seconds a body of `nbytes` is given to upload. -> float"""
    return UPLOAD_BASE_S + max(0, int(nbytes)) / MIN_UPLOAD_BPS


def _is_set(cancelled):
    if cancelled is None:
        return False
    check = getattr(cancelled, 'is_set', cancelled)
    return bool(check())


class _Body:
    """The serialised body as a readable with a known length, timed as it is read.

    requests sets Content-Length from `len()` (so the request is not chunked)
    and urllib3 reads it in blocks, sending each with its own socket write. It
    asks for the next block only after the socket accepted the last one, so a
    `read` call is the proof that everything handed out before it went out:
    `delivered` counts only those bytes, and the final read (the one that
    returns b'') is the proof the whole body did.
    """

    def __init__(self, data, *, until=None, cancelled=None):
        self._data = memoryview(data)
        self._handed = 0
        self._until = until            # the time.monotonic() instant the upload must finish by
        self._cancelled = cancelled
        self.delivered = 0
        self.stopped = None            # 'cancelled' | 'deadline' when this reader stopped the upload

    def __len__(self):
        return len(self._data)

    @property
    def started(self):
        """Whether a block of the body was handed to the socket (the connection was made)."""
        return self._handed > 0

    @property
    def fully_sent(self):
        return self.delivered >= len(self._data)

    def read(self, size=-1):
        self.delivered = self._handed
        if self._handed >= len(self._data):
            # Every byte is out: from here on a failure may follow a request the
            # provider has in full, so nothing is raised on the way to EOF.
            return b''
        if _is_set(self._cancelled):
            self.stopped = 'cancelled'
            raise _Stopped('the request was stopped before its body was sent')
        if self._until is not None and time.monotonic() >= self._until:
            self.stopped = 'deadline'
            raise UploadTimedOut(f'the request body was still uploading at its deadline '
                                 f'({self._handed} of {len(self._data)} bytes)')
        if size is None or size < 0:
            size = len(self._data) - self._handed
        size = min(size or BLOCK, len(self._data) - self._handed)
        chunk = self._data[self._handed:self._handed + size].tobytes()
        self._handed += size
        return chunk


def encode_json(payload):
    """The body `requests.post(json=payload)` would send. -> bytes"""
    return json.dumps(payload, allow_nan=False).encode('utf-8')


def post_json(url, payload, *, headers=None, timeout=(10, 60), stream=False, deadline=None, cancelled=None):
    """POST `payload` as JSON with a body upload timed by progress, not in one write. -> Response

    `timeout` is requests' (connect, read). `deadline` (a `time.monotonic()`
    instant) is absolute and counted from THIS call: the connect timeout and
    the response wait are clamped to what is left of it, and no block of the
    body is handed to the socket after it. The upload alone also has
    `upload_budget` of the body size from this call. Each block's socket write
    is bounded by the (clamped) connect timeout -- a stall bound; urllib3 has
    no separate write timeout to clamp further.

    `cancelled` (an Event-like `.is_set()` or a callable) is checked before
    every block: a Stop before the body is all out raises `UploadCancelled`,
    and the provider never gets a complete request to run.

    Redirects are not followed: a 307/308 would resend a body this reader has
    already spent. OpenRouter does not redirect a POST; a 3xx comes back as
    the response, for the caller's status check to refuse.

    Raises `UploadFailed` only when the upload began and provably did not all
    go out. A connection never made, or lost after the last byte was handed
    over, is the plain `requests` error.
    """
    started = time.monotonic()
    data = encode_json(payload)
    until = started + upload_budget(len(data))
    if deadline is not None:
        until = min(until, deadline)
    connect, read = timeout if isinstance(timeout, tuple) else (timeout, timeout)
    if _is_set(cancelled):
        raise UploadCancelled('the request was stopped before it was sent')
    if until - started <= 0:
        raise UploadFailed('the deadline passed before the request was sent', sent=0, total=len(data))
    connect = min(connect, until - started)
    if deadline is not None:
        # `total` makes urllib3 wait for the response only as long as is left
        # of the deadline after connecting and uploading.
        timeout = urllib3.Timeout(connect=connect, read=read, total=deadline - started)
    else:
        timeout = (connect, read)
    body = _Body(data, until=until, cancelled=cancelled)
    headers = {**(headers or {}), 'Content-Type': 'application/json'}
    try:
        return requests.post(url, data=body, headers=headers, timeout=timeout, stream=stream,
                             allow_redirects=False)
    except requests.ConnectionError as exc:
        if body.stopped == 'cancelled':
            raise UploadCancelled('the request was stopped before its body was sent') from exc
        if body.fully_sent or not body.started:
            # All of it out (the provider may have it), or none of it: a
            # connection that was never made is no upload to shrink.
            raise
        raise UploadFailed(f'the request body broke off after {body.delivered} of {len(data)} bytes '
                           f'({type(exc).__name__})', sent=body.delivered, total=len(data)) from exc


# --------------------------------------------------------------------- images

def _flatten(image):
    """RGB for JPEG. Transparent pixels go to black, which is what the renders'
    empty background already is and what `convert('RGB')` used to leave there."""
    from PIL import Image
    if image.mode in ('RGBA', 'LA') or (image.mode == 'P' and 'transparency' in image.info):
        image = image.convert('RGBA')
        flat = Image.new('RGB', image.size, (0, 0, 0))
        flat.paste(image, mask=image.getchannel('A'))
        return flat
    return image.convert('RGB')


def encode_image(image, *, max_side=MAX_SIDE, quality=QUALITY, lossless=False):
    """A PIL image as model-ready bytes. -> (bytes, mime)

    Downscaled so its longest side is at most `max_side` (never upscaled), then
    JPEG at `quality`, or optimised PNG when `lossless` -- for a picture whose
    small printed numbers ARE the content, such as a numbered piece sheet.
    """
    from PIL import Image
    if max_side and max(image.size) > max_side:
        image = image.copy()
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    if lossless:
        if image.mode not in ('RGB', 'RGBA', 'L', 'LA', 'P'):
            image = image.convert('RGBA')
        image.save(output, format='PNG', optimize=True)
        return output.getvalue(), 'image/png'
    _flatten(image).save(output, format='JPEG', quality=int(quality), optimize=True)
    return output.getvalue(), 'image/jpeg'


def data_url(raw, mime):
    return f'data:{mime};base64,' + base64.b64encode(raw).decode('ascii')


def _smaller_url(url, max_side, quality):
    """A `data:image/...` URL re-encoded smaller, or None when it is not one or would not shrink."""
    if not isinstance(url, str) or not url.startswith('data:image/') or ';base64,' not in url:
        return None
    try:
        raw = base64.b64decode(url.split(',', 1)[1])
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            smaller = data_url(*encode_image(image, max_side=max_side, quality=quality))
    except (ValueError, OSError):
        return None
    return smaller if len(smaller) < len(url) else None


def shrink_messages(messages, *, max_side=SMALL_MAX_SIDE, quality=SMALL_QUALITY):
    """`messages` with every inline picture re-encoded smaller. -> new list, or None when none shrank.

    The input is never modified: the caller's own copy of the conversation
    keeps its pictures, only the retry is sent smaller.
    """
    changed = False
    out = copy.deepcopy(messages)
    for message in out or []:
        content = message.get('content') if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get('type') not in ('image_url', 'input_image'):
                continue
            holder = part.get('image_url')
            url = holder.get('url') if isinstance(holder, dict) else holder
            smaller = _smaller_url(url, max_side, quality)
            if smaller is None:
                continue
            if isinstance(holder, dict):
                holder['url'] = smaller
            else:
                part['image_url'] = smaller
            changed = True
    return out if changed else None


def image_bytes(messages):
    """Characters of inline picture data in `messages` (what the pictures add to the body). -> int"""
    total = 0
    for message in messages or []:
        content = message.get('content') if isinstance(message, dict) else None
        for part in content if isinstance(content, list) else []:
            if isinstance(part, dict) and part.get('type') in ('image_url', 'input_image'):
                holder = part.get('image_url')
                url = holder.get('url') if isinstance(holder, dict) else holder
                total += len(url) if isinstance(url, str) else 0
    return total
