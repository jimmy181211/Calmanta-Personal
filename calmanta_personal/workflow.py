from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from .core_bridge import CoreTools
from .store import LocalStore

ALLOWED_PLATFORMS = {"instagram", "xiaohongshu"}
ALLOWED_ITEM_TYPES = {"message", "comment", "post"}
ALLOWED_AI_DECISIONS = {"draft", "no_reply", "escalate", "block"}


class PersonalWorkflow:
    def __init__(self, store: LocalStore, core: CoreTools, profile_path: Path):
        self.store = store
        self.core = core
        self.profile_path = profile_path

    def filter_new(self, raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        new_items: list[dict[str, Any]] = []
        seen_in_batch: set[str] = set()
        for raw in raw_items:
            item = self._normalize(raw, include_decision=False)
            item["fingerprint"] = content_fingerprint(item)
            fingerprint = item["fingerprint"]
            if fingerprint in seen_in_batch or self.store.has_fingerprint(fingerprint):
                continue
            seen_in_batch.add(fingerprint)
            new_items.append(item)
        return new_items

    def ingest(self, raw_items: list[dict[str, Any]]) -> dict[str, Any]:
        created: list[dict[str, Any]] = []
        duplicates: list[dict[str, Any]] = []
        for raw in raw_items:
            normalized = self._normalize(raw, include_decision=True)
            normalized["fingerprint"] = content_fingerprint(normalized)
            item = self._decide(normalized)
            stored, was_created = self.store.create_item(item)
            (created if was_created else duplicates).append(stored)
        return {"created": created, "duplicates": duplicates}

    def validate_edited_draft(self, item: dict[str, Any], draft_text: str) -> None:
        cleaned = draft_text.strip()
        hard_limit = 3000 if item["item_type"] == "post" else self.max_reply_chars
        problems = self.core.validate_reply(cleaned, item["original_text"], hard_limit)
        if problems:
            raise ValueError("Draft failed Calmanta safety checks: " + ", ".join(problems))

    @property
    def max_reply_chars(self) -> int:
        profile = self._profile()
        return max(50, min(int(profile.get("max_reply_chars", 300)), 1000))

    def voice_profile(self) -> dict[str, Any]:
        raw = self._profile().get("voice_profile", {})
        if not isinstance(raw, dict):
            raise ValueError("config/profile.json voice_profile must be an object")
        return {
            "summary": str(raw.get("summary", ""))[:1000],
            "preferred_phrases": _string_list(raw.get("preferred_phrases"), 10, 500),
            "avoid_phrases": _string_list(raw.get("avoid_phrases"), 10, 500),
            "examples": _string_list(raw.get("examples"), 10, 500),
        }

    def _normalize(self, raw: dict[str, Any], include_decision: bool) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError("Every observed item must be a JSON object")
        self.core.reject_auth_material(raw)
        platform = str(raw.get("platform", "")).strip().lower()
        item_type = str(raw.get("item_type", "message")).strip().lower()
        if platform not in ALLOWED_PLATFORMS:
            raise ValueError(f"Unsupported Personal platform: {platform}")
        if item_type not in ALLOWED_ITEM_TYPES:
            raise ValueError(f"Unsupported item_type: {item_type}")
        original_text = str(raw.get("original_text", "")).strip()
        if not original_text:
            raise ValueError("original_text is required")
        if len(original_text) > 10_000:
            raise ValueError("original_text exceeds 10000 characters")
        counterparty = str(raw.get("counterparty_display_name", "")).strip()[:200]
        if item_type != "post" and not counterparty:
            raise ValueError("counterparty_display_name is required")
        item = {
            "platform": platform,
            "item_type": item_type,
            "counterparty_key": str(raw.get("counterparty_key", "")).strip()[:300],
            "counterparty_display_name": counterparty,
            "original_text": original_text,
            "platform_item_id": str(raw.get("platform_item_id", "")).strip()[:300],
            "source_url": str(raw.get("source_url", "")).strip()[:2000],
            "observed_at": str(raw.get("observed_at", "")).strip()[:100],
        }
        if include_decision:
            decision = str(raw.get("assistant_decision", "")).strip().lower()
            if decision not in ALLOWED_AI_DECISIONS:
                raise ValueError(
                    "assistant_decision must be draft, no_reply, escalate, or block"
                )
            item.update(
                {
                    "assistant_decision": decision,
                    "assistant_draft": str(raw.get("assistant_draft", "")).strip(),
                    "assistant_rationale": str(raw.get("assistant_rationale", "")).strip()[:1000],
                    "preview_payload": raw.get("preview_payload", {}),
                }
            )
        return item

    def _decide(self, observation: dict[str, Any]) -> dict[str, Any]:
        text = observation["original_text"]
        item_type = observation["item_type"]
        sensitive_tags = self.core.sensitive_tags(text)
        analysis = self.core.enforce_analysis_safety(text, self.core.classify_comment(text))
        decision = observation["assistant_decision"]
        rationale = observation.get("assistant_rationale", "")
        draft_text = ""
        risk_level = str(analysis.risk_level)

        if "threat" in analysis.safety_flags or "privacy" in analysis.safety_flags:
            state = "hard_blocked"
            final_decision = "record_and_escalate"
            rationale = "Calmanta detected a threat or privacy risk; no reply draft is allowed."
        elif sensitive_tags:
            state = "user_handling_required"
            final_decision = "escalate_to_user"
            risk_level = "medium" if risk_level == "low" else risk_level
            rationale = (
                "Sensitive topic detected: complaint, refund, price, collaboration, or contract."
            )
        elif item_type != "post" and (
            decision == "no_reply" or self.core.no_reply_recommended(text)
        ):
            state = "no_reply_recommended"
            final_decision = "no_reply_recommended"
            rationale = rationale or "No useful reply is needed."
        elif decision in {"escalate", "block"}:
            state = "hard_blocked" if decision == "block" else "user_handling_required"
            final_decision = "record_and_escalate" if decision == "block" else "escalate_to_user"
            rationale = rationale or "ChatGPT marked this item for the user to handle."
        else:
            draft_text = observation["assistant_draft"].strip()
            hard_limit = 3000 if item_type == "post" else self.max_reply_chars
            problems = self.core.validate_reply(draft_text, text, hard_limit)
            if problems:
                raise ValueError("Draft failed Calmanta safety checks: " + ", ".join(problems))
            state = "preview_pending_review" if item_type == "post" else "draft_pending_review"
            final_decision = "preview_for_review" if item_type == "post" else "draft_for_review"
            rationale = rationale or "ChatGPT prepared a draft for explicit user approval."

        timestamp = self.core.utc_now()
        preview_payload = observation.get("preview_payload", {})
        if not isinstance(preview_payload, dict):
            raise ValueError("preview_payload must be an object")
        if item_type == "post" and draft_text:
            preview_payload = {
                "destination": str(
                    preview_payload.get("destination", observation["platform"])
                )[:200],
                "audience": str(preview_payload.get("audience", "confirm in platform"))[:200],
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
            "counterparty_display_name": observation["counterparty_display_name"],
            "original_text": text,
            "platform_item_id": observation["platform_item_id"],
            "source_url": observation["source_url"],
            "observed_at": observation["observed_at"],
            "decision": final_decision,
            "state": state,
            "sensitive_tags": sensitive_tags,
            "risk_level": risk_level,
            "rationale": rationale,
            "voice_profile": self.voice_profile(),
            "draft_text": draft_text,
            "preview_payload": preview_payload,
            "created_at": timestamp,
            "updated_at": timestamp,
            "approved_at": "",
        }

    def _profile(self) -> dict[str, Any]:
        if not self.profile_path.is_file():
            raise ValueError(f"Profile configuration not found: {self.profile_path}")
        raw = json.loads(self.profile_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("config/profile.json must contain a JSON object")
        return raw


def content_fingerprint(item: dict[str, Any]) -> str:
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
            "counterparty_display_name": item.get("counterparty_display_name", ""),
            "original_text": item["original_text"],
            "source_url": item.get("source_url", ""),
        }
    encoded = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def approval_fingerprint(item: dict[str, Any]) -> str:
    source = {
        "work_item_id": item["work_item_id"],
        "platform": item["platform"],
        "item_type": item["item_type"],
        "draft_text": item["draft_text"],
        "preview_payload": item["preview_payload"],
    }
    encoded = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _string_list(value: Any, limit: int, item_limit: int) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("Voice profile list fields must be arrays")
    return [str(item)[:item_limit] for item in value[:limit]]
