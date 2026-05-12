"""
lock.py — Cross-platform single-instance lock for DeskGhost.

Acquires an exclusive OS-level file lock on ~/.deskghost/deskghost.lock.
If the lock is already held by a running process the caller gets back a
``LockHeld`` instance (truthy-false) and should exit immediately.

Usage::

    with InstanceLock() as lock:
        if not lock:
            log.info("DeskGhost already running, exiting.")
            return 0
        # ... rest of main ...

The lock is an OS advisory file lock, NOT a PID file.  This means:
- No stale-lock cleanup needed: the OS releases the lock automatically
  when the holding process dies (crash, kill, reboot, etc.).
- Works correctly when the machine wakes from sleep with the original
  process still alive (lock still held → new instance exits immediately).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import TracebackType
from typing import IO, Optional

_LOCK_DIR = Path.home() / ".deskghost"
_LOCK_FILE = _LOCK_DIR / "deskghost.lock"


class _LockResult:
    """Returned by ``InstanceLock.__enter__``.  Evaluates to bool."""

    def __init__(self, acquired: bool, pid: Optional[int] = None) -> None:
        self._acquired = acquired
        self.pid = pid  # PID of the already-running instance when acquired=False

    def __bool__(self) -> bool:
        return self._acquired


class InstanceLock:
    """Context manager that holds an exclusive file lock for the process lifetime."""

    def __init__(self, path: Path = _LOCK_FILE) -> None:
        self._path = path
        self._fh: Optional[IO[bytes]] = None

    def __enter__(self) -> _LockResult:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fh = open(self._path, "wb")  # noqa: WPS515
            _acquire_exclusive(self._fh)
            # Store our PID so other instances can read it
            self._fh.write(str(os.getpid()).encode())
            self._fh.flush()
            return _LockResult(True)
        except OSError:
            # Lock is held by another process — try to read its PID
            if self._fh is not None:
                self._fh.close()
                self._fh = None
            existing_pid: Optional[int] = None
            try:
                raw = self._path.read_text().strip()
                if raw.isdigit():
                    existing_pid = int(raw)
            except OSError:
                pass
            return _LockResult(False, pid=existing_pid)

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        if self._fh is not None:
            _release(self._fh)
            self._fh.close()
            self._fh = None


# ── Platform-specific lock primitives ─────────────────────────────────────────

if sys.platform == "win32":
    import msvcrt

    def _acquire_exclusive(fh: IO[bytes]) -> None:
        """Non-blocking exclusive lock via msvcrt.locking (Windows)."""
        # LK_NBLCK raises OSError immediately if the lock cannot be obtained.
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]

    def _release(fh: IO[bytes]) -> None:
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]

else:
    import fcntl

    def _acquire_exclusive(fh: IO[bytes]) -> None:
        """Non-blocking exclusive lock via fcntl.flock (macOS / Linux)."""
        # LOCK_EX | LOCK_NB raises OSError(EWOULDBLOCK) if already locked.
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _release(fh: IO[bytes]) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
