"""SQLite audit log for ClawSafe."""

import sqlite3
import json
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .config import config_dir


@dataclass
class Event:
    id: int
    timestamp: datetime
    tool: str
    arguments: str  # JSON string
    verdict: str
    rule: str
    reason: str
    cloud_judgment: bool
    override: bool
    synced: bool


class AuditStore:
    """SQLite-backed audit log."""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = config_dir() / "audit.db"

        db_path.parent.mkdir(parents=True, exist_ok=True)

        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._init_schema()

    def _init_schema(self):
        """Initialize database schema."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                tool TEXT NOT NULL,
                arguments TEXT NOT NULL,
                verdict TEXT NOT NULL,
                rule TEXT,
                reason TEXT,
                cloud_judgment INTEGER DEFAULT 0,
                override INTEGER DEFAULT 0,
                synced INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS allowlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool TEXT NOT NULL,
                argument_pattern TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_events_tool ON events(tool);
            CREATE INDEX IF NOT EXISTS idx_events_verdict ON events(verdict);
        """)
        self.conn.commit()

    def log_event(
        self,
        tool: str,
        arguments: dict[str, Any],
        verdict: str,
        rule: str,
        reason: str,
        cloud_judgment: bool = False,
        override: bool = False,
    ) -> Event:
        """Log a tool call event."""
        args_json = json.dumps(arguments)

        cursor = self.conn.execute(
            """
            INSERT INTO events (tool, arguments, verdict, rule, reason, cloud_judgment, override)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (tool, args_json, verdict, rule, reason, int(cloud_judgment), int(override))
        )
        self.conn.commit()

        return Event(
            id=cursor.lastrowid,
            timestamp=datetime.now(),
            tool=tool,
            arguments=args_json,
            verdict=verdict,
            rule=rule,
            reason=reason,
            cloud_judgment=cloud_judgment,
            override=override,
            synced=False,
        )

    def get_recent_events(self, limit: int = 20) -> list[Event]:
        """Get most recent events."""
        cursor = self.conn.execute(
            """
            SELECT id, timestamp, tool, arguments, verdict, rule, reason,
                   cloud_judgment, override, synced
            FROM events
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,)
        )

        events = []
        for row in cursor:
            events.append(Event(
                id=row[0],
                timestamp=datetime.fromisoformat(row[1]) if row[1] else datetime.now(),
                tool=row[2],
                arguments=row[3],
                verdict=row[4],
                rule=row[5] or "",
                reason=row[6] or "",
                cloud_judgment=bool(row[7]),
                override=bool(row[8]),
                synced=bool(row[9]),
            ))

        return events

    def get_stats(self) -> tuple[int, int, int]:
        """Get counts of allowed, blocked, and gray events."""
        cursor = self.conn.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN verdict = 'allow' THEN 1 ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN verdict = 'block' THEN 1 ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN verdict = 'gray' THEN 1 ELSE 0 END), 0)
            FROM events
        """)
        row = cursor.fetchone()
        return row[0], row[1], row[2]

    def add_to_allowlist(self, tool: str, argument_pattern: Optional[str] = None):
        """Add a tool to the allowlist."""
        self.conn.execute(
            "INSERT INTO allowlist (tool, argument_pattern) VALUES (?, ?)",
            (tool, argument_pattern)
        )
        self.conn.commit()

    def is_in_allowlist(self, tool: str) -> bool:
        """Check if a tool is in the allowlist."""
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM allowlist WHERE tool = ?",
            (tool,)
        )
        return cursor.fetchone()[0] > 0

    def close(self):
        """Close the database connection."""
        self.conn.close()
