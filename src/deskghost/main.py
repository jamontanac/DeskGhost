import ctypes
import os
import signal
import sys
import time

from deskghost.config import MANUAL_ALWAYS_ON
from deskghost.lock import InstanceLock
from deskghost.logger import ThrottledLogger, configure_file_logging, get_logger
from deskghost.schedule import (
    DAY_OVERRIDES,
    IDLE_TIME_SECONDS,
    LUNCH_DURATION_MINUTES,
    LUNCH_START_TIME,
    MOVE_INTERVAL_SECONDS,
    SCHEDULE_TIMEZONE_LABEL,
    WORK_END_TIME,
    WORK_START_TIME,
    WORK_DAYS,
    is_lunch_time,
    is_work_hours,
)

if sys.platform == "win32":
    from deskghost.windows.watcher import ActivityWatcher
else:
    from deskghost.macos.watcher import ActivityWatcher


def _is_accessibility_trusted() -> bool:
    """Return True if this process has macOS Accessibility (AX) permission."""
    if sys.platform == "win32":
        return True
    try:
        lib = ctypes.CDLL(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        return lib.AXIsProcessTrusted()
    except OSError:
        return True


def _request_accessibility_permission() -> None:
    """Ask macOS to show the Accessibility permission dialog for this process."""
    if sys.platform == "win32":
        return
    try:
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        ax = ctypes.CDLL(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )

        key_cbs = ctypes.c_void_p.in_dll(cf, "kCFTypeDictionaryKeyCallBacks")
        val_cbs = ctypes.c_void_p.in_dll(cf, "kCFTypeDictionaryValueCallBacks")

        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_uint32,
        ]
        key = cf.CFStringCreateWithCString(None, b"AXTrustedCheckOptionPrompt", 0x08000100)

        cf_bool_true = ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue")

        cf.CFDictionaryCreate.restype = ctypes.c_void_p
        cf.CFDictionaryCreate.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        key_ptr = ctypes.c_void_p(key)
        val_ptr = ctypes.c_void_p(cf_bool_true.value)
        options = cf.CFDictionaryCreate(
            None,
            ctypes.byref(key_ptr),
            ctypes.byref(val_ptr),
            1,
            ctypes.addressof(key_cbs),
            ctypes.addressof(val_cbs),
        )

        ax.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool
        ax.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]
        ax.AXIsProcessTrustedWithOptions(options)
    except OSError:
        return


def _handle_cli_flags() -> int | None:
    """Handle helper CLI flags used by setup scripts.

    Flags:
    - ``--ax-status``: prints trusted/not-trusted and exits (0 trusted, 1 not).
    - ``--request-ax``: requests Accessibility permission and exits.
    """
    if "--ax-status" in sys.argv:
        trusted = _is_accessibility_trusted()
        print("trusted" if trusted else "not-trusted")
        return 0 if trusted else 1

    if "--request-ax" in sys.argv:
        _request_accessibility_permission()
        trusted = _is_accessibility_trusted()
        print("trusted" if trusted else "not-trusted")
        return 0 if trusted else 1

    return None


def _runtime_cli_options() -> tuple[bool, bool]:
    """Return (manual_mode, always_on_override) from runtime CLI flags.

    --always-on implies --manual because it is a manual execution profile.
    """
    manual_mode = "--manual" in sys.argv
    always_on_override = "--always-on" in sys.argv
    if always_on_override:
        manual_mode = True
    return manual_mode, always_on_override


def _is_process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _terminate_existing_instance(pid: int, log) -> bool:
    if pid == os.getpid():
        log.error("Refusing to terminate current process during takeover.")
        return False

    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except ProcessLookupError:
        return True
    except PermissionError:
        log.error(f"Cannot terminate existing DeskGhost PID {pid}: permission denied.")
        return False
    except OSError as exc:
        log.error(f"Cannot terminate existing DeskGhost PID {pid}: {exc}")
        return False


