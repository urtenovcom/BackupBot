"""Concurrency control using file-based locking."""

import fcntl
import os
import time
from pathlib import Path
from typing import Optional


class LockAcquisitionError(Exception):
    """Raised when lock cannot be acquired."""
    pass


class BackupLock:
    """Mutual exclusion lock using fcntl.flock to prevent overlapping backup runs."""

    def __init__(self, lock_dir: str, name: str = "backupbot.lock", blocking: bool = False, timeout: float = 0.0):
        self.lock_dir = Path(lock_dir)
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        self.lock_file_path = self.lock_dir / name
        self.blocking = blocking
        self.timeout = timeout
        self._fd: Optional[int] = None

    def acquire(self) -> bool:
        """Acquire the lock. Raises LockAcquisitionError if non-blocking and already held."""
        self._fd = os.open(str(self.lock_file_path), os.O_CREAT | os.O_RDWR, 0o600)
        flags = fcntl.LOCK_EX
        if not self.blocking:
            flags |= fcntl.LOCK_NB

        start_time = time.time()
        while True:
            try:
                fcntl.flock(self._fd, flags)
                # Write current PID into lock file for debugging
                os.ftruncate(self._fd, 0)
                os.write(self._fd, f"{os.getpid()}\n".encode("utf-8"))
                return True
            except (BlockingIOError, OSError) as e:
                if not self.blocking or (self.timeout > 0 and (time.time() - start_time) >= self.timeout):
                    self.release()
                    raise LockAcquisitionError(
                        f"Another backup process is currently running (lock file: {self.lock_file_path})"
                    ) from e
                time.sleep(0.5)

    def release(self) -> None:
        """Release the file lock."""
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def __enter__(self) -> "BackupLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()
