"""
Local SQLite audit log.

Design decisions:
- Uses aiosqlite for async operations (non-blocking in the proxy event loop)
- Arguments are stored LOCALLY and never synced to the dashboard
- The dashboard only receives: timestamp, tool, verdict, rule_name, reason
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL    NOT NULL,
    tool        TEXT    NOT NULL,
    arguments   TEXT    NOT NULL,
    verdict     TEXT    NOT NULL CHECK (verdict IN ('allow', 'block', 'gray')),
    rule_name   TEXT    DEFAULT '',
    reason      TEXT    DEFAULT '',
    cloud_used  INTEGER DEFAULT 0,
    overridden  INTEGER DEFAULT 0,
    synced      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS allowlist (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tool            TEXT    NOT NULL,
    argument_hash   TEXT,
    note            TEXT    DEFAULT '',
    created_at      REAL    NOT NULL DEFAULT (unixepoch())
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_synced    ON events(synced, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_verdict   ON events(verdict, timestamp DESC);
"""


class AuditLog:
    """Async SQLite audit log."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Open the database connection and create tables."""
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        logger.info(f"Audit log initialized: {self.db_path}")

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def log_event(
        self,
        tool: str,
        arguments: dict,
        verdict: str,
        rule_name: str = "",
        reason: str = "",
        cloud_used: bool = False,
        overridden: bool = False,
    ) -> int:
        """Insert one event into the audit log. Returns the new row ID."""
        cursor = await self._db.execute(
            """INSERT INTO events
               (timestamp, tool, arguments, verdict, rule_name, reason, cloud_used, overridden)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                time.time(),
                tool,
                json.dumps(arguments),
                verdict,
                rule_name,
                reason,
                int(cloud_used),
                int(overridden),
            )
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_unsynced(self, limit: int = 100) -> list[dict]:
        """Return events not yet synced to the dashboard (arguments excluded)."""
        async with self._db.execute(
            """SELECT id, timestamp, tool, verdict, rule_name, reason, cloud_used
               FROM events
               WHERE synced = 0
               ORDER BY timestamp
               LIMIT ?""",
            (limit,)
        ) as cursor:
            rows = await cursor.fetchall()

        return [
            {
                "id": row["id"],
                "timestamp": row["timestamp"],
                "tool": row["tool"],
                "verdict": row["verdict"],
                "rule_name": row["rule_name"],
                "reason": row["reason"],
                "cloud_used": bool(row["cloud_used"]),
            }
            for row in rows
        ]

    async def mark_synced(self, event_ids: list[int]) -> None:
        """Mark events as synced after successful dashboard upload."""
        if not event_ids:
            return
        placeholders = ",".join("?" * len(event_ids))
        await self._db.execute(
            f"UPDATE events SET synced = 1 WHERE id IN ({placeholders})",
            event_ids
        )
        await self._db.commit()

    async def recent(self, limit: int = 50, verdict_filter: str | None = None) -> list[dict]:
        """Get recent events for the CLI logs command."""
        if verdict_filter:
            query = "SELECT * FROM events WHERE verdict = ? ORDER BY timestamp DESC LIMIT ?"
            params = (verdict_filter, limit)
        else:
            query = "SELECT * FROM events ORDER BY timestamp DESC LIMIT ?"
            params = (limit,)

        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        return [
            {
                "id": row["id"],
                "timestamp": row["timestamp"],
                "tool": row["tool"],
                "arguments": json.loads(row["arguments"]),
                "verdict": row["verdict"],
                "rule_name": row["rule_name"],
                "reason": row["reason"],
                "cloud_used": bool(row["cloud_used"]),
                "overridden": bool(row["overridden"]),
            }
            for row in rows
        ]

    async def stats(self) -> dict:
        """Return summary statistics for the status command."""
        async with self._db.execute(
            """SELECT verdict, COUNT(*) as count FROM events GROUP BY verdict"""
        ) as cursor:
            rows = await cursor.fetchall()

        result = {"allow": 0, "block": 0, "gray": 0, "total": 0}
        for row in rows:
            result[row["verdict"]] = row["count"]
            result["total"] += row["count"]
        return result
