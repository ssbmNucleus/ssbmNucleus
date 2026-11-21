"""Model-request bodies on a slow uplink (shared.aiengine.model_upload).

A tester's second look and one whole chat turn failed seven OpenRouter
requests with `ConnectionError: ('Connection aborted.', TimeoutError('The
write operation timed out'))`, each after ~10.4 s: urllib3 sends a body under
the CONNECT timeout, in one write, so every request had ten seconds to upload
all of it, and the look's pages went up as ~5 MB of PNG. Everything here is
offline: a local HTTP server, and a socket that sends at a set rate.
"""
import base64
import http.server
import io
import json
import threading
import time

import numpy as np
import pytest
import requests
import urllib3.connection
from PIL import Image, ImageDraw, ImageFilter

from shared.aiengine import model_upload
from randall.assistant.tasks import coordinator, stage_journal


def render(path=None, size=(1560, 1156), seed=0):
    """A review-page stand-in: smooth shaded shapes over a dark gradient, with
    the fine noise real renders carry (it is what makes their PNGs big)."""
    rng = np.random.default_rng(seed)
    w, h = size
    y = np.mgrid[0:h, 0:w][0]
    image = Image.fromarray(np.stack([30 + 20 * y / h, 33 + 20 * y / h, 40 + 25 * y / h], -1).astype('uint8'))
    draw = ImageDraw.Draw(image)
    for _ in range(6):
        cx, cy, r = rng.integers(100, w - 100), rng.integers(100, h - 100), rng.integers(60, 200)
        draw.ellipse((cx - r, cy - r * 1.5, cx + r, cy + r * 1.5), fill=tuple(int(v) for v in rng.integers(80, 255, 3)))
    image = image.filter(ImageFilter.GaussianBlur(3))
    pixels = np.asarray(image).astype(int) + rng.integers(-4, 5, (h, w, 3))
    image = Image.fromarray(np.clip(pixels, 0, 255).astype('uint8'))
    if path is not None:
        image.save(path)
    return image


def decoded(url):
    head, data = url.split(',', 1)
    return head, Image.open(io.BytesIO(base64.b64decode(data)))


def image_data_url(path, **options):
    """A picture file as the data: URL a model request carries."""
    with Image.open(path) as image:
        image.load()
        return model_upload.data_url(*model_upload.encode_image(image, **options))


def urls(payload):
    return [part['image_url']['url'] for message in payload['messages'] if isinstance(message['content'], list)
            for part in message['content'] if part.get('type') == 'image_url']


# --------------------------------------------------------------- payload size

def test_a_review_page_goes_up_as_a_downscaled_jpeg_a_fraction_of_its_png(tmp_path):
    page = tmp_path / 'page.png'
    render(page)
    url = image_data_url(page)
    head, image = decoded(url)
    assert head == 'data:image/jpeg;base64'
    assert max(image.size) == model_upload.MAX_SIDE and image.size[0] / image.size[1] == pytest.approx(1560 / 1156, rel=.01)
    assert len(url) < page.stat().st_size / 10


def test_a_small_picture_is_never_upscaled_and_lossless_stays_pixel_exact(tmp_path):
    sheet = tmp_path / 'sheet.png'
    image = Image.new('RGB', (300, 120), (240, 240, 240))
    ImageDraw.Draw(image).text((10, 10), '12 13 14', fill=(0, 0, 0))
    image.save(sheet)
    head, out = decoded(image_data_url(sheet, lossless=True, max_side=None))
    assert head == 'data:image/png;base64' and out.size == (300, 120)
    assert np.array_equal(np.asarray(out.convert('RGB')), np.asarray(image))
    assert decoded(image_data_url(sheet))[1].size == (300, 120)


def test_a_transparent_render_is_flattened_onto_black_for_jpeg():
    image = Image.new('RGBA', (64, 64), (255, 255, 255, 0))
    ImageDraw.Draw(image).rectangle((16, 16, 48, 48), fill=(200, 40, 40, 255))
    raw, mime = model_upload.encode_image(image)
    out = Image.open(io.BytesIO(raw)).convert('RGB')
    assert mime == 'image/jpeg' and max(out.getpixel((2, 2))) < 12 and out.getpixel((32, 32))[0] > 180


