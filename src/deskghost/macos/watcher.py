import random
import subprocess
import time
from typing import Optional

import pyautogui
from pynput import keyboard, mouse

from deskghost.schedule import MOVE_DISTANCE_PIXELS

_screen_w, _screen_h = pyautogui.size()


class ActivityWatcher:
    """Watches for user input and nudges the mouse when the user is idle.

    Uses ``pynput`` for input monitoring and ``pyautogui`` for smooth
    cursor movement with return-to-origin behaviour.
    """

    def __init__(self) -> None:
        self.last_activity_time = time.time()
        self._bot_moving = False
        self._caffeinate_proc: Optional[subprocess.Popen] = None

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

    def nudge_mouse(self) -> None:
        """Move the cursor slightly and return it to its original position."""
        ox, oy = pyautogui.position()
        tx = max(0, min(_screen_w - 1, ox + random.randint(-MOVE_DISTANCE_PIXELS, MOVE_DISTANCE_PIXELS)))
        ty = max(0, min(_screen_h - 1, oy + random.randint(-MOVE_DISTANCE_PIXELS, MOVE_DISTANCE_PIXELS)))

        self._bot_moving = True
        try:
            pyautogui.moveTo(tx, ty, duration=0.2)
            time.sleep(0.05)
            pyautogui.moveTo(ox, oy, duration=0.2)
        finally:
            self._bot_moving = False

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
        """Stop input listeners and release any power assertions."""
        self.allow_display_sleep()
        self._mouse_listener.stop()
        self._kbd_listener.stop()
