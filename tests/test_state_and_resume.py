"""Tests for SQLite state database and upload resumption."""

from datetime import datetime, timezone

from backupbot.db.state import StateDatabase


def test_state_db_lifecycle_and_resume(tmp_path):
    db_file = tmp_path / "state.db"
    db = StateDatabase(str(db_file))

    started = datetime.now(timezone.utc)
    backup_id = "bk_test_100"

    # 1. Create backup
    db.create_backup(backup_id, "project_a", "vps_01", started)
    rec = db.get_backup(backup_id)
    assert rec is not None
    assert rec["status"] == "PENDING"
    assert rec["stage"] == "INIT"

    # 2. Record 3 parts
    parts = [
        {
            "backup_id": backup_id,
            "part_index": 1,
            "total_parts": 3,
            "filename": "part01.age",
            "file_path": "/tmp/part01.age",
            "sha256": "hash1",
            "size_bytes": 1000,
        },
        {
            "backup_id": backup_id,
            "part_index": 2,
            "total_parts": 3,
            "filename": "part02.age",
            "file_path": "/tmp/part02.age",
            "sha256": "hash2",
            "size_bytes": 1000,
        },
        {
            "backup_id": backup_id,
            "part_index": 3,
            "total_parts": 3,
            "filename": "part03.age",
            "file_path": "/tmp/part03.age",
            "sha256": "hash3",
            "size_bytes": 500,
        },
    ]
    db.record_parts(parts)

    all_parts = db.get_parts(backup_id)
    assert len(all_parts) == 3

    unconfirmed = db.get_unconfirmed_parts(backup_id)
    assert len(unconfirmed) == 3

    # 3. Simulate uploading part 1
    db.mark_part_uploaded(backup_id, part_index=1, telegram_message_id=98765)

    # 4. Check unconfirmed parts - now only part 2 and 3 should be returned!
    unconfirmed_after = db.get_unconfirmed_parts(backup_id)
    assert len(unconfirmed_after) == 2
    assert [p["part_index"] for p in unconfirmed_after] == [2, 3]

    # Check part 1 has message_id stored
    updated_parts = db.get_parts(backup_id)
    p1 = next(p for p in updated_parts if p["part_index"] == 1)
    assert p1["status"] == "UPLOADED"
    assert p1["telegram_message_id"] == 98765

    # 5. Mark remaining parts
    db.mark_part_uploaded(backup_id, part_index=2, telegram_message_id=98766)
    db.mark_part_uploaded(backup_id, part_index=3, telegram_message_id=98767)

    assert len(db.get_unconfirmed_parts(backup_id)) == 0

    # 6. Update backup to SUCCESS
    db.update_backup(backup_id, status="SUCCESS", stage="COMPLETED")
    final_backup = db.get_backup(backup_id)
    assert final_backup["status"] == "SUCCESS"
    assert final_backup["stage"] == "COMPLETED"
