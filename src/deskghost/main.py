import sys
import time

from deskghost.logger import ThrottledLogger, configure_file_logging, get_logger
from deskghost.schedule import (
    IDLE_TIME_SECONDS,
    LUNCH_DURATION_MINUTES,
    LUNCH_START_TIME,
    MOVE_INTERVAL_SECONDS,
    WORK_END_TIME,
    WORK_START_TIME,
    is_lunch_time,
    is_work_hours,
)

if sys.platform == "win32":
    from deskghost.windows.watcher import ActivityWatcher
else:
    from deskghost.macos.watcher import ActivityWatcher


def main() -> int:
    log = get_logger()
    log_file = configure_file_logging()
    throttled = ThrottledLogger()
    watcher = ActivityWatcher()

    log.info("=" * 55)
    log.info("  DeskGhost started")
    log.info(
        f"  Work hours : Mon-Fri  "
        f"{WORK_START_TIME[0]:02d}:{WORK_START_TIME[1]:02d} -> "
        f"{WORK_END_TIME[0]:02d}:{WORK_END_TIME[1]:02d}"
    )
    log.info(
        f"  Lunch      : {LUNCH_START_TIME[0]:02d}:{LUNCH_START_TIME[1]:02d}  "
        f"for {LUNCH_DURATION_MINUTES} min"
    )
    log.info(
        f"  Idle threshold : {IDLE_TIME_SECONDS}s  |  "
        f"Nudge interval : {MOVE_INTERVAL_SECONDS}s"
    )
    log.info(f"  Platform : {sys.platform}")
    log.info(f"  Log file : {log_file}")
    log.info("=" * 55)

    in_lunch = False

    try:
        while True:
            # 1. Outside work hours — exit cleanly
            if not is_work_hours():
                log.info("Outside work hours. Bot stopped.")
                break

            # 2. Lunch break — keep screen alive silently
            if is_lunch_time():
                if not in_lunch:
                    log.info("Lunch break started. Preventing screen lock...")
                    in_lunch = True
                watcher.nudge_mouse()
                throttled.info("lunch", "  [lunch] Screen kept active.")
                time.sleep(MOVE_INTERVAL_SECONDS)

            # 3. Returning from lunch — reset idle so we don't nudge immediately
            elif in_lunch:
                log.info("Lunch break ended. Resetting idle timer.")
                watcher.reset_idle()
                in_lunch = False
                time.sleep(1)

            # 4. User has been idle long enough — nudge
            elif watcher.get_idle_time() >= IDLE_TIME_SECONDS:
                watcher.nudge_mouse()
                throttled.info(
                    "nudge",
                    f"  [idle {int(watcher.get_idle_time())}s] Cursor moved and restored.",
                )
                time.sleep(MOVE_INTERVAL_SECONDS)

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
