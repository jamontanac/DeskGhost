import time

from deskghost.config import (
    IDLE_TIME_SECONDS,
    LUNCH_DURATION_MINUTES,
    LUNCH_START_TIME,
    MOVE_INTERVAL_SECONDS,
    WORK_DAYS,
    WORK_END_TIME,
    WORK_START_TIME,
)

# Re-export so existing imports of these names from deskghost.schedule keep working.
__all__ = [
    "IDLE_TIME_SECONDS",
    "MOVE_INTERVAL_SECONDS",
    "WORK_START_TIME",
    "WORK_END_TIME",
    "WORK_DAYS",
    "LUNCH_START_TIME",
    "LUNCH_DURATION_MINUTES",
    "minutes_since_midnight",
    "is_work_hours",
    "is_lunch_time",
]


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