def test_shrinking_re_encodes_every_picture_smaller_and_leaves_the_original_alone(tmp_path):
    page = tmp_path / 'page.png'
    render(page)
    payload = {'model': 'm', 'messages': [
        {'role': 'system', 'content': 'judge it'},
        {'role': 'user', 'content': [{'type': 'text', 'text': 'Fighter: Fox.'},
                                     {'type': 'image_url', 'image_url': {'url': image_data_url(page)}},
                                     {'type': 'image_url', 'image_url': {'url': image_data_url(page)}}]}]}
    before = json.dumps(payload)
    smaller = {**payload, 'messages': model_upload.shrink_messages(payload['messages'])}
    assert json.dumps(payload) == before
    assert smaller['messages'][0] == payload['messages'][0]
    assert smaller['messages'][1]['content'][0] == payload['messages'][1]['content'][0]
    assert model_upload.image_bytes(smaller['messages']) < model_upload.image_bytes(payload['messages']) / 2
    assert all(max(decoded(u)[1].size) <= model_upload.SMALL_MAX_SIDE for u in urls(smaller))
    assert model_upload.shrink_messages([{'role': 'user', 'content': 'text only'}]) is None


# ------------------------------------------------------------ the upload itself

class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True


class _Handler(http.server.BaseHTTPRequestHandler):
    """Records every POST, whole or cut short. `server.mode`: 'ok' answers;
    'redirect' answers /start with a 307 to /next; 'drop' reads the whole body
    and hangs up without answering; 'slow' answers after `server.delay` s."""
    timeout = 3

    def do_POST(self):
        length = int(self.headers['Content-Length'])
        try:
            body = self.rfile.read(length)
        except OSError:
            body = b''
        self.server.seen.append({'length': length, 'chunked': self.headers.get('Transfer-Encoding'),
                                 'type': self.headers.get('Content-Type'), 'body': body, 'path': self.path})
        mode = self.server.mode
        if len(body) < length:
            return
        if mode == 'drop':
            self.close_connection = True
            return
        if mode == 'redirect' and self.path.endswith('/start'):
            self.send_response(307)
            self.send_header('Location', '/next')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if mode == 'slow':
            time.sleep(self.server.delay)
        out = json.dumps({'received': len(body)}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = _Server(('127.0.0.1', 0), _Handler)
    httpd.seen, httpd.mode, httpd.delay = [], 'ok', 0.
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd, f'http://127.0.0.1:{httpd.server_address[1]}/v1/chat/completions'
    httpd.shutdown()
    httpd.server_close()


class _Uplink:
    """A socket that sends at `rate` bytes/s, with CPython's `sendall` rule:
    the socket timeout bounds the WHOLE call, however much it is given.
    `breaks(data)` -> True makes that write fail as a reset connection."""

    def __init__(self, sock, setting):
        self._sock, self._setting = sock, setting

    def sendall(self, data):
        if self._setting.get('breaks') and self._setting['breaks'](bytes(data)):
            raise ConnectionResetError('An existing connection was forcibly closed by the remote host')
        need = len(data) / self._setting['rate']
        limit = self._sock.gettimeout()
        if limit is not None and need > limit:
            time.sleep(limit)
            raise TimeoutError('The write operation timed out')
        time.sleep(need)
        return self._sock.sendall(data)

    def __getattr__(self, name):
        return getattr(self._sock, name)


@pytest.fixture
def slow_uplink(monkeypatch):
    """Every new HTTP connection uploads at the rate set on the returned dict
    (after `connect_delay` s of connecting, and failing a write `breaks` names)."""
    setting = {'rate': 200_000, 'connect_delay': 0., 'breaks': None}
    connect = urllib3.connection.HTTPConnection.connect

    def throttled(self):
        time.sleep(setting['connect_delay'])
        connect(self)
        self.sock = _Uplink(self.sock, setting)
    monkeypatch.setattr(urllib3.connection.HTTPConnection, 'connect', throttled)
    return setting


def test_the_body_goes_up_whole_with_a_content_length_and_not_chunked(server):
    httpd, url = server
    payload = {'model': 'm', 'messages': [{'role': 'user', 'content': 'x' * 100_000}]}
    response = model_upload.post_json(url, payload, headers={'X-Title': 't'}, timeout=(5, 5))
    assert response.json() == {'received': len(model_upload.encode_json(payload))}
    seen = httpd.seen[0]
    assert seen['chunked'] is None and seen['type'] == 'application/json'
    assert json.loads(seen['body']) == payload


def test_a_slow_uplink_fails_one_timed_write_and_gets_through_in_blocks(server, slow_uplink):
    """The tester's failure, reproduced at a tenth of the scale: 0.4 MB at
    200 KB/s is two seconds of upload against a half-second connect timeout."""
    httpd, url = server
    payload = {'model': 'm', 'messages': [{'role': 'user', 'content': 'x' * 400_000}]}
    with pytest.raises(requests.ConnectionError, match='The write operation timed out'):
        requests.post(url, json=payload, timeout=(.5, 5))
    started = time.monotonic()
    response = model_upload.post_json(url, payload, timeout=(.5, 5))
    assert response.json() == {'received': len(model_upload.encode_json(payload))}
    assert 1.5 < time.monotonic() - started < 6


def test_an_upload_that_stalls_is_an_upload_failure_not_a_hang(server, slow_uplink):
    httpd, url = server
    slow_uplink['rate'] = 2_000          # one 16 KB block takes eight seconds
    started = time.monotonic()
    with pytest.raises(model_upload.UploadFailed) as caught:
        model_upload.post_json(url, {'content': 'x' * 100_000}, timeout=(.5, 5))
    assert time.monotonic() - started < 3
    assert isinstance(caught.value, requests.ConnectionError)
    assert caught.value.total > 100_000 and caught.value.sent < caught.value.total
    assert coordinator.classify(caught.value) == 'transient'


def test_the_upload_never_outlives_the_callers_deadline(server, slow_uplink):
    httpd, url = server
    slow_uplink['rate'] = 50_000         # each block makes progress, the whole body would take 8 s
    started = time.monotonic()
    with pytest.raises(model_upload.UploadFailed):
        model_upload.post_json(url, {'content': 'x' * 400_000}, timeout=(.5, 5), deadline=started + 1.)
    assert time.monotonic() - started < 2.5


def test_the_upload_budget_scales_with_the_body():
    assert model_upload.upload_budget(0) == model_upload.UPLOAD_BASE_S
    assert model_upload.upload_budget(1_000_000) > model_upload.upload_budget(100_000) + 30


# ------------------------------------------------------ one retry, smaller body

def test_a_chat_round_whose_upload_broke_is_resent_once_with_smaller_pictures(tmp_path, monkeypatch):
    from randall.assistant.tasks import contracts, events
    task = coordinator.TaskContext(contracts.TaskResult(task_id='upload-test', workflow='chat'),
                                   persist=False, bus=events.Bus())
    for _mod in (coordinator, stage_journal):
        monkeypatch.setattr(_mod, 'current', lambda: task)
    monkeypatch.setattr(coordinator, 'backoff', lambda attempt: 0.)
    monkeypatch.setattr(task, 'record_span', lambda span, **kw: None)
    page = tmp_path / 'page.png'
    render(page)
    messages = [{'role': 'system', 'content': 'prompt'},
                {'role': 'user', 'content': [{'type': 'image_url',
                                              'image_url': {'url': image_data_url(page, max_side=1024)}}]}]
    original = json.dumps(messages)
    sent = []

    def provider(messages, schemas, key, cancelled):
        sent.append(model_upload.image_bytes(messages))
        if len(sent) < 3:
            raise model_upload.UploadFailed('the request body broke off', sent=1, total=2)
        yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'done'}}

    events_out = list(coordinator.traced_provider(provider, role='main')(messages, [], 'k', threading.Event()))
    assert events_out[-1]['message']['content'] == 'done'
    assert sent[1] < sent[0] / 2 and sent[2] == sent[1]
    assert json.dumps(messages) == original, "the conversation's own pictures are untouched"


