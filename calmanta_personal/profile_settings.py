from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

RISK_LEVELS = ("no_risk", "low", "medium", "high")
RISK_ACTIONS = {"record_only", "generate_draft"}
DEFAULT_RISK_LEVEL_ACTIONS = {
    "no_risk": "record_only",
    "low": "record_only",
    "medium": "generate_draft",
    "high": "generate_draft",
}
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


def ensure_local_profile(project_home: Path) -> Path:
    """Create or migrate the user-only profile outside the tracked example file."""
    config_dir = project_home / "config"
    local_path = config_dir / "profile.local.json"
    if local_path.is_file():
        return local_path
    config_dir.mkdir(parents=True, exist_ok=True)
    legacy_path = config_dir / "profile.json"
    if legacy_path.is_file():
        legacy_path.replace(local_path)
        return local_path
    example_path = config_dir / "profile.example.json"
    if not example_path.is_file():
        raise ValueError(f"Personal profile example not found: {example_path}")
    local_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")
    return local_path


class ProfileSettings:
    """Read and safely update the user-editable Personal profile settings."""

    def __init__(self, profile_path: Path):
        self.profile_path = profile_path.resolve()

    def risk_level_actions(self) -> dict[str, str]:
        profile = self._profile()
        return _validated_risk_actions(profile.get("risk_level_actions", {}))

    def preview_risk_level_actions(self, changes: dict[str, str]) -> dict[str, Any]:
        validated_changes = _validated_changes(changes)
        current = self.risk_level_actions()
        proposed = {**current, **validated_changes}
        changed = [
            {
                "risk_level": level,
                "risk_label": RISK_LABELS[level],
                "from": current[level],
                "from_label": ACTION_LABELS[current[level]],
                "to": proposed[level],
                "to_label": ACTION_LABELS[proposed[level]],
            }
            for level in RISK_LEVELS
            if current[level] != proposed[level]
        ]
        return {
            "current": current,
            "proposed": proposed,
            "changes": changed,
            "saved": False,
        }

    def save_risk_level_actions(
        self,
        changes: dict[str, str],
        confirmation: str,
    ) -> dict[str, Any]:
        if confirmation != "SAVE":
            raise ValueError("Exact confirmation SAVE is required to change settings")
        preview = self.preview_risk_level_actions(changes)
        if not preview["changes"]:
            return {**preview, "saved": True}
        profile = self._profile()
        profile["risk_level_actions"] = preview["proposed"]
        self._atomic_write(profile)
        return {**preview, "saved": True}

    def voice_templates(self) -> list[dict[str, Any]]:
        profile = self._profile()
        voice_profile = profile.get("voice_profile", {})
        if not isinstance(voice_profile, dict):
            raise ValueError("Personal voice_profile must be an object")
        templates = voice_profile.get("custom_templates", [])
        if not isinstance(templates, list):
            raise ValueError("voice_profile.custom_templates must be an array")
        return [dict(item) for item in templates if isinstance(item, dict)]

    def save_voice_template(self, template: dict[str, Any], confirmation: str) -> dict[str, Any]:
        _require_template_confirmation(template, confirmation)
        template_id = str(template.get("id", "")).strip()
        if not template_id:
            raise ValueError("Voice template id is required")
        templates = self.voice_templates()
        if len(templates) >= 12:
            raise ValueError("At most 12 voice templates are allowed")
        if any(item.get("id") == template_id for item in templates):
            raise ValueError("Voice template id already exists")
        _validate_unique_template_bindings(templates + [template])
        profile = self._profile()
        voice_profile = dict(profile.get("voice_profile", {}))
        voice_profile["custom_templates"] = templates + [template]
        profile["voice_profile"] = voice_profile
        self._atomic_write(profile)
        return template

    def get_voice_template(self, template_id: str) -> dict[str, Any]:
        for template in self.voice_templates():
            if template.get("id") == template_id:
                return template
        raise ValueError("Voice template not found")

    def update_voice_template(self, template: dict[str, Any], confirmation: str) -> dict[str, Any]:
        _require_template_confirmation(template, confirmation)
        template_id = str(template.get("id", "")).strip()
        existing = self.get_voice_template(template_id)
        updated = dict(template)
        updated["created_at"] = existing.get("created_at", updated.get("created_at", ""))
        templates = [updated if item.get("id") == template_id else item for item in self.voice_templates()]
        _validate_unique_template_bindings(templates)
        self._save_voice_templates(templates)
        return updated

    def add_voice_template_bindings(
        self,
        template_id: str,
        scenario_ids: list[str],
        confirmation: str,
    ) -> dict[str, Any]:
        if confirmation != "SAVE":
            raise ValueError("Exact confirmation SAVE is required to add reply categories")
        template = self.get_voice_template(template_id)
        combined = list(dict.fromkeys(list(template.get("when", [])) + scenario_ids))
        _validate_scenario_ids(combined, allow_empty=_template_status(template) == "draft")
        updated = {**template, "when": combined}
        return self.update_voice_template(
            updated,
            "SAVE_DRAFT" if _template_status(template) == "draft" else "SAVE",
        )

    def remove_voice_template_binding(
        self,
        template_id: str,
        scenario_id: str,
        confirmation: str,
    ) -> dict[str, Any]:
        if confirmation != "SAVE":
            raise ValueError("Exact confirmation SAVE is required to remove a reply category")
        template = self.get_voice_template(template_id)
        bindings = list(template.get("when", []))
        if scenario_id not in bindings:
            raise ValueError("This reply category is not bound to the template")
        remaining = [item for item in bindings if item != scenario_id]
        if not remaining and _template_status(template) != "draft":
            raise ValueError("A voice template must keep at least one reply category; delete it instead")
        updated = {**template, "when": remaining}
        return self.update_voice_template(
            updated,
            "SAVE_DRAFT" if _template_status(template) == "draft" else "SAVE",
        )

    def set_voice_template_enabled(
        self,
        template_id: str,
        enabled: bool,
        confirmation: str,
    ) -> dict[str, Any]:
        return self.set_voice_template_status(
            template_id,
            "enabled" if enabled else "disabled",
            confirmation,
        )

    def set_voice_template_status(
        self,
        template_id: str,
        status: str,
        confirmation: str,
    ) -> dict[str, Any]:
        if status not in VOICE_TEMPLATE_STATUS_LABELS:
            raise ValueError("Voice template status must be draft, enabled, or disabled")
        _require_template_confirmation({"status": status}, confirmation)
        templates = self.voice_templates()
        for template in templates:
            if template.get("id") == template_id:
                template["status"] = status
                template["enabled"] = status == "enabled"
                profile = self._profile()
                voice_profile = dict(profile.get("voice_profile", {}))
                voice_profile["custom_templates"] = templates
                profile["voice_profile"] = voice_profile
                self._atomic_write(profile)
                return template
        raise ValueError("Voice template not found")

    def delete_voice_template(self, template_id: str, confirmation: str) -> None:
        if confirmation != "DELETE":
            raise ValueError("Exact confirmation DELETE is required to delete a voice template")
        templates = self.voice_templates()
        remaining = [item for item in templates if item.get("id") != template_id]
        if len(remaining) == len(templates):
            raise ValueError("Voice template not found")
        profile = self._profile()
        voice_profile = dict(profile.get("voice_profile", {}))
        voice_profile["custom_templates"] = remaining
        profile["voice_profile"] = voice_profile
        self._atomic_write(profile)

    def _save_voice_templates(self, templates: list[dict[str, Any]]) -> None:
        profile = self._profile()
        voice_profile = dict(profile.get("voice_profile", {}))
        voice_profile["custom_templates"] = templates
        profile["voice_profile"] = voice_profile
        self._atomic_write(profile)

    def _profile(self) -> dict[str, Any]:
        if not self.profile_path.is_file():
            raise ValueError(f"Profile configuration not found: {self.profile_path}")
        raw = json.loads(self.profile_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Personal profile must contain a JSON object")
        return raw

    def _atomic_write(self, profile: dict[str, Any]) -> None:
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.profile_path.parent,
                prefix=f".{self.profile_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(profile, temporary, ensure_ascii=False, indent=2)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path.replace(self.profile_path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()


def format_settings_panel(
    actions: dict[str, str],
    templates: list[dict[str, Any]] | None = None,
    *,
    preview: bool = False,
) -> str:
    validated = _validated_risk_actions(actions)
    title = "Calmanta Personal 风险处理设置"
    if preview:
        title += "（未保存预览）"
    lines = [title, ""]
    lines.extend(
        f"{RISK_LABELS[level]}：{ACTION_LABELS[validated[level]]}" for level in RISK_LEVELS
    )
    lines.extend(
        (
            "",
            "可选处理方式：生成草稿 / 仅记录",
            "强制安全规则不会被这些设置覆盖。",
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
    fallback = [label for scenario, label in VOICE_TEMPLATE_SCENARIOS.items() if scenario not in active_bindings]
    if fallback:
        lines.append("使用基础口吻规则：" + "、".join(fallback))
    return "\n".join(lines)


def format_voice_template_preview(template: dict[str, Any]) -> str:
    labels = "、".join(_scenario_label(item) for item in template.get("when", []))
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
    lines.extend(("", "可以说“保存口吻模板”直接启用，或“保存口吻模板草稿”稍后继续编辑。"))
    return "\n".join(lines)


def _template_line(template: dict[str, Any]) -> str:
    name = str(template.get("name", "未命名模板"))
    scenarios = "、".join(_scenario_label(item) for item in template.get("when", []))
    status = VOICE_TEMPLATE_STATUS_LABELS[_template_status(template)]
    return f"- {name}：{scenarios or '暂未选择评论类别'}（{status}）"


def _scenario_label(value: Any) -> str:
    return VOICE_TEMPLATE_SCENARIOS.get(str(value), "未知评论类别")


def _validate_scenario_ids(scenario_ids: list[str], *, allow_empty: bool = False) -> None:
    if not scenario_ids and not allow_empty:
        raise ValueError("Choose at least one voice-template scenario")
    unknown = [item for item in scenario_ids if item not in VOICE_TEMPLATE_SCENARIOS]
    if unknown:
        raise ValueError("Unknown voice-template scenario: " + ", ".join(unknown))


def _validate_unique_template_bindings(templates: list[dict[str, Any]]) -> None:
    owners: dict[str, str] = {}
    for template in templates:
        template_id = str(template.get("id", ""))
        bindings = template.get("when", [])
        if not isinstance(bindings, list):
            raise ValueError("Voice template when must be an array")
        if _template_status(template) == "draft":
            _validate_scenario_ids([str(item) for item in bindings], allow_empty=True)
            continue
        _validate_scenario_ids([str(item) for item in bindings])
        for scenario in bindings:
            existing = owners.get(str(scenario))
            if existing is not None:
                raise ValueError(
                    "Each reply category can use only one voice template: " +
                    VOICE_TEMPLATE_SCENARIOS[str(scenario)]
                )
            owners[str(scenario)] = template_id


def _template_status(template: dict[str, Any]) -> str:
    raw = template.get("status")
    if raw is None:
        raw = "enabled" if template.get("enabled", True) else "disabled"
    status = str(raw)
    if status not in VOICE_TEMPLATE_STATUS_LABELS:
        raise ValueError("Voice template status must be draft, enabled, or disabled")
    return status


def _require_template_confirmation(template: dict[str, Any], confirmation: str) -> None:
    expected = "SAVE_DRAFT" if _template_status(template) == "draft" else "SAVE"
    if confirmation != expected:
        raise ValueError(f"Exact confirmation {expected} is required to save a voice template")


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
            raise ValueError(f"Duplicate risk level in settings change: {level}")
        changes[level] = action
    return _validated_changes(changes)


def _validated_changes(changes: dict[str, str]) -> dict[str, str]:
    if not changes:
        raise ValueError("At least one risk setting change is required")
    unknown_levels = sorted(set(changes) - set(RISK_LEVELS))
    if unknown_levels:
        raise ValueError("Unknown risk level: " + ", ".join(unknown_levels))
    invalid_actions = sorted(
        f"{level}={action}" for level, action in changes.items() if action not in RISK_ACTIONS
    )
    if invalid_actions:
        raise ValueError(
            "Risk actions must be record_only or generate_draft: " + ", ".join(invalid_actions)
        )
    return {level: str(changes[level]) for level in RISK_LEVELS if level in changes}


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
