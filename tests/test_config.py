"""
tests/test_config.py — unit tests for src/deskghost/config.py

Tests cover:
  - Loading the real conf/config.yaml returns correct typed values
  - HH:MM strings are parsed to (hour, minute) tuples
  - Missing config file raises FileNotFoundError with a helpful message
  - Invalid types raise ValueError with a helpful message
  - Out-of-range time values raise ValueError
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

import deskghost.config as config_module
from deskghost.config import _load, _parse_hhmm, _require_int


# ── _parse_hhmm ───────────────────────────────────────────────────────────────

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


# ── _require_int ──────────────────────────────────────────────────────────────

def test_require_int_valid():
    assert _require_int(120, "nudge.idle_time_seconds") == 120


def test_require_int_rejects_string():
    with pytest.raises(ValueError, match="integer"):
        _require_int("120", "nudge.idle_time_seconds")  # type: ignore[arg-type]


def test_require_int_rejects_bool():
    # bool is a subclass of int in Python — must be rejected explicitly
    with pytest.raises(ValueError, match="integer"):
        _require_int(True, "nudge.idle_time_seconds")


def test_require_int_rejects_below_minimum():
    with pytest.raises(ValueError, match=">= 1"):
        _require_int(0, "nudge.idle_time_seconds")


# ── _load: real config.yaml ───────────────────────────────────────────────────

def test_load_real_config_returns_all_keys():
    cfg = _load()
    expected_keys = {
        "IDLE_TIME_SECONDS", "MOVE_INTERVAL_SECONDS",
        "WORK_START_TIME", "WORK_END_TIME", "WORK_DAYS",
        "LUNCH_START_TIME", "LUNCH_DURATION_MINUTES",
    }
    assert expected_keys <= cfg.keys()


def test_load_code_default_values(tmp_path):
    """When all config keys are absent, _load() must fall back to built-in defaults."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("{}\n")  # empty mapping → every .get() uses its default
    cfg = _load(cfg_file)
    assert cfg["IDLE_TIME_SECONDS"]      == 120
    assert cfg["MOVE_INTERVAL_SECONDS"]  == 5
    assert cfg["WORK_START_TIME"]        == (7, 0)
    assert cfg["WORK_END_TIME"]          == (18, 0)
    assert cfg["WORK_DAYS"]              == {0, 1, 2, 3, 4}
    assert cfg["LUNCH_START_TIME"]       == (12, 30)
    assert cfg["LUNCH_DURATION_MINUTES"] == 60


def test_load_real_config_types():
    cfg = _load()
    assert isinstance(cfg["IDLE_TIME_SECONDS"],      int)
    assert isinstance(cfg["MOVE_INTERVAL_SECONDS"],  int)
    assert isinstance(cfg["WORK_START_TIME"],        tuple)
    assert isinstance(cfg["WORK_END_TIME"],          tuple)
    assert isinstance(cfg["WORK_DAYS"],              set)
    assert isinstance(cfg["LUNCH_START_TIME"],       tuple)
    assert isinstance(cfg["LUNCH_DURATION_MINUTES"], int)


# ── _load: custom path ────────────────────────────────────────────────────────

def test_load_missing_file_raises_file_not_found(tmp_path):
    missing = tmp_path / "nonexistent.yaml"
    with pytest.raises(FileNotFoundError, match="conf/config.yaml|nonexistent"):
        _load(missing)


def test_load_custom_path_overrides_values(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(textwrap.dedent("""\
        nudge:
          idle_time_seconds: 300
          move_interval_seconds: 10
        schedule:
          work_start: "08:30"
          work_end: "17:00"
          work_days: [0, 1, 2, 3, 4]
        lunch:
          start: "13:00"
          duration_minutes: 45
    """))
    cfg = _load(cfg_file)
    assert cfg["IDLE_TIME_SECONDS"]      == 300
    assert cfg["MOVE_INTERVAL_SECONDS"]  == 10
    assert cfg["WORK_START_TIME"]        == (8, 30)
    assert cfg["WORK_END_TIME"]          == (17, 0)
    assert cfg["LUNCH_START_TIME"]       == (13, 0)
    assert cfg["LUNCH_DURATION_MINUTES"] == 45


def test_load_invalid_idle_time_type_raises(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(textwrap.dedent("""\
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
    """))
    with pytest.raises(ValueError, match="nudge.idle_time_seconds"):
        _load(cfg_file)


def test_load_invalid_time_string_raises(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(textwrap.dedent("""\
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
    """))
    with pytest.raises(ValueError, match="schedule.work_start"):
        _load(cfg_file)


# ── Module-level constants match _load() ─────────────────────────────────────

def test_module_constants_match_loaded_config():
    cfg = _load()
    assert config_module.IDLE_TIME_SECONDS      == cfg["IDLE_TIME_SECONDS"]
    assert config_module.MOVE_INTERVAL_SECONDS  == cfg["MOVE_INTERVAL_SECONDS"]
    assert config_module.WORK_START_TIME        == cfg["WORK_START_TIME"]
    assert config_module.WORK_END_TIME          == cfg["WORK_END_TIME"]
    assert config_module.WORK_DAYS              == cfg["WORK_DAYS"]
    assert config_module.LUNCH_START_TIME       == cfg["LUNCH_START_TIME"]
    assert config_module.LUNCH_DURATION_MINUTES == cfg["LUNCH_DURATION_MINUTES"]


def test_module_has_no_removed_constants():
    """Verify removed config keys are truly gone from the module."""
    assert not hasattr(config_module, "MOVE_DISTANCE_PIXELS")
    assert not hasattr(config_module, "SEND_KEYSTROKES")
