import json
from pathlib import Path
import struct
import zipfile

import pytest
from PIL import Image

from tools.stages import workbench as w


def test_mesh_to_package_preserves_pixels_and_triangle_payload(tmp_path):
    texture = tmp_path / "paint.png"
    Image.new("RGBA", (4, 4), (15, 25, 35, 255)).save(texture)
    vertices = [[0, 0, 0, 0, 0, 1, 1, 1, 1], [1, 0, 0, 1, 0, 1, 1, 1, 1], [0, 1, 0, 0, 1, 1, 1, 1, 1]]
    src = tmp_path / "mesh.json"
    src.write_text(json.dumps({"texture": "paint.png", "vertices": vertices}))
    entry = w.handle({"op": "mesh", "spec": str(src), "out": str(tmp_path / "tri")})
    assert Path(entry["mesh"]).read_bytes() == struct.pack("<i27f", 3, *(v for row in vertices for v in row))
    assert Path(entry["tex"]).read_bytes() == struct.pack("<ii", 4, 4) + bytes((35, 25, 15, 255)) * 16
    w.validate_meshes({"cs": {"meshes": [entry]}})


def test_invalid_mesh_refuses_before_native_or_output(tmp_path, monkeypatch):
    target = tmp_path / "base.dat"
    target.write_bytes(b"base")
    mesh = tmp_path / "broken.mesh"
    mesh.write_bytes(struct.pack("<i", 3))
    texture = tmp_path / "texture.img"
    texture.write_bytes(b"")
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"target": "base.dat", "receive_group": 0,
                              "cs": {"meshes": [{"mesh": "broken.mesh", "tex": "texture.img"}]}}))
    monkeypatch.setattr(w, "native", lambda log: pytest.fail("native should not run"))
    dest = tmp_path / "new.dat"
    with pytest.raises(ValueError, match="Invalid triangle mesh"):
        w.handle({"op": "graft", "spec": str(spec), "out": str(dest)})
    assert not dest.exists()
    assert target.read_bytes() == b"base"


def test_resolve_spec_keeps_freeform_fields_and_resolves_assets(tmp_path):
    for name in ("base.dat", "scene.rdat", "front.img"):
        (tmp_path / name).write_bytes(b"data")
    spec, inputs = w.resolve_spec({"target": "base.dat", "receive_group": 1,
        "donors": [{"file": "scene.rdat", "path": {"frames": 180, "points": [[0, 1, 2]]}}],
        "item_card": {"front": ["front.img"], "back": ["front.img"]},
        "creative_future_option": {"placement": 4}}, tmp_path)
    assert spec["donors"][0]["file"] == str(tmp_path / "scene.rdat")
    assert spec["donors"][0]["path"]["frames"] == 180
    assert spec["creative_future_option"] == {"placement": 4}
    assert len(inputs) == 4


def test_mipmap_dimensions_are_checked(tmp_path):
    m = tmp_path / "a.mesh"
    t = tmp_path / "a.img"
    m.write_bytes(struct.pack("<i27f", 3, *([0.0] * 27)))
    t.write_bytes(struct.pack("<ii", 3, 4) + bytes(3 * 4 * 4))
    entry = {"mesh": str(m), "tex": str(t)}
    warnings = w.validate_meshes({"cs": {"meshes": [entry]}})
    assert len(warnings) == 1 and "power-of-two" in warnings[0]
    entry["mips"] = False
    assert w.validate_meshes({"cs": {"meshes": [entry]}}) == []


def test_output_refuses_source_and_existing_revision(tmp_path):
    existing = tmp_path / "stage.dat"
    existing.write_bytes(b"keep")
    with pytest.raises(ValueError, match="overwrite an input"):
        w.output_path(existing, [existing])
    with pytest.raises(ValueError, match="already exists"):
        w.write_new(w.output_path(existing), b"replace")
    assert existing.read_bytes() == b"keep"


def test_atomic_publish_does_not_overwrite_late_file(tmp_path):
    dest = tmp_path / "new.zip"
    planned = w.output_path(dest)
    dest.write_bytes(b"another writer")
    with pytest.raises(FileExistsError):
        w.write_new(planned, b"our data")
    assert dest.read_bytes() == b"another writer"
    assert list(tmp_path.iterdir()) == [dest]


def test_package_preflight_and_verified_zip(tmp_path):
    src = tmp_path / "custom.dat"
    src.write_bytes(b"stage fixture")
    dest = tmp_path / "stage.zip"
    with pytest.raises(ValueError, match="missing"):
        w.package({"files": {"GrNBa.dat": str(src), "GrPs.dat": str(tmp_path / "missing")}, "out": str(dest)})
    assert not dest.exists()
    result = w.package({"files": {"GrNBa.dat": str(src)}, "out": str(dest)})
    with zipfile.ZipFile(dest) as z:
        assert z.read("GrNBa.dat") == src.read_bytes()
    assert result["sha256"] == w.sha256(dest)
    assert result["installed"] is False
    assert result["gameplay_tested"] is False


@pytest.mark.parametrize("name", ["../a.dat", "a/b.dat", "C:a.dat", "a.dat ", ".."])
def test_package_rejects_unsafe_names(tmp_path, name):
    src = tmp_path / "data"
    src.write_bytes(b"test")
    with pytest.raises(ValueError, match="plain archive filename"):
        w.package({"files": {name: str(src)}, "out": str(tmp_path / "out.zip")})


def test_missing_custom_stage_reference_refuses_package(tmp_path):
    dat = tmp_path / "stage.dat"
    dat.write_bytes(b"stage")
    meta = tmp_path / "stage.json"
    meta.write_text(json.dumps({"fileName": "absent.dat"}))
    with pytest.raises(ValueError, match="missing from ZIP"):
        w.package({"files": {"stage.json": str(meta), "stage.dat": str(dat)}, "out": str(tmp_path / "out.zip")})
    assert not (tmp_path / "out.zip").exists()


def test_camera_presets_and_custom_views(tmp_path):
    bf = w.cameras({"stage": "battlefield"})
    ys = w.cameras({"stage": "yoshisstory", "out": str(tmp_path / "sweep.json")})
    assert len(bf["views"]) == len(ys["views"]) == 10
    assert {v["fov"] for v in bf["views"]} == {30}
    assert {v["fov"] for v in ys["views"]} == {20}
    assert json.loads((tmp_path / "sweep.json").read_text()) == ys["views"]
    cam = json.loads((w.HERE / "camera_presets.json").read_text())["battlefield"]
    custom = w.cameras({"stage": "battlefield", "camera": dict(cam, fov=25),
                        "views": [{"name": "my spot", "box": [-40, -10, 70, 45]}]})
    assert custom["views"][0]["fov"] == 25
    assert custom["views"][0]["name"] == "my spot"
    assert len(custom["views"]) == 1


def test_budget_is_advisory_not_pass_fail():
    result = w.budget_report(3_000_000, "pokemonstadium")
    assert result["over_reference"]
    assert "ok" not in result
    assert "Advisory" in result["scope"]
