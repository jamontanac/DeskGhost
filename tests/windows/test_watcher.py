"""Tests for deskghost.windows.watcher — skipped on non-Windows platforms."""

import sys
import time
from unittest.mock import MagicMock, call, patch

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows watcher tests only run on Windows",
)

# ---------------------------------------------------------------------------
# Helpers — build fake ctypes / pynput before importing the module
# ---------------------------------------------------------------------------

SCREEN_W, SCREEN_H = 1920, 1080
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002
_VK_CTRL        = 0x11
_VK_SHIFT       = 0x10
_VK_ALT         = 0x12
_VK_SCROLL_LOCK = 0x91
_VK_F13         = 0x7C
_VK_F14         = 0x7D
_VK_F15         = 0x7E
_SAFE_KEYS      = [_VK_CTRL, _VK_SHIFT, _VK_ALT, _VK_SCROLL_LOCK, _VK_F13, _VK_F14, _VK_F15]
_KEYEVENTF_KEYUP = 0x0002


def _make_fake_ctypes(cursor_pos=(500, 400)):
    """Build a fake ctypes module with controllable user32/kernel32."""
    user32 = MagicMock()
    kernel32 = MagicMock()

    # GetSystemMetrics returns screen dimensions
    user32.GetSystemMetrics.side_effect = lambda idx: SCREEN_W if idx == 0 else SCREEN_H

    # GetCursorPos fills the POINT structure passed by reference
    def _get_cursor_pos(point_ref):
        point_ref.x = cursor_pos[0]
        point_ref.y = cursor_pos[1]

    user32.GetCursorPos.side_effect = _get_cursor_pos

    windll = MagicMock()
    windll.user32 = user32
    windll.kernel32 = kernel32

    fake_ctypes = MagicMock()
    fake_ctypes.windll = windll
    # Make Structure and c_long passthrough so _POINT can be defined
    fake_ctypes.Structure = object
    fake_ctypes.c_long = int
    fake_ctypes.c_int = int

    return fake_ctypes, user32, kernel32


def _make_fake_pynput():
    listener_instance = MagicMock()
    listener_cls = MagicMock(return_value=listener_instance)
    pynput = MagicMock()
    pynput.mouse.Listener = listener_cls
    pynput.keyboard.Listener = listener_cls
    return pynput, listener_instance


def _import_watcher(fake_ctypes, fake_pynput):
    with patch.dict(
        sys.modules,
        {
            "ctypes": fake_ctypes,
            "pynput": fake_pynput,
            "pynput.mouse": fake_pynput.mouse,
            "pynput.keyboard": fake_pynput.keyboard,
        },
    ):
        if "deskghost.windows.watcher" in sys.modules:
            del sys.modules["deskghost.windows.watcher"]
        from deskghost.windows.watcher import ActivityWatcher
        return ActivityWatcher


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------

class TestActivityWatcherInit:
    def test_init_calls_set_thread_execution_state(self):
        fake_ctypes, user32, kernel32 = _make_fake_ctypes()
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_ctypes, fake_pynput)
        Watcher()
        kernel32.SetThreadExecutionState.assert_called_once_with(
            _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED
        )

    def test_init_starts_listeners(self):
        fake_ctypes, _, _ = _make_fake_ctypes()
        fake_pynput, listener_instance = _make_fake_pynput()
        Watcher = _import_watcher(fake_ctypes, fake_pynput)
        Watcher()
        assert listener_instance.start.call_count >= 2

    def test_init_idle_time_is_near_zero(self):
        fake_ctypes, _, _ = _make_fake_ctypes()
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_ctypes, fake_pynput)
        w = Watcher()
        assert w.get_idle_time() < 1.0


# ---------------------------------------------------------------------------
# get_idle_time / reset_idle
# ---------------------------------------------------------------------------

