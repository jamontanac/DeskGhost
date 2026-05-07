"""Tests for deskghost.macos.watcher — skipped on non-macOS platforms."""

import sys
import time
from unittest.mock import MagicMock, call, patch

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="macOS watcher tests only run on macOS",
)


# ---------------------------------------------------------------------------
# Helpers — build fake pyautogui / pynput before importing the module
# ---------------------------------------------------------------------------

SCREEN_W, SCREEN_H = 1920, 1080


def _make_fake_pyautogui(pos=(500, 400)):
    fake = MagicMock()
    fake.size.return_value = (SCREEN_W, SCREEN_H)
    fake.position.return_value = pos
    return fake


def _make_fake_pynput():
    listener_instance = MagicMock()
    listener_cls = MagicMock(return_value=listener_instance)
    pynput = MagicMock()
    pynput.mouse.Listener = listener_cls
    pynput.keyboard.Listener = listener_cls
    return pynput, listener_instance


def _import_watcher(fake_pyautogui, fake_pynput):
    """Import ActivityWatcher with patched external modules."""
    with patch.dict(
        sys.modules,
        {
            "pyautogui": fake_pyautogui,
            "pynput": fake_pynput,
            "pynput.mouse": fake_pynput.mouse,
            "pynput.keyboard": fake_pynput.keyboard,
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
    def test_init_starts_mouse_listener(self):
        fake_pyautogui = _make_fake_pyautogui()
        fake_pynput, listener_instance = _make_fake_pynput()
        Watcher = _import_watcher(fake_pyautogui, fake_pynput)
        Watcher()
        listener_instance.start.assert_called()

    def test_init_starts_keyboard_listener(self):
        fake_pyautogui = _make_fake_pyautogui()
        fake_pynput, listener_instance = _make_fake_pynput()
        Watcher = _import_watcher(fake_pyautogui, fake_pynput)
        Watcher()
        # start() should be called at least twice (mouse + keyboard)
        assert listener_instance.start.call_count >= 2

    def test_init_idle_time_is_near_zero(self):
        fake_pyautogui = _make_fake_pyautogui()
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_pyautogui, fake_pynput)
        w = Watcher()
        assert w.get_idle_time() < 1.0


# ---------------------------------------------------------------------------
# get_idle_time / reset_idle
# ---------------------------------------------------------------------------

class TestIdleTracking:
    def test_get_idle_time_increases_over_time(self):
        fake_pyautogui = _make_fake_pyautogui()
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_pyautogui, fake_pynput)
        w = Watcher()
        w.last_activity_time = time.time() - 30
        assert w.get_idle_time() >= 30

    def test_reset_idle_resets_timer(self):
        fake_pyautogui = _make_fake_pyautogui()
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_pyautogui, fake_pynput)
        w = Watcher()
        w.last_activity_time = time.time() - 120
        w.reset_idle()
        assert w.get_idle_time() < 1.0

    def test_on_activity_updates_last_activity_time(self):
        fake_pyautogui = _make_fake_pyautogui()
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_pyautogui, fake_pynput)
        w = Watcher()
        w.last_activity_time = time.time() - 60
        w._on_activity()
        assert w.get_idle_time() < 1.0

    def test_on_activity_ignored_while_bot_moving(self):
        fake_pyautogui = _make_fake_pyautogui()
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_pyautogui, fake_pynput)
        w = Watcher()
        old_time = time.time() - 60
        w.last_activity_time = old_time
        w._bot_moving = True
        w._on_activity()
        assert w.last_activity_time == old_time


# ---------------------------------------------------------------------------
# nudge_mouse
# ---------------------------------------------------------------------------

class TestNudgeMouse:
    def test_nudge_calls_moveto_twice(self):
        origin = (500, 400)
        fake_pyautogui = _make_fake_pyautogui(pos=origin)
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_pyautogui, fake_pynput)
        w = Watcher()
        w.nudge_mouse()
        assert fake_pyautogui.moveTo.call_count == 2

    def test_nudge_returns_to_origin(self):
        origin = (500, 400)
        fake_pyautogui = _make_fake_pyautogui(pos=origin)
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_pyautogui, fake_pynput)
        w = Watcher()
        w.nudge_mouse()
        # Second moveTo call should be back to origin
        last_call = fake_pyautogui.moveTo.call_args_list[-1]
        assert last_call[0][0] == origin[0]
        assert last_call[0][1] == origin[1]

    def test_nudge_target_clamped_to_screen_bounds(self):
        # Place cursor at top-left corner; nudge offset will be clamped to >= 0
        origin = (0, 0)
        fake_pyautogui = _make_fake_pyautogui(pos=origin)
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_pyautogui, fake_pynput)
        w = Watcher()
        for _ in range(20):
            w.nudge_mouse()
            first_call = fake_pyautogui.moveTo.call_args_list[0]
            tx, ty = first_call[0][0], first_call[0][1]
            assert 0 <= tx < SCREEN_W
            assert 0 <= ty < SCREEN_H
            fake_pyautogui.moveTo.reset_mock()

    def test_nudge_bot_moving_flag_reset_after_nudge(self):
        fake_pyautogui = _make_fake_pyautogui()
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_pyautogui, fake_pynput)
        w = Watcher()
        w.nudge_mouse()
        assert w._bot_moving is False

    def test_nudge_bot_moving_flag_reset_even_on_exception(self):
        origin = (500, 400)
        fake_pyautogui = _make_fake_pyautogui(pos=origin)
        fake_pyautogui.moveTo.side_effect = RuntimeError("boom")
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_pyautogui, fake_pynput)
        w = Watcher()
        with pytest.raises(RuntimeError):
            w.nudge_mouse()
        assert w._bot_moving is False


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------

class TestCleanup:
    def test_cleanup_stops_mouse_listener(self):
        fake_pyautogui = _make_fake_pyautogui()
        fake_pynput, listener_instance = _make_fake_pynput()
        Watcher = _import_watcher(fake_pyautogui, fake_pynput)
        w = Watcher()
        w.cleanup()
        listener_instance.stop.assert_called()

    def test_cleanup_stops_keyboard_listener(self):
        fake_pyautogui = _make_fake_pyautogui()
        fake_pynput, listener_instance = _make_fake_pynput()
        Watcher = _import_watcher(fake_pyautogui, fake_pynput)
        w = Watcher()
        w.cleanup()
        assert listener_instance.stop.call_count >= 2
