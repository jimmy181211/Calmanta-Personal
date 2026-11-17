"""Persist validated local settings without changing unrelated profile
fields.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .profile_panels import (  # noqa: F401
    _scenario_label,
    _template_line,
    format_settings_panel,
    format_voice_template_preview,
)
from .profile_rules import (  # noqa: F401
    ACTION_LABELS,
    DEFAULT_REPLY_WORTHINESS_THRESHOLD,
    DEFAULT_RISK_LEVEL_ACTIONS,
    RISK_ACTIONS,
    RISK_LABELS,
    RISK_LEVELS,
    VOICE_TEMPLATE_SCENARIOS,
    VOICE_TEMPLATE_STATUS_LABELS,
    _require_template_confirmation,
    _template_status,
    _validate_scenario_ids,
    _validate_unique_template_bindings,
    _validated_changes,
    _validated_reply_worthiness_threshold,
    _validated_risk_actions,
    parse_risk_changes,
)


def ensure_local_profile(project_home: Path) -> Path:
    """Create or migrate the user-only profile outside the tracked example
    file.
    """
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
    local_path.write_text(
        example_path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return local_path


class ProfileSettings:
    """Read and safely update the user-editable Personal profile settings."""

    def __init__(self, profile_path: Path):
        self.profile_path = profile_path.resolve()

    def risk_level_actions(self) -> dict[str, str]:
        profile = self._profile()
        return _validated_risk_actions(profile.get("risk_level_actions", {}))

    def reply_worthiness_threshold(self) -> int:
        return _validated_reply_worthiness_threshold(
            self._profile().get(
                "reply_worthiness_threshold",
                DEFAULT_REPLY_WORTHINESS_THRESHOLD,
            )
        )

    def preview_risk_level_actions(
        self, changes: dict[str, str]
    ) -> dict[str, Any]:
        """Build a comparison without writing the proposed policy to disk."""
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

    def preview_draft_settings(
        self,
        changes: dict[str, str],
        threshold: int | None,
    ) -> dict[str, Any]:
        """Validate policy and threshold changes together without saving
        them.
        """
        current_actions = self.risk_level_actions()
        proposed_actions = (
            {**current_actions, **_validated_changes(changes)}
            if changes
            else current_actions
        )
        current_threshold = self.reply_worthiness_threshold()
        proposed_threshold = (
            current_threshold
            if threshold is None
            else _validated_reply_worthiness_threshold(threshold)
        )
        if not changes and threshold is None:
            raise ValueError("At least one draft setting change is required")
        return {
            "current": current_actions,
            "proposed": proposed_actions,
            "changes": [
                {
                    "risk_level": level,
                    "risk_label": RISK_LABELS[level],
                    "from": current_actions[level],
                    "from_label": ACTION_LABELS[current_actions[level]],
                    "to": proposed_actions[level],
                    "to_label": ACTION_LABELS[proposed_actions[level]],
                }
                for level in RISK_LEVELS
                if current_actions[level] != proposed_actions[level]
            ],
            "current_threshold": current_threshold,
            "proposed_threshold": proposed_threshold,
            "threshold_changed": current_threshold != proposed_threshold,
            "saved": False,
        }

    def save_draft_settings(
        self,
        changes: dict[str, str],
        threshold: int | None,
        confirmation: str,
    ) -> dict[str, Any]:
        """Persist the validated preview only after the required
        confirmation.
        """
        if confirmation != "SAVE":
            raise ValueError(
                "Exact confirmation SAVE is required to change settings"
            )
        preview = self.preview_draft_settings(changes, threshold)
        profile = self._profile()
        profile["risk_level_actions"] = preview["proposed"]
        profile["reply_worthiness_threshold"] = preview["proposed_threshold"]
        self._atomic_write(profile)
        return {**preview, "saved": True}

    def save_risk_level_actions(
        self,
        changes: dict[str, str],
        confirmation: str,
    ) -> dict[str, Any]:
        """Save confirmed policy changes while retaining unrelated profile
        fields.
        """
        if confirmation != "SAVE":
            raise ValueError(
                "Exact confirmation SAVE is required to change settings"
            )
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

    def save_voice_template(
        self, template: dict[str, Any], confirmation: str
    ) -> dict[str, Any]:
        """Validate the reviewed template and atomically update the local
        profile.
        """
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

    def update_voice_template(
        self, template: dict[str, Any], confirmation: str
    ) -> dict[str, Any]:
        """Replace editable fields while preserving the saved template
        identity.
        """
        _require_template_confirmation(template, confirmation)
        template_id = str(template.get("id", "")).strip()
        existing = self.get_voice_template(template_id)
        updated = dict(template)
        updated["created_at"] = existing.get(
            "created_at", updated.get("created_at", "")
        )
        templates = [
            updated if item.get("id") == template_id else item
            for item in self.voice_templates()
        ]
        _validate_unique_template_bindings(templates)
        self._save_voice_templates(templates)
        return updated

    def add_voice_template_bindings(
        self,
        template_id: str,
        scenario_ids: list[str],
        confirmation: str,
    ) -> dict[str, Any]:
        """Add category bindings without assigning a category to two
        templates.
        """
        if confirmation != "SAVE":
            raise ValueError(
                "Exact confirmation SAVE is required to add reply categories"
            )
        template = self.get_voice_template(template_id)
        combined = list(
            dict.fromkeys(list(template.get("when", [])) + scenario_ids)
        )
        _validate_scenario_ids(
            combined, allow_empty=_template_status(template) == "draft"
        )
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
        """Remove the selected category and retain the remaining bindings."""
        if confirmation != "SAVE":
            raise ValueError(
                (
                    "Exact confirmation SAVE is "
                    "required to remove a reply "
                    "category"
                )
            )
        template = self.get_voice_template(template_id)
        bindings = list(template.get("when", []))
        if scenario_id not in bindings:
            raise ValueError(
                ("This reply category is not bound to the template")
            )
        remaining = [item for item in bindings if item != scenario_id]
        if not remaining and _template_status(template) != "draft":
            raise ValueError(
                (
                    "A voice template must keep at least one reply category; "
                    "delete it instead"
                )
            )
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
        """Validate the requested lifecycle state before persisting the
        template.
        """
        if status not in VOICE_TEMPLATE_STATUS_LABELS:
            raise ValueError(
                "Voice template status must be draft, enabled, or disabled"
            )
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

    def delete_voice_template(
        self, template_id: str, confirmation: str
    ) -> None:
        """Delete only the explicitly confirmed template from the local
        profile.
        """
        if confirmation != "DELETE":
            raise ValueError(
                (
                    "Exact confirmation DELETE is required to delete a voice "
                    "template"
                )
            )
        templates = self.voice_templates()
        remaining = [
            item for item in templates if item.get("id") != template_id
        ]
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
            raise ValueError(
                f"Profile configuration not found: {self.profile_path}"
            )
        raw = json.loads(self.profile_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Personal profile must contain a JSON object")
        return raw

    def _atomic_write(self, profile: dict[str, Any]) -> None:
        """Replace the profile only after a temporary file is fully written
        and synced.
        """
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
