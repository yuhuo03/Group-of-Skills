from __future__ import annotations

from evaluation.alfworld.goskills_selector import parse_goal, select_skill_names


AVAILABLE = [
    "alfworld-clean-object",
    "alfworld-object-cooler",
    "alfworld-object-heater",
    "alfworld-object-state-inspector",
    "alfworld-locate-target-object",
    "alfworld-receptacle-finder",
    "alfworld-device-operator",
    "alfworld-task-verifier",
]


def test_alfworld_clean_and_place_selects_state_captain() -> None:
    result = select_skill_names("put a clean apple in fridge", AVAILABLE, top_k=4)

    assert result["mode"] == "goskills_alfworld_selector"
    assert result["captain"] == "alfworld-clean-object"
    assert "alfworld-locate-target-object" in result["skill_names"]
    assert "alfworld-receptacle-finder" in result["skill_names"]


def test_alfworld_goal_parser_detects_device() -> None:
    parsed = parse_goal("heat a mug and put it in the microwave")

    assert parsed.task_type == "heat_and_place"
    assert parsed.object_name == "mug"
    assert parsed.device == "microwave"
