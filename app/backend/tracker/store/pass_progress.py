"""Counters a long pass reports to its job (core/jobs.py), twice a second at most.

A scan counts thousands of files, and every ``job.progress`` is a socket event
carrying the whole record. The counters ride in the record's ``extra``; the
pass returns the final ones as its result.
"""
import time

_EVERY_S = 0.5


class PassProgress:
    def __init__(self, job, unit, **counts):
        self.job = job
        self.unit = unit
        self.counts = {"total": 0, "done": 0, **counts}
        self._sent = 0.0

    def add(self, **deltas):
        for key, n in deltas.items():
            self.counts[key] = self.counts.get(key, 0) + n

    def report(self, force=False, **values):
        """Set ``values`` and send the counters, unless sent under 0.5 s ago."""
        self.counts.update(values)
        now = time.monotonic()
        if not force and now - self._sent < _EVERY_S:
            return
        self._sent = now
        total, done = self.counts["total"], self.counts["done"]
        self.job.progress(done / total if total else None,
                          f"{done:,} / {total:,} {self.unit}" if total else None,
                          **self.counts)
