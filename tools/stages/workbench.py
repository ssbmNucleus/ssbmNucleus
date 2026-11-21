"""Composable stage tools. No project state machine, design recipe, or mandatory game test."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time
import uuid
import zipfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BACKEND = REPO / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

STAGES = {
    "battlefield": ("GrNBa.dat", 0.8, 68.4, 54.4, 2_400_000),
    "final": ("GrNLa.dat", 1.0, 85.6, 0.0, 2_400_000),
    "fountain": ("GrIz.dat", 0.75, 63.4, 42.8, 2_390_000),
    "dreamland": ("GrOp.dat", 1.0, 77.3, 51.4, 2_400_000),
    "stadium": ("GrPs.usd", 1.0, 87.8, 25.0, 1_461_000),
    "yoshis": ("GrSt.dat", 0.7, 56.0, 42.0, 2_400_000),
}
ALIASES = {"finaldestination": "final", "fountainofdreams": "fountain",
           "pokemonstadium": "stadium", "yoshisstory": "yoshis"}


def stage_key(value):
    key = ALIASES.get(value, value)
    if key not in STAGES:
        raise ValueError(f"Unknown stage preset {value!r}; choose {', '.join(STAGES)}")
    return key


def file_path(value, base=None):
    p = Path(value).expanduser()
    if not p.is_absolute():
        if base is None:
            raise ValueError(f"Use an absolute path: {value}")
        p = base / p
    p = p.resolve()
    if not p.is_file():
        raise ValueError(f"Input file missing: {p}")
    return p


def output_path(value, inputs=()):
    p = Path(value).expanduser()
    if not p.is_absolute():
        raise ValueError(f"Use an absolute output path: {value}")
    p = p.resolve()
    if p in {Path(x).resolve() for x in inputs}:
        raise ValueError(f"Output would overwrite an input: {p}")
    if p.exists():
        raise ValueError(f"Output already exists; choose a new revision: {p}")
    return p


def sha256(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def _publish(tmp, dest):
    # Windows rename refuses existing targets; POSIX rename would overwrite.
    if os.name == "nt":
        os.rename(tmp, dest)
    else:
        os.link(tmp, dest)
        Path(tmp).unlink()


def write_new(dest, data):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.building")
    try:
        tmp.write_bytes(data)
        _publish(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)


def _run(cmd, log, timeout=300):
    from core.config import get_subprocess_args
    log(f"Running {Path(str(cmd[0])).name} {cmd[1]}")
    started = time.monotonic()
    with subprocess.Popen([str(x) for x in cmd], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, encoding="utf-8",
                          errors="replace", **get_subprocess_args()) as p:
        while True:
            try:
                stdout, stderr = p.communicate(timeout=min(15, max(0.01, timeout - (time.monotonic() - started))))
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() - started >= timeout:
                    p.kill()
                    p.communicate()
                    raise RuntimeError(f"Stage tool timed out after {timeout}s: {cmd[1]}")
                log(f"Stage tool still running ({int(time.monotonic() - started)}s)")
    if p.returncode:
        raise RuntimeError(f"Stage tool failed ({p.returncode}):\n{(stdout + stderr)[-8000:]}")
    return stdout


def native(log):
    """Compile the promoted builder against Nucleus's configured HSDRaw, cached by content."""
    from core.config import HSDRAW_EXE, SCRATCH_PATH
    dll = file_path(Path(HSDRAW_EXE).parent / "HSDRaw.dll")
    dotnet = shutil.which("dotnet")
    if not dotnet:
        raise RuntimeError("Stage graft/inspect needs the .NET 8+ SDK. Camera and package operations do not.")
    sources = sorted((HERE / "native").glob("*.cs")) + [HERE / "native" / "stagegraft.csproj"]
    key = hashlib.sha256()
    for p in [dll, *sources]:
        key.update(p.name.encode()); key.update(p.read_bytes())
    cache = Path(SCRATCH_PATH) / "stage-workbench" / "native"
    ready = cache / key.hexdigest()[:24]
    binary = ready / "bin" / "stagegraft.dll"
    if not binary.is_file():
        build = cache / f"{key.hexdigest()[:24]}-{uuid.uuid4().hex}"
        build.mkdir(parents=True)
        _run([dotnet, "build", HERE / "native" / "stagegraft.csproj", "-c", "Release",
              "--nologo", "-v", "q", "-p:UseSharedCompilation=false", "--disable-build-servers",
              f"-p:HSDRawPath={dll}", f"-p:BaseIntermediateOutputPath={build / 'obj'}{os.sep}",
              "-o", build / "bin"], log)
        try:
            build.rename(ready)
        except OSError:
            if not binary.is_file():
                raise
    return [dotnet, str(binary)]


