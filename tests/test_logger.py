"""Tests for deskghost.logger."""

import logging

import pytest

from deskghost.logger import LOG_INTERVAL_SECONDS, ThrottledLogger, get_logger


# ---------------------------------------------------------------------------
# get_logger
# ---------------------------------------------------------------------------

class TestGetLogger:
    def test_get_logger_returns_logger(self):
        logger = get_logger()
        assert isinstance(logger, logging.Logger)

    def test_get_logger_has_one_handler(self):
        # Reset handlers to simulate fresh call
        logging.getLogger("deskghost").handlers.clear()
        logger = get_logger()
        assert len(logger.handlers) == 1

    def test_get_logger_no_duplicate_handlers_on_repeated_calls(self):
        logging.getLogger("deskghost").handlers.clear()
        get_logger()
        get_logger()
        assert len(get_logger().handlers) == 1

    def test_get_logger_level_is_info(self):
        logging.getLogger("deskghost").handlers.clear()
        logger = get_logger()
        assert logger.level == logging.INFO

    def test_get_logger_handler_is_stream_handler(self):
        logging.getLogger("deskghost").handlers.clear()
        logger = get_logger()
        assert isinstance(logger.handlers[0], logging.StreamHandler)

    def test_get_logger_custom_name(self):
        logger = get_logger("deskghost.test_custom")
        assert logger.name == "deskghost.test_custom"


# ---------------------------------------------------------------------------
# ThrottledLogger
# ---------------------------------------------------------------------------

class TestThrottledLogger:
    def test_info_emits_on_first_call(self, mocker):
        mock_log = mocker.patch("deskghost.logger.get_logger")
        mock_logger = mocker.MagicMock()
        mock_log.return_value = mock_logger

        t = ThrottledLogger(interval=60)
        t.info("key1", "hello")

        mock_logger.info.assert_called_once_with("hello")

    def test_info_suppresses_second_call_within_interval(self, mocker):
        mock_log = mocker.patch("deskghost.logger.get_logger")
        mock_logger = mocker.MagicMock()
        mock_log.return_value = mock_logger
        mocker.patch("time.time", side_effect=[1000.0, 1030.0])

        t = ThrottledLogger(interval=60)
        t.info("key1", "first")
        t.info("key1", "second — should be suppressed")

        mock_logger.info.assert_called_once_with("first")

    def test_info_emits_again_after_interval_elapses(self, mocker):
        mock_log = mocker.patch("deskghost.logger.get_logger")
        mock_logger = mocker.MagicMock()
        mock_log.return_value = mock_logger
        # Each info() call reads time.time() once for `now`.
        # First call at t=1000 (emits), second at t=1061 > interval (emits again).
        mocker.patch("time.time", side_effect=[1000.0, 1061.0])

        t = ThrottledLogger(interval=60)
        t.info("key1", "first")
        t.info("key1", "second — should emit")

        assert mock_logger.info.call_count == 2

    def test_info_different_keys_are_independent(self, mocker):
        mock_log = mocker.patch("deskghost.logger.get_logger")
        mock_logger = mocker.MagicMock()
        mock_log.return_value = mock_logger
        mocker.patch("time.time", return_value=1000.0)

        t = ThrottledLogger(interval=60)
        t.info("key_a", "message a")
        t.info("key_b", "message b")

        assert mock_logger.info.call_count == 2

    def test_info_same_key_within_interval_only_emits_once(self, mocker):
        mock_log = mocker.patch("deskghost.logger.get_logger")
        mock_logger = mocker.MagicMock()
        mock_log.return_value = mock_logger
        mocker.patch("time.time", return_value=1000.0)

        t = ThrottledLogger(interval=60)
        for _ in range(5):
            t.info("repeat", "msg")

        mock_logger.info.assert_called_once()

    def test_default_interval_matches_module_constant(self):
        t = ThrottledLogger()
        assert t._interval == LOG_INTERVAL_SECONDS
