"""Tests for deskghost.macos.watcher — skipped on non-macOS platforms."""

import sys
import time
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="macOS watcher tests only run on macOS",
)


# ---------------------------------------------------------------------------
# Helpers — build a fake Quartz module before importing the watcher
# ---------------------------------------------------------------------------

def _make_fake_quartz(idle_seconds: float = 0.0):
    fake = MagicMock()
    # Constants used by the module
    fake.kCGEventSourceStateHIDSystemState = 1
    fake.kCGAnyInputEventType = 0xFFFFFFFF
    fake.kCGEventMouseMoved = 5
    fake.kCGMouseButtonLeft = 0
    fake.kCGHIDEventTap = 0

    # Idle-time query
    fake.CGEventSourceSecondsSinceLastEventType.return_value = idle_seconds

    # CGEvent creation / location / post — return fresh MagicMocks each call
    fake.CGEventCreate.return_value = MagicMock()
    fake.CGEventGetLocation.return_value = MagicMock()  # a CGPoint stand-in
    fake.CGEventCreateMouseEvent.return_value = MagicMock()
    fake.CGEventPost.return_value = None

    return fake


def _import_watcher(fake_quartz):
    """Import ActivityWatcher with the given fake Quartz module."""
    with patch.dict(sys.modules, {"Quartz": fake_quartz}):
        if "deskghost.macos.watcher" in sys.modules:
            del sys.modules["deskghost.macos.watcher"]
        from deskghost.macos.watcher import ActivityWatcher
        return ActivityWatcher


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------

class TestActivityWatcherInit:
    def test_init_caffeinate_is_none(self):
        w = _import_watcher(_make_fake_quartz())()
        assert w._caffeinate_proc is None

    def test_init_reset_time_is_none(self):
        w = _import_watcher(_make_fake_quartz())()
        assert w._reset_time is None

    def test_init_idle_time_reads_from_quartz(self):
        w = _import_watcher(_make_fake_quartz(idle_seconds=5.0))()
        assert w.get_idle_time() == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# get_idle_time / reset_idle
# ---------------------------------------------------------------------------

class TestIdleTracking:
    def test_get_idle_time_returns_hid_value_when_no_reset(self):
        w = _import_watcher(_make_fake_quartz(idle_seconds=42.0))()
        assert w.get_idle_time() == pytest.approx(42.0)

    def test_get_idle_time_uses_reset_time_when_smaller(self):
        w = _import_watcher(_make_fake_quartz(idle_seconds=3600.0))()
        w.reset_idle()
        # time_since_reset ~0 << 3600 → get_idle_time() ~0
        assert w.get_idle_time() < 1.0

    def test_get_idle_time_uses_hid_when_smaller_than_since_reset(self):
        w = _import_watcher(_make_fake_quartz(idle_seconds=5.0))()
        # Push reset_time far into the past so time_since_reset >> hid_idle
        w._reset_time = time.time() - 3600
        assert w.get_idle_time() == pytest.approx(5.0)

    def test_reset_idle_sets_reset_time(self):
        w = _import_watcher(_make_fake_quartz())()
        before = time.time()
        w.reset_idle()
        after = time.time()
        assert before <= w._reset_time <= after

    def test_reset_idle_makes_idle_time_near_zero(self):
        w = _import_watcher(_make_fake_quartz(idle_seconds=120.0))()
        w.reset_idle()
        assert w.get_idle_time() < 1.0


# ---------------------------------------------------------------------------
# nudge_mouse — Caffeine-style zero-movement CGEvent
# ---------------------------------------------------------------------------

class TestNudgeMouse:
    def test_nudge_creates_cgevent_source(self):
        fake_quartz = _make_fake_quartz()
        w = _import_watcher(fake_quartz)()
        w.nudge_mouse()
        fake_quartz.CGEventCreate.assert_called_once_with(None)

    def test_nudge_reads_current_cursor_position(self):
        fake_quartz = _make_fake_quartz()
        src_event = MagicMock()
        fake_quartz.CGEventCreate.return_value = src_event
        w = _import_watcher(fake_quartz)()
        w.nudge_mouse()
        fake_quartz.CGEventGetLocation.assert_called_once_with(src_event)

    def test_nudge_creates_mouse_moved_event_at_current_position(self):
        fake_quartz = _make_fake_quartz()
        pos = MagicMock(name="pos")
        fake_quartz.CGEventGetLocation.return_value = pos
        w = _import_watcher(fake_quartz)()
        w.nudge_mouse()
        fake_quartz.CGEventCreateMouseEvent.assert_called_once_with(
            None,
            fake_quartz.kCGEventMouseMoved,
            pos,
            fake_quartz.kCGMouseButtonLeft,
        )

    def test_nudge_posts_event_to_hid_tap(self):
        fake_quartz = _make_fake_quartz()
        move_event = MagicMock(name="move_event")
        fake_quartz.CGEventCreateMouseEvent.return_value = move_event
        w = _import_watcher(fake_quartz)()
        w.nudge_mouse()
        fake_quartz.CGEventPost.assert_called_once_with(
            fake_quartz.kCGHIDEventTap, move_event
        )

    def test_nudge_does_not_alter_cursor_position(self):
        """nudge_mouse() must not call any function that moves the cursor."""
        fake_quartz = _make_fake_quartz()
        w = _import_watcher(fake_quartz)()
        w.nudge_mouse()
        # Ensure no CGWarpMouseCursorPosition or similar was called
        assert not fake_quartz.CGWarpMouseCursorPosition.called

    def test_nudge_can_be_called_multiple_times(self):
        fake_quartz = _make_fake_quartz()
        w = _import_watcher(fake_quartz)()
        for _ in range(5):
            w.nudge_mouse()
        assert fake_quartz.CGEventPost.call_count == 5


# ---------------------------------------------------------------------------
# prevent / allow display sleep
# ---------------------------------------------------------------------------

class TestDisplaySleep:
    def test_prevent_display_sleep_starts_caffeinate(self):
        fake_quartz = _make_fake_quartz()
        Watcher = _import_watcher(fake_quartz)
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_popen.return_value = mock_proc
            w = Watcher()
            w.prevent_display_sleep()
            mock_popen.assert_called_once()
            args = mock_popen.call_args[0][0]
            assert args[0] == "caffeinate"
            assert "-d" in args

    def test_prevent_display_sleep_does_not_restart_if_already_running(self):
        fake_quartz = _make_fake_quartz()
        Watcher = _import_watcher(fake_quartz)
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None  # still alive
            mock_popen.return_value = mock_proc
            w = Watcher()
            w.prevent_display_sleep()
            w.prevent_display_sleep()
            assert mock_popen.call_count == 1

    def test_allow_display_sleep_terminates_caffeinate(self):
        fake_quartz = _make_fake_quartz()
        w = _import_watcher(fake_quartz)()
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        w._caffeinate_proc = mock_proc
        w.allow_display_sleep()
        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called_once()
        assert w._caffeinate_proc is None

    def test_allow_display_sleep_no_op_when_none(self):
        w = _import_watcher(_make_fake_quartz())()
        w.allow_display_sleep()  # must not raise


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------

class TestCleanup:
    def test_cleanup_terminates_caffeinate(self):
        w = _import_watcher(_make_fake_quartz())()
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        w._caffeinate_proc = mock_proc
        w.cleanup()
        mock_proc.terminate.assert_called_once()

    def test_cleanup_without_caffeinate_is_safe(self):
        w = _import_watcher(_make_fake_quartz())()
        w.cleanup()  # must not raise
