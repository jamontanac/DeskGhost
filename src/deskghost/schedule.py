from datetime import datetime
from zoneinfo import ZoneInfo

from deskghost.config import (
    DAY_OVERRIDES,
    IDLE_TIME_SECONDS,
    LUNCH_DURATION_MINUTES,
    LUNCH_START_TIME,
    MOVE_INTERVAL_SECONDS,
    SCHEDULE_TIMEZONE,
    SCHEDULE_TIMEZONE_LABEL,
    WORK_DAYS,
    WORK_END_TIME,
    WORK_START_TIME,
    get_effective_day_schedule,
)

# Re-export so existing imports of these names from deskghost.schedule keep working.
__all__ = [
    "IDLE_TIME_SECONDS",
    "MOVE_INTERVAL_SECONDS",
    "WORK_START_TIME",
    "WORK_END_TIME",
    "WORK_DAYS",
    "SCHEDULE_TIMEZONE",
    "SCHEDULE_TIMEZONE_LABEL",
    "DAY_OVERRIDES",
    "LUNCH_START_TIME",
    "LUNCH_DURATION_MINUTES",
    "now_in_schedule_timezone",
    "effective_day_schedule",
    "minutes_since_midnight",
    "is_work_hours",
    "is_lunch_time",
]


def now_in_schedule_timezone() -> datetime:
    """Return current datetime in the configured schedule timezone."""
    if SCHEDULE_TIMEZONE is None:
        return datetime.now().astimezone()
    return datetime.now(ZoneInfo(SCHEDULE_TIMEZONE))


def effective_day_schedule(weekday: int | None = None) -> tuple[bool, tuple[int, int], tuple[int, int]]:
    """Return (enabled, start, end) for a weekday after applying overrides."""
    day = now_in_schedule_timezone().weekday() if weekday is None else weekday
    return get_effective_day_schedule(day)


def minutes_since_midnight(now: datetime | None = None) -> int:
    """Return minutes elapsed since midnight in the schedule timezone."""
    current = now or now_in_schedule_timezone()
    return current.hour * 60 + current.minute


def is_work_hours(now: datetime | None = None) -> bool:
    current = now or now_in_schedule_timezone()
    enabled, start_time, end_time = get_effective_day_schedule(current.weekday())
    if not enabled:
        return False
    m = minutes_since_midnight(current)
    start = start_time[0] * 60 + start_time[1]
    end = end_time[0] * 60 + end_time[1]
    return start <= m < end


def is_lunch_time(now: datetime | None = None) -> bool:
    current = now or now_in_schedule_timezone()
    start = LUNCH_START_TIME[0] * 60 + LUNCH_START_TIME[1]
    return start <= minutes_since_midnight(current) < start + LUNCH_DURATION_MINUTES
