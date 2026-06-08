"""
config.py — loads conf/config.yaml and exposes all user-facing constants.

The loader walks up from this file until it finds pyproject.toml, which marks
the project root.  conf/config.yaml is then resolved relative to that root.
This means the module works correctly whether the package is run from source
(uv run deskghost) or installed into a venv.
"""

from __future__ import annotations

from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from typing import TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml


# ── Locate project root ───────────────────────────────────────────────────────

def _find_project_root() -> Path:
    """Walk up from this file until a directory containing pyproject.toml is found."""
    current = Path(__file__).resolve().parent
    while True:
        if (current / "pyproject.toml").exists():
            return current
        parent = current.parent
        if parent == current:
            raise FileNotFoundError(
                "Could not locate project root (no pyproject.toml found in any "
                f"parent directory of {__file__})"
            )
        current = parent


# ── YAML parsing helpers ──────────────────────────────────────────────────────


class DayOverride(TypedDict, total=False):
    enabled: bool
    work_start: tuple[int, int]
    work_end: tuple[int, int]


def _require_mapping(value: object, field: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"Config field '{field}' must be a mapping/object, got: {value!r}")
    return value

def _parse_hhmm(value: str, field: str) -> tuple[int, int]:
    """Convert a 'HH:MM' string to a (hour, minute) tuple."""
    try:
        h, m = value.split(":")
        hour, minute = int(h), int(m)
    except (ValueError, AttributeError):
        raise ValueError(
            f"Config field '{field}' must be a time string in HH:MM format, "
            f"got: {value!r}"
        )
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(
            f"Config field '{field}' has out-of-range time {value!r} "
            f"(hour must be 0-23, minute 0-59)"
        )
    return (hour, minute)


def _require_int(value: object, field: str, min_val: int = 1) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(
            f"Config field '{field}' must be an integer, got: {value!r}"
        )
    if value < min_val:
        raise ValueError(
            f"Config field '{field}' must be >= {min_val}, got: {value!r}"
        )
    return value


def _require_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(
            f"Config field '{field}' must be a boolean, got: {value!r}"
        )
    return value


def _parse_weekday(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"Config field '{field}' must be a weekday integer 0-6, got: {value!r}")
    if isinstance(value, int):
        day = value
    elif isinstance(value, str) and value.strip().isdigit():
        day = int(value.strip())
    else:
        raise ValueError(f"Config field '{field}' must be a weekday integer 0-6, got: {value!r}")
    if not 0 <= day <= 6:
        raise ValueError(f"Config field '{field}' weekday must be in range 0-6, got: {value!r}")
    return day


def _parse_work_days(value: object, field: str) -> set[int]:
    if not isinstance(value, (list, tuple, set)):
        raise ValueError(
            f"Config field '{field}' must be a list/set of weekday integers 0-6, got: {value!r}"
        )
    return {_parse_weekday(day, f"{field}[]") for day in value}


def _parse_timezone(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"Config field '{field}' must be an IANA timezone string "
            f"(for example 'America/Bogota'), got: {value!r}"
        )
    name = value.strip()
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            f"Config field '{field}' has unknown timezone {name!r}. "
            "Use a valid IANA timezone like 'America/Bogota' or 'Europe/Madrid'."
        ) from exc
    return name


def _time_to_minutes(value: tuple[int, int]) -> int:
    return value[0] * 60 + value[1]


