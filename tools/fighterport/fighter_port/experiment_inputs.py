"""Freeze loaded project implementations before a measured experiment begins.

Explicit data inputs remain hash-bound in place. Project Python sources are also
copied by content hash, so later edits cannot erase the exact implementation
which produced a receipt. This records the loaded closure, not an assertion that
all possible runtime imports or external tools were discovered automatically.
"""
import hashlib
import importlib.metadata
from pathlib import Path
import platform
import sys

from .workbench import fingerprint, write_new, check_pins


def freeze(out, inputs, *, project_root):
    out=Path(out);root=Path(project_root).resolve()
    if not root.is_dir():raise ValueError('Existing project root required')
    sources={};binaries={}
    for name,module in list(sys.modules.items()):
        filename=getattr(module,'__file__',None)
        if filename:
            path=Path(filename).resolve()
            if path.suffix=='.py' and path.is_relative_to(root):sources[name]=path
            if path.suffix.lower() in ('.pyd','.so') and path.is_file():binaries[name]=path
    paths={f'input:{k}':Path(v).resolve() for k,v in inputs.items()}
    paths.update({f'code:{k}':v for k,v in sources.items()})
    paths.update({f'binary:{k}':v for k,v in binaries.items()})
    pins={k:fingerprint(v) for k,v in paths.items()}
    out.mkdir(parents=True,exist_ok=False);objects=out/'sources';objects.mkdir()
    snapshots={}
    for key,path in paths.items():
        if not key.startswith('code:'):continue
        content=path.read_bytes();digest=hashlib.sha256(content).hexdigest()
        if digest!=pins[key]['sha256']:raise ValueError('Source changed while freezing')
        target=objects/(digest+'.py')
        if not target.exists():target.write_bytes(content)
        snapshots[key]=str(target.resolve())
    versions={}
    for name in ('numpy','scipy','ssbh_data_py'):
        try:versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:versions[name]='not registered; pin reader binary separately'
    check_pins(pins)
    write_new(out/'manifest.json',dict(schema='mocap-experiment-inputs-v1',inputs=pins,snapshots=snapshots,
        environment=dict(python=sys.version,executable=sys.executable,platform=platform.platform(),packages=versions),
        scope='Explicit inputs and project Python modules loaded at freeze time; late imports need a separate pin.'))
    return pins


def finish(out, initial, *, project_root):
    """Verify initial inputs and snapshot the final loaded closure, including late imports.

    Output is a separate immutable manifest. This cannot discover modules that
    were unloaded or arbitrary external resources; callers still name data/tools.
    """
    check_pins(initial)
    explicit={key.removeprefix('input:'):pin['path'] for key,pin in initial.items() if key.startswith('input:')}
    final=freeze(out,explicit,project_root=project_root)
    for key,pin in initial.items():
        if key in final and final[key]!=pin:raise ValueError('Initial input changed during final snapshot')
    write_new(Path(out)/'closure.json',dict(status='INITIAL_INPUTS_PRESERVED_FINAL_CLOSURE_RECORDED',
        added=sorted(set(final)-set(initial)),absent_from_final=sorted(set(initial)-set(final)),
        scope='Final loaded closure only; unloaded modules and external resources are not inferred.'))
    check_pins(initial)
    return final
