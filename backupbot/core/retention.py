"""Local backup retention policy enforcement."""

import logging
import os
import shutil
from pathlib import Path
from typing import List

from backupbot.db.state import StateDatabase
from backupbot.utils.disk import format_size

logger = logging.getLogger("backupbot.retention")


class RetentionManager:
    """Cleans up expired local archives that were successfully delivered to Telegram."""

    def __init__(self, db: StateDatabase):
        self.db = db

    def cleanup_expired_backups(self, retention_days: int) -> int:
        """Find and remove local archive files of successful backups older than retention_days.

        Never deletes failed or unconfirmed backups.
        Returns the number of cleaned up backup runs.
        """
        if retention_days < 0:
            logger.debug("Retention days is negative; skipping local cleanup.")
            return 0

        expired_backups = self.db.get_expired_successful_backups(retention_days)
        if not expired_backups:
            logger.debug("No expired local backups found for cleanup (retention: %d days)", retention_days)
            return 0

        cleaned_count = 0
        freed_bytes = 0

        for b in expired_backups:
            backup_id = b["backup_id"]
            archive_path = b.get("archive_path")
            logger.info("Cleaning up expired local backup %s (started: %s)...", backup_id, b.get("started_at"))

            # Delete main archive path or staging directory if stored
            if archive_path and os.path.exists(archive_path):
                try:
                    if os.path.isfile(archive_path):
                        freed_bytes += os.path.getsize(archive_path)
                        os.remove(archive_path)
                    elif os.path.isdir(archive_path):
                        shutil.rmtree(archive_path)
                except OSError as e:
                    logger.warning("Failed to remove %s: %s", archive_path, e)

            # Check and delete individual part files
            parts = self.db.get_parts(backup_id)
            for p in parts:
                p_path = p.get("file_path")
                if p_path and os.path.isfile(p_path):
                    try:
                        freed_bytes += os.path.getsize(p_path)
                        os.remove(p_path)
                    except OSError as e:
                        logger.warning("Failed to remove part %s: %s", p_path, e)

            self.db.mark_backup_deleted_locally(backup_id)
            cleaned_count += 1

        logger.info(
            "Local retention cleanup finished: %d backup(s) pruned, %s freed",
            cleaned_count,
            format_size(freed_bytes),
        )
        return cleaned_count
