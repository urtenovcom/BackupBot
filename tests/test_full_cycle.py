"""Comprehensive full-cycle test: creation, splitting, encryption, Telegram upload, and complete restoration."""

import json
import os
import tarfile
from unittest.mock import MagicMock
import pyrage

from backupbot.config import AppConfig, EncryptionConfig, HooksConfig, ProjectConfig, StorageConfig, TelegramConfig
from backupbot.core.archiver import BackupArchiver
from backupbot.core.crypto import AgeEncryptor
from backupbot.core.runner import BackupRunner
from backupbot.db.state import StateDatabase
from backupbot.telegram.client import TelegramClient
from backupbot.utils.disk import compute_sha256


def test_full_backup_and_restoration_cycle(tmp_path):
    # 1. Generate Age Keypair
    identity = pyrage.x25519.Identity.generate()
    recipient_pub = str(identity.to_public())
    secret_key = str(identity)

    # 2. Setup project source directory
    src_dir = tmp_path / "project_src"
    src_dir.mkdir()
    (src_dir / "compose.yaml").write_text("services:\n  web:\n    image: nginx\n")
    (src_dir / "uploads").mkdir()
    (src_dir / "uploads" / "sample.txt").write_text("Hello from uploaded file!")
    (src_dir / "cache").mkdir()
    (src_dir / "cache" / "ignore.me").write_text("This should be excluded")

    # 3. Setup work & state paths
    work_dir = tmp_path / "work"
    state_db = tmp_path / "state.db"
    hook_marker_pre = tmp_path / "pre_hook_executed.txt"
    hook_marker_post = tmp_path / "post_hook_executed.txt"

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
                id="shop_project",
                name="Shop Project",
                schedule="0 3 * * *",
                timezone="Europe/Moscow",
                paths=[str(src_dir / "compose.yaml"), str(src_dir / "uploads")],
                exclude=["*.me", "cache/*"],
                hooks=HooksConfig(
                    pre_backup=f"touch '{hook_marker_pre}'",
                    post_backup=f"touch '{hook_marker_post}'",
                ),
                encryption=EncryptionConfig(
                    enabled=True,
                    recipient=recipient_pub,
                ),
                retention_days=7,
                split_size_mb=1,  # 1 MB threshold
            )
        ],
    )

    # 4. Mock Telegram Client to capture uploaded files and messages
    uploaded_documents = []
    sent_messages = []

    mock_telegram = MagicMock(spec=TelegramClient)

    def fake_send_document(chat_id, file_path, filename, caption):
        # Read and store document info
        with open(file_path, "rb") as f:
            content = f.read()
        doc_info = {
            "chat_id": chat_id,
            "filename": filename,
            "file_path": file_path,
            "content": content,
            "sha256": compute_sha256(file_path),
            "caption": caption,
            "message_id": 1000 + len(uploaded_documents),
        }
        uploaded_documents.append(doc_info)
        return doc_info["message_id"]

    def fake_send_message(chat_id, text):
        sent_messages.append({"chat_id": chat_id, "text": text})
        return 9999

    mock_telegram.send_document.side_effect = fake_send_document
    mock_telegram.send_message.side_effect = fake_send_message

    # 5. Run Backup
    runner = BackupRunner(app_config, telegram_client=mock_telegram)
    success = runner.run_project("shop_project")

    assert success is True
    assert hook_marker_pre.exists(), "Pre-backup hook should have been executed"
    assert hook_marker_post.exists(), "Post-backup hook should have been executed"

    # 6. Verify Telegram Uploads
    assert len(uploaded_documents) >= 1
    assert len(sent_messages) == 1
    assert "✅ Резервная копия успешно отправлена" in sent_messages[0]["text"]
    assert "#project_shop_project" in sent_messages[0]["text"]

    # 7. Check SQLite database
    db = StateDatabase(str(state_db))
    last_backup = db.get_last_backup_for_project("shop_project")
    assert last_backup is not None
    assert last_backup["status"] == "SUCCESS"
    assert last_backup["stage"] == "COMPLETED"

    # 8. RESTORATION VERIFICATION
    # Step A: Simulate receiving files from Telegram & checking SHA-256
    restored_dir = tmp_path / "restoration"
    restored_dir.mkdir()

    saved_parts = []
    for doc in uploaded_documents:
        part_save_path = restored_dir / doc["filename"]
        part_save_path.write_bytes(doc["content"])
        # Verify SHA-256 matches what caption had
        assert compute_sha256(str(part_save_path)) == doc["sha256"]
        saved_parts.append(str(part_save_path))

    # Step B: Reassemble if split
    assembled_encrypted = restored_dir / "assembled.tar.gz.age"
    BackupArchiver.reassemble_parts(saved_parts, str(assembled_encrypted))
    assert assembled_encrypted.exists()

    # Step C: Decrypt with Age Private Key
    decrypted_tar_gz = restored_dir / "restored.tar.gz"
    AgeEncryptor.decrypt_file(str(assembled_encrypted), str(decrypted_tar_gz), secret_key)
    assert decrypted_tar_gz.exists()

    # Step D: Extract archive
    extracted_data_dir = restored_dir / "extracted"
    extracted_data_dir.mkdir()
    with tarfile.open(decrypted_tar_gz, "r:gz") as tar:
        tar.extractall(path=extracted_data_dir)

    # Step E: Verify Manifest
    manifest_file = extracted_data_dir / "manifest.json"
    assert manifest_file.exists()
    with open(manifest_file, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["project_id"] == "shop_project"
    assert manifest["server_id"] == "vps_test"
    assert manifest["format_version"] == "1.0"

    # Step F: Verify Restored Contents
    # compose.yaml and uploads/sample.txt must be restored intact
    files_dir = extracted_data_dir / "files"
    assert (files_dir / "compose.yaml").exists()
    assert "services:" in (files_dir / "compose.yaml").read_text()

    assert (files_dir / "uploads" / "sample.txt").exists()
    assert (files_dir / "uploads" / "sample.txt").read_text() == "Hello from uploaded file!"

    # Excluded files must not be in archive
    assert not (files_dir / "cache" / "ignore.me").exists()
