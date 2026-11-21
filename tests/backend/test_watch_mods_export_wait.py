"""Watch-with-mods has to wait for the ISO the exporter actually wrote.

/api/mex/export/start takes a `filename`, but export.py is explicit that it is
"only a suggested save/download name and never identifies bytes on disk": the
bytes land at output/artifacts/<artifactId>.iso and the real path comes back in
the export job's record, /api/jobs/<artifactId>. watch_mods used to POST a filename and
then watch output/<filename> for 15 minutes — a file nobody writes — so even a
perfectly good build ended in "export timed out", and an export that FAILED was
indistinguishable from one still running.

Found by an adversarial review of the worker-auth fix (the auth bug masked this
one: the job never reached the export at all).
"""
import pytest

from core import jobs
from core import state as core_state
from tracker.replays import watch_mods


class _FakeWorker:
    """Answers /api/jobs/<id> with a scripted sequence of job records."""

    def __init__(self, states):
        self.states = list(states)
        self.calls = []

    def api(self, method, route, body=None, timeout=300):
        self.calls.append(route)
        job = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return {"success": True, "job": job}


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch, tmp_path):
    monkeypatch.setattr(watch_mods.time, "sleep", lambda _s: None)
    monkeypatch.setattr(jobs, "_root_override", tmp_path / "jobs")
    monkeypatch.setattr(jobs, "_jobs", {})
    monkeypatch.setattr(core_state, "get_socketio", lambda: None)


def test_returns_the_path_the_exporter_reports(tmp_path):
    iso = tmp_path / "artifacts" / "build_deadbeef.iso"
    iso.parent.mkdir()
    iso.write_bytes(b"iso")
    worker = _FakeWorker([
        {"status": "running", "progress": 0.1},
        {"status": "running", "progress": 0.8},
        {"status": "done", "result": {"path": str(iso)}},
    ])

    assert watch_mods._await_export(worker, "build_deadbeef") == str(iso)
    assert worker.calls[0] == "/api/jobs/build_deadbeef"


def test_a_failed_export_raises_with_its_reason(tmp_path):
    worker = _FakeWorker([{"status": "failed",
                           "error": "Export finished but produced no ISO file"}])

    with pytest.raises(RuntimeError, match="produced no ISO file"):
        watch_mods._await_export(worker, "build_1")


def test_complete_without_bytes_on_disk_is_a_failure(tmp_path):
    """'done' pointing at a path that is not there must not be launched."""
    worker = _FakeWorker([{"status": "done",
                           "result": {"path": str(tmp_path / "gone.iso")}}])

    with pytest.raises(RuntimeError, match="wrote no ISO"):
        watch_mods._await_export(worker, "build_2")


def test_a_build_that_never_finishes_times_out(monkeypatch):
    monkeypatch.setattr(watch_mods, "EXPORT_TIMEOUT_S", 0.1)
    worker = _FakeWorker([{"status": "running", "progress": 0.05}])

    with pytest.raises(RuntimeError, match="never finished building"):
        watch_mods._await_export(worker, "build_3")


def test_progress_reaches_the_job(monkeypatch, tmp_path):
    iso = tmp_path / "build_x.iso"
    iso.write_bytes(b"iso")
    worker = _FakeWorker([
        {"status": "running", "progress": 0.42},
        {"status": "done", "result": {"path": str(iso)}},
    ])
    job = jobs.Job(watch_mods.WATCH_KIND)

    watch_mods._await_export(worker, "build_x", job)
    assert "42%" in job.detail
    assert job.extra["phase"] == "exporting"


def test_a_stop_ends_the_wait_for_the_build():
    worker = _FakeWorker([{"status": "running", "progress": 0.05}])
    job = jobs.Job(watch_mods.WATCH_KIND)
    job.status = "running"
    jobs._jobs[job.id] = job
    jobs.cancel(job.id)

    with pytest.raises(jobs.Cancelled):
        watch_mods._await_export(worker, "build_4", job)


def test_an_export_nucleus_closed_on_is_a_failure():
    worker = _FakeWorker([{"status": "interrupted",
                           "error": "Nucleus closed while this was running."}])

    with pytest.raises(RuntimeError, match="Nucleus closed"):
        watch_mods._await_export(worker, "build_5")
