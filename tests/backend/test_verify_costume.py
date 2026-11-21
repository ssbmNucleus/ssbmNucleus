"""The metered in-game verification gate, without an emulator.

Nothing here boots Dolphin. What is tested is everything that decides whether a
run MEANS anything: profile resolution and its incompleteness, the costume slot
travelling from the build to the capture and back out of RAM, the actor
measurement derived from real paired images, the manifest the release gate
consumes, cache poisoning, leaving a busy Dolphin alone, the watchdog, and
cancelling only the instance this run owns.
"""
import json
import threading
from pathlib import Path
import time
import types

import pytest

from shared.ingame import verify_costume as vc
import shared.ingame.verify_cache as vc_cache
import shared.ingame.verify_outcome as vc_outcome
import shared.ingame.verify_evidence as vc_evidence
import shared.ingame.verify_appearance as vc_appearance
import shared.ingame.verify_profile as vc_profile

BACKGROUND = "404040"
APPEARANCE = vc_profile._PROFILES[vc.PROFILE_VERSION]["appearance"]


# --- profile resolution -------------------------------------------------------- #

def test_profile_resolves_every_entry_against_the_engines_own_catalog():
    resolved = vc.resolve_profile()
    assert resolved["profile_version"] == "costume_verification_v1"
    assert resolved["complete"] is True
    assert resolved["unsupported"] == []
    by_id = {e["id"]: e for e in resolved["entries"]}
    assert by_id["run"]["frames"] == [5, 15]
    assert by_id["jab"]["frames"] == [1, 2, 3]
    assert by_id["fsmash"]["frames"] == [10]
    assert by_id["upb"]["frames"] == [5]
    assert by_id["dashattack"]["frames"] == [6]
    assert by_id["grab"]["frames"] == [3]
    assert by_id["idle"]["frames"] == [1]
    assert all(e["status"] == "supported" for e in resolved["entries"])
    assert len(resolved["expected_captures"]) == 10


def test_every_profile_move_is_a_name_the_engine_actually_accepts():
    catalog = set(vc_profile.engine_catalog())
    for entry in vc_profile._PROFILES[vc.PROFILE_VERSION]["entries"]:
        assert entry["move"] in catalog, entry


def test_an_unsupported_entry_is_recorded_and_makes_the_profile_incomplete():
    catalog = [m for m in vc_profile.engine_catalog() if m != "grab"]
    resolved = vc.resolve_profile(catalog=catalog)
    assert resolved["complete"] is False
    assert resolved["unsupported"] == ["grab"]
    grab = next(e for e in resolved["entries"] if e["id"] == "grab")
    assert grab["status"] == "unsupported" and "grab" in grab["reason"]
    assert len(resolved["entries"]) == 7          # recorded, not dropped
    assert not [c for c in resolved["expected_captures"] if c["move"] == "grab"]
    assert "grab:3" not in vc.shot_specs(resolved)


def test_shot_specs_are_what_the_capture_engine_is_asked_for():
    assert vc.shot_specs(vc.resolve_profile()) == [
        "idle:1", "run:5,15", "jab:1,2,3", "fsmash:10", "upb:5",
        "dashattack:6", "grab:3"]


def test_unknown_profile_version_is_refused():
    with pytest.raises(ValueError):
        vc.resolve_profile("costume_verification_v99")


# --- execution evidence ---------------------------------------------------------- #

def _resolved():
    return vc.resolve_profile()


FRAMES = (("idle", 1), ("run", 5), ("run", 15), ("jab", 1), ("jab", 2),
          ("jab", 3), ("fsmash", 10), ("upb", 5), ("dashattack", 6), ("grab", 3))
STATES = {"idle": 14, "run": 21, "jab": 44, "fsmash": 58, "upb": 353,
          "dashattack": 50, "grab": 212}


def _sidecars(frames=FRAMES, state=None, port=0, game_frame=True):
    by_move, counter = {}, 1000
    for move, frame in frames:
        counter += 7
        row = by_move.setdefault(move, {"move": move, "captures": []})
        row["captures"].append({
            "move_frame": frame, "file": f"mewtwo-{move}-f{frame:02d}.png",
            "state": STATES[move] if state is None else state,
            "state_name": move, "anim_frame": float(frame), "x": 0.0, "y": 0.0,
            "facing": 1.0, "airborne": False, "port": port,
            "game_frame": counter if game_frame else None})
    return list(by_move.values())


def _row(costume_id=4, kind=0x10, ground=0x25, status="ok"):
    return {"id": "mewtwo-slot4", "status": status, "reason": "",
            "ckind": 0x0A, "color": 4, "dir": "/captures",
            "live_identity": {"kind": kind, "costume_id": costume_id,
                              "port": 0, "schema": "gale01-fighter-identity-v1"},
            "live_stage_state": {"ground_kind": ground,
                                 "schema": "gale01-stage-ground-kind-v1"}}


GOOD_ISO = {"insertion_verified": True, "inserted_file": "PlMtNr_001.dat",
            "inserted_member": "PlMtNr.dat", "added_costumes": ["PlMtNr_001.dat"],
            "sha256": "aa" * 32, "sha256_after_capture": "aa" * 32,
            "unchanged_during_capture": True}


def _evidence(**kw):
    requested = kw.pop("requested", None) or {"character": "Mewtwo",
                                              "ckind": 0x0A, "costume_slot": 4}
    requested.setdefault("iso_identity", kw.pop("iso_identity", None) or GOOD_ISO)
    return vc.execution_evidence(
        resolved=kw.pop("resolved", _resolved()),
        requested=requested,
        batch_row=kw.pop("batch_row", _row()),
        sidecars=kw.pop("sidecars", _sidecars()))


def _named(evidence, check_id):
    return next(c for c in evidence["checks"] if c["check_id"] == check_id)


def _codes(reasons):
    return [r["code"] for r in reasons]


def _details(reasons):
    return " | ".join(r["detail"] for r in reasons)


def test_the_slot_the_build_produced_is_the_slot_the_engine_reports():
    evidence = _evidence()
    assert _named(evidence, "costume_slot_loaded")["status"] == "pass"
    # `upb` is a special: this build has no portable expectation for its state,
    # so the action-state check is unknown and the evidence is not complete.
    assert _named(evidence, "action_states")["status"] == "unknown"
    assert evidence["status"] == "incomplete"


def test_built_slot_four_captured_slot_zero_is_a_critical_failure():
    """The exact defect this gate exists to make impossible."""
    evidence = _evidence(batch_row=_row(costume_id=0))
    slot = _named(evidence, "costume_slot_loaded")
    assert slot["status"] == "fail" and slot["critical"] is True
    assert slot["expected"] == 4 and slot["observed"] == 0
    outcome, reasons = vc.decide_outcome(evidence, [])
    assert outcome == "failed"
    assert "costume_slot_loaded" in _codes(reasons)


def test_an_unreadable_costume_slot_is_unknown_never_a_pass():
    row = _row()
    row["live_identity"] = {"kind": 0x10}
    evidence = _evidence(batch_row=row)
    assert _named(evidence, "costume_slot_loaded")["status"] == "unknown"
    # `slot_unreadable` is not an allow-listed observability limitation: the
    # run did not establish what it was for, so it is unfinished work.
    assert vc.decide_outcome(evidence, [])[0] == "incomplete"


def test_the_wrong_fighter_and_the_wrong_stage_are_caught_from_ram():
    assert _named(_evidence(batch_row=_row(kind=0x0C)),
                  "character_loaded")["status"] == "fail"
    assert _named(_evidence(batch_row=_row(ground=0x24)),
                  "stage_loaded")["status"] == "fail"


def test_an_mex_added_fighter_has_no_verified_kind_mapping_so_it_is_unknown():
    evidence = _evidence(
        requested={"character": "0x1A", "ckind": 0x1A, "costume_slot": 1},
        batch_row=_row(costume_id=1, kind=0x21))
    assert _named(evidence, "character_loaded")["status"] == "unknown"


def test_a_frame_the_stepper_never_landed_on_is_missing_not_captured():
    partial = _sidecars([f for f in FRAMES if f != ("run", 15)])
    evidence = _evidence(sidecars=partial)
    assert evidence["missing_captures"] == ["run:15"]
    present = _named(evidence, "captures_present")
    assert present["status"] == "fail" and present["critical"] is False


