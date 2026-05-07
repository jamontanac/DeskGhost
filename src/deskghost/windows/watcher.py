import ctypes
import random
import time

from pynput import keyboard, mouse

from deskghost.schedule import MOVE_DISTANCE_PIXELS

# SetThreadExecutionState flags
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002

# Virtual-key codes
_VK_CTRL = 0x11
_VK_SHIFT = 0x10
_KEYEVENTF_KEYUP = 0x0002

# Interpolation steps for smooth cursor movement
_MOVE_STEPS = 20
_STEP_SLEEP = 0.01  # seconds per step → ~0.2 s total travel


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _get_screen_size() -> tuple[int, int]:
    user32 = ctypes.windll.user32
    user32.GetSystemMetrics.restype = ctypes.c_int
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


class ActivityWatcher:
    """Watches for user input and nudges the mouse when the user is idle.

    Uses ``ctypes`` (user32/kernel32) for all cursor and keystroke
    operations — no pyautogui required on Windows.  Also calls
    ``SetThreadExecutionState`` to prevent the display from sleeping.
    """

    def __init__(self) -> None:
        self.last_activity_time = time.time()
        self._bot_moving = False
        self._user32 = ctypes.windll.user32
        self._screen_w, self._screen_h = _get_screen_size()

        # Prevent system and display sleep for the lifetime of this watcher
        ctypes.windll.kernel32.SetThreadExecutionState(
            _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED
        )

        self._mouse_listener = mouse.Listener(
            on_move=self._on_activity,
            on_click=self._on_activity,
            on_scroll=self._on_activity,
        )
        self._kbd_listener = keyboard.Listener(on_press=self._on_activity)
        self._mouse_listener.start()
        self._kbd_listener.start()

    def _on_activity(self, *args) -> None:
        if not self._bot_moving:
            self.last_activity_time = time.time()

    def get_idle_time(self) -> float:
        """Seconds since the last detected user input event."""
        return time.time() - self.last_activity_time

    def reset_idle(self) -> None:
        """Reset the idle timer (e.g. when returning from lunch)."""
        self.last_activity_time = time.time()

    def _move_linear(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """Interpolate cursor from (x0, y0) to (x1, y1) in small steps."""
        for i in range(1, _MOVE_STEPS + 1):
            ix = int(x0 + (x1 - x0) * i / _MOVE_STEPS)
            iy = int(y0 + (y1 - y0) * i / _MOVE_STEPS)
            self._user32.SetCursorPos(ix, iy)
            time.sleep(_STEP_SLEEP)

    def _press_random_key(self) -> None:
        """Press and release either Ctrl or Shift, chosen at random."""
        vk = random.choice([_VK_CTRL, _VK_SHIFT])
        self._user32.keybd_event(vk, 0, 0, 0)                  # key down
        time.sleep(0.05)
        self._user32.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)   # key up

    def nudge_mouse(self) -> None:
        """Move the cursor slightly, return it to origin, then tap a key."""
        pt = _POINT()
        self._user32.GetCursorPos(ctypes.byref(pt))
        ox, oy = pt.x, pt.y

        tx = max(0, min(self._screen_w - 1, ox + random.randint(-MOVE_DISTANCE_PIXELS, MOVE_DISTANCE_PIXELS)))
        ty = max(0, min(self._screen_h - 1, oy + random.randint(-MOVE_DISTANCE_PIXELS, MOVE_DISTANCE_PIXELS)))

        self._bot_moving = True
        try:
            self._move_linear(ox, oy, tx, ty)
            time.sleep(0.05)
            self._move_linear(tx, ty, ox, oy)
        finally:
            self._bot_moving = False

        self._press_random_key()

    def cleanup(self) -> None:
        """Restore normal execution state and stop input listeners."""
        ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
        self._mouse_listener.stop()
        self._kbd_listener.stop()