class TestIdleTracking:
    def test_get_idle_time_increases_over_time(self):
        fake_ctypes, _, _ = _make_fake_ctypes()
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_ctypes, fake_pynput)
        w = Watcher()
        w.last_activity_time = time.time() - 30
        assert w.get_idle_time() >= 30

    def test_reset_idle_resets_timer(self):
        fake_ctypes, _, _ = _make_fake_ctypes()
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_ctypes, fake_pynput)
        w = Watcher()
        w.last_activity_time = time.time() - 120
        w.reset_idle()
        assert w.get_idle_time() < 1.0

    def test_on_activity_updates_last_activity_time(self):
        fake_ctypes, _, _ = _make_fake_ctypes()
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_ctypes, fake_pynput)
        w = Watcher()
        w.last_activity_time = time.time() - 60
        w._on_activity()
        assert w.get_idle_time() < 1.0

    def test_on_activity_ignored_while_bot_moving(self):
        fake_ctypes, _, _ = _make_fake_ctypes()
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_ctypes, fake_pynput)
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
    def test_nudge_calls_set_cursor_pos_multiple_times(self):
        fake_ctypes, user32, _ = _make_fake_ctypes(cursor_pos=(500, 400))
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_ctypes, fake_pynput)
        w = Watcher()
        w.nudge_mouse()
        # Two linear interpolations of _MOVE_STEPS each
        assert user32.SetCursorPos.call_count >= 2

    def test_nudge_target_clamped_to_screen_bounds(self):
        # Cursor at bottom-right corner
        fake_ctypes, user32, _ = _make_fake_ctypes(cursor_pos=(SCREEN_W - 1, SCREEN_H - 1))
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_ctypes, fake_pynput)
        w = Watcher()
        for _ in range(20):
            user32.SetCursorPos.reset_mock()
            w.nudge_mouse()
            for c in user32.SetCursorPos.call_args_list:
                x, y = c[0]
                assert 0 <= x < SCREEN_W
                assert 0 <= y < SCREEN_H

    def test_nudge_bot_moving_flag_reset_after_nudge(self):
        fake_ctypes, _, _ = _make_fake_ctypes()
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_ctypes, fake_pynput)
        w = Watcher()
        w.nudge_mouse()
        assert w._bot_moving is False

    def test_nudge_bot_moving_flag_reset_on_exception(self):
        fake_ctypes, user32, _ = _make_fake_ctypes()
        user32.SetCursorPos.side_effect = OSError("boom")
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_ctypes, fake_pynput)
        w = Watcher()
        with pytest.raises(OSError):
            w.nudge_mouse()
        assert w._bot_moving is False

    def test_nudge_calls_press_random_key_when_send_keystrokes_true(self):
        fake_ctypes, user32, _ = _make_fake_ctypes()
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_ctypes, fake_pynput)
        w = Watcher()
        with patch("deskghost.windows.watcher.SEND_KEYSTROKES", True):
            w.nudge_mouse()
        # keybd_event must be called exactly twice: key-down + key-up
        assert user32.keybd_event.call_count == 2

    def test_nudge_skips_press_random_key_when_send_keystrokes_false(self):
        fake_ctypes, user32, _ = _make_fake_ctypes()
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_ctypes, fake_pynput)
        w = Watcher()
        with patch("deskghost.windows.watcher.SEND_KEYSTROKES", False):
            w.nudge_mouse()
        assert user32.keybd_event.call_count == 0


# ---------------------------------------------------------------------------
# _press_random_key
# ---------------------------------------------------------------------------

class TestPressRandomKey:
    def test_press_random_key_uses_key_from_safe_pool(self):
        fake_ctypes, user32, _ = _make_fake_ctypes()
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_ctypes, fake_pynput)
        w = Watcher()
        for _ in range(30):
            user32.keybd_event.reset_mock()
            w._press_random_key()
            down_call = user32.keybd_event.call_args_list[0]
            vk = down_call[0][0]
            assert vk in _SAFE_KEYS, f"Unexpected VK code: {hex(vk)}"

    def test_press_random_key_sends_keydown_then_keyup(self):
        fake_ctypes, user32, _ = _make_fake_ctypes()
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_ctypes, fake_pynput)
        w = Watcher()
        w._press_random_key()
        calls = user32.keybd_event.call_args_list
        assert len(calls) == 2
        # first call: dwFlags == 0 (key down)
        assert calls[0][0][2] == 0
        # second call: dwFlags == KEYEVENTF_KEYUP
        assert calls[1][0][2] == _KEYEVENTF_KEYUP

    def test_press_random_key_uses_same_vk_for_down_and_up(self):
        fake_ctypes, user32, _ = _make_fake_ctypes()
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_ctypes, fake_pynput)
        w = Watcher()
        w._press_random_key()
        calls = user32.keybd_event.call_args_list
        assert calls[0][0][0] == calls[1][0][0]


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------

class TestCleanup:
    def test_cleanup_restores_execution_state(self):
        fake_ctypes, _, kernel32 = _make_fake_ctypes()
        fake_pynput, _ = _make_fake_pynput()
        Watcher = _import_watcher(fake_ctypes, fake_pynput)
        w = Watcher()
        kernel32.SetThreadExecutionState.reset_mock()
        w.cleanup()
        kernel32.SetThreadExecutionState.assert_called_once_with(_ES_CONTINUOUS)

    def test_cleanup_stops_listeners(self):
        fake_ctypes, _, _ = _make_fake_ctypes()
        fake_pynput, listener_instance = _make_fake_pynput()
        Watcher = _import_watcher(fake_ctypes, fake_pynput)
        w = Watcher()
        w.cleanup()
        assert listener_instance.stop.call_count >= 2
