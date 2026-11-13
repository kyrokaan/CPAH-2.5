from __future__ import annotations

import pytest

from cpah import constants, logic, models


@pytest.mark.parametrize(
    ("version", "legacy"),
    (
        (1, {"target_detection_threshold": 0.7}),
        (2, {"autohack_activation_key": "f"}),
        (3, {}),
        (4, {"daemon_toggle_hotkey": ["control", "shift"]}),
        (5, {"daemon_toggle_hotkey": ["controlshift"]}),
        (6, {"daemon_toggle_hotkey": ["control", "shift"]}),
    ),
)
def test_every_historical_schema_migrates_to_a_valid_config(version, legacy):
    migrated = logic._migrate_config({"schema_version": version, **legacy})
    config = models.Config.model_validate(migrated)
    assert config.schema_version == 7
    assert config.objective_toggle_hotkey == ["control", "shift"]


def test_schema_6_migrates_objectives_and_discards_ahk():
    migrated = logic._migrate_config(
        {
            "schema_version": 6,
            "daemon_priorities": ["datamine_v1", "datamine_v3", "icepick"],
            "daemon_toggle_hotkey": ["control", "shift"],
            "daemon_detection_threshold": 0.65,
            "ahk_enabled": True,
            "ahk_executable": "AutoHotkey.exe",
            "ahk_autohack_key_bindings": {},
        }
    )
    assert migrated["schema_version"] == 7
    assert migrated["objective_priorities"] == ["basic_datamine", "expert_datamine"]
    assert migrated["objective_toggle_hotkey"] == ["control", "shift"]
    assert migrated["objective_detection_threshold"] == 0.65
    assert "ahk_enabled" not in migrated


def test_tuple_solver_supports_code_ids_greater_than_nine():
    puzzle = models.Puzzle(
        matrix=((10, 0), (1, 2)),
        buffer_size=1,
        objectives=(models.SequenceObjective((10,), "Custom"),),
    )
    result = logic.calculate_sequence_path_data(puzzle, (0,))
    assert result.solution_valid
    assert result.shortest_solution == (10,)


def test_force_solver_scores_datamines_by_objective_not_screen_order():
    puzzle = models.Puzzle(
        matrix=(
            (0, 0, 1, 4, 1),
            (1, 3, 4, 0, 3),
            (0, 3, 1, 4, 4),
            (0, 3, 3, 0, 1),
            (1, 1, 0, 1, 1),
        ),
        buffer_size=4,
        objectives=(
            models.SequenceObjective((1, 0, 1), "EXPERT DATAMINE", "datamine_v3"),
            models.SequenceObjective((1, 3), "BASIC DATAMINE", "datamine_v1"),
            models.SequenceObjective((3, 1), "ADVANCED DATAMINE", "datamine_v2"),
        ),
    )
    result, selected = logic.force_calculate_sequence_path_data(models.Config(), puzzle)
    assert result.solution_valid
    assert selected == (0, 1)


def test_autohack_refuses_invalid_solution(monkeypatch):
    sent = []
    monkeypatch.setattr(logic.windows, "send_key", lambda *args: sent.append(args))
    result = models.SequencePathData((), None, None, False, False)
    puzzle = models.Puzzle(matrix=((0,),), buffer_size=1, objectives=())
    with pytest.raises(ValueError, match="Refusing to send input"):
        logic.autohack(models.Config(), puzzle, models.ScreenshotData(None), result)
    assert sent == []


def test_current_release_metadata():
    assert constants.CONFIG_SCHEMA_VERSION == 7
    assert constants.VERSION == "2.5.0"
