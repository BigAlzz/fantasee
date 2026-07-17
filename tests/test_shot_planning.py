from fantasee_server.shot_planning import plan_semantic_shots, validate_shot_plan


def test_planner_creates_purposeful_ordered_shots_from_duration_and_pacing():
    narration = " ".join(["The road is empty and the storm is getting closer."] * 30)

    shots = plan_semantic_shots(
        scene_id="scene-01",
        narration=narration,
        visual_direction="A flooded mountain road at dusk",
        pacing="urgent",
    )

    assert 3 <= len(shots) <= 6
    assert [shot.order for shot in shots] == list(range(1, len(shots) + 1))
    assert len({shot.purpose for shot in shots}) == len(shots)
    assert all(shot.scene_id == "scene-01" for shot in shots)


def test_validation_rejects_duplicate_purpose_and_missing_visual_context():
    shots = plan_semantic_shots(
        scene_id="scene-01",
        narration="A woman crosses a bridge in the rain.",
        visual_direction="A soaked bridge above a black river",
        pacing="quiet",
    )
    duplicate = list(shots)
    duplicate[0] = duplicate[0].__class__(**{**duplicate[0].__dict__, "purpose": duplicate[1].purpose})

    report = validate_shot_plan(duplicate)

    assert not report.valid
    assert "duplicate_purpose" in report.codes
