"""Validate draft policies and voice bindings without reading files."""

from __future__ import annotations

from typing import Any

RISK_LEVELS = ("no_risk", "low", "medium", "high")

RISK_ACTIONS = {"record_only", "generate_draft"}

DEFAULT_RISK_LEVEL_ACTIONS = {
    "no_risk": "record_only",
    "low": "record_only",
    "medium": "generate_draft",
    "high": "record_only",
}

DEFAULT_REPLY_WORTHINESS_THRESHOLD = 75

RISK_LABELS = {
    "no_risk": "无风险",
    "low": "低风险",
    "medium": "中风险",
    "high": "高风险",
}

ACTION_LABELS = {
    "record_only": "仅记录",
    "generate_draft": "生成草稿",
}

VOICE_TEMPLATE_SCENARIOS = {
    "friendly_or_ordinary": "友好或普通交流",
    "ordinary_question": "提问",
    "factual_correction": "事实纠正",
    "ordinary_disagreement": "普通质疑或分歧",
    "unverified_accusation": "未证实指控",
    "personal_attack": "侮辱或人身攻击",
    "continued_harassment": "持续骚扰",
}

VOICE_TEMPLATE_STATUS_LABELS = {
    "draft": "草稿",
    "enabled": "已启用",
    "disabled": "已停用",
}


def _validate_scenario_ids(
    scenario_ids: list[str], *, allow_empty: bool = False
) -> None:
    if not scenario_ids and not allow_empty:
        raise ValueError("Choose at least one voice-template scenario")
    unknown = [
        item for item in scenario_ids if item not in VOICE_TEMPLATE_SCENARIOS
    ]
    if unknown:
        raise ValueError(
            "Unknown voice-template scenario: " + ", ".join(unknown)
        )


def _validate_unique_template_bindings(templates: list[dict[str, Any]]) -> None:
    """Reject overlapping active bindings while allowing unfinished drafts."""
    owners: dict[str, str] = {}
    for template in templates:
        template_id = str(template.get("id", ""))
        bindings = template.get("when", [])
        if not isinstance(bindings, list):
            raise ValueError("Voice template when must be an array")
        if _template_status(template) == "draft":
            _validate_scenario_ids(
                [str(item) for item in bindings], allow_empty=True
            )
            continue
        _validate_scenario_ids([str(item) for item in bindings])
        for scenario in bindings:
            existing = owners.get(str(scenario))
            if existing is not None:
                raise ValueError(
                    "Each reply category can use only one voice template: "
                    + VOICE_TEMPLATE_SCENARIOS[str(scenario)]
                )
            owners[str(scenario)] = template_id


def _template_status(template: dict[str, Any]) -> str:
    raw = template.get("status")
    if raw is None:
        raw = "enabled" if template.get("enabled", True) else "disabled"
    status = str(raw)
    if status not in VOICE_TEMPLATE_STATUS_LABELS:
        raise ValueError(
            "Voice template status must be draft, enabled, or disabled"
        )
    return status


def _require_template_confirmation(
    template: dict[str, Any], confirmation: str
) -> None:
    expected = "SAVE_DRAFT" if _template_status(template) == "draft" else "SAVE"
    if confirmation != expected:
        raise ValueError(
            (
                "Exact confirmation "
                f"{expected}"
                " is required to save a voice template"
            )
        )


def parse_risk_changes(values: list[str]) -> dict[str, str]:
    if not values:
        raise ValueError("At least one --set LEVEL=ACTION value is required")
    changes: dict[str, str] = {}
    for value in values:
        level, separator, action = value.partition("=")
        level = level.strip()
        action = action.strip()
        if not separator or not level or not action:
            raise ValueError("Each --set value must use LEVEL=ACTION")
        if level in changes:
            raise ValueError(
                f"Duplicate risk level in settings change: {level}"
            )
        changes[level] = action
    return _validated_changes(changes)


def _validated_changes(changes: dict[str, str]) -> dict[str, str]:
    if not changes:
        raise ValueError("At least one risk setting change is required")
    unknown_levels = sorted(set(changes) - set(RISK_LEVELS))
    if unknown_levels:
        raise ValueError("Unknown risk level: " + ", ".join(unknown_levels))
    invalid_actions = sorted(
        f"{level}={action}"
        for level, action in changes.items()
        if action not in RISK_ACTIONS
    )
    if invalid_actions:
        raise ValueError(
            "Risk actions must be record_only or generate_draft: "
            + ", ".join(invalid_actions)
        )
    return {
        level: str(changes[level]) for level in RISK_LEVELS if level in changes
    }


def _validated_risk_actions(supplied: Any) -> dict[str, str]:
    if not isinstance(supplied, dict):
        raise ValueError("Personal risk_level_actions must be an object")
    actions = {**DEFAULT_RISK_LEVEL_ACTIONS, **supplied}
    for level in RISK_LEVELS:
        if actions.get(level) not in RISK_ACTIONS:
            raise ValueError(
                f"Personal risk_level_actions.{level} must be "
                "record_only or generate_draft"
            )
    return {level: str(actions[level]) for level in RISK_LEVELS}


def _validated_reply_worthiness_threshold(value: Any) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > 100
    ):
        raise ValueError(
            "reply_worthiness_threshold must be an integer from 0 to 100"
        )
    return value
