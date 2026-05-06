from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable


TASK_TYPE_PATTERNS = {
    "clean_and_place": (r"\bclean\b", r"\bwash\b", r"\brinse\b"),
    "cool_and_place": (r"\bcool\b", r"\bcold\b", r"\bchill\b"),
    "heat_and_place": (r"\bheat\b", r"\bhot\b", r"\bwarm\b"),
    "put_two": (r"\btwo\b", r"\b2\b"),
    "examine": (r"\blook at\b", r"\bexamine\b", r"\binspect\b"),
    "put": (r"\bput\b", r"\bplace\b", r"\bmove\b"),
}

OBJECT_HINTS = {
    "apple",
    "book",
    "bowl",
    "cup",
    "desklamp",
    "egg",
    "fork",
    "knife",
    "lettuce",
    "mug",
    "pan",
    "plate",
    "potato",
    "soapbar",
    "spoon",
    "tomato",
    "towel",
}

RECEPTACLE_HINTS = {
    "cabinet",
    "countertop",
    "desk",
    "drawer",
    "fridge",
    "garbagecan",
    "microwave",
    "shelf",
    "sinkbasin",
    "sofa",
    "table",
}

DEVICE_HINTS = {"fridge", "microwave", "sinkbasin"}


@dataclass(frozen=True)
class AlfworldGoal:
    text: str
    task_type: str
    object_name: str
    target_receptacle: str
    device: str


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def infer_task_type(goal: str) -> str:
    normalized = normalize_text(goal)
    for task_type, patterns in TASK_TYPE_PATTERNS.items():
        if any(re.search(pattern, normalized) for pattern in patterns):
            return task_type
    return "other"


def first_hint(goal: str, hints: Iterable[str], default: str = "unknown") -> str:
    normalized = normalize_text(goal)
    for hint in sorted(hints, key=len, reverse=True):
        if re.search(rf"\b{re.escape(hint)}\b", normalized):
            return hint
    return default


def parse_goal(goal: str) -> AlfworldGoal:
    return AlfworldGoal(
        text=goal,
        task_type=infer_task_type(goal),
        object_name=first_hint(goal, OBJECT_HINTS),
        target_receptacle=first_hint(goal, RECEPTACLE_HINTS),
        device=first_hint(goal, DEVICE_HINTS, default="none"),
    )


def skill_name(skill: str | dict[str, Any]) -> str:
    if isinstance(skill, str):
        return skill
    return str(skill.get("name") or "").strip()


def available_name_set(skills: Iterable[str | dict[str, Any]]) -> set[str]:
    return {name for skill in skills if (name := skill_name(skill))}


def append_first_available(selected: list[str], available: set[str], *candidates: str) -> str | None:
    for candidate in candidates:
        if candidate in available and candidate not in selected:
            selected.append(candidate)
            return candidate
    return None


def select_skill_names(goal: str, available_skills: Iterable[str | dict[str, Any]], *, top_k: int = 4) -> dict[str, Any]:
    parsed = parse_goal(goal)
    available = available_name_set(available_skills)
    selected: list[str] = []

    if parsed.task_type == "clean_and_place":
        append_first_available(selected, available, "alfworld-clean-object", "alfworld-object-state-modifier")
    elif parsed.task_type == "cool_and_place":
        append_first_available(selected, available, "alfworld-object-cooler", "alfworld-temperature-regulator")
    elif parsed.task_type == "heat_and_place":
        append_first_available(selected, available, "alfworld-object-heater", "alfworld-heat-object-with-appliance")
    elif parsed.task_type == "examine":
        append_first_available(selected, available, "alfworld-object-state-inspector", "alfworld-search-verifier")
    elif parsed.task_type == "put_two":
        append_first_available(selected, available, "alfworld-object-retriever", "alfworld-object-transporter")
    elif parsed.task_type == "put":
        append_first_available(selected, available, "alfworld-object-transporter", "alfworld-object-placer")

    append_first_available(selected, available, "alfworld-goal-interpreter", "alfworld-environment-scanner")
    append_first_available(selected, available, "alfworld-locate-target-object", "alfworld-object-locator")
    if parsed.target_receptacle != "unknown":
        append_first_available(selected, available, "alfworld-receptacle-finder", "alfworld-receptacle-navigator")
    if parsed.device != "none":
        append_first_available(selected, available, "alfworld-device-operator", "alfworld-appliance-navigator")
    append_first_available(selected, available, "alfworld-task-verifier", "alfworld-search-verifier")

    selected = selected[: max(0, top_k)]
    return {
        "mode": "goskills_alfworld_selector",
        "goal": parsed.__dict__,
        "captain": selected[0] if selected else "",
        "support": selected[1:],
        "skill_names": selected,
        "summary": render_summary(parsed, selected),
    }


def render_summary(parsed: AlfworldGoal, selected: list[str]) -> str:
    lines = [
        "GoSkills ALFWorld group plan.",
        (
            f"Parsed task_type={parsed.task_type}; object={parsed.object_name}; "
            f"target_receptacle={parsed.target_receptacle}; device={parsed.device}."
        ),
    ]
    if selected:
        lines.append(f"Start: use `{selected[0]}` as the captain skill.")
    if len(selected) > 1:
        lines.append("Support: " + ", ".join(f"`{name}`" for name in selected[1:]) + ".")
    lines.append("Check: preserve ALFWorld action syntax and verify the goal state.")
    lines.append("Avoid: do not follow long plans when a shorter valid action sequence is visible.")
    return "\n".join(lines)
