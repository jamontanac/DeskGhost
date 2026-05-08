"""Installation smoke tests for DeskGhost.

These tests verify that the OS-level scheduler integration (launchd on macOS,
Task Scheduler on Windows) is correctly set up.  They are **skipped
automatically** when the agent / task has not been installed on the current
machine, so they never fail in a clean development environment.

Run after ``bash scripts/setup.sh install`` (macOS) or
``scripts\\setup.ps1 install`` (Windows) to confirm everything is wired up
correctly.

    uv run pytest tests/test_install.py -v
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    """Return the repository root (directory containing pyproject.toml)."""
    current = Path(__file__).resolve().parent
    while True:
        if (current / "pyproject.toml").exists():
            return current
        parent = current.parent
        if parent == current:
            raise FileNotFoundError("Could not locate project root")
        current = parent


PROJECT_ROOT = _project_root()

# ---------------------------------------------------------------------------
# macOS tests
# ---------------------------------------------------------------------------

MACOS_LABEL = "com.deskghost.agent"
MACOS_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{MACOS_LABEL}.plist"

# Skip the entire macOS block on non-macOS or when the agent is not installed
macos_installed = pytest.mark.skipif(
    sys.platform != "darwin" or not MACOS_PLIST.exists(),
    reason="macOS LaunchAgent not installed — run 'bash scripts/setup.sh install' first",
)


@macos_installed
class TestMacOSLaunchAgent:
    """Verify the launchd plist is present, valid, and correctly configured."""

    def _parse_plist(self) -> dict:
        import plistlib
        with MACOS_PLIST.open("rb") as fh:
            return plistlib.load(fh)

    def test_plist_file_exists(self):
        assert MACOS_PLIST.exists(), f"Plist not found: {MACOS_PLIST}"

    def test_plist_is_valid_xml(self):
        result = subprocess.run(
            ["plutil", "-lint", str(MACOS_PLIST)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"plutil -lint failed:\n{result.stdout}\n{result.stderr}"

    def test_plist_label_matches(self):
        plist = self._parse_plist()
        assert plist.get("Label") == MACOS_LABEL

    def test_plist_run_at_load_is_true(self):
        """RunAtLoad must be present and True so DeskGhost starts on login."""
        plist = self._parse_plist()
        assert plist.get("RunAtLoad") is True, (
            "RunAtLoad is missing or False — DeskGhost will not start on login. "
            "Re-run 'bash scripts/setup.sh install'."
        )

    def test_plist_keep_alive_is_false(self):
        """KeepAlive must be False — the app self-exits after work hours."""
        plist = self._parse_plist()
        assert plist.get("KeepAlive") is False

    def test_plist_has_five_weekday_calendar_entries(self):
        """StartCalendarInterval must have exactly 5 entries (Mon–Fri)."""
        plist = self._parse_plist()
        entries = plist.get("StartCalendarInterval", [])
        assert len(entries) == 5, (
            f"Expected 5 weekday entries in StartCalendarInterval, got {len(entries)}"
        )

    def test_plist_calendar_hour_matches_config(self):
        """The Hour in the plist must match WORK_START_TIME from conf/config.yaml."""
        from deskghost.config import WORK_START_TIME
        plist = self._parse_plist()
        entries = plist.get("StartCalendarInterval", [])
        for entry in entries:
            assert entry["Hour"] == WORK_START_TIME[0], (
                f"Plist Hour {entry['Hour']} does not match config {WORK_START_TIME[0]}. "
                "Re-run 'bash scripts/setup.sh install' after changing conf/config.yaml."
            )

    def test_plist_calendar_minute_matches_config(self):
        """The Minute in the plist must match WORK_START_TIME from conf/config.yaml."""
        from deskghost.config import WORK_START_TIME
        plist = self._parse_plist()
        entries = plist.get("StartCalendarInterval", [])
        for entry in entries:
            assert entry["Minute"] == WORK_START_TIME[1], (
                f"Plist Minute {entry['Minute']} does not match config {WORK_START_TIME[1]}. "
                "Re-run 'bash scripts/setup.sh install' after changing conf/config.yaml."
            )

    def test_plist_working_directory_points_to_project(self):
        plist = self._parse_plist()
        wd = plist.get("WorkingDirectory", "")
        assert Path(wd).resolve() == PROJECT_ROOT.resolve(), (
            f"WorkingDirectory in plist ({wd}) does not match project root ({PROJECT_ROOT})."
        )

    def test_agent_is_loaded_in_launchctl(self):
        """The agent must be loaded (not just installed) in launchctl."""
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True, text=True,
        )
        assert MACOS_LABEL in result.stdout, (
            f"Agent '{MACOS_LABEL}' is not loaded. "
            "Run 'bash scripts/setup.sh install' or 'launchctl load' the plist."
        )

    def test_lock_directory_is_writable(self):
        """~/.deskghost must exist and be writable so the lock file can be created."""
        lock_dir = Path.home() / ".deskghost"
        assert lock_dir.exists(), f"Lock/log directory does not exist: {lock_dir}"
        assert lock_dir.is_dir()
        # Try creating a temp file to confirm write access
        probe = lock_dir / ".write_probe"
        try:
            probe.touch()
        finally:
            probe.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Windows tests
# ---------------------------------------------------------------------------

WINDOWS_TASK_NAME = "DeskGhost"

# Skip the entire Windows block on non-Windows or when the task is not registered
windows_installed = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows Task Scheduler tests only run on Windows",
)


def _windows_task_exists() -> bool:
    result = subprocess.run(
        ["schtasks", "/query", "/tn", WINDOWS_TASK_NAME],
        capture_output=True,
    )
    return result.returncode == 0


@windows_installed
class TestWindowsScheduledTask:
    """Verify the Task Scheduler task is registered and correctly configured."""

    @pytest.fixture(autouse=True)
    def require_task(self):
        if not _windows_task_exists():
            pytest.skip(
                f"Scheduled task '{WINDOWS_TASK_NAME}' not found — "
                "run '.\\scripts\\setup.ps1 install' first"
            )

    def _query_xml(self) -> str:
        """Return the task XML via schtasks /query /xml."""
        result = subprocess.run(
            ["schtasks", "/query", "/tn", WINDOWS_TASK_NAME, "/xml"],
            capture_output=True, text=True, encoding="utf-16",
        )
        assert result.returncode == 0, f"schtasks /query failed: {result.stderr}"
        return result.stdout

    def test_task_exists(self):
        assert _windows_task_exists()

    def test_task_has_logon_trigger(self):
        """Task must include a LogonTrigger so it fires at user login."""
        xml = self._query_xml()
        assert "LogonTrigger" in xml, (
            "No LogonTrigger found in task XML. "
            "Re-run '.\\scripts\\setup.ps1 install'."
        )

    def test_task_has_calendar_trigger(self):
        """Task must include a CalendarTrigger for the daily time-based start."""
        xml = self._query_xml()
        assert "CalendarTrigger" in xml or "ScheduleByWeek" in xml, (
            "No CalendarTrigger found in task XML. "
            "Re-run '.\\scripts\\setup.ps1 install'."
        )

    def test_task_start_when_available(self):
        """StartWhenAvailable must be true so missed triggers fire on wake."""
        xml = self._query_xml()
        assert "<StartWhenAvailable>true</StartWhenAvailable>" in xml, (
            "StartWhenAvailable is not set. "
            "Re-run '.\\scripts\\setup.ps1 install'."
        )

    def test_task_multiple_instances_ignore_new(self):
        """MultipleInstancesPolicy must be IgnoreNew — belt-and-suspenders guard
        alongside the in-process lock."""
        xml = self._query_xml()
        assert "IgnoreNew" in xml, (
            "MultipleInstancesPolicy is not IgnoreNew. "
            "Re-run '.\\scripts\\setup.ps1 install'."
        )

    def test_lock_directory_is_writable(self):
        """The lock/log directory must exist and be writable."""
        lock_dir = Path.home() / ".deskghost"
        assert lock_dir.exists(), f"Lock/log directory does not exist: {lock_dir}"
        probe = lock_dir / ".write_probe"
        try:
            probe.touch()
        finally:
            probe.unlink(missing_ok=True)
