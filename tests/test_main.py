"""Tests for deskghost.main — platform-agnostic loop logic.

The platform watcher is replaced with FakeWatcher so these tests run on
any OS.  schedule helpers and time are patched to drive each branch.
"""

import sys
import importlib
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import FakeWatcher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reload_main(fake_watcher: FakeWatcher, mocker, is_work: list, is_lunch: list):
    """Reload deskghost.main with mocked dependencies.

    ``is_work`` and ``is_lunch`` are consumed as side_effect sequences so
    each loop iteration returns the next value.  When the list is exhausted
    the loop exits (is_work_hours returns False).
    """
    # Patch the watcher class so main() gets our FakeWatcher
    mocker.patch("deskghost.main.ActivityWatcher", return_value=fake_watcher)
    mocker.patch("deskghost.main.is_work_hours", side_effect=is_work)
    mocker.patch("deskghost.main.is_lunch_time", side_effect=is_lunch)
    # Prevent real sleeping
    mocker.patch("deskghost.main.time.sleep")
    # Silence logger output during tests
    mocker.patch("deskghost.main.get_logger", return_value=MagicMock())
    mocker.patch("deskghost.main.ThrottledLogger", return_value=MagicMock())


# ---------------------------------------------------------------------------
# Outside work hours
# ---------------------------------------------------------------------------

class TestMainOutsideWorkHours:
    def test_exits_immediately_when_not_work_hours(self, fake_watcher, mocker):
        _reload_main(fake_watcher, mocker, is_work=[False], is_lunch=[])
        import deskghost.main as main_mod
        result = main_mod.main()
        assert result == 0

    def test_cleanup_called_on_normal_exit(self, fake_watcher, mocker):
        _reload_main(fake_watcher, mocker, is_work=[False], is_lunch=[])
        import deskghost.main as main_mod
        main_mod.main()
        assert fake_watcher.cleanup_calls == 1

    def test_no_nudge_when_not_work_hours(self, fake_watcher, mocker):
        _reload_main(fake_watcher, mocker, is_work=[False], is_lunch=[])
        import deskghost.main as main_mod
        main_mod.main()
        assert fake_watcher.nudge_calls == 0


# ---------------------------------------------------------------------------
# Lunch branch
# ---------------------------------------------------------------------------

class TestMainLunchBranch:
    def test_nudge_called_during_lunch(self, fake_watcher, mocker):
        # One lunch iteration, then exit
        _reload_main(fake_watcher, mocker, is_work=[True, False], is_lunch=[True])
        import deskghost.main as main_mod
        main_mod.main()
        assert fake_watcher.nudge_calls == 1

    def test_cleanup_called_after_lunch_exit(self, fake_watcher, mocker):
        _reload_main(fake_watcher, mocker, is_work=[True, False], is_lunch=[True])
        import deskghost.main as main_mod
        main_mod.main()
        assert fake_watcher.cleanup_calls == 1

    def test_reset_idle_called_when_returning_from_lunch(self, fake_watcher, mocker):
        # First iteration: lunch. Second: post-lunch (in_lunch=True, is_lunch=False). Third: exit.
        _reload_main(
            fake_watcher, mocker,
            is_work=[True, True, False],
            is_lunch=[True, False],
        )
        import deskghost.main as main_mod
        main_mod.main()
        assert fake_watcher.reset_calls == 1

    def test_no_nudge_on_post_lunch_transition(self, fake_watcher, mocker):
        _reload_main(
            fake_watcher, mocker,
            is_work=[True, True, False],
            is_lunch=[True, False],
        )
        import deskghost.main as main_mod
        main_mod.main()
        # nudge only happened during the lunch iteration, not during the transition
        assert fake_watcher.nudge_calls == 1


# ---------------------------------------------------------------------------
# Idle branch
# ---------------------------------------------------------------------------

class TestMainIdleBranch:
    def test_nudge_called_when_idle_threshold_exceeded(self, fake_watcher, mocker):
        fake_watcher.set_idle_time(999.0)
        _reload_main(fake_watcher, mocker, is_work=[True, False], is_lunch=[False])
        import deskghost.main as main_mod
        main_mod.main()
        assert fake_watcher.nudge_calls == 1

    def test_no_nudge_when_idle_time_below_threshold(self, fake_watcher, mocker):
        fake_watcher.set_idle_time(1.0)
        _reload_main(fake_watcher, mocker, is_work=[True, False], is_lunch=[False])
        import deskghost.main as main_mod
        main_mod.main()
        assert fake_watcher.nudge_calls == 0


# ---------------------------------------------------------------------------
# Keyboard interrupt
# ---------------------------------------------------------------------------

class TestMainKeyboardInterrupt:
    def test_keyboard_interrupt_returns_130(self, fake_watcher, mocker):
        mocker.patch("deskghost.main.ActivityWatcher", return_value=fake_watcher)
        mocker.patch("deskghost.main.is_work_hours", side_effect=KeyboardInterrupt)
        mocker.patch("deskghost.main.time.sleep")
        mocker.patch("deskghost.main.get_logger", return_value=MagicMock())
        mocker.patch("deskghost.main.ThrottledLogger", return_value=MagicMock())
        import deskghost.main as main_mod
        result = main_mod.main()
        assert result == 130

    def test_cleanup_called_on_keyboard_interrupt(self, fake_watcher, mocker):
        mocker.patch("deskghost.main.ActivityWatcher", return_value=fake_watcher)
        mocker.patch("deskghost.main.is_work_hours", side_effect=KeyboardInterrupt)
        mocker.patch("deskghost.main.time.sleep")
        mocker.patch("deskghost.main.get_logger", return_value=MagicMock())
        mocker.patch("deskghost.main.ThrottledLogger", return_value=MagicMock())
        import deskghost.main as main_mod
        main_mod.main()
        assert fake_watcher.cleanup_calls == 1