def test_a_frame_captured_outside_its_action_state_is_a_critical_failure():
    evidence = _evidence(sidecars=_sidecars(state=14))
    check = _named(evidence, "action_states")
    assert check["status"] == "fail" and check["critical"] is True
    assert vc.decide_outcome(evidence, [])[0] == "failed"


def test_a_special_with_no_portable_expectation_is_unknown_not_silently_passed():
    """It used to skip validation and leave the aggregate check passing, so a
    special reporting `Wait` came back as execution-complete."""
    only_upb = vc.resolve_profile()
    only_upb["expected_captures"] = [c for c in only_upb["expected_captures"]
                                     if c["move"] == "upb"]
    evidence = _evidence(resolved=only_upb,
                         sidecars=_sidecars([("upb", 5)], state=14))
    check = _named(evidence, "action_states")
    assert check["status"] == "unknown"
    assert "upb:5" in check["reason"]
    assert evidence["status"] == "incomplete"
    outcome, reasons = vc.decide_outcome(evidence, [_app("pass", "upb", 5)])
    assert outcome == "unknown"
    assert _codes(reasons) == ["unsupported_special"]


def test_a_reading_from_another_port_fails():
    evidence = _evidence(sidecars=_sidecars(port=3))
    check = _named(evidence, "capture_port")
    assert check["status"] == "fail" and check["critical"] is True


def test_a_missing_simulation_frame_counter_is_unknown():
    evidence = _evidence(sidecars=_sidecars(game_frame=False))
    assert _named(evidence, "frame_counters")["status"] == "unknown"


def test_an_absent_port_is_not_port_zero():
    """A reading with no port recorded is not a reading from port 0."""
    sidecars = _sidecars()
    for row in sidecars:
        for cap in row["captures"]:
            cap["port"] = None
    assert _named(_evidence(sidecars=sidecars), "capture_port")["status"] == "fail"


def test_an_impossible_animation_frame_is_not_a_reading():
    sidecars = _sidecars()
    for row in sidecars:
        for cap in row["captures"]:
            cap["anim_frame"] = 99999
    check = _named(_evidence(sidecars=sidecars), "frame_counters")
    assert check["status"] == "unknown"
    assert "99999" in check["reason"]


def test_the_frame_counter_check_says_what_it_does_not_establish():
    check = _named(_evidence(), "frame_counters")
    assert "NOT established" in check["expected"]


def test_two_move_frames_sharing_one_simulation_frame_is_unknown():
    sidecars = _sidecars()
    for row in sidecars:
        for cap in row["captures"]:
            cap["game_frame"] = 4242
    evidence = _evidence(sidecars=sidecars)
    check = _named(evidence, "frame_counters")
    assert check["status"] == "unknown"
    assert "shares frame 4242" in check["reason"]


# --- outcome: completion is never a pass ---------------------------------------- #

def _complete_evidence():
    """An evidence set where every check passes (no specials in the profile)."""
    resolved = vc.resolve_profile()
    resolved["expected_captures"] = [c for c in resolved["expected_captures"]
                                     if c["move"] != "upb"]
    return _evidence(resolved=resolved,
                     sidecars=_sidecars([f for f in FRAMES if f[0] != "upb"]))


def _app(status, move="jab", frame=1, code=None):
    return {"move": move, "frame": frame, "path": f"{move}-f{frame:02d}.png",
            "status": status, "reason": "because", "measurement": {},
            "source": "test",
            "code": code or ("in_frame" if status == "pass" else
                             "insufficient_framing" if status == "unknown" else
                             "actor_not_drawn")}


def test_an_unconfirmed_insertion_blocks_the_run():
    """Changing it used to affect nothing at all."""
    iso = dict(GOOD_ISO, insertion_verified=False,
               insertion_note="the builder transformed the bytes")
    evidence = _evidence(iso_identity=iso)
    check = _named(evidence, "candidate_inserted")
    assert check["status"] == "unknown" and check["critical"] is True
    assert vc.decide_outcome(evidence, [])[0] == "incomplete"


def test_a_disc_replaced_during_the_captures_fails():
    iso = dict(GOOD_ISO, sha256_after_capture="bb" * 32,
               unchanged_during_capture=False)
    evidence = _evidence(iso_identity=iso)
    check = _named(evidence, "iso_unchanged_during_capture")
    assert check["status"] == "fail" and check["critical"] is True
    assert vc.decide_outcome(evidence, [])[0] == "failed"


def test_a_complete_capture_run_with_a_passing_sheet_is_verified():
    evidence = _complete_evidence()
    assert evidence["status"] == "complete"
    outcome, reasons = vc.decide_outcome(evidence, [_app("pass"),
                                                    _app("pass", "run", 5)])
    assert outcome == "verified" and reasons == []


def test_a_complete_capture_run_with_no_measurement_is_never_verified():
    assert vc.decide_outcome(_complete_evidence(), [])[0] == "incomplete"


def test_one_allow_listed_unmeasurable_frame_makes_the_run_unknown():
    outcome, reasons = vc.decide_outcome(
        _complete_evidence(),
        [_app("pass"), _app("unknown", "run", 5, code="unresolved_isolation")])
    assert outcome == "unknown"
    assert _codes(reasons) == ["unresolved_isolation"]


def test_an_inconclusive_reason_outside_the_allowlist_is_unfinished_work():
    """`unknown` is for bounded, deterministic limitations a policy may decide
    to live with. Anything else is work that did not finish."""
    outcome, reasons = vc.decide_outcome(
        _complete_evidence(),
        [_app("pass"), _app("unknown", "run", 5, code="capture_unreadable")])
    assert outcome == "incomplete"
    assert "capture_unreadable" in _codes(reasons)


def test_an_appearance_failure_beats_everything_else():
    assert vc.decide_outcome(_complete_evidence(),
                             [_app("unknown"), _app("fail", "run", 5)])[0] == "failed"


def test_a_harness_exception_is_not_evidence_against_the_costume():
    """It used to become `failed`, which puts that word beside a candidate
    because the emulator fell over."""
    outcome, reasons = vc.decide_outcome(_complete_evidence(), [_app("pass")],
                                         run_error="Dolphin died during boot")
    assert outcome == "incomplete"
    assert _codes(reasons) == ["harness_error"]
    assert "Dolphin died during boot" in _details(reasons)


def test_a_cancelled_run_is_incomplete_not_a_verdict_on_the_costume():
    outcome, reasons = vc.decide_outcome(
        _complete_evidence(), [_app("pass")], cancelled=True,
        run_error="cancelled: only the emulator instance this run owned was stopped")
    assert outcome == "incomplete"
    assert _codes(reasons) == ["cancelled"]


def test_a_watchdog_timeout_is_an_execution_failure_not_a_costume_verdict():
    outcome, reasons = vc.decide_outcome(
        _complete_evidence(), [_app("pass")], execution_failure="timeout",
        run_error="timeout: boot/capture exceeded the 90s boot deadline")
    assert outcome == "incomplete"
    assert _codes(reasons) == ["timeout"]
    assert "execution failure of the harness" in _details(reasons)


# --- the actor measurement, from real paired images ------------------------------ #

def _frame(tmp_path, name, *, actor=None, effects=None, bars=56,
           width=1280, height=960, hide_actor=False):
    """A capture like PrintWindow produces: black pillarbox bars, flat
    background between them, an actor rectangle and an effects rectangle."""
    np = pytest.importorskip("numpy")
    from PIL import Image
    pixels = np.zeros((height, width, 3), dtype=np.uint8)
    pixels[:, bars:width - bars] = (0x40, 0x40, 0x40)
    if actor and not hide_actor:
        x0, x1, y0, y1 = actor
        pixels[y0:y1 + 1, x0:x1 + 1] = (200, 30, 30)
    if effects:
        x0, x1, y0, y1 = effects
        pixels[y0:y1 + 1, x0:x1 + 1] = (240, 240, 240)
    path = tmp_path / name
    Image.fromarray(pixels).save(path)
    return path


