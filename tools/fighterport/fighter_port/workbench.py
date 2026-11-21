"""Shared offline preflight, immutable evidence and bounded candidate selection.

No character imports or native launches. Reports are measurements, never promotion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import copy
import time
from pathlib import Path

from .compat.rig_inventory import build_report
from .motion_contract import read_motion_contract


def fingerprint(path):
    path = Path(path).resolve()
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            size += len(block)
            digest.update(block)
    return {'path': str(path), 'bytes': size, 'sha256': digest.hexdigest()}


def write_new(path, value):
    """Serialize before opening, refuse overwrite, including invalid JSON numbers."""
    payload = json.dumps(value, indent=2, allow_nan=False) + '\n'
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        stream.write(payload)


def check_pins(pins):
    for pin in pins.values():
        if fingerprint(pin['path']) != pin:
            raise ValueError(f"Input or implementation changed: {pin['path']}")


def preflight(costume, pl, aj, motions, *, baseline_costume=None, dol=None, gct=None):
    """One measured bank/rig snapshot and explicitly separated source/target clocks.

    Each motion supplies action, state, motion, source_end and authored_end. File
    facts override no declared expectation: a mismatch is an explicit gate.
    """
    if gct is not None and dol is None:
        raise ValueError('DOL required when supplying runtime patch file')
    paths = dict(costume=costume, pl=pl, aj=aj)
    if baseline_costume is not None:
        paths['baseline_costume'] = baseline_costume
    pins = {k: fingerprint(p) for k, p in paths.items()}
    data = {k: Path(p).read_bytes() for k, p in paths.items()}
    inventory = build_report(**data)
    capacity = dict(status='UNMEASURED', native_ready=False)
    if dol is not None:
        from .engine_capacity import assess
        for name, path in dict(dol=dol, gct=gct).items():
            if path is not None:
                pins[name] = fingerprint(path)
        capacity = assess(Path(dol).read_bytes(), joints=inventory['costume']['joint_count'],
                          dobjs=inventory['costume']['dobj_descriptor_count'],
                          gct=Path(gct).read_bytes() if gct is not None else None)
    clips = []
    seen = set()
    if not motions:
        raise ValueError('Explicit nonempty motion plan required')
    for spec in motions:
        action = spec['action']
        if action in seen:
            raise ValueError('Duplicate motion action')
        seen.add(action)
        for key in ('source_end', 'authored_end'):
            v = spec[key]
            if type(v) not in (int, float) or not math.isfinite(v) or v <= 0:
                raise ValueError(f'Positive finite {key} required')
        if type(action) is not int or not 0 <= action < len(inventory['bank']['rows']):
            raise ValueError('Action outside bank')
        row = inventory['bank']['rows'][action]
        if spec['state'] is None:
            if row['motion'] != spec['motion'] or row['archive_status'] != 'PRESENT':
                raise ValueError('Storage-only motion identity differs')
            con = dict(row, state=None, state_binding='UNMEASURED')
        else:
            con = read_motion_contract(data['pl'], data['aj'], **{k: spec[k] for k in ('action', 'state', 'motion')})
        con.update(flags=row['flags'], flags2=row['flags2'], script_offset=row['script_offset'],
                   source_end=spec['source_end'], authored_end=spec['authored_end'],
                   source_frames_per_authored_frame=spec['source_end'] / spec['authored_end'],
                   archive_duration_matches=con['archive_end'] == spec['authored_end'],
                   native_duration='UNMEASURED', source_semantics='REQUIRES_FRESH_SAMPLER_GATE')
        clips.append(con)
    check_pins(pins)
    return dict(schema='mocap-preflight-v1', status='MEASURED_NOT_ACCEPTED', inputs=pins,
                implementation=fingerprint(__file__), inventory=inventory, motions=clips, engine_capacity=capacity,
                domains={'joints': inventory['costume']['joint_count'],
                         'drawable_descriptors': inventory['costume']['dobj_descriptor_count'],
                         'animation_channels': 'MEASURE_PER_ENCODED_CLIP'},
                native_gates=['live parts and drawable count', 'consumer mapping',
                              'timing and transitions', 'procedural ownership'])


STAGES = ('source', 'transfer', 'exact', 'reduced', 'packed', 'native', 'gameplay')
REPAIRS = {'source': 'fix_source_semantics', 'transfer': 'review_rig_or_transfer',
           'exact': 'joint_space_fit_or_rig_comparison', 'reduced': 'targeted_precision_allocation',
           'packed': 'inspect_codec_readback', 'native': 'inspect_runtime_ownership_and_timing',
           'gameplay': 'inspect_state_and_script_contract'}

def diagnose(stages):
    """Locate the first observed failure; missing predecessors block attribution."""
    for name in STAGES:
        value = stages.get(name, 'UNMEASURED')
        if value not in ('PASS', 'FAIL', 'UNMEASURED'):
            raise ValueError(f'Invalid stage verdict {name}: {value}')
        if value == 'UNMEASURED':
            return dict(stage=name, status='UNMEASURED', next='measure_' + name)
        if value == 'FAIL':
            return dict(stage=name, status='MEASURED_FAILURE', next=REPAIRS[name],
                        limit='Finite measured candidate failure, not an impossibility result.')
    return dict(stage='gameplay', status='ALL_DECLARED_STAGES_PASS', next='review_evidence')


def candidate_score(metrics, limits):
    if not limits or set(metrics) != set(limits):
        raise ValueError('Every candidate must measure exactly the same declared metrics')
    for key in limits:
        for label, value in (('metric', metrics[key]), ('limit', limits[key])):
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (label == 'limit' and value == 0):
                raise ValueError(f'Invalid {label}: {key}')
    return max(metrics[k] / limits[k] for k in limits)


def stage_errors(times, source, authored, packed, skin, *, limits, parent, predecessors=None, authored_stage='exact'):
    """Measured three-way diagnosis; missing predecessor evidence stays missing."""
    from .animation_diagnostics import measure_stages
    if authored_stage not in ('exact','reduced'):
        raise ValueError('Authored stage must be exact or reduced')
    stages = dict(predecessors or {})
    if set(stages)-set(STAGES[:STAGES.index(authored_stage)]):
        raise ValueError('Only predecessor verdicts may be supplied')
    report = measure_stages(times,source,authored,packed,skin,limits=limits,parent=parent)
    stages[authored_stage] = 'PASS' if report['comparisons']['authored_vs_source']['passed'] else 'FAIL'
    # No reduced control was measured when comparing an exact authored input.
    # Keep that predecessor unmeasured rather than assuming its result.
    stages['packed'] = 'PASS' if report['comparisons']['packed_vs_authored']['passed'] else 'FAIL'
    report.update(stages=stages, first_failure=diagnose(stages))
    return report


def run_candidates(candidates, evaluate, *, limits, byte_budget, max_attempts, domain,
                   monotonic=False, max_seconds=900, generator=None, baseline=None, clock=time.monotonic,
                   tie_break='bytes'):
    """Evaluate a bounded ordered ladder; compare actual encoded bytes and all gates.

    evaluate(spec) returns blob: bytes, metrics: dict, domain: same immutable ID.
    Exceptions are retained and do not create an incumbent. Stop on a full pass.
    Runtime corrections must be separately supplied candidates, never inferred.
    Monotonic True/'gates' forbids pass-to-fail flips; 'metrics' forbids any
    metric increase. Either requires an evaluated baseline (blob/metrics/domain,
    optional spec/protected_state), kept at incumbent -1 without an attempt.
    Deadline stops new work and late results cannot replace the incumbent.
    The default breaks equal worst-error scores by bytes. Opt-in 'violations'
    first compares remaining failed-gate ratios, largest to smallest, so an
    unrelated tied maximum does not discard progress on another failing gate.
    Capacity, worst-error priority, monotonic and protected rules still apply.
    """
    if type(byte_budget) is not int or byte_budget <= 0 or type(max_attempts) is not int or max_attempts <= 0:
        raise ValueError('Positive integer byte and attempt budgets required')
    if not isinstance(domain, str) or not domain:
        raise ValueError('Bound sample/reference domain identity required')
    if monotonic not in (False,True,'gates','metrics') or type(max_seconds) not in (int,float) or not math.isfinite(max_seconds) or max_seconds<=0:
        raise ValueError('Known monotonic policy and positive elapsed budget required')
    if monotonic and baseline is None:raise ValueError('Monotonic repair requires an evaluated baseline')
    if tie_break not in ('bytes','violations'):raise ValueError('Known tie-break policy required')
    if (candidates is None) == (generator is None):
        raise ValueError('Supply either candidates or an incumbent-aware generator')
    candidate_score({k:0. for k in limits},limits)
    limits=copy.deepcopy(limits)
    def candidate_order(size,score,metrics):
        secondary=(tuple(sorted((max(1.,metrics[k]/limits[k]) for k in limits),reverse=True)),) if tie_break=='violations' else ()
        return (size>byte_budget,score,*secondary,size)
    rows, best, rank, incumbent = [], None, None, None
    if baseline is not None:
        baseline=copy.deepcopy(baseline)
        if baseline['domain']!=domain or not isinstance(baseline['blob'],bytes) or not baseline['blob']:
            raise ValueError('Baseline requires actual encoded bytes on the same domain')
        score=candidate_score(baseline['metrics'],limits);size=len(baseline['blob'])
        incumbent=dict(attempt=-1,spec=baseline.get('spec'),metrics=baseline['metrics'],bytes=size,
                       sha256=hashlib.sha256(baseline['blob']).hexdigest(),normalized_error=score,domain=domain,
                       protected_state=baseline.get('protected_state',{}),status='PASS' if size<=byte_budget and score<=1 else 'FAIL')
        if not isinstance(incumbent['protected_state'],dict) or any(not isinstance(k,str) or not isinstance(v,str) or not v for k,v in incumbent['protected_state'].items()):
            raise ValueError('Named baseline protected fingerprints required')
        best,rank=-1,candidate_order(size,score,baseline['metrics'])
    baseline_row=copy.deepcopy(incumbent)
    iterator=iter(candidates) if candidates is not None else None
    start=clock();stop='MAX_ATTEMPTS'
    for i in range(max_attempts):
        if incumbent is not None and incumbent['status']=='PASS':
            stop='GATES_PASS';break
        if clock()-start>=max_seconds:
            stop='TIME_BUDGET';break
        if generator is not None:
            spec=generator(copy.deepcopy(incumbent),i)
            if spec is None:
                stop='NO_MORE_CANDIDATES';break
        else:
            try:spec=next(iterator)
            except StopIteration:
                stop='NO_MORE_CANDIDATES';break
        if clock()-start>=max_seconds:
            stop='TIME_BUDGET';break
        row = dict(attempt=i, spec=copy.deepcopy(spec),accepted=False)
        try:
            value = copy.deepcopy(evaluate(copy.deepcopy(spec)))
            if value['domain'] != domain:
                raise ValueError('Candidate changed comparison domain')
            blob = value['blob']
            if not isinstance(blob, bytes) or not blob:
                raise ValueError('Actual nonempty encoded bytes required')
            score = candidate_score(value['metrics'], limits)
            fits = len(blob) <= byte_budget
            row.update(status='PASS' if fits and score <= 1 else 'FAIL', metrics=value['metrics'],
                       bytes=len(blob), sha256=hashlib.sha256(blob).hexdigest(), normalized_error=score,
                       domain=domain)
            regressed=[]
            if monotonic and incumbent is not None:
                regressed=[k for k in limits if (value['metrics'][k]>incumbent['metrics'][k] if monotonic=='metrics'
                           else incumbent['metrics'][k]<=limits[k]<value['metrics'][k])]
            protected=value.get('protected_state',{})
            if not isinstance(protected,dict) or any(not isinstance(k,str) or not isinstance(v,str) or not v for k,v in protected.items()):
                raise ValueError('Named protected interval fingerprints required')
            if protected and baseline is None:raise ValueError('Protected repair requires an evaluated baseline')
            if incumbent is not None:
                before=incumbent.get('protected_state',{})
                if set(before)!=set(protected):raise ValueError('Protected interval domain changed')
                changed=[k for k in before if before[k]!=protected[k]]
                checks=value.get('protected_rechecks',{})
                for k in changed:
                    check=checks.get(k,{})
                    if check.get('before')!=before[k] or check.get('after')!=protected[k] or check.get('passed') is not True or check.get('domain')!=domain:
                        raise ValueError('Changed protected interval requires a bound full recheck')
            late=clock()-start>=max_seconds
            row.update(protected_state=protected,protected_rechecks=value.get('protected_rechecks',{}),
                       regressed_metrics=regressed,deadline_exceeded=late)
            # A candidate that fits the budget outranks one that does not; within
            # that class preserve the best measured worst normalized error.
            candidate_rank = candidate_order(len(blob),score,value['metrics'])
            if not late and not regressed and (rank is None or candidate_rank < rank):
                best, rank = i, candidate_rank;row['accepted']=True;incumbent=row
        except Exception as exc:
            row.update(status='ERROR', error=f'{type(exc).__name__}: {exc}')
        rows.append(row)
        if row['status'] == 'PASS' and row['accepted']:
            stop='GATES_PASS';break
        if clock()-start>=max_seconds:
            stop='TIME_BUDGET';break
    if not rows and incumbent is None and stop!='TIME_BUDGET':
        raise ValueError('No candidates supplied')
    return dict(schema='mocap-candidate-search-v1', status='OFFLINE_PASS' if incumbent is not None and incumbent['status']=='PASS' else 'BOUNDED_SEARCH_EXHAUSTED',
                attempts=rows, incumbent=best, byte_budget=byte_budget, limits=limits, domain=domain,
                baseline=baseline_row,tie_break=tie_break,
                monotonic=monotonic,max_seconds=max_seconds,elapsed_seconds=clock()-start,stop=stop,
                runtime_accepted=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('costume', 'pl', 'aj', 'motions', 'out'):
        parser.add_argument('--' + key, type=Path, required=True)
    parser.add_argument('--baseline-costume', type=Path)
    parser.add_argument('--dol', type=Path)
    parser.add_argument('--gct', type=Path)
    args = parser.parse_args(argv)
    if args.out.exists():
        raise ValueError('Refusing to overwrite preflight')
    plan_pin = fingerprint(args.motions)
    report = preflight(args.costume, args.pl, args.aj, json.loads(args.motions.read_text()), baseline_costume=args.baseline_costume,
                       dol=args.dol, gct=args.gct)
    check_pins({'plan': plan_pin})
    report['inputs']['motion_plan'] = plan_pin
    write_new(args.out, report)
    print(json.dumps({'status': report['status'], 'domains': report['domains'], 'motions': len(report['motions'])}))


if __name__ == '__main__':
    main()