# ------------------------------------------ review of 2577a8af: what a send may claim

def _payload(nbytes):
    """A payload whose JSON body is exactly `nbytes` long."""
    overhead = len(model_upload.encode_json({'content': ''}))
    return {'content': 'x' * (nbytes - overhead)}


def test_a_body_whose_last_write_ends_past_the_budget_is_delivered_not_failed(server, slow_uplink, monkeypatch):
    """The provider had the whole request; raising then made the coordinator
    send it again -- a second charge, and the first with no generation id."""
    httpd, url = server
    monkeypatch.setattr(model_upload, 'UPLOAD_BASE_S', .8)
    monkeypatch.setattr(model_upload, 'MIN_UPLOAD_BPS', 10 ** 12)
    slow_uplink['rate'] = 50_000          # three blocks: handed out at 0, .33 and .66 s, done at ~.97 s
    payload = _payload(3 * 16_384 - 1_000)
    response = model_upload.post_json(url, payload, timeout=(5, 5))
    assert response.json() == {'received': len(model_upload.encode_json(payload))}
    assert len(httpd.seen) == 1


def test_the_deadline_counts_from_the_call_including_the_connect(server, slow_uplink):
    httpd, url = server
    slow_uplink['connect_delay'] = .6
    started = time.monotonic()
    with pytest.raises(requests.ConnectionError):
        model_upload.post_json(url, _payload(40_000), timeout=(5, 5), deadline=started + .4)
    assert time.monotonic() - started < 1.5
    time.sleep(.2)
    assert all(len(seen['body']) < seen['length'] for seen in httpd.seen), 'no complete request went out'


