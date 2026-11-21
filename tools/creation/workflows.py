"""MCP entrypoints for Nucleus fighter ports and the existing rigswap importer."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import re
import sys

from . import jobs

REPO = jobs.REPO
ENGINE = REPO / "tools" / "fighterport"
SETTINGS = REPO / "app" / "scratch" / "creation" / "settings.json"
GAMES = ("ultimate", "brawl", "slapcity", "rivals2")
ADAPTERS = ("audit", "movement_audit", "movement_repair", "hitbox_rebase",
            "source_combat_audit", "source_combat_install", "compress", "scale",
            "materials", "costume", "visibility", "pack", "preflight",
            "plan_rig", "source_visibility", "costume_budget", "animation_diagnose")
ENV_KEYS = ("SSBH_DATA_PY", "UNITY_PYDEPS", "RIVALS2_USMAP", "OODLE_DLL",
            "MEXTK_DIR", "PORT_DONOR_ZIP", "ULTIMATE_DUMP", "BRAWL_DUMP")


def path(value, kind=None):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A nonempty absolute path is required")
    p = Path(value).expanduser()
    if not p.is_absolute():
        raise ValueError(f"Use an absolute path: {value}")
    p = p.resolve()
    if kind == "file" and not p.is_file() or kind == "dir" and not p.is_dir():
        raise ValueError(f"Missing {kind}: {p}")
    return str(p)


def settings():
    return jobs.read(SETTINGS) if SETTINGS.is_file() else {}


def environment(tool):
    config = settings()
    env = dict(os.environ)
    for key, value in config.get("fighterport", {}).items():
        if key in ENV_KEYS:
            env.setdefault(key, str(value))
    env.update(NUCLEUS_REPO=str(REPO), PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    if tool == "native_port":
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(ENGINE), str(REPO / "app/backend"),
                                             env.get("SSBH_DATA_PY"), env.get("PYTHONPATH")]))
    python = env.get("FIGHTERPORT_PYTHON") if tool == "native_port" else None
    python = python or config.get("python") or sys.executable
    return path(str(python), "file"), env


def inspect_port(work):
    folder = Path(path(work, "dir"))
    result = {"work": str(folder), "receipts": {}}
    for name in ("port/status.json", "port/report.json", "preflight.json", "verify.json"):
        p = folder / name
        if p.is_file():
            value = jobs.read(p)
            result["receipts"][name] = value if len(json.dumps(value)) <= 12000 else {"file": str(p)}
    result["packages"] = [str(p) for p in sorted((folder / "package").glob("*.zip"))]
    result["notes"] = str(folder / "package/PORT_NOTES.txt") if (folder / "package/PORT_NOTES.txt").is_file() else None
    result["scope"] = "Build receipts and implementation limits; not a claim of polished graphics or source fidelity"
    return result


def port_argv(a):
    required = ("fighter", "name", "work", "root", "game")
    missing = [k for k in required if not a.get(k)]
    if missing:
        raise ValueError(f"port requires {', '.join(missing)}")
    if a["game"] not in GAMES:
        raise ValueError(f"game must be one of {GAMES}")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", a["fighter"]):
        raise ValueError("fighter must be a source fighter identifier")
    work, root = path(a["work"]), path(a["root"], "dir")
    # The build recipe recreates work/project; never let a source/install folder be its work area.
    if Path(work) == Path(root) or Path(work) in Path(root).parents:
        raise ValueError("work must not contain the source root")
    if Path(work) == REPO or Path(work) in REPO.parents or Path(work) == ENGINE:
        raise ValueError("Use a dedicated port work folder")
    argv = [a["fighter"], "--game", a["game"], "--name", a["name"], "--work", work,
            "--root", root, "--repo", str(REPO), "--donor", a.get("donor", "Marth")]
    own = a.get("own", a["game"] in ("slapcity", "rivals2"))
    if a["game"] in ("slapcity", "rivals2") and not own:
        raise ValueError("Slap City and Rivals 2 use the own-skeleton route")
    for key in ("body", "rip", "iso", "mextk"):
        if a.get(key):
            argv.extend(["--" + key, path(a[key], "dir" if key == "mextk" else "file" if key in ("body", "rip") else None)])
    for key in ("from", "to", "only", "forms_from"):
        if a.get(key):
            argv.extend(["--" + key.replace("_", "-"), a[key]])
    for key, value in (("own", own), ("calibrate", a.get("calibrate")), ("allow-large", a.get("allow_large"))):
        if value:
            argv.append("--" + key)
    if a.get("tests"):
        argv.extend(["--tests", *a["tests"]])
    return argv


def native_port(args, log):
    a = dict(args)
    op = a.get("op", "info")
    if op == "status":
        return jobs.status(a.get("job"), "native_port", wait=a.get("wait_seconds", jobs.STATUS_WAIT_DEFAULT))
    if op == "cancel":
        return jobs.cancel(a.get("job"), "native_port")
    if op == "info":
        python, env = environment("native_port")
        return dict(engine=str(ENGINE), python=python, games=list(GAMES),
                    guide=Path(__file__).with_name("README.md").read_text(encoding="utf-8"),
                    readers=str(ENGINE / "fighter_port/READERS.md"),
                    adapter_operations=list(ADAPTERS),
                    dependencies={key: {"configured": bool(env.get(key)),
                                        "exists": bool(env.get(key) and Path(env[key]).exists())} for key in ENV_KEYS})
    if op == "inspect":
        return inspect_port(a.get("work"))
    resource = None
    if op == "port":
        port_argv(a)  # Fail bad paths before making a job.
        resource = path(a["work"])
    elif op == "read_source":
        if a.get("game") not in ("slapcity", "rivals2"):
            raise ValueError("read_source supports slapcity and rivals2; Ultimate/Brawl use extracted source via port")
        a["game_dir"] = path(a.get("game_dir"), "dir")
        if a.get("list"):
            if a["game"] != "slapcity":
                raise ValueError("Roster listing is currently available for Slap City only")
        else:
            if not re.fullmatch(r"[A-Za-z0-9_-]+", a.get("fighter", "")):
                raise ValueError("read_source requires the source fighter name")
            a["root"] = path(a.get("root"))
            if Path(a["root"]).exists():
                raise ValueError("Choose a new reader output root to preserve earlier exports")
            if Path(a["game_dir"]) in Path(a["root"]).parents:
                raise ValueError("Reader output must be outside the game installation")
            resource = a["root"]
    elif op == "adapter":
        if a.get("operation") not in ADAPTERS:
            raise ValueError(f"operation must be one of {ADAPTERS}")
        a["options"] = dict(a.get("options") or {})
        resource = a["options"].get("out")
    elif op == "checklist":
        if a.get("work"):
            a["work"] = path(a["work"], "dir")
            resource = a["work"] if a.get("line") else None
        elif a.get("line"):
            raise ValueError("Recording a checklist answer requires work")
    else:
        raise ValueError(f"Unknown native_port operation: {op}")
    python, env = environment("native_port")
    return jobs.start("native_port", a, python=python, env=env, resource=resource)


def rigswap(args, log):
    from randall.model_import.chat import import_job as importer
    a = dict(args)
    op = a.get("op", "info")
    if op == "status":
        return jobs.status(a.get("job"), "rigswap", wait=a.get("wait_seconds", jobs.STATUS_WAIT_DEFAULT))
    if op == "cancel":
        return jobs.cancel(a.get("job"), "rigswap")
    found = importer.setup()
    if op == "info":
        return dict(available=not isinstance(found, str),
                    setup_error=found if isinstance(found, str) else None,
                    python=str(found[0]) if not isinstance(found, str) else None,
                    engine=str(found[1]) if not isinstance(found, str) else None,
                    fighters=importer.fighters(), operations=["info", "import", "fix", "status", "cancel"],
                    behavior="Uses Randall's existing importer; makes a costume and saves it to the vault. Fix uses the returned project id. No gameplay test is required. AI calls use existing configured credentials.")
    if isinstance(found, str):
        raise ValueError(found)
    if op == "import":
        a["source"] = path(a.get("source"), "file")
        a = dict(importer.check(a), op=op)
    elif op == "fix":
        if not re.fullmatch(r"[A-Za-z0-9_-]+", a.get("project", "")):
            raise ValueError("Use the project id returned by the importer")
        a = dict(importer.check(a), op=op)
    else:
        raise ValueError(f"Unknown rigswap operation: {op}")
    python, env = environment("rigswap")
    from randall.model_import.chat import studio_import
    resource = str(Path(studio_import.root()) / a["project"]) if op == "fix" else None
    return jobs.start("rigswap", a, python=python, env=env, resource=resource)


def execute(tool, a, folder):
    if tool == "rigswap":
        from randall.model_import.chat import import_job
        result = import_job.run({k: v for k, v in a.items() if k != "op"},
                                progress=lambda value: print(json.dumps(value, default=str), flush=True),
                                cancelled=lambda: (folder / "cancel").exists())
        return dict(ok=result.get("status") == "done", import_result=result)
    sys.path.insert(0, str(ENGINE))
    from fighter_port import port
    op = a["op"]
    if op == "port":
        code = port.main(port_argv(a))
        return dict(ok=code == 0, exit_code=code, **inspect_port(a["work"]))
    if op == "read_source":
        if a["game"] == "slapcity":
            from echo_slapcity.__main__ import main
        else:
            from echo_rivals2.__main__ import main
        if a.get("list"):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main([a["game_dir"], "--list"])
            return dict(ok=code in (0, None), roster=json.loads(output.getvalue()))
        code = main([a["game_dir"], a["fighter"], a["root"]])
        return dict(ok=code in (0, None), root=a["root"], fighter=a["fighter"].lower())
    if op == "checklist":
        if a.get("line"):
            port.record(a["work"], a["line"], a.get("answer"), a.get("how"))
        rows, got = port.lines(), port.answers(a.get("work")) if a.get("work") else {}
        return dict(ok=True, lines=rows, recorded=got,
                    rule="Optional fidelity backlog; unfilled lines do not prevent packaging or require an end-user harness")
    if op == "adapter":
        from fighter_port.port_mcp import handle
        result = handle(dict(a["options"], op=a["operation"]), print)
        return dict(ok=not bool(result.get("error")) and result.get("ok") is not False, result=result)
    raise ValueError(f"Unknown worker operation: {op}")


def schema(props):
    return dict(type="object", properties=props, additionalProperties=False)


STRING = {"type": "string"}
WAIT = {"type": "integer", "minimum": 0, "maximum": jobs.STATUS_WAIT_MAX,
        "description": f"op=status only: wait up to this many seconds for the job to end (default "
                       f"{jobs.STATUS_WAIT_DEFAULT}), so call status again at once, without sleeping"}
BOOL = {"type": "boolean"}
PORT_SCHEMA = schema({
    "op": {"type": "string", "enum": ["info", "read_source", "port", "inspect", "checklist", "adapter", "status", "cancel"]},
    "job": STRING, "wait_seconds": WAIT, "game": {"type": "string", "enum": list(GAMES)},
    "fighter": {"type": "string", "description": "Source identifier; reader uses Rivals capitalization (Ranno), port uses lowercase (ranno)"},
    "name": STRING, "donor": STRING,
    "work": {"type": "string", "description": "Dedicated absolute port work folder. Existing work resumes/rebuilds selected stages."},
    "root": {"type": "string", "description": "Absolute source root. For read_source, a NEW output folder."},
    "game_dir": {"type": "string", "description": "Slap City_Data or Rivals 2 installation; read_source only"},
    "list": BOOL, "own": BOOL, "body": STRING, "rip": STRING, "iso": STRING, "mextk": STRING,
    "from": STRING, "to": STRING, "only": STRING, "forms_from": STRING,
    "calibrate": {"type": "boolean", "description": "Optional developer gameplay calibration; default false"},
    "tests": {"type": "array", "items": STRING}, "allow_large": BOOL,
    "line": STRING, "answer": STRING, "how": STRING,
    "operation": {"type": "string", "enum": list(ADAPTERS)},
    "options": {"type": "object", "description": "Arguments for the selected advanced port_mcp adapter; absolute file paths"},
})
RIGSWAP_SCHEMA = schema({
    "op": {"type": "string", "enum": ["info", "import", "fix", "status", "cancel"]},
    "job": STRING, "wait_seconds": WAIT, "source": {"type": "string", "description": "Absolute model/archive path"},
    "fighter": {"type": "string", "description": "Melee fighter; omitted selects a suitable fighter automatically"},
    "name": STRING, "project": STRING,
    "change": {"type": "string", "description": "What should change in an existing import"},
    "said": {"type": "string", "description": "User's exact complaint, if change paraphrases it"},
})
TOOLS = [
    ("native_port", "Build native fighters with Nucleus's port engine and Slap City/Rivals 2 readers. Start op=info. Builds/readers/adapters return a durable job; follow it with op=status and job, which waits for it to end (wait_seconds) so it needs no sleeping between calls. op=inspect reads work receipts. Ports retain implementation limitations; gameplay calibration is optional.", PORT_SCHEMA, native_port),
    ("rigswap", "Import a model as a Melee costume through Randall's existing rigswap pipeline, save to vault, or fix a previous import. Start op=info. import/fix return a durable job; follow it with op=status, which waits for it to end (wait_seconds). Uses configured AI credentials. Native movesets use native_port instead.", RIGSWAP_SCHEMA, rigswap),
]
