"""Turn sanitized observations into local, approval-first review records."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from .core_bridge import CoreTools
from .profile_settings import RISK_LEVELS, ProfileSettings
from .store import LocalStore

ALLOWED_PLATFORMS = {"instagram", "xiaohongshu"}
ALLOWED_ITEM_TYPES = {"message", "comment", "post"}
ALLOWED_AI_DECISIONS = {"draft", "no_reply", "escalate", "block"}
ALLOWED_REPLY_WORTHINESS_SIGNALS = {
    "clear_question",
    "factual_correction",
    "constructive_disagreement",
    "meaningful_engagement",
    "simple_acknowledgement",
    "emoji_only",
    "spam",
    "unclear",
}
ALLOWED_CONVERSATION_RELATIONS = {
    "direct_message",
    "top_level_comment",
    "reply_to_owner",
}


class PersonalWorkflow:
    def __init__(self, store: LocalStore, core: CoreTools, profile_path: Path):
        self.store = store
        self.core = core
        self.profile_path = profile_path

    def filter_new(
        self, raw_items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Normalize observations and remove duplicates from this batch and
        local history.
        """
        new_items: list[dict[str, Any]] = []
        seen_in_batch: set[str] = set()
        for raw in raw_items:
            item = self._normalize(raw, include_decision=False)
            item["fingerprint"] = content_fingerprint(item)
            fingerprint = item["fingerprint"]
            if fingerprint in seen_in_batch or self.store.has_fingerprint(
                fingerprint
            ):
                continue
            seen_in_batch.add(fingerprint)
            new_items.append(item)
        return new_items

    def ingest(self, raw_items: list[dict[str, Any]]) -> dict[str, Any]:
        """Apply draft policy and persist each new observation with its
        decision.
        """
        created: list[dict[str, Any]] = []
        duplicates: list[dict[str, Any]] = []
        for raw in raw_items:
            normalized = self._normalize(raw, include_decision=True)
            normalized["fingerprint"] = content_fingerprint(normalized)
            item = self._decide(normalized)
            stored, was_created = self.store.create_item(item)
            (created if was_created else duplicates).append(stored)
        return {"created": created, "duplicates": duplicates}

    def validate_edited_draft(
        self, item: dict[str, Any], draft_text: str
    ) -> None:
        """Check the replacement text against the source and the item's
        length limit.
        """
        cleaned = draft_text.strip()
        hard_limit = (
            3000 if item["item_type"] == "post" else self.max_reply_chars
        )
        source_text = (
            item["user_intent_text"]
            if item["item_type"] == "post"
            else item["counterparty_text"]
        )
        problems = self.core.validate_reply(cleaned, source_text, hard_limit)
        if problems:
            raise ValueError(
                "Draft failed Calmanta safety checks: " + ", ".join(problems)
            )

    @property
    def max_reply_chars(self) -> int:
        profile = self._profile()
        return max(50, min(int(profile.get("max_reply_chars", 300)), 1000))

    def voice_profile(self) -> dict[str, Any]:
        raw = self._profile().get("voice_profile", {})
        return self.core.normalize_voice_profile(raw)

    def risk_level_actions(self) -> dict[str, str]:
        return ProfileSettings(self.profile_path).risk_level_actions()

    def reply_worthiness_threshold(self) -> int:
        return ProfileSettings(self.profile_path).reply_worthiness_threshold()

    def _normalize(
        self, raw: dict[str, Any], include_decision: bool
    ) -> dict[str, Any]:
        """Validate observation fields before they enter the decision
        workflow.
        """
        if not isinstance(raw, dict):
            raise ValueError("Every observed item must be a JSON object")
        self.core.reject_auth_material(raw)
        platform = str(raw.get("platform", "")).strip().lower()
        item_type = str(raw.get("item_type", "message")).strip().lower()
        if platform not in ALLOWED_PLATFORMS:
            raise ValueError(f"Unsupported Personal platform: {platform}")
        if item_type not in ALLOWED_ITEM_TYPES:
            raise ValueError(f"Unsupported item_type: {item_type}")
        counterparty = str(raw.get("counterparty_display_name", "")).strip()[
            :200
        ]
        if item_type != "post" and not counterparty:
            raise ValueError("counterparty_display_name is required")
        counterparty_text = ""
        owner_context_text = ""
        conversation_relation = "not_applicable"
        direction_verified = item_type == "post"
        role_resolution_source = "not_applicable" if item_type == "post" else ""
        user_intent_text = ""
        if item_type == "post":
            user_intent_text = str(raw.get("user_intent_text", "")).strip()
            if not user_intent_text:
                raise ValueError("user_intent_text is required for posts")
            if len(user_intent_text) > 10_000:
                raise ValueError("user_intent_text exceeds 10000 characters")
        else:
            counterparty_text = str(raw.get("counterparty_text", "")).strip()
            if not counterparty_text:
                raise ValueError(
                    (
                        "counterparty_text is required and must contain "
                        "only the other person's content"
                    )
                )
            if len(counterparty_text) > 10_000:
                raise ValueError("counterparty_text exceeds 10000 characters")
            owner_context_text = str(raw.get("owner_context_text", "")).strip()
            if len(owner_context_text) > 10_000:
                raise ValueError("owner_context_text exceeds 10000 characters")
            conversation_relation = str(
                raw.get("conversation_relation", "")
            ).strip()
            if conversation_relation not in ALLOWED_CONVERSATION_RELATIONS:
                raise ValueError(
                    (
                        "conversation_relation "
                        "must identify a verified "
                        "inbound item"
                    )
                )
            direction_verified = raw.get("direction_verified") is True
            if not direction_verified:
                raise ValueError(
                    (
                        "direction_verified must be "
                        "true before a draft can be "
                        "created"
                    )
                )
            role_resolution_source = str(
                raw.get("role_resolution_source", "")
            ).strip()[:100]
            if not role_resolution_source:
                raise ValueError(
                    (
                        "role_resolution_source is "
                        "required for messages and "
                        "comments"
                    )
                )
            if (
                conversation_relation == "reply_to_owner"
                and not owner_context_text
            ):
                raise ValueError(
                    (
                        "owner_context_text is required when the other person "
                        "replies to the owner"
                    )
                )
        item = {
            "platform": platform,
            "item_type": item_type,
            "counterparty_key": str(raw.get("counterparty_key", "")).strip()[
                :300
            ],
            "counterparty_display_name": counterparty,
            "counterparty_text": counterparty_text,
            "owner_context_text": owner_context_text,
            "conversation_relation": conversation_relation,
            "direction_verified": direction_verified,
            "role_resolution_source": role_resolution_source,
            "user_intent_text": user_intent_text,
            "platform_item_id": str(raw.get("platform_item_id", "")).strip()[
                :300
            ],
            "source_url": str(raw.get("source_url", "")).strip()[:2000],
            "observed_at": str(raw.get("observed_at", "")).strip()[:100],
        }
        if include_decision:
            decision = str(raw.get("assistant_decision", "")).strip().lower()
            if decision not in ALLOWED_AI_DECISIONS:
                raise ValueError(
                    (
                        "assistant_decision must be "
                        "draft, no_reply, escalate, "
                        "or block"
                    )
                )
            item.update(
                {
                    "assistant_decision": decision,
                    "assistant_category": str(
                        raw.get("assistant_category", "")
                    ).strip()[:100],
                    "assistant_risk_level": str(
                        raw.get("assistant_risk_level", "")
                    ).strip(),
                    "assistant_draft": str(
                        raw.get("assistant_draft", "")
                    ).strip(),
                    "assistant_rationale": str(
                        raw.get("assistant_rationale", "")
                    ).strip()[:1000],
                    "preview_payload": raw.get("preview_payload", {}),
                }
            )
            score = raw.get("assistant_reply_worthiness_score")
            worthiness_valid = True
            if score is not None and (
                isinstance(score, bool)
                or not isinstance(score, int)
                or score < 0
                or score > 100
            ):
                score = None
                worthiness_valid = False
            signals = raw.get("assistant_reply_worthiness_signals", [])
            if not isinstance(signals, list):
                signals = []
                worthiness_valid = False
            clean_signals = [str(value).strip() for value in signals[:3]]
            if any(
                value not in ALLOWED_REPLY_WORTHINESS_SIGNALS
                for value in clean_signals
            ):
                clean_signals = []
                worthiness_valid = False
            item["assistant_reply_worthiness_score"] = score
            item["assistant_reply_worthiness_reason"] = str(
                raw.get("assistant_reply_worthiness_reason", "")
            ).strip()[:300]
            item["assistant_reply_worthiness_signals"] = clean_signals
            item["assistant_reply_worthiness_valid"] = worthiness_valid
            category = item["assistant_category"]
            model_risk = item["assistant_risk_level"]
            if bool(category) != bool(model_risk):
                raise ValueError(
                    (
                        "assistant_category and assistant_risk_level must "
                        "be provided together"
                    )
                )
            if model_risk and model_risk not in RISK_LEVELS:
                raise ValueError(
                    (
                        "assistant_risk_level must "
                        "be no_risk, low, medium, "
                        "or high"
                    )
                )
        return item

    def _decide(self, observation: dict[str, Any]) -> dict[str, Any]:
        """Apply mandatory safety rules before the user's drafting policy and
        threshold.
        """
        item_type = observation["item_type"]
        text = (
            observation["user_intent_text"]
            if item_type == "post"
            else observation["counterparty_text"]
        )
        sensitive_tags = self.core.sensitive_tags(text)
        if observation.get("assistant_category"):
            model_analysis = self.core.analysis_factory(
                observation["assistant_category"],
                observation["assistant_risk_level"],
                observation.get("assistant_rationale", "")
                or "模型已完成初步分类。",
                "按风险等级设置处理",
            )
        else:
            model_analysis = self.core.classify_comment(text)
        analysis = self.core.enforce_analysis_safety(text, model_analysis)
        decision = observation["assistant_decision"]
        rationale = observation.get("assistant_rationale", "")
        draft_text = ""
        risk_level = str(analysis.risk_level)
        reply_worthiness_score = 0
        reply_worthiness_reason = "此内容不需要进行回复价值判断。"
        reply_worthiness_signals: list[str] = []

        if (
            "threat" in analysis.safety_flags
            or "privacy" in analysis.safety_flags
        ):
            state = "hard_blocked"
            final_decision = "record_and_escalate"
            rationale = (
                "Calmanta detected a threat or privacy risk; no reply "
                "draft is allowed."
            )
        elif sensitive_tags:
            state = "user_handling_required"
            final_decision = "escalate_to_user"
            risk_level = "medium" if risk_level == "low" else risk_level
            rationale = (
                "Sensitive topic detected: complaint, refund, price, "
                "collaboration, or contract."
            )
        elif decision in {"escalate", "block"}:
            state = (
                "hard_blocked"
                if decision == "block"
                else "user_handling_required"
            )
            final_decision = (
                "record_and_escalate"
                if decision == "block"
                else "escalate_to_user"
            )
            rationale = (
                rationale or "ChatGPT marked this item for the user to handle."
            )
        elif (
            item_type != "post"
            and self.risk_level_actions()[risk_level] == "record_only"
        ):
            state = "record_only"
            final_decision = "record_only"
            rationale = (
                "User configured "
                f"{risk_level}"
                " items as record-only; no reply draft was created."
            )
        elif item_type != "post":
            worthiness_available = True
            fixed = _fixed_reply_worthiness(
                text, self.core.no_reply_recommended(text)
            )
            if fixed is not None:
                (
                    reply_worthiness_score,
                    reply_worthiness_reason,
                    reply_worthiness_signals,
                ) = fixed
            else:
                supplied_score = observation.get(
                    "assistant_reply_worthiness_score"
                )
                supplied_reason = observation.get(
                    "assistant_reply_worthiness_reason", ""
                )
                if (
                    not observation.get(
                        "assistant_reply_worthiness_valid", True
                    )
                    or supplied_score is None
                    or not supplied_reason
                ):
                    worthiness_available = False
                    state = "record_only"
                    final_decision = "worthiness_unavailable"
                    reply_worthiness_reason = (
                        "无法确认回复价值，已保守地只保存记录。"
                    )
                    reply_worthiness_signals = ["unclear"]
                    rationale = reply_worthiness_reason
                else:
                    reply_worthiness_score = int(supplied_score)
                    reply_worthiness_reason = str(supplied_reason)
                    reply_worthiness_signals = list(
                        observation.get(
                            "assistant_reply_worthiness_signals", []
                        )
                    )
            if worthiness_available:
                if (
                    decision == "no_reply"
                    or reply_worthiness_score
                    < self.reply_worthiness_threshold()
                ):
                    state = "record_only"
                    final_decision = "no_reply_recommended"
                    rationale = reply_worthiness_reason
                else:
                    draft_text = observation["assistant_draft"].strip()
                    problems = self.core.validate_reply(
                        draft_text, text, self.max_reply_chars
                    )
                    if problems:
                        raise ValueError(
                            "Draft failed Calmanta safety checks: "
                            + ", ".join(problems)
                        )
                    state = "draft_pending_review"
                    final_decision = "draft_for_review"
                    rationale = rationale or "草稿已生成，等待你确认。"
        else:
            draft_text = observation["assistant_draft"].strip()
            hard_limit = 3000 if item_type == "post" else self.max_reply_chars
            problems = self.core.validate_reply(draft_text, text, hard_limit)
            if problems:
                raise ValueError(
                    "Draft failed Calmanta safety checks: "
                    + ", ".join(problems)
                )
            state = (
                "preview_pending_review"
                if item_type == "post"
                else "draft_pending_review"
            )
            final_decision = (
                "preview_for_review"
                if item_type == "post"
                else "draft_for_review"
            )
            rationale = (
                rationale
                or "ChatGPT prepared a draft for explicit user approval."
            )

        timestamp = self.core.utc_now()
        preview_payload = observation.get("preview_payload", {})
        if not isinstance(preview_payload, dict):
            raise ValueError("preview_payload must be an object")
        if item_type == "post" and draft_text:
            preview_payload = {
                "destination": str(
                    preview_payload.get("destination", observation["platform"])
                )[:200],
                "audience": str(
                    preview_payload.get("audience", "confirm in platform")
                )[:200],
                "caption": draft_text,
                "media": list(preview_payload.get("media", []))[:20],
                "publish_status": "preview_only",
            }
        return {
            "work_item_id": str(uuid4()),
            "fingerprint": observation["fingerprint"],
            "platform": observation["platform"],
            "item_type": item_type,
            "counterparty_key": observation["counterparty_key"],
            "counterparty_display_name": observation[
                "counterparty_display_name"
            ],
            "counterparty_text": observation["counterparty_text"],
            "owner_context_text": observation["owner_context_text"],
            "conversation_relation": observation["conversation_relation"],
            "direction_verified": observation["direction_verified"],
            "role_resolution_source": observation["role_resolution_source"],
            "user_intent_text": observation["user_intent_text"],
            "platform_item_id": observation["platform_item_id"],
            "source_url": observation["source_url"],
            "observed_at": observation["observed_at"],
            "decision": final_decision,
            "state": state,
            "sensitive_tags": sensitive_tags,
            "category": analysis.category,
            "risk_level": risk_level,
            "rationale": rationale,
            "reply_worthiness_score": reply_worthiness_score,
            "reply_worthiness_reason": reply_worthiness_reason,
            "reply_worthiness_signals": reply_worthiness_signals,
            "voice_profile": self.voice_profile(),
            "draft_text": draft_text,
            "preview_payload": preview_payload,
            "created_at": timestamp,
            "updated_at": timestamp,
            "approved_at": "",
        }

    def _profile(self) -> dict[str, Any]:
        if not self.profile_path.is_file():
            raise ValueError(
                f"Profile configuration not found: {self.profile_path}"
            )
        raw = json.loads(self.profile_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Personal profile must contain a JSON object")
        return raw


def content_fingerprint(item: dict[str, Any]) -> str:
    """Identify the same observed content independently of later draft edits."""
    stable_id = str(item.get("platform_item_id", "")).strip()
    if stable_id:
        source = {
            "platform": item["platform"],
            "item_type": item["item_type"],
            "platform_item_id": stable_id,
        }
    else:
        source = {
            "platform": item["platform"],
            "item_type": item["item_type"],
            "counterparty_key": item.get("counterparty_key", ""),
            "counterparty_display_name": item.get(
                "counterparty_display_name", ""
            ),
            "counterparty_text": item.get("counterparty_text", ""),
            "owner_context_text": item.get("owner_context_text", ""),
            "conversation_relation": item.get("conversation_relation", ""),
            "source_url": item.get("source_url", ""),
        }
    encoded = json.dumps(
        source, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def approval_fingerprint(item: dict[str, Any]) -> str:
    """Bind approval to the exact action and draft that the user reviewed."""
    source = {
        "work_item_id": item["work_item_id"],
        "platform": item["platform"],
        "item_type": item["item_type"],
        "counterparty_text": item.get("counterparty_text", ""),
        "owner_context_text": item.get("owner_context_text", ""),
        "conversation_relation": item.get("conversation_relation", ""),
        "direction_verified": item.get("direction_verified", False),
        "user_intent_text": item.get("user_intent_text", ""),
        "draft_text": item["draft_text"],
        "preview_payload": item["preview_payload"],
    }
    encoded = json.dumps(
        source, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _fixed_reply_worthiness(
    text: str,
    no_reply_recommended: bool,
) -> tuple[int, str, list[str]] | None:
    """Return a deterministic no-reply assessment for unambiguous low-value
    text.
    """
    cleaned = text.strip()
    if not no_reply_recommended:
        return None
    if any(
        token in cleaned.lower()
        for token in (
            "加微信",
            "刷粉",
            "代运营",
            "兼职日结",
            "点击链接",
            "免费领取",
            "investment opportunity",
        )
    ):
        return 0, "内容像垃圾信息，不建议回复。", ["spam"]
    signal = (
        "emoji_only"
        if cleaned and not any(character.isalnum() for character in cleaned)
        else "simple_acknowledgement"
    )
    return 0, "只是简单确认或表情，不需要回复。", [signal]
