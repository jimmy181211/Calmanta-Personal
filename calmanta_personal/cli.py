from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from .core_bridge import load_core, project_root
from .object_store import LocalObjectStore
from .store import LocalStore
from .workflow import PersonalWorkflow, approval_fingerprint


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = _run(args)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, separators=(",", ":")))
    return 0


def _run(args: argparse.Namespace) -> dict[str, Any]:
    home = Path(args.home).expanduser().resolve() if args.home else project_root()
    data_dir = home / "data"
    staging_dir = home / "staging"
    store = LocalStore(data_dir / "calmanta-personal.db")
    store.initialize()
    core = load_core()
    workflow = PersonalWorkflow(store, core, home / "config" / "profile.json")

    if args.command == "init":
        (data_dir / "objects").mkdir(parents=True, exist_ok=True)
        staging_dir.mkdir(parents=True, exist_ok=True)
        return {
            "database": str(store.database_path),
            "objects": str((data_dir / "objects").resolve()),
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
        return {"count": len(items), "items": [_review_card(item) for item in items]}
    if args.command == "show":
        item = _required(store, args.work_item_id)
        return {"item": item}
    if args.command == "edit":
        item = _required(store, args.work_item_id)
        draft_text = Path(args.draft_file).read_text(encoding="utf-8").strip()
        workflow.validate_edited_draft(item, draft_text)
        state = "preview_pending_review" if item["item_type"] == "post" else "draft_pending_review"
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
            "note": "Approval recorded locally. No browser send or publish action was executed.",
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="calmanta-personal")
    parser.add_argument("--home", default="", help="Calmanta Personal project root")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init", help="Initialize local SQLite and object storage")

    filter_parser = commands.add_parser("filter-new", help="Remove already-seen observations")
    filter_parser.add_argument("--input", required=True)
    filter_parser.add_argument("--output", required=True)

    ingest_parser = commands.add_parser("ingest", help="Validate and save ChatGPT decisions")
    ingest_parser.add_argument("--input", required=True)

    list_parser = commands.add_parser("list", help="List local review items")
    list_parser.add_argument("--state", default="")
    list_parser.add_argument("--limit", type=int, default=50)

    show_parser = commands.add_parser("show", help="Show one full local review item")
    show_parser.add_argument("work_item_id")

    edit_parser = commands.add_parser("edit", help="Replace a draft and return it to review")
    edit_parser.add_argument("work_item_id")
    edit_parser.add_argument("--draft-file", required=True)

    approve_parser = commands.add_parser("approve", help="Record explicit approval without sending")
    approve_parser.add_argument("work_item_id")
    approve_parser.add_argument("--confirm", required=True)

    reject_parser = commands.add_parser("reject", help="Reject a pending work item")
    reject_parser.add_argument("work_item_id")

    complete_parser = commands.add_parser(
        "complete",
        help="Record that an already-approved browser action visibly succeeded",
    )
    complete_parser.add_argument("work_item_id")
    complete_parser.add_argument("--confirm", required=True)

    object_parser = commands.add_parser("put-object", help="Copy a file into local object storage")
    object_parser.add_argument("file")
    object_parser.add_argument("--content-type", default="")
    return parser


def _read_items(path: Path) -> list[dict[str, Any]]:
    resolved = path.expanduser().resolve()
    raw = json.loads(resolved.read_text(encoding="utf-8"))
    items = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError("Input JSON must be an array or an object with an items array")
    return items


def _required(store: LocalStore, work_item_id: str) -> dict[str, Any]:
    item = store.get_item(work_item_id)
    if item is None:
        raise ValueError("Work item not found")
    return item


def _review_card(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "work_item_id": item["work_item_id"],
        "platform": item["platform"],
        "item_type": item["item_type"],
        "counterparty_display_name": item["counterparty_display_name"],
        "original_text": item["original_text"],
        "state": item["state"],
        "decision": item["decision"],
        "draft_text": item["draft_text"],
        "sensitive_tags": item["sensitive_tags"],
        "rationale": item["rationale"],
    }
