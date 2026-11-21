"""Index retained evidence without turning historical status prose into acceptance.

Coverage requires explicit, hash-bound claims. Receipt discovery alone never
increases coverage. Malformed files and absent levels remain visible.
"""
from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path

from .workbench import write_new, fingerprint

LEVELS = ('source', 'encoded', 'offline', 'native', 'gameplay')


def read_json(data):
    def pairs(items):
        result = {}
        for key,value in items:
            if key in result: raise ValueError(f'Duplicate JSON key: {key}')
            result[key]=value
        return result
    def bad(value): raise ValueError(f'Nonfinite JSON number: {value}')
    return json.loads(data, object_pairs_hook=pairs, parse_constant=bad)


def catalog(root):
    root=Path(root).resolve(); rows=[]
    if not root.is_dir(): raise ValueError('Evidence root must exist')
    for path in sorted(root.rglob('*receipt*.json')):
        if not path.resolve().is_relative_to(root): continue
        row=dict(path=str(path.relative_to(root)))
        try:
            data=path.read_bytes()
            row.update(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
            value=read_json(data)
            if not isinstance(value,dict): raise ValueError('Receipt is not an object')
            # Exact recorded text is searchable; no substring such as ACCEPTED
            # can accidentally turn RUNTIME_UNACCEPTED into a pass.
            status=value.get('status')
            row.update(status=status if isinstance(status,str) else 'NO_TOP_LEVEL_STATUS',
                       schema=value.get('schema'), keys=sorted(value), indexed=True)
        except (OSError, ValueError, TypeError) as exc:
            row.update(indexed=False,error=f'{type(exc).__name__}: {exc}')
        rows.append(row)
    return dict(schema='mocap-evidence-catalog-v1',root=str(root),files=rows,
                total=len(rows),errors=sum(not r['indexed'] for r in rows),
                recorded_status_counts=dict(Counter(r['status'] for r in rows if r['indexed'])),
                scope='Discovery only; historical statuses are not validated acceptance or coverage.')


def coverage(actions, claims, root):
    """Hash and exact-value validation of explicitly reviewed per-action claims.

    claim: action, level, path (under root), sha256, verdict_path (list of keys),
    expected (True or an exact string), subject_path and subject (artifact identity).
    No pass is inherited from a lower or higher evidence level.
    """
    if not actions or any(type(a) is not int or a<0 for a in actions) or len(set(actions))!=len(actions):
        raise ValueError('Unique nonnegative action indices required')
    root=Path(root).resolve()
    rows={a:dict(action=a,levels={k:'UNMEASURED' for k in LEVELS},evidence={}) for a in actions}
    seen=set()
    for claim in claims:
        a,level=claim['action'],claim['level']
        if a not in rows or level not in LEVELS or (a,level) in seen:
            raise ValueError('Unknown or duplicate coverage claim')
        seen.add((a,level))
        target=(root/claim['path']).resolve()
        if not target.is_relative_to(root): raise ValueError('Evidence path outside root')
        record=dict(path=claim['path'])
        try:
            pin=fingerprint(target)
            if pin['sha256']!=claim['sha256']: raise ValueError('Evidence hash differs')
            payload=target.read_bytes()
            if hashlib.sha256(payload).hexdigest()!=pin['sha256']:
                raise ValueError('Evidence changed while being read')
            value=read_json(payload)
            def at(keys):
                if not isinstance(keys,list) or not keys: raise ValueError('Explicit nonempty JSON key path required')
                result=value
                for key in keys: result=result[key]
                return result
            expected=claim['expected']
            if expected is not True and expected not in ('PASS','OFFLINE_PASS','VERIFIED'):
                raise ValueError('Explicit positive verdict required')
            actual=at(claim['verdict_path'])
            if type(actual) is not type(expected) or actual!=expected: raise ValueError('Exact verdict differs')
            actual_subject=at(claim['subject_path'])
            if type(actual_subject) is not type(claim['subject']) or actual_subject!=claim['subject']:
                raise ValueError('Evidence subject differs')
            record.update(sha256=pin['sha256'],status='VALIDATED_CLAIM')
            rows[a]['levels'][level]='VALIDATED_CLAIM'
        except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
            record.update(status='INVALID_CLAIM',error=str(exc));rows[a]['levels'][level]='INVALID_CLAIM'
        rows[a]['evidence'][level]=record
    return dict(schema='mocap-coverage-v1',actions=list(rows.values()),
                counts={level:sum(r['levels'][level]=='VALIDATED_CLAIM' for r in rows.values()) for level in LEVELS},
                scope='Explicit reviewed claims only; validation binds bytes, verdict and subject, not proof soundness.')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args(argv)
    if a.out.exists(): raise ValueError('Refusing to replace catalog')
    report=catalog(a.root);write_new(a.out,report)
    print(json.dumps({k:report[k] for k in ('total','errors')}))


if __name__=='__main__': main()
