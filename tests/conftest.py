"""Shared fixtures for the deskghost test suite."""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _make_localtime(weekday: int, hour: int, minute: int):
    """Return a ``time.struct_time`` fixed at the given weekday/hour/minute."""
    return time.struct_time((2024, 1, weekday + 1, hour, minute, 0, weekday, 1, 0))


@pytest.fixture
def freeze_time(monkeypatch):
    """Fixture that patches ``time.localtime`` and ``time.time``.

    Usage::

        def test_something(freeze_time):
            freeze_time(weekday=0, hour=9, minute=0, timestamp=1000.0)
    """
    def _freeze(weekday: int = 0, hour: int = 9, minute: int = 0, timestamp: float = 1000.0):
        struct = _make_localtime(weekday, hour, minute)
        monkeypatch.setattr("time.localtime", lambda *_: struct)
        monkeypatch.setattr("time.time", lambda: timestamp)

    return _freeze


# ---------------------------------------------------------------------------
# Fake ActivityWatcher
# ---------------------------------------------------------------------------

class FakeWatcher:
    """Drop-in replacement for any platform ActivityWatcher."""

    def __init__(self):
        self.nudge_calls = 0
        self.reset_calls = 0
        self.cleanup_calls = 0
        self._idle_time = 0.0

    def set_idle_time(self, seconds: float) -> None:
        self._idle_time = seconds

    def get_idle_time(self) -> float:
        return self._idle_time

    def nudge_mouse(self) -> None:
        self.nudge_calls += 1

    def reset_idle(self) -> None:
        self.reset_calls += 1

    def cleanup(self) -> None:
        self.cleanup_calls += 1


@pytest.fixture
def fake_watcher():
    """Return a fresh FakeWatcher instance."""
    return FakeWatcher()


# ---------------------------------------------------------------------------
# Fake pynput listeners (used by platform watcher tests)
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_pynput():
    """Return a MagicMock that stands in for the pynput module."""
    listener_instance = MagicMock()
    listener_cls = MagicMock(return_value=listener_instance)

    pynput = MagicMock()
    pynput.mouse.Listener = listener_cls
    pynput.keyboard.Listener = listener_cls
    return pynput
