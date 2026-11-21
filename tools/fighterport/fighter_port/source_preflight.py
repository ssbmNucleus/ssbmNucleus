"""Independent-source preflight gate for Ultimate (SSBH) animation samplers.

WHY THIS EXISTS
---------------
A production sampler and the verifier that checks its output must not share the
code that turns raw source tracks into poses. The incineroar_mobility slice shipped
a wrong quaternion order (the stored XYZW quaternion was reordered to WXYZ and then
handed to a helper that consumes XYZW) and every fidelity gate passed, because the
author fitted curves to poses from the sampler and the verifier compared the readback against poses from the same sampler. Tests that
would have caught it existed but were never run by the build.

This module is the production gate that the build runs *before authoring*: it
evaluates the raw source a second time, on its own, and compares the candidate
sampler against that at integer AND fractional authored frames, including the
actual retime the candidate applies. It has no pytest dependency.

WHAT THE REFERENCE IS
---------------------
`RawSource` reads the skeleton bind and the animation transform tracks into plain
arrays and evaluates forward kinematics itself:

  * rotation: SciPy `Rotation`/`Slerp` between the two bounding source samples
    (shortest arc), translation and scale interpolated linearly - its own
    interpolation, not the candidate's;
  * `compensate_scale`: the MAYA_JOINT order `T * diag(1/s_parent) * R * S` with
    the parent's own interpolated non-accumulated local scale from the raw parent
    track, `1` when the parent carries no track - its own parent-scale lookup,
    never a candidate helper;
  * retime: source time = authored_frame * source_end / authored_end, computed
    here from the declared authored length, so a candidate that retimes wrongly
    is caught rather than trusted;
  * override flags (`override_translation/_rotation/_scale/_compensate_scale`):
    REFUSED with `PreflightError`, never ignored. Their runtime meaning is not
    settled and a gate that guessed would only certify its own guess.

The MAYA_JOINT placement is the sourced third-party semantics documented in
`pilots/incineroar_decoder/reference_v2/REPORT.md` (ssbh_wgpu, smash-ultimate-
blender, Maya joint node). It is an explicit policy of this gate, recorded in
every receipt. It is NOT a claim of Ultimate runtime parity.

WHAT THE COMPARISON PROVES, AND WHAT IT DOES NOT
------------------------------------------------
`compare()` takes two callbacks and checks, at every planned frame: the joint
domain is exactly the declared one on both sides, every matrix is finite with an
affine bottom row, and the largest absolute 4x4 entry difference is within the
declared tolerance. It records the worst joint and sample and every failure.

Passing two different callables does not prove they are independent. The receipt
records the sha256 of the implementation files the caller names for each side;
whether those files share sampler code is a review claim about the code, and the
receipt says so instead of implying otherwise.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation, Slerp

__all__ = ['PreflightError', 'POLICY', 'RawSource', 'compare', 'frame_plan', 'evidence', 'run', 'error_receipt',
           'write_receipt', 'DEFAULT_TOLERANCE', 'DEFAULT_FRACTIONS', 'DEFAULT_MAX_INTERVALS']

OVERRIDE_FLAGS = ('override_translation', 'override_rotation', 'override_scale', 'override_compensate_scale')

#: The semantics this reference implements. Recorded verbatim in every receipt.
POLICY = {
    'compensate_scale': 'maya_joint: T * diag(1/s_parent) * R * S, s_parent = the parent track\'s own '
                        'interpolated non-accumulated local scale; 1 when the parent has no track',
    'override_flags': 'refused (PreflightError); never ignored, never substituted',
    'interpolation': 'shortest-arc slerp (scipy Slerp) on rotation, linear on translation and scale, '
                     'between the two bounding source samples',
    'retime': 'source_time = authored_frame * source_end / authored_end, computed by the reference',
    'unanimated_bones': 'bind local transform from the skeleton file',
    'sourced_from': 'pilots/incineroar_decoder/reference_v2 (ssbh_wgpu current, smash-ultimate-blender, '
                    'Maya joint [IS] placement)',
    'claim': 'explicit prototype policy; not Ultimate runtime parity',
}

#: Largest absolute difference allowed between candidate and reference 4x4 entries.
#: Declared for a candidate that reads the same float32 source values and a bind
#: pose that went through one float32 round trip (measured 4.7e-7 per matrix on the
#: gaogaen rig); a wrong quaternion order or a baked-Euler fractional reference
#: is 1e-1..1e+1. Callers may tighten it, never widen it silently - it is in the receipt.
DEFAULT_TOLERANCE = 1e-4
#: Fractional offsets sampled inside every planned interval.
DEFAULT_FRACTIONS = (0.125, 0.5, 0.875)
#: Upper bound on the number of intervals that receive fractional samples.
DEFAULT_MAX_INTERVALS = 24


class PreflightError(Exception):
    """The gate refused to run or the candidate failed it."""


def sha256(path: Path) -> dict:
    p = Path(path)
    return {'path': str(p), 'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}


class _AnyBone:
    """`allow_unbound` that passes over a track for ANY bone the skeleton lacks (the reader asks it only of those).
    Such a track makes no joint of a rig, so it moves nothing drawn or struck: the own-skeleton route's readers pass
    them over and list them (`RawSource.ignored`) rather than refuse the clip (Shulk's `S_Hip_hit`, on 318 of his 359
    clips and in no model file, once refused his standing clip and 339 clips of the rig's survey)."""

    def __contains__(self, name):
        return True


ANY_BONE = _AnyBone()


# ------------------------------------------------------------------ reference
@dataclass
class Track:
    t: np.ndarray            # (N, 3)
    q: np.ndarray            # (N, 4) XYZW as stored by SSBH
    s: np.ndarray            # (N, 3)
    compensate_scale: bool
    overrides: dict = field(default_factory=dict)


class RawSource:
    """Skeleton bind plus raw transform tracks, evaluated by this module alone."""

    def __init__(self, bones, tracks: dict, end: int, provenance: dict | None = None, allow_unbound=()):
        """`bones`: iterable of (name, parent_name_or_None, bind 4x4 column-vector local).
        `tracks`: bone name -> Track with N in {1, end+1}."""
        self.parent, self.bind = {}, {}
        for name, parent, bind in bones:
            if not name or name in self.parent:
                raise PreflightError(f'skeleton bone names must be unique and non-empty: {name!r}')
            m = np.asarray(bind, dtype=float)
            _check_matrix(m, f'bind of {name}')
            self.parent[name] = parent; self.bind[name] = m
        if not self.parent:
            raise PreflightError('skeleton has no bones')
        for name, parent in self.parent.items():
            if parent is not None and parent not in self.parent:
                raise PreflightError(f'bone {name} lists an unknown parent {parent}')
        # Parents before children regardless of file order (the .nusktb is not sorted).
        self.order, active = [], set()

        def visit(name):
            if name in self.order:
                return
            if name in active:
                raise PreflightError(f'cyclic skeleton hierarchy at {name}')
            active.add(name)
            if self.parent[name] is not None:
                visit(self.parent[name])
            active.discard(name); self.order.append(name)
        for name in self.parent:
            visit(name)
        if not isinstance(end, (int, np.integer)) or end < 0:
            raise PreflightError(f'source end must be a non-negative integer, got {end!r}')
        self.end = int(end)
        self.tracks, self.ignored = {}, []
        for name, tr in tracks.items():
            if name not in self.parent:
                if name in allow_unbound:
                    self.ignored.append(name); continue
                raise PreflightError(f'animation track for a bone the skeleton lacks: {name}')
            t, q, s = (np.asarray(x, dtype=float) for x in (tr.t, tr.q, tr.s))
            n = len(q)
            if n not in (1, self.end + 1) or t.shape != (n, 3) or q.shape != (n, 4) or s.shape != (n, 3):
                raise PreflightError(f'track {name}: expected 1 or {self.end + 1} samples of t3/q4/s3, '
                                     f'got t{t.shape} q{q.shape} s{s.shape}')
            if not (np.isfinite(t).all() and np.isfinite(q).all() and np.isfinite(s).all()):
                raise PreflightError(f'track {name} carries non-finite values')
            norms = np.linalg.norm(q, axis=1)
            if np.any(norms < 1e-8):
                raise PreflightError(f'track {name} carries a zero quaternion')
            active = [f for f, v in (tr.overrides or {}).items() if v]
            if active:
                raise PreflightError(f'track {name} sets {active}; override flags are refused, not ignored')
            if n == 1:
                t, q, s = (np.repeat(x, self.end + 1, axis=0) for x in (t, q, s))
            self.tracks[name] = Track(t, q / norms.reshape(-1, 1) if n > 1 else q / norms[0],
                                      s, bool(tr.compensate_scale), {})
        if not self.tracks:
            raise PreflightError('animation carries no skeletal transform tracks')
        self.provenance = provenance or {}

    # -- construction from the vendored reader -------------------------------
    @classmethod
    def from_files(cls, skel_path: Path, anim_path: Path, allow_unbound=()):
        try:
            import ssbh_data_py as ssbh
        except ImportError as exc:                      # pragma: no cover - environment
            raise PreflightError('the vendored ssbh_data_py reader is required') from exc
        skel = ssbh.skel_data.read_skel(str(skel_path)); anim = ssbh.anim_data.read_anim(str(anim_path))
        names = [b.name for b in skel.bones]
        bones = []
        for b in skel.bones:
            parent = names[b.parent_index] if b.parent_index is not None else None
            bones.append((b.name, parent, np.asarray(b.transform, dtype=float).T))   # row-vector -> column
        end = float(anim.final_frame_index)
        if not (math.isfinite(end) and end >= 0 and end.is_integer()):
            raise PreflightError(f'{anim_path}: non-integer final frame index {end}')
        tracks, ignored_groups = {}, []
        for group in anim.groups:
            if group.group_type.name != 'Transform':
                ignored_groups.append(group.group_type.name); continue
            for node in group.nodes:
                for tr in node.tracks:
                    if tr.name != 'Transform' or node.name in tracks:
                        raise PreflightError(f'unsupported or duplicate track {node.name}/{tr.name}')
                    flags = tr.transform_flags
                    tracks[node.name] = Track(
                        np.array([v.translation for v in tr.values], dtype=float),
                        np.array([v.rotation for v in tr.values], dtype=float),
                        np.array([v.scale for v in tr.values], dtype=float),
                        bool(tr.compensate_scale),
                        {f: bool(getattr(flags, f)) for f in OVERRIDE_FLAGS})
        prov = {'skeleton': sha256(skel_path), 'animation': sha256(anim_path),
                'reader': _reader_identity(ssbh), 'ignored_groups': ignored_groups}
        return cls(bones, tracks, int(end), prov, allow_unbound)

    # -- evaluation ----------------------------------------------------------
    def source_time(self, authored_frame: float, authored_end: int) -> float:
        if not isinstance(authored_end, (int, np.integer)) or isinstance(authored_end, (bool, np.bool_)) or authored_end <= 0:
            raise PreflightError(f'authored end must be a positive integer, got {authored_end!r}')
        if not 0 <= authored_frame <= authored_end:
            raise PreflightError(f'authored frame {authored_frame} outside 0..{authored_end}')
        return float(authored_frame) * self.end / int(authored_end)

    def parts(self, bone: str, t: float):
        """(translation, rotation 3x3, scale) of one track at source time t, or None if unanimated."""
        tr = self.tracks.get(bone)
        if tr is None:
            return None
        i = min(int(math.floor(t + 1e-9)), self.end); u = t - i; j = min(i + 1, self.end)
        if u <= 1e-12 or i == j:
            return tr.t[i].copy(), Rotation.from_quat(tr.q[i]).as_matrix(), tr.s[i].copy()
        qa, qb = tr.q[i], tr.q[j]
        if float(qa @ qb) < 0:
            qb = -qb
        if np.array_equal(qa, qb):
            r = Rotation.from_quat(qa)
        else:
            r = Slerp([0.0, 1.0], Rotation.from_quat([qa, qb]))(u)
        return ((1 - u) * tr.t[i] + u * tr.t[j], r.as_matrix(), (1 - u) * tr.s[i] + u * tr.s[j])

    def world(self, t: float) -> dict:
        """World 4x4 of every bone at source time t under POLICY."""
        if not 0 <= t <= self.end + 1e-9:
            raise PreflightError(f'source time {t} outside 0..{self.end}')
        world = {}
        for bone in self.order:
            parent = self.parent[bone]; p = self.parts(bone, t)
            if p is None:
                local = self.bind[bone]
            else:
                tt, r, s = p
                local = np.eye(4); local[:3, 3] = tt
                basis = r @ np.diag(s)
                if self.tracks[bone].compensate_scale and parent is not None:
                    pp = self.parts(parent, t)
                    ps = pp[2] if pp is not None else np.ones(3)
                    if np.any(np.abs(ps) < 1e-12):
                        raise PreflightError(f'cannot compensate a zero parent scale: {bone} at t={t}')
                    basis = np.diag(1.0 / ps) @ basis          # T * C * R * S
                local[:3, :3] = basis
            world[bone] = local if parent is None else world[parent] @ local
        return world

    def authored_world(self, authored_frame: float, authored_end: int) -> dict:
        return self.world(self.source_time(authored_frame, authored_end))


# ------------------------------------------------------------------ comparison
def frame_plan(authored_end: int, fractions=DEFAULT_FRACTIONS, max_intervals: int = DEFAULT_MAX_INTERVALS) -> list:
    """Every integer authored frame, plus `fractions` inside a bounded, deterministic set of intervals.

    `fractions` must be explicit: a non-empty sequence of finite, distinct offsets strictly
    inside (0, 1). `max_intervals` must be an int >= 2. When the clip has more intervals than
    the cap, exactly `max_intervals` are chosen, evenly spread and always including the first
    and the last interval; otherwise every interval is sampled. Depends only on its arguments.
    """
    if not isinstance(authored_end, (int, np.integer)) or isinstance(authored_end, bool) or authored_end < 0:
        raise PreflightError(f'authored end must be a non-negative integer, got {authored_end!r}')
    fr = _validated_fractions(fractions)
    if not isinstance(max_intervals, (int, np.integer)) or isinstance(max_intervals, bool) or max_intervals < 2:
        raise PreflightError(f'max_intervals must be an integer >= 2, got {max_intervals!r}')
    n = int(authored_end); frames = [float(i) for i in range(n + 1)]
    if n > 0:
        if n <= max_intervals:
            intervals = list(range(n))
        else:
            intervals = sorted({int(round(i * (n - 1) / (max_intervals - 1))) for i in range(int(max_intervals))})
        assert intervals[0] == 0 and intervals[-1] == n - 1 and len(intervals) <= max_intervals
        for i in intervals:
            frames += [i + f for f in fr]
    return sorted(frames)


def _validated_fractions(fractions) -> list:
    if isinstance(fractions, (str, bytes)):
        raise PreflightError(f'fractions must be a sequence of numbers, got {fractions!r}')
    try:
        fr = [float(f) for f in fractions]
    except (TypeError, ValueError) as exc:
        raise PreflightError(f'fractions must be a sequence of numbers, got {fractions!r}') from exc
    if not fr:
        raise PreflightError('fractions must not be empty')
    if any(not math.isfinite(f) or not 0.0 < f < 1.0 for f in fr):
        raise PreflightError(f'fractions must be finite and strictly inside (0, 1), got {fractions!r}')
    if len(set(fr)) != len(fr):
        raise PreflightError(f'fractions must be distinct, got {fractions!r}')
    return fr


def _validated_frames(frames) -> list:
    """Materialise once; reject empty, non-finite or duplicate frames."""
    if isinstance(frames, (str, bytes)):
        raise PreflightError(f'frames must be a sequence of numbers, got {frames!r}')
    try:
        out = [float(f) for f in frames]
    except (TypeError, ValueError) as exc:
        raise PreflightError(f'frames must be a sequence of numbers, got {frames!r}') from exc
    if not out:
        raise PreflightError('frames must not be empty')
    if any(not math.isfinite(f) for f in out):
        raise PreflightError('frames must be finite')
    if len(set(out)) != len(out):
        raise PreflightError('frames must be distinct')
    return out


def _check_matrix(m, what: str):
    m = np.asarray(m)
    if m.shape != (4, 4):
        raise PreflightError(f'{what}: expected a 4x4 matrix, got {m.shape}')
    if not np.isfinite(m).all():
        raise PreflightError(f'{what}: non-finite entries')
    if not np.allclose(m[3], [0, 0, 0, 1], rtol=0.0, atol=1e-9):
        raise PreflightError(f'{what}: bottom row is not [0 0 0 1]')


def compare(candidate, reference, frames, joints, tolerance: float = DEFAULT_TOLERANCE,
            labels=('candidate', 'reference')) -> dict:
    """Compare two `frame -> {joint: 4x4}` callbacks. Never raises for a failing candidate;
    every problem becomes a failure row and `passed` is False. Only a broken *reference*
    (an exception from the second callback) is raised, because then the gate itself is unusable."""
    joints = list(joints)
    if len(set(joints)) != len(joints) or not joints:
        raise PreflightError('joint domain must be a non-empty list of unique names')
    if not (isinstance(tolerance, (int, float)) and not isinstance(tolerance, bool)
            and math.isfinite(tolerance) and tolerance > 0):
        raise PreflightError(f'tolerance must be a positive finite number, got {tolerance!r}')
    frames = _validated_frames(frames)
    failures, per_frame = [], []
    worst = {'value': 0.0, 'joint': None, 'frame': None}
    for f in frames:
        try:
            c = candidate(f)
        except Exception as exc:                      # a candidate that crashes fails the gate
            failures.append({'kind': 'candidate_exception', 'frame': f, 'detail': f'{type(exc).__name__}: {exc}'})
            continue
        r = reference(f)
        row = {'frame': f, 'max_abs_diff': 0.0, 'joint': None}
        for side, poses in ((labels[0], c), (labels[1], r)):
            if not isinstance(poses, dict):
                failures.append({'kind': 'not_a_dict', 'frame': f, 'side': side}); poses = None
                continue
            missing = sorted(set(joints) - set(poses)); extra = sorted(set(poses) - set(joints))
            if missing or extra:
                failures.append({'kind': 'joint_domain', 'frame': f, 'side': side,
                                 'missing': missing[:10], 'extra': extra[:10],
                                 'missing_count': len(missing), 'extra_count': len(extra)})
        if any(x['frame'] == f and x['kind'] in ('joint_domain', 'not_a_dict') for x in failures):
            per_frame.append(row); continue
        for j in joints:
            ok = True
            for side, m in ((labels[0], c[j]), (labels[1], r[j])):
                try:
                    _check_matrix(m, f'{side} {j} @ {f}')
                except PreflightError as exc:
                    failures.append({'kind': 'invalid_matrix', 'frame': f, 'side': side, 'joint': j, 'detail': str(exc)})
                    ok = False
            if not ok:
                continue
            d = float(np.abs(np.asarray(c[j], dtype=float) - np.asarray(r[j], dtype=float)).max())
            if d > row['max_abs_diff']:
                row['max_abs_diff'], row['joint'] = d, j
            if d > worst['value']:
                worst = {'value': d, 'joint': j, 'frame': f}
        per_frame.append(row)
        if row['max_abs_diff'] > tolerance:
            failures.append({'kind': 'tolerance', 'frame': f, 'joint': row['joint'], 'max_abs_diff': row['max_abs_diff']})
    return {'passed': not failures, 'tolerance': tolerance, 'frames': list(frames),
            'frame_count': len(frames), 'joint_count': len(joints), 'worst': worst,
            'per_frame': per_frame, 'failures': failures, 'labels': list(labels),
            'independence_note': ('two different callables do not prove independence; see '
                                  'evidence.implementations for what each side is built from')}


def _reader_identity(ssbh) -> dict:
    p = Path(ssbh.__file__).resolve()
    out = {'module': str(p)}
    try:
        out['version'] = importlib.metadata.version('ssbh_data_py')
    except importlib.metadata.PackageNotFoundError:
        out['version'] = None
    for b in p.parent.glob('*.pyd'):
        out['binary'] = sha256(b); break
    return out


def evidence(implementations: dict, inputs: dict | None = None, extra: dict | None = None) -> dict:
    """Hash everything the verdict depends on. `implementations`: side -> list of files."""
    return {
        'reference_module': sha256(Path(__file__)),
        'implementations': {side: [sha256(Path(p)) for p in files] for side, files in implementations.items()},
        'inputs': {k: (sha256(Path(v)) if isinstance(v, (str, Path)) else v) for k, v in (inputs or {}).items()},
        'libraries': {'numpy': np.__version__, 'scipy': importlib.metadata.version('scipy')},
        'policy': POLICY, **(extra or {}),
        'independence': ('The candidate and reference sides are listed by file hash. Independence is the '
                         'claim that those files share no sampler code; it is established by reading them, '
                         'not by this receipt.')}


def run(specs, tolerance: float = DEFAULT_TOLERANCE, implementations: dict | None = None,
        fractions=DEFAULT_FRACTIONS, max_intervals: int = DEFAULT_MAX_INTERVALS) -> dict:
    """Gate several clips. Each spec: dict(key, skeleton, animation, candidate, authored_end,
    joints, allow_unbound=()). `candidate(authored_frame) -> {joint: 4x4}`.
    Returns a receipt; `receipt['passed']` is the verdict. Nothing is cached or reused.
    Empty specs and duplicate keys are rejected: a gate with nothing to check has no verdict,
    and a duplicate key would let a later result overwrite an earlier failure."""
    specs = list(specs)
    if not specs:
        raise PreflightError('run() needs at least one clip spec')
    keys = [spec.get('key') if isinstance(spec, dict) else None for spec in specs]
    if any(not isinstance(k, str) or not k for k in keys):
        raise PreflightError(f'every spec needs a non-empty string key, got {keys!r}')
    if len(set(keys)) != len(keys):
        raise PreflightError(f'duplicate spec keys: {sorted({k for k in keys if keys.count(k) > 1})}')
    fractions = _validated_fractions(fractions)
    clips, passed = {}, True
    for spec in specs:
        key = spec['key']
        ref = RawSource.from_files(spec['skeleton'], spec['animation'], spec.get('allow_unbound', ()))
        authored_end = spec['authored_end']
        if not isinstance(authored_end, (int, np.integer)) or isinstance(authored_end, (bool, np.bool_)) or authored_end <= 0:
            raise PreflightError(f'authored end must be a positive integer, got {authored_end!r}')
        authored_end = int(authored_end)
        frames = frame_plan(authored_end, fractions, max_intervals)
        result = compare(spec['candidate'], lambda f, ref=ref, e=authored_end: ref.authored_world(f, e),
                         frames, spec['joints'], tolerance)
        result.update(source_end=ref.end, authored_end=authored_end,
                      retime_source_frames_per_authored_frame=ref.end / authored_end,
                      source_times=[round(f * ref.end / authored_end, 6) for f in frames],
                      compensate_scale_tracks=sorted(b for b, t in ref.tracks.items() if t.compensate_scale),
                      provenance=ref.provenance, ignored_unbound_tracks=ref.ignored)
        clips[key] = result; passed &= result['passed']
    return {'schema': 2, 'gate': 'fighter_port.source_preflight', 'passed': passed, 'tolerance': tolerance,
            'fractions': list(fractions), 'max_intervals': int(max_intervals), 'clips': clips,
            'evidence': evidence(implementations or {}, extra={'tolerance': tolerance})}


def error_receipt(exc: BaseException, requested, implementations: dict | None = None, context: dict | None = None) -> dict:
    """A failing receipt for a gate that could not run (reference load error, bad spec, ...).
    Written by production wrappers so that a broken gate never looks like an absent one."""
    import traceback
    return {'schema': 2, 'gate': 'fighter_port.source_preflight', 'passed': False, 'gate_error': True,
            'error': {'type': type(exc).__name__, 'message': str(exc),
                      'traceback': traceback.format_exception(type(exc), exc, exc.__traceback__)},
            'requested': list(requested), 'context': context or {},
            'evidence': evidence(implementations or {})}


def write_receipt(path: Path, receipt: dict) -> Path:
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=1, default=_json_default), encoding='utf-8')
    return path


def _json_default(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, Path):
        return str(o)
    raise TypeError(f'not serialisable: {type(o).__name__}')
