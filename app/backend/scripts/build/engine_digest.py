"""Write the in-game verification engine digest for a packaged build.

Why this exists
---------------
`shared.ingame.verify_costume.engine_version()` identifies the code that decides what
a capture looks like and what it means, and that identity is part of the cache
key: a change to the capture engine has to stop the app serving a verdict
produced by the previous one.

In a checkout it hashes the sources. A FROZEN build has no source tree, so
every one of those hashes came back `None` and collapsed to a single constant
id -- every packaged install would have shared one cache namespace and no code
change would ever have invalidated an entry.

So the build writes the digest instead. Run this before PyInstaller and bundle
the result at `shared/ingame/engine_digest.json`:

    python scripts/build/engine_digest.py --out backend/shared/ingame/engine_digest.json

The spec then includes it like any other data file. If the file is missing at
runtime the identity is `None` and NOTHING is cached, which is the safe way to
be wrong.
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def digest(sources=None):
    """The same document `engine_version()` builds from a checkout."""
    from shared.ingame.verify_costume import engine_source_paths
    parts, missing = {}, []
    for path in (sources or engine_source_paths()):
        path = Path(path)
        try:
            parts[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        except OSError:
            parts[path.name] = None
            missing.append(path.name)
    if missing:
        raise SystemExit("cannot build an engine digest: these sources are "
                         "missing from the tree being packaged: "
                         + ", ".join(missing))
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    document = {"schema": "harness-engine-version-v1", "sources": parts,
                "id": hashlib.sha256(canonical.encode()).hexdigest()[:16],
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "generated_by": "scripts/build/engine_digest.py"}
    # The external binaries, where the build machine can see them. These are
    # RECORDED, not folded into the id: the emulator and the build tools are
    # the user's, they differ per install, and the run-time toolchain identity
    # (`verify_costume.toolchain_identity`) is what keys them into the cache.
    try:
        from shared.ingame.verify_costume import toolchain_identity
        document["toolchain_at_build"] = toolchain_identity()
    except Exception as exc:
        document["toolchain_at_build"] = {"error": f"{type(exc).__name__}: {exc}"}
    return document


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(BACKEND / "shared" / "ingame" / "engine_digest.json"),
                        help="where to write the digest (bundle this file)")
    parser.add_argument("--print", action="store_true", dest="show",
                        help="print the digest instead of writing it")
    args = parser.parse_args(argv)
    document = digest()
    if args.show:
        print(json.dumps(document, indent=2))
        return 0
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, indent=2), encoding="utf-8")
    print(f"engine digest {document['id']} -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
