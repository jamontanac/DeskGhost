import subprocess
import time
from typing import Optional

import Quartz

# CGEventSource constants — query system-wide HID idle time with no
# Input Monitoring or Accessibility permission required.
_HID_STATE = Quartz.kCGEventSourceStateHIDSystemState  # hardware events only
_ANY_EVENT = Quartz.kCGAnyInputEventType               # any input event type


class ActivityWatcher:
    """Watches for user input and nudges the system when the user is idle.

    Uses ``CGEventSourceSecondsSinceLastEventType`` (no Input Monitoring
    or Accessibility permission required) for idle detection.

    Nudging is done by posting a ``kCGEventMouseMoved`` CGEvent at the
    current cursor position with zero delta — this resets the HID idle
    timer (and therefore Teams' presence timer) without any visible cursor
    movement.  Technique mirrors Caffeine's ActivitySimulator.
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
        """Post a zero-movement CGEvent to reset the HID idle timer.

        Creates a ``kCGEventMouseMoved`` event at the current cursor position
        (zero delta) and posts it to ``kCGHIDEventTap``.  The cursor does not
        move visually, but the HID idle timer — and therefore Teams' presence
        timer — is reset.

        Requires Accessibility permission (AX) to inject into the HID stream.
        """
        # Read the current cursor position from the HID event source
        src_event = Quartz.CGEventCreate(None)
        pos = Quartz.CGEventGetLocation(src_event)

        # Create and post a mouseMoved event at the exact same position
        move_event = Quartz.CGEventCreateMouseEvent(
            None,
            Quartz.kCGEventMouseMoved,
            pos,
            Quartz.kCGMouseButtonLeft,
        )
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, move_event)

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