def budget_report(size, stage):
    key = stage_key(stage)
    cap = STAGES[key][4]
    return {"preset": key, "reference_bytes": cap, "file_bytes": size,
            "over_reference": size > cap, "remaining_bytes": cap - size,
            "scope": "Measured vanilla four-heavy-fighter reference from the Colosseum/CS2 work. "
                     "Advisory only; custom fighters, forms, code and other assets can change memory use."}


def inspect_file(path, log, stage=None, command=None):
    p = file_path(path)
    raw = _run([*(command or native(log)), "inspect", p], log)
    # HSDRaw may print diagnostics before the JSON result.
    result = json.loads(raw.strip().splitlines()[-1])
    result["sha256"] = sha256(p)
    if stage:
        result["budget"] = budget_report(p.stat().st_size, stage)
    return result


_PATH_KEYS = {"file", "target", "tex", "mesh", "template", "plit_from"}
_IMAGE_ARRAYS = {"images", "front", "back"}
_FOD_IMAGES = {"top", "wall", "panel", "white", "glass", "plat_top", "plat_side"}


def resolve_spec(spec, base):
    """Keep all creative fields; resolve only the builder's documented file references."""
    inputs = []

    def path(value):
        p = file_path(value, base)
        inputs.append(p)
        return str(p)

    def walk(value, parent=""):
        if isinstance(value, list):
            return [walk(v, parent) for v in value]
        if not isinstance(value, dict):
            return value
        out = {}
        for k, v in value.items():
            if isinstance(v, str) and (k in _PATH_KEYS or (parent == "fod" and k in _FOD_IMAGES)):
                out[k] = path(v)
            elif k in _IMAGE_ARRAYS and isinstance(v, list):
                out[k] = [path(x) if isinstance(x, str) else x for x in v]
            else:
                out[k] = walk(v, k)
        return out

    result = walk(spec)
    for required in ("target", "receive_group"):
        if required not in result:
            raise ValueError(f"Graft spec needs {required}")
    result.setdefault("clear_groups", [])
    result.setdefault("donors", [])
    return result, inputs


def validate_meshes(spec):
    warnings = []
    for m in spec.get("cs", {}).get("meshes", []):
        raw = Path(m["mesh"]).read_bytes()
        n = struct.unpack_from("<i", raw)[0] if len(raw) >= 4 else 0
        if n <= 0 or n % 3 or len(raw) != 4 + n * 36:
            raise ValueError(f"Invalid triangle mesh: {m['mesh']}")
        if not all(math.isfinite(x[0]) for x in struct.iter_unpack("<f", raw[4:])):
            raise ValueError(f"Non-finite mesh coordinates: {m['mesh']}")
        img = Path(m["tex"]).read_bytes()
        w, h = struct.unpack_from("<ii", img) if len(img) >= 8 else (0, 0)
        if not 1 <= w <= 1024 or not 1 <= h <= 1024 or len(img) != 8 + w * h * 4:
            raise ValueError(f"Invalid GX image dimensions/payload: {m['tex']}")
        if m.get("mips", True) and ((w & (w - 1)) or (h & (h - 1))):
            warnings.append(f"Non-power-of-two mipmapped texture ({w}x{h}): {m['tex']}. "
                            "For hardware compatibility, resize or set mips=false; existing Dolphin-only designs may use this.")
    return warnings


