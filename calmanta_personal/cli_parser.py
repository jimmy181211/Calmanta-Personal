"""Declare command syntax separately from command execution."""

from __future__ import annotations

import argparse


def _parser() -> argparse.ArgumentParser:
    """Declare supported commands and confirmations without executing an
    action.
    """
    parser = argparse.ArgumentParser(prog="calmanta-personal")
    parser.add_argument(
        "--home", default="", help="Calmanta Personal project root"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser(
        "init", help="Initialize local SQLite and object storage"
    )

    settings_parser = commands.add_parser(
        "settings",
        help="Show, preview, or save Personal risk-level settings",
    )
    settings_commands = settings_parser.add_subparsers(
        dest="settings_command", required=True
    )
    settings_commands.add_parser(
        "show", help="Show current risk-level settings"
    )
    preview_settings = settings_commands.add_parser(
        "preview",
        help="Preview risk-level changes without saving",
    )
    preview_settings.add_argument(
        "--set",
        dest="set_values",
        action="append",
        required=False,
        metavar="LEVEL=ACTION",
    )
    preview_settings.add_argument("--threshold", type=int)
    save_settings = settings_commands.add_parser(
        "save",
        help="Save validated risk-level changes",
    )
    save_settings.add_argument(
        "--set",
        dest="set_values",
        action="append",
        required=False,
        metavar="LEVEL=ACTION",
    )
    save_settings.add_argument("--threshold", type=int)
    save_settings.add_argument("--confirm", required=True)

    template_parser = settings_commands.add_parser(
        "template",
        help=(
            "Preview, save, draft, edit, bind, unbind, enable, disable, or "
            "delete Personal voice templates"
        ),
    )
    template_commands = template_parser.add_subparsers(
        dest="template_command", required=True
    )
    template_commands.add_parser("list", help="List saved voice templates")
    preview_template = template_commands.add_parser(
        "preview", help="Preview a voice template"
    )
    preview_template.add_argument("--input", required=True)
    save_template = template_commands.add_parser(
        "save", help="Save a reviewed voice template"
    )
    save_template.add_argument("--input", required=True)
    save_template.add_argument("--confirm", required=True)
    save_draft_template = template_commands.add_parser(
        "save-draft",
        help="Save an unfinished voice-template draft",
    )
    save_draft_template.add_argument("--input", required=True)
    save_draft_template.add_argument("--confirm", required=True)
    update_template = template_commands.add_parser(
        "update", help="Update a saved voice template"
    )
    update_template.add_argument("template_id")
    update_template.add_argument("--input", required=True)
    update_template.add_argument("--confirm", required=True)
    bind_template = template_commands.add_parser(
        "bind", help="Bind reply categories to a saved template"
    )
    bind_template.add_argument("template_id")
    bind_template.add_argument(
        "--scenario", dest="scenario_ids", action="append", required=True
    )
    bind_template.add_argument("--confirm", required=True)
    unbind_template = template_commands.add_parser(
        "unbind", help="Remove one reply-category binding"
    )
    unbind_template.add_argument("template_id")
    unbind_template.add_argument("scenario_id")
    unbind_template.add_argument("--confirm", required=True)
    for action in ("enable", "disable"):
        state_template = template_commands.add_parser(
            action, help=f"{action.title()} a voice template"
        )
        state_template.add_argument("template_id")
        state_template.add_argument("--confirm", required=True)
    delete_template = template_commands.add_parser(
        "delete", help="Delete a voice template"
    )
    delete_template.add_argument("template_id")
    delete_template.add_argument("--confirm", required=True)

    filter_parser = commands.add_parser(
        "filter-new", help="Remove already-seen observations"
    )
    filter_parser.add_argument("--input", required=True)
    filter_parser.add_argument("--output", required=True)

    ingest_parser = commands.add_parser(
        "ingest", help="Validate and save ChatGPT decisions"
    )
    ingest_parser.add_argument("--input", required=True)

    list_parser = commands.add_parser("list", help="List local review items")
    list_parser.add_argument("--state", default="")
    list_parser.add_argument("--limit", type=int, default=50)

    show_parser = commands.add_parser(
        "show", help="Show one full local review item"
    )
    show_parser.add_argument("work_item_id")

    edit_parser = commands.add_parser(
        "edit", help="Replace a draft and return it to review"
    )
    edit_parser.add_argument("work_item_id")
    edit_parser.add_argument("--draft-file", required=True)

    approve_parser = commands.add_parser(
        "approve", help="Record explicit approval without sending"
    )
    approve_parser.add_argument("work_item_id")
    approve_parser.add_argument("--confirm", required=True)

    reject_parser = commands.add_parser(
        "reject", help="Reject a pending work item"
    )
    reject_parser.add_argument("work_item_id")

    complete_parser = commands.add_parser(
        "complete",
        help=(
            "Record that an already-approved browser action visibly succeeded"
        ),
    )
    complete_parser.add_argument("work_item_id")
    complete_parser.add_argument("--confirm", required=True)

    object_parser = commands.add_parser(
        "put-object", help="Copy a file into local object storage"
    )
    object_parser.add_argument("file")
    object_parser.add_argument("--content-type", default="")
    return parser
