"""The one portrait renderer resolves its inputs correctly.

Most of these are the defects the 2026-08-22 consolidation fixed — each had
shipped because a call site re-implemented pose resolution and got it wrong.
They assert at the resolution layer (no HSDRawViewer), so they run in the
normal suite.
"""
import builtins
import symtable
from pathlib import Path

from shared.rendering import portrait


def test_module_imports_everything_it_uses():
    """A moved helper that lost an import only fails at RENDER time — which no
    unit test reached, so the scene-pose path shipped broken once already
    (PROCESSOR_DIR). symtable gives the exact set of names read from module
    scope, so lowercase misses (re, shutil, tempfile) are caught too.
    """
    src = Path(portrait.__file__).read_text(encoding="utf-8")
    table = symtable.symtable(src, portrait.__file__, "exec")

    def global_reads(t):
        for sym in t.get_symbols():
            if sym.is_global() and sym.is_referenced() and not sym.is_assigned():
                yield sym.get_name()
        for child in t.get_children():
            yield from global_reads(child)

    known = set(vars(portrait)) | set(dir(builtins))
    missing = sorted(n for n in set(global_reads(table)) if n not in known)
    assert not missing, f"read from module scope but never imported/defined: {missing}"


def test_scene_pose_detection_picks_the_scene_branch(tmp_path, monkeypatch):
    """`useSceneAnimation: true` must route through the merged scene file — and
    that file's NAME is what puts the viewer in scene mode, so assert it."""
    seen = {}

    def fake_internal(dat, character, anim_file, camera_file, scale, no_shadow=False, **kw):
        seen["anim"] = anim_file
        seen["camera"] = camera_file
        return "rendered.png"

    monkeypatch.setattr(portrait, "generate_single_csp_internal", fake_internal)
    # shaped like a real csp_data/<char>/scene.yml: top-level keys, a camera
    # block, and the baked animation the pose has to inherit
    baked = tmp_path / "baked_scene.yml"
    baked.write_text(
        "frame: 0\ncSPMode: true\n"
        "camera:\n  x: 4.36\n  y: 14.17\n  z: -63.39\n  scale: 1\n"
        "animation:\n  baked: true\n", encoding="utf-8")
    monkeypatch.setattr(portrait, "character_scene_file", lambda c: baked)

    scene_pose = tmp_path / "fist.yml"
    scene_pose.write_text("useSceneAnimation: true\ncamera:\n  x: 5\n", encoding="utf-8")
    portrait.render_pose_csp("dk.dat", "DK", scene_pose, None, 4)
    assert Path(seen["anim"]).name == "scene.yml", \
        "scene mode is triggered by the merged file being named scene.yml"
    assert seen["camera"] is None

    # a symbol pose goes straight through, with the AJ archive as the camera arg
    seen.clear()
    aj = tmp_path / "PlDkAJ.dat"
    aj.write_bytes(b"aj")
    symbol_pose = tmp_path / "wave.yml"
    symbol_pose.write_text("animSymbol: PlyDonkey5K_Share_ACTION_Wait1\n", encoding="utf-8")
    portrait.render_pose_csp("dk.dat", "DK", symbol_pose, aj, 4)
    assert Path(seen["anim"]).name == "wave.yml"
    assert seen["camera"] == str(aj)


def test_failed_pose_render_is_reported_not_disguised(monkeypatch, tmp_path):
    """The default portrait must never be handed back as though it were the
    pose — callers store the result under the pose's name."""
    pose_dir = tmp_path / "DK"
    pose_dir.mkdir()
    (pose_dir / "fist.yml").write_text("frame: 0\n", encoding="utf-8")
    monkeypatch.setattr(portrait, "poses_dir", lambda c: pose_dir)
    monkeypatch.setattr(portrait, "character_aj_file", lambda c: None)
    monkeypatch.setattr(portrait, "render_pose_csp", lambda *a, **kw: None)
    monkeypatch.setattr(portrait, "generate_csp", lambda dat, **kw: "default.png")

    result = portrait.render_portrait("dk.dat", "DK", pose_name="fist", scale=4)
    assert result.path == "default.png"
    assert result.pose_applied is False


def test_custom_character_poses_live_under_their_slug(monkeypatch):
    """The copy in storage_costumes hardcoded custom_poses/<character>, which
    never exists for a custom character, so their poses silently vanished."""
    monkeypatch.setattr(portrait, "custom_character_slug",
                        lambda c: "deoxys" if "deoxys" in c else None)
    assert portrait.pose_character_key("custom_characters/deoxys/skins") == "custom_characters/deoxys"
    assert portrait.poses_dir("custom_characters/deoxys/costumes").name == "deoxys"
    assert portrait.poses_dir("custom_characters/deoxys/costumes").parent.name == "custom_characters"
    # a canonical character is unaffected
    assert portrait.poses_dir("DK").name == "DK"


def test_scene_pose_merge_keeps_the_baked_animation(tmp_path):
    """A scene pose carries no animSymbol: the character's baked scene.yml
    supplies the animation, the pose supplies the camera."""
    scene = tmp_path / "scene.yml"
    scene.write_text("frame: 0\ncamera:\n  x: 1\n  y: 2\n  z: -3\n  scale: 1\n"
                     "animation:\n  baked: true\n", encoding="utf-8")
    merged = portrait.build_scene_pose_yaml(
        scene, {"camera": {"x": 9, "y": 8, "z": -70, "scale": 2}, "frame": 3})
    assert "animation:" in merged, "the baked animation block must survive the merge"
    assert "baked: true" in merged
    assert "9" in merged, "the pose's camera must replace the scene's"


