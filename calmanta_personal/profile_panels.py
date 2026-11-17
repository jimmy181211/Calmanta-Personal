"""Render settings and template previews; never persist user choices."""

from __future__ import annotations

from typing import Any

from .profile_rules import (
    ACTION_LABELS,
    DEFAULT_REPLY_WORTHINESS_THRESHOLD,
    RISK_LABELS,
    RISK_LEVELS,
    VOICE_TEMPLATE_SCENARIOS,
    VOICE_TEMPLATE_STATUS_LABELS,
    _template_status,
    _validated_reply_worthiness_threshold,
    _validated_risk_actions,
)


def format_settings_panel(
    actions: dict[str, str],
    templates: list[dict[str, Any]] | None = None,
    *,
    threshold: int = DEFAULT_REPLY_WORTHINESS_THRESHOLD,
    preview: bool = False,
) -> str:
    """Describe current or proposed settings without changing the profile."""
    validated = _validated_risk_actions(actions)
    threshold = _validated_reply_worthiness_threshold(threshold)
    title = "Calmanta Personal 草稿设置"
    if preview:
        title += "（未保存预览）"
    lines = [title, "", f"回复价值门槛：{threshold} / 100", ""]
    lines.extend(
        f"{RISK_LABELS[level]}：{ACTION_LABELS[validated[level]]}"
        for level in RISK_LEVELS
    )
    lines.extend(
        (
            "",
            "风险策略和回复价值门槛都通过，才会生成草稿。",
            "威胁、隐私和敏感决定不会生成草稿。",
        )
    )
    templates = templates or []
    lines.extend(("", f"我的口吻模板：{len(templates)} 个"))
    if templates:
        lines.extend(_template_line(template) for template in templates)
    else:
        lines.append("还没有个人模板。可以说“添加口吻模板”。")
    lines.append("个人模板只改变表达方式，不会覆盖基础口吻或安全规则。")
    active_bindings = {
        scenario
        for template in templates
        if _template_status(template) == "enabled"
        for scenario in template.get("when", [])
    }
    fallback = [
        label
        for scenario, label in VOICE_TEMPLATE_SCENARIOS.items()
        if scenario not in active_bindings
    ]
    if fallback:
        lines.append("使用基础口吻规则：" + "、".join(fallback))
    return "\n".join(lines)


def format_voice_template_preview(template: dict[str, Any]) -> str:
    """Render the unsaved template so the user can review its exact contents."""
    labels = "、".join(
        _scenario_label(item) for item in template.get("when", [])
    )
    examples = template.get("examples", [])
    lines = [
        "口吻模板预览（尚未保存）",
        "",
        f"名称：{template.get('name', '')}",
        f"适用评论类别：{labels}",
        "规则：",
    ]
    lines.extend(f"- {rule}" for rule in template.get("rules", []))
    if examples:
        lines.append("示例：")
        lines.extend(f"- {example}" for example in examples)
    avoided = template.get("avoid_phrases", [])
    if avoided:
        lines.append("避免：" + "、".join(avoided))
    lines.extend(
        ("", "可以说“保存口吻模板”直接启用，或“保存口吻模板草稿”稍后继续编辑。")
    )
    return "\n".join(lines)


def _template_line(template: dict[str, Any]) -> str:
    name = str(template.get("name", "未命名模板"))
    scenarios = "、".join(
        _scenario_label(item) for item in template.get("when", [])
    )
    status = VOICE_TEMPLATE_STATUS_LABELS[_template_status(template)]
    return f"- {name}：{scenarios or '暂未选择评论类别'}（{status}）"


def _scenario_label(value: Any) -> str:
    return VOICE_TEMPLATE_SCENARIOS.get(str(value), "未知评论类别")
