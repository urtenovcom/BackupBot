"""Tests for concurrency control and mutual exclusion file locking."""

import pytest

from backupbot.core.lock import BackupLock, LockAcquisitionError


def test_lock_mutual_exclusion(tmp_path):
    lock_dir = tmp_path / "locks"

    lock1 = BackupLock(str(lock_dir), name="test.lock", blocking=False)
    lock2 = BackupLock(str(lock_dir), name="test.lock", blocking=False)

    # First lock succeeds
    assert lock1.acquire() is True

    # Second lock fails
    with pytest.raises(LockAcquisitionError):
        lock2.acquire()

    # Release first lock
    lock1.release()

    # Now second lock succeeds
    assert lock2.acquire() is True
    lock2.release()


def test_lock_context_manager(tmp_path):
    lock_dir = tmp_path / "locks"

    with BackupLock(str(lock_dir), name="ctx.lock", blocking=False):
        # Nested attempt should fail
        with pytest.raises(LockAcquisitionError):
            with BackupLock(str(lock_dir), name="ctx.lock", blocking=False):
                pass

    # After exit, can acquire again
    with BackupLock(str(lock_dir), name="ctx.lock", blocking=False):
        pass
