"""The app's static copy of native_port and stage_workbench (randall/mcp/toolkit_schemas.py) matches the harness.

The installed app lists both tools without importing tools/ and forwards their calls to a creation toolkit
checkout (randall/mcp/toolkit.py). When the harness changes either tool, regenerate the copy from
``harness_mcp.TOOL_DEFS``.
"""
import sys

from tests.paths import REPO

sys.path[:0] = [str(REPO / "tools"), str(REPO / "tools/harness"), str(REPO / "app/backend")]
import harness_mcp as h  # noqa: E402
from randall.mcp import toolkit, toolkit_schemas  # noqa: E402


def test_static_copy_matches_the_harness():
    harness = {d["name"]: d for d in h.TOOL_DEFS if d["name"] in toolkit.FORWARDED}
    assert set(harness) == set(toolkit.FORWARDED)
    copied = {d["name"]: d for d in toolkit_schemas.TOOLS}
    assert copied == harness, "regenerate app/backend/randall/mcp/toolkit_schemas.py from harness_mcp.TOOL_DEFS"


def test_app_listing_only_prefixes_the_description():
    for listed, original in zip(toolkit.TOOLS, toolkit_schemas.TOOLS):
        assert listed["inputSchema"] == original["inputSchema"]
        assert listed["description"] == toolkit.NEEDS + original["description"]


def test_settings_guide_link_follows_the_repo_url():
    """Settings > AI > Creation toolkit opens SETUP.md in the same repository the tools' steps tell the AI to clone."""
    card = (REPO / "app/frontend/src/settings/CreationToolkitSection.jsx").read_text(encoding="utf-8")
    assert f"'{toolkit.REPO_URL}/blob/main/{toolkit.SETUP_SCRIPT.rsplit('/', 1)[0]}/SETUP.md'" in card
    assert (REPO / "tools/creation/SETUP.md").is_file()