def graft(args, log):
    src = file_path(args["spec"])
    spec, inputs = resolve_spec(json.loads(src.read_text(encoding="utf-8-sig")), src.parent)
    dest = output_path(args["out"], [src, *inputs])
    warnings = validate_meshes(spec)
    cmd = native(log)
    before = inspect_file(spec["target"], log, command=cmd)
    if before["kind"] != "melee_stage":
        raise ValueError("Graft target must be a Melee stage archive")
    if not isinstance(spec["receive_group"], int) or not 0 <= spec["receive_group"] < len(before["groups"]):
        raise ValueError("receive_group is outside the target stage's model groups")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tag = uuid.uuid4().hex
    tmp = dest.with_name(f".{dest.stem}.{tag}.dat")
    staged_spec = dest.with_name(f".{dest.stem}.{tag}.json")
    spec["out"] = str(tmp)
    try:
        staged_spec.write_text(json.dumps(spec, indent=2), encoding="utf-8")
        tail = _run([*cmd, "build", staged_spec], log, timeout=600)
        after = inspect_file(tmp, log, args.get("stage"), cmd)
        collision = {"before": before["collision_digest"], "after": after["collision_digest"],
                     "unchanged": bool(before["collision_digest"]) and before["collision_digest"] == after["collision_digest"],
                     "scope": "coll_data only; moved joints, stage code and camera/spawn points need separate review"}
        _publish(tmp, dest)
        after["file"] = str(dest)
        return {"ok": True, "artifact": after, "collision": collision,
                "warnings": warnings,
                "source_spec": str(src), "log_tail": tail.splitlines()[-25:],
                "gameplay_tested": False}
    finally:
        tmp.unlink(missing_ok=True)
        staged_spec.unlink(missing_ok=True)


def cameras(args):
    from . import gamecam
    key = stage_key(args.get("stage", "battlefield"))
    presets = json.loads((HERE / "camera_presets.json").read_text())
    cam = dict(args.get("camera") or presets[key])
    left, right = cam["left"] + cam["x_offset"], cam["right"] + cam["x_offset"]
    bottom, top = cam["bottom"] + cam["y_offset"], cam["top"] + cam["y_offset"]
    ledge, platform = STAGES[key][2:4]
    views = args.get("views") or [
        {"name": "close in the middle", "box": [-25, 0, 25, 30]},
        {"name": "two fighters across the stage", "box": [-ledge, 0, ledge, max(platform, 25)]},
        {"name": "left ledge recovery", "box": [-ledge - 30, -30, -ledge + 25, 25]},
        {"name": "right ledge recovery", "box": [ledge - 25, -30, ledge + 30, 25]},
        {"name": "bottom left", "box": [left, bottom, left + 50, bottom + 40]},
        {"name": "bottom right", "box": [right - 50, bottom, right, bottom + 40]},
        {"name": "bottom left to middle", "box": [left, bottom, 0, 30]},
        {"name": "top left", "box": [left, top - 40, left + 50, top]},
        {"name": "top right", "box": [right - 50, top - 40, right, top]},
        {"name": "every corner", "box": [left, bottom, right, top]},
    ]
    sweep = []
    for v in views:
        box = v["box"]
        if len(box) != 4 or not all(math.isfinite(x) for x in box) or box[2] <= box[0] or box[3] <= box[1]:
            raise ValueError("Camera boxes are finite [xmin, ymin, xmax, ymax] with positive width/height")
        depth = cam["zoom_rate"]
        for _ in range(4):
            factor = min(max((depth - 80.0) / 4920.0, 0.0), 1.0)
            pushed = [box[0], box[1] - (390.0 * factor + 10.0), box[2], box[3]]
            depth = gamecam.camera(pushed, cam)[0][2]
        eye, interest = gamecam.camera(pushed, cam)
        sweep.append({"name": v["name"], "eye": [round(float(x), 2) for x in eye],
                      "interest": [round(float(x), 2) for x in interest], "fov": cam.get("fov", gamecam.FOV)})
    result = {"stage": key, "units": "world", "file_to_world_scale": STAGES[key][1],
              "views": sweep, "basis": "Custom camera constants" if args.get("camera") else "Measured legal-stage camera preset",
              "scope": "Settled match-camera framing estimates; not captured gameplay or a proof of coverage."}
    if args.get("out"):
        dest = output_path(args["out"])
        write_new(dest, (json.dumps(sweep, indent=2) + "\n").encode())
        result["sweep_file"] = str(dest)
    return result


