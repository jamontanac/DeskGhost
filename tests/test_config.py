"""
tests/test_config.py — unit tests for src/deskghost/config.py
"""

from __future__ import annotations

import textwrap
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import deskghost.config as config_module
from deskghost.config import (
    _load,
    _parse_hhmm,
    _require_int,
    get_local_scheduler_trigger_entries,
)


# -- _parse_hhmm ---------------------------------------------------------------

def test_parse_hhmm_standard_time():
    assert _parse_hhmm("07:00", "f") == (7, 0)


def test_parse_hhmm_noon():
    assert _parse_hhmm("12:30", "f") == (12, 30)


def test_parse_hhmm_end_of_day():
    assert _parse_hhmm("18:00", "f") == (18, 0)


def test_parse_hhmm_midnight():
    assert _parse_hhmm("00:00", "f") == (0, 0)


def test_parse_hhmm_invalid_format_raises():
    with pytest.raises(ValueError, match="HH:MM"):
        _parse_hhmm("7-00", "schedule.work_start")


def test_parse_hhmm_non_string_raises():
    with pytest.raises(ValueError, match="HH:MM"):
        _parse_hhmm(700, "schedule.work_start")  # type: ignore[arg-type]


def test_parse_hhmm_out_of_range_hour_raises():
    with pytest.raises(ValueError, match="out-of-range"):
        _parse_hhmm("25:00", "schedule.work_start")


def test_parse_hhmm_out_of_range_minute_raises():
    with pytest.raises(ValueError, match="out-of-range"):
        _parse_hhmm("08:60", "schedule.work_start")


# -- _require_int --------------------------------------------------------------

def test_require_int_valid():
    assert _require_int(120, "nudge.idle_time_seconds") == 120


def test_require_int_rejects_string():
    with pytest.raises(ValueError, match="integer"):
        _require_int("120", "nudge.idle_time_seconds")  # type: ignore[arg-type]


def test_require_int_rejects_bool():
    with pytest.raises(ValueError, match="integer"):
        _require_int(True, "nudge.idle_time_seconds")


def test_require_int_rejects_below_minimum():
    with pytest.raises(ValueError, match=">= 1"):
        _require_int(0, "nudge.idle_time_seconds")


# -- _load: real config.yaml ---------------------------------------------------

def test_load_real_config_returns_all_keys():
    cfg = _load()
    expected_keys = {
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
    }
    assert expected_keys <= cfg.keys()


