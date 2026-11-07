"""Disk and file utilities."""

import hashlib
import os
import shutil
from pathlib import Path
from typing import Tuple


def get_free_disk_space_mb(path: str) -> float:
    """Return free disk space in megabytes for the given filesystem path."""
    target = Path(path).resolve()
    # If directory does not exist, check the nearest existing parent
    while not target.exists() and target.parent != target:
        target = target.parent

    usage = shutil.disk_usage(str(target))
    return usage.free / (1024 * 1024)


def check_disk_space(path: str, min_free_mb: float = 500.0) -> Tuple[bool, float]:
    """Check if the filesystem has enough free space."""
    free_mb = get_free_disk_space_mb(path)
    return free_mb >= min_free_mb, free_mb


def compute_sha256(file_path: str, chunk_size: int = 65536) -> str:
    """Compute SHA-256 hash of a file streaming in chunks."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def format_size(bytes_size: int) -> str:
    """Format bytes into human-readable size string (KB, MB, GB)."""
    if bytes_size < 1024:
        return f"{bytes_size} B"
    elif bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.1f} KB"
    elif bytes_size < 1024 * 1024 * 1024:
        return f"{bytes_size / (1024 * 1024):.1f} MB"
    else:
        return f"{bytes_size / (1024 * 1024 * 1024):.2f} GB"
