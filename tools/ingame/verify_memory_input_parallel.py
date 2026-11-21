"""Six isolated native input verification workers and exact baseline comparisons.

The script form of docs/dev/INGAME_TESTING.md's parallel memory-input check: six tools/ingame/verify_memory_input.py
workers on one ISO, each compared with a pipe baseline by devtools/compare_memory_input.py. Run from the repo root.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time

BACKEND=Path(__file__).resolve().parents[2]/'app/backend'
WORKER=Path(__file__).resolve().parent/'verify_memory_input.py'


def save(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')


def run(iso,baseline,output,protected):
    output.mkdir(parents=True,exist_ok=False)
    env=dict(os.environ,NUCLEUS_DOLPHIN_SLOTS='6',NUCLEUS_DOLPHIN_INPUT='memory',
             NUCLEUS_DOLPHIN_CAPTURE='wgc',MELEE_DOLPHIN_LOCK_WAIT='300')
    def worker(index):
        folder=output/f'worker-{index}'
        cmd=[sys.executable,'-B',str(WORKER),'--backend','memory',
             '--background','--deterministic-visuals','--iso',str(iso),'--out',str(folder),
             '--wait-for-dolphin','300']
        for pid in protected:cmd+=['--protected-pid',str(pid)]
        with (output/f'worker-{index}.log').open('w') as log:
            process=subprocess.Popen(cmd,cwd=BACKEND,env=env,stdout=log,stderr=subprocess.STDOUT,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            save(output/f'worker-{index}.process.json',dict(pid=process.pid,parent=os.getpid(),command=cmd))
            code=process.wait()
        comparison=subprocess.run([sys.executable,'devtools/compare_memory_input.py',str(baseline),str(folder)],
                          cwd=BACKEND,env=env,text=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
        (output/f'worker-{index}.comparison.json').write_text(comparison.stdout,encoding='utf-8')
        receipt=(json.loads((folder/'verification.json').read_text()) if (folder/'verification.json').is_file()
                 else dict(success=False,error='worker exited without receipt',exit=code))
        print(index,code,comparison.returncode,flush=True)
        return dict(worker=index,exit=code,comparison_exit=comparison.returncode,receipt=receipt)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures=[pool.submit(worker,i) for i in range(6)]
        # Keep a read-only live slot snapshot, without delaying the workers.
        time.sleep(15)
        status=subprocess.run([sys.executable,'-c',
            'import json,harness_mcp; print(json.dumps(harness_mcp.t_dolphin_status({},print)))'],
            cwd=BACKEND,env=env,capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
        (output/'concurrent-slots.json').write_text(status.stdout,encoding='utf-8')
        rows=[f.result() for f in futures]
    receipts=[r['receipt'] for r in rows]
    complete=all(r['exit']==0 and r['comparison_exit'] in (0,2) and r['receipt']['success'] for r in rows)
    overlap=max(r.get('ready_utc','z') for r in receipts)<min(r.get('finished_utc','') for r in receipts)
    result=dict(workers=rows,all_input_state_checks_passed=complete,
                distinct_dolphins=len({r.get('dolphin_pid') for r in receipts})==6,
                slots=sorted(r.get('lock_slot',-1) for r in receipts),overlap=overlap,
                unique_run_directories=len({r.get('run_directory') for r in receipts})==6,
                visual_review='pending' if any(r['comparison_exit']==2 for r in rows) else 'pixel_identical',
                all_owned_processes_exited=all(r.get('cleanup',{}).get('owned_process_exited') for r in receipts))
    status=subprocess.run([sys.executable,'-c',
            'import json,harness_mcp; print(json.dumps(harness_mcp.t_dolphin_status({},print)))'],
            cwd=BACKEND,env=env,capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    (output/'final-slots.json').write_text(status.stdout,encoding='utf-8')
    save(output/'verification.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--iso',type=Path,required=True)
    p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--protected-pid',type=int,action='append',default=[])
    a=p.parse_args();run(a.iso.resolve(),a.baseline.resolve(),a.output.resolve(),a.protected_pid)
