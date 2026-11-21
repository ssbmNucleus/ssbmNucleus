"""
stage_yml_converter.py - convert classic m-ex stage packages (stage.yml — the
MexTK / old-MexManager format, 100+ of them in the wild) into modern
MexManager packages (stage.json) that MexCLI add-stage understands.

Field mapping notes:
  - The yml usually carries the same data twice: a nested old-style section
    (stage:/reverb:/collision:/playlist:) and flattened newer keys
    (internalID, stageName, fileName, mapGOBJs, onStageInit, ...). We prefer
    the flattened keys and fall back to the nested ones.
  - Classic packages embed the map GOBJ function table itself
    (gOBJFunctionsPointer: -1 + an explicit array). Modern MexStage only
    carried a pointer until we extended mexLib with `mapGOBJs` /
    `movingCollisions` fields (MexStage.cs) — this converter emits those, and
    ToMxDt writes them as real array references in MxDt.dat.
  - sound.spk (classic sound pack) is NOT converted; the stage gets sound
    bank 55 ("none"), same as MexStage.FromPackage's default. Stage-specific
    sound effects are silent until .spk conversion is implemented.
  - The internal/external stage IDs in the yml are slot assignments from the
    ORIGINAL build — meaningless here; AddStage assigns fresh ones.
"""

import io
import logging
import zipfile
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


def _u32(v):
    """yml stores some pointers as signed int32; stage.json wants uint."""
    return int(v) & 0xFFFFFFFF if v is not None else 0


def _gobj_entries(doc):
    flat = doc.get('mapGOBJs')
    if flat:
        return flat
    nested = (doc.get('stage') or {}).get('gOBJFunctions') or {}
    return nested.get('array') or []


def _moving_collisions(doc):
    flat = doc.get('movingCollisions')
    if flat:
        return flat
    nested = (doc.get('stage') or {}).get('movingCollisionPoint') or {}
    return nested.get('array') or []


def convert_stage_yml(yml_text, fallback_name):
    """Convert a stage.yml document to a stage.json dict (camelCase keys
    matching MexJsonSerializer). Raises ValueError on unusable input."""
    doc = yaml.safe_load(yml_text)
    if not isinstance(doc, dict):
        raise ValueError('stage.yml did not parse to a mapping')

    nested_stage = doc.get('stage') or {}
    reverb = doc.get('reverb') or {}
    collision = doc.get('collision') or {}

    file_name = (doc.get('fileName')
                 or nested_stage.get('stageFileName') or '').lstrip('/')
    if not file_name:
        raise ValueError('stage.yml has no fileName/stageFileName')

    def pick(flat_key, nested_key=None):
        v = doc.get(flat_key)
        if v is None:
            v = nested_stage.get(nested_key or flat_key)
        return v

    gobjs = _gobj_entries(doc)
    moving = _moving_collisions(doc)
    gobj_pointer = nested_stage.get('gOBJFunctionsPointer', -1)

    stage_json = {
        'name': doc.get('stageName') or fallback_name,
        'location': '',
        'seriesID': 0,
        'fileName': file_name,
        'additionalFiles': [],
        # 55 = none; classic sound.spk packs are not convertible (yet).
        'soundBank': 55,
        'reverbValue1': doc.get('reverbValue', reverb.get('reverb', 0)) or 0,
        'reverbValue2': doc.get('unknown', reverb.get('unknown', 0)) or 0,
        'collisionMaterials': _u32(collision.get('collisionFunction', 0)),
        # -1 means "the array is embedded" (mapGOBJs below carries it).
        'mapDescPointer': _u32(gobj_pointer) if gobj_pointer not in (-1, None) else 0,
        'onStageInit': _u32(pick('onStageInit')),
        'onStageLoad': _u32(pick('onStageLoad')),
        'onStageGo': _u32(pick('onStageGo')),
        'onGo': _u32(pick('onUnknown1')),
        'onUnknown2': _u32(pick('onUnknown2')),
        'onTouchLine': _u32(pick('onUnknown3')),
        'onUnknown4': _u32(pick('onUnknown4')),
        'unknownValue': pick('unknownValue') or 0,
        'movingCollisionPointer': 0,
        'movingCollisionCount': len(moving),
        'items': [],
        'playlist': {'entries': []},
        'alternateStages': [],
        'mapGOBJs': [{
            'onCreation': _u32(g.get('onCreation')),
            'onDeletion': _u32(g.get('onDeletion')),
            'onFrame': _u32(g.get('onFrame')),
            'onUnk': _u32(g.get('onUnk')),
            'bitflags': _u32(g.get('bitflags')),
        } for g in gobjs],
        'movingCollisions': [{
            'lineID': int(m.get('lineID', 0)),
            'gobjID': int(m.get('gOBJID', m.get('gobjID', 0))),
            'unknown': int(m.get('unknown', 0)),
        } for m in moving],
    }
    return stage_json


def convert_stage_yml_zip(zip_bytes, fallback_name):
    """Convert a classic stage.yml package zip into a modern stage.json
    package zip. Returns (new_zip_bytes, info dict). Raises ValueError."""
    import json

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist()
                 if not n.startswith('__MACOSX') and not n.endswith('/')]
        yml_member = next((n for n in names
                           if Path(n).name.lower() == 'stage.yml'), None)
        if yml_member is None:
            raise ValueError('no stage.yml in archive')

        stage_json = convert_stage_yml(
            zf.read(yml_member).decode('utf-8', errors='replace'), fallback_name)

        dats = [n for n in names if Path(n).suffix.lower() in ('.dat', '.usd')]
        if not any(Path(n).name.lower() == stage_json['fileName'].lower()
                   for n in dats):
            # tolerate case/typo'd extensions: fall back to the first dat
            if dats:
                logger.warning(f"fileName {stage_json['fileName']} not in zip; "
                               f"using {Path(dats[0]).name}")
                stage_json['fileName'] = Path(dats[0]).name
            else:
                raise ValueError('no stage .dat in archive')

        skipped = [n for n in names
                   if Path(n).suffix.lower() == '.spk']

        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as dest:
            dest.writestr('stage.json', json.dumps(stage_json, indent=2))
            for n in dats:
                dest.writestr(Path(n).name, zf.read(n))
            # carry over any preview images for the vault
            for n in names:
                if Path(n).suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'):
                    dest.writestr(Path(n).name, zf.read(n))

    info = {
        'name': stage_json['name'],
        'fileName': stage_json['fileName'],
        'mapGOBJs': len(stage_json['mapGOBJs']),
        'movingCollisions': len(stage_json['movingCollisions']),
        'skipped_sound': skipped,
    }
    return out.getvalue(), info
