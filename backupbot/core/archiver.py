"""Tar archiving, manifest generation, streaming splitting, and reassembly."""

import fnmatch
import json
import logging
import os
import shutil
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from backupbot.utils.disk import compute_sha256

logger = logging.getLogger("backupbot.archiver")

FORMAT_VERSION = "1.0"


class ArchiverError(Exception):
    """Exception raised during archive creation or splitting."""
    pass


class BackupArchiver:
    """Creates tar.gz archives, embeds manifest.json, and splits them into chunks."""

    @classmethod
    def should_exclude(cls, path_str: str, exclude_patterns: List[str]) -> bool:
        """Check if a given path matches any exclude pattern."""
        if not exclude_patterns:
            return False

        basename = os.path.basename(path_str)
        norm_path = path_str.replace("\\", "/")

        for pattern in exclude_patterns:
            pattern = pattern.strip()
            if not pattern:
                continue

            # Match against basename
            if fnmatch.fnmatch(basename, pattern):
                return True

            # Match against relative or full path
            if fnmatch.fnmatch(norm_path, pattern) or fnmatch.fnmatch(f"/{norm_path}", pattern):
                return True

            # Match directory prefix pattern like "cache/*" or "*/node_modules/*"
            if pattern.endswith("/") and norm_path.startswith(pattern):
                return True

        return False

    @classmethod
    def create_tar_gz(
        cls,
        staging_dir: str,
        output_tar_gz: str,
        exclude_patterns: Optional[List[str]] = None,
    ) -> str:
        """Create compressed .tar.gz archive from staging_dir streaming on disk."""
        exclude_patterns = exclude_patterns or []
        Path(output_tar_gz).parent.mkdir(parents=True, exist_ok=True)

        def tar_filter(tarinfo: tarfile.TarInfo) -> Optional[tarfile.TarInfo]:
            if cls.should_exclude(tarinfo.name, exclude_patterns):
                logger.debug("Excluding path from archive: %s", tarinfo.name)
                return None
            return tarinfo

        logger.info("Packing staging directory %s into %s...", staging_dir, output_tar_gz)

        try:
            with tarfile.open(output_tar_gz, "w:gz") as tar:
                # Add all items in staging_dir
                for item in sorted(os.listdir(staging_dir)):
                    item_path = os.path.join(staging_dir, item)
                    tar.add(item_path, arcname=item, filter=tar_filter)
        except Exception as e:
            if os.path.exists(output_tar_gz):
                try:
                    os.remove(output_tar_gz)
                except OSError:
                    pass
            raise ArchiverError(f"Failed to create tar.gz archive: {e}") from e

        logger.info("Archive created: %s (%d bytes)", output_tar_gz, os.path.getsize(output_tar_gz))
        return output_tar_gz

    @classmethod
    def write_manifest(
        cls,
        staging_dir: str,
        backup_id: str,
        server_id: str,
        project_id: str,
        project_name: str,
        started_at: datetime,
        finished_at: datetime,
        timezone_str: str,
        composition: List[Dict[str, Any]],
    ) -> str:
        """Create and write manifest.json into the root of staging_dir."""
        manifest = {
            "format_version": FORMAT_VERSION,
            "backup_id": backup_id,
            "server_id": server_id,
            "project_id": project_id,
            "project_name": project_name,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "timezone": timezone_str,
            "composition": composition,
        }

        manifest_path = os.path.join(staging_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        return manifest_path

    @classmethod
    def split_file(
        cls,
        input_file: str,
        output_prefix: str,
        max_size_bytes: int,
        buffer_size: int = 1048576,  # 1MB buffer
    ) -> List[Dict[str, Any]]:
        """Split input_file into chunks if it exceeds max_size_bytes.

        Returns list of part info dicts:
        [{'part_index': 1, 'total_parts': N, 'file_path': ..., 'filename': ..., 'sha256': ..., 'size_bytes': ...}]
        """
        if not os.path.isfile(input_file):
            raise FileNotFoundError(f"Input file for splitting not found: {input_file}")

        file_size = os.path.getsize(input_file)

        # If file is within limit, do not split
        if file_size <= max_size_bytes:
            sha256 = compute_sha256(input_file)
            filename = os.path.basename(input_file)
            return [
                {
                    "part_index": 1,
                    "total_parts": 1,
                    "file_path": input_file,
                    "filename": filename,
                    "sha256": sha256,
                    "size_bytes": file_size,
                }
            ]

        # Splitting required
        total_parts = (file_size + max_size_bytes - 1) // max_size_bytes
        logger.info(
            "Splitting %s (%d bytes) into %d parts (max %d bytes per part)...",
            input_file,
            file_size,
            total_parts,
            max_size_bytes,
        )

        parts_info: List[Dict[str, Any]] = []
        part_idx = 1

        with open(input_file, "rb") as in_f:
            while True:
                part_filename = f"{os.path.basename(output_prefix)}.part{part_idx:02d}"
                part_path = f"{output_prefix}.part{part_idx:02d}"
                bytes_written = 0

                with open(part_path, "wb") as out_part:
                    while bytes_written < max_size_bytes:
                        read_len = min(buffer_size, max_size_bytes - bytes_written)
                        chunk = in_f.read(read_len)
                        if not chunk:
                            break
                        out_part.write(chunk)
                        bytes_written += len(chunk)

                if bytes_written == 0:
                    # Clean up empty dangling file if reached EOF exactly
                    if os.path.exists(part_path):
                        os.remove(part_path)
                    break

                sha256 = compute_sha256(part_path)
                parts_info.append(
                    {
                        "part_index": part_idx,
                        "total_parts": total_parts,
                        "file_path": part_path,
                        "filename": part_filename,
                        "sha256": sha256,
                        "size_bytes": bytes_written,
                    }
                )
                part_idx += 1

        # Correct total_parts if actual number of written parts differs
        actual_total = len(parts_info)
        for p in parts_info:
            p["total_parts"] = actual_total

        return parts_info

    @classmethod
    def reassemble_parts(
        cls,
        part_files: List[str],
        output_file: str,
        buffer_size: int = 1048576,
    ) -> str:
        """Reassemble split part files in order into a single output file."""
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "wb") as out_f:
            for part in sorted(part_files):
                with open(part, "rb") as in_part:
                    while chunk := in_part.read(buffer_size):
                        out_f.write(chunk)
        return output_file
