"""Tests for local backup retention cleanup policy."""

from datetime import datetime, timedelta, timezone

from backupbot.core.retention import RetentionManager
from backupbot.db.state import StateDatabase


def test_retention_policy_cleanup(tmp_path):
    db_path = tmp_path / "state.db"
    db = StateDatabase(str(db_path))
    retention_mgr = RetentionManager(db)

    # 1. Old successful backup (10 days old)
    old_time = datetime.now(timezone.utc) - timedelta(days=10)
    old_file = tmp_path / "old_backup.tar.gz.age"
    old_file.write_bytes(b"old archive data")

    db.create_backup("old_bk", "proj1", "vps_01", old_time)
    db.update_backup("old_bk", status="SUCCESS", archive_path=str(old_file))

    # 2. Old failed backup (10 days old) - MUST NOT BE DELETED!
    failed_file = tmp_path / "failed_backup.tar.gz.age"
    failed_file.write_bytes(b"failed data")
    db.create_backup("failed_bk", "proj1", "vps_01", old_time)
    db.update_backup("failed_bk", status="FAILED", archive_path=str(failed_file))

    # 3. Recent successful backup (1 day old) - MUST NOT BE DELETED!
    recent_time = datetime.now(timezone.utc) - timedelta(days=1)
    recent_file = tmp_path / "recent_backup.tar.gz.age"
    recent_file.write_bytes(b"recent data")
    db.create_backup("recent_bk", "proj1", "vps_01", recent_time)
    db.update_backup("recent_bk", status="SUCCESS", archive_path=str(recent_file))

    # Run cleanup with 7 days retention
    cleaned = retention_mgr.cleanup_expired_backups(retention_days=7)
    assert cleaned == 1

    # Check files
    assert not old_file.exists()
    assert failed_file.exists()
    assert recent_file.exists()

    # Check database state
    old_rec = db.get_backup("old_bk")
    assert old_rec["deleted_locally"] == 1