def _parse_day_overrides(value: object, field: str) -> dict[int, DayOverride]:
    if value is None:
        return {}
    mapping = _require_mapping(value, field)

    parsed: dict[int, DayOverride] = {}
    for raw_day, raw_override in mapping.items():
        day = _parse_weekday(raw_day, f"{field} key")
        if day in parsed:
            raise ValueError(f"Config field '{field}' contains duplicate override for weekday {day}")

        override_mapping = _require_mapping(raw_override, f"{field}.{day}")
        override: DayOverride = {}
        for key, raw_val in override_mapping.items():
            if key == "enabled":
                if not isinstance(raw_val, bool):
                    raise ValueError(
                        f"Config field '{field}.{day}.enabled' must be boolean, got: {raw_val!r}"
                    )
                override["enabled"] = raw_val
            elif key == "work_start":
                override["work_start"] = _parse_hhmm(raw_val, f"{field}.{day}.work_start")
            elif key == "work_end":
                override["work_end"] = _parse_hhmm(raw_val, f"{field}.{day}.work_end")
            else:
                raise ValueError(
                    f"Config field '{field}.{day}' has unknown key {key!r}. "
                    "Allowed keys: enabled, work_start, work_end"
                )

        if not override:
            raise ValueError(
                f"Config field '{field}.{day}' must define at least one of: "
                "enabled, work_start, work_end"
            )

        if "work_start" in override and "work_end" in override:
            if _time_to_minutes(override["work_start"]) >= _time_to_minutes(override["work_end"]):
                raise ValueError(
                    f"Config field '{field}.{day}' has invalid window: "
                    "work_start must be earlier than work_end"
                )

        parsed[day] = override

    return parsed


def _local_timezone_label() -> str:
    tz = datetime.now().astimezone().tzinfo
    if isinstance(tz, ZoneInfo):
        return tz.key
    if tz is None:
        return "local"
    return str(tz)


def _validate_effective_windows(
    work_days: set[int],
    work_start: tuple[int, int],
    work_end: tuple[int, int],
    day_overrides: dict[int, DayOverride],
) -> None:
    base_start = _time_to_minutes(work_start)
    base_end = _time_to_minutes(work_end)
    if base_start >= base_end:
        raise ValueError("Config field 'schedule' has invalid window: work_start must be earlier than work_end")

    for day in range(7):
        enabled = day in work_days
        start = work_start
        end = work_end
        override = day_overrides.get(day)
        if override is not None:
            if "enabled" in override:
                enabled = override["enabled"]
            if "work_start" in override:
                start = override["work_start"]
            if "work_end" in override:
                end = override["work_end"]

        if enabled and _time_to_minutes(start) >= _time_to_minutes(end):
            raise ValueError(
                f"Config field 'schedule.day_overrides' produces invalid window for weekday {day}: "
                "work_start must be earlier than work_end"
            )


# ── Loader ────────────────────────────────────────────────────────────────────

def _load(path: Path | None = None) -> dict:
    """Load and validate config.yaml; return a dict of typed constants."""
    if path is None:
        path = _find_project_root() / "conf" / "config.yaml"

    if not path.exists():
        raise FileNotFoundError(
            f"DeskGhost config file not found: {path}\n"
            "Create conf/config.yaml in the project root or check the path."
        )

    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    if not isinstance(raw, dict):
        raise ValueError(f"Config file {path} must contain a YAML mapping at the top level.")

    nudge = _require_mapping(raw.get("nudge", {}), "nudge")
    schedule = _require_mapping(raw.get("schedule", {}), "schedule")
    lunch = _require_mapping(raw.get("lunch", {}), "lunch")
    manual = _require_mapping(raw.get("manual", {}), "manual")

    work_start = _parse_hhmm(schedule.get("work_start", "07:00"), "schedule.work_start")
    work_end = _parse_hhmm(schedule.get("work_end", "18:00"), "schedule.work_end")
    work_days = _parse_work_days(schedule.get("work_days", [0, 1, 2, 3, 4]), "schedule.work_days")
    schedule_timezone = _parse_timezone(schedule.get("timezone"), "schedule.timezone")
    day_overrides = _parse_day_overrides(schedule.get("day_overrides", {}), "schedule.day_overrides")
    _validate_effective_windows(work_days, work_start, work_end, day_overrides)

    return {
        "IDLE_TIME_SECONDS":      _require_int(nudge.get("idle_time_seconds", 120),    "nudge.idle_time_seconds"),
        "MOVE_INTERVAL_SECONDS":  _require_int(nudge.get("move_interval_seconds", 5),  "nudge.move_interval_seconds"),
        "WORK_START_TIME":        work_start,
        "WORK_END_TIME":          work_end,
        "WORK_DAYS":              work_days,
        "SCHEDULE_TIMEZONE":      schedule_timezone,
        "SCHEDULE_TIMEZONE_LABEL": schedule_timezone or _local_timezone_label(),
        "DAY_OVERRIDES":          day_overrides,
        "LUNCH_START_TIME":       _parse_hhmm(lunch.get("start", "12:30"),             "lunch.start"),
        "LUNCH_DURATION_MINUTES": _require_int(lunch.get("duration_minutes", 60),      "lunch.duration_minutes"),
        "MANUAL_ALWAYS_ON":       _require_bool(manual.get("always_on", False),         "manual.always_on"),
    }