def test_render_portrait_keeps_the_pair_over_a_pose(monkeypatch, tmp_path):
    """Ice Climbers poses are an accepted scope cut; posing one climber would
    drop Nana from the composite, so the pair wins — and says so."""
    calls = {}
    monkeypatch.setattr(portrait, "generate_csp",
                        lambda dat, **kw: calls.setdefault("default", kw) or "out.png")
    monkeypatch.setattr(portrait, "render_pose_csp",
                        lambda *a, **kw: calls.setdefault("posed", True) or "posed.png")
    pose_dir = tmp_path / "Ice Climbers"
    pose_dir.mkdir()
    (pose_dir / "wave.yml").write_text("frame: 0\n", encoding="utf-8")
    monkeypatch.setattr(portrait, "poses_dir", lambda c: pose_dir)

    result = portrait.render_portrait("popo.dat", "Ice Climbers", pose_name="wave",
                                      paired_dat="nana.dat", scale=4)
    assert "posed" not in calls, "a posed IC render would have dropped Nana"
    assert calls["default"]["paired_dat_filepath"] == "nana.dat"
    assert result.pose_applied is False, "the caller must not label this with the pose"


def test_render_portrait_forwards_gw_colours(monkeypatch, tmp_path):
    """Without gw_colors a G&W colour mod falls back to vanilla slot 0 = black."""
    seen = {}
    monkeypatch.setattr(portrait, "generate_csp", lambda dat, **kw: seen.update(kw) or "out.png")
    monkeypatch.setattr(portrait, "poses_dir", lambda c: tmp_path / "none")
    colours = {"fill": (200, 30, 30), "outline": (0, 0, 0, 255)}
    portrait.render_portrait("gw.dat", "Mr. Game & Watch", gw_colors=colours, color_index=2)
    assert seen["gw_colors"] == colours
    assert seen["color_index"] == 2


def test_missing_pose_falls_back_to_the_default(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(portrait, "generate_csp", lambda dat, **kw: seen.update(kw) or "out.png")

    def must_not_pose(*a, **kw):
        raise AssertionError("a pose whose file is gone must not reach the renderer")

    monkeypatch.setattr(portrait, "render_pose_csp", must_not_pose)
    monkeypatch.setattr(portrait, "poses_dir", lambda c: tmp_path / "empty")
    result = portrait.render_portrait("x.dat", "DK", pose_name="gone", scale=1)
    assert result == ("out.png", False)


def test_hidden_nodes_past_the_body_are_dropped_for_scene_and_symbol_poses(tmp_path, monkeypatch):
    """The live viewer numbers a costume's accessory DObjs (Jigglypuff's hats) after the body's and saves the
    never-drawn ones as hidden; the CSP renderer unlinks those accessories first, so a saved 14..23 hid blue
    Jigglypuff's visible bow (2026-11-19). Entries at or past the body's DObj count are dropped; body ones stay."""
    seen = []

    def fake_internal(dat, character, anim_file, camera_file, scale, no_shadow=False, **kw):
        seen.append((Path(anim_file).name, Path(anim_file).read_text(encoding="utf-8")))
        return "rendered.png"

    monkeypatch.setattr(portrait, "generate_single_csp_internal", fake_internal)
    monkeypatch.setattr(portrait, "_model_dobj_count", lambda dat: 14)
    baked = tmp_path / "baked_scene.yml"
    baked.write_text("frame: 0\ncSPMode: true\ncamera:\n  x: 1\n  y: 2\nanimation:\n  baked: true\n",
                     encoding="utf-8")
    monkeypatch.setattr(portrait, "character_scene_file", lambda c: baked)
    hidden = "hiddenNodes:\n- 7\n- 8\n- 9\n- 10\n- 14\n- 15\n- 20\n"

    def hidden_in(text):
        return [int(line[2:]) for line in text.split("hiddenNodes:")[1].splitlines() if line.startswith("- ")]

    scene_pose = tmp_path / "scene_pose.yml"
    scene_pose.write_text("useSceneAnimation: true\ncamera:\n  x: 5\n" + hidden, encoding="utf-8")
    portrait.render_pose_csp("PlPrBu.dat", "Jigglypuff", scene_pose, None, 4)
    symbol_pose = tmp_path / "symbol_pose.yml"
    symbol_pose.write_text("animSymbol: PlyPurin5K_Share_ACTION_Wait1\n" + hidden + "frame: 3\n", encoding="utf-8")
    aj = tmp_path / "PlPrAJ.dat"
    aj.write_bytes(b"aj")
    portrait.render_pose_csp("PlPrBu.dat", "Jigglypuff", symbol_pose, aj, 4)

    (scene_name, scene_text), (symbol_name, symbol_text) = seen
    assert scene_name == "scene.yml" and hidden_in(scene_text) == [7, 8, 9, 10]
    assert symbol_name == "pose.yml", "a symbol pose must not be named scene.yml (that is scene mode)"
    assert hidden_in(symbol_text) == [7, 8, 9, 10]
    assert "animSymbol: PlyPurin5K_Share_ACTION_Wait1" in symbol_text and "frame: 3" in symbol_text
    assert symbol_pose.read_text(encoding="utf-8").count("- ") == 7      # the saved pose itself is unchanged

    # nothing past the body (or an unreadable model): the saved file goes through as it is
    seen.clear()
    inside = tmp_path / "inside.yml"
    inside.write_text("animSymbol: PlyPurin5K_Share_ACTION_Wait1\nhiddenNodes:\n- 3\n", encoding="utf-8")
    portrait.render_pose_csp("PlPrBu.dat", "Jigglypuff", inside, aj, 4)
    monkeypatch.setattr(portrait, "_model_dobj_count", lambda dat: None)
    portrait.render_pose_csp("PlPrBu.dat", "Jigglypuff", symbol_pose, aj, 4)
    assert [name for name, _ in seen] == ["inside.yml", "symbol_pose.yml"]
