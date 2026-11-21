"""Stream a temporary archive, then remove it after its last reader closes."""
import logging
import os
import threading
import weakref
from pathlib import Path

from flask import request, send_file

import file_retry

logger = logging.getLogger(__name__)
_lock = threading.RLock()
_readers = {}


def _identity(stat):
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


class _DownloadBody:
    def __init__(self, body, source, key, consume):
        self.body = body
        self.iterator = iter(body)
        self.source = source
        # Werkzeug can skip application_iter.close() when its request-drain
        # read raises on a reset Windows socket. Releasing that abandoned body
        # must perform the same cleanup; the finalizer does not retain self.
        self._finalizer = weakref.finalize(self, _close_download, body, source,
                                           key, consume)

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.iterator)

    def close(self):
        self._finalizer()


def _close_download(body, source, key, consume):
    with _lock:
        try:
            close = getattr(body, 'close', None)
            if close is not None:
                close()
        finally:
            try:
                source.close()
            finally:
                state = _readers[key]
                state[0] -= 1
                state[1] = state[1] or consume
                if not state[0]:
                    del _readers[key]
                    if state[1]:
                        _remove_if_unchanged(*key)


def _remove_if_unchanged(path, identity):
    def remove():
        try:
            # Never unlink a replacement published at the same path. Recheck
            # on retries as well, since an external scanner can briefly lock it.
            if not path.is_symlink() and _identity(path.stat()) == identity:
                path.unlink()
        except FileNotFoundError:
            pass
    try:
        file_retry.retry_locked(remove)
    except OSError:
        logger.exception('Could not remove completed temporary download %s', path)


def send_temporary_zip(path, *, download_name):
    """Return a one-shot full download, with Windows-safe WSGI cleanup.

    after_this_request runs before streaming. Response.call_on_close alone is
    also insufficient: send_file's direct-passthrough GET returns its body
    directly to WSGI. Attach close to that body so normal and aborted transfers
    release the handle before unlinking. Overlapping readers share ownership;
    HEAD requests inspect the archive without consuming it.
    """
    path = Path(path).resolve()
    with _lock:
        source = path.open('rb')
        try:
            stat = os.fstat(source.fileno())
            response = send_file(source, as_attachment=True,
                                 download_name=download_name,
                                 mimetype='application/zip', conditional=False,
                                 etag=False)
            response.content_length = stat.st_size
            response.headers['Cache-Control'] = 'no-store'
            key = (path, _identity(stat))
            body = _DownloadBody(response.response, source, key,
                                 request.method == 'GET')
        except BaseException:
            source.close()
            raise
        _readers.setdefault(key, [0, False])[0] += 1
        response.response = body
        return response
