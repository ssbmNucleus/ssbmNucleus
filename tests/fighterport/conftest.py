"""Run the port engine's tests from the Nucleus repository."""
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
os.environ.setdefault("NUCLEUS_REPO", str(REPO))
sys.path[:0] = [str(REPO / "tools"), str(REPO / "tools" / "fighterport"), str(REPO / "app" / "backend")]
# Use the same optional local dependency paths as the MCP. CI without game data
# continues to skip the artifact tests; this never downloads dependencies.
from creation.workflows import ENV_KEYS, environment
_, configured = environment("native_port")
for key in ENV_KEYS:
    if configured.get(key):
        os.environ.setdefault(key, configured[key])
if os.environ.get("SSBH_DATA_PY"):
    sys.path.append(os.environ["SSBH_DATA_PY"])


def pytest_configure(config):
    config.addinivalue_line("markers", "native_artifact(*paths): requires local game artifacts")
