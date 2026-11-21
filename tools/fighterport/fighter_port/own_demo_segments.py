"""Whole source victories in bounded native demo clips, using otherwise unentered rows.

Only the results screen's three entry rows are eligible. Each segment shares its
boundary pose with the next; a per-fighter process changes the demo state after
animation, before physics/draw. The retail buffers and loaders are unchanged.
"""
from __future__ import annotations
import math
import json

ENTRIES = (0, 2, 5)
UNENTERED = (1, 3, 4, 6, 7, 8)
MAX_WHOLE_ERROR = 0.005
TARGET_INTERVALS = 65


def jobs(job, end, count):
    if (len(job.get('parts') or []) != 1 or job['parts'][0].get('keys') or job.get('loop') or
            type(end) is not int or not 1 < count <= end):
        raise ValueError('Demo continuation requires one whole nonlooping source clip and positive segments')
    width = end // count
    edges = [i * width for i in range(count)] + [end]
    return [dict(job, parts=[dict(job['parts'][0], keys=[[0,a],[b-a,b]])])
        for a,b in zip(edges,edges[1:])]


def count_for(end, available):
    count = max(2, math.ceil(end / TARGET_INTERVALS))
    if count > available + 1:
        raise ValueError(f'Victory needs {count} segments; only {available+1} demo rows are available')
    return count


def prepare(source, source_jobs, rows, settings, rig_hash, capacity, reducer, cache, playback_key=None, log=print):
    """Prebuild entered victories; only capacity failures allocate unused continuation rows."""
    from . import own_bank as bank, own_demo as demo
    assigned = dict(source_jobs)
    prepared, chains, shared = {}, [], {}
    by_index = {r['index']:r for r in rows}
    free = [i for i in UNENTERED if i in by_index and by_index[i]['symbol'] and by_index[i]['size']]

    def make(symbol, job, keep):
        key = bank._key('clip',settings,rig_hash,symbol,job['parts'],bool(job.get('loop')),keep,
                        [source.hash(p['stem']) for p in job['parts']],source.hash(None))
        return demo._cached(cache,key,lambda:bank.make_clip(source,symbol,job,keep,capacity,reducer))

    for index in ENTRIES:
        row = by_index.get(index)
        job = assigned.get(row['symbol']) if row else None
        if not job:
            continue
        travel,_why = bank.job_travel(source,job)
        if travel is None:
            continue
        keep = ''.join(a for a in 'XYZ' if a in travel)
        same = playback_key(job) if playback_key else None
        previous = shared.get(same) if same is not None else None
        signature = bank._key('segments-v1',TARGET_INTERVALS,settings,rig_hash,row['symbol'],job,
                              [source.hash(p['stem']) for p in job['parts']],source.hash(None))
        manifest = cache / (signature + '.segments.json') if cache else None
        count = len(previous['segments']) if previous else (
            json.loads(manifest.read_text())['count'] if manifest and manifest.exists() else None)
        if count is None:
            try:
                prepared[row['symbol']] = make(row['symbol'],job,keep)
                continue
            except ValueError as error:
                # The bank's existing failure API distinguishes this exact refusal from
                # malformed keys, missing clips and codec errors. Those must still fail.
                if not str(error).endswith('The full-duration clip cannot fit this rig.'):
                    raise
            raw = source.clip(job['parts'][0]['stem'])
            count = count_for(int(raw.end),len(free))
        if not previous and count-1 > len(free):
            raise ValueError('No unentered native demo rows remain for the complete victory')
        raw = source.clip(job['parts'][0]['stem'])
        parts = jobs(job,int(raw.end),count)
        destinations = [index] if previous else [index] + free[:count-1]
        log(f"  demo {index}: {job['motion']} uses {count} bounded segments"
            + (f"; shared tail from entry {previous['entry']}" if previous else ''))
        chain = dict(entry=index,source=job['parts'][0]['stem'],source_end=int(raw.end),segments=[])
        for target,part in zip(destinations,parts):
            symbol = by_index[target]['symbol']
            blob,made,hit = make(symbol,part,keep)
            if made['error']['whole'] > MAX_WHOLE_ERROR:
                raise ValueError(f"Victory segment {target}: native game-frame error {made['error']['whole']:.6f} exceeds {MAX_WHOLE_ERROR}")
            first,last = (key[1] for key in part['parts'][0]['keys'])
            made = dict(made,source_first=first,source_last=last,source_motion=job['motion'])
            prepared[symbol] = blob,made,hit
            assigned[symbol] = part
            chain['segments'].append(dict(row=target,frames=made['frames'],source_first=first,source_last=last,
                                           bytes=len(blob),error=made['error']))
            log(f"    row {target}: source {first}..{last}, {len(blob)} bytes, "
                f"error {made['error']['whole']:.5f} whole / {made['error']['between']:.5f} between")
        if previous:
            chain['shared_tail_from'] = previous['entry']
            chain['segments'] += previous['segments'][1:]
        else:
            free = free[count-1:]
            if same is not None:
                shared[same] = chain
        chains.append(chain)
        if manifest:
            manifest.write_text(json.dumps(dict(count=count)))
    return assigned,prepared,chains


def code(mine, report):
    chains = report.get('continuations') or []
    if not chains:
        return mine
    mine = dict(mine) if mine else dict(source=[],frame=[],load=[],provides=[],rows=[],table=[])
    lines = ['static void DemoContinue(GOBJ *gobj)', '{',
             '    FighterData *fd=gobj->userdata;',
             '    if (fd->ftaction != (FtAction *)(fd->ftData->x14)) return;',
             '    switch (fd->action_id)', '    {']
    transitions = {}
    for chain in chains:
        for a,b in zip(chain['segments'],chain['segments'][1:]):
            value = (a['frames'],b['row'])
            if a['row'] in transitions and transitions[a['row']] != value:
                raise ValueError('One native demo state has conflicting continuation destinations')
            transitions[a['row']] = value
    for row,(frames,destination) in sorted(transitions.items()):
        lines += [f"    case {row}:",
                  f"        if (fd->state.frame >= {float(frames)}f)",
                  f"            ActionStateChange(fd->state.frame-{float(frames)}f,1,0,gobj,{destination},0,0);",
                  '        break;']
    lines += ['    }','}']
    mine['source'] = list(mine.get('source') or []) + lines
    mine['load'] = list(mine.get('load') or []) + [
        'if (fd->ftaction == (FtAction *)(fd->ftData->x14)) GObj_AddProc(gobj,DemoContinue,2);']
    mine['provides'] = list(mine.get('provides') or []) + ['full victory animations across bounded native demo clips']
    return mine