def _group(tmp_path, stem, *, actor, effects=None, delivered_actor=None,
           consistent=True):
    """Write a whole measurement group and return (delivered, recorded)."""
    delivered = _frame(tmp_path, f"{stem}.png",
                       actor=delivered_actor if delivered_actor is not None else actor,
                       effects=effects)
    # The particle-hidden pass still shows non-particle effects; only the
    # fighter-hidden pass drops the actor.
    _frame(tmp_path, f"{stem}-actor.png", actor=actor, effects=effects)
    _frame(tmp_path, f"{stem}-background.png", actor=actor, effects=effects,
           hide_actor=True)
    recorded = {"group_consistent": consistent, "settled": True,
                "model_measured": consistent, "reframed": False,
                "actor_file": f"{stem}-actor.png",
                "background_file": f"{stem}-background.png",
                "game_before": 100, "game_after": 100,
                "camera_before": [8, 1, 2, 3], "camera_after": [8, 1, 2, 3]}
    return delivered, recorded


def test_an_actor_well_inside_the_playfield_passes(tmp_path):
    delivered, recorded = _group(tmp_path, "ok", actor=(400, 900, 200, 800))
    row = vc.measure_capture(delivered, APPEARANCE, recorded, folder=tmp_path)
    assert row["status"] == "pass", row["reason"]
    assert row["measurement"]["render_rect"] == (56, 1223, 0, 959)
    assert row["measurement"]["bbox"] == (400, 900, 200, 800)
    assert row["measurement"]["actor_sha256"]
    assert row["measurement"]["background_sha256"]


def test_an_actor_running_through_the_render_boundary_is_seen_at_all(tmp_path):
    """The defect the old check could not see: `model_extent` dilated the
    bar/effects mask by 2 px and subtracted it, deleting exactly the actor
    pixels at the boundary, and the margin then asked for 1 px of slack.

    The verdict is `unknown`, not `fail`: the frame does not show the actor's
    full extent, and at this camera that cannot be attributed to the costume.
    """
    delivered, recorded = _group(tmp_path, "wide", actor=(400, 1223, 200, 800))
    row = vc.measure_capture(delivered, APPEARANCE, recorded, folder=tmp_path)
    assert row["status"] == "unknown"
    assert "reaches the rendered boundary" in row["reason"]
    assert "cannot be attributed to the costume" in row["reason"]
    assert row["measurement"]["clipped"] is True


def test_the_dilation_was_the_bug_not_the_margin(tmp_path):
    """The dragon's idle frame was RECORDED as 58..1221 inside a 56..1223
    playfield, which reads as two pixels of slack. It was not: the old effects
    mask covered the black bars and was dilated by two pixels before being
    subtracted, so the two columns against the boundary were deleted from the
    actor before anything measured it. An actor that genuinely stops two pixels
    short is in frame; one that reaches the boundary is not, and the same
    geometry now measures as reaching it."""
    clear, recorded = _group(tmp_path, "clear", actor=(58, 1221, 400, 450))
    assert vc.measure_capture(clear, APPEARANCE, recorded,
                              folder=tmp_path)["status"] == "pass"
    touching, recorded = _group(tmp_path, "touch", actor=(56, 1223, 400, 450))
    row = vc.measure_capture(touching, APPEARANCE, recorded, folder=tmp_path)
    assert row["status"] == "unknown" and row["measurement"]["clipped"] is True


def test_clipping_blocks_a_run_without_condemning_the_costume():
    """An accepted Pikachu fit clips on jab 2-3 at this camera. Blocking is
    right; calling it a failed costume is not."""
    outcome, reasons = vc.decide_outcome(
        _complete_evidence(),
        [_app("pass"), {"move": "jab", "frame": 2, "path": "jab-f02.png",
                        "status": "unknown", "code": "insufficient_framing",
                        "reason": "reaches the rendered boundary ... cannot be "
                                  "attributed to the costume",
                        "measurement": {"clipped": True}, "source": "test"}])
    assert outcome == "unknown"
    assert _codes(reasons) == ["insufficient_framing"]
    assert "cannot be attributed to the costume" in _details(reasons)


def test_an_actor_that_is_not_drawn_fails(tmp_path):
    delivered, recorded = _group(tmp_path, "gone", actor=(400, 402, 400, 402))
    row = vc.measure_capture(delivered, APPEARANCE, recorded, folder=tmp_path)
    assert row["status"] == "fail" and "not drawn" in row["reason"]


def test_an_isolated_actor_covering_most_of_the_playfield_is_gross_overflow(tmp_path):
    """The isolated branch used to skip `max_actor_frac` entirely."""
    delivered, recorded = _group(tmp_path, "huge", actor=(100, 1180, 10, 950))
    row = vc.measure_capture(delivered, APPEARANCE, recorded, folder=tmp_path)
    assert row["status"] == "fail"
    assert "gross overflow" in row["reason"] or "reaches the rendered" in row["reason"]


def test_the_measurement_must_describe_the_delivered_image(tmp_path):
    """The 2026-09-22 known-good grab: bounds recorded from one capture, a
    different capture saved. The delivered frame is checked against the mask."""
    delivered, recorded = _group(tmp_path, "drift", actor=(400, 900, 200, 800),
                                 delivered_actor=(20, 40, 20, 40))
    row = vc.measure_capture(delivered, APPEARANCE, recorded, folder=tmp_path)
    assert row["status"] == "unknown"
    assert "different captures" in row["reason"]
    assert row["measurement"]["absent_from_delivered_share"] > 0.9


def test_effects_that_swallow_the_playfield_make_the_actor_unmeasurable(tmp_path):
    delivered, recorded = _group(tmp_path, "flash", actor=(400, 900, 200, 800),
                                 effects=(60, 1220, 10, 700))
    row = vc.measure_capture(delivered, APPEARANCE, recorded, folder=tmp_path)
    assert row["status"] == "unknown"
    assert "cannot be separated" in row["reason"]


def test_a_visibility_write_that_did_nothing_is_unmeasurable(tmp_path):
    delivered = _frame(tmp_path, "same.png", actor=(400, 900, 200, 800))
    _frame(tmp_path, "same-actor.png", actor=(400, 900, 200, 800))
    _frame(tmp_path, "same-background.png", actor=(400, 900, 200, 800))
    recorded = {"group_consistent": True, "model_measured": True,
                "reframed": False, "actor_file": "same-actor.png",
                "background_file": "same-background.png"}
    row = vc.measure_capture(delivered, APPEARANCE, recorded, folder=tmp_path)
    assert row["status"] == "unknown"
    assert "removed nothing" in row["reason"]


def test_a_group_that_did_not_hold_together_is_unknown(tmp_path):
    delivered, recorded = _group(tmp_path, "moved", actor=(400, 900, 200, 800),
                                 consistent=False)
    row = vc.measure_capture(delivered, APPEARANCE, recorded, folder=tmp_path)
    assert row["status"] == "unknown"
    assert "not attributable to the declared camera" in row["reason"]


def test_a_retained_pair_that_is_missing_is_unknown(tmp_path):
    delivered, recorded = _group(tmp_path, "lost", actor=(400, 900, 200, 800))
    (tmp_path / "lost-background.png").unlink()
    row = vc.measure_capture(delivered, APPEARANCE, recorded, folder=tmp_path)
    assert row["status"] == "unknown"
    assert "was not retained" in row["reason"]


def test_a_missing_file_is_unknown_not_a_pass(tmp_path):
    row = vc.measure_capture(tmp_path / "nope.png", APPEARANCE)
    assert row["status"] == "unknown" and "does not exist" in row["reason"]


def test_a_frame_whose_camera_moved_cannot_be_graded(tmp_path):
    png = _frame(tmp_path, "a.png", actor=(400, 900, 200, 800))
    row = vc.measure_capture(png, APPEARANCE, {"reframed": True})
    assert row["status"] == "unknown" and "camera moved" in row["reason"]


def test_the_render_rect_is_the_playfield_not_the_captured_window(tmp_path):
    png = _frame(tmp_path, "bars.png")
    assert vc_appearance.render_rect(png.read_bytes(), BACKGROUND) == (56, 1223, 0, 959)


def test_a_background_pass_with_almost_no_background_has_no_render_rect(tmp_path):
    png = _frame(tmp_path, "full.png", effects=(56, 1100, 0, 959))
    assert vc_appearance.render_rect(png.read_bytes(), BACKGROUND) is None


