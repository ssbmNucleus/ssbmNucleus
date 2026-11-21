"""Deadline-aware line reads for owned subprocess pipes."""

import queue
import threading


_EOF = object()


class DeadlineLineReader:
    """Move blocking pipe reads to one daemon and expose bounded queue reads."""

    def __init__(self, pipe):
        self._pipe = pipe
        self._lines = queue.Queue()
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self):
        try:
            while True:
                line = self._pipe.readline()
                if not line:
                    self._lines.put(_EOF)
                    return
                self._lines.put(line)
        except Exception as exc:
            self._lines.put(exc)

    def readline(self, timeout):
        """Return a line, '' on EOF, or None when the deadline slice expires."""
        try:
            item = self._lines.get(timeout=max(0, timeout))
        except queue.Empty:
            return None
        if item is _EOF:
            return ''
        if isinstance(item, Exception):
            raise item
        return item
