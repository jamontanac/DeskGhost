import ctypes
import ctypes.wintypes
import time

# ── SetThreadExecutionState flags ─────────────────────────────────────────────
_ES_CONTINUOUS       = 0x80000000
_ES_SYSTEM_REQUIRED  = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002

# ── SendInput / MOUSEINPUT ────────────────────────────────────────────────────
_INPUT_MOUSE        = 0
_MOUSEEVENTF_MOVE   = 0x0001  # relative mouse move — dx/dy of 0 = no movement


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx",          ctypes.c_long),
        ("dy",          ctypes.c_long),
        ("mouseData",   ctypes.c_ulong),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT(ctypes.Structure):
    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT)]

    _anonymous_ = ("_input",)
    _fields_ = [
        ("type",   ctypes.c_ulong),
        ("_input", _INPUT_UNION),
    ]


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("dwTime", ctypes.c_ulong),
    ]


class ActivityWatcher:
    """Watches for user input and nudges the system when the user is idle.

    Uses ``GetLastInputInfo`` to read the OS-level HID idle time (mirrors the
    macOS ``CGEventSourceSecondsSinceLastEventType`` approach — no listener
    threads required).

    Nudging is done via ``SendInput`` with a zero-delta ``MOUSEEVENTF_MOVE``
    event, which resets the system idle timer without moving the cursor
    visibly.  Optionally a harmless keystroke is also injected when
    ``SEND_KEYSTROKES`` is enabled.

    ``SetThreadExecutionState`` is held for the lifetime of the watcher to
    prevent display sleep.
    """

    def __init__(self) -> None:
        self._user32   = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32

        # Prevent system and display sleep for the lifetime of this watcher
        self._kernel32.SetThreadExecutionState(
            _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED
        )

    # ── Idle detection ────────────────────────────────────────────────────────

    def get_idle_time(self) -> float:
        """Seconds since the last hardware input event.

        Reads ``GetLastInputInfo`` — the Windows equivalent of macOS
        ``CGEventSourceSecondsSinceLastEventType``.  No listener threads or
        special permissions required.
        """
        lii = _LASTINPUTINFO(ctypes.sizeof(_LASTINPUTINFO))
        self._user32.GetLastInputInfo(ctypes.byref(lii))
        elapsed_ms = self._kernel32.GetTickCount() - lii.dwTime
        return max(0, elapsed_ms) / 1000.0

    def reset_idle(self) -> None:
        """Reset the system idle timer by injecting a zero-delta mouse event.

        ``GetLastInputInfo`` tracks real injected input, so the only reliable
        way to reset it is to actually post an input event — which
        ``nudge_mouse()`` already does.
        """
        self._send_zero_move()

    # ── Nudge ─────────────────────────────────────────────────────────────────

    def nudge_mouse(self) -> None:
        """Inject a zero-delta mouse move via SendInput to reset the system
        idle timer without moving the cursor visibly.

        ``SendInput`` posts a real HID-level mouse event into the input stream,
        resetting ``GetLastInputInfo`` (and Teams' idle timer) without any
        visible cursor movement.
        """
        self._send_zero_move()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _send_zero_move(self) -> None:
        """Post a MOUSEEVENTF_MOVE with dx=0, dy=0 via SendInput.

        This injects a real HID-level mouse event into the input stream,
        resetting ``GetLastInputInfo`` (and Teams' idle timer) without any
        visible cursor movement.
        """
        inp = _INPUT(
            type=_INPUT_MOUSE,
            _input=_INPUT._INPUT_UNION(
                mi=_MOUSEINPUT(
                    dx=0,
                    dy=0,
                    mouseData=0,
                    dwFlags=_MOUSEEVENTF_MOVE,
                    time=0,
                    dwExtraInfo=None,
                )
            ),
        )
        self._user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def cleanup(self) -> None:
        """Restore normal execution state."""
        self._kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
