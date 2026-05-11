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
# Helpers — build fake pyautogui / Quartz before importing the module
# ---------------------------------------------------------------------------

SCREEN_W, SCREEN_H = 1920, 1080


def _make_fake_pyautogui(pos=(500, 400)):
    fake = MagicMock()
    fake.size.return_value = (SCREEN_W, SCREEN_H)
    fake.position.return_value = pos
    return fake


def _make_fake_quartz(idle_seconds=0.0):
    fake = MagicMock()
    fake.kCGEventSourceStateHIDSystemState = 1
    fake.kCGAnyInputEventType = 0xFFFFFFFF
    fake.CGEventSourceSecondsSinceLastEventType.return_value = idle_seconds
    return fake


def _import_watcher(fake_pyautogui, fake_quartz):
    """Import ActivityWatcher with patched external modules."""
    with patch.dict(
        sys.modules,
        {
            "pyautogui": fake_pyautogui,
            "Quartz": fake_quartz,
        },
    ):
        # Force re-import so module-level size() call uses our fake
        if "deskghost.macos.watcher" in sys.modules:
            del sys.modules["deskghost.macos.watcher"]
        from deskghost.macos.watcher import ActivityWatcher
        return ActivityWatcher


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------

class TestActivityWatcherInit:
    def test_init_caffeinate_is_none(self):
        fake_pyautogui = _make_fake_pyautogui()
        fake_quartz = _make_fake_quartz()
        Watcher = _import_watcher(fake_pyautogui, fake_quartz)
        w = Watcher()
        assert w._caffeinate_proc is None

    def test_init_reset_time_is_none(self):
        fake_pyautogui = _make_fake_pyautogui()
        fake_quartz = _make_fake_quartz()
        Watcher = _import_watcher(fake_pyautogui, fake_quartz)
        w = Watcher()
        assert w._reset_time is None

    def test_init_idle_time_reads_from_quartz(self):
        fake_pyautogui = _make_fake_pyautogui()
        fake_quartz = _make_fake_quartz(idle_seconds=5.0)
        Watcher = _import_watcher(fake_pyautogui, fake_quartz)
        w = Watcher()
        assert w.get_idle_time() == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# get_idle_time / reset_idle
# ---------------------------------------------------------------------------

class TestIdleTracking:
    def test_get_idle_time_returns_hid_value_when_no_reset(self):
        fake_pyautogui = _make_fake_pyautogui()
        fake_quartz = _make_fake_quartz(idle_seconds=42.0)
        Watcher = _import_watcher(fake_pyautogui, fake_quartz)
        w = Watcher()
        assert w.get_idle_time() == pytest.approx(42.0)

    def test_get_idle_time_uses_reset_time_when_smaller(self):
        fake_pyautogui = _make_fake_pyautogui()
        fake_quartz = _make_fake_quartz(idle_seconds=3600.0)
        Watcher = _import_watcher(fake_pyautogui, fake_quartz)
        w = Watcher()
        w.reset_idle()
        # time_since_reset ~0 < 3600, so get_idle_time() ~0
        assert w.get_idle_time() < 1.0

    def test_get_idle_time_uses_hid_when_smaller_than_since_reset(self):
        fake_pyautogui = _make_fake_pyautogui()
        fake_quartz = _make_fake_quartz(idle_seconds=5.0)
        Watcher = _import_watcher(fake_pyautogui, fake_quartz)
        w = Watcher()
        # Set reset_time far in the past so time_since_reset >> hid_idle
        w._reset_time = time.time() - 3600
        assert w.get_idle_time() == pytest.approx(5.0)

    def test_reset_idle_sets_reset_time(self):
        fake_pyautogui = _make_fake_pyautogui()
        fake_quartz = _make_fake_quartz()
        Watcher = _import_watcher(fake_pyautogui, fake_quartz)
        w = Watcher()
        before = time.time()
        w.reset_idle()
        after = time.time()
        assert before <= w._reset_time <= after

    def test_reset_idle_makes_idle_time_near_zero(self):
        fake_pyautogui = _make_fake_pyautogui()
        fake_quartz = _make_fake_quartz(idle_seconds=120.0)
        Watcher = _import_watcher(fake_pyautogui, fake_quartz)
        w = Watcher()
        w.reset_idle()
        assert w.get_idle_time() < 1.0


# ---------------------------------------------------------------------------
# nudge_mouse
# ---------------------------------------------------------------------------

class TestNudgeMouse:
    def test_nudge_calls_moveto_twice(self):
        origin = (500, 400)
        fake_pyautogui = _make_fake_pyautogui(pos=origin)
        fake_quartz = _make_fake_quartz()
        Watcher = _import_watcher(fake_pyautogui, fake_quartz)
        w = Watcher()
        w.nudge_mouse()
        assert fake_pyautogui.moveTo.call_count == 2

    def test_nudge_returns_to_origin(self):
        origin = (500, 400)
        fake_pyautogui = _make_fake_pyautogui(pos=origin)
        fake_quartz = _make_fake_quartz()
        Watcher = _import_watcher(fake_pyautogui, fake_quartz)
        w = Watcher()
        w.nudge_mouse()
        last_call = fake_pyautogui.moveTo.call_args_list[-1]
        assert last_call[0][0] == origin[0]
        assert last_call[0][1] == origin[1]

    def test_nudge_target_clamped_to_screen_bounds(self):
        # Place cursor at top-left corner; nudge offset will be clamped to >= 0
        origin = (0, 0)
        fake_pyautogui = _make_fake_pyautogui(pos=origin)
        fake_quartz = _make_fake_quartz()
        Watcher = _import_watcher(fake_pyautogui, fake_quartz)
        w = Watcher()
        for _ in range(20):
            w.nudge_mouse()
            first_call = fake_pyautogui.moveTo.call_args_list[0]
            tx, ty = first_call[0][0], first_call[0][1]
            assert 0 <= tx < SCREEN_W
            assert 0 <= ty < SCREEN_H
            fake_pyautogui.moveTo.reset_mock()


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------

class TestCleanup:
    def test_cleanup_terminates_caffeinate(self):
        fake_pyautogui = _make_fake_pyautogui()
        fake_quartz = _make_fake_quartz()
        Watcher = _import_watcher(fake_pyautogui, fake_quartz)
        w = Watcher()
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        w._caffeinate_proc = mock_proc
        w.cleanup()
        mock_proc.terminate.assert_called_once()

    def test_cleanup_without_caffeinate_is_safe(self):
        fake_pyautogui = _make_fake_pyautogui()
        fake_quartz = _make_fake_quartz()
        Watcher = _import_watcher(fake_pyautogui, fake_quartz)
        w = Watcher()
        # Should not raise when no caffeinate process was started
        w.cleanup()
