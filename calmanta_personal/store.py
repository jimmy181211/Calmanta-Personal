from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS work_items (
    work_item_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL UNIQUE,
    platform TEXT NOT NULL,
    item_type TEXT NOT NULL,
    counterparty_key TEXT NOT NULL DEFAULT '',
    counterparty_display_name TEXT NOT NULL DEFAULT '',
    counterparty_text TEXT NOT NULL DEFAULT '',
    owner_context_text TEXT NOT NULL DEFAULT '',
    conversation_relation TEXT NOT NULL DEFAULT 'not_applicable',
    direction_verified INTEGER NOT NULL DEFAULT 0,
    role_resolution_source TEXT NOT NULL DEFAULT '',
    user_intent_text TEXT NOT NULL DEFAULT '',
    platform_item_id TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    observed_at TEXT NOT NULL DEFAULT '',
    decision TEXT NOT NULL,
    state TEXT NOT NULL,
    sensitive_tags_json TEXT NOT NULL DEFAULT '[]',
    category TEXT NOT NULL DEFAULT '未分类',
    risk_level TEXT NOT NULL DEFAULT 'low',
    rationale TEXT NOT NULL DEFAULT '',
    reply_worthiness_score INTEGER NOT NULL DEFAULT 0 CHECK (
        reply_worthiness_score BETWEEN 0 AND 100
    ),
    reply_worthiness_reason TEXT NOT NULL DEFAULT '',
    reply_worthiness_signals_json TEXT NOT NULL DEFAULT '[]',
    voice_profile_json TEXT NOT NULL DEFAULT '{}',
    draft_text TEXT NOT NULL DEFAULT '',
    preview_payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    approved_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_work_items_state_created
ON work_items(state, created_at DESC);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    work_item_id TEXT NOT NULL REFERENCES work_items(work_item_id),
    confirmation TEXT NOT NULL,
    approved_text TEXT NOT NULL,
    action_fingerprint TEXT NOT NULL,
    approved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_item_id TEXT NOT NULL REFERENCES work_items(work_item_id),
    event_type TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS objects (
    object_key TEXT PRIMARY KEY,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    content_type TEXT NOT NULL,
    source_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

JSON_FIELDS = {
    "sensitive_tags_json": "sensitive_tags",
    "reply_worthiness_signals_json": "reply_worthiness_signals",
    "voice_profile_json": "voice_profile",
    "preview_payload_json": "preview_payload",
}


class LocalStore:
    def __init__(self, database_path: Path):
        self.database_path = database_path.resolve()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate_work_item_roles(connection)

    def has_fingerprint(self, fingerprint: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM work_items WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
        return row is not None

    def create_item(self, item: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        columns = [
            "work_item_id",
            "fingerprint",
            "platform",
            "item_type",
            "counterparty_key",
            "counterparty_display_name",
            "counterparty_text",
            "owner_context_text",
            "conversation_relation",
            "direction_verified",
            "role_resolution_source",
            "user_intent_text",
            "platform_item_id",
            "source_url",
            "observed_at",
            "decision",
            "state",
            "sensitive_tags_json",
            "category",
            "risk_level",
            "rationale",
            "reply_worthiness_score",
            "reply_worthiness_reason",
            "reply_worthiness_signals_json",
            "voice_profile_json",
            "draft_text",
            "preview_payload_json",
            "created_at",
            "updated_at",
            "approved_at",
        ]
        record = dict(item)
        record["sensitive_tags_json"] = _json(record.pop("sensitive_tags", []))
        record["reply_worthiness_signals_json"] = _json(
            record.pop("reply_worthiness_signals", [])
        )
        record["voice_profile_json"] = _json(record.pop("voice_profile", {}))
        record["preview_payload_json"] = _json(record.pop("preview_payload", {}))
        values = [record.get(column, "") for column in columns]
        placeholders = ", ".join("?" for _ in columns)
        insert_sql = (
            f"INSERT INTO work_items ({', '.join(columns)}) VALUES ({placeholders})"  # noqa: S608 - column names are a fixed list above.
        )
        try:
            with self._connect() as connection:
                connection.execute(insert_sql, values)
                self._event(
                    connection,
                    item["work_item_id"],
                    "created",
                    {"state": item["state"], "decision": item["decision"]},
                    item["created_at"],
                )
        except sqlite3.IntegrityError as exc:
            if "fingerprint" not in str(exc).lower():
                raise
            existing = self.get_by_fingerprint(item["fingerprint"])
            if existing is None:
                raise
            return existing, False
        created = self.get_item(item["work_item_id"])
        if created is None:
            raise RuntimeError("Created work item could not be reloaded")
        return created, True

    def get_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM work_items WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
        return _row(row)

    def get_item(self, work_item_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM work_items WHERE work_item_id = ?",
                (work_item_id,),
            ).fetchone()
        return _row(row)

    def list_items(self, limit: int = 50, state: str = "") -> list[dict[str, Any]]:
        bounded = max(1, min(limit, 200))
        query = "SELECT * FROM work_items"
        parameters: tuple[Any, ...] = ()
        if state:
            query += " WHERE state = ?"
            parameters = (state,)
        query += " ORDER BY created_at DESC LIMIT ?"
        parameters += (bounded,)
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_row(row) for row in rows if row is not None]

    def update_draft(
        self,
        work_item_id: str,
        draft_text: str,
        state: str,
        decision: str,
        updated_at: str,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            current = connection.execute(
                """
                SELECT state, item_type, preview_payload_json
                FROM work_items WHERE work_item_id = ?
                """,
                (work_item_id,),
            ).fetchone()
            if current is None:
                raise ValueError("Work item not found")
            if current["state"] not in {
                "draft_pending_review",
                "preview_pending_review",
                "no_reply_recommended",
                "record_only",
                "user_handling_required",
            }:
                raise ValueError("This work item cannot be edited")
            preview_payload = json.loads(current["preview_payload_json"])
            if current["item_type"] == "post":
                preview_payload["caption"] = draft_text
                preview_payload["publish_status"] = "preview_only"
            connection.execute(
                """
                UPDATE work_items
                SET draft_text = ?, preview_payload_json = ?, state = ?, decision = ?,
                    updated_at = ?, approved_at = ''
                WHERE work_item_id = ?
                """,
                (
                    draft_text,
                    _json(preview_payload),
                    state,
                    decision,
                    updated_at,
                    work_item_id,
                ),
            )
            self._event(connection, work_item_id, "draft_edited", {}, updated_at)
        return self._required_item(work_item_id)

    def approve(
        self,
        work_item_id: str,
        approval_id: str,
        action_fingerprint: str,
        approved_at: str,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state, draft_text FROM work_items WHERE work_item_id = ?",
                (work_item_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Work item not found")
            if row["state"] not in {"draft_pending_review", "preview_pending_review"}:
                raise ValueError("Only a pending draft or post preview can be approved")
            if not row["draft_text"].strip():
                raise ValueError("Approved content cannot be empty")
            connection.execute(
                """
                INSERT INTO approvals (
                    approval_id, work_item_id, confirmation, approved_text,
                    action_fingerprint, approved_at
                ) VALUES (?, ?, 'OK', ?, ?, ?)
                """,
                (approval_id, work_item_id, row["draft_text"], action_fingerprint, approved_at),
            )
            connection.execute(
                """
                UPDATE work_items
                SET state = 'approved', updated_at = ?, approved_at = ?
                WHERE work_item_id = ?
                """,
                (approved_at, approved_at, work_item_id),
            )
            self._event(
                connection,
                work_item_id,
                "approved_with_explicit_ok",
                {"action_fingerprint": action_fingerprint},
                approved_at,
            )
        return self._required_item(work_item_id)

    def reject(self, work_item_id: str, updated_at: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state FROM work_items WHERE work_item_id = ?",
                (work_item_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Work item not found")
            if row["state"] in {"approved", "rejected", "hard_blocked", "completed"}:
                raise ValueError("This work item cannot be rejected")
            connection.execute(
                """
                UPDATE work_items
                SET state = 'rejected', decision = 'user_rejected', updated_at = ?
                WHERE work_item_id = ?
                """,
                (updated_at, work_item_id),
            )
            self._event(connection, work_item_id, "user_rejected", {}, updated_at)
        return self._required_item(work_item_id)

    def complete(self, work_item_id: str, updated_at: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state FROM work_items WHERE work_item_id = ?",
                (work_item_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Work item not found")
            if row["state"] != "approved":
                raise ValueError("Only an approved work item can be marked completed")
            connection.execute(
                "UPDATE work_items SET state = 'completed', updated_at = ? WHERE work_item_id = ?",
                (updated_at, work_item_id),
            )
            self._event(
                connection,
                work_item_id,
                "platform_action_confirmed",
                {"confirmation": "SENT"},
                updated_at,
            )
        return self._required_item(work_item_id)

    def record_object(self, metadata: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO objects (
                    object_key, size_bytes, sha256, content_type, source_name, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    metadata["object_key"],
                    metadata["size_bytes"],
                    metadata["sha256"],
                    metadata["content_type"],
                    metadata["source_name"],
                    metadata["created_at"],
                ),
            )

    def _required_item(self, work_item_id: str) -> dict[str, Any]:
        item = self.get_item(work_item_id)
        if item is None:
            raise ValueError("Work item not found")
        return item

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        work_item_id: str,
        event_type: str,
        details: dict[str, Any],
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO events (work_item_id, event_type, details_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (work_item_id, event_type, _json(details), created_at),
        )

    @staticmethod
    def _migrate_work_item_roles(connection: sqlite3.Connection) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(work_items)").fetchall()
        }
        if "original_text" in columns and "counterparty_text" not in columns:
            connection.execute("ALTER TABLE work_items RENAME COLUMN original_text TO counterparty_text")
            columns.remove("original_text")
            columns.add("counterparty_text")
        additions = {
            "owner_context_text": "TEXT NOT NULL DEFAULT ''",
            "conversation_relation": "TEXT NOT NULL DEFAULT 'unknown'",
            "direction_verified": "INTEGER NOT NULL DEFAULT 0",
            "role_resolution_source": "TEXT NOT NULL DEFAULT 'legacy_unverified'",
            "user_intent_text": "TEXT NOT NULL DEFAULT ''",
            "category": "TEXT NOT NULL DEFAULT '未分类'",
            "reply_worthiness_score": "INTEGER NOT NULL DEFAULT 0",
            "reply_worthiness_reason": "TEXT NOT NULL DEFAULT ''",
            "reply_worthiness_signals_json": "TEXT NOT NULL DEFAULT '[]'",
        }
        for column, definition in additions.items():
            if column not in columns:
                connection.execute(
                    f"ALTER TABLE work_items ADD COLUMN {column} {definition}"  # noqa: S608 - values come from the fixed additions mapping above.
                )
        connection.execute(
            """
            UPDATE work_items
            SET user_intent_text = counterparty_text,
                counterparty_text = '',
                conversation_relation = 'not_applicable',
                direction_verified = 1,
                role_resolution_source = 'legacy_post'
            WHERE item_type = 'post' AND user_intent_text = ''
            """
        )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    if "direction_verified" in result:
        result["direction_verified"] = bool(result["direction_verified"])
    for database_field, public_field in JSON_FIELDS.items():
        result[public_field] = json.loads(result.pop(database_field))
    return result
