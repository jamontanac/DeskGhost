import time

# Idle / nudge behaviour
IDLE_TIME_SECONDS = 120       # seconds idle before nudging starts
MOVE_INTERVAL_SECONDS = 5     # seconds between nudges while idle
MOVE_DISTANCE_PIXELS = 20     # maximum nudge offset in any direction

# Work schedule
WORK_START_TIME = (7, 0)      # (hour, minute) — 07:00
WORK_END_TIME = (18, 0)       # (hour, minute) — 18:00
WORK_DAYS = {0, 1, 2, 3, 4}  # 0=Monday … 4=Friday

# Lunch break
LUNCH_START_TIME = (12, 30)   # (hour, minute)
LUNCH_DURATION_MINUTES = 60


def minutes_since_midnight() -> int:
    """Return minutes elapsed since midnight for the current local time."""
    t = time.localtime()
    return t.tm_hour * 60 + t.tm_min


def is_work_hours() -> bool:
    t = time.localtime()
    if t.tm_wday not in WORK_DAYS:
        return False
    m = minutes_since_midnight()
    start = WORK_START_TIME[0] * 60 + WORK_START_TIME[1]
    end = WORK_END_TIME[0] * 60 + WORK_END_TIME[1]
    return start <= m < end


def is_lunch_time() -> bool:
    start = LUNCH_START_TIME[0] * 60 + LUNCH_START_TIME[1]
    return start <= minutes_since_midnight() < start + LUNCH_DURATION_MINUTES
