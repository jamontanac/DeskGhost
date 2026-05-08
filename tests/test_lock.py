"""Unit tests for deskghost.lock — cross-platform single-instance file lock.

All tests use pytest's ``tmp_path`` fixture so nothing touches the real
~/.deskghost directory.  The tests exercise the actual OS file-lock
primitives (fcntl on macOS, msvcrt on Windows) rather than mocking them,
giving high confidence that the mechanism works on each platform.
"""

import multiprocessing
import sys
from pathlib import Path

import pytest

from deskghost.lock import InstanceLock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _try_acquire(lock_path: Path, result_queue: multiprocessing.Queue) -> None:
    """Subprocess target: try to acquire the lock and report back.

    Puts True into ``result_queue`` if the lock was acquired, False otherwise.
    Stays alive until the queue has an item pushed back to it (used as a
    signal to release the lock and exit).
    """
    with InstanceLock(path=lock_path) as lock:
        result_queue.put(bool(lock))
        # Wait for the test to signal us to exit
        result_queue.get()


# ---------------------------------------------------------------------------
# Basic acquisition
# ---------------------------------------------------------------------------

class TestInstanceLockAcquisition:
    def test_lock_acquired_when_free(self, tmp_path):
        lock_file = tmp_path / "test.lock"
        with InstanceLock(path=lock_file) as lock:
            assert bool(lock) is True

    def test_lock_result_is_truthy_when_acquired(self, tmp_path):
        lock_file = tmp_path / "test.lock"
        with InstanceLock(path=lock_file) as lock:
            assert lock  # implicit bool

    def test_lock_creates_file(self, tmp_path):
        lock_file = tmp_path / "test.lock"
        with InstanceLock(path=lock_file):
            assert lock_file.exists()

    def test_lock_creates_parent_directory(self, tmp_path):
        lock_file = tmp_path / "nested" / "dir" / "test.lock"
        with InstanceLock(path=lock_file) as lock:
            assert bool(lock) is True
            assert lock_file.parent.exists()

    def test_custom_path_works(self, tmp_path):
        custom = tmp_path / "custom.lock"
        with InstanceLock(path=custom) as lock:
            assert bool(lock) is True


# ---------------------------------------------------------------------------
# Contention — second lock on the same file
# ---------------------------------------------------------------------------

class TestInstanceLockContention:
    def test_second_lock_not_acquired_while_first_held(self, tmp_path):
        lock_file = tmp_path / "test.lock"
        with InstanceLock(path=lock_file) as first:
            assert bool(first) is True
            # Same process, same file — fcntl re-entrancy on some platforms
            # would allow this, but msvcrt won't.  We test via a subprocess
            # to guarantee cross-platform correctness.
            q: multiprocessing.Queue = multiprocessing.Queue()
            p = multiprocessing.Process(target=_try_acquire, args=(lock_file, q))
            p.start()
            acquired_in_child = q.get(timeout=5)
            q.put("done")  # signal child to exit
            p.join(timeout=5)
            assert acquired_in_child is False

    def test_second_lock_acquired_after_first_released(self, tmp_path):
        lock_file = tmp_path / "test.lock"
        # First context exits, releasing the lock
        with InstanceLock(path=lock_file) as first:
            assert bool(first) is True
        # Second context should now succeed
        with InstanceLock(path=lock_file) as second:
            assert bool(second) is True


# ---------------------------------------------------------------------------
# Release behaviour
# ---------------------------------------------------------------------------

class TestInstanceLockRelease:
    def test_lock_released_on_normal_exit(self, tmp_path):
        lock_file = tmp_path / "test.lock"
        with InstanceLock(path=lock_file):
            pass
        # After context exits the same path should be acquirable again
        with InstanceLock(path=lock_file) as lock:
            assert bool(lock) is True

    def test_lock_released_when_exception_raised_inside_block(self, tmp_path):
        lock_file = tmp_path / "test.lock"
        try:
            with InstanceLock(path=lock_file):
                raise RuntimeError("something went wrong")
        except RuntimeError:
            pass
        # Lock must have been released by __exit__ despite the exception
        with InstanceLock(path=lock_file) as lock:
            assert bool(lock) is True

    def test_lock_not_held_after_context_exits(self, tmp_path):
        """Verify via a subprocess that the lock is truly free after exit."""
        lock_file = tmp_path / "test.lock"
        with InstanceLock(path=lock_file):
            pass

        q: multiprocessing.Queue = multiprocessing.Queue()
        p = multiprocessing.Process(target=_try_acquire, args=(lock_file, q))
        p.start()
        acquired_in_child = q.get(timeout=5)
        q.put("done")
        p.join(timeout=5)
        assert acquired_in_child is True


# ---------------------------------------------------------------------------
# _LockResult truth-value
# ---------------------------------------------------------------------------

class TestLockResult:
    def test_acquired_lock_is_truthy(self, tmp_path):
        with InstanceLock(path=tmp_path / "a.lock") as lock:
            assert bool(lock) is True

    def test_failed_lock_is_falsy(self, tmp_path):
        lock_file = tmp_path / "b.lock"
        with InstanceLock(path=lock_file):
            q: multiprocessing.Queue = multiprocessing.Queue()
            p = multiprocessing.Process(target=_try_acquire, args=(lock_file, q))
            p.start()
            result = q.get(timeout=5)
            q.put("done")
            p.join(timeout=5)
            assert result is False
