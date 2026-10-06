"""Local SQLite state. This module never stores email body text or credentials."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

STATUSES = {"proposed", "applied", "needs_review", "transient_error"}
TERMINAL_STATUSES = {"applied", "needs_review"}


class StateStore:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.state_dir / "state.sqlite3"
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL CHECK(status IN ('proposed','applied','needs_review','transient_error')),
                    category TEXT,
                    confidence REAL,
                    internal_date_ms INTEGER,
                    recovery_floor_ms INTEGER,
                    error_code TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            message_columns = {
                str(row["name"]) for row in connection.execute("PRAGMA table_info(messages)").fetchall()
            }
            if "recovery_floor_ms" not in message_columns:
                connection.execute("ALTER TABLE messages ADD COLUMN recovery_floor_ms INTEGER")
            connection.execute("CREATE INDEX IF NOT EXISTS messages_status_idx ON messages(status)")

    def get_metadata(self, key: str) -> str | None:
        with self._connection() as connection:
            row = connection.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
            return str(row["value"]) if row else None

    def set_metadata(self, key: str, value: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO metadata(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def initialize_activation(self, history_id: str, activated_at_ms: int) -> bool:
        """Save the first cursor only. Return false when activation already exists."""
        with self._connection() as connection:
            row = connection.execute("SELECT value FROM metadata WHERE key='history_id'").fetchone()
            if row:
                return False
            connection.execute("INSERT INTO metadata(key, value) VALUES('history_id', ?)", (str(history_id),))
            connection.execute(
                "INSERT INTO metadata(key, value) VALUES('activated_at_ms', ?)", (str(int(activated_at_ms)),)
            )
            return True

    def history_id(self) -> str | None:
        return self.get_metadata("history_id")

    def set_history_id(self, history_id: str) -> None:
        self.set_metadata("history_id", str(history_id))

    def recovery_floor_ms(self) -> int | None:
        value = self.get_metadata("recovery_floor_ms")
        return int(value) if value is not None else None

    def set_recovery_floor(self, internal_date_ms: int) -> None:
        self.set_metadata("recovery_floor_ms", str(int(internal_date_ms)))

    def clear_recovery_floor(self) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM metadata WHERE key='recovery_floor_ms'")

    def ensure_transient(self, message_id: str, recovery_floor_ms: int | None = None) -> None:
        """Durably record a history message before its cursor is advanced."""
        with self._connection() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO messages(message_id, status, error_code, recovery_floor_ms)
                   VALUES(?, 'transient_error', 'pending', ?)""",
                (message_id, recovery_floor_ms),
            )

    def status(self, message_id: str) -> str | None:
        with self._connection() as connection:
            row = connection.execute("SELECT status FROM messages WHERE message_id=?", (message_id,)).fetchone()
            return str(row["status"]) if row else None

    def retryable_messages(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT message_id, category, confidence, internal_date_ms, recovery_floor_ms FROM messages WHERE status='transient_error' ORDER BY updated_at"
            ).fetchall()
            return [dict(row) for row in rows]

    def has_recovery_retries(self) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM messages WHERE status='transient_error' AND recovery_floor_ms IS NOT NULL LIMIT 1"
            ).fetchone()
            return row is not None

    def pending_proposals(self, limit: int | None = 100) -> list[dict[str, Any]]:
        with self._connection() as connection:
            query = "SELECT message_id, category, confidence, internal_date_ms FROM messages WHERE status='proposed' ORDER BY updated_at"
            if limit is not None:
                rows = connection.execute(query + " LIMIT ?", (limit,)).fetchall()
            else:
                rows = connection.execute(query).fetchall()
            return [dict(row) for row in rows]
    def save_proposal(self, message_id: str, category: str, confidence: float, internal_date_ms: int | None) -> None:
        with self._connection() as connection:
            current = connection.execute("SELECT status FROM messages WHERE message_id=?", (message_id,)).fetchone()
            if current and current["status"] in TERMINAL_STATUSES:
                return
            connection.execute(
                """INSERT INTO messages(message_id, status, category, confidence, internal_date_ms, error_code, updated_at)
                   VALUES(?, 'proposed', ?, ?, ?, NULL, CURRENT_TIMESTAMP)
                   ON CONFLICT(message_id) DO UPDATE SET status='proposed', category=excluded.category,
                     confidence=excluded.confidence, internal_date_ms=COALESCE(excluded.internal_date_ms, messages.internal_date_ms),
                     recovery_floor_ms=NULL, error_code=NULL, updated_at=CURRENT_TIMESTAMP""",
                (message_id, category, float(confidence), internal_date_ms),
            )

    def mark_applied(self, message_id: str, category: str, confidence: float, internal_date_ms: int | None) -> None:
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO messages(message_id, status, category, confidence, internal_date_ms, error_code, updated_at)
                   VALUES(?, 'applied', ?, ?, ?, NULL, CURRENT_TIMESTAMP)
                   ON CONFLICT(message_id) DO UPDATE SET status='applied', category=excluded.category,
                     confidence=excluded.confidence, internal_date_ms=COALESCE(excluded.internal_date_ms, messages.internal_date_ms),
                     recovery_floor_ms=NULL, error_code=NULL, updated_at=CURRENT_TIMESTAMP""",
                (message_id, category, float(confidence), internal_date_ms),
            )

    def mark_needs_review(self, message_id: str, internal_date_ms: int | None, error_code: str = "low_confidence") -> None:
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO messages(message_id, status, internal_date_ms, error_code, updated_at)
                   VALUES(?, 'needs_review', ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(message_id) DO UPDATE SET status='needs_review', category=NULL, confidence=NULL,
                     internal_date_ms=COALESCE(excluded.internal_date_ms, messages.internal_date_ms),
                     recovery_floor_ms=NULL, error_code=excluded.error_code, updated_at=CURRENT_TIMESTAMP""",
                (message_id, internal_date_ms, error_code),
            )

    def mark_transient_error(
        self,
        message_id: str,
        error_code: str,
        internal_date_ms: int | None = None,
        category: str | None = None,
        confidence: float | None = None,
    ) -> None:
        safe_code = error_code if error_code.replace("_", "").isalnum() else "operation_error"
        with self._connection() as connection:
            current = connection.execute("SELECT status FROM messages WHERE message_id=?", (message_id,)).fetchone()
            if current and current["status"] in TERMINAL_STATUSES:
                return
            connection.execute(
                """INSERT INTO messages(message_id, status, category, confidence, internal_date_ms, error_code, updated_at)
                   VALUES(?, 'transient_error', ?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(message_id) DO UPDATE SET status='transient_error',
                     category=COALESCE(excluded.category, messages.category),
                     confidence=COALESCE(excluded.confidence, messages.confidence),
                     internal_date_ms=COALESCE(excluded.internal_date_ms, messages.internal_date_ms),
                     error_code=excluded.error_code, updated_at=CURRENT_TIMESTAMP""",
                (message_id, category, confidence, internal_date_ms, safe_code[:48]),
            )

    def discard(self, message_id: str) -> None:
        """Remove a no-longer-eligible Inbox message from local processing state."""
        with self._connection() as connection:
            connection.execute("DELETE FROM messages WHERE message_id=?", (message_id,))

    def last_internal_date_ms(self) -> int | None:
        with self._connection() as connection:
            row = connection.execute("SELECT MAX(internal_date_ms) AS value FROM messages").fetchone()
            return int(row["value"]) if row and row["value"] is not None else None

    def proposal(self, message_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT message_id, category, confidence, internal_date_ms FROM messages WHERE message_id=? AND status='proposed'",
                (message_id,),
            ).fetchone()
            return dict(row) if row else None
    def activated_at_ms(self) -> int | None:
        value = self.get_metadata("activated_at_ms")
        return int(value) if value is not None else None
