from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from calmanta_personal.cli import _format_review_card
from calmanta_personal.core_bridge import load_core, project_root
from calmanta_personal.object_store import LocalObjectStore
from calmanta_personal.store import LocalStore
from calmanta_personal.workflow import PersonalWorkflow, approval_fingerprint


class PersonalWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = LocalStore(self.root / "data" / "personal.db")
        self.store.initialize()
        self.core = load_core()
        self.assertEqual("Calmanta-Core", self.core.root.name)
        self.workflow = PersonalWorkflow(
            self.store,
            self.core,
            project_root() / "config" / "profile.example.json",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_filter_ingest_and_deduplicate(self) -> None:
        observation = {
            "platform": "xiaohongshu",
            "item_type": "comment",
            "counterparty_display_name": "小明",
            "counterparty_text": "这个方法新手也能用吗？",
            "conversation_relation": "top_level_comment",
            "direction_verified": True,
            "role_resolution_source": "visible_page_roles",
            "platform_item_id": "comment-100",
        }
        filtered = self.workflow.filter_new([observation, observation])
        self.assertEqual(1, len(filtered))
        filtered[0].update(
            {
                "assistant_decision": "draft",
                "assistant_draft": (
                    "可以的，建议先从最简单的一步开始，遇到具体问题再告诉我。"
                ),
                "assistant_rationale": "对方提出了具体问题，值得简短回复。",
            }
        )
        result = self.workflow.ingest(filtered)
        self.assertEqual(1, len(result["created"]))
        self.assertEqual("record_only", result["created"][0]["state"])
        self.assertEqual("提问", result["created"][0]["category"])
        self.assertEqual("no_risk", result["created"][0]["risk_level"])
        self.assertEqual([], self.workflow.filter_new([observation]))

    def test_sensitive_topic_overrides_draft(self) -> None:
        result = self.workflow.ingest(
            [
                {
                    "platform": "instagram",
                    "item_type": "message",
                    "counterparty_display_name": "buyer",
                    "counterparty_text": "我要退款，请马上处理。",
                    "conversation_relation": "direct_message",
                    "direction_verified": True,
                    "role_resolution_source": "visible_thread_roles",
                    "platform_item_id": "dm-200",
                    "assistant_decision": "draft",
                    "assistant_draft": "我来处理。",
                }
            ]
        )
        item = result["created"][0]
        self.assertEqual("user_handling_required", item["state"])
        self.assertEqual("", item["draft_text"])
        self.assertIn("refund", item["sensitive_tags"])

    def test_approval_is_recorded_but_never_sent(self) -> None:
        result = self.workflow.ingest(
            [
                {
                    "platform": "instagram",
                    "item_type": "message",
                    "counterparty_display_name": "reader",
                    "counterparty_text": "你就是垃圾。",
                    "conversation_relation": "direct_message",
                    "direction_verified": True,
                    "role_resolution_source": "visible_thread_roles",
                    "platform_item_id": "dm-201",
                    "assistant_decision": "draft",
                    "assistant_draft": "请保持理性交流；如果有具体问题，可以基于事实说明。",
                }
            ]
        )
        item = result["created"][0]
        approved = self.store.approve(
            item["work_item_id"],
            "approval-test",
            approval_fingerprint(item),
            self.core.utc_now(),
        )
        self.assertEqual("approved", approved["state"])
        self.assertNotIn("sent", approved)
        completed = self.store.complete(item["work_item_id"], self.core.utc_now())
        self.assertEqual("completed", completed["state"])

    def test_auth_material_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.workflow.filter_new(
                [
                    {
                        "platform": "instagram",
                        "item_type": "message",
                        "counterparty_display_name": "reader",
                        "counterparty_text": "hello",
                        "conversation_relation": "direct_message",
                        "direction_verified": True,
                        "role_resolution_source": "visible_thread_roles",
                        "cookie": "forbidden",
                    }
                ]
            )

    def test_local_object_store_deduplicates_by_hash(self) -> None:
        source = self.root / "note.txt"
        source.write_text("evidence", encoding="utf-8")
        objects = LocalObjectStore(self.root / "data" / "objects", self.store)
        first = objects.put_file(source, self.core.utc_now())
        second = objects.put_file(source, self.core.utc_now())
        self.assertEqual(first["object_key"], second["object_key"])
        self.assertTrue((self.root / "data" / "objects" / first["object_key"]).is_file())

    def test_editing_post_keeps_preview_caption_in_sync(self) -> None:
        result = self.workflow.ingest(
            [
                {
                    "platform": "instagram",
                    "item_type": "post",
                    "user_intent_text": "分享一个简单的学习方法",
                    "platform_item_id": "post-draft-1",
                    "assistant_decision": "draft",
                    "assistant_draft": "先从十分钟开始。",
                }
            ]
        )
        item = result["created"][0]
        updated = self.store.update_draft(
            item["work_item_id"],
            "先从每天十分钟开始，能坚持比一次做很多更重要。",
            "preview_pending_review",
            "user_authored_for_review",
            self.core.utc_now(),
        )
        self.assertEqual(updated["draft_text"], updated["preview_payload"]["caption"])

    def test_reply_to_owner_keeps_owner_content_out_of_counterparty_text(self) -> None:
        result = self.workflow.ingest(
            [
                {
                    "platform": "xiaohongshu",
                    "item_type": "comment",
                    "counterparty_display_name": "咏琳",
                    "counterparty_text": "北京长大的孩子，不是海外华人。",
                    "owner_context_text": "只能说赛道不同吧，你要麻省的来高考他也不会啊，又看不懂中文。",
                    "conversation_relation": "reply_to_owner",
                    "direction_verified": True,
                    "role_resolution_source": "visible_notification_roles",
                    "platform_item_id": "reply-roles-1",
                    "assistant_decision": "draft",
                    "assistant_draft": "明白了，是我把成长背景搞错了，谢谢你指出。",
                }
            ]
        )
        item = result["created"][0]
        self.assertEqual(item["counterparty_text"], "北京长大的孩子，不是海外华人。")
        self.assertEqual(
            item["owner_context_text"],
            "只能说赛道不同吧，你要麻省的来高考他也不会啊，又看不懂中文。",
        )
        self.assertEqual(item["conversation_relation"], "reply_to_owner")
        self.assertTrue(item["direction_verified"])

    def test_review_card_always_places_draft_before_message_metadata(self) -> None:
        card = _format_review_card(
            {
                "work_item_id": "review-order-1",
                "draft_text": "明白了，谢谢你指出。",
                "platform": "xiaohongshu",
                "item_type": "comment",
                "counterparty_display_name": "咏琳",
                "counterparty_text": "北京长大的孩子，不是海外华人。",
                "owner_context_text": "只能说赛道不同吧。",
                "conversation_relation": "reply_to_owner",
                "risk_level": "low",
                "category": "事实纠正",
                "rationale": "对方在纠正事实。",
            }
        )
        self.assertTrue(card.startswith("拟回复（尚未发送）：明白了，谢谢你指出。"))
        self.assertLess(card.index("平台："), card.index("对方发给我的内容（原消息）："))
        self.assertLess(card.index("对方发给我的内容（原消息）："), card.index("风险等级："))
        self.assertLess(card.index("风险等级："), card.index("建议回复原因："))
        self.assertIn("风险等级：低风险 / 评论类别：事实纠正", card)
        self.assertLess(card.index("建议回复原因："), card.index("请选择："))
        self.assertLess(card.index("请选择："), card.index("<details>"))
        self.assertIn("编辑回复 / 同意并发送 / 拒绝且不回复 / 拒绝并重新生成", card)
        self.assertLess(card.index("<details>"), card.index("对话关系："))
        self.assertLess(card.index("对话关系："), card.index("我的被回复内容（仅供上下文）："))

    def test_personal_uses_shared_human_voice_guide(self) -> None:
        profile = self.workflow.voice_profile()
        self.assertEqual("2026-08-22", profile["guide_version"])
        self.assertIn("感谢您的宝贵意见", profile["avoid_phrases"])
        scenario_ids = {scenario["id"] for scenario in profile["scenarios"]}
        self.assertIn("factual_correction", scenario_ids)
        self.assertIn("对，北京长大的确实不算海外华人，我前面说岔了。", profile["examples"])

    def test_inbound_items_require_verified_roles(self) -> None:
        with self.assertRaisesRegex(ValueError, "counterparty_text"):
            self.workflow.filter_new(
                [{
                    "platform": "instagram",
                    "item_type": "message",
                    "counterparty_display_name": "reader",
                    "conversation_relation": "direct_message",
                    "direction_verified": True,
                    "role_resolution_source": "visible_thread_roles",
                }]
            )

    def test_legacy_database_rows_remain_unverified_after_role_migration(self) -> None:
        legacy_path = self.root / "data" / "legacy.db"
        with sqlite3.connect(legacy_path) as connection:
            connection.executescript(
                """
                CREATE TABLE work_items (
                    work_item_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    platform TEXT NOT NULL,
                    item_type TEXT NOT NULL,
                    counterparty_key TEXT NOT NULL DEFAULT '',
                    counterparty_display_name TEXT NOT NULL DEFAULT '',
                    original_text TEXT NOT NULL,
                    platform_item_id TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    observed_at TEXT NOT NULL DEFAULT '',
                    decision TEXT NOT NULL,
                    state TEXT NOT NULL,
                    sensitive_tags_json TEXT NOT NULL DEFAULT '[]',
                    risk_level TEXT NOT NULL DEFAULT 'low',
                    rationale TEXT NOT NULL DEFAULT '',
                    voice_profile_json TEXT NOT NULL DEFAULT '{}',
                    draft_text TEXT NOT NULL DEFAULT '',
                    preview_payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    approved_at TEXT NOT NULL DEFAULT ''
                );
                INSERT INTO work_items (
                    work_item_id, fingerprint, platform, item_type,
                    counterparty_display_name, original_text, decision, state,
                    created_at, updated_at
                ) VALUES (
                    'legacy-1', 'legacy-fingerprint', 'xiaohongshu', 'comment',
                    '旧用户', '旧记录的模糊原文', 'draft_for_review', 'draft_pending_review',
                    '2026-08-22T00:00:00Z', '2026-08-22T00:00:00Z'
                );
                """
            )
        connection.close()
        migrated = LocalStore(legacy_path)
        migrated.initialize()
        item = migrated.get_item("legacy-1")
        if item is None:
            self.fail("Migrated work item should exist")
        self.assertEqual(item["counterparty_text"], "旧记录的模糊原文")
        self.assertEqual(item["conversation_relation"], "unknown")
        self.assertFalse(item["direction_verified"])
        self.assertEqual(item["role_resolution_source"], "legacy_unverified")
        with sqlite3.connect(legacy_path) as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("PRAGMA journal_mode = DELETE")
        connection.close()
        with self.assertRaisesRegex(ValueError, "direction_verified"):
            self.workflow.filter_new(
                [{
                    "platform": "instagram",
                    "item_type": "message",
                    "counterparty_display_name": "reader",
                    "counterparty_text": "hello",
                    "conversation_relation": "direct_message",
                    "role_resolution_source": "visible_thread_roles",
                }]
            )


if __name__ == "__main__":
    unittest.main()