# ── Module-level constants (imported by schedule.py and the rest of the app) ──

_cfg = _load()

IDLE_TIME_SECONDS:      int             = _cfg["IDLE_TIME_SECONDS"]
MOVE_INTERVAL_SECONDS:  int             = _cfg["MOVE_INTERVAL_SECONDS"]
WORK_START_TIME:        tuple[int, int] = _cfg["WORK_START_TIME"]
WORK_END_TIME:          tuple[int, int] = _cfg["WORK_END_TIME"]
WORK_DAYS:              set[int]        = _cfg["WORK_DAYS"]
SCHEDULE_TIMEZONE:      str | None      = _cfg["SCHEDULE_TIMEZONE"]
SCHEDULE_TIMEZONE_LABEL: str            = _cfg["SCHEDULE_TIMEZONE_LABEL"]
DAY_OVERRIDES:          dict[int, DayOverride] = _cfg["DAY_OVERRIDES"]
LUNCH_START_TIME:       tuple[int, int] = _cfg["LUNCH_START_TIME"]
LUNCH_DURATION_MINUTES: int             = _cfg["LUNCH_DURATION_MINUTES"]
MANUAL_ALWAYS_ON:       bool            = _cfg["MANUAL_ALWAYS_ON"]


def get_effective_day_schedule(weekday: int) -> tuple[bool, tuple[int, int], tuple[int, int]]:
    """Return (enabled, start, end) for a weekday after applying overrides."""
    day = _parse_weekday(weekday, "weekday")
    enabled = day in WORK_DAYS
    start = WORK_START_TIME
    end = WORK_END_TIME

    override = DAY_OVERRIDES.get(day)
    if override is not None:
        if "enabled" in override:
            enabled = override["enabled"]
        if "work_start" in override:
            start = override["work_start"]
        if "work_end" in override:
            end = override["work_end"]

    return (enabled, start, end)


def get_enabled_day_start_times() -> dict[int, tuple[int, int]]:
    """Return {weekday: effective_work_start} for all enabled weekdays."""
    starts: dict[int, tuple[int, int]] = {}
    for day in range(7):
        enabled, start, _ = get_effective_day_schedule(day)
        if enabled:
            starts[day] = start
    return starts


def get_local_scheduler_trigger_entries(
    reference_local: datetime | None = None,
) -> list[tuple[int, int, int]]:
    """Return local scheduler entries as (weekday, hour, minute).

    Weekday uses Python's convention: 0=Monday ... 6=Sunday.
    """
    starts = get_enabled_day_start_times()
    if not starts:
        return []

    if SCHEDULE_TIMEZONE is None:
        return sorted((day, start[0], start[1]) for day, start in starts.items())

    if reference_local is not None:
        if reference_local.tzinfo is None:
            raise ValueError("reference_local must be timezone-aware")
        local_now = reference_local
    else:
        local_now = datetime.now().astimezone()
    local_tz = local_now.tzinfo
    if local_tz is None:
        raise ValueError("Could not resolve local timezone for scheduler trigger conversion")

    schedule_tz = ZoneInfo(SCHEDULE_TIMEZONE)
    schedule_now = local_now.astimezone(schedule_tz)
    monday = schedule_now.date() - timedelta(days=schedule_now.weekday())

    entries: set[tuple[int, int, int]] = set()
    for day, start in starts.items():
        schedule_dt = datetime.combine(
            monday + timedelta(days=day),
            dt_time(start[0], start[1]),
            tzinfo=schedule_tz,
        )
        local_dt = schedule_dt.astimezone(local_tz)
        entries.add((local_dt.weekday(), local_dt.hour, local_dt.minute))

    return sorted(entries)
