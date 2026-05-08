"""Tests for deskghost.main — platform-agnostic loop logic.

The platform watcher is replaced with FakeWatcher so these tests run on
any OS.  schedule helpers and time are patched to drive each branch.

All tests that exercise the main loop also request the ``patch_instance_lock``
fixture (defined in conftest.py) so they never touch the real lock file on
disk.  Two dedicated tests at the bottom verify the lock-guard logic itself.
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
    mocker.patch("deskghost.main.configure_file_logging", return_value="/fake/log")


# ---------------------------------------------------------------------------
# Outside work hours
# ---------------------------------------------------------------------------

class TestMainOutsideWorkHours:
    def test_exits_immediately_when_not_work_hours(self, fake_watcher, mocker, patch_instance_lock):
        _reload_main(fake_watcher, mocker, is_work=[False], is_lunch=[])
        import deskghost.main as main_mod
        result = main_mod.main()
        assert result == 0

    def test_cleanup_called_on_normal_exit(self, fake_watcher, mocker, patch_instance_lock):
        _reload_main(fake_watcher, mocker, is_work=[False], is_lunch=[])
        import deskghost.main as main_mod
        main_mod.main()
        assert fake_watcher.cleanup_calls == 1

    def test_no_nudge_when_not_work_hours(self, fake_watcher, mocker, patch_instance_lock):
        _reload_main(fake_watcher, mocker, is_work=[False], is_lunch=[])
        import deskghost.main as main_mod
        main_mod.main()
        assert fake_watcher.nudge_calls == 0


# ---------------------------------------------------------------------------
# Lunch branch
# ---------------------------------------------------------------------------

class TestMainLunchBranch:
    def test_prevent_display_sleep_called_during_lunch(self, fake_watcher, mocker, patch_instance_lock):
        # One lunch iteration, then exit
        _reload_main(fake_watcher, mocker, is_work=[True, False], is_lunch=[True])
        import deskghost.main as main_mod
        main_mod.main()
        assert fake_watcher.prevent_display_sleep_calls == 1

    def test_no_nudge_during_lunch(self, fake_watcher, mocker, patch_instance_lock):
        # Lunch must NOT call nudge_mouse — display is kept alive via caffeinate, not cursor movement
        _reload_main(fake_watcher, mocker, is_work=[True, False], is_lunch=[True])
        import deskghost.main as main_mod
        main_mod.main()
        assert fake_watcher.nudge_calls == 0

    def test_cleanup_called_after_lunch_exit(self, fake_watcher, mocker, patch_instance_lock):
        _reload_main(fake_watcher, mocker, is_work=[True, False], is_lunch=[True])
        import deskghost.main as main_mod
        main_mod.main()
        assert fake_watcher.cleanup_calls == 1

    def test_reset_idle_called_when_returning_from_lunch(self, fake_watcher, mocker, patch_instance_lock):
        # First iteration: lunch. Second: post-lunch (in_lunch=True, is_lunch=False). Third: exit.
        _reload_main(
            fake_watcher, mocker,
            is_work=[True, True, False],
            is_lunch=[True, False],
        )
        import deskghost.main as main_mod
        main_mod.main()
        assert fake_watcher.reset_calls == 1

    def test_no_nudge_on_post_lunch_transition(self, fake_watcher, mocker, patch_instance_lock):
        _reload_main(
            fake_watcher, mocker,
            is_work=[True, True, False],
            is_lunch=[True, False],
        )
        import deskghost.main as main_mod
        main_mod.main()
        # nudge must never be called — lunch uses prevent_display_sleep, not nudge_mouse
        assert fake_watcher.nudge_calls == 0


# ---------------------------------------------------------------------------
# Idle branch
# ---------------------------------------------------------------------------

class TestMainIdleBranch:
    def test_nudge_called_when_idle_threshold_exceeded(self, fake_watcher, mocker, patch_instance_lock):
        fake_watcher.set_idle_time(999.0)
        _reload_main(fake_watcher, mocker, is_work=[True, False], is_lunch=[False])
        import deskghost.main as main_mod
        main_mod.main()
        assert fake_watcher.nudge_calls == 1

    def test_no_nudge_when_idle_time_below_threshold(self, fake_watcher, mocker, patch_instance_lock):
        fake_watcher.set_idle_time(1.0)
        _reload_main(fake_watcher, mocker, is_work=[True, False], is_lunch=[False])
        import deskghost.main as main_mod
        main_mod.main()
        assert fake_watcher.nudge_calls == 0


# ---------------------------------------------------------------------------
# Keyboard interrupt
# ---------------------------------------------------------------------------

class TestMainKeyboardInterrupt:
    def test_keyboard_interrupt_returns_130(self, fake_watcher, mocker, patch_instance_lock):
        mocker.patch("deskghost.main.ActivityWatcher", return_value=fake_watcher)
        mocker.patch("deskghost.main.is_work_hours", side_effect=KeyboardInterrupt)
        mocker.patch("deskghost.main.time.sleep")
        mocker.patch("deskghost.main.get_logger", return_value=MagicMock())
        mocker.patch("deskghost.main.ThrottledLogger", return_value=MagicMock())
        mocker.patch("deskghost.main.configure_file_logging", return_value="/fake/log")
        import deskghost.main as main_mod
        result = main_mod.main()
        assert result == 130

    def test_cleanup_called_on_keyboard_interrupt(self, fake_watcher, mocker, patch_instance_lock):
        mocker.patch("deskghost.main.ActivityWatcher", return_value=fake_watcher)
        mocker.patch("deskghost.main.is_work_hours", side_effect=KeyboardInterrupt)
        mocker.patch("deskghost.main.time.sleep")
        mocker.patch("deskghost.main.get_logger", return_value=MagicMock())
        mocker.patch("deskghost.main.ThrottledLogger", return_value=MagicMock())
        mocker.patch("deskghost.main.configure_file_logging", return_value="/fake/log")
        import deskghost.main as main_mod
        main_mod.main()
        assert fake_watcher.cleanup_calls == 1


# ---------------------------------------------------------------------------
# Lock guard — integration with InstanceLock
# ---------------------------------------------------------------------------

class TestMainLockGuard:
    def test_returns_0_immediately_when_lock_not_acquired(self, fake_watcher, mocker):
        """main() must exit with 0 and never start the watcher if the lock is held."""
        watcher_cls = mocker.patch("deskghost.main.ActivityWatcher", return_value=fake_watcher)

        # Build a mock InstanceLock whose __enter__ returns a falsy lock result
        falsy_lock = MagicMock()
        falsy_lock.__bool__ = MagicMock(return_value=False)
        mock_lock_cm = MagicMock()
        mock_lock_cm.__enter__ = MagicMock(return_value=falsy_lock)
        mock_lock_cm.__exit__ = MagicMock(return_value=False)
        mocker.patch("deskghost.main.InstanceLock", return_value=mock_lock_cm)

        import deskghost.main as main_mod
        result = main_mod.main()

        assert result == 0
        # The watcher must never have been constructed
        watcher_cls.assert_not_called()

    def test_watcher_started_when_lock_acquired(self, fake_watcher, mocker, patch_instance_lock):
        """main() must enter the run loop when the lock is successfully acquired."""
        _reload_main(fake_watcher, mocker, is_work=[False], is_lunch=[])
        import deskghost.main as main_mod
        main_mod.main()
        # watcher was created and cleanup was called — proves _run() was entered
        assert fake_watcher.cleanup_calls == 1