def test_the_wait_for_the_answer_is_clamped_to_the_deadline(server):
    httpd, url = server
    httpd.mode, httpd.delay = 'slow', 2.
    started = time.monotonic()
    with pytest.raises(requests.RequestException):
        model_upload.post_json(url, _payload(1_000), timeout=(5, 5), deadline=started + .5)
    assert time.monotonic() - started < 1.2


def test_a_stop_between_blocks_never_completes_the_body(server, slow_uplink):
    httpd, url = server
    slow_uplink['rate'] = 50_000          # 400 KB would take eight seconds
    stop = threading.Event()
    threading.Timer(.3, stop.set).start()
    started = time.monotonic()
    with pytest.raises(model_upload.UploadCancelled) as caught:
        model_upload.post_json(url, _payload(400_000), timeout=(5, 5), cancelled=stop)
    assert time.monotonic() - started < 1.5
    assert not isinstance(caught.value, requests.ConnectionError)
    assert coordinator.classify(caught.value) != 'transient', 'a Stop is not retried'
    time.sleep(.2)
    assert all(len(seen['body']) < seen['length'] for seen in httpd.seen)
    with pytest.raises(model_upload.UploadCancelled):
        model_upload.post_json(url, _payload(1_000), cancelled=lambda: True)


def test_stop_during_a_chat_upload_never_hands_the_model_a_whole_request(monkeypatch):
    from randall.assistant import engine, main_model
    stop = threading.Event()
    posts = []

    class Stream:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def iter_lines(self, chunk_size=1):
            yield b'data: ' + json.dumps({'choices': [{'delta': {'content': 'hi'}, 'finish_reason': 'stop'}]}).encode()
            yield b'data: [DONE]'

    def post(url, data=None, **kw):
        # What urllib3 does with the body: a block at a time, the next asked
        # for once the last is out. The user presses Stop after the first.
        try:
            data.read(16_384)
            stop.set()
            while data.read(16_384):
                pass
        except OSError as exc:
            posts.append('incomplete')
            raise requests.ConnectionError(('Connection aborted.', exc))
        posts.append('complete')
        return Stream()

    monkeypatch.setattr(main_model.requests, 'post', post)
    messages = [{'role': 'user', 'content': 'x' * 50_000}]
    assert list(main_model._provider(messages, [], 'k', stop)) == []
    assert posts == ['incomplete']


def test_a_redirect_is_not_followed_with_a_spent_body(server):
    httpd, url = server
    httpd.mode = 'redirect'
    start = url.rsplit('/', 3)[0] + '/start'
    response = model_upload.post_json(start, _payload(5_000), timeout=(2, 2))
    assert response.status_code == 307
    assert [seen['path'] for seen in httpd.seen] == ['/start']


@pytest.mark.parametrize('size,breaks_at', [(3 * 16_384 - 1_000, 2 * 16_384), (5_000, 0)])
def test_a_failed_last_write_is_an_upload_failure(server, slow_uplink, size, breaks_at):
    """The last block (or the only one) failing to go out is still a body that
    did not arrive -- the shrinking retry is for exactly this."""
    httpd, url = server
    payload = _payload(size)
    last = model_upload.encode_json(payload)[breaks_at:]
    slow_uplink['breaks'] = lambda data: data == last
    with pytest.raises(model_upload.UploadFailed) as caught:
        model_upload.post_json(url, payload, timeout=(5, 5))
    assert caught.value.sent == breaks_at and caught.value.total == size


def test_a_connection_lost_after_the_whole_body_is_possibly_charged(server):
    """The provider may be running (and billing) the request: not an upload
    failure, and the attempt's reservation stays booked as an unknown charge."""
    from randall.assistant.tasks import contracts, events
    httpd, url = server
    httpd.mode = 'drop'
    task = coordinator.TaskContext(contracts.TaskResult(task_id='drop-test', workflow='model_import'),
                                   persist=False, bus=events.Bus())
    with pytest.raises(requests.ConnectionError) as caught:
        coordinator.run_model_request('vision', lambda span: model_upload.post_json(url, _payload(40_000),
                                                                                    timeout=(5, 5)),
                                      attempts=1, task=task)
    assert not isinstance(caught.value, model_upload.UploadFailed)
    assert httpd.seen[0]['length'] == len(httpd.seen[0]['body'])
    assert task.costs.unknown_requests == 1 and task.costs.pending_usd > 0
