from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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
        self.workflow = PersonalWorkflow(
            self.store,
            self.core,
            project_root() / "config" / "profile.json",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_filter_ingest_and_deduplicate(self) -> None:
        observation = {
            "platform": "xiaohongshu",
            "item_type": "comment",
            "counterparty_display_name": "小明",
            "original_text": "这个方法新手也能用吗？",
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
        self.assertEqual("draft_pending_review", result["created"][0]["state"])
        self.assertEqual([], self.workflow.filter_new([observation]))

    def test_sensitive_topic_overrides_draft(self) -> None:
        result = self.workflow.ingest(
            [
                {
                    "platform": "instagram",
                    "item_type": "message",
                    "counterparty_display_name": "buyer",
                    "original_text": "我要退款，请马上处理。",
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
                    "original_text": "能再解释一下吗？",
                    "platform_item_id": "dm-201",
                    "assistant_decision": "draft",
                    "assistant_draft": "可以，你卡在哪一步？我按那一步展开说。",
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
                        "original_text": "hello",
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
                    "original_text": "分享一个简单的学习方法",
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


if __name__ == "__main__":
    unittest.main()