def test_clip_state_treats_contact_with_the_boundary_as_clipping():
    rect = (56, 1223, 0, 959)
    assert vc_appearance.clip_state((400, 900, 100, 800), rect, 2) is False
    assert vc_appearance.clip_state((56, 1100, 100, 800), rect, 2) is True
    assert vc_appearance.clip_state((100, 1223, 100, 800), rect, 2) is True
    assert vc_appearance.clip_state((100, 900, 0, 800), rect, 2) is True
    assert vc_appearance.clip_state((100, 900, 100, 959), rect, 2) is True
    assert vc_appearance.clip_state(None, rect, 2) is None
    assert vc_appearance.clip_state((1, 2, 3, 4), None, 2) is None


# --- identity, cache spec and poisoning ------------------------------------------ #

def test_the_engine_version_covers_the_sources_that_decide_the_pictures():
    version = vc.engine_version()
    assert version["id"] and len(version["id"]) == 16
    assert set(version["sources"]) >= {"frameshot.py", "moves.py",
                                       "gamestate.py", "verify_costume.py"}


def test_an_engine_whose_sources_cannot_be_hashed_has_no_identity(monkeypatch,
                                                                  tmp_path):
    """A frozen build has no source tree. Collapsing that to one constant id
    would make every packaged install share a cache namespace."""
    monkeypatch.setattr(vc, "_engine_digest_file", lambda: None)
    monkeypatch.setattr(vc, "engine_source_paths",
                        lambda: (tmp_path / "gone.py",))
    version = vc.engine_version()
    assert version["id"] is None
    assert version["unavailable"] == ["gone.py"]


def test_a_build_generated_engine_digest_is_used_when_present(monkeypatch,
                                                              tmp_path):
    digest = tmp_path / vc.ENGINE_DIGEST_NAME
    digest.write_text(json.dumps({"schema": "harness-engine-version-v1",
                                  "id": "abcdef0123456789",
                                  "sources": {"frameshot.py": "deadbeef"}}),
                      encoding="utf-8")
    monkeypatch.setattr(vc, "_engine_digest_file", lambda: digest)
    version = vc.engine_version()
    assert version["id"] == "abcdef0123456789"
    assert version["source"] == str(digest)


def _spec(**kw):
    base = dict(candidate_hash="aa" * 32, member_hashes={"PlMtNr.dat": "bb" * 32},
                profile_version=vc.PROFILE_VERSION, engine={"id": "eng1"},
                toolchain={"id": "tool1", "complete": True}, character="Mewtwo",
                stage="finaldestination")
    base.update(kw)
    return vc.cache_spec(**base)


def test_the_cache_key_covers_every_effective_input():
    base = vc.cache_key(_spec())
    assert base == vc.cache_key(_spec(character="mewtwo"))
    assert base != vc.cache_key(_spec(candidate_hash="cc" * 32))
    assert base != vc.cache_key(_spec(member_hashes={"PlMtNr.dat": "cc" * 32}))
    assert base != vc.cache_key(_spec(profile_version="costume_verification_v2"))
    assert base != vc.cache_key(_spec(engine={"id": "eng2"}))
    assert base != vc.cache_key(_spec(toolchain={"id": "tool2", "complete": True}))
    assert base != vc.cache_key(_spec(character="Pikachu"))
    assert base != vc.cache_key(_spec(stage="battlefield"))
    assert base != vc.cache_key(_spec(nana_hash="dd" * 32))


def test_the_toolchain_identity_is_content_not_metadata():
    """Path, size and mtime are not identity: a rebuilt MexCLI keeps all three
    and changes every capture. The linked HSDRaw DLL counts too."""
    toolchain = vc.toolchain_identity()
    assert set(toolchain) >= {"mexcli", "hsdraw", "dolphin", "vanilla_iso",
                              "mexcli_libraries", "complete", "id"}
    assert toolchain["complete"] is False       # no base ISO was supplied
    for name in ("mexcli", "hsdraw", "dolphin"):
        if toolchain[name]:
            assert len(toolchain[name]["sha256"]) == 64, name
    dll = vc._mexcli_libraries()[0]
    if not dll.is_file():
        pytest.skip(f"needs {dll.name} beside the fetched MexCLI ({dll.parent}), which a clone "
                    "gets from `python tools/build/fetch_native.py all`")
    assert "HSDRaw.dll" in (toolchain["mexcli_libraries"] or {})


def _stored(tmp_path, spec, key, *, candidate=None, outcome="verified",
            captures=None, checks=None, appearance=None, reasons=None,
            drop_pair=False):
    """A stored manifest carrying EVERY capture the profile requires."""
    rows = []
    for want in vc.resolve_profile(spec["profile_version"])["expected_captures"]:
        stem = f"{want['move']}-f{want['frame']:02d}"
        png = tmp_path / f"{stem}.png"
        png.write_bytes(f"pretend png {stem}".encode())
        actor = tmp_path / f"{stem}-actor.png"
        actor.write_bytes(f"actor {stem}".encode())
        background = tmp_path / f"{stem}-background.png"
        background.write_bytes(f"background {stem}".encode())
        row = {"move": want["move"], "frame": want["frame"], "path": str(png),
               "hash": f"sha256:{vc.sha256_file(png)}"}
        if not drop_pair:
            row["measurement_pair"] = {
                "actor": {"path": str(actor),
                          "hash": f"sha256:{vc.sha256_file(actor)}"},
                "background": {"path": str(background),
                               "hash": f"sha256:{vc.sha256_file(background)}"}}
        rows.append(row)
    if captures is not None:
        rows = captures
    return {"schema": vc.MANIFEST_SCHEMA,
            "engine_version": {"id": spec["engine_id"]},
            "cache": {"key": key, "spec": spec},
            "execution_evidence": {"checks": checks if checks is not None
                                   else [{"status": "pass"}]},
            "appearance_checks": appearance if appearance is not None
            else [{"status": "pass"}],
            "outcome_reasons": reasons or [],
            "game_verification": {
                "candidate_hash": f"sha256:{candidate or spec['candidate_sha256']}",
                "profile_version": spec["profile_version"],
                "outcome": outcome, "captures": rows}}


def test_a_valid_stored_record_is_reusable(tmp_path):
    spec = _spec()
    key = vc.cache_key(spec)
    assert vc.validate_cached(_stored(tmp_path, spec, key), spec, key) is None


def test_a_manifest_for_another_costume_is_refused(tmp_path):
    """Supplying the Pikachu manifest under the dragon's key returned
    `verified`, character Pikachu, with a candidate hash that was not the input."""
    spec = _spec()
    key = vc.cache_key(spec)
    stored = _stored(tmp_path, spec, key, candidate="ff" * 32)
    refusal = vc.validate_cached(stored, spec, key)
    assert refusal and "is about candidate" in refusal


def test_arbitrary_json_at_the_cache_filename_is_refused(tmp_path):
    spec = _spec()
    key = vc.cache_key(spec)
    for bad in ({"hello": "world"}, ["not", "a", "manifest"], "text", 3):
        assert vc.validate_cached(bad, spec, key)


def test_a_record_written_under_another_specification_is_refused(tmp_path):
    spec = _spec()
    key = vc.cache_key(spec)
    stored = _stored(tmp_path, spec, key)
    stored["cache"]["spec"] = _spec(engine={"id": "eng9"})
    assert "specification differs" in vc.validate_cached(stored, spec, key)


def test_a_record_whose_evidence_no_longer_hashes_is_refused(tmp_path):
    spec = _spec()
    key = vc.cache_key(spec)
    stored = _stored(tmp_path, spec, key)
    path = Path(stored["game_verification"]["captures"][0]["path"])
    path.write_bytes(b"something else entirely")
    assert "does not match its hash" in vc.validate_cached(stored, spec, key)
    path.unlink()
    assert "no longer exists" in vc.validate_cached(stored, spec, key)


def test_an_unfinished_outcome_is_never_reused(tmp_path):
    spec = _spec()
    key = vc.cache_key(spec)
    for outcome in ("incomplete", "passed", None):
        stored = _stored(tmp_path, spec, key, outcome=outcome)
        assert "not a measured verdict" in vc.validate_cached(stored, spec, key)


