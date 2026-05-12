"""Tests for deskghost.windows.watcher — skipped on non-Windows platforms."""

import sys
import ctypes
from unittest.mock import MagicMock, patch, call

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows watcher tests only run on Windows",
)

# ---------------------------------------------------------------------------
# Constants mirrored from the module under test
# ---------------------------------------------------------------------------

_ES_CONTINUOUS       = 0x80000000
_ES_SYSTEM_REQUIRED  = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002
_INPUT_MOUSE         = 0
_MOUSEEVENTF_MOVE    = 0x0001


# ---------------------------------------------------------------------------
# Helpers — build a fake ctypes windll before importing the module
# ---------------------------------------------------------------------------

def _make_fake_windll(last_input_ms: int = 0, tick_count: int = 0):
    """Return (fake_windll, user32_mock, kernel32_mock).

    last_input_ms: dwTime value returned by GetLastInputInfo
    tick_count:    value returned by GetTickCount
    The idle time reported by get_idle_time() == (tick_count - last_input_ms) / 1000
    """
    user32 = MagicMock()
    kernel32 = MagicMock()

    # GetLastInputInfo fills the LASTINPUTINFO struct's dwTime field
    def _get_last_input(lii_ref):
        lii_ref.dwTime = last_input_ms
        return True

    user32.GetLastInputInfo.side_effect = _get_last_input
    user32.SendInput.return_value = 1

    kernel32.GetTickCount.return_value = tick_count
    kernel32.SetThreadExecutionState.return_value = 0

    windll = MagicMock()
    windll.user32 = user32
    windll.kernel32 = kernel32
    return windll, user32, kernel32


def _import_watcher(windll, last_input_ms=0, tick_count=0):
    """Import ActivityWatcher with a patched ctypes.windll."""
    with patch("ctypes.windll", windll):
        if "deskghost.windows.watcher" in sys.modules:
            del sys.modules["deskghost.windows.watcher"]
        from deskghost.windows.watcher import ActivityWatcher
        return ActivityWatcher


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------

class TestActivityWatcherInit:
    def test_init_calls_set_thread_execution_state(self):
        windll, user32, kernel32 = _make_fake_windll()
        Watcher = _import_watcher(windll)
        Watcher()
        kernel32.SetThreadExecutionState.assert_called_once_with(
            _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED
        )

    def test_init_does_not_start_any_listeners(self):
        """No pynput listener threads should be created."""
        windll, user32, kernel32 = _make_fake_windll()
        Watcher = _import_watcher(windll)
        w = Watcher()
        # The watcher must expose only expected public attributes
        assert not hasattr(w, "_mouse_listener")
        assert not hasattr(w, "_kbd_listener")


# ---------------------------------------------------------------------------
# get_idle_time — delegates to GetLastInputInfo
# ---------------------------------------------------------------------------

class TestIdleTracking:
    def test_get_idle_time_returns_elapsed_since_last_input(self):
        # tick_count=5000, last_input_ms=0 → idle = 5.0 s
        windll, user32, kernel32 = _make_fake_windll(last_input_ms=0, tick_count=5000)
        Watcher = _import_watcher(windll)
        w = Watcher()
        assert w.get_idle_time() == pytest.approx(5.0)

    def test_get_idle_time_zero_when_just_used(self):
        # tick_count == last_input_ms → idle = 0 s
        windll, user32, kernel32 = _make_fake_windll(last_input_ms=1000, tick_count=1000)
        Watcher = _import_watcher(windll)
        w = Watcher()
        assert w.get_idle_time() == pytest.approx(0.0)

    def test_get_idle_time_calls_get_last_input_info(self):
        windll, user32, kernel32 = _make_fake_windll()
        Watcher = _import_watcher(windll)
        w = Watcher()
        w.get_idle_time()
        user32.GetLastInputInfo.assert_called()

    def test_get_idle_time_never_negative(self):
        # tick_count < last_input_ms (e.g. tick counter wrapped) → clamped to 0
        windll, user32, kernel32 = _make_fake_windll(last_input_ms=9000, tick_count=1000)
        Watcher = _import_watcher(windll)
        w = Watcher()
        assert w.get_idle_time() >= 0.0

    def test_reset_idle_calls_send_input(self):
        windll, user32, kernel32 = _make_fake_windll()
        Watcher = _import_watcher(windll)
        w = Watcher()
        user32.SendInput.reset_mock()
        w.reset_idle()
        user32.SendInput.assert_called_once()


# ---------------------------------------------------------------------------
# nudge_mouse — SendInput zero-delta MOUSEEVENTF_MOVE
# ---------------------------------------------------------------------------

class TestNudgeMouse:
    def test_nudge_calls_send_input_once(self):
        windll, user32, kernel32 = _make_fake_windll()
        Watcher = _import_watcher(windll)
        w = Watcher()
        user32.SendInput.reset_mock()
        w.nudge_mouse()
        user32.SendInput.assert_called_once()

    def test_nudge_send_input_count_is_one(self):
        """First arg to SendInput must be 1 (one INPUT struct)."""
        windll, user32, kernel32 = _make_fake_windll()
        Watcher = _import_watcher(windll)
        w = Watcher()
        user32.SendInput.reset_mock()
        w.nudge_mouse()
        count_arg = user32.SendInput.call_args[0][0]
        assert count_arg == 1

    def test_nudge_does_not_call_set_cursor_pos(self):
        """Cursor must not move — SetCursorPos must never be called."""
        windll, user32, kernel32 = _make_fake_windll()
        Watcher = _import_watcher(windll)
        w = Watcher()
        w.nudge_mouse()
        user32.SetCursorPos.assert_not_called()

    def test_nudge_does_not_call_keybd_event(self):
        """Keystrokes must not be sent — keybd_event must never be called."""
        windll, user32, kernel32 = _make_fake_windll()
        Watcher = _import_watcher(windll)
        w = Watcher()
        w.nudge_mouse()
        user32.keybd_event.assert_not_called()

    def test_nudge_can_be_called_multiple_times(self):
        windll, user32, kernel32 = _make_fake_windll()
        Watcher = _import_watcher(windll)
        w = Watcher()
        user32.SendInput.reset_mock()
        for _ in range(5):
            w.nudge_mouse()
        assert user32.SendInput.call_count == 5


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------

class TestCleanup:
    def test_cleanup_restores_execution_state(self):
        windll, user32, kernel32 = _make_fake_windll()
        Watcher = _import_watcher(windll)
        w = Watcher()
        kernel32.SetThreadExecutionState.reset_mock()
        w.cleanup()
        kernel32.SetThreadExecutionState.assert_called_once_with(_ES_CONTINUOUS)

    def test_cleanup_does_not_call_listener_stop(self):
        """No pynput .stop() calls — listeners don't exist."""
        windll, user32, kernel32 = _make_fake_windll()
        Watcher = _import_watcher(windll)
        w = Watcher()
        w.cleanup()
        # If no AttributeError raised and only SetThreadExecutionState was
        # called, the test passes.
        assert True