def test_load_code_default_values(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("{}\n")
    cfg = _load(cfg_file)
    assert cfg["IDLE_TIME_SECONDS"] == 120
    assert cfg["MOVE_INTERVAL_SECONDS"] == 5
    assert cfg["WORK_START_TIME"] == (7, 0)
    assert cfg["WORK_END_TIME"] == (18, 0)
    assert cfg["WORK_DAYS"] == {0, 1, 2, 3, 4}
    assert cfg["SCHEDULE_TIMEZONE"] is None
    assert cfg["DAY_OVERRIDES"] == {}
    assert cfg["LUNCH_START_TIME"] == (12, 30)
    assert cfg["LUNCH_DURATION_MINUTES"] == 60


def test_load_real_config_types():
    cfg = _load()
    assert isinstance(cfg["IDLE_TIME_SECONDS"], int)
    assert isinstance(cfg["MOVE_INTERVAL_SECONDS"], int)
    assert isinstance(cfg["WORK_START_TIME"], tuple)
    assert isinstance(cfg["WORK_END_TIME"], tuple)
    assert isinstance(cfg["WORK_DAYS"], set)
    assert cfg["SCHEDULE_TIMEZONE"] is None or isinstance(cfg["SCHEDULE_TIMEZONE"], str)
    assert isinstance(cfg["SCHEDULE_TIMEZONE_LABEL"], str)
    assert isinstance(cfg["DAY_OVERRIDES"], dict)
    assert isinstance(cfg["LUNCH_START_TIME"], tuple)
    assert isinstance(cfg["LUNCH_DURATION_MINUTES"], int)


# -- _load: custom path --------------------------------------------------------

def test_load_missing_file_raises_file_not_found(tmp_path):
    missing = tmp_path / "nonexistent.yaml"
    with pytest.raises(FileNotFoundError, match="conf/config.yaml|nonexistent"):
        _load(missing)


def test_load_custom_path_overrides_values(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        textwrap.dedent(
            """\
            nudge:
              idle_time_seconds: 300
              move_interval_seconds: 10
            schedule:
              work_start: "08:30"
              work_end: "17:00"
              work_days: [0, 1, 2, 3, 4]
              timezone: "America/Bogota"
              day_overrides:
                4:
                  work_end: "14:00"
                5:
                  enabled: true
                  work_start: "09:00"
                  work_end: "12:00"
            lunch:
              start: "13:00"
              duration_minutes: 45
            """
        )
    )
    cfg = _load(cfg_file)
    assert cfg["IDLE_TIME_SECONDS"] == 300
    assert cfg["MOVE_INTERVAL_SECONDS"] == 10
    assert cfg["WORK_START_TIME"] == (8, 30)
    assert cfg["WORK_END_TIME"] == (17, 0)
    assert cfg["WORK_DAYS"] == {0, 1, 2, 3, 4}
    assert cfg["SCHEDULE_TIMEZONE"] == "America/Bogota"
    assert cfg["DAY_OVERRIDES"][4]["work_end"] == (14, 0)
    assert cfg["DAY_OVERRIDES"][5]["enabled"] is True
    assert cfg["LUNCH_START_TIME"] == (13, 0)
    assert cfg["LUNCH_DURATION_MINUTES"] == 45


def test_load_invalid_idle_time_type_raises(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        textwrap.dedent(
            """\
            nudge:
              idle_time_seconds: "abc"
              move_interval_seconds: 5
            schedule:
              work_start: "07:00"
              work_end: "18:00"
              work_days: [0, 1, 2, 3, 4]
            lunch:
              start: "12:30"
              duration_minutes: 60
            """
        )
    )
    with pytest.raises(ValueError, match="nudge.idle_time_seconds"):
        _load(cfg_file)


def test_load_invalid_time_string_raises(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        textwrap.dedent(
            """\
            nudge:
              idle_time_seconds: 120
              move_interval_seconds: 5
            schedule:
              work_start: "7am"
              work_end: "18:00"
              work_days: [0, 1, 2, 3, 4]
            lunch:
              start: "12:30"
              duration_minutes: 60
            """
        )
    )
    with pytest.raises(ValueError, match="schedule.work_start"):
        _load(cfg_file)


def test_load_invalid_timezone_raises(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        textwrap.dedent(
            """\
            schedule:
              work_start: "08:00"
              work_end: "18:00"
              work_days: [0, 1, 2, 3, 4]
              timezone: "UTF-5"
            """
        )
    )
    with pytest.raises(ValueError, match="schedule.timezone"):
        _load(cfg_file)


def test_load_invalid_work_days_raises(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        textwrap.dedent(
            """\
            schedule:
              work_start: "08:00"
              work_end: "18:00"
              work_days: [0, 1, 9]
            """
        )
    )
    with pytest.raises(ValueError, match="work_days"):
        _load(cfg_file)


def test_load_invalid_day_override_key_raises(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        textwrap.dedent(
            """\
            schedule:
              work_start: "08:00"
              work_end: "18:00"
              work_days: [0, 1, 2, 3, 4]
              day_overrides:
                8:
                  work_end: "14:00"
            """
        )
    )
    with pytest.raises(ValueError, match="weekday"):
        _load(cfg_file)


def test_load_invalid_day_override_value_raises(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        textwrap.dedent(
            """\
            schedule:
              work_start: "08:00"
              work_end: "18:00"
              work_days: [0, 1, 2, 3, 4]
              day_overrides:
                4:
                  enabled: "yes"
            """
        )
    )
    with pytest.raises(ValueError, match="enabled"):
        _load(cfg_file)


def test_load_invalid_effective_window_raises(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        textwrap.dedent(
            """\
            schedule:
              work_start: "08:00"
              work_end: "18:00"
              work_days: [0, 1, 2, 3, 4]
              day_overrides:
                4:
                  work_start: "15:00"
                  work_end: "14:00"
            """
        )
    )
    with pytest.raises(ValueError, match="work_start"):
        _load(cfg_file)


def test_load_base_invalid_window_raises(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        textwrap.dedent(
            """\
            schedule:
              work_start: "18:00"
              work_end: "08:00"
              work_days: [0, 1, 2, 3, 4]
            """
        )
    )
    with pytest.raises(ValueError, match="work_start"):
        _load(cfg_file)


# -- Module-level constants ----------------------------------------------------

def test_module_constants_match_loaded_config():
    cfg = _load()
    assert config_module.IDLE_TIME_SECONDS == cfg["IDLE_TIME_SECONDS"]
    assert config_module.MOVE_INTERVAL_SECONDS == cfg["MOVE_INTERVAL_SECONDS"]
    assert config_module.WORK_START_TIME == cfg["WORK_START_TIME"]
    assert config_module.WORK_END_TIME == cfg["WORK_END_TIME"]
    assert config_module.WORK_DAYS == cfg["WORK_DAYS"]
    assert config_module.SCHEDULE_TIMEZONE == cfg["SCHEDULE_TIMEZONE"]
    assert config_module.SCHEDULE_TIMEZONE_LABEL == cfg["SCHEDULE_TIMEZONE_LABEL"]
    assert config_module.DAY_OVERRIDES == cfg["DAY_OVERRIDES"]
    assert config_module.LUNCH_START_TIME == cfg["LUNCH_START_TIME"]
    assert config_module.LUNCH_DURATION_MINUTES == cfg["LUNCH_DURATION_MINUTES"]


def test_module_has_no_removed_constants():
    assert not hasattr(config_module, "MOVE_DISTANCE_PIXELS")
    assert not hasattr(config_module, "SEND_KEYSTROKES")


# -- Scheduler trigger conversion ----------------------------------------------

def test_scheduler_entries_are_local_when_timezone_unset(monkeypatch):
    monkeypatch.setattr(config_module, "SCHEDULE_TIMEZONE", None)
    monkeypatch.setattr(config_module, "get_enabled_day_start_times", lambda: {0: (8, 0), 4: (14, 30)})
    entries = get_local_scheduler_trigger_entries()
    assert entries == [(0, 8, 0), (4, 14, 30)]


def test_scheduler_entries_convert_named_timezone_to_local(monkeypatch):
    monkeypatch.setattr(config_module, "SCHEDULE_TIMEZONE", "America/Bogota")
    monkeypatch.setattr(config_module, "get_enabled_day_start_times", lambda: {0: (8, 0), 6: (9, 15)})
    reference_local = datetime(2026, 1, 5, 12, 0, tzinfo=ZoneInfo("Europe/Madrid"))
    entries = get_local_scheduler_trigger_entries(reference_local=reference_local)
    assert entries == [(0, 14, 0), (6, 15, 15)]


def test_scheduler_entries_require_aware_reference_when_provided(monkeypatch):
    monkeypatch.setattr(config_module, "SCHEDULE_TIMEZONE", "America/Bogota")
    monkeypatch.setattr(config_module, "get_enabled_day_start_times", lambda: {0: (8, 0)})
    with pytest.raises(ValueError, match="timezone-aware"):
        get_local_scheduler_trigger_entries(reference_local=datetime(2026, 1, 5, 12, 0))