def test_a_deterministic_unknown_IS_reused_so_exports_do_not_reboot(tmp_path):
    """~70 s once per eligible new revision is fine; once per identical export
    for a verdict that cannot change is not."""
    spec = _spec()
    key = vc.cache_key(spec)
    stored = _stored(tmp_path, spec, key, outcome="unknown",
                     checks=[{"status": "unknown"}],
                     appearance=[{"status": "unknown"}],
                     reasons=[{"code": "insufficient_framing", "check": "jab:2",
                               "detail": "reaches the boundary"}])
    assert vc.validate_cached(stored, spec, key) is None


def test_an_unknown_for_a_transient_reason_is_not_reused(tmp_path):
    spec = _spec()
    key = vc.cache_key(spec)
    stored = _stored(tmp_path, spec, key, outcome="unknown",
                     checks=[{"status": "unknown"}],
                     appearance=[{"status": "unknown"}],
                     reasons=[{"code": "harness_error", "check": "run",
                               "detail": "Dolphin died"}])
    assert "not deterministic" in vc.validate_cached(stored, spec, key)


def test_a_record_missing_required_captures_is_refused(tmp_path):
    """It accepted one of ten."""
    spec = _spec()
    key = vc.cache_key(spec)
    full = _stored(tmp_path, spec, key)
    one = dict(full)
    one["game_verification"] = dict(full["game_verification"],
                                    captures=full["game_verification"]["captures"][:1])
    refusal = vc.validate_cached(one, spec, key)
    assert refusal and "missing required captures" in refusal


def test_a_record_whose_measurement_pair_is_gone_is_refused(tmp_path):
    spec = _spec()
    key = vc.cache_key(spec)
    stored = _stored(tmp_path, spec, key)
    pair = stored["game_verification"]["captures"][0]["measurement_pair"]
    Path(pair["actor"]["path"]).unlink()
    refusal = vc.validate_cached(stored, spec, key)
    assert refusal and "actor pass" in refusal


def test_a_record_whose_verdict_disagrees_with_its_checks_is_refused(tmp_path):
    spec = _spec()
    key = vc.cache_key(spec)
    stored = _stored(tmp_path, spec, key, outcome="verified",
                     checks=[{"status": "pass"}, {"status": "unknown"}])
    refusal = vc.validate_cached(stored, spec, key)
    assert refusal and "its own checks are" in refusal
    stored = _stored(tmp_path, spec, key, outcome="failed",
                     checks=[{"status": "pass"}], appearance=[{"status": "pass"}])
    assert "no check of its own failed" in vc.validate_cached(stored, spec, key)


def test_a_record_with_no_captures_is_refused(tmp_path):
    spec = _spec()
    key = vc.cache_key(spec)
    stored = _stored(tmp_path, spec, key, captures=[])
    assert "references no captures" in vc.validate_cached(stored, spec, key)


# --- the sealed candidate --------------------------------------------------------- #

def _zip(path, members):
    import zipfile
    with zipfile.ZipFile(path, "w") as archive:
        for name, blob in members.items():
            archive.writestr(name, blob)
    return path


def test_sealing_records_every_member_and_leaves_the_copy_read_only(tmp_path):
    source = _zip(tmp_path / "candidate.zip", {"PlMtNr.dat": b"dat bytes",
                                               "csp.png": b"portrait"})
    package = vc.seal_candidate(source, tmp_path / "sealed")
    assert package["sha256"] == vc.sha256_file(source)
    assert set(package["members"]) == {"PlMtNr.dat", "csp.png"}
    import hashlib
    assert package["members"]["PlMtNr.dat"] == hashlib.sha256(b"dat bytes").hexdigest()
    with pytest.raises(OSError):
        package["path"].write_bytes(b"tampered")


def test_resealing_replaces_a_previous_read_only_package(tmp_path):
    source = _zip(tmp_path / "a.zip", {"PlMtNr.dat": b"one"})
    vc.seal_candidate(source, tmp_path / "sealed")
    _zip(tmp_path / "a.zip", {"PlMtNr.dat": b"two"})
    package = vc.seal_candidate(tmp_path / "a.zip", tmp_path / "sealed")
    import hashlib
    assert package["members"]["PlMtNr.dat"] == hashlib.sha256(b"two").hexdigest()


def _disc(monkeypatch, tmp_path, before, after, payloads):
    from core import iso_reads
    clean = tmp_path / "clean.iso"
    clean.write_bytes(b"a clean disc")
    built = tmp_path / "built.iso"
    built.write_bytes(b"the built disc")
    monkeypatch.setattr(iso_reads, "file_names",
                        lambda path: before if str(path).endswith("clean.iso") else after)
    monkeypatch.setattr(vc_evidence, "_iter_disc_files",
                        lambda iso, names=None, **kw: iter(
                            [(n, b) for n, b in payloads.items()
                             if names is None or n in set(names)]))
    return str(built), str(clean)


def _package(members):
    return {"members": members}


def test_the_insertion_is_the_file_the_build_ADDED(tmp_path, monkeypatch):
    """Not "the bytes are somewhere on the disc" -- that accepted a matching
    csp.png. The set difference against the clean disc is the insertion."""
    import hashlib
    blob = b"the costume DAT"
    digest = hashlib.sha256(blob).hexdigest()
    built, clean = _disc(monkeypatch, tmp_path, ["PlPkNr.dat", "main.dol"],
                         ["PlPkNr.dat", "main.dol", "PlPkNr_001.dat"],
                         {"PlPkNr_001.dat": blob})
    found = vc.insertion_evidence(built, clean,
                                  _package({"PlPkNr.dat": digest}), "Pikachu",
                                  lambda m: None)
    assert found["insertion_verified"] is True
    assert found["inserted_file"] == "PlPkNr_001.dat"
    assert found["inserted_member"] == "PlPkNr.dat"
    assert found["added_costumes"] == ["PlPkNr_001.dat"]
    assert "m-ex costume table was not read" in found["limitation"]


def test_a_matching_portrait_can_no_longer_satisfy_the_insertion(tmp_path,
                                                                 monkeypatch):
    import hashlib
    blob = b"a portrait, not a costume"
    digest = hashlib.sha256(blob).hexdigest()
    built, clean = _disc(monkeypatch, tmp_path, ["main.dol"],
                         ["main.dol", "csp.png"], {"csp.png": blob})
    found = vc.insertion_evidence(built, clean,
                                  _package({"csp.png": digest}), "Pikachu",
                                  lambda m: None)
    assert found["insertion_verified"] is False
    assert found["added_costumes"] == []


def test_an_added_costume_for_another_fighter_is_not_this_insertion(tmp_path,
                                                                    monkeypatch):
    import hashlib
    blob = b"x"
    built, clean = _disc(monkeypatch, tmp_path, ["main.dol"],
                         ["main.dol", "PlMtNr_001.dat"], {"PlMtNr_001.dat": blob})
    found = vc.insertion_evidence(
        built, clean,
        _package({"PlPkNr.dat": hashlib.sha256(blob).hexdigest()}), "Pikachu",
        lambda m: None)
    assert found["insertion_verified"] is False
    assert "exactly one" in found["insertion_note"]


def test_a_builder_that_transformed_the_bytes_is_said_out_loud(tmp_path,
                                                               monkeypatch):
    built, clean = _disc(monkeypatch, tmp_path, ["main.dol"],
                         ["main.dol", "PlPkNr_001.dat"],
                         {"PlPkNr_001.dat": b"rewritten by the builder"})
    found = vc.insertion_evidence(built, clean,
                                  _package({"PlPkNr.dat": "aa" * 32}),
                                  "Pikachu", lambda m: None)
    assert found["insertion_verified"] is False
    assert "DERIVED costume" in found["insertion_note"]


def test_an_unreadable_disc_does_not_claim_a_verified_insertion(monkeypatch):
    from core import iso_reads

    def explode(path):
        raise ValueError("invalid or truncated FST region")

    monkeypatch.setattr(iso_reads, "file_names", explode)
    found = vc.insertion_evidence("/built.iso", __file__,
                                  _package({"a": "b"}), "Pikachu", lambda m: None)
    assert found["insertion_verified"] is False
    assert "not confirmed" in found["insertion_note"]