def _wait_for_lock_availability(timeout_seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with InstanceLock() as probe:
            if probe:
                return True
        time.sleep(0.2)
    return False


def _attempt_manual_takeover(existing_pid: int | None, log) -> bool:
    if existing_pid is None:
        log.error(
            "Manual always-on mode requested takeover, but the running PID is unknown. "
            "Stop the existing instance manually and retry."
        )
        return False

    log.warning(
        f"Manual always-on mode is taking over from running DeskGhost PID {existing_pid}."
    )

    if not _terminate_existing_instance(existing_pid, log):
        return False

    if not _wait_for_lock_availability():
        if _is_process_running(existing_pid):
            log.error(
                f"Takeover timed out waiting for DeskGhost PID {existing_pid} to exit."
            )
        else:
            log.error("Takeover timed out waiting for DeskGhost lock release.")
        return False

    log.warning(
        f"Manual always-on takeover completed. Replaced PID {existing_pid}."
    )
    return True


def main() -> int:
    cli_result = _handle_cli_flags()
    if cli_result is not None:
        return cli_result

    manual_mode, always_on_override = _runtime_cli_options()
    always_on_mode = always_on_override or (manual_mode and MANUAL_ALWAYS_ON)
    takeover_attempts = 0

    while True:
        with InstanceLock() as lock:
            if lock:
                return _run(always_on_mode=always_on_mode, manual_mode=manual_mode)

            # Another instance is already running (e.g. machine woke from sleep
            # while a previous session was still alive, and the scheduler or
            # login item fired again).
            log = get_logger()

            if always_on_mode and manual_mode:
                if takeover_attempts >= 1:
                    if lock.pid is not None:
                        log.error(
                            f"Could not acquire lock after takeover attempt. "
                            f"DeskGhost PID {lock.pid} is still running."
                        )
                    else:
                        log.error("Could not acquire lock after takeover attempt.")
                    return 1

                takeover_attempts += 1
                if _attempt_manual_takeover(lock.pid, log):
                    continue
                return 1

            if lock.pid is not None:
                log.warning(
                    f"DeskGhost already running (PID {lock.pid}). "
                    f"To stop it: kill {lock.pid}"
                )
            else:
                log.warning("DeskGhost already running (PID unknown). Lock file: ~/.deskghost/deskghost.lock")
            return 0


def _run(always_on_mode: bool = False, manual_mode: bool = False) -> int:
    log = get_logger()
    log_file = configure_file_logging()
    throttled = ThrottledLogger()
    watcher = ActivityWatcher()
    day_labels = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    base_days = ", ".join(day_labels[day] for day in sorted(WORK_DAYS)) or "none"

    log.info("=" * 55)
    log.info("  DeskGhost started")
    log.info(f"  Schedule TZ: {SCHEDULE_TIMEZONE_LABEL}")
    log.info(
        f"  Base hours : "
        f"{WORK_START_TIME[0]:02d}:{WORK_START_TIME[1]:02d} -> "
        f"{WORK_END_TIME[0]:02d}:{WORK_END_TIME[1]:02d} "
        f"({base_days})"
    )
    if DAY_OVERRIDES:
        log.info("  Day overrides:")
        for day in sorted(DAY_OVERRIDES):
            override = DAY_OVERRIDES[day]
            parts: list[str] = []
            if "enabled" in override:
                parts.append(f"enabled={override['enabled']}")
            if "work_start" in override:
                parts.append(
                    f"start={override['work_start'][0]:02d}:{override['work_start'][1]:02d}"
                )
            if "work_end" in override:
                parts.append(
                    f"end={override['work_end'][0]:02d}:{override['work_end'][1]:02d}"
                )
            log.info(f"    {day_labels[day]}: {', '.join(parts)}")
    log.info(
        f"  Lunch      : {LUNCH_START_TIME[0]:02d}:{LUNCH_START_TIME[1]:02d}  "
        f"for {LUNCH_DURATION_MINUTES} min"
    )
    log.info(
        f"  Idle threshold : {IDLE_TIME_SECONDS}s  |  "
        f"Nudge interval : {MOVE_INTERVAL_SECONDS}s"
    )
    if always_on_mode:
        log.warning("  Manual always-on mode is active.")
        log.warning("  Schedule and lunch windows are ignored.")
        log.warning("  DeskGhost will stay active until stopped (Ctrl+C).")
    elif manual_mode:
        log.info("  Manual mode is active. Schedule and lunch windows still apply.")
    log.info(f"  Platform : {sys.platform}")
    log.info(f"  Log file : {log_file}")
    log.info("=" * 55)

    if not _is_accessibility_trusted():
        log.warning("=" * 55)
        log.warning("  ACCESSIBILITY PERMISSION NOT GRANTED")
        log.warning("  Accessibility permission not granted — CGEventPost cannot")
        log.warning("  inject HID events to reset the idle timer.")
        log.warning("  Teams (and similar apps) will still go idle.")
        log.warning("  Run this to open the permission dialog automatically:")
        log.warning("    bash scripts/setup.sh grant-ax")
        log.warning("  Then re-run: bash scripts/setup.sh uninstall && bash scripts/setup.sh install")
        log.warning("=" * 55)

    in_lunch = False
    last_nudge_time: float = 0.0  # epoch 0 ensures first nudge fires immediately

    try:
        while True:
            # 1. Outside work hours — exit cleanly
            if not always_on_mode and not is_work_hours():
                log.info("Outside work hours. Bot stopped.")
                break

            # 2. Lunch break — keep display alive without simulating input
            if not always_on_mode and is_lunch_time():
                if not in_lunch:
                    log.info("Lunch break started. Preventing display sleep (Teams may go idle)...")
                    in_lunch = True
                watcher.prevent_display_sleep()
                throttled.info("lunch", "  [lunch] Display kept active, input simulation paused.")
                time.sleep(MOVE_INTERVAL_SECONDS)

            # 3. Returning from lunch — release display assertion and reset idle
            elif in_lunch and not always_on_mode:
                log.info("Lunch break ended. Releasing display assertion, resetting idle timer.")
                watcher.allow_display_sleep()
                watcher.reset_idle()
                in_lunch = False
                time.sleep(1)

            # 4. User has been idle long enough — nudge on wall-clock interval
            elif watcher.get_idle_time() >= IDLE_TIME_SECONDS:
                now = time.time()
                if now - last_nudge_time >= MOVE_INTERVAL_SECONDS:
                    watcher.nudge_mouse()
                    last_nudge_time = now
                    throttled.info(
                        "nudge",
                        f"  [idle {int(watcher.get_idle_time())}s] Cursor moved and restored.",
                    )
                time.sleep(1)

            # 5. User is active — nothing to do
            else:
                throttled.info("active", "  [active] User activity detected.")
                time.sleep(1)

    except KeyboardInterrupt:
        log.info("Program stopped manually.")
        return 130

    finally:
        watcher.cleanup()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
