"""
config.py — loads conf/config.yaml and exposes all user-facing constants.

The loader walks up from this file until it finds pyproject.toml, which marks
the project root.  conf/config.yaml is then resolved relative to that root.
This means the module works correctly whether the package is run from source
(uv run deskghost) or installed into a venv.
"""

from __future__ import annotations

from pathlib import Path

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

    nudge    = raw.get("nudge", {})
    schedule = raw.get("schedule", {})
    lunch    = raw.get("lunch", {})

    return {
        "IDLE_TIME_SECONDS":      _require_int(nudge.get("idle_time_seconds", 120),    "nudge.idle_time_seconds"),
        "MOVE_INTERVAL_SECONDS":  _require_int(nudge.get("move_interval_seconds", 5),  "nudge.move_interval_seconds"),
        "WORK_START_TIME":        _parse_hhmm(schedule.get("work_start", "07:00"),     "schedule.work_start"),
        "WORK_END_TIME":          _parse_hhmm(schedule.get("work_end",   "18:00"),     "schedule.work_end"),
        "WORK_DAYS":              set(schedule.get("work_days", [0, 1, 2, 3, 4])),
        "LUNCH_START_TIME":       _parse_hhmm(lunch.get("start", "12:30"),             "lunch.start"),
        "LUNCH_DURATION_MINUTES": _require_int(lunch.get("duration_minutes", 60),      "lunch.duration_minutes"),
    }


# ── Module-level constants (imported by schedule.py and the rest of the app) ──

_cfg = _load()

IDLE_TIME_SECONDS:      int             = _cfg["IDLE_TIME_SECONDS"]
MOVE_INTERVAL_SECONDS:  int             = _cfg["MOVE_INTERVAL_SECONDS"]
WORK_START_TIME:        tuple[int, int] = _cfg["WORK_START_TIME"]
WORK_END_TIME:          tuple[int, int] = _cfg["WORK_END_TIME"]
WORK_DAYS:              set[int]        = _cfg["WORK_DAYS"]
LUNCH_START_TIME:       tuple[int, int] = _cfg["LUNCH_START_TIME"]
LUNCH_DURATION_MINUTES: int             = _cfg["LUNCH_DURATION_MINUTES"]