# --- the machine ------------------------------------------------------------------ #

def _free_lock(monkeypatch):
    from shared.ingame import dolphin_lock
    monkeypatch.setattr(dolphin_lock, "status",
                        lambda: {"locked": False, "owner": None, "stale": False})
    return dolphin_lock


def test_a_busy_dolphin_is_left_alone_and_nothing_is_built(tmp_path, monkeypatch):
    monkeypatch.setenv("NUCLEUS_VERIFY_CACHE", str(tmp_path / "cache"))
    from shared.ingame import dolphin_lock
    owner = {"pid": 4321, "purpose": "someone else's grading sweep",
             "started_str": "2026-09-22 04:00:00"}
    monkeypatch.setattr(dolphin_lock, "status",
                        lambda: {"locked": True, "owner": owner, "stale": False})
    monkeypatch.setattr(dolphin_lock, "acquire",
                        lambda *a, **k: (_ for _ in ()).throw(dolphin_lock.BusyError(owner)))
    released = []
    monkeypatch.setattr(dolphin_lock, "release", lambda **k: released.append(True))
    monkeypatch.setattr(vc, "_build_iso", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("nothing may be built while another process owns Dolphin")))
    candidate = _zip(tmp_path / "candidate.zip", {"PlMtNr.dat": b"bytes"})

    out = vc.verify(str(candidate), "Mewtwo", destination=str(tmp_path / "out"),
                    log=lambda m: None)
    record = out["game_verification"]
    assert record["outcome"] == "incomplete"
    assert out["outcome_reasons"] == ["dolphin_busy"]
    assert record["captures"] == [] and record["costume_slot"] is None
    check = out["execution_evidence"]["checks"][0]
    assert check["check_id"] == "dolphin_available" and check["status"] == "unknown"
    assert check["observed"]["pid"] == 4321
    assert released == []                       # we never held it
    assert (tmp_path / "out" / "verification.json").is_file()


def test_cancelling_before_the_emulator_starts_never_takes_the_lock(tmp_path,
                                                                    monkeypatch):
    monkeypatch.setenv("NUCLEUS_VERIFY_CACHE", str(tmp_path / "cache"))
    from shared.ingame import dolphin_lock
    monkeypatch.setattr(dolphin_lock, "acquire", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("a cancelled run must not take the machine-wide lock")))
    candidate = _zip(tmp_path / "candidate.zip", {"PlMtNr.dat": b"bytes"})
    stop = threading.Event()
    stop.set()
    with pytest.raises(vc.Cancelled):
        vc.verify(str(candidate), "Mewtwo", destination=str(tmp_path / "out"),
                  stop_event=stop, log=lambda m: None)


def test_two_verifications_in_one_process_do_not_share_the_machine(tmp_path,
                                                                   monkeypatch):
    """Same pid means the file lock "reacquires" happily; the second run must
    not proceed while the first holds the emulator."""
    monkeypatch.setenv("NUCLEUS_VERIFY_CACHE", str(tmp_path / "cache"))
    dolphin_lock = _free_lock(monkeypatch)
    monkeypatch.setattr(dolphin_lock, "acquire",
                        lambda *a, **k: {"pid": 1, "token": "lease"})
    monkeypatch.setattr(dolphin_lock, "release", lambda **k: None)
    inside, second, second_ended = threading.Event(), {}, threading.Event()
    candidate = _zip(tmp_path / "candidate.zip", {"PlMtNr.dat": b"bytes"})

    def slow_build(sealed, character, target, vanilla_iso, nana_file, say):
        target.write_bytes(b"iso")
        inside.set()
        # Hold the machine until the second run has ended (refused, if the guard works), not for a fixed time: a
        # 0.6 s sleep let the second thread arrive after the first had already let go on a loaded machine.
        second_ended.wait(10)
        raise RuntimeError("stop here")

    monkeypatch.setattr(vc, "_build_iso", slow_build)

    def other():
        inside.wait(10)
        try:
            second["manifest"] = vc.verify(str(candidate), "Mewtwo",
                                           destination=str(tmp_path / "out2"),
                                           log=lambda m: None)
        finally:
            second_ended.set()

    worker = threading.Thread(target=other)
    worker.start()
    vc.verify(str(candidate), "Mewtwo", destination=str(tmp_path / "out1"),
              log=lambda m: None)
    worker.join(15)
    record = second["manifest"]["game_verification"]
    assert record["outcome"] == "incomplete"
    assert second["manifest"]["outcome_reasons"] == ["dolphin_busy"]


def test_the_lock_nests_and_only_its_lease_holder_hands_it_back(tmp_path,
                                                                monkeypatch):
    from shared.ingame import dolphin_lock
    monkeypatch.setattr(dolphin_lock, "LOCK_PATH", tmp_path / "harness.lock")
    monkeypatch.setattr(dolphin_lock, "_state", {"depth": 0, "token": None})
    outer = dolphin_lock.acquire("coordinator", wait=1)
    inner = dolphin_lock.acquire("the boot inside it", wait=1)
    assert inner["token"] == outer["token"] and inner["depth"] == 2
    assert dolphin_lock.release() is False          # the boot's own release
    assert dolphin_lock.status()["locked"] is True
    assert dolphin_lock.release(token="not-the-lease") is False
    assert dolphin_lock.status()["locked"] is True
    assert dolphin_lock.release(token=outer["token"]) is True
    assert dolphin_lock.status()["locked"] is False


def test_the_lock_file_is_never_observed_half_written(tmp_path, monkeypatch):
    from shared.ingame import dolphin_lock
    monkeypatch.setattr(dolphin_lock, "LOCK_PATH", tmp_path / "harness.lock")
    monkeypatch.setattr(dolphin_lock, "_state", {"depth": 0, "token": None})
    payload = dolphin_lock.acquire("atomic", wait=1)
    assert json.loads((tmp_path / "harness.lock").read_text())["token"] == payload["token"]
    assert not list(tmp_path.glob("*.tmp"))
    dolphin_lock.release(token=payload["token"])


class _FakeBoot:
    def __init__(self, pid=4242):
        self.pid = pid
        self.proc = types.SimpleNamespace(pid=pid, poll=lambda: 0)

    def terminate(self):
        pass


class _FakeSession:
    def __init__(self, pid=4242, booted=True):
        # frameshot hands the session over BEFORE open(), when it has no child
        # yet; `launch()` is what gives it one.
        self.boot = _FakeBoot(pid) if booted else None
        self._pid = pid
        self.closed = []

    def launch(self):
        self.boot = _FakeBoot(self._pid)

    def alive(self):
        return not self.closed

    def close(self, keep=False):
        self.closed.append(keep)
        return "/runs/kept"


def _stub_capture_plumbing(monkeypatch, run_targets):
    from devtools import frameshot as fs
    monkeypatch.setattr(fs, "run_targets", run_targets)
    monkeypatch.setattr(vc, "_capture_args",
                        lambda *a, **k: (types.SimpleNamespace(char="mewtwo",
                                                               color=4), ["--fake"]))
    monkeypatch.setattr(fs, "make_target", lambda *a, **k: {"id": "t"})
    monkeypatch.setattr(fs, "parse_shots", lambda args: [("idle", [1])])


def test_the_watchdog_stops_an_emulator_whose_BOOT_hangs(monkeypatch):
    """The 2026-09-22 failure: menu navigation spun for 626 s holding the
    machine-wide lock, and the session was handed over before open() returned."""
    import pathlib
    session = _FakeSession(booted=False)

    def hanging_boot(args, iso, targets, out_dir, flat, bag_kind, *,
                     timing=None, on_session=None, stop_event=None):
        on_session(session)          # before open(): no child exists yet
        deadline = time.time() + 5
        while not session.closed and time.time() < deadline:
            time.sleep(0.01)
        timing["boot_seconds"] = 0.4
        raise SystemExit("never reached the offline CSS")

    _stub_capture_plumbing(monkeypatch, hanging_boot)
    monkeypatch.setattr(vc, "PHASE_DEADLINES", {"boot": 0.3, "captures": 5.0})
    owned = {"session": None, "pid": None, "booted": False}
    with pytest.raises(TimeoutError, match="boot deadline"):
        vc._run_captures("/iso", "mewtwo", 4, vc.resolve_profile(),
                         pathlib.Path("."), vc.Timing(), None, 60,
                         lambda m: None, owned=owned)
    assert session.closed == [True]
    # A session that never launched is NOT let go of: a child the worker
    # reaches a moment later must still be stoppable.
    assert owned["awaiting_launch"] is True


