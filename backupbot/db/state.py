"""SQLite database for backup run tracking and resume management."""

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class StateDatabase:
    """Manages persistent SQLite storage of backup runs and uploaded parts."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS backups (
                    backup_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    server_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    total_parts INTEGER DEFAULT 0,
                    total_size_bytes INTEGER DEFAULT 0,
                    archive_path TEXT,
                    error_message TEXT,
                    deleted_locally INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS backup_parts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    backup_id TEXT NOT NULL,
                    part_index INTEGER NOT NULL,
                    total_parts INTEGER NOT NULL,
                    filename TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    telegram_message_id INTEGER,
                    uploaded_at TEXT,
                    FOREIGN KEY(backup_id) REFERENCES backups(backup_id)
                );

                CREATE INDEX IF NOT EXISTS idx_backups_project ON backups(project_id);
                CREATE INDEX IF NOT EXISTS idx_parts_backup ON backup_parts(backup_id);
                """
            )

    def create_backup(
        self,
        backup_id: str,
        project_id: str,
        server_id: str,
        started_at: datetime,
    ) -> None:
        """Create initial backup record in PENDING state."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO backups (
                    backup_id, project_id, server_id, status, stage, started_at, created_at
                ) VALUES (?, ?, ?, 'PENDING', 'INIT', ?, ?)
                """,
                (
                    backup_id,
                    project_id,
                    server_id,
                    started_at.isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def update_backup(
        self,
        backup_id: str,
        status: Optional[str] = None,
        stage: Optional[str] = None,
        finished_at: Optional[datetime] = None,
        total_parts: Optional[int] = None,
        total_size_bytes: Optional[int] = None,
        archive_path: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update backup fields."""
        fields = []
        values = []

        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if stage is not None:
            fields.append("stage = ?")
            values.append(stage)
        if finished_at is not None:
            fields.append("finished_at = ?")
            values.append(finished_at.isoformat())
        if total_parts is not None:
            fields.append("total_parts = ?")
            values.append(total_parts)
        if total_size_bytes is not None:
            fields.append("total_size_bytes = ?")
            values.append(total_size_bytes)
        if archive_path is not None:
            fields.append("archive_path = ?")
            values.append(archive_path)
        if error_message is not None:
            fields.append("error_message = ?")
            values.append(error_message)

        if not fields:
            return

        values.append(backup_id)
        query = f"UPDATE backups SET {', '.join(fields)} WHERE backup_id = ?"

        with self._get_connection() as conn:
            conn.execute(query, values)

    def record_parts(self, parts: List[Dict[str, Any]]) -> None:
        """Record all prepared parts for a backup."""
        with self._get_connection() as conn:
            for p in parts:
                conn.execute(
                    """
                    INSERT INTO backup_parts (
                        backup_id, part_index, total_parts, filename, file_path,
                        sha256, size_bytes, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING')
                    """,
                    (
                        p["backup_id"],
                        p["part_index"],
                        p["total_parts"],
                        p["filename"],
                        p["file_path"],
                        p["sha256"],
                        p["size_bytes"],
                    ),
                )

    def mark_part_uploaded(self, backup_id: str, part_index: int, telegram_message_id: int) -> None:
        """Mark a specific part as successfully uploaded with Telegram message_id."""
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE backup_parts
                SET status = 'UPLOADED',
                    telegram_message_id = ?,
                    uploaded_at = ?
                WHERE backup_id = ? AND part_index = ?
                """,
                (
                    telegram_message_id,
                    datetime.now(timezone.utc).isoformat(),
                    backup_id,
                    part_index,
                ),
            )

    def get_parts(self, backup_id: str) -> List[Dict[str, Any]]:
        """Retrieve all parts registered for a backup."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM backup_parts
                WHERE backup_id = ?
                ORDER BY part_index ASC
                """,
                (backup_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_unconfirmed_parts(self, backup_id: str) -> List[Dict[str, Any]]:
        """Retrieve parts that have not yet been confirmed uploaded to Telegram."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM backup_parts
                WHERE backup_id = ? AND (status != 'UPLOADED' OR telegram_message_id IS NULL)
                ORDER BY part_index ASC
                """,
                (backup_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_backup(self, backup_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve backup record by backup_id."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM backups WHERE backup_id = ?",
                (backup_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_last_backup_for_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Get the most recent backup record for a given project."""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM backups
                WHERE project_id = ?
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (project_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_backups(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List most recent backups."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM backups
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_expired_successful_backups(self, retention_days: int) -> List[Dict[str, Any]]:
        """Get SUCCESS backups older than retention_days that have not been pruned locally."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM backups
                WHERE status = 'SUCCESS'
                  AND deleted_locally = 0
                  AND started_at <= ?
                """,
                (cutoff,),
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_backup_deleted_locally(self, backup_id: str) -> None:
        """Mark backup as cleaned up locally."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE backups SET deleted_locally = 1 WHERE backup_id = ?",
                (backup_id,),
            )
