"""Close only a retained harness child after checking its identity and ancestry."""
import os
from pathlib import Path


def _identity(pid):
    import psutil
    process=psutil.Process(pid)
    return dict(pid=process.pid,parent=process.ppid(),exe=process.exe(),created=process.create_time()), {
        p.pid for p in psutil.Process().parents()}


def close_owned_session(session, *, protected_pids=(12348,30400,16316)):
    boot=session.boot
    proc=boot.proc if boot else None
    record=dict(owned_process=None)
    if proc is not None and proc.poll() is None:
        identity,ancestors=_identity(proc.pid)
        protected=set(protected_pids)|ancestors|{os.getpid(),12348}
        if (identity['pid']!=proc.pid or boot.pid!=proc.pid or proc.pid in protected or
                identity['parent']!=os.getpid() or
                Path(identity['exe']).resolve()!=Path(boot.exe).resolve()):
            raise RuntimeError('Owned process identity failed; refusing session cleanup')
        record['owned_process']=dict(identity,python=os.getpid())
    # The session closes pipes and uses the retained Popen handle. It does not
    # enumerate processes or kill a tree. Keep the run directory and logs.
    record['run_directory']=session.close(keep=True)
    record['owned_process_exited']=proc is None or proc.poll() is not None
    if not record['owned_process_exited']:
        raise RuntimeError('Owned emulator did not exit; run directory retained')
    return record


def persist_and_close(session, save, artifacts):
    """Attempt retained outputs; always close the verified child if a writer fails.

    Caller supplies its existing overwrite/immutable file policy. A write error
    still propagates after cleanup, so missing evidence cannot become success.
    """
    try:
        for name,value in artifacts.items():save(name,value)
    finally:
        cleanup=close_owned_session(session)
        save('cleanup.json',cleanup)
        if cleanup['owned_process'] is not None:save('owned-process.json',cleanup['owned_process'])
    return cleanup
