import io
import sys

import pytest
from PIL import Image

from tests.paths import REPO

sys.path.insert(0, str(REPO / "tools" / "harness"))
import harness_mcp as h
from shared.ingame import capture


def test_stage_workbench_is_registered_and_guide_loads():
    assert "stage_workbench" in h.HANDLERS
    result = h.HANDLERS["stage_workbench"]({"op": "guide"}, lambda _: None)
    assert "graft" in result["operations"]
    assert "freeform" in result["guide"]


def test_sweep_returns_every_view_and_fails_if_one_is_missing(tmp_path, monkeypatch):
    image = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(image, "PNG")
    views = [{"eye": [0, 0, 100], "interest": [0, 0, 0], "fov": 30, "name": "center"},
             {"eye": [40, 0, 100], "interest": [40, 0, 0], "fov": 30, "name": "ledge"}]
    calls = {}

    def run(*args, **kwargs):
        calls.update(kwargs)
        return {"ok": True, "shots": [{"png": image.getvalue(), "framing": views[0]},
                                       {"png": None, "reason": "capture failed", "framing": views[1]}]}

    monkeypatch.setattr(h, "_no_session", lambda _: None)
    monkeypatch.setattr(h, "_resolve_iso", lambda _: tmp_path / "input.iso")
    monkeypatch.setattr(h, "MCP_OUT", tmp_path)
    monkeypatch.setattr(h.fs, "RUNS_ROOT", tmp_path)
    monkeypatch.setattr(capture, "capture_stage", run)
    result = h.t_stage_shot({"stage": "battlefield", "framing_sweep": views}, lambda _: None)
    assert calls["framing_sweep"] == views
    assert result["ok"] is False
    assert result["shots"][0]["ok"] is True
    assert result["shots"][1]["ok"] is False
    assert "file" not in result["shots"][1]
    assert "_image" in result


@pytest.mark.parametrize("args", [
    {"framing_sweep": []},
    {"framing_sweep": [{"eye": [0, 0, 1], "interest": [0, 0, 0]}], "pause": True},
    {"framing_sweep": [{"eye": [0, 0, float('nan')], "interest": [0, 0, 0]}]},
])
def test_bad_sweep_does_not_launch_dolphin(args, monkeypatch):
    monkeypatch.setattr(h, "_no_session", lambda _: pytest.fail("must validate before emulator work"))
    with pytest.raises(ValueError):
        h.t_stage_shot(args, lambda _: None)
