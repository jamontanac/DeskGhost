import pyautogui
import random
import time
from pynput import mouse, keyboard

# Main configuration
IDLE_TIME_SECONDS = 120  # Idle time threshold before nudging the mouse
MOVE_INTERVAL_SECONDS = 5  # Seconds between nudges while idle
MOVE_DISTANCE_PIXELS = 20  # Maximum nudge distance in pixels

# Work schedule (the script exits outside this window)
WORK_START_TIME = (7, 0)  # 7:00 AM
WORK_END_TIME = (18, 0)  # 6:00 PM
WORK_DAYS = {0, 1, 2, 3, 4}  # 0=Monday ... 4=Friday

# Lunch break
LUNCH_START_TIME = (12, 30)  # Lunch start time (hour, minute)
LUNCH_DURATION_MINUTES = 60  # Lunch duration in minutes

# Logging
LOG_INTERVAL_SECONDS = 60  # Print repeated status messages at most every N seconds

screen_width, screen_height = pyautogui.size()


def minutes_since_midnight():
    """Return minutes elapsed since midnight."""
    t = time.localtime()
    return t.tm_hour * 60 + t.tm_min


def is_work_hours():
    t = time.localtime()
    if t.tm_wday not in WORK_DAYS:
        return False
    current_minutes = minutes_since_midnight()
    start_minutes = WORK_START_TIME[0] * 60 + WORK_START_TIME[1]
    end_minutes = WORK_END_TIME[0] * 60 + WORK_END_TIME[1]
    return start_minutes <= current_minutes < end_minutes


def is_lunch_time():
    start_minutes = LUNCH_START_TIME[0] * 60 + LUNCH_START_TIME[1]
    end_minutes = start_minutes + LUNCH_DURATION_MINUTES
    return start_minutes <= minutes_since_midnight() < end_minutes


class ActivityWatcher:
    def __init__(self):
        self.last_activity_time = time.time()
        self._bot_moving = False

        self.mouse_listener = mouse.Listener(
            on_move=self.on_activity,
            on_click=self.on_activity,
            on_scroll=self.on_activity,
        )
        self.keyboard_listener = keyboard.Listener(on_press=self.on_activity)

        self.mouse_listener.start()
        self.keyboard_listener.start()

    def on_activity(self, *args):
        if self._bot_moving:
            return
        self.last_activity_time = time.time()

    def get_idle_time(self):
        return time.time() - self.last_activity_time

    def reset_idle(self):
        """Reset idle timer (for example, when lunch break ends)."""
        self.last_activity_time = time.time()

    def nudge_mouse(self):
        """Move the cursor slightly and return it to its original position."""
        origin_x, origin_y = pyautogui.position()
        offset_x = random.randint(-MOVE_DISTANCE_PIXELS, MOVE_DISTANCE_PIXELS)
        offset_y = random.randint(-MOVE_DISTANCE_PIXELS, MOVE_DISTANCE_PIXELS)
        target_x = max(0, min(screen_width - 1, origin_x + offset_x))
        target_y = max(0, min(screen_height - 1, origin_y + offset_y))

        self._bot_moving = True
        try:
            pyautogui.moveTo(target_x, target_y, duration=0.2)
            time.sleep(0.05)
            pyautogui.moveTo(origin_x, origin_y, duration=0.2)
        finally:
            self._bot_moving = False


class ThrottledLogger:
    """Print a message only if at least LOG_INTERVAL_SECONDS elapsed since the previous one."""

    def __init__(self, interval=LOG_INTERVAL_SECONDS):
        self._interval = interval
        self._last_msg = {}

    def log(self, key, message):
        now = time.time()
        if now - self._last_msg.get(key, 0) >= self._interval:
            print(message)
            self._last_msg[key] = now


def main():
    # Startup

    watcher = ActivityWatcher()
    logger = ThrottledLogger()

    print("=" * 55)
    print("  Bot started")
    print(
        f"  Work hours: Mon-Fri {WORK_START_TIME[0]:02d}:{WORK_START_TIME[1]:02d} -> "
        f"{WORK_END_TIME[0]:02d}:{WORK_END_TIME[1]:02d}"
    )
    print(
        f"  Lunch break: {LUNCH_START_TIME[0]:02d}:{LUNCH_START_TIME[1]:02d} "
        f"for {LUNCH_DURATION_MINUTES} min"
    )
    print(
        f"  Idle threshold: {IDLE_TIME_SECONDS}s  |  "
        f"Nudge interval: {MOVE_INTERVAL_SECONDS}s"
    )
    print("=" * 55)

    in_lunch_break = False  # Detect transition out of lunch break

    try:
        while True:
            # 1. Outside work hours: stop the process
            if not is_work_hours():
                print("Outside work hours. Bot stopped.")
                break

            # 2. Lunch break
            if is_lunch_time():
                if not in_lunch_break:
                    print("Lunch break started. Preventing screen lock...")
                    in_lunch_break = True

                # Silent nudge to keep the screen awake
                watcher.nudge_mouse()
                logger.log("lunch", "  [lunch] Screen kept active.")
                time.sleep(MOVE_INTERVAL_SECONDS)

            # 3. Returning from lunch: reset idle timer
            elif in_lunch_break:
                print("Lunch break ended. Resetting idle timer.")
                watcher.reset_idle()
                in_lunch_break = False
                time.sleep(1)

            # 4. Normal inactivity: nudge
            elif watcher.get_idle_time() >= IDLE_TIME_SECONDS:
                watcher.nudge_mouse()
                logger.log(
                    "nudge",
                    f"  [idle {int(watcher.get_idle_time())}s] Cursor moved and restored."
                )
                time.sleep(MOVE_INTERVAL_SECONDS)

            # 5. User is active
            else:
                logger.log("active", "  [active] User activity detected.")
                time.sleep(1)

    except KeyboardInterrupt:
        print("\nProgram stopped manually.")
        return 130

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

