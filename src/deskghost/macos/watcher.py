import random
import subprocess
import time
from typing import Optional

import pyautogui
import Quartz

from deskghost.schedule import MOVE_DISTANCE_PIXELS

_screen_w, _screen_h = pyautogui.size()

# CGEventSource constants — query system-wide HID idle time with no
# Input Monitoring or Accessibility permission required.
_HID_STATE = Quartz.kCGEventSourceStateHIDSystemState  # hardware events only
_ANY_EVENT = Quartz.kCGAnyInputEventType               # any input event type


class ActivityWatcher:
    """Watches for user input and nudges the mouse when the user is idle.

    Uses ``CGEventSourceSecondsSinceLastEventType`` (no Input Monitoring
    permission required) for idle detection and ``pyautogui`` for smooth
    cursor movement with return-to-origin behaviour.
    """

    def __init__(self) -> None:
        self._reset_time: Optional[float] = None
        self._caffeinate_proc: Optional[subprocess.Popen] = None

    def get_idle_time(self) -> float:
        """Seconds since the last hardware input event.

        Reads from ``kCGEventSourceStateHIDSystemState`` — no Input Monitoring
        or Accessibility permission required.  If ``reset_idle()`` was called
        more recently than the last hardware event, that elapsed time is used
        instead so the idle counter always starts from zero after a reset.
        """
        hid_idle = Quartz.CGEventSourceSecondsSinceLastEventType(_HID_STATE, _ANY_EVENT)
        if self._reset_time is not None:
            return min(hid_idle, time.time() - self._reset_time)
        return hid_idle

    def reset_idle(self) -> None:
        """Mark the current moment as the start of a fresh idle period."""
        self._reset_time = time.time()

    def nudge_mouse(self) -> None:
        """Move the cursor slightly and return it to its original position."""
        ox, oy = pyautogui.position()
        tx = max(0, min(_screen_w - 1, ox + random.randint(-MOVE_DISTANCE_PIXELS, MOVE_DISTANCE_PIXELS)))
        ty = max(0, min(_screen_h - 1, oy + random.randint(-MOVE_DISTANCE_PIXELS, MOVE_DISTANCE_PIXELS)))

        pyautogui.moveTo(tx, ty, duration=0.2)
        time.sleep(0.05)
        pyautogui.moveTo(ox, oy, duration=0.2)

    def prevent_display_sleep(self) -> None:
        """Assert a display-sleep-prevention power claim via caffeinate.

        Uses ``caffeinate -d`` which holds a
        ``kIOPMAssertionTypePreventUserIdleDisplaySleep`` IOKit assertion
        without generating any HID events, so Teams (and similar apps) will
        still see the user as idle/away.
        """
        if self._caffeinate_proc is None or self._caffeinate_proc.poll() is not None:
            self._caffeinate_proc = subprocess.Popen(
                ["caffeinate", "-d"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def allow_display_sleep(self) -> None:
        """Release the display-sleep-prevention assertion if one is held."""
        if self._caffeinate_proc is not None:
            self._caffeinate_proc.terminate()
            self._caffeinate_proc.wait()
            self._caffeinate_proc = None

    def cleanup(self) -> None:
        """Release any power assertions."""
        self.allow_display_sleep()
