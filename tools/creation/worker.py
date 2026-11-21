"""Private subprocess entrypoint for the two creation MCP tools."""
from pathlib import Path
import sys
import traceback

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path[:0] = [str(HERE.parent), str(REPO / "app" / "backend")]
from creation import jobs


def execute(folder):
    from creation.workflows import execute as run
    request = jobs.read(folder / "request.json")
    try:
        result = run(request["tool"], request["args"], folder)
    except BaseException as exc:
        traceback.print_exc()
        result = dict(ok=False, error=f"{type(exc).__name__}: {exc}")
    jobs.write(folder / "result.json", result)
    return 0 if result.get("ok") is True else 1


if __name__ == "__main__":
    if sys.argv[1] == "--execute":
        raise SystemExit(execute(Path(sys.argv[2])))
    jobs.supervise(Path(sys.argv[1]))
