from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from calmanta_personal.cli import main
from calmanta_personal.profile_settings import (
    ProfileSettings,
    format_settings_panel,
    format_voice_template_preview,
    parse_risk_changes,
)


class ProfileSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.profile_path = self.root / "config" / "profile.local.json"
        self.profile_path.parent.mkdir(parents=True)
        self.profile_path.write_text(
            json.dumps(
                {
                    "max_reply_chars": 300,
                    "risk_level_actions": {
                        "no_risk": "record_only",
                        "low": "record_only",
                        "medium": "generate_draft",
                        "high": "generate_draft",
                    },
                    "voice_profile": {"summary": "保持温和"},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self.settings = ProfileSettings(self.profile_path)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_preview_does_not_modify_profile(self) -> None:
        before = self.profile_path.read_text(encoding="utf-8")
        preview = self.settings.preview_risk_level_actions(
            {"low": "generate_draft", "high": "record_only"}
        )
        self.assertFalse(preview["saved"])
        self.assertEqual("generate_draft", preview["proposed"]["low"])
        self.assertEqual("record_only", preview["proposed"]["high"])
        self.assertEqual(before, self.profile_path.read_text(encoding="utf-8"))

    def test_save_requires_confirmation_and_preserves_other_profile_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "SAVE"):
            self.settings.save_risk_level_actions({"low": "generate_draft"}, "save")

        result = self.settings.save_risk_level_actions(
            {"low": "generate_draft"},
            "SAVE",
        )
        saved_profile = json.loads(self.profile_path.read_text(encoding="utf-8"))
        self.assertTrue(result["saved"])
        self.assertEqual("generate_draft", saved_profile["risk_level_actions"]["low"])
        self.assertEqual(300, saved_profile["max_reply_chars"])
        self.assertEqual({"summary": "保持温和"}, saved_profile["voice_profile"])

    def test_only_two_risk_actions_are_allowed(self) -> None:
        with self.assertRaisesRegex(ValueError, "record_only or generate_draft"):
            self.settings.preview_risk_level_actions({"low": "silent_record"})
        panel = format_settings_panel(self.settings.risk_level_actions())
        self.assertIn("风险策略和回复价值门槛都通过", panel)
        self.assertNotIn("静默记录", panel)

    def test_change_parser_rejects_unknown_and_duplicate_levels(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown risk level"):
            parse_risk_changes(["critical=record_only"])
        with self.assertRaisesRegex(ValueError, "Duplicate risk level"):
            parse_risk_changes(["low=record_only", "low=generate_draft"])

    def test_settings_show_works_without_loading_database_or_portable_core(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(["--home", str(self.root), "settings", "show"])
        payload = json.loads(output.getvalue())
        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"])
        self.assertIn("Calmanta Personal 草稿设置", payload["settings_panel"])
        self.assertEqual(75, payload["reply_worthiness_threshold"])
        self.assertIn("我的口吻模板：0 个", payload["settings_panel"])
        self.assertEqual("record_only", payload["risk_level_actions"]["no_risk"])

    def test_reply_worthiness_threshold_preview_and_save(self) -> None:
        before = self.profile_path.read_text(encoding="utf-8")
        preview = self.settings.preview_draft_settings({}, 82)
        self.assertEqual(82, preview["proposed_threshold"])
        self.assertEqual(before, self.profile_path.read_text(encoding="utf-8"))

        saved = self.settings.save_draft_settings({}, 82, "SAVE")
        self.assertTrue(saved["saved"])
        self.assertEqual(82, self.settings.reply_worthiness_threshold())
        with self.assertRaisesRegex(ValueError, "integer from 0 to 100"):
            self.settings.preview_draft_settings({}, 101)

    def test_saved_voice_template_appears_in_settings_panel(self) -> None:
        template = {
            "id": "template-1",
            "name": "朋友式回复",
            "when": ["ordinary_question"],
            "rules": ["基础口吻规则和安全规则始终优先。", "简短直接。"],
            "examples": ["可以，你具体想问哪一部分？"],
            "avoid_phrases": [],
            "enabled": True,
            "created_at": "2026-08-22T00:00:00Z",
            "updated_at": "2026-08-22T00:00:00Z",
        }
        preview = format_voice_template_preview(template)
        self.assertIn("口吻模板预览（尚未保存）", preview)
        self.settings.save_voice_template(template, "SAVE")
        panel = format_settings_panel(
            self.settings.risk_level_actions(),
            self.settings.voice_templates(),
        )
        self.assertIn("我的口吻模板：1 个", panel)
        self.assertIn("朋友式回复：提问（已启用）", panel)

    def test_cli_previews_then_saves_voice_template(self) -> None:
        input_path = self.root / "template.json"
        input_path.write_text(
            json.dumps(
                {
                    "name": "朋友式回复",
                    "scenario_ids": ["ordinary_question"],
                    "desired_style": "短一点，像朋友聊天。",
                    "examples": ["可以，你具体想问哪一部分？"],
                    "avoid_phrases": ["感谢您的宝贵意见"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        preview_output = io.StringIO()
        with redirect_stdout(preview_output):
            preview_exit = main([
                "--home", str(self.root), "settings", "template", "preview", "--input", str(input_path),
            ])
        preview = json.loads(preview_output.getvalue())
        self.assertEqual(0, preview_exit)
        self.assertIn("口吻模板预览（尚未保存）", preview["voice_template_panel"])

        save_output = io.StringIO()
        with redirect_stdout(save_output):
            save_exit = main([
                "--home", str(self.root), "settings", "template", "save", "--input", str(input_path),
                "--confirm", "SAVE",
            ])
        saved = json.loads(save_output.getvalue())
        self.assertEqual(0, save_exit)
        self.assertTrue(saved["saved"])
        self.assertEqual(1, len(self.settings.voice_templates()))

    def test_template_bindings_are_unique_and_can_be_removed(self) -> None:
        first = {
            "id": "template-1",
            "name": "直接澄清",
            "when": ["unverified_accusation"],
            "rules": ["基础口吻规则和安全规则始终优先。", "直接说重点。"],
            "examples": [],
            "avoid_phrases": [],
            "enabled": True,
            "created_at": "2026-08-22T00:00:00Z",
            "updated_at": "2026-08-22T00:00:00Z",
        }
        self.settings.save_voice_template(first, "SAVE")
        bound = self.settings.add_voice_template_bindings(
            "template-1",
            ["personal_attack"],
            "SAVE",
        )
        self.assertEqual(["unverified_accusation", "personal_attack"], bound["when"])
        unbound = self.settings.remove_voice_template_binding(
            "template-1",
            "personal_attack",
            "SAVE",
        )
        self.assertEqual(["unverified_accusation"], unbound["when"])
        duplicate = {**first, "id": "template-2", "name": "重复绑定"}
        with self.assertRaisesRegex(ValueError, "only one voice template"):
            self.settings.save_voice_template(duplicate, "SAVE")

    def test_incomplete_template_can_be_saved_as_a_draft_only(self) -> None:
        draft = {
            "id": "draft-1",
            "name": "未命名草稿",
            "when": [],
            "rules": ["基础口吻规则和安全规则始终优先。"],
            "examples": [],
            "avoid_phrases": [],
            "status": "draft",
            "enabled": False,
            "created_at": "2026-08-22T00:00:00Z",
            "updated_at": "2026-08-22T00:00:00Z",
        }
        self.settings.save_voice_template(draft, "SAVE_DRAFT")
        panel = format_settings_panel(
            self.settings.risk_level_actions(),
            self.settings.voice_templates(),
        )
        self.assertIn("未命名草稿：暂未选择评论类别（草稿）", panel)
        with self.assertRaisesRegex(ValueError, "SAVE_DRAFT"):
            self.settings.save_voice_template({**draft, "id": "draft-2"}, "SAVE")


if __name__ == "__main__":
    unittest.main()
