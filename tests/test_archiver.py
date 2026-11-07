"""Tests for archive creation, manifest generation, splitting, and reassembly."""

import json
import os
import tarfile
from datetime import datetime
from zoneinfo import ZoneInfo

from backupbot.core.archiver import BackupArchiver
from backupbot.utils.disk import compute_sha256


def test_write_manifest(tmp_path):
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()

    dt_start = datetime(2026, 11, 7, 3, 0, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    dt_end = datetime(2026, 11, 7, 3, 1, 30, tzinfo=ZoneInfo("Europe/Moscow"))

    manifest_path = BackupArchiver.write_manifest(
        staging_dir=str(staging_dir),
        backup_id="bk_123",
        server_id="vps_01",
        project_id="test_proj",
        project_name="Test Project",
        started_at=dt_start,
        finished_at=dt_end,
        timezone_str="Europe/Moscow",
        composition=[{"type": "database", "name": "db1", "size_bytes": 1024}],
    )

    assert os.path.isfile(manifest_path)
    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["backup_id"] == "bk_123"
    assert data["server_id"] == "vps_01"
    assert data["project_id"] == "test_proj"
    assert data["format_version"] == "1.0"
    assert len(data["composition"]) == 1


def test_create_tar_gz_with_exclusions(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()

    (staging / "app.py").write_text("print('hello')")
    (staging / "app.log").write_text("debug log")
    (staging / "cache").mkdir()
    (staging / "cache" / "temp.dat").write_text("cache data")

    archive_path = tmp_path / "archive.tar.gz"
    BackupArchiver.create_tar_gz(
        staging_dir=str(staging),
        output_tar_gz=str(archive_path),
        exclude_patterns=["*.log", "cache/*"],
    )

    assert archive_path.exists()

    with tarfile.open(archive_path, "r:gz") as tar:
        names = tar.getnames()
        assert "app.py" in names
        assert "app.log" not in names
        assert "cache/temp.dat" not in names


def test_split_and_reassemble(tmp_path):
    data_file = tmp_path / "large_data.bin"
    # Create a 2.5 MB file
    content = os.urandom(2500000)
    data_file.write_bytes(content)
    orig_sha256 = compute_sha256(str(data_file))

    # Split into 1MB (1048576 bytes) chunks
    split_prefix = tmp_path / "chunks" / "backup.bin"
    (tmp_path / "chunks").mkdir()
    max_chunk_size = 1048576

    parts = BackupArchiver.split_file(
        input_file=str(data_file),
        output_prefix=str(split_prefix),
        max_size_bytes=max_chunk_size,
    )

    assert len(parts) == 3
    assert parts[0]["part_index"] == 1
    assert parts[0]["total_parts"] == 3
    assert parts[0]["size_bytes"] == max_chunk_size
    assert parts[1]["size_bytes"] == max_chunk_size
    assert parts[2]["size_bytes"] == 2500000 - 2 * max_chunk_size

    # Reassemble parts
    reassembled_file = tmp_path / "restored.bin"
    part_paths = [p["file_path"] for p in parts]
    BackupArchiver.reassemble_parts(part_paths, str(reassembled_file))

    assert reassembled_file.exists()
    assert reassembled_file.stat().st_size == len(content)
    assert compute_sha256(str(reassembled_file)) == orig_sha256
    assert reassembled_file.read_bytes() == content