def test_cancellation_closes_only_the_session_this_run_opened(monkeypatch):
    import pathlib
    session = _FakeSession(pid=9999)
    stop, started = threading.Event(), threading.Event()

    def fake_run_targets(args, iso, targets, out_dir, flat, bag_kind, *,
                         timing=None, on_session=None, stop_event=None):
        on_session(session)
        started.set()
        deadline = time.time() + 5
        while not session.closed and time.time() < deadline:
            time.sleep(0.01)
        timing["boot_seconds"] = 1.5
        timing["teardown_seconds"] = 0.25
        raise RuntimeError("session closed under the capture loop")

    _stub_capture_plumbing(monkeypatch, fake_run_targets)
    timing = vc.Timing()
    watcher = threading.Thread(target=lambda: (started.wait(2), stop.set()))
    watcher.start()
    with pytest.raises(vc.Cancelled):
        vc._run_captures("/iso", "mewtwo", 4, vc.resolve_profile(),
                         pathlib.Path("."), timing, stop, 60, lambda m: None)
    watcher.join()
    assert session.closed == [True], "exactly one owned session, closed once"
    assert timing.result()["boot"] == 1.5


def test_close_owned_waits_for_the_child_to_actually_exit():
    session = _FakeSession(pid=31337)
    alive = {"n": 3}

    def poll():
        alive["n"] -= 1
        return None if alive["n"] > 0 else 0

    session.boot.proc = types.SimpleNamespace(pid=31337, poll=poll)
    owned = {"session": session, "pid": None}
    vc._close_owned(owned, lambda m: None, wait=2.0)
    assert owned["exited"] is True and owned["pid"] == 31337


def test_close_owned_never_looks_at_anything_it_did_not_start():
    import inspect
    source = inspect.getsource(vc._close_owned) + inspect.getsource(vc._run_captures) \
        + inspect.getsource(vc._await_owned_exit)
    for forbidden in ("taskkill", "psutil.process_iter", "Get-Process",
                      "pkill", "process_iter", "dolphin_running"):
        assert forbidden not in source, forbidden
    assert vc._close_owned({"session": None}, lambda m: None) is None


def test_a_phase_deadline_stops_waiting_on_a_stuck_external_tool(monkeypatch):
    monkeypatch.setattr(vc, "PHASE_DEADLINES", {"iso_build": 0.2})
    monkeypatch.setattr(vc, "_ABANDONED", [])

    def stuck():
        time.sleep(3)

    with pytest.raises(TimeoutError, match="iso_build"):
        vc._deadline("iso_build", None, lambda m: None, stuck)
    assert len(vc._ABANDONED) == 1


def test_a_phase_deadline_returns_the_value_and_re_raises_the_error(monkeypatch):
    monkeypatch.setattr(vc, "PHASE_DEADLINES", {"iso_build": 5.0})
    assert vc._deadline("iso_build", None, lambda m: None, lambda: 7) == 7
    with pytest.raises(ValueError, match="mexcli"):
        vc._deadline("iso_build", None, lambda m: None,
                     lambda: (_ for _ in ()).throw(ValueError("mexcli said no")))


def test_a_lingering_capture_thread_blocks_a_new_run_in_this_process(tmp_path,
                                                                     monkeypatch):
    monkeypatch.setenv("NUCLEUS_VERIFY_CACHE", str(tmp_path / "cache"))
    from shared.ingame import dolphin_lock
    monkeypatch.setattr(dolphin_lock, "acquire", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("the lock must not be taken while a thread is unwinding")))
    release = threading.Event()
    lingering = threading.Thread(target=release.wait, daemon=True)
    lingering.start()
    monkeypatch.setattr(vc, "_ABANDONED", [lingering])
    candidate = _zip(tmp_path / "c.zip", {"PlMtNr.dat": b"c"})
    try:
        manifest = vc.verify(str(candidate), "Mewtwo",
                             destination=str(tmp_path / "out"), log=lambda m: None)
        assert manifest["game_verification"]["outcome"] == "incomplete"
        assert manifest["outcome_reasons"] == ["dolphin_busy"]
    finally:
        release.set()
        lingering.join(2)


# --- the manifest, and the release gate that consumes it ------------------------- #

REQUIRED_FIELDS = ("profile_version", "candidate_hash", "iso_identity",
                   "costume_slot", "captures", "ram_observations", "outcome",
                   "timing")


def _require_a_complete_toolchain(manifest):
    """Only a run whose whole toolchain is identified by content is cached
    (verify(): `cacheable`). A clone gets MexCLI and HSDRawViewer from
    `python tools/build/fetch_native.py all`, and Slippi Dolphin and a vanilla ISO
    at first-run setup; until then nothing is stored and there is nothing to hit."""
    __tracebackhide__ = True
    toolchain = manifest["toolchain"]
    if not toolchain.get("complete"):
        gone = [name for name in ("mexcli", "hsdraw", "mexcli_libraries", "dolphin", "vanilla_iso")
                if toolchain.get(name) is None]
        pytest.skip("needs the whole verification toolchain on disk to cache a result; missing here: "
                    + ", ".join(gone) + " (MexCLI/HSDRawViewer come from `python tools/build/"
                    "fetch_native.py all`, Slippi Dolphin and a vanilla ISO from first-run setup)")


def _full_run(tmp_path, monkeypatch, *, slot=4, statuses="pass"):
    """A complete verify() with the machine and the capture engine stubbed."""
    monkeypatch.setenv("NUCLEUS_VERIFY_CACHE", str(tmp_path / "cache"))
    dolphin_lock = _free_lock(monkeypatch)
    monkeypatch.setattr(dolphin_lock, "acquire",
                        lambda *a, **k: {"pid": 1, "token": "lease"})
    monkeypatch.setattr(dolphin_lock, "release", lambda **k: None)
    profile = vc.resolve_profile()
    profile["expected_captures"] = [c for c in profile["expected_captures"]
                                    if c["move"] != "upb"]
    monkeypatch.setattr(vc, "resolve_profile", lambda *a, **k: profile)
    monkeypatch.setattr(vc_cache, "resolve_profile", lambda *a, **k: profile)
    seen = {}

    def fake_build(sealed, character, target, vanilla_iso, nana_file, say):
        target.write_bytes(b"pretend ISO")
        return slot

    def fake_captures(iso, character, color, resolved, shots_dir, timing,
                      stop_event, timeout, say, owned=None, deadline_at=None):
        seen["color"] = color
        shots_dir.mkdir(parents=True, exist_ok=True)
        for want in resolved["expected_captures"]:
            (shots_dir / f"mewtwo-{want['move']}-f{want['frame']:02d}.png"
             ).write_bytes(b"png")
        for sidecar in _sidecars([f for f in FRAMES if f[0] != "upb"]):
            (shots_dir / f"mewtwo-{sidecar['move']}.json").write_text(
                json.dumps(sidecar), encoding="utf-8")
        timing.add("boot", 92.0)
        timing.add("captures", 61.0)
        return {"targets": [dict(_row(costume_id=slot), dir=str(shots_dir))],
                "boots": 1, "_path": str(shots_dir / "capture-manifest.json")}

    monkeypatch.setattr(vc, "_build_iso", fake_build)
    monkeypatch.setattr(vc, "_run_captures", fake_captures)
    monkeypatch.setattr(vc, "measure_capture",
                        lambda path, appearance, rec=None, folder=None: {
                            "path": str(path), "status": statuses, "reason": "",
                            "measurement": {}, "source": "test"})
    monkeypatch.setattr(vc, "insertion_evidence",
                        lambda iso, clean, package, character, say: {
                            "insertion_verified": True,
                            "inserted_member": "PlMtNr.dat",
                            "inserted_file": "PlMtNr_001.dat",
                            "added_costumes": ["PlMtNr_001.dat"]})
    candidate = _zip(tmp_path / "dragon.zip", {"PlMtNr.dat": b"dragon bytes"})
    said = []
    manifest = vc.verify(str(candidate), "Mewtwo",
                         destination=str(tmp_path / "out"), log=said.append)
    manifest["_log"] = said
    return manifest, seen


