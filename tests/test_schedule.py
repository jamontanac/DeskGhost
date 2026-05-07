"""Tests for deskghost.schedule — pure logic, no I/O."""

import pytest

import deskghost.schedule as sched


# ---------------------------------------------------------------------------
# minutes_since_midnight
# ---------------------------------------------------------------------------

class TestMinutesSinceMidnight:
    def test_midnight(self, freeze_time):
        freeze_time(weekday=0, hour=0, minute=0)
        assert sched.minutes_since_midnight() == 0

    def test_noon(self, freeze_time):
        freeze_time(weekday=0, hour=12, minute=0)
        assert sched.minutes_since_midnight() == 720

    def test_arbitrary(self, freeze_time):
        freeze_time(weekday=0, hour=9, minute=37)
        assert sched.minutes_since_midnight() == 9 * 60 + 37


# ---------------------------------------------------------------------------
# is_work_hours
# ---------------------------------------------------------------------------

class TestIsWorkHours:
    def test_weekday_inside_window(self, freeze_time):
        freeze_time(weekday=0, hour=9, minute=0)  # Monday 09:00
        assert sched.is_work_hours() is True

    def test_weekday_at_start(self, freeze_time):
        freeze_time(weekday=0, hour=sched.WORK_START_TIME[0], minute=sched.WORK_START_TIME[1])
        assert sched.is_work_hours() is True

    def test_weekday_one_minute_before_start(self, freeze_time):
        h, m = sched.WORK_START_TIME
        minute = m - 1 if m > 0 else 59
        hour = h if m > 0 else h - 1
        freeze_time(weekday=0, hour=hour, minute=minute)
        assert sched.is_work_hours() is False

    def test_weekday_at_end_is_outside(self, freeze_time):
        # end time is exclusive
        freeze_time(weekday=0, hour=sched.WORK_END_TIME[0], minute=sched.WORK_END_TIME[1])
        assert sched.is_work_hours() is False

    def test_weekday_one_minute_before_end(self, freeze_time):
        h, m = sched.WORK_END_TIME
        minute = m - 1 if m > 0 else 59
        hour = h if m > 0 else h - 1
        freeze_time(weekday=0, hour=hour, minute=minute)
        assert sched.is_work_hours() is True

    def test_saturday_is_outside(self, freeze_time):
        freeze_time(weekday=5, hour=10, minute=0)  # Saturday
        assert sched.is_work_hours() is False

    def test_sunday_is_outside(self, freeze_time):
        freeze_time(weekday=6, hour=10, minute=0)  # Sunday
        assert sched.is_work_hours() is False

    def test_all_configured_work_days_are_inside(self, freeze_time):
        for day in sched.WORK_DAYS:
            freeze_time(weekday=day, hour=10, minute=0)
            assert sched.is_work_hours() is True, f"Expected work hours on weekday {day}"


# ---------------------------------------------------------------------------
# is_lunch_time
# ---------------------------------------------------------------------------

class TestIsLunchTime:
    def test_at_lunch_start(self, freeze_time):
        h, m = sched.LUNCH_START_TIME
        freeze_time(weekday=0, hour=h, minute=m)
        assert sched.is_lunch_time() is True

    def test_one_minute_before_lunch(self, freeze_time):
        h, m = sched.LUNCH_START_TIME
        minute = m - 1 if m > 0 else 59
        hour = h if m > 0 else h - 1
        freeze_time(weekday=0, hour=hour, minute=minute)
        assert sched.is_lunch_time() is False

    def test_at_lunch_end_is_outside(self, freeze_time):
        total = sched.LUNCH_START_TIME[0] * 60 + sched.LUNCH_START_TIME[1] + sched.LUNCH_DURATION_MINUTES
        freeze_time(weekday=0, hour=total // 60, minute=total % 60)
        assert sched.is_lunch_time() is False

    def test_one_minute_before_lunch_end(self, freeze_time):
        total = sched.LUNCH_START_TIME[0] * 60 + sched.LUNCH_START_TIME[1] + sched.LUNCH_DURATION_MINUTES - 1
        freeze_time(weekday=0, hour=total // 60, minute=total % 60)
        assert sched.is_lunch_time() is True

    def test_morning_is_not_lunch(self, freeze_time):
        freeze_time(weekday=0, hour=9, minute=0)
        assert sched.is_lunch_time() is False

    def test_afternoon_after_lunch_is_not_lunch(self, freeze_time):
        total = sched.LUNCH_START_TIME[0] * 60 + sched.LUNCH_START_TIME[1] + sched.LUNCH_DURATION_MINUTES + 60
        freeze_time(weekday=0, hour=total // 60, minute=total % 60)
        assert sched.is_lunch_time() is False