def mesh(args):
    """Convert an agent's triangle list and texture into the graft engine's neutral inputs."""
    from PIL import Image
    src = file_path(args["spec"])
    spec = json.loads(src.read_text(encoding="utf-8-sig"))
    texture = file_path(spec["texture"], src.parent)
    base = output_path(args["out"], [src, texture])
    mesh_out = output_path(str(base) + ".mesh", [src, texture])
    tex_out = output_path(str(base) + ".img", [src, texture])
    vertices = spec["vertices"]
    if not vertices or len(vertices) % 3:
        raise ValueError("vertices must contain a non-empty triangle list")
    raw = bytearray(struct.pack("<i", len(vertices)))
    for vertex in vertices:
        if len(vertex) != 9 or not all(math.isfinite(v) and abs(v) <= 3.402823e38 for v in vertex):
            raise ValueError("Each vertex is 9 finite float32 values: x,y,z,u,v,r,g,b,a")
        raw.extend(struct.pack("<9f", *vertex))
    with Image.open(texture) as im:
        im = im.convert("RGBA")
        w, h = im.size
        if max(w, h) > 1024:
            raise ValueError("Resize/tile the texture to at most 1024 on either axis before conversion")
        image = struct.pack("<ii", w, h) + im.tobytes("raw", "BGRA")
    write_new(mesh_out, raw)
    write_new(tex_out, image)
    return {"name": spec.get("name", base.name), "mesh": str(mesh_out), "tex": str(tex_out),
            "mips": False, "wrap": "clamp", "colors": spec.get("colors", False),
            "cutout": spec.get("cutout", False)}


def package(args):
    files = args.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("files must map ZIP member names to absolute source paths")
    resolved, seen = {}, set()
    for name, path in files.items():
        if not name or name in (".", "..") or any(c in name for c in '/\\:<>"|?*') or name.rstrip(" .") != name:
            raise ValueError(f"Use a plain archive filename: {name!r}")
        if name.casefold() in seen:
            raise ValueError(f"Duplicate archive filename: {name}")
        seen.add(name.casefold())
        resolved[name] = file_path(path)
    if not any(name.lower().endswith((".dat", ".usd")) for name in resolved):
        raise ValueError("Stage package must include a DAT/USD")
    if "stage.json" in resolved:
        from vault.importing.custom_stage_package import validate_stage_package_references
        meta = json.loads(resolved["stage.json"].read_text(encoding="utf-8-sig"))
        validate_stage_package_references(meta, resolved)
    dest = output_path(args["out"], resolved.values())
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.building")
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for name, p in resolved.items():
                z.write(p, name)
        with zipfile.ZipFile(tmp) as z:
            bad = z.testzip()
            if bad:
                raise RuntimeError(f"ZIP verification failed for {bad}")
            members = [{"name": i.filename, "bytes": i.file_size, "crc32": f"{i.CRC:08x}"} for i in z.infolist()]
        digest = sha256(tmp)
        _publish(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    return {"ok": True, "file": str(dest), "sha256": digest, "members": members,
            "installed": False, "gameplay_tested": False,
            "next": "detect_content, then vault_import/build_modded_iso when requested; custom slot metadata comes from MexCLI export."}


def handle(args, log=lambda _message: None):
    op = args.get("op", "guide")
    if op == "guide":
        return {"guide": (HERE / "README.md").read_text(encoding="utf-8"),
                "tools_directory": str(HERE), "operations": ["guide", "inspect", "mesh", "graft", "cameras", "package"]}
    if op == "inspect":
        return inspect_file(args["file"], log, args.get("stage"))
    if op == "graft":
        return graft(args, log)
    if op == "cameras":
        return cameras(args)
    if op == "mesh":
        return mesh(args)
    if op == "package":
        return package(args)
    raise ValueError(f"Unknown stage workbench operation: {op}")


if __name__ == "__main__":
    # Same contract as MCP, useful before a client reconnects to discover a new tool.
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig")) if len(sys.argv) == 2 else json.load(sys.stdin)
    print(json.dumps(handle(request, lambda s: print(s, file=sys.stderr, flush=True)), indent=2))
