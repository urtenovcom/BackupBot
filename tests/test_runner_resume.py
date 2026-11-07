"""Tests for resuming interrupted uploads (uploading only unconfirmed parts)."""

import os
from unittest.mock import MagicMock
import pyrage

from backupbot.config import AppConfig, EncryptionConfig, ProjectConfig, StorageConfig, TelegramConfig
from backupbot.core.runner import BackupRunner
from backupbot.db.state import StateDatabase
from backupbot.telegram.client import TelegramAPIError, TelegramClient


def test_resume_only_uploads_unconfirmed_parts(tmp_path):
    identity = pyrage.x25519.Identity.generate()
    recipient_pub = str(identity.to_public())

    src_dir = tmp_path / "project"
    src_dir.mkdir()
    # Create ~2.5 MB of random uncompressible data so it splits into 3 parts with 1MB chunk size
    (src_dir / "large.bin").write_bytes(os.urandom(2500 * 1024))

    work_dir = tmp_path / "work"
    state_db = tmp_path / "state.db"

    app_config = AppConfig(
        server_id="vps_test",
        telegram=TelegramConfig(
            bot_token="123456789:ABCDefgh-1234567890abcdef1234567",
            chat_id="-100987654321",
        ),
        storage=StorageConfig(
            work_dir=str(work_dir),
            state_db=str(state_db),
            min_free_space_mb=10.0,
        ),
        projects=[
            ProjectConfig(
                id="my_proj",
                name="My Project",
                paths=[str(src_dir / "large.bin")],
                encryption=EncryptionConfig(enabled=True, recipient=recipient_pub),
                split_size_mb=1,
            )
        ],
    )

    mock_telegram = MagicMock(spec=TelegramClient)
    uploaded_files = []

    # First run: upload part 1 succeeds, part 2 throws TelegramAPIError
    def fake_send_doc_first_run(chat_id, file_path, filename, caption):
        if "part02" in filename:
            raise TelegramAPIError("Simulated Telegram upload network failure")
        uploaded_files.append(filename)
        return 12345

    mock_telegram.send_document.side_effect = fake_send_doc_first_run
    mock_telegram.send_message.return_value = 9999

    runner = BackupRunner(app_config, telegram_client=mock_telegram)
    # First run fails during upload
    res = runner.run_project("my_proj")
    assert res is False

    db = StateDatabase(str(state_db))
    last_backup = db.get_last_backup_for_project("my_proj")
    assert last_backup is not None
    assert last_backup["status"] == "FAILED"
    backup_id = last_backup["backup_id"]

    parts = db.get_parts(backup_id)
    assert len(parts) == 3
    # Part 1 should be UPLOADED, Part 2 and 3 should be PENDING
    assert parts[0]["status"] == "UPLOADED"
    assert parts[1]["status"] == "PENDING"
    assert parts[2]["status"] == "PENDING"
    assert uploaded_files == [parts[0]["filename"]]

    # Now simulate resuming the upload for this backup
    uploaded_on_resume = []

    def fake_send_doc_resume(chat_id, file_path, filename, caption):
        uploaded_on_resume.append(filename)
        return 54321

    mock_telegram.send_document.side_effect = fake_send_doc_resume

    from datetime import datetime

    # Call _upload_parts_to_telegram directly for the existing backup
    project = app_config.projects[0]
    runner._upload_parts_to_telegram(
        project=project,
        backup_id=backup_id,
        started_at=datetime.fromisoformat(last_backup["started_at"]),
        composition=[{"type": "file", "name": "large.bin"}],
        total_size_bytes=last_backup["total_size_bytes"],
    )

    # CRITICAL VERIFICATION:
    # Part 1 was ALREADY uploaded, so it MUST NOT have been uploaded again!
    # Only parts 2 and 3 should be in uploaded_on_resume!
    assert parts[0]["filename"] not in uploaded_on_resume
    assert parts[1]["filename"] in uploaded_on_resume
    assert parts[2]["filename"] in uploaded_on_resume

    # Check that all parts are now marked UPLOADED in SQLite
    unconfirmed = db.get_unconfirmed_parts(backup_id)
    assert len(unconfirmed) == 0
