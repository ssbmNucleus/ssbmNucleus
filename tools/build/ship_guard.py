#!/usr/bin/env python3
"""
ship_guard.py -- the one implementation of "what may go into a packaged build".

Windows (build.bat), Linux (build-linux.sh), macOS (build-macos.sh) and the
PyInstaller spec (mex_backend.spec) all call THIS module, which reads THIS
directory's ship_rules.json. There is no second copy of the rules anywhere, on
purpose: build.bat used to stage + scrub + guard while the two shell scripts
packaged straight out of the working tree, and the shipped 0.7.0 AppImage
carried 5.6 MB of retail costume DATs that Windows had been stripping for
months. Rules in one file is the fix; keep it that way.

Subcommands
-----------
  stage  --platform win|linux|mac --stage DIR
         Build the disposable packaging stage: copy the manifest, apply the
         scrub rules, verify the critical artifacts. electron-builder then runs
         with --projectDir <stage>, so the working tree can never leak.

  scrub  --stage DIR
         Apply the scrub rules to an existing stage (stage does this for you).

  scan   --stage DIR [--backend PATH] [--project-root DIR] [--report FILE]
         Categorised inventory of everything the build would ship, with sizes,
         plus the retail/policy findings. This is the release gate.

Exit codes: 0 clean (or overridden), 1 findings block the build, 2 usage error.

Stdlib only -- it has to run on a bare Linux/mac build host with no venv.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULES_PATH = HERE / "ship_rules.json"
PROJECT_ROOT = HERE.parent.parent / "app"   # tools/build -> repo root -> app/

BLOCK, REVIEW, NOTE = "BLOCK", "REVIEW", "NOTE"
_SEV_ORDER = {BLOCK: 0, REVIEW: 1, NOTE: 2}


# --------------------------------------------------------------------------
# rules
# --------------------------------------------------------------------------

_RULES_CACHE = None


def load_rules():
    global _RULES_CACHE
    if _RULES_CACHE is None:
        with open(RULES_PATH, "r", encoding="utf-8") as fh:
            _RULES_CACHE = json.load(fh)
    return _RULES_CACHE


def _glob_to_re(pattern: str) -> "re.Pattern":
    """Translate a path glob to a regex.

    ``**`` spans directories, ``*`` and ``?`` do not cross ``/``.  Matching is
    case-insensitive so a Windows stage and a Linux stage give the same verdict.
    """
    out, i, n = [], 0, len(pattern)
    while i < n:
        if pattern.startswith("**/", i):
            out.append("(?:[^/]+/)*")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        elif pattern[i] == "[":
            j = pattern.find("]", i)
            if j == -1:
                out.append(re.escape("["))
                i += 1
            else:
                out.append(pattern[i:j + 1])
                i = j + 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE)


def _compile_globs(patterns):
    return [_glob_to_re(p) for p in (patterns or [])]


def csp_data_excluded(name: str) -> bool:
    """True if a csp_data file must never be bundled.

    mex_backend.spec calls this instead of keeping its own copy of the Pl*/Ty*/
    CSP_2.zip/MnSlChr*/portrait list.  Derived from EVERY scrub rule that targets
    ``csp_data`` (currently ``csp-data-roster`` and ``csp-data-portraits``) so the
    frozen backend and the electron stage can't disagree -- the spec embeds the
    same tree the stage copies, and a scrub rule that only reached one of the two
    is how retail data kept shipping inside mex_backend.

    Matching is on the basename: the spec walks csp_data itself, so the directory
    prefix is already implied, and every pattern here is rooted at csp_data.
    """
    for rule in load_rules().get("scrub", []):
        for pat in rule.get("delete", []):
            if "/csp_data/" not in pat:
                continue
            leaf = pat.rsplit("/", 1)[-1]
            if _glob_to_re(leaf).match(name):
                return True
    return False


def detect_excluded(category_id: str, rel: str) -> bool:
    """True if `rel` is caught by the named ``detect`` category.

    For trees the electron stage never copies -- ``backend/assets`` only reaches
    an installer folded inside mex_backend -- there is nothing for ``scrub`` to
    delete, so the spec asks the detect category directly.  Same single-source
    argument as csp_data_excluded: whatever the guard would FLAG in a shipped
    artifact is exactly what the spec must not put there, and the two cannot
    drift apart because they read one list.

    `rel` is the project-root-relative posix path, e.g.
    ``backend/assets/hud_vanilla/glyph_0.png``.
    """
    rel = rel.replace("\\", "/")
    name = rel.rsplit("/", 1)[-1]
    for cat in load_rules().get("detect", {}).get("categories", []):
        if cat.get("id") == category_id:
            return _cat_hit(_category_matchers(cat), rel, name)
    raise KeyError(f"no detect category named {category_id!r}")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def human(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num) < 1024.0 or unit == "GB":
            return f"{num:,.0f} {unit}" if unit == "B" else f"{num:,.1f} {unit}"
        num /= 1024.0
    return f"{num} B"


def _iter_files(root: Path):
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            yield Path(dirpath) / fn


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def gate_ships(name: str) -> bool:
    """True when release gate `name` is ON in the build being packaged: asked
    for as a preview feature (NUCLEUS_PREVIEW_FEATURES, the build.bat selector),
    or no longer forced off in packaged builds by app/backend/core/gates.py
    (the assistant, since 0.9.0). Entries tagged "ships_with_gate" follow this,
    so a gated feature's payload (rigswap's package and the model import tools'
    manifest for Randall's model import) ships exactly when the feature does; the build scripts ask
    `ship_guard.py gate assistant` before building the frontend, and
    mex_backend.spec and the frozen build smoke apply the same rule."""
    wanted = {f.strip().lower() for f in os.environ.get("NUCLEUS_PREVIEW_FEATURES", "").split(",")}
    if name.lower() in wanted:
        return True
    gates = _gates_table()
    gate = gates.GATES.get(name)
    if gate is None:
        raise SystemExit(f"ship_rules.json names an unknown gate: {name}")
    return not gate.packaged_off or gate_ships_in_stable(name)


def _gates_table():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "nucleus_release_gates", PROJECT_ROOT / "backend" / "core" / "gates.py")
    gates = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gates)
    return gates


def gate_ships_in_stable(name: str) -> bool:
    """True when packaged_off gate `name` is opened in stable builds of this platform all
    the same (gates.release_features: Play once PLAY_IN_STABLE is True, Windows only).
    build.bat then writes it into the packaged manifest as releaseFeatures, which
    electron/main.js reads."""
    return name.lower() in _gates_table().release_features()


#: The lazy frontend chunk each gated surface builds into (Vite names a chunk
#: after the module it splits off). A build whose gate is closed folds the
#: import away (frontend/src/shared/config/features.js), so the chunk must be
#: absent; finding one means the fold broke and unreleased UI would ship. A
#: build whose gate ships must have it: a missing one means the frontend was
#: built without its flag, and the backend would ship with no UI to reach it.
GATED_FRONTEND_CHUNKS = {
    "assistant": ("AssistantPanel",),
    "randall": ("CoachPage",),
    "combo_video": ("ComboVideoPage",),
    "play": ("PlayApp",),
}


def gated_frontend_leaks(root: Path) -> list:
    """Chunks in `root`/frontend/dist/assets that a closed gate must not ship."""
    assets = root / "frontend" / "dist" / "assets"
    if not assets.is_dir():
        return []
    leaks = []
    for gate, chunks in GATED_FRONTEND_CHUNKS.items():
        if gate_ships(gate):
            continue
        for chunk in chunks:
            leaks += [f"frontend/dist/assets/{f.name} ({gate} does not ship in this build)"
                      for f in sorted(assets.glob(f"{chunk}-*"))]
    return leaks


def gated_frontend_missing(root: Path) -> list:
    """Chunks a gate that ships in this build should have put in `root`/frontend/dist/assets."""
    assets = root / "frontend" / "dist" / "assets"
    if not assets.is_dir():
        return []
    return [f"frontend/dist/assets/{chunk}-*.js ({gate} ships in this build)"
            for gate, chunks in GATED_FRONTEND_CHUNKS.items() if gate_ships(gate)
            for chunk in chunks if not any(assets.glob(f"{chunk}-*.js"))]


def _assert_stage(stage: Path) -> None:
    """Refuse to mutate anything that is not one of our own stages.

    ``scrub`` deletes files.  A typo'd --stage pointing at the repo would be
    unrecoverable, so every stage carries a marker file and nothing without one
    is ever written to.
    """
    marker = load_rules().get("stage_marker", ".nucleus-package-stage")
    if not (stage / marker).is_file():
        raise SystemExit(
            f"refusing to touch {stage}: no {marker} marker.\n"
            "Only a stage created by `ship_guard.py stage` may be scrubbed."
        )


# --------------------------------------------------------------------------
# stage
# --------------------------------------------------------------------------

def cmd_stage(args) -> int:
    rules = load_rules()
    root = Path(args.project_root).resolve()
    stage = Path(args.stage).resolve()

    if stage == root or root in stage.parents and stage.name in ("", "."):
        raise SystemExit(f"refusing to use {stage} as a stage")

    print(f"Preparing clean packaging stage: {stage}")
    if stage.exists():
        if not args.keep and not (stage / rules["stage_marker"]).is_file():
            raise SystemExit(
                f"{stage} exists but has no {rules['stage_marker']} marker -- "
                "refusing to delete it. Move it aside or pick another path."
            )
        if not args.keep:
            shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)
    (stage / rules["stage_marker"]).write_text(
        "Disposable electron-builder packaging stage created by "
        "tools/build/ship_guard.py. Safe to delete.\n", encoding="utf-8")

    for d in rules["stage"].get("mkdirs", []):
        (stage / d).mkdir(parents=True, exist_ok=True)

    entries = list(rules["stage"].get("common", [])) + list(rules["stage"].get(args.platform, []))
    missing = []
    for ent in entries:
        src = root / ent["src"]
        dst = stage / ent["dst"]
        if ent.get("ships_with_gate") and not gate_ships(ent["ships_with_gate"]):
            print(f"  skip (gate '{ent['ships_with_gate']}' is off in this build): {ent['src']}")
            continue
        if not src.exists():
            if ent.get("optional"):
                print(f"  skip (optional, absent): {ent['src']}")
            elif args.rehearse:
                print(f"  MISSING (rehearsal, ignored): {ent['src']}")
            else:
                print(f"  ERROR: missing {ent['src']}")
                missing.append(ent["src"])
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if ent["kind"] == "dir":
            ignore = shutil.ignore_patterns(*ent.get("exclude", [])) if ent.get("exclude") else None
            shutil.copytree(
                src, dst, dirs_exist_ok=True, symlinks=True, ignore=ignore
            )
        else:
            shutil.copy2(src, dst)
        print(f"  staged {ent['src']} -> {ent['dst']}")

    if missing:
        print("\nRefusing to package: the build did not produce these inputs.")
        for m in missing:
            print(f"   {m}")
        return 1

    if not args.rehearse:
        rc = _install_production_dependencies(stage)
        if rc:
            return rc

    rc = _scrub(stage)
    if rc:
        return rc

    if args.rehearse:
        print()
        print("REHEARSAL: build outputs were not required and artifacts were not")
        print("verified. This stage is INCOMPLETE and must not be packaged.")
        return 0

    if not args.no_verify:
        rc = _verify(stage, args.platform, rules)
        if rc:
            return rc
    # Every real release, on every platform, exercises the staged helper.
    # --no-verify only skips the file inventory; it cannot waive this check.
    from music_tools_smoke import MusicToolsError, verify_stage_music_tools
    try:
        verify_stage_music_tools(stage, args.platform)
    except MusicToolsError as exc:
        print(f'Refusing to package: music tools check failed: {exc}')
        return 1
    return 0


def _install_production_dependencies(stage: Path) -> int:
    """Recreate the staged Node runtime dependencies from the lockfile.

    Copying a developer's ``node_modules`` makes the package depend on whatever
    happens to be installed locally. The staged app only needs the production
    dependency set (currently ``ws``), so install exactly the lockfile and do
    not run package lifecycle scripts in the disposable stage.
    """
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        print("  ERROR: npm not found; cannot install staged runtime dependencies")
        return 1

    print("\nInstalling locked production Node dependencies in the stage...")
    result = subprocess.run(
        [npm, "ci", "--omit=dev", "--ignore-scripts", "--no-audit", "--no-fund"],
        cwd=stage,
        check=False,
    )
    if result.returncode:
        print("  ERROR: staged `npm ci --omit=dev` failed")
        return 1
    print("  production dependencies match package-lock.json")
    return 0


# --------------------------------------------------------------------------
# scrub
# --------------------------------------------------------------------------

def _scrub(stage: Path) -> int:
    _assert_stage(stage)
    rules = load_rules()
    print("\nScrubbing ISO-derived and unreleased content from the stage "
          "(the stage is disposable; the source tree is untouched)...")
    total_files = 0
    total_bytes = 0
    for rule in rules.get("scrub", []):
        removed, freed = 0, 0
        for rel in rule.get("delete_dirs", []):
            for target in _resolve_glob_dirs(stage, rel):
                for f in _iter_files(target):
                    freed += f.stat().st_size
                    removed += 1
                shutil.rmtree(target, ignore_errors=True)
        matchers = _compile_globs(rule.get("delete", []))
        kept = _compile_globs(rule.get("keep", []))     # runtime payload a wide delete glob would also catch
        if matchers:
            for f in list(_iter_files(stage)):
                r = _rel(f, stage)
                if any(m.match(r) for m in matchers) and not any(k.match(r) for k in kept):
                    freed += f.stat().st_size
                    removed += 1
                    try:
                        f.unlink()
                    except OSError as exc:
                        print(f"  ERROR: could not delete {r}: {exc}")
                        return 1
        total_files += removed
        total_bytes += freed
        print(f"  {rule['id']}: removed {removed} file(s), {human(freed)}")
    print(f"  total scrubbed: {total_files} file(s), {human(total_bytes)}")
    return 0


def _resolve_glob_dirs(stage: Path, rel: str):
    if any(ch in rel for ch in "*?["):
        rx = _glob_to_re(rel)
        for dirpath, dirnames, _ in os.walk(stage):
            for d in list(dirnames):
                p = Path(dirpath) / d
                if rx.match(_rel(p, stage)):
                    yield p
    else:
        p = stage / rel
        if p.is_dir():
            yield p


def cmd_scrub(args) -> int:
    return _scrub(Path(args.stage).resolve())


def cmd_gate(args) -> int:
    """Exit 0 when release gate `args.name` ships in this build, 1 when it is left out.
    The build scripts use it to build the frontend half of the gate the same way."""
    if getattr(args, "stable", False):
        ships = gate_ships_in_stable(args.name)
        print(f"Release gate {args.name}: {'opened' if ships else 'not opened'} by releaseFeatures in this build")
        return 0 if ships else 1
    ships = gate_ships(args.name)
    print(f"Release gate {args.name}: {'ships' if ships else 'left out'} in this build")
    return 0 if ships else 1


# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------

def _verify(stage: Path, platform: str, rules) -> int:
    print("\nVerifying critical bundle artifacts...")
    wanted = []
    for w in list(rules["verify"].get("common", [])) + list(rules["verify"].get(platform, [])):
        if isinstance(w, dict):     # {"path", "ships_with_gate"}: required only when the gate ships
            if not gate_ships(w["ships_with_gate"]):
                continue
            w = w["path"]
        wanted.append(w)
    missing = [w for w in wanted if not (stage / w).exists()]
    for w in missing:
        print(f"  ERROR: {w} missing from the stage")
    if missing:
        print("\nRefusing to package an installer with missing critical artifacts.")
        return 1
    print(f"  {len(wanted)} artifact(s) present.")
    leaks = gated_frontend_leaks(stage)
    for line in leaks:
        print(f"  ERROR: unreleased UI in the bundle: {line}")
    if leaks:
        print("\nRefusing to package unreleased feature code: rebuild the frontend without the preview flag.")
        return 1
    absent = gated_frontend_missing(stage)
    for line in absent:
        print(f"  ERROR: shipped feature without its UI: {line} is missing")
    if absent:
        print("\nRefusing to package a feature with no way to reach it: build the frontend with "
              "VITE_ASSISTANT_PREVIEW=1 (the build scripts set it when `ship_guard.py gate assistant` passes).")
        return 1
    stale = _stale_trees(stage)
    for line in stale:
        print(f"  ERROR: {line}")
    if stale:
        print("\nRefusing to package a tree fetched before its pin moved: rerun its tools/build/fetch_*.py.")
        return 1
    return 0


def _stale_trees(stage: Path) -> list:
    """Each fetched tree in the stage whose receipt no longer matches its manifest: the archive's sha256, and for
    rigswap's package (utility/rigswap/app) its commit. A pin moved without a re-fetch would otherwise ship the old
    tree."""
    stale = []
    receipts = sorted(stage.glob("utility/*/.fetch-receipt.json")) + sorted(stage.glob("utility/*/*/.fetch-receipt.json"))
    for path in receipts:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        manifest_path = PROJECT_ROOT / str(receipt.get("manifest") or "")
        if not receipt.get("manifest") or not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if "rigswap" in manifest:
            pins = {"rigswap_commit": manifest["rigswap"]["commit"]}
        elif isinstance(manifest.get("sha256"), str):
            pins = {"sha256": manifest["sha256"]}
        else:
            continue        # a per-platform manifest (hsdlib, mex): fetch_native checks those
        moved = [k for k, v in pins.items() if receipt.get(k) != v]
        if moved:
            stale.append(f"{path.parent.relative_to(stage).as_posix()} was fetched for other pins than "
                         f"{receipt['manifest']} holds now ({', '.join(moved)})")
    return stale


# --------------------------------------------------------------------------
# scan
# --------------------------------------------------------------------------

class Finding:
    __slots__ = ("rel", "size", "root_label")

    def __init__(self, rel, size, root_label):
        self.rel, self.size, self.root_label = rel, size, root_label


def _category_matchers(cat):
    return {
        "within": _compile_globs(cat.get("within")),
        "paths": _compile_globs(cat.get("paths")),
        "names": _compile_globs(cat.get("names")),
        "exts": {e.lower() for e in cat.get("exts", [])},
        "except_paths": _compile_globs(cat.get("except_paths")),
        "except_names": _compile_globs(cat.get("except_names")),
    }


def _cat_hit(m, rel: str, name: str) -> bool:
    """``within`` is a scope (AND); ``paths``/``names``/``exts`` are alternatives (OR).

    So "any .wav under vanilla/sounds" is within + exts, while "css_template.png
    anywhere, or anything called MnSlChr*" is two entries in paths/names.
    """
    if any(x.match(rel) for x in m["except_paths"]):
        return False
    if any(x.match(name) for x in m["except_names"]):
        return False
    if m["within"] and not any(x.match(rel) for x in m["within"]):
        return False
    if not (m["paths"] or m["names"] or m["exts"]):
        return bool(m["within"])
    return (any(x.match(rel) for x in m["paths"])
            or any(x.match(name) for x in m["names"])
            or Path(name).suffix.lower() in m["exts"])


def _iter_asar(asar: Path):
    """Yield (internal_path, size) for an electron .asar archive.

    The stage scan does not need this -- before packaging, frontend/dist is loose.
    It matters when pointing `scan` at an already-built artifact (an extracted
    AppImage, an installed app), where the frontend has been folded into
    app.asar and would otherwise read as clean.  Header: 4-byte pickle length,
    4-byte header-size pickle, 4-byte string length, then the JSON directory.
    """
    import struct
    with open(asar, "rb") as fh:
        head = fh.read(16)
        if len(head) < 16:
            return
        json_len = struct.unpack("<I", head[12:16])[0]
        raw = fh.read(json_len)
    try:
        tree = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return

    def walk(node, prefix=""):
        for name, val in node.get("files", {}).items():
            path = f"{prefix}/{name}" if prefix else name
            if "files" in val:
                yield from walk(val, path)
            else:
                yield path, int(val.get("size", 0))

    yield from walk(tree)


def _scan_tree(root: Path, label: str, cats, findings, inventory, prefix: str = "",
               exclude=None, include=None):
    """Walk a tree.

    ``prefix`` restores the path a file will HAVE in the shipped product when the
    scan root is not the product root -- the embedded_roots are scanned straight
    out of the project (e.g. backend/assets), but inside the frozen exe they live
    at backend/assets/..., and the rules are written against that shipped path.

    ``exclude`` and ``include`` are both PROXIES for what the spec actually
    bundles, and both are only as honest as the spec they mirror.  Use
    ``exclude`` when the spec takes the whole tree minus a filter: the source
    tree still holds the filtered-out files, the exe does not, and reporting
    them would be a false positive.  It stays honest only while the spec derives
    that filter from this same rules file (see mex_backend.spec's
    detect_excluded call), and it must never quiet a tree that really does ship.
    Use ``include`` for the opposite shape -- the spec names an explicit handful
    of files out of a larger source directory (mex_backend.spec lists
    backend/data's two JSON files one by one).  Anything not matching an
    ``include`` glob is not in the exe, so scanning it would report source-only
    leftovers (stale ``__pycache__``, scratch files) as shipped content.  Both
    lists match the SHIPPED path, i.e. after ``prefix`` is applied, and both must
    be kept in step with the spec by hand.
    """
    ex_matchers = _compile_globs(exclude)
    inc_matchers = _compile_globs(include)
    for f in _iter_files(root):
        rel = _rel(f, root)
        inv_top = rel.split("/")[0] if "/" in rel else "(root files)"
        if prefix:
            rel = f"{prefix}/{rel}"
        if inc_matchers and not any(m.match(rel) for m in inc_matchers):
            continue
        if any(m.match(rel) for m in ex_matchers):
            continue
        try:
            size = f.stat().st_size
        except OSError:
            size = 0
        _record(rel, size, label, cats, findings, inventory, inv_top)
        if f.suffix.lower() == ".asar":
            # Contents count towards findings but not the inventory -- the
            # archive's own on-disk size is already counted above.
            for inner, isize in _iter_asar(f):
                _record(f"{rel}!/{inner}", isize, label, cats, findings, None)


def _record(rel, size, label, cats, findings, inventory, inv_top=None):
    if inventory is not None:
        top = inv_top or (rel.split("/")[0] if "/" in rel else "(root files)")
        bucket = inventory.setdefault((label, top), [0, 0])
        bucket[0] += 1
        bucket[1] += size
    name = rel.rsplit("/", 1)[-1]
    for cat, m in cats:
        if _cat_hit(m, rel, name):
            findings.setdefault(cat["id"], []).append(Finding(rel, size, label))
            break  # first (highest-severity) category wins


def _scan_backend_exe(exe: Path, patterns):
    """String-scan the frozen backend.

    PyInstaller's onefile archive stores every embedded data file's path as a
    literal, so retail paths inside the exe are visible as latin1 text.  Sizes
    are not recoverable this way -- that is what embedded_roots is for.
    """
    blob = exe.read_bytes().decode("latin1")
    out = {}
    for sev, pats in (("BLOCK", patterns.get("block", [])),
                      ("REVIEW", patterns.get("review", []))):
        hits = set()
        for p in pats:
            hits.update(m.group(0) for m in re.finditer(p, blob))
        if hits:
            out[sev] = sorted(hits)
    return out


def cmd_scan(args) -> int:
    rules = load_rules()
    detect = rules["detect"]
    cats = [(c, _category_matchers(c)) for c in detect["categories"]]
    cats.sort(key=lambda cm: _SEV_ORDER[cm[0]["severity"]])

    findings: dict[str, list] = {}
    inventory: dict[tuple, list] = {}
    roots_scanned = []

    stage = Path(args.stage).resolve() if args.stage else None
    if stage and stage.is_dir():
        _scan_tree(stage, "stage", cats, findings, inventory)
        roots_scanned.append(("stage (loose files in the installer)", stage))
    elif stage:
        print(f"WARN: stage not found at {stage} (skipping stage scan)")

    project_root = Path(args.project_root).resolve()
    if not args.no_embedded:
        for ent in rules["embedded_roots"]["roots"]:
            src = project_root / ent["src"]
            if not src.is_dir():
                if not ent.get("optional"):
                    print(f"WARN: embedded root missing: {ent['src']}")
                continue
            _scan_tree(src, f"inside mex_backend: {ent['src']}", cats, findings,
                       inventory, prefix=ent["src"], exclude=ent.get("exclude"),
                       include=ent.get("include"))
            roots_scanned.append((f"inside mex_backend: {ent['src']}", src))

    exe_hits = {}
    backend = Path(args.backend).resolve() if args.backend else None
    if backend and backend.is_file():
        exe_hits = _scan_backend_exe(backend, detect["backend_exe_patterns"])
    elif backend:
        print(f"WARN: backend not found at {backend} (skipping exe string scan)")

    lines = _render(rules, cats, findings, inventory, roots_scanned, exe_hits,
                    stage, backend)

    override = os.environ.get(rules["override_env"], "") == "1"
    blocked = any(c["severity"] == BLOCK and findings.get(c["id"]) for c, _ in cats)
    blocked = blocked or "BLOCK" in exe_hits
    review = any(c["severity"] == REVIEW and findings.get(c["id"]) for c, _ in cats)
    review = review or "REVIEW" in exe_hits

    lines += _verdict(rules, blocked, review, override)
    text = "\n".join(lines)
    print(text)

    if args.report:
        rp = Path(args.report)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(_full_report(text, findings, cats), encoding="utf-8")
        print(f"\nFull per-file inventory written to {rp}")

    if args.json:
        jp = Path(args.json)
        jp.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "blocked": blocked, "review": review, "override": override,
            "categories": {
                cid: {
                    "severity": next(c["severity"] for c, _ in cats if c["id"] == cid),
                    "count": len(fs),
                    "bytes": sum(f.size for f in fs),
                    "files": [{"path": f.rel, "bytes": f.size, "root": f.root_label} for f in fs],
                } for cid, fs in findings.items()
            },
            "backend_exe": exe_hits,
        }
        jp.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if blocked:
        return 1
    if review and not override:
        return 1
    return 0


def _render(rules, cats, findings, inventory, roots_scanned, exe_hits, stage, backend):
    L = []
    L.append("=" * 78)
    L.append(" SSBM Nucleus ship guard -- everything this build would put on a user's disk")
    L.append("=" * 78)

    if not roots_scanned and not backend:
        L.append("NOTHING SCANNED -- pass --stage and/or --backend.")
        return L

    L.append("")
    L.append("SHIP INVENTORY")
    L.append("  (The stage is scanned BEFORE electron-builder applies package.json's")
    L.append("   file filters. The stage is therefore an exact allowlist and anything")
    L.append("   present here is conservatively treated as shipping.)")
    by_root = {}
    for (label, top), (n, b) in inventory.items():
        by_root.setdefault(label, []).append((top, n, b))
    for label, rows in by_root.items():
        tot_n = sum(r[1] for r in rows)
        tot_b = sum(r[2] for r in rows)
        L.append(f"  {label}  --  {tot_n:,} files, {human(tot_b)}")
        for top, n, b in sorted(rows, key=lambda r: -r[2])[:12]:
            L.append(f"      {top:<44} {n:>7,} files  {human(b):>12}")
    if backend and backend.is_file():
        L.append(f"  frozen backend {backend.name:<32} {human(backend.stat().st_size):>12}")

    L.append("")
    L.append("RETAIL / POLICY FINDINGS")
    any_found = False
    for cat, _m in cats:
        fs = findings.get(cat["id"])
        if not fs:
            L.append(f"  [ ok ] {cat['id']:<32} clean")
            continue
        any_found = True
        total = sum(f.size for f in fs)
        L.append("")
        L.append(f"  [{cat['severity']:^6}] {cat['id']} -- {cat['title']}")
        L.append(f"           {len(fs):,} file(s), {human(total)}")
        L.append(f"           why: {cat['why']}")
        shown = sorted(fs, key=lambda f: -f.size)[:8]
        for f in shown:
            L.append(f"             {f.rel}  ({human(f.size)})  [{f.root_label}]")
        if len(fs) > len(shown):
            L.append(f"             ... and {len(fs) - len(shown):,} more "
                     f"(use --report for the complete list)")

    if exe_hits:
        any_found = True
        L.append("")
        L.append("  frozen backend exe -- retail paths found in the PyInstaller archive TOC")
        for sev, hits in exe_hits.items():
            L.append(f"    [{sev}] {len(hits)} distinct path string(s)")
            for h in hits[:12]:
                L.append(f"           {h}")
            if len(hits) > 12:
                L.append(f"           ... and {len(hits) - 12} more")

    if not any_found:
        L.append("  nothing matched -- no retail-derived or unreleased content detected.")
    return L


def _verdict(rules, blocked, review, override):
    env = rules["override_env"]
    L = ["", "-" * 78]
    if blocked:
        L.append("VERDICT: BLOCKED.")
        L.append("BLOCK-severity content is in the build. Every BLOCK category is")
        L.append("supposed to be removed by a scrub rule in ship_rules.json, so this")
        L.append("means the tree and the rules have drifted: fix one of them. There is")
        L.append(f"no override for BLOCK -- {env} does not apply.")
        return L
    if review and not override:
        L.append("VERDICT: BLOCKED (unresolved retail assets).")
        L.append("None of it is a regression -- these files ship in 0.7.0 today. They")
        L.append("are retail-derived and load-bearing, and the decision to keep, gate")
        L.append("or source-them-from-the-user's-ISO belongs to the project owner.")
        L.append("")
        L.append("To produce a LOCAL build while that decision is open, set the")
        L.append("override and re-run the build script:")
        L.append(f"    Windows:  set {env}=1")
        L.append(f"    Unix:     export {env}=1")
        L.append("A build made that way MUST NOT be published. There is no allowlist")
        L.append("for these categories on purpose -- the override has to be typed, and")
        L.append("it prints a banner every time.")
        return L
    if review and override:
        L.append("!!! " + "=" * 70)
        L.append(f"!!! {env}=1 IS SET.")
        L.append("!!! Unresolved retail-derived assets were found and allowed through.")
        L.append("!!! THIS BUILD IS FOR LOCAL USE ONLY. DO NOT PUBLISH OR DISTRIBUTE IT.")
        L.append("!!! " + "=" * 70)
        L.append("VERDICT: PASS (overridden).")
        return L
    L.append("VERDICT: PASS -- no retail-derived or unreleased content detected.")
    return L


def _full_report(console_text, findings, cats):
    out = [console_text, "", "=" * 78, " COMPLETE PER-FILE INVENTORY", "=" * 78]
    for cat, _m in cats:
        fs = findings.get(cat["id"])
        if not fs:
            continue
        out.append("")
        out.append(f"[{cat['severity']}] {cat['id']} -- {cat['title']}  "
                   f"({len(fs):,} files, {human(sum(f.size for f in fs))})")
        for f in sorted(fs, key=lambda f: f.rel):
            out.append(f"    {f.size:>12,}  {f.rel}   [{f.root_label}]")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("stage", help="build the packaging stage (copy + scrub + verify)")
    p.add_argument("--platform", required=True, choices=["win", "linux", "mac"])
    p.add_argument("--stage", required=True)
    p.add_argument("--project-root", default=str(PROJECT_ROOT))
    p.add_argument("--keep", action="store_true", help="do not wipe an existing stage")
    p.add_argument("--no-verify", action="store_true")
    p.add_argument("--rehearse", action="store_true",
                   help="stage only what the working tree already has, skip verify. "
                        "For validating rule changes without a full 2-hour build; "
                        "the resulting stage is incomplete and unpackageable.")
    p.set_defaults(func=cmd_stage)

    p = sub.add_parser("scrub", help="apply the scrub rules to an existing stage")
    p.add_argument("--stage", required=True)
    p.set_defaults(func=cmd_scrub)

    p = sub.add_parser("gate", help="exit 0 if a release gate ships in this build, 1 if not")
    p.add_argument("name", help="a gate name from app/backend/core/gates.py, e.g. assistant")
    p.add_argument("--stable", action="store_true",
                   help="exit 0 only if the gate is packaged_off but opened in stable builds all the "
                        "same (gates.release_features; build.bat writes it as releaseFeatures)")
    p.set_defaults(func=cmd_gate)

    p = sub.add_parser("scan", help="categorised inventory + release gate")
    p.add_argument("--stage", help="packaging stage, or any extracted build tree")
    p.add_argument("--backend", help="frozen mex_backend[.exe] to string-scan")
    p.add_argument("--project-root", default=str(PROJECT_ROOT))
    p.add_argument("--no-embedded", action="store_true",
                   help="skip the trees mex_backend.spec embeds in the exe")
    p.add_argument("--report", help="write the complete per-file inventory here")
    p.add_argument("--json", help="write machine-readable findings here")
    p.set_defaults(func=cmd_scan)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - a build gate must explain itself
        print(f"ship_guard: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