def test_the_manifest_carries_exactly_the_gates_game_verification_field(tmp_path,
                                                                        monkeypatch):
    manifest, seen = _full_run(tmp_path, monkeypatch)
    record = manifest["game_verification"]
    assert set(record) == set(REQUIRED_FIELDS)
    assert record["profile_version"] == "costume_verification_v1"
    assert record["candidate_hash"].startswith("sha256:")
    assert record["costume_slot"] == 4 and seen["color"] == 4
    assert record["iso_identity"]["sha256"]
    assert record["iso_identity"]["insertion_verified"] is True
    assert record["iso_identity"]["unchanged_during_capture"] is True
    assert len(record["captures"]) == 9
    assert all({"move", "frame", "path", "hash"} <= set(c)
               for c in record["captures"])
    assert record["ram_observations"]["live_identity"]["costume_id"] == 4
    assert record["ram_observations"]["live_stage_state"]["ground_kind"] == 0x25
    assert record["outcome"] == "verified"
    for phase in ("lock_wait", "iso_build", "boot", "captures", "teardown",
                  "total"):
        assert phase in record["timing"]
    assert manifest["candidate"]["members"] == {
        "PlMtNr.dat": __import__("hashlib").sha256(b"dragon bytes").hexdigest()}
    on_disk = json.loads((tmp_path / "out" / "verification.json").read_text())
    assert on_disk["game_verification"]["outcome"] == "verified"
    _require_a_complete_toolchain(manifest)
    assert on_disk["cache"]["stored"]


def test_the_slot_the_build_chose_is_the_slot_passed_to_capture(tmp_path,
                                                                monkeypatch):
    manifest, seen = _full_run(tmp_path, monkeypatch, slot=7)
    assert seen["color"] == 7
    assert manifest["game_verification"]["costume_slot"] == 7


def test_an_identical_rerun_is_served_from_the_cache_and_still_writes_a_manifest(
        tmp_path, monkeypatch):
    manifest, _ = _full_run(tmp_path, monkeypatch)
    assert manifest["cache"]["hit"] is False
    _require_a_complete_toolchain(manifest)
    dolphin_lock = _free_lock(monkeypatch)
    monkeypatch.setattr(dolphin_lock, "acquire", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("a cache hit must not take the Dolphin lock")))
    monkeypatch.setattr(vc, "_build_iso", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("a cache hit must not build anything")))
    again = vc.verify(str(tmp_path / "dragon.zip"), "Mewtwo",
                      destination=str(tmp_path / "out-again"), log=lambda m: None)
    assert again["cache"]["hit"] is True
    assert again["game_verification"]["outcome"] == "verified"
    written = json.loads((tmp_path / "out-again" / "verification.json").read_text())
    assert written["cache"]["hit"] is True


def test_the_capture_argv_declares_a_fixed_camera_from_the_profile(tmp_path):
    resolved = vc.resolve_profile()
    args, argv = vc._capture_args("/x.iso", "Mewtwo", 4, resolved, tmp_path)
    assert "--fixed-camera" in argv and args.fixed_camera is True
    assert args.closeup is True
    assert args.plain_bg == resolved["appearance"]["background"]
    assert args.cam_dist == resolved["camera"]["cam_dist"]
    assert args.color == 4 and args.stage == resolved["stage"]
    from devtools import frameshot as fs
    assert fs.fit_mode(args) == "measure"
    assert fs.autofit_on(args) is False   # the camera may never be re-framed


def test_the_watchdog_default_survives_the_facades():
    import inspect
    from nucleus_api import game
    from randall.delivery import game_tests
    assert vc.WATCHDOG_SECONDS == 360.0
    for function in (game.verify_costume, game_tests.verify):
        assert "WATCHDOG_SECONDS" in inspect.getsource(function), function.__name__


def test_effects_on_the_boundary_cannot_manufacture_fully_inside(tmp_path):
    """A synthetic actor run off the right edge, with effects covering only 2 %
    of the playfield placed over that edge, came back `clipped: False`."""
    delivered, recorded = _group(tmp_path, "sneak", actor=(400, 1223, 300, 700),
                                 effects=(1200, 1223, 280, 720))
    row = vc.measure_capture(delivered, APPEARANCE, recorded, folder=tmp_path)
    assert row["status"] == "unknown"
    assert row["code"] == "unobservable_boundary"
    assert "right" in row["measurement"]["occluded_edges"]


def test_an_actor_reaching_the_damage_hud_records_that_limitation(tmp_path):
    """The HUD is a standing limitation of this profile, recorded rather than
    silently ignored -- and rather than making every frame unknown, since it
    touches two boundaries on every single one."""
    delivered, recorded = _group(tmp_path, "hud", actor=(400, 900, 400, 800))
    row = vc.measure_capture(delivered, APPEARANCE, recorded, folder=tmp_path)
    assert row["measurement"]["hud_adjacent"] is True
    assert "not observable" in row["measurement"]["hud_limitation"]
    assert row["status"] == "pass"          # not a per-frame unknown


def test_the_unknown_allowlist_is_exactly_what_a_policy_may_soften():
    assert vc_outcome.UNKNOWN_REASON_CODES == frozenset({
        "insufficient_framing", "unobservable_boundary", "unsupported_special",
        "unresolved_isolation", "unmeasurable_render_area",
        "character_kind_unmapped"})
    assert not (vc_outcome.UNKNOWN_REASON_CODES & vc_outcome.INCOMPLETE_REASON_CODES)


def test_deterministic_unknown_is_what_may_be_remembered():
    framing = [{"code": "insufficient_framing", "check": "jab:2", "detail": "x"}]
    transient = [{"code": "harness_error", "check": "run", "detail": "x"}]
    assert vc.deterministic_unknown("unknown", framing) is True
    assert vc.deterministic_unknown("unknown", framing + transient) is False
    assert vc.deterministic_unknown("incomplete", framing) is False
    assert vc.deterministic_unknown("unknown", []) is False


def test_the_whole_run_ceiling_counts_the_build_too(monkeypatch):
    """Counting it from the first capture gave a slow build its minutes back."""
    import pathlib
    session = _FakeSession()

    def slow(args, iso, targets, out_dir, flat, bag_kind, *, timing=None,
             on_session=None, stop_event=None):
        on_session(session)
        deadline = time.time() + 5
        while not session.closed and time.time() < deadline:
            time.sleep(0.01)
        raise SystemExit("stopped")

    _stub_capture_plumbing(monkeypatch, slow)
    monkeypatch.setattr(vc, "PHASE_DEADLINES", {"boot": 60.0, "captures": 60.0})
    with pytest.raises(TimeoutError, match="whole-run ceiling"):
        vc._run_captures("/iso", "mewtwo", 4, vc.resolve_profile(),
                         pathlib.Path("."), vc.Timing(), None, 60,
                         lambda m: None, owned={"session": None, "pid": None},
                         deadline_at=time.monotonic() - 1)


def test_an_inconsistent_manifest_fails_the_self_consistency_check(tmp_path, monkeypatch):
    """A Pikachu manifest with a synthetic passing outcome bound to the dragon
    DAT with no binding errors, and the gate returned pass."""
    from nucleus_api import game
    manifest, _ = _full_run(tmp_path, monkeypatch)
    forged = json.loads(json.dumps(manifest))
    forged["execution_evidence"]["checks"].append(
        {"check_id": "costume_slot_loaded", "status": "unknown", "reason": "x"})
    errors = game.verification_self_consistency(forged, character="Mewtwo")
    assert errors
    assert any("verified" in error for error in errors)

    other = json.loads(json.dumps(manifest))
    other["run"]["character"] = "Pikachu"
    errors = game.verification_self_consistency(other, character="Mewtwo")
    assert any("not Mewtwo" in error for error in errors)

    unproven = json.loads(json.dumps(manifest))
    unproven["game_verification"]["iso_identity"]["insertion_verified"] = False
    errors = game.verification_self_consistency(unproven, character="Mewtwo")
    assert any("not confirmed on the built disc" in e for e in errors)
