"""Tests for deskghost.schedule — pure logic, no I/O."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import deskghost.schedule as sched


# ---------------------------------------------------------------------------
# minutes_since_midnight
# ---------------------------------------------------------------------------

class TestMinutesSinceMidnight:
    def test_midnight(self):
        now = datetime(2026, 1, 5, 0, 0, tzinfo=ZoneInfo("UTC"))
        assert sched.minutes_since_midnight(now) == 0

    def test_noon(self):
        now = datetime(2026, 1, 5, 12, 0, tzinfo=ZoneInfo("UTC"))
        assert sched.minutes_since_midnight(now) == 720

    def test_arbitrary(self):
        now = datetime(2026, 1, 5, 9, 37, tzinfo=ZoneInfo("UTC"))
        assert sched.minutes_since_midnight(now) == 9 * 60 + 37


# ---------------------------------------------------------------------------
# is_work_hours
# ---------------------------------------------------------------------------

class TestIsWorkHours:
    def test_weekday_inside_base_window(self):
        now = datetime(2026, 1, 5, 9, 0, tzinfo=ZoneInfo("UTC"))  # Monday 09:00
        assert sched.is_work_hours(now) is True

    def test_weekday_at_base_start(self):
        now = datetime(
            2026,
            1,
            5,
            sched.WORK_START_TIME[0],
            sched.WORK_START_TIME[1],
            tzinfo=ZoneInfo("UTC"),
        )
        assert sched.is_work_hours(now) is True

    def test_weekday_at_base_end_is_outside(self):
        now = datetime(
            2026,
            1,
            5,
            sched.WORK_END_TIME[0],
            sched.WORK_END_TIME[1],
            tzinfo=ZoneInfo("UTC"),
        )
        assert sched.is_work_hours(now) is False

    def test_disabled_weekday_from_base_days_is_outside(self):
        now = datetime(2026, 1, 10, 10, 0, tzinfo=ZoneInfo("UTC"))  # Saturday
        assert sched.is_work_hours(now) is False

    def test_enabled_override_can_activate_weekend(self, monkeypatch):
        monkeypatch.setattr(
            sched,
            "get_effective_day_schedule",
            lambda weekday: (True, (9, 0), (12, 0)) if weekday == 5 else (False, (8, 0), (18, 0)),
        )
        now = datetime(2026, 1, 10, 10, 0, tzinfo=ZoneInfo("UTC"))
        assert sched.is_work_hours(now) is True

    def test_override_end_shortens_day(self, monkeypatch):
        monkeypatch.setattr(
            sched,
            "get_effective_day_schedule",
            lambda weekday: (True, (8, 0), (14, 0)) if weekday == 4 else (True, (8, 0), (18, 0)),
        )
        friday_1430 = datetime(2026, 1, 9, 14, 30, tzinfo=ZoneInfo("UTC"))
        assert sched.is_work_hours(friday_1430) is False

    def test_override_start_delays_day(self, monkeypatch):
        monkeypatch.setattr(
            sched,
            "get_effective_day_schedule",
            lambda weekday: (True, (10, 0), (18, 0)) if weekday == 1 else (True, (8, 0), (18, 0)),
        )
        tuesday_0930 = datetime(2026, 1, 6, 9, 30, tzinfo=ZoneInfo("UTC"))
        assert sched.is_work_hours(tuesday_0930) is False

    def test_override_enabled_false_disables_base_workday(self, monkeypatch):
        monkeypatch.setattr(
            sched,
            "get_effective_day_schedule",
            lambda weekday: (False, (8, 0), (18, 0)) if weekday == 2 else (True, (8, 0), (18, 0)),
        )
        wednesday_1100 = datetime(2026, 1, 7, 11, 0, tzinfo=ZoneInfo("UTC"))
        assert sched.is_work_hours(wednesday_1100) is False


# ---------------------------------------------------------------------------
# is_lunch_time
# ---------------------------------------------------------------------------

class TestIsLunchTime:
    def test_at_lunch_start(self):
        h, m = sched.LUNCH_START_TIME
        now = datetime(2026, 1, 5, h, m, tzinfo=ZoneInfo("UTC"))
        assert sched.is_lunch_time(now) is True

    def test_one_minute_before_lunch(self):
        h, m = sched.LUNCH_START_TIME
        minute = m - 1 if m > 0 else 59
        hour = h if m > 0 else h - 1
        now = datetime(2026, 1, 5, hour, minute, tzinfo=ZoneInfo("UTC"))
        assert sched.is_lunch_time(now) is False

    def test_at_lunch_end_is_outside(self):
        total = sched.LUNCH_START_TIME[0] * 60 + sched.LUNCH_START_TIME[1] + sched.LUNCH_DURATION_MINUTES
        now = datetime(2026, 1, 5, total // 60, total % 60, tzinfo=ZoneInfo("UTC"))
        assert sched.is_lunch_time(now) is False

    def test_one_minute_before_lunch_end(self):
        total = sched.LUNCH_START_TIME[0] * 60 + sched.LUNCH_START_TIME[1] + sched.LUNCH_DURATION_MINUTES - 1
        now = datetime(2026, 1, 5, total // 60, total % 60, tzinfo=ZoneInfo("UTC"))
        assert sched.is_lunch_time(now) is True

    def test_morning_is_not_lunch(self):
        now = datetime(2026, 1, 5, 9, 0, tzinfo=ZoneInfo("UTC"))
        assert sched.is_lunch_time(now) is False


# ---------------------------------------------------------------------------
# timezone-aware now
# ---------------------------------------------------------------------------

class TestScheduleTimezoneNow:
    def test_now_in_schedule_timezone_uses_configured_zone(self):
        now = sched.now_in_schedule_timezone()
        if sched.SCHEDULE_TIMEZONE is None:
            assert now.tzinfo is not None
        else:
            assert str(now.tzinfo) == sched.SCHEDULE_TIMEZONE

    def test_effective_day_schedule_defaults_to_current_weekday(self, monkeypatch):
        current = datetime(2026, 1, 7, 12, 0, tzinfo=ZoneInfo("UTC"))  # Wednesday
        monkeypatch.setattr(sched, "now_in_schedule_timezone", lambda: current)
        called = {}

        def fake(day: int):
            called["day"] = day
            return (True, (8, 0), (18, 0))

        monkeypatch.setattr(sched, "get_effective_day_schedule", fake)
        result = sched.effective_day_schedule()
        assert result == (True, (8, 0), (18, 0))
        assert called["day"] == 2

    def test_effective_day_schedule_respects_explicit_weekday(self, monkeypatch):
        monkeypatch.setattr(sched, "get_effective_day_schedule", lambda day: (day == 5, (9, 0), (12, 0)))
        assert sched.effective_day_schedule(weekday=5) == (True, (9, 0), (12, 0))
        assert sched.effective_day_schedule(weekday=1) == (False, (9, 0), (12, 0))
