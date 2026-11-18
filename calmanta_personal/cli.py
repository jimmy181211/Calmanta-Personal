"""Execute local commands through the store and approval workflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from .cli_parser import (
    _parser,
)
from .core_bridge import load_core, project_root
from .object_store import LocalObjectStore
from .profile_settings import (
    ProfileSettings,
    ensure_local_profile,
    format_settings_panel,
    format_voice_template_preview,
    parse_risk_changes,
)
from .store import LocalStore
from .workflow import PersonalWorkflow, approval_fingerprint


def main(argv: list[str] | None = None) -> int:
    _use_utf8_output(sys.stdout)
    _use_utf8_output(sys.stderr)
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = _run(args)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(
            json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {"ok": True, **result}, ensure_ascii=False, separators=(",", ":")
        )
    )
    return 0


def _use_utf8_output(stream: Any) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")


def _run(args: argparse.Namespace) -> dict[str, Any]:
    """Dispatch the parsed command through the local store and approval
    workflow.
    """
    home = (
        Path(args.home).expanduser().resolve() if args.home else project_root()
    )
    profile_path = ensure_local_profile(home)
    if args.command == "settings":
        settings = ProfileSettings(profile_path)
        if args.settings_command == "show":
            actions = settings.risk_level_actions()
            threshold = settings.reply_worthiness_threshold()
            templates = settings.voice_templates()
            return {
                "settings_panel": format_settings_panel(
                    actions, templates, threshold=threshold
                ),
                "risk_level_actions": actions,
                "reply_worthiness_threshold": threshold,
                "voice_templates": templates,
                "saved": True,
            }
        if args.settings_command == "template":
            if args.template_command == "list":
                templates = settings.voice_templates()
                return {"voice_templates": templates, "count": len(templates)}
            if args.template_command == "delete":
                settings.delete_voice_template(args.template_id, args.confirm)
                actions = settings.risk_level_actions()
                templates = settings.voice_templates()
                return {
                    "deleted": True,
                    "voice_templates": templates,
                    "settings_panel": format_settings_panel(
                        actions,
                        templates,
                        threshold=settings.reply_worthiness_threshold(),
                    ),
                }
            if args.template_command == "bind":
                template = settings.add_voice_template_bindings(
                    args.template_id,
                    args.scenario_ids,
                    args.confirm,
                )
                return {"voice_template": template, "saved": True}
            if args.template_command == "unbind":
                template = settings.remove_voice_template_binding(
                    args.template_id,
                    args.scenario_id,
                    args.confirm,
                )
                return {"voice_template": template, "saved": True}
            if args.template_command in {"enable", "disable"}:
                template = settings.set_voice_template_enabled(
                    args.template_id,
                    args.template_command == "enable",
                    args.confirm,
                )
                return {"voice_template": template, "saved": True}
            core = load_core()
            raw_template = _read_object(Path(args.input))
            if args.template_command == "save-draft":
                raw_template["status"] = "draft"
            if (
                args.template_command == "update"
                and "status" not in raw_template
            ):
                existing = settings.get_voice_template(args.template_id)
                raw_template["status"] = existing.get(
                    "status",
                    "enabled" if existing.get("enabled", True) else "disabled",
                )
            template = core.prepare_voice_template(
                raw_template,
                template_id=(
                    "preview-only"
                    if args.template_command == "preview"
                    else args.template_id
                    if args.template_command == "update"
                    else str(uuid4())
                ),
                created_at=(
                    ""
                    if args.template_command == "preview"
                    else settings.get_voice_template(args.template_id).get(
                        "created_at", ""
                    )
                    if args.template_command == "update"
                    else core.utc_now()
                ),
            )
            if args.template_command == "preview":
                return {
                    "voice_template": template,
                    "voice_template_panel": format_voice_template_preview(
                        template
                    ),
                    "confirmation_required": "SAVE or SAVE_DRAFT",
                }
            saved = (
                settings.update_voice_template(template, args.confirm)
                if args.template_command == "update"
                else settings.save_voice_template(template, args.confirm)
            )
            actions = settings.risk_level_actions()
            templates = settings.voice_templates()
            return {
                "voice_template": saved,
                "settings_panel": format_settings_panel(
                    actions,
                    templates,
                    threshold=settings.reply_worthiness_threshold(),
                ),
                "saved": True,
            }
        changes = parse_risk_changes(args.set_values) if args.set_values else {}
        if args.settings_command == "preview":
            result = settings.preview_draft_settings(changes, args.threshold)
            return {
                **result,
                "settings_panel": format_settings_panel(
                    result["proposed"],
                    threshold=result["proposed_threshold"],
                    preview=True,
                ),
                "confirmation_required": "SAVE",
            }
        if args.settings_command == "save":
            result = settings.save_draft_settings(
                changes, args.threshold, args.confirm
            )
            return {
                **result,
                "settings_panel": format_settings_panel(
                    result["proposed"], threshold=result["proposed_threshold"]
                ),
            }
        raise ValueError(f"Unknown settings command: {args.settings_command}")

    data_dir = home / "data"
    staging_dir = home / "staging"
    store = LocalStore(data_dir / "calmanta-personal.db")
    store.initialize()
    core = load_core()
    workflow = PersonalWorkflow(store, core, profile_path)

    if args.command == "init":
        (data_dir / "objects").mkdir(parents=True, exist_ok=True)
        staging_dir.mkdir(parents=True, exist_ok=True)
        return {
            "database": str(store.database_path),
            "objects": str((data_dir / "objects").resolve()),
            "profile": str(profile_path),
            "core": str(core.root),
        }
    if args.command == "filter-new":
        raw = _read_items(Path(args.input))
        items = workflow.filter_new(raw)
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps({"items": items}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {"new_count": len(items), "output": str(output)}
    if args.command == "ingest":
        result = workflow.ingest(_read_items(Path(args.input)))
        return {
            "created_count": len(result["created"]),
            "duplicate_count": len(result["duplicates"]),
            "items": [_review_card(item) for item in result["created"]],
        }
    if args.command == "list":
        items = store.list_items(limit=args.limit, state=args.state)
        return {
            "count": len(items),
            "items": [_review_card(item) for item in items],
        }
    if args.command == "show":
        item = _required(store, args.work_item_id)
        return {"review_card": _format_review_card(item), "item": item}
    if args.command == "edit":
        item = _required(store, args.work_item_id)
        draft_text = Path(args.draft_file).read_text(encoding="utf-8").strip()
        workflow.validate_edited_draft(item, draft_text)
        state = (
            "preview_pending_review"
            if item["item_type"] == "post"
            else "draft_pending_review"
        )
        updated = store.update_draft(
            item["work_item_id"],
            draft_text,
            state,
            "user_authored_for_review",
            core.utc_now(),
        )
        return {"item": _review_card(updated)}
    if args.command == "approve":
        if args.confirm != "OK":
            raise ValueError("Exact confirmation OK is required")
        item = _required(store, args.work_item_id)
        updated = store.approve(
            item["work_item_id"],
            str(uuid4()),
            approval_fingerprint(item),
            core.utc_now(),
        )
        return {
            "item": _review_card(updated),
            "sent": False,
            "note": (
                "Approval recorded locally. No browser send or publish "
                "action was executed."
            ),
        }
    if args.command == "reject":
        updated = store.reject(args.work_item_id, core.utc_now())
        return {"item": _review_card(updated)}
    if args.command == "complete":
        if args.confirm != "SENT":
            raise ValueError("Exact confirmation SENT is required")
        updated = store.complete(args.work_item_id, core.utc_now())
        return {"item": _review_card(updated)}
    if args.command == "put-object":
        object_store = LocalObjectStore(data_dir / "objects", store)
        metadata = object_store.put_file(
            Path(args.file),
            core.utc_now(),
            content_type=args.content_type,
        )
        return {"object": metadata}
    raise ValueError(f"Unknown command: {args.command}")


def _read_items(path: Path) -> list[dict[str, Any]]:
    resolved = path.expanduser().resolve()
    raw = json.loads(resolved.read_text(encoding="utf-8"))
    items = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError(
            "Input JSON must be an array or an object with an items array"
        )
    return items


def _read_object(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    raw = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Input JSON must be an object")
    return raw


def _required(store: LocalStore, work_item_id: str) -> dict[str, Any]:
    item = store.get_item(work_item_id)
    if item is None:
        raise ValueError("Work item not found")
    return item


def _review_card(item: dict[str, Any]) -> dict[str, Any]:
    """Collect the source, decision, and proposed action into one reviewable
    record.
    """
    return {
        "review_card": _format_review_card(item),
        "draft_text": item["draft_text"],
        "work_item_id": item["work_item_id"],
        "platform": item["platform"],
        "item_type": item["item_type"],
        "counterparty_display_name": item["counterparty_display_name"],
        "counterparty_text": item.get("counterparty_text", ""),
        "owner_context_text": item.get("owner_context_text", ""),
        "conversation_relation": item.get("conversation_relation", ""),
        "direction_verified": item.get("direction_verified", False),
        "user_intent_text": item.get("user_intent_text", ""),
        "risk_level": item.get("risk_level", ""),
        "category": item.get("category", "未分类"),
        "state": item["state"],
        "decision": item["decision"],
        "sensitive_tags": item["sensitive_tags"],
        "rationale": item["rationale"],
        "reply_worthiness_score": item.get("reply_worthiness_score", 0),
        "reply_worthiness_reason": item.get("reply_worthiness_reason", ""),
    }


def _format_review_card(item: dict[str, Any]) -> str:
    """Render the required human review order instead of relying on JSON field
    order.
    """
    if item["item_type"] == "post":
        return "\n".join(
            (
                f"拟发布预览（尚未发布）：{item.get('draft_text', '')}",
                f"ID：{item.get('work_item_id', '')}",
                f"平台：{item.get('platform', '')}",
                f"发布意图：{item.get('user_intent_text', '')}",
                (
                    "风险等级："
                    f"{_risk_level_label(item.get('risk_level', ''))}"
                    " / 评论类别："
                    f"{item.get('category', '未分类')}"
                ),
                f"建议原因：{item.get('rationale', '')}",
                "请选择：编辑预览 / 同意并发布 / 拒绝且不发布 / 拒绝并重新生成",
            )
        )

    relation = _conversation_relation_label(
        item.get("conversation_relation", "")
    )
    lines = [
        f"拟回复（尚未发送）：{item.get('draft_text', '')}",
        f"ID：{item.get('work_item_id', '')}",
        f"平台：{item.get('platform', '')}",
        f"对方：{item.get('counterparty_display_name', '')}",
        f"对方发给我的内容（原消息）：{item.get('counterparty_text', '')}",
        (
            "风险等级："
            f"{_risk_level_label(item.get('risk_level', ''))}"
            " / 评论类别："
            f"{item.get('category', '未分类')}"
        ),
        (
            "回复价值："
            f"{item.get('reply_worthiness_score', 0)}"
            " / 100 — "
            f"{item.get('reply_worthiness_reason', '')}"
        ),
        f"建议回复原因：{item.get('rationale', '')}",
        "请选择：编辑回复 / 同意并发送 / 拒绝且不回复 / 拒绝并重新生成",
        "",
        "<details>",
        "<summary>对话详情（展开查看）</summary>",
        "",
        f"对话关系：{relation}",
    ]
    owner_context = str(item.get("owner_context_text", "")).strip()
    if owner_context:
        lines.append(f"我的被回复内容（仅供上下文）：{owner_context}")
    lines.append("</details>")
    return "\n".join(lines)


def _conversation_relation_label(value: Any) -> str:
    labels = {
        "direct_message": "对方直接私信我",
        "top_level_comment": "对方直接评论我的内容",
        "reply_to_owner": "对方回复了我的评论",
    }
    return labels.get(str(value), "需要确认上下文")


def _risk_level_label(value: Any) -> str:
    labels = {
        "no_risk": "无风险",
        "low": "低风险",
        "medium": "中风险",
        "high": "高风险",
    }
    return labels.get(str(value), "未知等级")
